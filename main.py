import json
import queue
import time
from pathlib import Path

import cv2
import mediapipe as mp
import pyautogui
import sounddevice as sd
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from vosk import KaldiRecognizer, Model, SetLogLevel

from controls import GestureTrigger, NAMES, VOICE_KEYS, VOICE_PHRASES, classify_hand, voice_commands
from integration.gsi import GSIState, start_server
from spell_planner import plan_spell
from whisper_capture import PhraseCapture

ROOT = Path(__file__).resolve().parent
FONT_PATH = '/System/Library/Fonts/Supplemental/Arial.ttf'
HINTS = [
    'Q  Куас — указательный',
    'W  Векс — указательный + средний',
    'E  Экзорт — большой + указательный в кольцо',
    'R  Инвоук — указательный + мизинец',
    'D  Первый — большой палец вверх',
    'F  Второй — большой палец вниз',
    'Стоп — выключить ввод',
]


def draw_hints(frame, font):
    height, width = frame.shape[:2]
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert('RGBA')
    overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    spacing = max(19, min(27, height // 18))
    top = max(140, height - spacing * len(HINTS) - 42)
    if top + spacing * len(HINTS) + 8 > height - 25:
        top = max(0, height - spacing * len(HINTS) - 28)
    panel_width = min(width - 8, max(int(draw.textlength(line, font=font)) for line in HINTS) + 24)
    draw.rounded_rectangle((4, top, panel_width, top + spacing * len(HINTS) + 8), radius=8, fill=(0, 0, 0, 190))
    for index, line in enumerate(HINTS):
        draw.text((12, top + 4 + index * spacing), line, font=font, fill=(255, 255, 255, 255))
    image = Image.alpha_composite(image, overlay).convert('RGB')
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def main():
    audio = queue.Queue(maxsize=32)
    overflow = False

    def callback(indata, frames, time_info, status):
        nonlocal overflow
        if status:
            overflow = True
        try:
            audio.put_nowait(bytes(indata))
        except queue.Full:
            overflow = True

    camera = None
    gsi_server = None
    enabled = False
    trigger = GestureTrigger()
    message = ''
    message_until = 0.0
    capture = None
    pending = None
    awaiting = None

    def send(key, source):
        nonlocal enabled, message, message_until
        try:
            pyautogui.press(key)
            message = f'{source}: {NAMES[key]} [{key.upper()}]'
            message_until = time.monotonic() + 1.5
            print(message, flush=True)
        except Exception as error:
            enabled = False
            trigger.reset()
            print('Ввод отключён из-за ошибки:', error, flush=True)

    try:
        gsi = GSIState()
        gsi_server = start_server(gsi)
        print('GSI запущен: ожидание данных Dota 2 на 127.0.0.1:38742.', flush=True)
        hint_font = ImageFont.truetype(FONT_PATH, 15)
        device = sd.query_devices(kind='input')
        rate = int(device['default_samplerate'])
        capture = PhraseCapture(rate)
        SetLogLevel(-1)
        model = Model(str(ROOT / 'models/vosk-model-small-ru-0.22'))
        vocabulary = [word for word in VOICE_KEYS if model.vosk_model_find_word(word) >= 0]
        vocabulary += list(VOICE_PHRASES) + ['стоп', '[unk]']
        recognizer = KaldiRecognizer(model, rate, json.dumps(vocabulary, ensure_ascii=False))
        options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(ROOT / 'models/hand_landmarker.task')),
            running_mode=vision.RunningMode.VIDEO, num_hands=2,
        )
        camera = cv2.VideoCapture(0)
        if not camera.isOpened():
            print('Не удалось открыть камеру. Проверьте разрешение macOS.')
            return
        with vision.HandLandmarker.create_from_options(options) as detector, sd.RawInputStream(
            samplerate=rate, blocksize=8000, dtype='int16', channels=1, callback=callback
        ):
            last_timestamp = -1
            previous_slots = None
            print('Пробел в окне камеры — вкл/выкл. Esc — выход. «Стоп» — выключить всё.')
            print('Перед первым жестом покажите раскрытую правую ладонь.')
            while True:
                # Process pending speech before permitting a gesture action.
                commands = []
                while True:
                    try:
                        chunk = audio.get_nowait()
                    except queue.Empty:
                        break
                    capture.feed(chunk)
                    if recognizer.AcceptWaveform(chunk):
                        text = json.loads(recognizer.Result()).get('text', '')
                        if text:
                            print('Речь:', text, flush=True)
                        commands.extend(voice_commands(text))
                    else:
                        partial = json.loads(recognizer.PartialResult()).get('partial', '')
                        if 'стоп' in partial.split():
                            commands.append('stop')
                if overflow or 'stop' in commands:
                    enabled = False
                    trigger.reset()
                    capture.cancel()
                    pending = None
                    awaiting = None
                    message = 'INPUT OFF'
                    message_until = time.monotonic() + 1.5
                    if overflow:
                        recognizer.Reset()
                        print('Ввод отключён: потеря аудиоданных.', flush=True)
                        overflow = False
                elif enabled and not (capture.recording or capture.busy or pending or awaiting):
                    for command in commands:
                        if enabled:
                            send(command, 'VOICE')
                while True:
                    try:
                        token, transcript, error = capture.results.get_nowait()
                    except queue.Empty:
                        break
                    if token != capture.token or not enabled:
                        continue
                    if error:
                        print('Ошибка Whisper:', error, flush=True)
                        continue
                    print('Whisper:', transcript, flush=True)
                    plan = plan_spell(transcript, gsi.snapshot())
                    if plan is None or pending or awaiting:
                        print('Команда не распознана или GSI недоступен.', flush=True)
                        continue
                    print(f'План: {plan.kind} {plan.spell} ({plan.score:.0%})', flush=True)
                    if plan.kind == 'prepare':
                        pending = {'keys': list(plan.keys), 'spell': plan.spell, 'next': time.monotonic()}
                    else:
                        send(plan.keys, 'VOICE')
                now = time.monotonic()
                if pending and enabled and now >= pending['next']:
                    if gsi.snapshot(max_age=2) is None:
                        print('Подготовка отменена: нет свежих данных GSI.', flush=True)
                        pending = None
                    else:
                        key = pending['keys'].pop(0)
                        send(key, 'VOICE')
                        if not enabled:
                            pending = None
                        elif not pending['keys']:
                            awaiting = {'spell': pending['spell'], 'deadline': now + 4}
                            pending = None
                        else:
                            pending['next'] = now + 0.2
                if awaiting:
                    expected = 'invoker_' + awaiting['spell'].replace(' ', '_')
                    current = gsi.snapshot(max_age=2)
                    if current and expected in current:
                        print('GSI подтвердил подготовку:', awaiting['spell'], flush=True)
                        awaiting = None
                    elif now > awaiting['deadline']:
                        print('GSI не подтвердил подготовку; проверьте игру.', flush=True)
                        awaiting = None
                ok, frame = camera.read()
                if not ok:
                    print('Не удалось получить кадр.')
                    break
                frame = cv2.flip(frame, 1)
                height, width = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                timestamp = max(time.monotonic_ns() // 1_000_000, last_timestamp + 1)
                last_timestamp = timestamp
                result = detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp)
                gesture = None
                for hand, handedness in zip(result.hand_landmarks, result.handedness):
                    if handedness[0].category_name != 'Right' or handedness[0].score < 0.75:
                        continue
                    gesture = classify_hand(hand, width, height)
                    points = [(int(p.x * width), int(p.y * height)) for p in hand]
                    for c in vision.HandLandmarksConnections.HAND_CONNECTIONS:
                        cv2.line(frame, points[c.start], points[c.end], (0, 220, 0), 2)
                    for point in points:
                        cv2.circle(frame, point, 4, (0, 100, 255), -1)
                    break
                if enabled and not (capture.recording or capture.busy or pending or awaiting):
                    action = trigger.update(gesture, time.monotonic())
                    if action:
                        send(action, 'HAND')
                color = (0, 255, 100) if enabled else (0, 100, 255)
                slots = gsi.snapshot()
                if slots != previous_slots:
                    print('GSI D/F:', ' / '.join(slots) if slots else 'данные недоступны', flush=True)
                    previous_slots = slots
                if slots:
                    labels = [name.removeprefix('invoker_').replace('_', ' ').upper() for name in slots]
                    cv2.putText(frame, f'D: {labels[0]}  F: {labels[1]}', (20, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
                else:
                    cv2.putText(frame, 'GSI: WAITING / NO INVOKER', (20, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 180, 255), 2)
                status = 'INPUT ON' if enabled else 'INPUT OFF'
                cv2.putText(frame, status, (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                detected = NAMES.get(gesture, gesture or 'no right hand')
                cv2.putText(frame, f'Hand: {detected}', (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                if enabled and not trigger.ready:
                    cv2.putText(frame, 'Show open RIGHT palm to arm gestures', (20, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1)
                if time.monotonic() < message_until:
                    cv2.putText(frame, message, (20, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                cv2.putText(frame, 'SPACE: toggle | ESC: quit', (20, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                cv2.putText(frame, 'V: record phrase' + (' (recording)' if capture.recording else ' (processing)' if capture.busy else ''), (20, 190), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
                frame = draw_hints(frame, hint_font)
                cv2.imshow('DOTA MAGIC', frame)
                key = cv2.waitKey(1) & 0xff
                if key == 27:
                    break
                if key == ord(' '):
                    enabled = not enabled
                    trigger.reset()
                    capture.cancel()
                    pending = None
                    awaiting = None
                    recognizer.Reset()
                    while not audio.empty():
                        try:
                            audio.get_nowait()
                        except queue.Empty:
                            break
                    print('Ввод включён.' if enabled else 'Ввод выключен.', flush=True)
                if key == ord('v') and enabled and not pending and not awaiting:
                    if capture.start():
                        print('Запись фразы: говорите 4 секунды.', flush=True)
    except Exception as error:
        print('Ошибка камеры, микрофона или модели:', error)
        print('Если порт GSI занят, закройте inspect_gsi.py и перезапустите программу.')
    finally:
        if gsi_server is not None:
            gsi_server.shutdown()
            gsi_server.server_close()
        if camera is not None:
            camera.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()

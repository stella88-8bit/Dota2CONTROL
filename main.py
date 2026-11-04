import json
import queue
import time
from pathlib import Path

import cv2
import mediapipe as mp
import sounddevice as sd
import pyautogui
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from vosk import KaldiRecognizer, Model, SetLogLevel

from hand_tracking import fingers_touch

ROOT = Path(__file__).resolve().parent


def main():
    audio = queue.Queue(maxsize=32)

    def callback(indata, frames, time_info, status):
        if status:
            print('Микрофон:', status, flush=True)
        try:
            audio.put_nowait(bytes(indata))
        except queue.Full:
            pass

    camera = None
    try:
        device = sd.query_devices(kind='input')
        rate = int(device['default_samplerate'])
        SetLogLevel(-1)
        recognizer = KaldiRecognizer(Model(str(ROOT / 'models/vosk-model-small-ru-0.22')), rate)
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
            enabled = False
            touch_since = None
            triggered = False
            message_until = 0.0
            last_timestamp = -1
            print('Скажите «стоп» для отключения жестов. R — включить, Q — выход.')
            while True:
                while True:
                    try:
                        chunk = audio.get_nowait()
                    except queue.Empty:
                        break
                    if recognizer.AcceptWaveform(chunk):
                        words = json.loads(recognizer.Result()).get('text', '').split()
                        if 'стоп' in words:
                            enabled = False
                            touch_since = None
                            triggered = False
                            message_until = 0.0
                            print('Жесты выключены голосом.', flush=True)
                ok, frame = camera.read()
                if not ok:
                    print('Не удалось получить кадр.')
                    break
                frame = cv2.flip(frame, 1)
                height, width = frame.shape[:2]
                if enabled:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    timestamp = max(time.monotonic_ns() // 1_000_000, last_timestamp + 1)
                    last_timestamp = timestamp
                    result = detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp)
                    touching = any(fingers_touch(hand, width, height) for hand in result.hand_landmarks)
                    if touching:
                        if touch_since is None:
                            touch_since = time.monotonic()
                        if not triggered and time.monotonic() - touch_since >= 0.3:
                            triggered = True
                            try:
                                pyautogui.press('q')
                                message_until = time.monotonic() + 1.0
                                print('ОТПРАВЛЕНО: Q', flush=True)
                            except Exception as error:
                                enabled = False
                                print('Ошибка отправки клавиши:', error, flush=True)
                    else:
                        touch_since = None
                        triggered = False
                    if time.monotonic() < message_until:
                        cv2.putText(frame, 'ACTION: Q', (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 100), 2)
                    for hand in result.hand_landmarks:
                        points = [(int(p.x * width), int(p.y * height)) for p in hand]
                        for c in vision.HandLandmarksConnections.HAND_CONNECTIONS:
                            cv2.line(frame, points[c.start], points[c.end], (0, 220, 0), 2)
                        for point in points:
                            cv2.circle(frame, point, 4, (0, 100, 255), -1)
                status = 'GESTURES ON' if enabled else 'GESTURES OFF - press R'
                cv2.putText(frame, status, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 100) if enabled else (0, 100, 255), 2)
                cv2.putText(frame, 'Q: quit', (20, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                cv2.imshow('DOTA MAGIC', frame)
                key = cv2.waitKey(1) & 0xff
                if key == ord('q'):
                    break
                if key == ord('r'):
                    enabled = True
                    touch_since = None
                    triggered = True
                    print('Жесты включены.', flush=True)
    except Exception as error:
        print('Ошибка запуска камеры, микрофона или модели:', error)
    finally:
        if camera is not None:
            camera.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()

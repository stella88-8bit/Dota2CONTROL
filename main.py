"""DOTA MAGIC: voice-only control with local game-state integration."""
import json
import queue
import re
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import pyautogui
import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel

from controls import NAMES, VOICE_KEYS, VOICE_PHRASES, voice_commands
from integration.gsi import GSIState, start_server
from spell_planner import plan_spell, slot_for_spell
from whisper_capture import PhraseCapture
from voice_policy import is_stop_result
from laughter import LaughterDetector, LaughterPlayer
from combos import match_combo
from combo_runner import ComboRunner

ROOT = Path(__file__).resolve().parent


def main():
    audio = queue.Queue(maxsize=64)
    state = {'enabled': False, 'overflow': False, 'pending': None, 'awaiting': None, 'combo': None, 'playback': False, 'enabled_at': 0.0}
    gsi = GSIState()
    server = capture = stream = laughter = player = None
    root = tk.Tk()
    root.title('DOTA MAGIC — голосовое управление')
    root.geometry('620x340')
    status = tk.StringVar(value='Ввод выключен')
    slots_text = tk.StringVar(value='GSI: ожидание данных Invoker')
    voice_text = tk.StringVar(value='Голосовая модель загружается')
    last_text = tk.StringVar(value='Ожидание команды')
    ttk.Label(root, text='DOTA MAGIC', font=('Arial', 22, 'bold')).pack(pady=12)
    ttk.Label(root, textvariable=status, font=('Arial', 15, 'bold')).pack(pady=5)
    ttk.Label(root, textvariable=slots_text).pack(pady=5)
    ttk.Label(root, textvariable=voice_text).pack(pady=5)
    ttk.Label(root, textvariable=last_text, wraplength=580).pack(pady=5)
    buttons = ttk.Frame(root)
    buttons.pack(pady=10)

    def disable(reason='Ввод выключен'):
        state.update(enabled=False, pending=None, awaiting=None, combo=None)
        if capture:
            capture.cancel()
        status.set(reason)
        print(reason, flush=True)

    def enable():
        if not capture.ready:
            status.set('Модель ещё загружается или недоступна')
            return
        disable('Подготовка к запуску')
        recognizer.Reset()
        while not audio.empty():
            try: audio.get_nowait()
            except queue.Empty: break
        state['enabled'] = True
        state['enabled_at'] = time.monotonic()
        status.set('Ввод включён — переключись в Dota')
        print('Ввод включён.', flush=True)

    ttk.Button(buttons, text='Включить', command=enable).pack(side='left', padx=8)
    ttk.Button(buttons, text='СТОП', command=lambda: disable('Остановлено кнопкой')).pack(side='left', padx=8)
    ttk.Label(root, text='Скажи «стоп», чтобы выключить управление.').pack(pady=5)

    def callback(indata, frames, time_info, flags):
        if flags: state['overflow'] = True
        data = bytes(indata)
        try: audio.put_nowait(data)
        except queue.Full: state['overflow'] = True
        if state['enabled'] and capture and not state['playback']:
            capture.feed(data)
        if laughter:
            laughter.feed(data if state['enabled'] and not state['playback'] else bytes(len(data)))

    def send(key, self_target=False):
        try:
            if self_target:
                pyautogui.hotkey('alt', key)
            else:
                pyautogui.press(key)
            last_text.set(f'Отправлено: {NAMES[key]} [{key.upper()}]')
            print('VOICE:', key.upper(), flush=True)
        except Exception as exc:
            disable('Ошибка ввода: ' + str(exc))

    def tick():
        if player:
            state['playback'] = player.is_playing()
        if laughter:
            while True:
                try: detected_at = laughter.events.get_nowait()
                except queue.Empty: break
                if state['enabled'] and not state['combo'] and detected_at >= state['enabled_at'] and time.monotonic() - detected_at < 2:
                    try:
                        chosen = player.play()
                        if chosen:
                            state['playback'] = True
                            capture.cancel()
                            last_text.set('Смех: воспроизводится реплика Invoker')
                            print('Реплика Invoker:', chosen, flush=True)
                    except OSError as error:
                        print('Не удалось воспроизвести реплику:', error, flush=True)
        commands = []
        while True:
            try: chunk = audio.get_nowait()
            except queue.Empty: break
            if recognizer.AcceptWaveform(chunk):
                result = json.loads(recognizer.Result())
                if is_stop_result(result):
                    commands.append('stop')
        if state['overflow']:
            state['overflow'] = False
            recognizer.Reset()
            capture.cancel()
            state.update(pending=None, awaiting=None, combo=None)
            last_text.set('Сбой аудио: действие отменено, слушаю следующую команду')
            print('Аудио восстановлено; ввод остаётся включённым.', flush=True)
        if 'stop' in commands and state['enabled']:
            disable('Остановлено командой «стоп»')
        pending, awaiting = state['pending'], state['awaiting']
        while not pending and not awaiting and not state['combo']:
            try: token, text, error, received = capture.results.get_nowait()
            except queue.Empty: break
            if token != capture.token or not state['enabled'] or time.monotonic() - received > 1:
                continue
            if error:
                last_text.set('Распознавание восстанавливается: ' + error)
                print('Ошибка Whisper, ожидаю следующую команду:', error, flush=True)
                continue
            print('Whisper:', text, flush=True)
            normalized = ' '.join(re.sub(r'[^\w\s]', ' ', text.lower()).split())
            if normalized == 'стоп':
                disable('Остановлено командой «стоп»')
                break
            combo_match = match_combo(text)
            if combo_match:
                if not gsi.details():
                    last_text.set('Прокаст отменён: нет свежих данных GSI')
                    continue
                state['combo'] = ComboRunner(combo_match[1], time.monotonic())
                last_text.set('Прокаст: ' + combo_match[0])
                print('Прокаст:', combo_match[0], flush=True)
                break
            direct = {**VOICE_KEYS, **VOICE_PHRASES}.get(normalized)
            if direct:
                send(direct)
                continue
            plan = plan_spell(text, gsi.snapshot(max_age=2))
            if not plan:
                last_text.set('Фраза не распознана или нет свежих данных GSI')
                continue
            last_text.set(f'{plan.kind}: {plan.spell} ({plan.score:.0%})')
            print('План:', plan, flush=True)
            if plan.kind == 'prepare':
                pending = {'keys': list(plan.keys), 'spell': plan.spell, 'next': time.monotonic(), 'recognized_at': received}
                state['pending'] = pending
            else:
                send(plan.keys)
        now = time.monotonic()
        combo = state['combo']
        if combo and state['enabled']:
            action = combo.step(now, gsi.details(max_age=2, after=combo.after))
            if action:
                print('Прокаст:', combo.spells[combo.index], '→', action, flush=True)
                send(action[0], action[1])
            if combo.error:
                last_text.set('Прокаст остановлен: ' + combo.error)
                print('Прокаст остановлен:', combo.error, flush=True)
                state['combo'] = None
            elif combo.complete:
                last_text.set('Прокаст завершён')
                print('Прокаст завершён.', flush=True)
                state['combo'] = None
        if pending and state['enabled'] and now >= pending['next']:
            if gsi.snapshot(max_age=2) is None:
                state['pending'] = None
                last_text.set('Нет GSI — подготовка отменена, слушаю дальше')
            else:
                key = pending['keys'].pop(0)
                send(key)
                if state['enabled']:
                    if pending['keys']:
                        pending['next'] = time.monotonic() + .08
                    else:
                        state['pending'] = None
                        sent_at = time.monotonic()
                        state['awaiting'] = {'spell': pending['spell'], 'sent_at': sent_at, 'deadline': sent_at + 4, 'recognized_at': pending['recognized_at']}
        awaiting = state['awaiting']
        if awaiting:
            current = gsi.snapshot(max_age=2, after=awaiting['sent_at'])
            slot = slot_for_spell(awaiting['spell'], current)
            if now <= awaiting['deadline'] and slot and state['enabled']:
                state['awaiting'] = None
                print('GSI подтвердил:', awaiting['spell'], '— применение', slot.upper(), flush=True)
                confirmed_at = time.monotonic()
                print(f'Время отправки сфер и Invoke: {awaiting["sent_at"] - awaiting["recognized_at"]:.2f} с; ожидание GSI после Invoke: {confirmed_at - awaiting["sent_at"]:.2f} с', flush=True)
                send(slot)
            elif now > awaiting['deadline']:
                last_text.set('GSI не подтвердил подготовку')
                state['awaiting'] = None
        slots = gsi.snapshot()
        slots_text.set(f'D: {slots[0]} | F: {slots[1]}' if slots else 'GSI: ожидание данных Invoker')
        voice_text.set(('Голос готов' if capture.ready else 'Голосовая модель загружается') + f' | уровень {capture.level:.3f} | пропущено {capture.dropped}')
        root.after(10, tick)

    try:
        server = start_server(gsi)
        device = sd.query_devices(kind='input')
        rate = int(device['default_samplerate'])
        capture = PhraseCapture(rate)
        try:
            laughter = LaughterDetector(rate)
            player = LaughterPlayer()
        except (OSError, ValueError) as error:
            print('Детектор смеха недоступен:', error, flush=True)
        SetLogLevel(-1)
        model = Model(str(ROOT / 'models/vosk-model-small-ru-0.22'))
        # A restricted grammar could force unrelated speech into "стоп".
        recognizer = KaldiRecognizer(model, rate)
        recognizer.SetWords(True)
        pyautogui.PAUSE = .01
        stream = sd.RawInputStream(samplerate=rate, blocksize=1024, dtype='int16', channels=1, callback=callback)
        stream.start()
        root.after(10, tick)
        root.mainloop()
    finally:
        if stream: stream.stop(); stream.close()
        if laughter: laughter.close()
        if player: player.close()
        if capture: capture.close()
        if server: server.shutdown(); server.server_close()


if __name__ == '__main__':
    main()

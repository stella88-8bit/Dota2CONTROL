"""DOTA MAGIC: UI observes voice control; it never schedules gameplay input."""
import queue
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import pyautogui
import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel

from integration.gsi import GSIState, start_server
from whisper_capture import PhraseCapture
from laughter import LaughterDetector, LaughterPlayer
from voice_controller import VoiceController
from voice_stop import StopListener

ROOT = Path(__file__).resolve().parent


def main():
    gsi = GSIState()
    server = capture = stream = laughter = player = controller = stop_listener = None
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
    ttk.Button(buttons, text='Включить', command=lambda: controller.enable()).pack(side='left', padx=8)
    ttk.Button(buttons, text='СТОП', command=lambda: controller.disable()).pack(side='left', padx=8)
    ttk.Label(root, text='Скажи «стоп», чтобы выключить управление.').pack(pady=5)

    def callback(indata, frames, time_info, flags):
        if not controller.enabled:
            return
        token = capture.token
        if flags:
            controller.audio_error(token)
        data = bytes(indata)
        stop_listener.feed(token, data)
        if not controller.playback:
            capture.feed(data)
        if laughter:
            laughter.feed(data if not controller.playback else bytes(len(data)))

    def send(key, self_target=False):
        if self_target:
            pyautogui.hotkey('alt', key)
        else:
            pyautogui.press(key)

    def refresh():
        # Rendering or a slow terminal cannot hold up the spell-control thread.
        for _ in range(100):
            try:
                kind, text = controller.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                print(text, flush=True)
            elif kind == 'status':
                status.set(text)
            elif kind == 'last':
                last_text.set(text)
        slots = gsi.snapshot()
        slots_text.set(f'D: {slots[0]} | F: {slots[1]}' if slots else 'GSI: ожидание данных Invoker')
        voice_text.set(('Голос готов' if capture.ready else 'Голосовая модель загружается')
                       + f' | уровень {capture.level:.3f} | пропущено {capture.dropped}')
        root.after(50, refresh)

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
        recognizer = KaldiRecognizer(model, rate)
        recognizer.SetWords(True)
        pyautogui.PAUSE = 0
        pyautogui.DARWIN_CATCH_UP_TIME = .005
        controller = VoiceController(gsi, capture, send, laughter, player)
        stop_listener = StopListener(
            recognizer,
            lambda token: controller.disable('Остановлено командой «стоп»', token),
            controller.audio_error)
        stream = sd.RawInputStream(samplerate=rate, blocksize=1024, dtype='int16', channels=1, callback=callback)
        stream.start()
        root.after(50, refresh)
        root.mainloop()
    finally:
        if stream:
            stream.stop()
            stream.close()
        if stop_listener:
            stop_listener.close()
        if controller:
            controller.close()
        if laughter:
            laughter.close()
        if player:
            player.close()
        if capture:
            capture.close()
        if server:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()

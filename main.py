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
from invoker_database import SpellDatabase, ensure_database

ROOT = Path(__file__).resolve().parent


def main():
    gsi = GSIState()
    server = capture = stream = laughter = player = controller = stop_listener = None
    root = tk.Tk()
    root.title('DOTA MAGIC — голосовое управление')
    root.geometry('660x520')
    status = tk.StringVar(value='Ввод выключен')
    slots_text = tk.StringVar(value='GSI: ожидание данных Invoker')
    voice_text = tk.StringVar(value='Голосовая модель загружается')
    last_text = tk.StringVar(value='Ожидание команды')
    levels_text = tk.StringVar(value='Уровни Invoker: ожидание GSI')
    ttk.Label(root, text='DOTA MAGIC', font=('Arial', 22, 'bold')).pack(pady=12)
    ttk.Label(root, textvariable=status, font=('Arial', 15, 'bold')).pack(pady=5)
    ttk.Label(root, textvariable=slots_text).pack(pady=5)
    ttk.Label(root, textvariable=voice_text).pack(pady=5)
    ttk.Label(root, textvariable=last_text, wraplength=580).pack(pady=5)
    ttk.Label(root, textvariable=levels_text).pack(pady=3)
    distance = tk.DoubleVar(value=600)
    distance_text = tk.StringVar(value='Расстояние до цели: примерно 600 ед.')
    scepter_choice = tk.StringVar(value='Авто')
    shard_choice = tk.StringVar(value='Авто')
    require_window = tk.BooleanVar(value=True)
    choices = {'Авто': None, 'Quas': 1, 'Wex': 2, 'Exort': 3}

    def update_timing(*_):
        value = round(distance.get()/25)*25
        distance_text.set(f'Расстояние до цели: примерно {value:g} ед.')
        if controller:
            controller.set_timing_options(value, choices[scepter_choice.get()], choices[shard_choice.get()],require_window.get())

    ttk.Label(root, textvariable=distance_text).pack(pady=2)
    ttk.Scale(root, from_=0, to=1200, variable=distance, command=update_timing).pack(fill='x', padx=55)
    upgrades = ttk.Frame(root)
    upgrades.pack(pady=6)
    ttk.Label(upgrades, text='Выбранный в игре Scepter:').pack(side='left')
    scepter_box = ttk.Combobox(upgrades, textvariable=scepter_choice, values=list(choices), width=7, state='readonly')
    scepter_box.pack(side='left', padx=5)
    ttk.Label(upgrades, text='Shard:').pack(side='left')
    shard_box = ttk.Combobox(upgrades, textvariable=shard_choice, values=list(choices), width=7, state='readonly')
    shard_box.pack(side='left', padx=5)
    for box in (scepter_box, shard_box):
        box.bind('<<ComboboxSelected>>', update_timing)
    ttk.Checkbutton(root,text='Требовать общее окно попадания после Tornado',variable=require_window,command=update_timing).pack(pady=3)
    ttk.Label(root, text='GSI не сообщает положение врага. Укажи дистанцию и наведи курсор на цель.', wraplength=600).pack(pady=5)
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
        hero, abilities, _ = gsi.read_context(max_age=5)
        if hero and abilities:
            ranks = [abilities.get('ability'+str(i),{}).get('level','?') for i in range(3)]
            levels_text.set(f'Invoker {hero.get("level", "?")} | Quas {ranks[0]} · Wex {ranks[1]} · Exort {ranks[2]}')
        else:
            levels_text.set('Уровни Invoker: ожидание GSI')
        root.after(50, refresh)

    try:
        database = SpellDatabase(ensure_database())
        print('База Invoker: ' + database.metadata['source_sha256'][:12] + ' (данные установленной игры)', flush=True)
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
        controller = VoiceController(gsi, capture, send, laughter, player, spell_database=database)
        update_timing()
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

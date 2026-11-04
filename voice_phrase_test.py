"""Manual phrase recognition test. Does not send keys or control the game."""
import difflib
import re
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
import wave

import sounddevice as sd
from spell_phrases import SPELLS, INVOKE_PHRASE, match_phrase
from spell_planner import plan_spell
from integration.gsi import GSIState, start_server

ROOT = Path(__file__).resolve().parent
CLI = ROOT / 'integration' / 'whisper-bin' / 'whisper-cli'
MODEL = ROOT / 'models' / 'ggml-small-q5_1.bin'
PHRASES = list(SPELLS) + [INVOKE_PHRASE]


def normalize(text):
    return ' '.join(re.sub(r'[^\w\s]', ' ', text.lower().replace('ё', 'е')).split())


def main():
    gsi = GSIState()
    try:
        server = start_server(gsi)
    except OSError:
        server = None
        print('GSI недоступен: останови main.py и inspect_gsi.py.', flush=True)
    window = tk.Tk()
    window.title('DOTA MAGIC — проверка фраз')
    window.geometry('720x480')
    selected = tk.StringVar(value=PHRASES[0])
    status = tk.StringVar(value='Выбери фразу и нажми «Записать».')
    result = tk.StringVar(value='Распознанный текст появится здесь.')
    ttk.Label(window, text='Проверка голосовых фраз Invoker', font=('Arial', 20, 'bold')).pack(pady=15)
    ttk.Label(window, text='Выбери фразу, нажми кнопку и произнеси её за 5 секунд.').pack()
    chooser = ttk.Combobox(window, textvariable=selected, values=PHRASES, state='readonly', width=50)
    chooser.pack(pady=15)
    ttk.Label(window, textvariable=status, wraplength=680).pack(pady=10)
    ttk.Label(window, textvariable=result, wraplength=680, font=('Arial', 15)).pack(pady=12)
    ttk.Label(window, text='Это проверка: игровые клавиши не отправляются.').pack(side='bottom', pady=20)

    def start():
        target = selected.get()
        button.config(state='disabled')
        status.set('Запись: говори сейчас (5 секунд)…')
        result.set('')

        def worker():
            try:
                started = time.monotonic()
                samples = sd.rec(int(5 * 16000), samplerate=16000, channels=1, dtype='int16')
                sd.wait()
                window.after(0, lambda: status.set('Распознавание…'))
                with tempfile.TemporaryDirectory() as tmp:
                    wav = Path(tmp) / 'voice.wav'
                    with wave.open(str(wav), 'wb') as audio:
                        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
                        audio.writeframes(samples.tobytes())
                    output = str(Path(tmp) / 'result')
                    process = subprocess.run([str(CLI), '-m', str(MODEL), '-f', str(wav), '-l', 'ru', '-nt', '-otxt', '-of', output], capture_output=True, text=True, timeout=180)
                    if process.returncode:
                        raise RuntimeError(process.stderr[-700:] or 'Ошибка whisper-cli')
                    transcript = Path(output + '.txt').read_text(encoding='utf-8').strip()
                score = difflib.SequenceMatcher(None, normalize(target), normalize(transcript)).ratio()
                elapsed = time.monotonic() - started - 5
                verdict = 'Совпало точно' if normalize(target) == normalize(transcript) else 'Нужно сравнить вручную'
                name = SPELLS[target][0].upper() if target in SPELLS else 'INVOKE'
                matched, best_score = match_phrase(transcript)
                detected = SPELLS[matched][0].upper() if matched in SPELLS else ('INVOKE' if matched else 'НЕ РАСПОЗНАНО')
                plan = plan_spell(transcript, gsi.snapshot())
                print('План:', f'{plan.kind} {plan.keys}' if plan else 'нет данных GSI или совпадения', flush=True)
                description = f'Ожидается: {name}\nРаспознано: {transcript or "(нет текста)"}\nКоманда: {detected} ({best_score:.0%})\n{verdict}; сходство с выбранной фразой {score:.0%}; обработка {elapsed:.1f} с.'
                window.after(0, lambda: result.set(description))
                window.after(0, lambda: status.set('Готово. Выбери следующую фразу.'))
            except Exception as exc:
                error = str(exc)
                window.after(0, lambda: status.set('Ошибка: ' + error))
            finally:
                window.after(0, lambda: button.config(state='normal'))

        threading.Thread(target=worker, daemon=True).start()

    button = ttk.Button(window, text='Записать', command=start)
    button.pack(pady=10)
    try:
        window.mainloop()
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()

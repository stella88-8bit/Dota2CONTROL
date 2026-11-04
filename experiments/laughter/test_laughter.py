"""Record a short sample and show macOS Sound Analysis scores; no game input."""
import subprocess
import tempfile
import wave
from pathlib import Path

import sounddevice as sd


def main():
    analyzer = Path(__file__).resolve().parent / 'analyze-laughter'
    if not analyzer.exists():
        print('Сначала соберите анализатор по инструкции в README.md.')
        return
    device = sd.query_devices(kind='input')
    rate = int(device['default_samplerate'])
    print('Микрофон:', device['name'])
    input('Нажмите Enter и в течение 6 секунд посмейтесь: ')
    samples = sd.rec(int(rate * 6), samplerate=rate, channels=1, dtype='int16')
    sd.wait()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'sample.wav'
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(samples.tobytes())
        result = subprocess.run([str(analyzer), str(path)], check=False)
        if result.returncode:
            print('Анализ не удался. Проверьте сообщение выше.')
        else:
            print('Готово. Запись удалена; пришлите значения laughter и строки «Лидер».')


if __name__ == '__main__':
    main()

import json
import queue
from pathlib import Path

import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel


def main():
    model_path = Path(__file__).parent / 'models' / 'vosk-model-small-ru-0.22'
    if not model_path.exists():
        print('Модель Vosk не найдена:', model_path)
        return
    audio = queue.Queue()
    try:
        device = sd.query_devices(kind='input')
        rate = int(device['default_samplerate'])
        print('Микрофон:', device['name'])
        print('Загрузка модели...')
        SetLogLevel(-1)
        recognizer = KaldiRecognizer(Model(str(model_path)), rate)

        def callback(indata, frames, time_info, status):
            if status:
                print('Микрофон:', status)
            audio.put(bytes(indata))

        with sd.RawInputStream(samplerate=rate, blocksize=8000, dtype='int16', channels=1, callback=callback):
            print('Микрофон открыт. Скажите «стоп», затем сделайте паузу. Выход: Ctrl+C.')
            while True:
                if recognizer.AcceptWaveform(audio.get()):
                    text = json.loads(recognizer.Result()).get('text', '')
                    if text:
                        print('Распознано:', text, flush=True)
                        if 'стоп' in text.split():
                            print('КОМАНДА: СТОП', flush=True)
    except KeyboardInterrupt:
        print('\nПроверка завершена.')
    except Exception as error:
        print('Ошибка микрофона или модели:', error)
        print('Проверьте микрофон и разрешение для приложения в настройках macOS.')


if __name__ == '__main__':
    main()

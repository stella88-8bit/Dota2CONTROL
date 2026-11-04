"""Download the Whisper model used by voice_phrase_test.py."""
import hashlib
import os
from pathlib import Path
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent
DESTINATION = ROOT / 'models' / 'ggml-small-q5_1.bin'
URL = 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin'
SHA256 = 'ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb'


def digest(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


def main():
    if DESTINATION.exists():
        if digest(DESTINATION) == SHA256:
            print('Модель уже установлена и проверена:', DESTINATION)
            return
        raise SystemExit('Существующий файл модели не совпадает с контрольной суммой; он не изменён.')
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=DESTINATION.parent, prefix='.whisper-', delete=False) as stream:
            temporary = Path(stream.name)
            print('Загрузка модели (~181 МиБ)...')
            with urllib.request.urlopen(URL, timeout=60) as response:
                while chunk := response.read(1024 * 1024):
                    stream.write(chunk)
        if digest(temporary) != SHA256:
            raise ValueError('Контрольная сумма загруженной модели не совпадает.')
        # Do not replace a model created by another process while downloading.
        os.link(temporary, DESTINATION)
        print('Модель загружена и проверена:', DESTINATION)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()

"""Capture an explicitly requested audio segment and transcribe it in background."""
import queue
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
CLI = ROOT / 'integration/whisper-bin/whisper-cli'
MODEL = ROOT / 'models/ggml-small-q5_1.bin'


class PhraseCapture:
    def __init__(self, rate):
        self.rate = rate
        self.chunks = []
        self.recording = False
        self.busy = False
        self.token = 0
        self.results = queue.Queue()

    def cancel(self):
        self.token += 1
        self.recording = False
        self.chunks = []

    def start(self):
        if self.busy or self.recording:
            return False
        self.cancel()
        self.recording = True
        return True

    def feed(self, chunk):
        if not self.recording:
            return
        self.chunks.append(chunk)
        if sum(map(len, self.chunks)) < self.rate * 2 * 4:
            return
        self.recording = False
        raw = b''.join(self.chunks)
        self.chunks = []
        self.busy = True
        token = self.token
        threading.Thread(target=self._recognize, args=(raw, token), daemon=True).start()

    def _recognize(self, raw, token):
        try:
            samples = np.frombuffer(raw, dtype='<i2').astype(np.float32)
            count = int(len(samples) * 16000 / self.rate)
            samples = np.interp(np.arange(count) * self.rate / 16000, np.arange(len(samples)), samples).astype('<i2')
            with tempfile.TemporaryDirectory() as directory:
                wav = Path(directory) / 'input.wav'
                with wave.open(str(wav), 'wb') as stream:
                    stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
                    stream.writeframes(samples.tobytes())
                output = str(Path(directory) / 'out')
                run = subprocess.run([str(CLI), '-m', str(MODEL), '-f', str(wav), '-l', 'ru', '-nt', '-otxt', '-of', output], capture_output=True, text=True, timeout=120)
                if run.returncode:
                    raise RuntimeError(run.stderr[-300:])
                result = Path(output + '.txt').read_text(encoding='utf-8').strip()
            self.results.put((token, result, None))
        except Exception as exc:
            self.results.put((token, '', str(exc)))
        finally:
            self.busy = False

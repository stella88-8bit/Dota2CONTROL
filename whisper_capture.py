"""Continuous audio segmentation and one persistent Whisper worker."""
from collections import deque
import queue
import os
import struct
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / 'models/ggml-small-q5_1.bin'
WORKER = ROOT / 'integration/whisper-bin/whisper-worker'


class PhraseCapture:
    def __init__(self, rate):
        self.rate = rate
        self.token = 0
        self.recording = self.busy = False
        self.ready = False
        self.level = 0.0
        self.noise = 0.001
        self.last_timing = ''
        self.dropped = 0
        self.results = queue.Queue()
        self._audio = queue.Queue(maxsize=128)
        self._jobs = queue.Queue(maxsize=2)
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._process = None
        self._force_cpu = False
        self._reset()
        self._threads = [threading.Thread(target=self._segment, daemon=True),
                         threading.Thread(target=self._recognize, daemon=True)]
        for thread in self._threads:
            thread.start()

    def _reset(self):
        self._pre = deque(maxlen=max(1, int(self.rate * 0.2 / 1024)))
        self._chunks = []
        self._count = self._silence = self._voiced = 0
        self.recording = False

    def cancel(self):
        with self._lock:
            self.token += 1
            self._reset()

    def feed(self, chunk):
        # Called from the audio callback: do not wait for inference or camera.
        try:
            self._audio.put_nowait((self.token, chunk))
        except queue.Full:
            self.dropped += 1
            self.cancel()

    def _segment(self):
        while not self._closed.is_set():
            try:
                token, chunk = self._audio.get(timeout=0.1)
            except queue.Empty:
                continue
            with self._lock:
                if token != self.token:
                    continue
                samples = np.frombuffer(chunk, dtype='<i2').astype(np.float32) / 32768.0
                if not len(samples):
                    continue
                self.level = float(np.sqrt(np.mean(samples * samples)))
                threshold = max(0.003, self.noise * 3)
                talking = self.level > threshold
                if not talking and not self.recording:
                    self.noise = 0.98 * self.noise + 0.02 * self.level
                if not self.recording:
                    self._pre.append(chunk)
                    if not talking:
                        continue
                    self._chunks = list(self._pre)
                    self._count = sum(map(len, self._chunks)) // 2
                    self._silence = 0
                    self._voiced = len(samples)
                    self.recording = True
                    continue
                self._chunks.append(chunk)
                self._count += len(samples)
                self._voiced += len(samples) if talking else 0
                self._silence = 0 if talking else self._silence + len(samples)
                if self._count >= self.rate * 7:
                    # Never turn a truncated long speech/noise segment into a spell.
                    self.dropped += 1
                    self._reset()
                elif self._silence >= self.rate * 0.30:
                    if self._voiced >= self.rate * 0.18:
                        # Keep 100 ms of trailing silence, not the whole endpoint pause.
                        raw = b''.join(self._chunks)
                        trim = max(0, self._silence - int(self.rate * 0.1)) * 2
                        raw = raw[:-trim] if trim else raw
                        try:
                            self._jobs.put_nowait((token, raw, time.monotonic()))
                        except queue.Full:
                            self.dropped += 1
                    self._reset()

    @staticmethod
    def _read(stream, size):
        data = bytearray()
        while len(data) < size:
            part = stream.read(size - len(data))
            if not part:
                raise RuntimeError('Whisper worker завершился. Перезапустите main.py.')
            data.extend(part)
        return bytes(data)

    def _recognize(self):
        while not self._closed.is_set():
            self._recognize_once()
            if self._closed.wait(0.5):
                break

    def _recognize_once(self):
        try:
            # stderr is retained for diagnostics, never mixed with the binary protocol.
            with (ROOT / 'whisper-worker.log').open('w') as log:
                env = os.environ.copy()
                if self._force_cpu:
                    env['DOTA_WHISPER_CPU'] = '1'
                process = subprocess.Popen([str(WORKER), str(MODEL)], stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=log, env=env)
                self._process = process
                if self._closed.is_set():
                    process.terminate()
                    return
                self._read(process.stdout, 4)
                self.ready = True
                while not self._closed.is_set():
                    try:
                        token, raw, ended = self._jobs.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if token != self.token or time.monotonic() - ended > 2:
                        self.dropped += 1
                        continue
                    self.busy = True
                    started = time.monotonic()
                    samples = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768.0
                    count = int(len(samples) * 16000 / self.rate)
                    pcm = np.interp(np.arange(count) * self.rate / 16000,
                                    np.arange(len(samples)), samples).astype('<f4')
                    process.stdin.write(struct.pack('<I', len(pcm)) + pcm.tobytes())
                    process.stdin.flush()
                    length = struct.unpack('<I', self._read(process.stdout, 4))[0]
                    if length > 100000:
                        raise RuntimeError('Некорректный ответ Whisper worker')
                    text = self._read(process.stdout, length).decode('utf-8').strip()
                    done = time.monotonic()
                    self.last_timing = f'ASR {done-started:.2f}s; after speech ~{done-ended+0.30:.2f}s'
                    # Old/cancelled results must never produce delayed game actions.
                    if token == self.token and done - ended < 3:
                        self.results.put((token, text, None, done))
                        print('VOICE timing:', self.last_timing, flush=True)
                    else:
                        self.dropped += 1
                    self.busy = False
        except Exception as exc:
            if not self._closed.is_set():
                self._force_cpu = True
                self.results.put((self.token, '', str(exc), time.monotonic()))
        finally:
            self.busy = self.ready = False
            if self._process and self._process.poll() is None:
                self._process.terminate()
                self._process.wait(timeout=5)

    def close(self):
        self.cancel()
        self._closed.set()
        if self._process and self._process.poll() is None:
            self._process.terminate()
        for thread in self._threads:
            thread.join(timeout=2)

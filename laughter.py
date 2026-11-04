"""Local laughter detection and playback of user-installed game audio."""
from pathlib import Path
import queue
import random
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parent / 'experiments' / 'laughter'


class LaughterDetector:
    def __init__(self, rate):
        self.audio = queue.Queue(maxsize=128)
        self.events = queue.Queue(maxsize=4)
        self.closed = threading.Event()
        self.process = subprocess.Popen([str(ROOT / 'stream-laughter'), str(rate)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0)
        self.threads = [threading.Thread(target=self._write, daemon=True),
                        threading.Thread(target=self._read, daemon=True)]
        for thread in self.threads:
            thread.start()

    def feed(self, data):
        try: self.audio.put_nowait(data)
        except queue.Full: pass

    def _write(self):
        while not self.closed.is_set():
            try: data = self.audio.get(timeout=.1)
            except queue.Empty: continue
            try:
                view = memoryview(data)
                while view:
                    written = self.process.stdin.write(view)
                    if not written: return
                    view = view[written:]
            except (BrokenPipeError, OSError, ValueError): return

    def _read(self):
        try:
            for line in self.process.stdout:
                if line.startswith(b'LAUGH '):
                    try: self.events.put_nowait(time.monotonic())
                    except queue.Full: pass
        except (OSError, ValueError): pass

    def close(self):
        self.closed.set()
        if self.process.poll() is None:
            self.process.terminate()
        try: self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
        for thread in self.threads: thread.join(timeout=1)
        self.process.stdin.close()
        self.process.stdout.close()


class LaughterPlayer:
    def __init__(self, cooldown=20):
        self.paths = [ROOT / 'voices' / name for name in ('laugh.mp3', 'knowing.mp3', 'carl.mp3')]
        self.cooldown = cooldown
        self.last = float('-inf')
        self.process = None
        self.muted_until = 0.0

    def is_playing(self):
        if self.process and self.process.poll() is None:
            return True
        if self.process:
            self.process = None
            self.muted_until = time.monotonic() + 1
        return time.monotonic() < self.muted_until

    def play(self):
        now = time.monotonic()
        if now - self.last < self.cooldown or self.is_playing():
            return None
        available = [p for p in self.paths if p.is_file()]
        if len(available) != 3:
            print('Нет всех трёх файлов реплик Invoker в experiments/laughter/voices.', flush=True)
            return None
        chosen = random.choice(available)
        self.process = subprocess.Popen(['/usr/bin/afplay', str(chosen)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.last = now
        return chosen.name

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=2)

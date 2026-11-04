"""Emergency speech recognition never runs on the keyboard or GUI thread."""
import json
import queue
import threading

from voice_policy import is_stop_result


class StopListener:
    def __init__(self, recognizer, on_stop, on_overflow):
        self.recognizer = recognizer
        self.on_stop = on_stop
        self.on_overflow = on_overflow
        self.audio = queue.Queue(maxsize=64)
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._run, name='voice-stop', daemon=True)
        self.thread.start()

    def feed(self, token, data):
        try:
            self.audio.put_nowait((token, data))
        except queue.Full:
            self.on_overflow(token)

    def _run(self):
        previous = None
        while not self.closed.is_set():
            try:
                token, data = self.audio.get(timeout=.1)
            except queue.Empty:
                continue
            if token != previous:
                self.recognizer.Reset()
                previous = token
            if self.recognizer.AcceptWaveform(data):
                if is_stop_result(json.loads(self.recognizer.Result())):
                    self.on_stop(token)

    def close(self):
        self.closed.set()
        self.thread.join(timeout=2)

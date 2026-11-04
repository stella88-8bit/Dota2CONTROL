import time
import unittest
from unittest.mock import patch
import numpy as np
from dota_magic.whisper_capture import PhraseCapture


class VoiceStreamTests(unittest.TestCase):
    def capture(self):
        # Test audio segmentation without loading a model or touching a microphone.
        def idle(instance):
            instance._closed.wait()
        with patch.object(PhraseCapture, '_recognize', idle):
            capture = PhraseCapture(16000)
        self.addCleanup(capture.close)
        return capture

    def flush(self, c):
        deadline = time.monotonic() + 2
        while not c._audio.empty() and time.monotonic() < deadline:
            time.sleep(.005)
        time.sleep(.02)

    def phrase(self, c):
        loud = np.full(1024, 500, dtype='<i2').tobytes()
        quiet = np.zeros(1024, dtype='<i2').tobytes()
        for _ in range(8): c.feed(loud)
        for _ in range(6): c.feed(quiet)
        self.flush(c)

    def test_next_phrase_captured_while_decoder_busy(self):
        c = self.capture()
        c.busy = True
        self.phrase(c)
        self.phrase(c)
        self.assertEqual(c._jobs.qsize(), 2)
        self.assertFalse(c.recording)

    def test_stop_invalidates_queued_audio(self):
        c = self.capture()
        self.phrase(c)
        old = c._jobs.get_nowait()[0]
        c.cancel()
        self.assertNotEqual(c.token, old)
        self.assertFalse(c.recording)

    def test_silence_never_queues_inference(self):
        c = self.capture()
        for _ in range(20): c.feed(np.zeros(1024, dtype='<i2').tobytes())
        self.flush(c)
        self.assertTrue(c._jobs.empty())

    def test_queue_is_bounded(self):
        c = self.capture()
        for _ in range(4): self.phrase(c)
        self.assertEqual(c._jobs.qsize(), 2)
        self.assertEqual(c.dropped, 2)


if __name__ == '__main__': unittest.main()

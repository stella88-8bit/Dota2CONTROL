import unittest
import io
from unittest.mock import patch
from laughter import LaughterPlayer


class LaughterPlayerTests(unittest.TestCase):
    def test_selects_one_of_three_and_limits_repeats(self):
        player = LaughterPlayer()
        with patch('laughter.subprocess.Popen') as popen, patch('laughter.random.shuffle', side_effect=lambda paths: None):
            popen.return_value.poll.return_value = None
            self.assertEqual(player.play(), 'carl.mp3')
            self.assertIsNone(player.play())
            self.assertEqual(popen.call_count, 1)

    def test_missing_voice_does_not_play(self):
        player = LaughterPlayer()
        player.paths[0] = player.paths[0].with_name('missing.mp3')
        with patch('laughter.subprocess.Popen') as popen:
            self.assertIsNone(player.play())
            popen.assert_not_called()

    def test_ready_as_soon_as_playback_finishes(self):
        player = LaughterPlayer()
        with patch('laughter.subprocess.Popen') as popen:
            proc = popen.return_value
            proc.poll.return_value = 0
            proc.returncode = 0
            proc.stderr = io.BytesIO()
            self.assertIsNotNone(player.play())
            self.assertFalse(player.is_playing())
            proc.stderr = io.BytesIO()
            self.assertIsNotNone(player.play())
            self.assertEqual(popen.call_count, 2)

    def test_all_three_before_repeat(self):
        player = LaughterPlayer()
        with patch('laughter.subprocess.Popen') as popen:
            proc = popen.return_value
            proc.poll.return_value = 0
            proc.returncode = 0
            selected = []
            for _ in range(6):
                proc.stderr = io.BytesIO()
                selected.append(player.play())
            self.assertEqual(len(set(selected[:3])), 3)
            self.assertEqual(len(set(selected[3:])), 3)
            self.assertNotEqual(selected[2], selected[3])


if __name__ == '__main__': unittest.main()

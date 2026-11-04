import unittest
from unittest.mock import patch
from laughter import LaughterPlayer


class LaughterPlayerTests(unittest.TestCase):
    def test_selects_one_of_three_and_limits_repeats(self):
        player = LaughterPlayer()
        with patch('laughter.subprocess.Popen') as popen, patch('laughter.random.choice', side_effect=lambda paths: paths[1]):
            popen.return_value.poll.return_value = None
            self.assertEqual(player.play(), 'knowing.mp3')
            self.assertIsNone(player.play())
            self.assertEqual(popen.call_count, 1)

    def test_missing_voice_does_not_play(self):
        player = LaughterPlayer()
        player.paths[0] = player.paths[0].with_name('missing.mp3')
        with patch('laughter.subprocess.Popen') as popen:
            self.assertIsNone(player.play())
            popen.assert_not_called()


if __name__ == '__main__': unittest.main()

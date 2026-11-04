import unittest
from dota_magic.controls import GestureTrigger, voice_commands


class ControlsTests(unittest.TestCase):
    def test_voice_keys_and_repeated_orbs(self):
        self.assertEqual(voice_commands('куас куас векс экзорт инвоук первый второй'),
                         ['q', 'q', 'w', 'e', 'r', 'd', 'f'])
        self.assertEqual(voice_commands('векс стоп первый'), ['stop'])
        self.assertEqual(voice_commands('ин вок ин волк'), ['r', 'r'])
        self.assertEqual(voice_commands('ин вок стоп'), ['stop'])
        self.assertEqual(voice_commands('поговорим о погоде'), [])

    def test_all_commands_and_held_gesture(self):
        t = GestureTrigger()
        self.assertIsNone(t.update('q', 0))
        self.assertIsNone(t.update('q', 1))
        t.update('neutral', 2)
        t.update('neutral', 2.2)
        for index, key in enumerate('qwerdf'):
            now = 3 + index
            self.assertIsNone(t.update(key, now))
            self.assertEqual(t.update(key, now + .3), key)
            self.assertIsNone(t.update(key, now + .6))

    def test_loss_does_not_rearm_and_palm_does(self):
        t = GestureTrigger()
        t.update('neutral', 0)
        t.update('neutral', .2)
        t.update('q', 1)
        self.assertEqual(t.update('q', 1.3), 'q')
        t.update(None, 2)
        t.update('q', 3)
        self.assertIsNone(t.update('q', 3.3))
        t.update('neutral', 4)
        t.update('neutral', 4.2)
        t.update('q', 5)
        self.assertEqual(t.update('q', 5.3), 'q')
        t.reset()
        self.assertFalse(t.ready)


if __name__ == '__main__':
    unittest.main()

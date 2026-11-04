import unittest
from combos import COMBOS, match_combo
from combo_runner import ComboRunner, ORBS


class ComboTests(unittest.TestCase):
    def test_phrases_and_order(self):
        self.assertEqual(match_combo('Мама, я Миракл!')[1], COMBOS['мама я миракл'])
        self.assertEqual(match_combo('Мой любимый две тысячи седьмой')[1], COMBOS['мой любимый 2007 й'])
        self.assertIsNone(match_combo('совсем другие слова'))

    def test_prepare_confirm_and_self_cast(self):
        run = ComboRunner(('alacrity',), 0)
        data = {'ability3': {'name':'other', 'can_cast': True},
                'ability4': {'name':'other2', 'can_cast': True},
                'ability5': {'can_cast': True}}
        now = 0
        sent = []
        for _ in range(4):
            action = run.step(now, data)
            sent.append(action[0])
            now += .13
        self.assertEqual(''.join(sent), ORBS['alacrity'] + 'r')
        self.assertEqual(run.phase, 'invoke_confirm')
        self.assertIsNone(run.step(now, None))
        data['ability4'] = {'name':'invoker_alacrity', 'can_cast':True, 'cooldown':0}
        self.assertEqual(run.step(now, data), ('f', True))
        self.assertIsNone(run.step(now + .1, None))
        data['ability4']['cooldown'] = 10
        self.assertIsNone(run.step(now + .2, data))
        self.assertTrue(run.complete)

    def test_timeout_and_missing_state_never_cast(self):
        run = ComboRunner(('emp',), 0)
        self.assertIsNone(run.step(1, None))
        self.assertIsNone(run.step(13, None))
        self.assertTrue(run.error)
        self.assertIsNone(run.step(14, {'ability3':{'name':'invoker_emp','can_cast':True}}))

    def test_cold_snap_retries_until_cast_confirmed(self):
        run = ComboRunner(('cold snap', 'emp'), 0)
        data = {'ability3': {'name': 'invoker_cold_snap', 'can_cast': True, 'cooldown': 0},
                'ability4': {'name': 'invoker_emp', 'can_cast': True, 'cooldown': 0},
                'ability5': {'can_cast': True}}
        self.assertEqual(run.step(0, data), ('d', False))
        self.assertIsNone(run.step(.2, data))
        self.assertEqual(run.step(.4, data), ('d', False))
        self.assertEqual(run.index, 0)
        data['ability3']['cooldown'] = 10
        self.assertIsNone(run.step(.8, data))
        self.assertEqual(run.index, 1)
        self.assertEqual(run.step(1.1, data), ('f', False))


if __name__ == '__main__': unittest.main()

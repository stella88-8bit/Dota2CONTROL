import unittest
from dota_magic.spell_phrases import SPELLS, identify_phrase


class SpellPhraseTests(unittest.TestCase):
    def test_approved_phrases(self):
        self.assertEqual(len(SPELLS), 10)
        self.assertEqual(len({name for name, _ in SPELLS.values()}), 10)
        for phrase, expected in SPELLS.items():
            self.assertEqual(identify_phrase(phrase.upper() + '!'), expected)
        self.assertEqual(identify_phrase('Слова силы!'), ('invoke', 'r'))

    def test_nonexact_and_unknown_input_do_not_match(self):
        self.assertIsNone(identify_phrase('призрак'))
        self.assertIsNone(identify_phrase('призрак мирота стоп'))
        self.assertIsNone(identify_phrase(''))


if __name__ == '__main__':
    unittest.main()

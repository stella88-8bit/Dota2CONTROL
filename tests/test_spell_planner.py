import unittest
from spell_planner import plan_spell
from spell_phrases import SPELLS


class PlannerTests(unittest.TestCase):
    def test_every_spell_prepares_or_casts_in_correct_slot(self):
        for phrase, (name, orbs) in SPELLS.items():
            spell = 'invoker_' + name.replace(' ', '_')
            with self.subTest(spell=spell):
                self.assertEqual(plan_spell(phrase, ('other', 'other')).keys, orbs + 'r')
                self.assertEqual(plan_spell(phrase, (spell, 'other')).keys, 'd')
                self.assertEqual(plan_spell(phrase, ('other', spell)).keys, 'f')

    def test_missing_state_and_unknown_phrase_do_not_plan(self):
        self.assertIsNone(plan_spell('призрак мирота', None))
        self.assertIsNone(plan_spell('что угодно', ('a', 'b')))
        self.assertIsNone(plan_spell('слова силы', None))
        self.assertEqual(plan_spell('слова силы', ('a', 'b')).keys, 'r')


if __name__ == '__main__':
    unittest.main()

import unittest
import time
from integration.gsi import GSIState


class GsiTests(unittest.TestCase):
    def test_slots_update_and_non_invoker_invalidates(self):
        state = GSIState()
        self.assertIsNone(state.snapshot())
        payload = {'hero': {'name': 'npc_dota_hero_invoker'}, 'abilities': {
            'ability3': {'name': 'invoker_emp'}, 'ability4': {'name': 'invoker_sun_strike'}}}
        state.update(payload)
        self.assertEqual(state.snapshot(), ('invoker_emp', 'invoker_sun_strike'))
        payload['abilities']['ability3'], payload['abilities']['ability4'] = payload['abilities']['ability4'], payload['abilities']['ability3']
        state.update(payload)
        self.assertEqual(state.snapshot(), ('invoker_sun_strike', 'invoker_emp'))
        state.update({'hero': {'name': 'npc_dota_hero_axe'}, 'abilities': payload['abilities']})
        self.assertIsNone(state.snapshot())

    def test_incomplete_and_stale_state_are_not_used(self):
        state = GSIState()
        state.update({'hero': {'name': 'npc_dota_hero_invoker'}, 'abilities': {}})
        self.assertIsNone(state.snapshot())
        state.update({'hero': {'name': 'npc_dota_hero_invoker'}, 'abilities': {
            'ability3': {'name': 'invoker_emp'}, 'ability4': {'name': 'invoker_sun_strike'}}})
        self.assertIsNone(state.snapshot(max_age=-1))

    def test_confirmation_requires_new_update(self):
        state = GSIState()
        payload = {'hero': {'name': 'npc_dota_hero_invoker'}, 'abilities': {
            'ability3': {'name': 'invoker_emp'}, 'ability4': {'name': 'invoker_sun_strike'}}}
        state.update(payload)
        marker = time.monotonic()
        self.assertIsNone(state.snapshot(after=marker))
        state.update(payload)
        self.assertEqual(state.snapshot(after=marker), ('invoker_emp', 'invoker_sun_strike'))

    def test_hero_and_orbs_are_read_from_same_packet(self):
        state=GSIState()
        abilities={'ability3':{'name':'invoker_emp'},'ability4':{'name':'invoker_sun_strike'},
                   'ability0':{'name':'invoker_quas','level':3}}
        state.update({'hero':{'name':'npc_dota_hero_invoker','level':7},'abilities':abilities})
        hero,spells,stamp=state.read_context()
        self.assertEqual(hero['level'],7)
        self.assertEqual(spells['ability0']['level'],3)
        self.assertIsNotNone(stamp)
        self.assertEqual(state.read_context(max_age=-1)[:2],(None,None))
        state.update({'hero':{'name':'npc_dota_hero_axe'},'abilities':abilities})
        self.assertEqual(state.read_context()[:2],(None,None))


if __name__ == '__main__':
    unittest.main()

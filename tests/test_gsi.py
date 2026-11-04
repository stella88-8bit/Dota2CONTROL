import unittest
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


if __name__ == '__main__':
    unittest.main()

import copy
import unittest

from predictive_combo import PredictiveComboRunner, invoke_cooldown


def state(level=8):
    return {**{'ability' + str(i): {'name': 'invoker_' + name, 'level': level}
               for i, name in enumerate(('quas', 'wex', 'exort'))},
            'ability3': {'name': 'empty', 'can_cast': True, 'cooldown': 0},
            'ability4': {'name': 'empty', 'can_cast': True, 'cooldown': 0},
            'ability5': {'can_cast': True, 'cooldown': 0}}


def dispatch(run, data, end, packet_at=0, start=0):
    actions = []
    now = start
    while now < end:
        action = run.step(now, data, packet_at)
        if action:
            actions.append((round(now, 4), action))
        now = round(now + .005, 4)
    return actions


class PredictiveTests(unittest.TestCase):
    def test_dispatch_needs_no_new_packet_per_spell(self):
        run = PredictiveComboRunner(('tornado', 'emp', 'chaos meteor', 'deafening blast'), 0)
        actions = dispatch(run, state(), 1)
        self.assertEqual(''.join(a[0] for _, a in actions), 'qwwrdwwwrdweerdqwerd')
        self.assertEqual(run.phase, 'verify')
        self.assertLess(run.dispatch_complete_at, 1)
        self.assertFalse(run.complete)  # Sending is not proof of successful casts.
        run.step(4, None, 0)
        self.assertTrue(run.complete)
        self.assertTrue(run.verification_timed_out)

    def test_invoke_uses_orb_levels_and_waits_for_game_cooldown(self):
        self.assertAlmostEqual(invoke_cooldown(state(7)), .7)
        self.assertAlmostEqual(invoke_cooldown(state(1)), 6.1)
        self.assertEqual(invoke_cooldown({}), 7)
        run = PredictiveComboRunner(('tornado', 'emp'), 0)
        times = [t for t, a in dispatch(run, state(7), 1.5) if a[0] == 'r']
        self.assertEqual(len(times), 2)
        self.assertGreaterEqual(times[1] - times[0], .7 - .001)

    def test_delayed_old_slot_packet_does_not_rollback_prediction(self):
        run = PredictiveComboRunner(('tornado', 'emp'), 0)
        initial = state()
        dispatch(run, initial, .4)
        predicted = run.slots
        run.step(.8, copy.deepcopy(initial), .8)
        self.assertEqual(run.slots, predicted)
        self.assertFalse(run.error)

    def test_two_stable_mismatches_repair_missing_final_invoke(self):
        run = PredictiveComboRunner(('tornado', 'emp'), 0)
        initial = state()
        dispatch(run, initial, .4)
        run.step(1.8, initial, 1.8)
        self.assertEqual(run.phase, 'verify')
        action = run.step(2.0, copy.deepcopy(initial), 2.0)
        self.assertEqual(action, ('w', False))
        self.assertEqual(run.index, 1)
        self.assertEqual(run.corrections['emp'], 1)

    def test_slot_f_is_used_directly_and_alacrity_targets_self(self):
        run = PredictiveComboRunner(('alacrity',), 0)
        data = state()
        data['ability4']['name'] = 'invoker_alacrity'
        self.assertEqual(run.step(0, data, 0), ('f', True))

    def test_cold_snap_stays_targeted_until_confirmed_then_continues(self):
        run = PredictiveComboRunner(('cold snap', 'emp'), 0)
        data = state()
        data['ability3']['name'] = 'invoker_cold_snap'
        self.assertEqual(run.step(0, data, 0), ('d', False))
        actions = dispatch(run, data, .5, start=.01)
        self.assertTrue(actions)
        self.assertTrue(all(a == ('d', False) for _, a in actions))
        self.assertEqual(run.index, 0)
        changed = copy.deepcopy(data)
        changed['ability3'].update(cooldown=19, can_cast=False)
        run.step(.6, changed, .6)
        self.assertEqual(run.index, 1)
        self.assertEqual(run.step(.7, changed, .6), ('w', False))

    def test_disconnected_feed_pauses_dispatch(self):
        run = PredictiveComboRunner(('tornado', 'emp'), 0)
        data = state()
        self.assertEqual(run.step(0, data, 0), ('q', False))
        self.assertIsNone(run.step(.1, None, 0))
        self.assertIsNone(run.step(.5, None, 0))
        self.assertEqual(run.phase, 'orbs')

    def test_observed_unavailable_spell_is_not_cast_optimistically(self):
        run = PredictiveComboRunner(('emp',), 0)
        data = state()
        dispatch(run, data, .08)
        observed = state()
        observed['ability3'].update(name='invoker_emp', can_cast=False, cooldown=5)
        self.assertIsNone(run.step(.2, observed, .2))
        self.assertNotIn('emp', run.sent)
        ready = copy.deepcopy(observed)
        ready['ability3'].update(can_cast=True, cooldown=0)
        self.assertEqual(run.step(.3, ready, .3), ('d', False))

    def test_unconfirmed_tail_recast_requires_two_distinct_packets(self):
        run = PredictiveComboRunner(('emp',), 0)
        data = state()
        dispatch(run, data, .3)
        observed = state()
        observed['ability3']['name'] = 'invoker_emp'
        self.assertIsNone(run.step(1.8, observed, 1.8))
        self.assertIsNone(run.step(1.9, observed, 1.8))
        self.assertEqual(run.step(2, observed, 2), ('d', False))
        confirmed = copy.deepcopy(observed)
        confirmed['ability3'].update(cooldown=10, can_cast=False)
        run.step(2.1, confirmed, 2.1)
        self.assertTrue(run.complete)
        self.assertIn('emp', run.confirmed)

    def test_last_confirmation_does_not_hide_missed_previous_visible_spell(self):
        run = PredictiveComboRunner(('tornado', 'emp'), 0)
        dispatch(run, state(), .6)
        observed = state()
        observed['ability3'].update(name='invoker_emp', can_cast=False, cooldown=10)
        observed['ability4'].update(name='invoker_tornado', can_cast=True, cooldown=0)
        run.step(1.8, observed, 1.8)
        self.assertFalse(run.complete)
        self.assertEqual(run.step(2, observed, 2), ('f', False))


if __name__ == '__main__':
    unittest.main()

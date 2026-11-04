import copy
import queue
import threading
import time
import unittest
from unittest.mock import Mock

from combo_runner import ORBS
from combos import COMBOS
from integration.gsi import GSIState
from voice_controller import VoiceController


class Capture:
    def __init__(self):
        self.ready = True
        self.token = 0
        self.results = queue.Queue()
        self.wakeup = None

    def cancel(self):
        self.token += 1

    def recognize(self, text):
        self.results.put((self.token, text, None, time.monotonic()))
        self.wakeup.set()


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return True
        threading.Event().wait(.002)
    return False


class ControllerTests(unittest.TestCase):
    def setup_control(self, spells, cold_snap_target=True):
        self.capture = Capture()
        self.gsi = GSIState()
        self.payload = {'hero': {'name': 'npc_dota_hero_invoker'}, 'abilities': {
            **{'ability' + str(i): {'name': 'invoker_' + name, 'level': 8}
               for i, name in enumerate(('quas', 'wex', 'exort'))},
            'ability3': {'name': 'empty'}, 'ability4': {'name': 'empty'},
            'ability5': {'can_cast': True}}}
        self.sent, self.casts, self.orbs = [], [], []
        self.finished = threading.Event()

        def send(key, self_target):
            self.sent.append((key, self_target))
            abilities = self.payload['abilities']
            if key in 'qwe':
                self.orbs.append(key)
            elif key == 'r':
                spell = next(name for name, orbs in ORBS.items() if orbs == ''.join(self.orbs[-3:]))
                abilities['ability4'] = abilities['ability3']
                abilities['ability3'] = {'name': 'invoker_' + spell.replace(' ', '_'),
                                         'can_cast': True, 'cooldown': 0}
            else:
                ability = abilities['ability3' if key == 'd' else 'ability4']
                spell = ability['name'][8:].replace('_', ' ')
                if spell == 'cold snap' and not cold_snap_target:
                    return
                self.casts.append((spell, self_target))
                ability.update(can_cast=False, cooldown=10)
                if len(self.casts) == len(spells):
                    self.finished.set()
            self.gsi.update(copy.deepcopy(self.payload))

        self.gsi.update(copy.deepcopy(self.payload))
        self.control = VoiceController(self.gsi, self.capture, send, activity=Mock())
        self.addCleanup(self.control.close)
        self.control.enable()
        self.assertTrue(wait_for(lambda: self.control.enabled))

    def test_all_combos_complete_without_gui_or_log_consumer(self):
        for phrase, spells in COMBOS.items():
            with self.subTest(phrase=phrase):
                self.setup_control(spells)
                self.capture.recognize(phrase)
                self.assertTrue(self.finished.wait(2))
                self.assertTrue(wait_for(lambda: self.control.active is None))
                self.assertEqual(self.casts, [(s, s == 'alacrity') for s in spells])
                self.assertTrue(self.control.enabled)
                self.control.close()

    def test_stop_cancels_cold_snap_wait_and_stale_speech_cannot_restart(self):
        spells = COMBOS['от меня не убежишь']
        self.setup_control(spells, cold_snap_target=False)
        self.capture.recognize('от меня не убежишь')
        self.assertTrue(wait_for(lambda: self.control.active is not None
                               and self.control.active.spells[self.control.active.index] == 'cold snap'
                               and self.control.active.phase == 'cast_confirm'))
        old_token = self.capture.token
        self.control.disable(token=old_token)
        self.assertTrue(wait_for(lambda: not self.control.enabled))
        self.assertIsNone(self.control.active)
        count = len(self.sent)
        self.capture.results.put((old_token, 'мама я миракл', None, time.monotonic()))
        self.control.wakeup.set()
        self.control.close()
        self.assertEqual(len(self.sent), count)

    def test_single_spell_uses_same_executor_and_self_targets_alacrity(self):
        self.setup_control(('alacrity',))
        self.capture.recognize('Рвение Эксорта')
        self.assertTrue(self.finished.wait(2))
        self.assertEqual(self.casts, [('alacrity', True)])

    def test_recognition_error_keeps_control_enabled(self):
        self.setup_control(('emp',))
        self.capture.results.put((self.capture.token, '', 'test audio error', time.monotonic()))
        self.capture.recognize('Экстрагирующий Мана Пульс')
        self.assertTrue(self.finished.wait(2))
        self.assertTrue(self.control.enabled)

    def test_stop_during_key_send_prevents_next_key(self):
        self.setup_control(COMBOS['мама я миракл'])
        started, release = threading.Event(), threading.Event()
        original = self.control.send

        def blocked_send(key, target):
            started.set()
            release.wait(2)
            original(key, target)

        self.control.send = blocked_send
        self.capture.recognize('мама я миракл')
        self.assertTrue(started.wait(2))
        self.control.disable()
        release.set()
        self.assertTrue(wait_for(lambda: not self.control.enabled))
        self.control.close()
        self.assertEqual(len(self.sent), 1)


if __name__ == '__main__':
    unittest.main()

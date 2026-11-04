"""Measure the real controller + local HTTP GSI using a simulated game.

No microphone, GUI, keyboard events or Dota commands are used.
"""
import argparse
import copy
import http.client
import json
import queue
import statistics
import threading
import time
from pathlib import Path

from combo_runner import ORBS
from combos import COMBOS
from integration.gsi import GSIState, start_server
from voice_controller import VoiceController
from predictive_combo import invoke_cooldown


class Capture:
    ready = True

    def __init__(self):
        self.token = 0
        self.results = queue.Queue()
        self.wakeup = None

    def cancel(self):
        self.token += 1


class Game:
    def __init__(self, port, spells, key_ms, gsi_ms):
        self.port, self.spells = port, spells
        self.key_delay, self.gsi_delay = key_ms / 1000, gsi_ms / 1000
        self.payload = {'hero': {'name': 'npc_dota_hero_invoker'}, 'abilities': {
            **{'ability' + str(i): {'name': 'invoker_' + name, 'level': 7}
               for i, name in enumerate(('quas', 'wex', 'exort'))},
            'ability3': {'name': 'empty'}, 'ability4': {'name': 'empty'},
            'ability5': {'can_cast': True}}}
        self.commands = queue.Queue()
        self.snapshots = queue.Queue()
        self.closed = threading.Event()
        self.finished = threading.Event()
        self.orbs, self.casts, self.requests = [], [], []
        self.error = None
        self.invoke_ready_at = 0
        self._post()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.poster = threading.Thread(target=self._publish, daemon=True)
        self.thread.start()
        self.poster.start()

    def _post(self, payload=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=2)
        start = time.monotonic()
        try:
            connection.request('POST', '/', json.dumps(self.payload if payload is None else payload), {'Content-Type': 'application/json'})
            response = connection.getresponse()
            if response.status != 200 or response.read() != b'OK':
                raise RuntimeError('Unexpected GSI response')
            self.requests.append((time.monotonic() - start) * 1000)
        finally:
            connection.close()

    def _publish(self):
        try:
            while not self.closed.is_set():
                try:
                    due, payload = self.snapshots.get(timeout=.05)
                except queue.Empty:
                    continue
                if self.closed.wait(max(0, due - time.monotonic())):
                    break
                self._post(payload)
        except Exception as error:
            self.error = error
            self.finished.set()

    def send(self, key, self_target):
        self.commands.put((time.monotonic(), key, self_target))
        # Simulate time spent posting a press/release pair through the OS API.
        time.sleep(self.key_delay)

    def _run(self):
        try:
            while not self.closed.is_set():
                try:
                    stamp, key, self_target = self.commands.get(timeout=.05)
                except queue.Empty:
                    continue
                abilities = self.payload['abilities']
                if key in 'qwe':
                    self.orbs.append(key)
                    continue
                if key == 'r':
                    if time.monotonic() < self.invoke_ready_at:
                        continue
                    spell = next(name for name, orbs in ORBS.items()
                                 if orbs == ''.join(self.orbs[-3:]))
                    abilities['ability4'] = copy.deepcopy(abilities['ability3'])
                    abilities['ability3'] = {'name': 'invoker_' + spell.replace(' ', '_'),
                                             'can_cast': True, 'cooldown': 0}
                    self.invoke_ready_at = time.monotonic() + invoke_cooldown(abilities)
                else:
                    ability = abilities['ability3' if key == 'd' else 'ability4']
                    if ability.get('can_cast') is not True:
                        continue
                    spell = ability['name'][8:].replace('_', ' ')
                    self.casts.append((stamp, spell, self_target))
                    ability.update(can_cast=False, cooldown=10)
                remaining = max(0, self.invoke_ready_at - time.monotonic())
                abilities['ability5'].update(can_cast=remaining == 0, cooldown=remaining)
                self.snapshots.put((time.monotonic() + self.gsi_delay, copy.deepcopy(self.payload)))
                if len(self.casts) == len(self.spells):
                    self.finished.set()
        except Exception as error:
            self.error = error
            self.finished.set()

    def close(self):
        self.closed.set()
        self.thread.join(timeout=3)
        self.poster.join(timeout=3)


def measure(phrase, spells, key_ms, gsi_ms):
    state, capture = GSIState(), Capture()
    server = start_server(state, port=0)
    game = control = None
    try:
        game = Game(server.server_port, spells, key_ms, gsi_ms)
        control = VoiceController(state, capture, game.send)
        control.enable()
        deadline = time.monotonic() + 2
        while not control.enabled:
            if time.monotonic() > deadline:
                raise RuntimeError('Controller did not enable')
            time.sleep(.001)
        received = time.monotonic()
        capture.results.put((capture.token, phrase, None, received))
        capture.wakeup.set()
        # Deliberately do not consume GUI/log events during execution.
        if not game.finished.wait(max(10, len(spells) * (2 * gsi_ms / 1000 + 1) + 5)):
            raise RuntimeError('Combo timed out')
        if game.error:
            raise game.error
        deadline = time.monotonic() + 2
        while control.active is not None:
            if time.monotonic() > deadline:
                raise RuntimeError('Final GSI confirmation timed out')
            time.sleep(.001)
        elapsed = time.monotonic() - received
        actual = [(spell, target) for _, spell, target in game.casts]
        expected = [(spell, spell == 'alacrity') for spell in spells]
        if actual != expected:
            raise RuntimeError(f'Wrong cast order: {actual!r}')
        stamps = [stamp for stamp, _, _ in game.casts]
        return {'phrase': phrase, 'total_ms': round(elapsed * 1000, 2),
                'dispatch_ms': round((control.last_run.dispatch_complete_at - received) * 1000, 2),
                'first_cast_ms': round((stamps[0] - received) * 1000, 2),
                'inter_spell_ms': [round((b-a)*1000, 2) for a, b in zip(stamps, stamps[1:])],
                'http_median_ms': round(statistics.median(game.requests), 2),
                'http_max_ms': round(max(game.requests), 2), 'cast_order_verified': True}
    finally:
        if control:
            control.close()
        if game:
            game.close()
        server.shutdown()
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-ms', type=float, default=16)
    parser.add_argument('--gsi-ms', type=float, default=30)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.key_ms < 0 or args.gsi_ms < 0 or args.repeats < 1:
        parser.error('Delays must be nonnegative and repeats positive')
    measurements = [measure(phrase, spells, args.key_ms, args.gsi_ms)
                    for _ in range(args.repeats) for phrase, spells in COMBOS.items()]
    report = {'mode': 'simulated_game_real_controller_and_http_no_keyboard_or_microphone',
              'simulated_key_api_ms': args.key_ms, 'simulated_game_gsi_delay_ms': args.gsi_ms,
              'orb_levels': [7, 7, 7], 'invoke_cooldown_enforced': True,
              'gui_and_console_not_serviced_during_combos': True, 'measurements': measurements}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + '\n', encoding='utf-8')
    print(rendered)


if __name__ == '__main__':
    main()

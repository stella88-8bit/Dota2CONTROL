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

from dota_magic.combo_runner import ORBS
from dota_magic.combos import COMBOS
from integration.gsi import GSIState, start_server
from dota_magic.voice_controller import VoiceController
from dota_magic.predictive_combo import invoke_cooldown
from dota_magic.invoker_database import SpellDatabase


class Capture:
    ready = True

    def __init__(self):
        self.token = 0
        self.results = queue.Queue()
        self.wakeup = None

    def cancel(self):
        self.token += 1


class Game:
    def __init__(self, port, spells, key_ms, gsi_ms, levels=(7,7,7), timed=False):
        self.port, self.spells = port, spells
        self.key_delay, self.gsi_delay = key_ms / 1000, gsi_ms / 1000
        self.payload = {'hero': {'name': 'npc_dota_hero_invoker','level':30,'mana':9999}, 'abilities': {
            **{'ability' + str(i): {'name': 'invoker_' + name, 'level': levels[i]}
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
        self.cooldown = max(.05,SpellDatabase().profile(30,*levels)['invoke_cooldown']) if timed else invoke_cooldown(self.payload['abilities'])
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
                    self.invoke_ready_at = time.monotonic() + self.cooldown
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


def measure(phrase, spells, key_ms, gsi_ms, timed=False, levels=(7,7,7), distance=600):
    state, capture = GSIState(), Capture()
    server = start_server(state, port=0)
    game = control = None
    try:
        game = Game(server.server_port, spells, key_ms, gsi_ms, levels, timed)
        control = VoiceController(state, capture, game.send, spell_database=SpellDatabase() if timed else None,target_distance=distance)
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
        if not game.finished.wait(max(40 if timed else 10, len(spells) * (2 * gsi_ms / 1000 + 1) + 5)):
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
        expected = [(spell, spell == 'alacrity') for spell in control.last_run.spells]
        if actual != expected:
            raise RuntimeError(f'Wrong cast order: {actual!r}')
        stamps = [stamp for stamp, _, _ in game.casts]
        report = {'phrase': phrase, 'total_ms': round(elapsed * 1000, 2),
                'dispatch_ms': round((control.last_run.dispatch_complete_at - received) * 1000, 2),
                'first_cast_ms': round((stamps[0] - received) * 1000, 2),
                'inter_spell_ms': [round((b-a)*1000, 2) for a, b in zip(stamps, stamps[1:])],
                'http_median_ms': round(statistics.median(game.requests), 2),
                'http_max_ms': round(max(game.requests), 2), 'cast_order_verified': True}
        if timed:
            plan=control.last_run.timing
            report['timing_plan']=plan.as_dict()
            report['predicted_impacts_not_measured_game_hits']=plan.impact_report(
                {spell:stamp for stamp,spell,_ in game.casts},received)
            if plan.synchronized and plan.landing is not None:
                if not all(item['within_nominal_window'] for item in report['predicted_impacts_not_measured_game_hits'].values()):
                    raise RuntimeError('Real controller timing missed the nominal model window')
        return report
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
    parser.add_argument('--timed',action='store_true',help='Use the level database and impact scheduler')
    parser.add_argument('--levels',type=int,nargs=3,default=(7,7,7),metavar=('QUAS','WEX','EXORT'))
    parser.add_argument('--distance',type=float,default=600)
    args = parser.parse_args()
    if args.key_ms < 0 or args.gsi_ms < 0 or args.repeats < 1:
        parser.error('Delays must be nonnegative and repeats positive')
    if any(not 1<=rank<=9 for rank in args.levels):
        parser.error('Benchmark orb levels must be 1..9')
    measurements = [measure(phrase, spells, args.key_ms, args.gsi_ms,args.timed,tuple(args.levels),args.distance)
                    for _ in range(args.repeats) for phrase, spells in COMBOS.items()]
    report = {'mode': 'simulated_game_real_controller_and_http_no_keyboard_or_microphone',
              'simulated_key_api_ms': args.key_ms, 'simulated_game_gsi_delay_ms': args.gsi_ms,
              'orb_levels': args.levels, 'invoke_cooldown_enforced': True,'database_timing_enabled':args.timed,
              'gui_and_console_not_serviced_during_combos': True, 'measurements': measurements}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + '\n', encoding='utf-8')
    print(rendered)


if __name__ == '__main__':
    main()

"""Dispatch combos from predicted slots; reconcile with asynchronous GSI.

Timing defaults come from the installed npc_dota_hero_invoker definition:
Invoke 7 - 0.3 * total orb levels; spell cast point 0.05 seconds.
"""
from combo_runner import ORBS, TARGET_RETRY_INTERVAL

KEY_GAP = .012
INVOKE_SETTLE = .065
CAST_SETTLE = .075
LAG_GRACE = 1.25
VERIFY_TIMEOUT = 3.0


def invoke_cooldown(details):
    levels = []
    for index, name in enumerate(('quas', 'wex', 'exort')):
        ability = details.get('ability' + str(index), {})
        if ability.get('name') != 'invoker_' + name or not isinstance(ability.get('level'), (int, float)):
            return 7.0  # Unknown levels: a newer GSI readiness report can shorten this.
        levels.append(ability['level'])
    return max(.05, 7.0 - .3 * sum(levels))


class PredictiveComboRunner:
    predictive = True

    def __init__(self, spells, now):
        self.spells = list(spells)
        self.started_at = now
        self.index = 0
        self.phase = 'choose'
        self.next_at = now
        self.deadline = now + 15
        self.complete = False
        self.error = None
        self.events = []
        self.slots = None
        self.packet_at = None
        self.details = None
        self.keys = []
        self.last_invoke_at = None
        self.invoke_ready_at = now
        self.last_cast_at = None
        self.sent = {}
        self.confirmed = set()
        self.corrections = {}
        self.misses = {}
        self.mismatch = None
        self.mismatch_count = 0
        self.dispatch_complete_at = None
        self.verify_until = None
        self.verification_timed_out = False

    def _note(self, text, now):
        self.events.append(('note', text, now, None))

    def _observe(self, now, details, packet_at):
        if packet_at == self.packet_at:
            return
        self.packet_at, self.details = packet_at, details
        actual = tuple(details['ability' + str(i)].get('name') for i in (3, 4))
        if self.slots is None:
            self.slots = actual
            self._note(f'Быстрый прокаст; расчётная перезарядка Invoke {invoke_cooldown(details):.3f} с', now)
        for i in (3, 4):
            ability = details['ability' + str(i)]
            spell = ability.get('name', '').removeprefix('invoker_').replace('_', ' ')
            if spell in self.sent and packet_at > self.sent[spell] and ability.get('cooldown', 0) > 0:
                if spell not in self.confirmed:
                    self.confirmed.add(spell)
                    self.events.append(('confirmed', spell, now, now - self.sent[spell]))
        invoke = details.get('ability5', {})
        if self.last_invoke_at is None:
            self.invoke_ready_at = now + max(0, invoke.get('cooldown', 0))
        elif actual == self.slots and packet_at >= self.last_invoke_at + INVOKE_SETTLE:
            if invoke.get('can_cast') is True:
                self.invoke_ready_at = min(self.invoke_ready_at, now)
            elif invoke.get('cooldown', 0) > invoke_cooldown(details) + 1:
                # Remaining cooldown may come from a snapshot generated long
                # before receipt (and may be rounded). Do not restart the normal
                # cooldown at packet arrival. Extend only for a larger discrepancy.
                self.invoke_ready_at = max(self.invoke_ready_at, now + invoke['cooldown'])
            if self.phase == 'invoke':
                self.next_at = min(self.next_at, max(now + KEY_GAP, self.invoke_ready_at))
        if actual == self.slots:
            self.mismatch = None
            self.mismatch_count = 0
            return
        # A received packet can describe an earlier step. Never roll back a fast
        # sequence solely because its old slot pair arrived late.
        mutation = self.last_invoke_at if self.last_invoke_at is not None else self.started_at
        if now < mutation + LAG_GRACE:
            return
        self.mismatch_count = self.mismatch_count + 1 if actual == self.mismatch else 1
        self.mismatch = actual
        if self.mismatch_count < 2:
            return
        self.slots = actual
        self.mismatch_count = 0
        self._note('GSI: корректирую прогноз ячеек по двум согласованным пакетам', now)
        if self.phase not in ('verify', 'cast_confirm'):
            spell = self.spells[self.index]
            self.corrections[spell] = self.corrections.get(spell, 0) + 1
            if self.corrections[spell] > 2:
                self.error = 'Не удалось синхронизировать ячейки: ' + spell
                return
            self.phase, self.keys = 'choose', []
        elif self.phase == 'verify' and self._slot(self.spells[-1]) is None:
            spell = self.spells[-1]
            if self.corrections.get(spell, 0) < 2:
                self.corrections[spell] = self.corrections.get(spell, 0) + 1
                self.index = len(self.spells) - 1
                self.phase, self.keys = 'choose', []
                self.next_at, self.deadline = now, now + 15
                self._note('GSI: повтор подготовки отсутствующего последнего заклинания', now)

    def _slot(self, spell):
        expected = 'invoker_' + spell.replace(' ', '_')
        return ('d' if self.slots.index(expected) == 0 else 'f') if expected in self.slots else None

    def _advance(self, now):
        self.index += 1
        self.next_at = now + CAST_SETTLE
        if self.index == len(self.spells):
            self.phase = 'verify'
            self.dispatch_complete_at = now
            self.verify_until = now + VERIFY_TIMEOUT
            self._note(f'Команды прокаста отправлены за {now-self.started_at:.3f} с; проверка GSI продолжается', now)
        else:
            self.phase = 'choose'
            self.deadline = now + 15

    def step(self, now, details, packet_at):
        if self.complete or self.error:
            return None
        if details is not None:
            self._observe(now, details, packet_at)
        if self.error:
            return None
        if self.phase == 'verify':
            # Recast a verifiably missed tail ability only while GSI agrees with
            # our current slots. Evicted abilities cannot be verified or replayed.
            if details is not None and tuple(details['ability' + str(i)]['name'] for i in (3, 4)) == self.slots:
                for i in (3, 4):
                    ability = details['ability' + str(i)]
                    spell = ability['name'].removeprefix('invoker_').replace('_', ' ')
                    if (spell in self.sent and spell not in self.confirmed
                            and packet_at > self.sent[spell] + LAG_GRACE
                            and ability.get('can_cast') is True and ability.get('cooldown', 0) == 0
                            and now >= self.next_at):
                        last_packet, count = self.misses.get(spell, (None, 0))
                        if last_packet != packet_at:
                            count += 1
                            self.misses[spell] = packet_at, count
                        if count < 2:
                            continue
                        if self.corrections.get(spell, 0) >= 2:
                            continue
                        self.corrections[spell] = self.corrections.get(spell, 0) + 1
                        self.sent[spell] = now
                        self.misses[spell] = None, 0
                        self.next_at = now + CAST_SETTLE
                        self.verify_until = now + VERIFY_TIMEOUT
                        self._note('GSI: повтор неприменённого заклинания ' + spell, now)
                        return ('d' if i == 3 else 'f'), spell == 'alacrity'
            visible_pending = ({name.removeprefix('invoker_').replace('_', ' ')
                                for name in self.slots} & self.sent.keys()) - self.confirmed
            if self.spells[-1] in self.confirmed and not visible_pending:
                self.complete = True
            elif now >= self.verify_until:
                self.verification_timed_out = True
                self.complete = True
            return None
        if now > self.deadline:
            self.error = 'Способность недоступна или нет GSI: ' + self.spells[self.index]
            return None
        # Fresh enough data is still required to keep sending input, but not a
        # new packet per action. Loss of the feed pauses dispatch.
        if details is None or self.slots is None or now < self.next_at:
            return None
        spell = self.spells[self.index]
        if self.phase == 'cast_confirm':  # Targeted Cold Snap: preserve retry-until-hit.
            if spell in self.confirmed:
                self._advance(now)
                return None
            slot = self._slot(spell)
            if slot is None:
                self.phase = 'choose'
                self._note('GSI: Cold Snap исчез из ячейки, подготавливаю повторно', now)
                return None
            self.next_at = now + TARGET_RETRY_INTERVAL
            self.events.append(('retry', spell, now, None))
            return slot, False
        if self.phase == 'choose':
            slot = self._slot(spell)
            if slot:
                # Don't knowingly cast an unavailable ability from a reconciled slot.
                observed = details['ability3' if slot == 'd' else 'ability4']
                if observed.get('name') == 'invoker_' + spell.replace(' ', '_'):
                    if observed.get('can_cast') is not True:
                        return None
                self.phase = 'cast'
            else:
                self.keys = list(ORBS[spell])
                self.phase = 'orbs'
        if self.phase == 'orbs':
            key = self.keys.pop(0)
            self.next_at = now + KEY_GAP
            if not self.keys:
                self.phase = 'invoke'
            return key, False
        if self.phase == 'invoke':
            if now < self.invoke_ready_at:
                self.next_at = self.invoke_ready_at
                return None
            invoke = details.get('ability5', {})
            if invoke.get('can_cast') not in (True, False):
                return None
            if (self.last_invoke_at is None and invoke.get('can_cast') is False
                    and invoke.get('cooldown', 0) <= 0):
                return None
            self.slots = ('invoker_' + spell.replace(' ', '_'), self.slots[0])
            self.last_invoke_at = now
            self.invoke_ready_at = now + invoke_cooldown(details)
            self.next_at = now + INVOKE_SETTLE
            self.phase = 'cast'
            self.events.append(('invoke', spell, now, None))
            return 'r', False
        if self.phase == 'cast':
            slot = self._slot(spell)
            if slot is None:
                self.phase = 'choose'
                return None
            observed = details['ability3' if slot == 'd' else 'ability4']
            if (observed.get('name') == 'invoker_' + spell.replace(' ', '_')
                    and observed.get('can_cast') is not True):
                return None
            interval = None if self.last_cast_at is None else now - self.last_cast_at
            self.last_cast_at = now
            self.sent[spell] = now
            self.events.append(('cast', spell, now, interval))
            if spell == 'cold snap':
                self.phase = 'cast_confirm'
                self.deadline = float('inf')
                self.next_at = now + TARGET_RETRY_INTERVAL
            else:
                self._advance(now)
            return slot, spell == 'alacrity'
        return None

    def wait_time(self, now):
        return min(.02, max(.001, self.next_at - now))

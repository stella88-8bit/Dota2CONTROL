"""Nonblocking combo runner. All steps are gated by fresh GSI data."""
from spell_phrases import SPELLS

ORBS = {name: orbs for name, orbs in SPELLS.values()}
TARGET_RETRY_INTERVAL = .06


class ComboRunner:
    def __init__(self, spells, now):
        self.spells = list(spells)
        self.index = 0
        self.phase = 'choose'
        self.next_at = now
        self.deadline = now + 12
        self.after = None
        self.keys = []
        self.error = None
        self.complete = False
        self.started_at = now
        self.events = []
        self.last_cast_at = None
        self.invoke_at = self.attempt_at = None
        self.prepared_spell = None
        self.prepared_keys = []
        self.prepare_at = now

    def _prepare_next(self, now, slots):
        if self.index + 1 >= len(self.spells):
            return None
        spell = self.spells[self.index + 1]
        expected = 'invoker_' + spell.replace(' ', '_')
        if expected in slots:
            return None
        if self.prepared_spell != spell:
            self.prepared_spell = spell
            self.prepared_keys = list(ORBS[spell])
            self.prepare_at = now
            self.events.append(('preparing', spell, now, None))
        if not self.prepared_keys or now < self.prepare_at:
            return None
        key = self.prepared_keys.pop(0)
        self.prepare_at = now + .012
        return key, False

    def step(self, now, details, *, fresh=True):
        """Return (key, self_target) or None. Missing GSI pauses; deadlines abort."""
        if self.complete or self.error:
            return None
        if now > self.deadline:
            self.error = f'Нет подтверждения или способность недоступна: {self.spells[self.index]}'
            return None
        if not details:
            return None
        if not fresh and self.phase != 'cast_confirm':
            return None
        if self.phase in ('choose', 'orbs') and now < self.next_at:
            return None
        spell = self.spells[self.index]
        expected = 'invoker_' + spell.replace(' ', '_')
        a, b = details.get('ability3', {}), details.get('ability4', {})
        slots = (a.get('name'), b.get('name'))
        if self.phase == 'choose':
            if expected in slots:
                self.prepared_spell = None
                self.prepared_keys = []
                self.phase = 'cast'
            elif details.get('ability5', {}).get('can_cast') is True:
                self.keys = (self.prepared_keys.copy() + ['r'] if self.prepared_spell == spell
                             else list(ORBS[spell] + 'r'))
                self.next_at = max(self.next_at, self.prepare_at) if self.prepared_spell == spell else self.next_at
                self.prepared_spell = None
                self.prepared_keys = []
                self.phase = 'orbs'
            else:
                return None
        if self.phase == 'orbs':
            if now < self.next_at:
                return None
            key = self.keys.pop(0)
            # Keep a short gap so macOS/the game can process each distinct key event.
            self.next_at = now + .012
            if not self.keys:
                self.phase = 'invoke_confirm'
                self.after = now
                self.deadline = now + 5
                self.invoke_at = now
                self.events.append(('invoke', spell, now, None))
            return key, False
        if self.phase == 'invoke_confirm':
            if expected not in slots:
                return None
            self.events.append(('invoked', spell, now, now - self.invoke_at))
            self.phase = 'cast'
        if self.phase == 'cast':
            if expected not in slots:
                self.error = 'Заклинание исчезло из ячейки'
                return None
            index = slots.index(expected)
            ability = (a, b)[index]
            if ability.get('can_cast') is not True or ability.get('cooldown', 0) > 0:
                return None
            self.phase = 'cast_confirm'
            self.after = now
            self.deadline = float('inf') if spell == 'cold snap' else now + 4
            self.next_at = now + (TARGET_RETRY_INTERVAL if spell == 'cold snap' else 0)
            interval = None if self.last_cast_at is None else now - self.last_cast_at
            self.last_cast_at = now
            self.attempt_at = now
            self.events.append(('cast', spell, now, interval))
            return ('d' if index == 0 else 'f'), spell == 'alacrity'
        if self.phase == 'cast_confirm':
            if expected not in slots:
                self.error = 'Ячейка изменилась до подтверждения применения'
                return None
            ability = (a, b)[slots.index(expected)]
            if ability.get('cooldown', 0) <= 0:
                if spell == 'cold snap' and ability.get('can_cast') is True and now >= self.next_at:
                    self.after = now
                    self.attempt_at = now
                    self.next_at = now + TARGET_RETRY_INTERVAL
                    self.events.append(('retry', spell, now, None))
                    return ('d' if slots.index(expected) == 0 else 'f'), False
                return self._prepare_next(now, slots)
            if not fresh:
                return self._prepare_next(now, slots)
            self.events.append(('confirmed', spell, now, now - self.attempt_at))
            self.index += 1
            if self.index == len(self.spells):
                self.complete = True
            else:
                self.phase = 'choose'
                self.after = None
                self.deadline = now + 12
                self.next_at = now
                # Same tick, with the current slots: no fixed inter-spell sleep.
                return self.step(now, details)
        return None

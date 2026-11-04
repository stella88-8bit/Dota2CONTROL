"""Nonblocking combo runner. All steps are gated by fresh GSI data."""
from spell_phrases import SPELLS

ORBS = {name: orbs for name, orbs in SPELLS.values()}


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

    def step(self, now, details):
        """Return (key, self_target) or None. Missing GSI pauses; deadlines abort."""
        if self.complete or self.error:
            return None
        if now > self.deadline:
            self.error = f'Нет подтверждения или способность недоступна: {self.spells[self.index]}'
            return None
        if now < self.next_at or not details:
            return None
        spell = self.spells[self.index]
        expected = 'invoker_' + spell.replace(' ', '_')
        a, b = details.get('ability3', {}), details.get('ability4', {})
        slots = (a.get('name'), b.get('name'))
        if self.phase == 'choose':
            if expected in slots:
                self.phase = 'cast'
            elif details.get('ability5', {}).get('can_cast') is True:
                self.keys = list(ORBS[spell] + 'r')
                self.phase = 'orbs'
            else:
                return None
        if self.phase == 'orbs':
            key = self.keys.pop(0)
            self.next_at = now + .12
            if not self.keys:
                self.phase = 'invoke_confirm'
                self.after = now
                self.deadline = now + 5
            return key, False
        if self.phase == 'invoke_confirm':
            if expected not in slots:
                return None
            self.phase = 'cast'
        if self.phase == 'cast':
            if expected not in slots:
                self.error = 'Заклинание исчезло из ячейки'
                return None
            index = slots.index(expected)
            ability = (a, b)[index]
            if ability.get('can_cast') is not True:
                return None
            self.phase = 'cast_confirm'
            self.after = now
            self.deadline = float('inf') if spell == 'cold snap' else now + 4
            self.next_at = now + (.35 if spell == 'cold snap' else 0)
            return ('d' if index == 0 else 'f'), spell == 'alacrity'
        if self.phase == 'cast_confirm':
            if expected not in slots:
                self.error = 'Ячейка изменилась до подтверждения применения'
                return None
            ability = (a, b)[slots.index(expected)]
            if spell == 'cold snap' and ability.get('cooldown', 0) <= 0 and ability.get('can_cast') is not True:
                return None
            if ability.get('cooldown', 0) <= 0 and ability.get('can_cast') is not False:
                if spell == 'cold snap':
                    self.after = now
                    self.next_at = now + .35
                    return ('d' if slots.index(expected) == 0 else 'f'), False
                return None
            self.index += 1
            if self.index == len(self.spells):
                self.complete = True
            else:
                self.phase = 'choose'
                self.after = None
                self.deadline = now + 12
                self.next_at = now + .25
        return None

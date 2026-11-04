"""Plan spell actions from recognised phrases and current, verified GSI slots."""
from dataclasses import dataclass
from dota_magic.spell_phrases import SPELLS, INVOKE_PHRASE, match_phrase


@dataclass(frozen=True)
class SpellPlan:
    kind: str
    spell: str
    keys: str
    score: float


def slot_for_spell(spell, slots):
    if slots is None or len(slots) != 2:
        return None
    expected = 'invoker_' + spell.replace(' ', '_')
    if slots[0] == expected:
        return 'd'
    if slots[1] == expected:
        return 'f'
    return None


def plan_spell(text, slots):
    phrase, score = match_phrase(text)
    if phrase is None:
        return None
    if slots is None or len(slots) != 2:
        return None
    if phrase == INVOKE_PHRASE:
        return SpellPlan('invoke', 'invoke', 'r', score)
    name, orbs = SPELLS[phrase]
    slot = slot_for_spell(name, slots)
    if slot:
        return SpellPlan('cast', name, slot, score)
    return SpellPlan('prepare', name, orbs + 'r', score)

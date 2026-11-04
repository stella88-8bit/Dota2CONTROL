"""Plan spell actions from recognised phrases and current, verified GSI slots."""
from dataclasses import dataclass
from spell_phrases import SPELLS, INVOKE_PHRASE, match_phrase


@dataclass(frozen=True)
class SpellPlan:
    kind: str
    spell: str
    keys: str
    score: float


def plan_spell(text, slots):
    phrase, score = match_phrase(text)
    if phrase is None:
        return None
    if slots is None or len(slots) != 2:
        return None
    if phrase == INVOKE_PHRASE:
        return SpellPlan('invoke', 'invoke', 'r', score)
    name, orbs = SPELLS[phrase]
    internal_name = 'invoker_' + name.replace(' ', '_')
    if internal_name in slots:
        return SpellPlan('cast', name, 'd' if slots[0] == internal_name else 'f', score)
    return SpellPlan('prepare', name, orbs + 'r', score)

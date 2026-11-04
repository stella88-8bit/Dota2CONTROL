"""Approved voice phrases; recognition and game input are not connected yet."""
import re
from difflib import SequenceMatcher

SPELLS = {
    'обрети хрупкость льда': ('cold snap', 'qqq'),
    'призрак мирота': ('ghost walk', 'qqw'),
    'гибельная стена корикса': ('ice wall', 'qqe'),
    'экстрагирующий мана пульс': ('emp', 'www'),
    'когти торнаруса': ('tornado', 'qww'),
    'рвение эксорта': ('alacrity', 'wwe'),
    'заклятье испепеления харлека': ('sun strike', 'eee'),
    'элементали горя': ('forge spirit', 'qee'),
    'пироклазм бездны': ('chaos meteor', 'wee'),
    'оглушающее трио': ('deafening blast', 'qwe'),
}
INVOKE_PHRASE = 'слова силы'


def identify_phrase(text):
    text = re.sub(r'[^\w\s]', ' ', text.lower()).replace('ё', 'е')
    text = ' '.join(text.split())
    if text == INVOKE_PHRASE:
        return ('invoke', 'r')
    return SPELLS.get(text)


def match_phrase(text, threshold=0.8):
    """Return the best unambiguous phrase only when textual similarity exceeds threshold."""
    text = ' '.join(re.sub(r'[^\w\s]', ' ', text.lower().replace('ё', 'е')).split())
    if not text:
        return None, 0.0
    candidates = list(SPELLS) + [INVOKE_PHRASE]
    ranked = sorted(((SequenceMatcher(None, text, phrase).ratio(), phrase)
                     for phrase in candidates), reverse=True)
    score, phrase = ranked[0]
    if score <= threshold or (len(ranked) > 1 and score == ranked[1][0]):
        return None, score
    return phrase, score

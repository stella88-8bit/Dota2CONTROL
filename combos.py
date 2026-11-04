"""Голосовые фразы и состав прокастов; порядок уточняет планировщик."""
from difflib import SequenceMatcher
import re

COMBOS = {
    'мама я миракл': ('tornado', 'emp', 'chaos meteor', 'deafening blast'),
    'от меня не убежишь': ('ice wall', 'cold snap', 'forge spirit', 'alacrity'),
    'мой любимый 2007 й': ('tornado', 'cold snap', 'sun strike', 'chaos meteor', 'deafening blast'),
    'ремпейдж': ('cold snap', 'tornado', 'emp', 'sun strike', 'chaos meteor', 'forge spirit', 'alacrity'),
}


def match_combo(text):
    text = ' '.join(re.sub(r'[^\w\s]', ' ', text.lower().replace('ё', 'е')).split())
    text = text.replace('rampage', 'ремпейдж').replace('рэмпейдж', 'ремпейдж')
    text = text.replace('две тысячи седьмой', '2007 й').replace('две тысячи седьмого', '2007 й')
    ranked = sorted(((SequenceMatcher(None, text, phrase).ratio(), phrase) for phrase in COMBOS), reverse=True)
    score, phrase = ranked[0]
    if score <= .8 or score == ranked[1][0]:
        return None
    return phrase, COMBOS[phrase], score

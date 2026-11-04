"""Gesture and command logic, independent of camera and keyboard access."""
import math

VOICE_KEYS = {'куас': 'q', 'векс': 'w', 'экзорт': 'e',
              'инвоук': 'r', 'первый': 'd', 'второй': 'f',
              'квас': 'q', 'экспорт': 'e', 'вызов': 'r'}
NAMES = {'q': 'QUAS', 'w': 'WEX', 'e': 'EXORT', 'r': 'INVOKE',
         'd': 'SLOT 1', 'f': 'SLOT 2'}
VOICE_PHRASES = {'ин вок': 'r', 'ин волк': 'r'}


def voice_commands(text):
    words = text.lower().split()
    if 'стоп' in words:
        return ['stop']
    commands = []
    index = 0
    while index < len(words):
        phrase = ' '.join(words[index:index + 2])
        if phrase in VOICE_PHRASES:
            commands.append(VOICE_PHRASES[phrase])
            index += 2
        else:
            if words[index] in VOICE_KEYS:
                commands.append(VOICE_KEYS[words[index]])
            index += 1
    return commands


def classify_hand(hand, width, height):
    p = [(v.x * width, v.y * height) for v in hand]
    distance = lambda a, b: math.dist(p[a], p[b])
    scale = distance(0, 9)
    if scale < 10:
        return None

    def straight(tip, joint, base):
        a = (p[base][0] - p[joint][0], p[base][1] - p[joint][1])
        b = (p[tip][0] - p[joint][0], p[tip][1] - p[joint][1])
        length = math.hypot(*a) * math.hypot(*b)
        return (length > 0 and (a[0]*b[0] + a[1]*b[1]) / length < -0.65
                and distance(0, tip) > distance(0, joint) * 1.12)

    fingers = tuple(straight(t, j, b) for t, j, b in
                    [(8, 6, 5), (12, 10, 9), (16, 14, 13), (20, 18, 17)])
    if distance(4, 8) / scale < 0.35 and fingers[1:] == (True, True, True):
        return 'e'
    if fingers == (True, True, True, True):
        return 'neutral'
    if fingers == (False, False, False, False):
        if straight(4, 3, 2) and abs(p[4][1] - p[2][1]) > scale * 0.45:
            return 'd' if p[4][1] < p[2][1] else 'f'
        return None
    return {(True, False, False, False): 'q',
            (True, True, False, False): 'w',
            (True, False, False, True): 'r',
            }.get(fingers)


class GestureTrigger:
    def __init__(self):
        self.reset()

    def reset(self):
        self.ready = False
        self.last = None
        self.candidate = None
        self.since = 0.0

    def update(self, gesture, now):
        if gesture != self.candidate:
            self.candidate, self.since = gesture, now
        if gesture is None:
            return None  # Losing sight of the hand never rearms a held gesture.
        if now - self.since < (0.15 if gesture == 'neutral' else 0.22):
            return None
        if gesture == 'neutral':
            self.ready, self.last = True, None
        elif self.ready and gesture != self.last:
            self.last = gesture
            return gesture
        return None

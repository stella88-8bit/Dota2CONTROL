"""Explicit stop detection, separate from recoverable speech/audio failures."""
def is_stop_result(result):
    if result.get('text', '').strip().lower() != 'стоп':
        return False
    words = result.get('result', [])
    return len(words) == 1 and words[0].get('word') == 'стоп' and words[0].get('conf', 0) >= 0.9

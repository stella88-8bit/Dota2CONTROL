"""Minimal Valve KeyValues reader for game ability definitions."""


def parse(text: str) -> dict:
    tokens = []
    position = 0
    while position < len(text):
        char = text[position]
        if char.isspace():
            position += 1
        elif text.startswith('//', position):
            end = text.find('\n', position)
            position = len(text) if end < 0 else end + 1
        elif text.startswith('/*', position):
            end = text.find('*/', position + 2)
            if end < 0:
                raise ValueError('Unclosed KeyValues comment')
            position = end + 2
        elif char in '{}':
            tokens.append(char)
            position += 1
        elif char == '"':
            position += 1
            value = []
            while position < len(text):
                char = text[position]
                if char == '"':
                    position += 1
                    break
                if char == '\\' and position + 1 < len(text) and text[position + 1] in ('"', '\\'):
                    position += 1
                    char = text[position]
                value.append(char)
                position += 1
            else:
                raise ValueError('Unclosed KeyValues string')
            tokens.append(''.join(value))
        else:
            end = position
            while end < len(text) and not text[end].isspace() and text[end] not in '{}':
                end += 1
            tokens.append(text[position:end])
            position = end
    index = 0

    def block(nested=False):
        nonlocal index
        result = {}
        while index < len(tokens):
            key = tokens[index]
            index += 1
            if key == '}':
                if not nested:
                    raise ValueError('Unexpected closing brace')
                return result
            if key == '{' or index >= len(tokens):
                raise ValueError('Expected KeyValues key and value')
            value = tokens[index]
            index += 1
            if value == '{':
                value = block(True)
            elif value == '}':
                raise ValueError('Expected value before closing brace')
            if key in result:
                raise ValueError('Duplicate KeyValues key: ' + key)
            result[key] = value
        if nested:
            raise ValueError('Unclosed KeyValues block')
        return result

    return block()

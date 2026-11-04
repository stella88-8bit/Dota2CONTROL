"""Receive Dota state locally and expose recent Invoker slots."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class GSIState:
    def __init__(self):
        self._lock = threading.Lock()
        self._updated = None
        self._slots = None
        self._abilities = None

    def update(self, data):
        hero = data.get('hero')
        abilities = data.get('abilities')
        slots = None
        if isinstance(hero, dict) and hero.get('name') == 'npc_dota_hero_invoker' and isinstance(abilities, dict):
            a, b = abilities.get('ability3'), abilities.get('ability4')
            if isinstance(a, dict) and isinstance(b, dict) and isinstance(a.get('name'), str) and isinstance(b.get('name'), str):
                slots = (a['name'], b['name'])
        with self._lock:
            self._updated = time.monotonic()
            self._slots = slots
            self._abilities = abilities if slots else None

    def details(self, max_age=2, after=None):
        with self._lock:
            if (self._updated is None or time.monotonic() - self._updated > max_age
                    or (after is not None and self._updated <= after)):
                return None
            return self._abilities

    def snapshot(self, max_age=5, after=None):
        with self._lock:
            if (self._updated is None or time.monotonic() - self._updated > max_age
                    or (after is not None and self._updated <= after)):
                return None
            return self._slots


def start_server(state, port=38742):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1_000_000:
                    raise ValueError('invalid size')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError('invalid payload')
                state.update(payload)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'OK')
            except (ValueError, TypeError):
                self.send_error(400)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server

"""Receive Dota state locally and expose recent Invoker slots."""
import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class GSIState:
    def __init__(self):
        self._lock = threading.Lock()
        self._updated = None
        self._slots = None
        self._abilities = None
        self._hero = None
        self.changed = threading.Event()
        self._intervals = deque(maxlen=64)

    def update(self, data):
        hero = data.get('hero')
        abilities = data.get('abilities')
        slots = None
        if isinstance(hero, dict) and hero.get('name') == 'npc_dota_hero_invoker' and isinstance(abilities, dict):
            a, b = abilities.get('ability3'), abilities.get('ability4')
            if isinstance(a, dict) and isinstance(b, dict) and isinstance(a.get('name'), str) and isinstance(b.get('name'), str):
                slots = (a['name'], b['name'])
        with self._lock:
            now = time.monotonic()
            if self._updated is not None:
                self._intervals.append(now - self._updated)
            self._updated = now
            self._slots = slots
            self._abilities = abilities if slots else None
            self._hero = hero if slots else None
        self.changed.set()

    def timing_summary(self):
        with self._lock:
            intervals = sorted(self._intervals)
        if not intervals:
            return 'GSI: недостаточно пакетов для измерения интервала'
        median = intervals[len(intervals) // 2]
        return (f'GSI: интервал пакетов медиана {median*1000:.1f} мс, '
                f'максимум {intervals[-1]*1000:.1f} мс (последние {len(intervals)})')

    def details(self, max_age=2, after=None):
        with self._lock:
            if (self._updated is None or time.monotonic() - self._updated > max_age
                    or (after is not None and self._updated <= after)):
                return None
            return self._abilities

    def read(self, max_age=2):
        """Return data and its receive timestamp atomically for prediction."""
        with self._lock:
            if self._updated is None or time.monotonic() - self._updated > max_age:
                return None, self._updated
            return self._abilities, self._updated

    def read_context(self, max_age=2):
        """Return hero, abilities and receive time from the same GSI packet."""
        with self._lock:
            if self._updated is None or time.monotonic() - self._updated > max_age:
                return None, None, self._updated
            return self._hero, self._abilities, self._updated

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
                self.send_header('Content-Length', '2')
                self.send_header('Connection', 'close')
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

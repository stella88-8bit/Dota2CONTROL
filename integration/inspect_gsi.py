"""Read-only local diagnostic: print hero and ability fields received from Dota."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size <= 0 or size > 1_000_000:
                self.send_error(400)
                return
            data = json.loads(self.rfile.read(size))
            print(json.dumps({'hero': data.get('hero'), 'abilities': data.get('abilities')},
                             ensure_ascii=False, indent=2), flush=True)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
        except (ValueError, TypeError):
            self.send_error(400)


if __name__ == '__main__':
    print('Ожидание данных Dota на 127.0.0.1:38742. Выход: Ctrl+C.', flush=True)
    try:
        HTTPServer(('127.0.0.1', 38742), Handler).serve_forever()
    except KeyboardInterrupt:
        print('\nОстановлено.')

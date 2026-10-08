"""Loopback browser transport for ChatService, with origin and token checks."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import secrets
from urllib.parse import parse_qs, urlsplit
import webbrowser

from .chat import ChatService
from .domain import ForgeError


class ChatServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True

    def __init__(self, service: ChatService, port: int = 0):
        if type(port) is not int or not 0 <= port <= 65535:
            raise ForgeError('Chat port must be between 0 and 65535.')
        self.service = service
        self.token = secrets.token_urlsafe(32)
        super().__init__(('127.0.0.1', port), ChatHandler)
        self.origin = f'http://127.0.0.1:{self.server_port}'
        self.url = self.origin + '/#token=' + self.token


class ChatHandler(BaseHTTPRequestHandler):
    server: ChatServer

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *args):
        # URLs, tokens, and conversation contents never go into access logs.
        pass

    def _reply(self, status: int, data, content_type: str = 'application/json'):
        body = json.dumps(data, ensure_ascii=False).encode() if content_type == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # The service has already persisted the turn.

    def _allowed(self, *, api=False) -> bool:
        host = urlsplit(self.server.origin).netloc
        if self.headers.get('Host') != host or self.headers.get('Origin', self.server.origin) != self.server.origin:
            self._reply(403, {'error': 'Only the local chat window can access this server.'})
            return False
        if api and not secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + self.server.token):
            self._reply(401, {'error': 'Open the chat URL printed in the terminal to authenticate.'})
            return False
        return True

    def do_GET(self):
        path = urlsplit(self.path)
        if not self._allowed(api=path.path.startswith('/api/')):
            return
        assets = {'/': ('chat.html', 'text/html; charset=utf-8'),
                  '/chat.css': ('chat.css', 'text/css; charset=utf-8'),
                  '/chat.js': ('chat.js', 'text/javascript; charset=utf-8')}
        if path.path in assets:
            name, mime = assets[path.path]
            self._reply(200, files('solar_forge').joinpath('web', name).read_bytes(), mime)
            return
        try:
            if path.path == '/api/config':
                config = self.server.service.config
                self._reply(200, {'provider': config.kind, 'model': config.model,
                                  'project': self.server.service.workspace.root.name})
            elif path.path == '/api/sessions':
                self._reply(200, {'sessions': self.server.service.list()})
            elif path.path == '/api/session':
                self._reply(200, self.server.service.get(parse_qs(path.query).get('id', [''])[0]))
            else:
                self._reply(404, {'error': 'Not found.'})
        except (ForgeError, OSError) as exc:
            self._reply(400, {'error': str(exc)})

    def do_POST(self):
        if not self._allowed(api=True):
            return
        try:
            if self.headers.get('Content-Type') != 'application/json':
                self._reply(415, {'error': 'Use application/json.'})
                return
            length = int(self.headers.get('Content-Length', '0'))
            limit = self.server.service.config.max_file_bytes * 6 + 10000
            if not 0 < length <= limit or self.headers.get('Transfer-Encoding'):
                self._reply(413, {'error': 'Request body is missing or too large.'})
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('Incomplete body')
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError('Expected object')
            path = urlsplit(self.path).path
            if path == '/api/sessions' and body == {}:
                self._reply(201, self.server.service.new())
            elif path == '/api/message' and set(body) == {'id', 'message'} and isinstance(body['id'], str):
                self._reply(200, self.server.service.send(body['id'], body['message']))
            elif path == '/api/retry' and set(body) == {'id'} and isinstance(body['id'], str):
                self._reply(200, self.server.service.send(body['id'], retry=True))
            else:
                self._reply(400, {'error': 'Unknown action or invalid arguments.'})
        except (ValueError, UnicodeError):
            self._reply(400, {'error': 'Request must contain a valid JSON object.'})
        except (ForgeError, OSError) as exc:
            self._reply(409, {'error': str(exc)})
        except Exception:
            self._reply(500, {'error': 'Chat reply failed. Check the project audit and retry the pending message.'})


def serve_chat(service: ChatService, *, port: int = 0, open_browser: bool = True) -> None:
    with ChatServer(service, port) as server:
        print(f'Forge chat · {service.config.kind} / {service.config.model}', flush=True)
        print(f'Open {server.url}', flush=True)
        print('Keep this terminal open. Ctrl-C stops chat after active replies are saved.', flush=True)
        if open_browser:
            try:
                if not webbrowser.open(server.url, new=1):
                    print('Browser did not open automatically; use the URL above.', flush=True)
            except webbrowser.Error:
                print('Browser did not open automatically; use the URL above.', flush=True)
        try:
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            print('\nClosing chat. Saving any active replies…', flush=True)

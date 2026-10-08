from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from solar_forge.chat import ChatService
from solar_forge.chat_server import ChatServer, serve_chat
from solar_forge.cli import main
from solar_forge.domain import Config, CONFIG_TEMPLATE, ForgeError
from solar_forge.workspace import Workspace


class TextProvider:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def complete(self, system, messages):
        self.calls.append((system, messages))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


class ChatServiceTests(unittest.TestCase):
    def test_multiturn_context_and_persisted_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            ws.write('README.md', 'Use UTC for invoice dates.')
            ws.write('request.md', 'Draft request under discussion.')
            provider = TextProvider('Hello!', 'Use UTC.')
            service = ChatService(ws, Config(model='test-model'), provider)
            session = service.new()
            result = service.send(session['id'], 'Hello')
            self.assertEqual(result['title'], 'Hello')
            result = service.send(session['id'], 'Which timezone?')
            self.assertEqual(len(result['messages']), 4)
            self.assertIn('Use UTC for invoice dates', provider.calls[0][0])
            self.assertIn('Draft request under discussion', provider.calls[0][0])
            self.assertEqual(len(provider.calls[1][1]), 3)
            reopened = ChatService(ws, Config(model='test-model'), TextProvider())
            self.assertEqual(reopened.get(session['id'])['messages'], result['messages'])
            self.assertEqual(reopened.list()[0]['id'], session['id'])
            audit = ws.root / session['id']
            self.assertIn('Which timezone?', (audit / 'transcript.md').read_text())
            self.assertEqual(len(list((audit / 'calls').glob('*-output.txt'))), 2)

    def test_failed_turn_retries_without_duplicate_user_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            provider = TextProvider(ForgeError('Connection failed.'), 'Recovered')
            service = ChatService(ws, Config(model='test-model'), provider)
            session = service.new()
            with self.assertRaises(ForgeError):
                service.send(session['id'], 'My question')
            pending = service.get(session['id'])
            self.assertEqual(pending['pending_message'], 'My question')
            self.assertEqual(pending['messages'], [])
            with self.assertRaises(ForgeError):
                service.send(session['id'], 'Another question')
            result = service.send(session['id'], retry=True)
            self.assertEqual([m['role'] for m in result['messages']], ['user', 'assistant'])
            self.assertIsNone(result['pending_message'])
            self.assertEqual(provider.calls[0][1], provider.calls[1][1])

    def test_limits_model_mismatch_and_no_pending_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            service = ChatService(ws, Config(model='test-model', max_turns=1), TextProvider('answer'))
            session = service.new()
            with self.assertRaises(ForgeError):
                service.send(session['id'], retry=True)
            with self.assertRaises(ForgeError):
                service.send(session['id'], '')
            other = ChatService(ws, Config(model='different'), TextProvider())
            with self.assertRaises(ForgeError):
                other.send(session['id'], 'hello')
            service.send(session['id'], 'hello')
            with self.assertRaises(ForgeError):
                service.send(session['id'], 'second turn')


class ChatHTTPTests(unittest.TestCase):
    def test_http_auth_origin_assets_and_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = ChatService(Workspace(Path(tmp)), Config(model='test-model'), TextProvider('<script>alert(1)</script>'))
            with ChatServer(service) as server:
                thread = Thread(target=server.serve_forever, daemon=True)
                thread.start()
                def fetch(path, body=None, headers=None):
                    request = Request(server.origin + path, data=json.dumps(body).encode() if body is not None else None,
                                      headers={'Authorization': 'Bearer ' + server.token,
                                               'Content-Type': 'application/json', 'Origin': server.origin, **(headers or {})})
                    with urlopen(request, timeout=5) as response:
                        return response.status, response.headers, response.read()
                try:
                    code, headers, html = fetch('/')
                    self.assertEqual(code, 200)
                    self.assertIn(b'What are we building?', html)
                    self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
                    self.assertNotIn(server.token.encode(), html)
                    self.assertNotIn(b'api_key', fetch('/api/config')[2])
                    self.assertIn(b'textContent = message.content', fetch('/chat.js')[2])
                    for overrides in ({'Authorization': ''}, {'Origin': 'https://evil.example'}, {'Host': 'evil.example'}):
                        with self.assertRaises(HTTPError) as error:
                            fetch('/api/config', headers=overrides)
                        self.assertIn(error.exception.code, (401, 403))
                        error.exception.close()
                    session = json.loads(fetch('/api/sessions', {})[2])
                    result = json.loads(fetch('/api/message', {'id': session['id'], 'message': 'hello'})[2])
                    self.assertEqual(result['messages'][-1]['content'], '<script>alert(1)</script>')
                    self.assertEqual(len(json.loads(fetch('/api/sessions')[2])['sessions']), 1)
                    with self.assertRaises(HTTPError) as error:
                        fetch('/api/message', {'id': session['id'], 'message': 'hello', 'extra': 'x'})
                    self.assertEqual(error.exception.code, 400)
                    error.exception.close()
                finally:
                    server.shutdown()
                    thread.join(timeout=2)

    def test_cli_chat_uses_selected_model_and_browser_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.forge').mkdir()
            (root / '.forge/config.toml').write_text(CONFIG_TEMPLATE)
            with patch('solar_forge.cli.serve_chat') as serve, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = main(['--project', tmp, 'chat', '--model', 'installed-model', '--no-browser', '--port', '8765'])
            self.assertEqual(result, 0)
            self.assertEqual(serve.call_args.args[0].config.model, 'installed-model')
            self.assertEqual(serve.call_args.kwargs, {'port': 8765, 'open_browser': False})

    def test_launcher_opens_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = ChatService(Workspace(Path(tmp)), Config(model='test-model'), TextProvider())
            with patch.object(ChatServer, 'serve_forever', side_effect=KeyboardInterrupt), \
                    patch('solar_forge.chat_server.webbrowser.open', return_value=True) as browser, redirect_stdout(StringIO()):
                serve_chat(service)
            self.assertTrue(browser.call_args.args[0].startswith('http://127.0.0.1:'))
            self.assertIn('/#token=', browser.call_args.args[0])
            self.assertEqual(browser.call_args.kwargs, {'new': 1})

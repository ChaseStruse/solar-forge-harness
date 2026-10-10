from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from solar_forge.requests import DEFAULT_REQUEST, read_request, write_request
from solar_forge.chat import ChatService
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
            write_request(ws, DEFAULT_REQUEST, 'Draft request under discussion.')
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


class ChatCLITests(unittest.TestCase):
    def test_cli_chat_uses_selected_model_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.forge').mkdir()
            (root / '.forge/config.toml').write_text(CONFIG_TEMPLATE)
            with patch('solar_forge.terminal_chat.run_terminal_chat') as run, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = main(['--project', tmp, 'chat', '--model', 'installed-model', '--resume', 'saved-chat'])
            self.assertEqual(result, 0)
            self.assertEqual(run.call_args.args[0].config.model, 'installed-model')
            self.assertEqual(run.call_args.kwargs, {'resume': 'saved-chat'})

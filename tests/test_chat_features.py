import json
from pathlib import Path
import tempfile
import unittest

from solar_forge.audit import Audit
from solar_forge.chat import ChatService
from solar_forge.domain import Config
from solar_forge.requests import DEFAULT_REQUEST, read_request, write_request
from solar_forge.workspace import Workspace
from test_foundation import REQUEST
from test_chat import TextProvider


class ChatFeatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Workspace(Path(self.tmp.name))
        write_request(self.ws, DEFAULT_REQUEST, REQUEST + '\n## Extra\nKeep this.\n')
        self.service = ChatService(self.ws, Config(model='test'), TextProvider())
        self.session = self.service.new()['id']

    def command(self, text):
        result = self.service.command(self.session, text)
        self.assertIsNone(result['command_error'])
        return result

    def test_pick_edit_and_preserve_extra_sections_and_conflict_check(self):
        listing = self.command('/requests')
        self.assertIn('Add billing export', listing['messages'][-1]['content'])
        self.command('/select 1')
        self.command('/edit-request')
        self.command('/edit description Updated export.')
        self.command('/edit title Better billing')
        self.command('/save-request')
        text = read_request(self.ws, DEFAULT_REQUEST)
        self.assertIn('Updated export.', text)
        self.assertIn('## Extra\nKeep this.', text)
        self.assertIn('# Request: Better billing', text)
        self.command('/edit-request')
        write_request(self.ws, DEFAULT_REQUEST, text + '\nExternal change')
        result = self.service.command(self.session, '/save-request')
        self.assertIn('changed while', result['command_error'])

    def test_edit_partial_draft_keeps_other_answers(self):
        self.command('/request New idea')
        self.command('Description')
        self.command('/edit description Better description')
        self.command('Technical details')
        self.command('It works')
        self.command('/save-request')
        text = read_request(self.ws, 'agentic_audit/requests/new-idea/request.md')
        self.assertIn('Better description', text)
        self.assertIn('Technical details', text)

    def test_context_and_continuation_need_no_model_calls(self):
        self.command('/requests')
        self.command('/select 1')
        self.command('/edit-request')
        result = self.command('/context')
        self.assertIn('Prompt before your next message:', result['messages'][-1]['content'])
        self.assertIn(DEFAULT_REQUEST, result['messages'][-1]['content'])
        old = Audit.open(self.ws, self.session).load()
        following = self.service.command(self.session, '/continue')
        self.assertNotEqual(following['id'], self.session)
        state = Audit.open(self.ws, following['id']).load()
        self.assertEqual(state['parent_chat'], self.session)
        self.assertEqual(state['request_path'], DEFAULT_REQUEST)
        self.assertEqual(state['request_draft'], old['request_draft'])
        self.assertNotIn('reviewed_plan', state)
        self.assertEqual(state['turns'], 0)
        self.assertEqual(Audit.open(self.ws, self.session).load()['messages'], old['messages'])
        self.assertEqual(self.service.provider.calls, [])

    def test_stream_cancellation_saves_partial_without_committing_reply(self):
        from threading import Event
        from solar_forge.domain import ForgeError
        stop = Event()
        class StreamProvider:
            def stream(self, system, messages):
                yield 'First'
                raise AssertionError('Cancelled stream must not request another chunk')
        self.service.provider = StreamProvider()
        chunks = []
        def receive(text):
            chunks.append(text)
            stop.set()
        with self.assertRaisesRegex(ForgeError, 'Stopped'):
            self.service.send(self.session, 'hello', on_chunk=receive, cancelled=stop.is_set)
        self.assertEqual(chunks, ['First'])
        state = self.service.get(self.session)
        self.assertEqual(state['pending_message'], 'hello')
        self.assertEqual(state['messages'], [])
        audit = Audit.open(self.ws, self.session)
        partial = list((audit.path / 'calls').glob('*-partial.txt'))
        self.assertEqual(partial[0].read_text(), 'First')

    def test_ollama_stream_requires_completion_and_rejects_bad_data(self):
        from io import BytesIO
        from unittest.mock import patch
        from solar_forge.providers import HTTPProvider
        from solar_forge.domain import ForgeError
        provider = HTTPProvider(Config(model='test'))
        good = b'{"message":{"content":"Hi"},"done":false}\n{"done":true}\n'
        for data, valid in [(good, True), (good.splitlines(keepends=True)[0], False),
                            (b'{"message":{"content":4}}\n', False), (b'not-json\n', False)]:
            with patch('solar_forge.providers.build_opener') as opener:
                opener.return_value.open.return_value = BytesIO(data)
                if valid:
                    self.assertEqual(list(provider.stream('system', [])), ['Hi'])
                else:
                    with self.assertRaises(ForgeError):
                        list(provider.stream('system', []))

    def test_coding_stop_preserves_pending_action_without_writing(self):
        from solar_forge.agent import approve, run
        from solar_forge.workflow import prepare, plan
        from solar_forge.domain import ForgeError
        from test_workflow import ScriptedProvider
        from threading import Event
        cfg = self.service.config
        audit = prepare(self.ws, cfg, DEFAULT_REQUEST, ScriptedProvider({'questions': []}))
        plan(self.ws, cfg, audit, ScriptedProvider({'plan': '# Plan'}))
        approve(audit)
        stop = Event()
        class StopProvider:
            def complete(self, system, messages):
                stop.set()
                return json.dumps({'tool': 'write_file', 'path': 'app.py', 'content': 'value = 1'})
        with self.assertRaisesRegex(ForgeError, 'Stopped'):
            run(self.ws, cfg, audit, StopProvider(), cancelled=stop.is_set)
        self.assertFalse((self.ws.root / 'app.py').exists())
        self.assertEqual(audit.load()['pending_action']['path'], 'app.py')
        self.assertEqual(audit.load()['status'], 'interrupted')

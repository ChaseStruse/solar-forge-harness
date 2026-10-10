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

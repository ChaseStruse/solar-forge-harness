from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from solar_forge.audit import Audit
from solar_forge.domain import Config, ForgeError, Request
from solar_forge.progress import read_progress, format_progress, update_progress, with_progress
from solar_forge.providers import HTTPProvider, ProviderText, normalize_usage
from solar_forge.workflow import call
from solar_forge.workspace import Workspace
from test_foundation import REQUEST
from test_chat import TextProvider


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audit = Audit.create(Workspace(Path(self.tmp.name)), Request.parse(REQUEST))
        self.at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def event(self, kind, seconds=0, **details):
        update_progress(self.audit, {'at': (self.at + timedelta(seconds=seconds)).isoformat(),
                                     'type': kind, **details})

    def test_elapsed_time_live_and_stopped_and_unknown_usage(self):
        self.event('provider_call_started')
        snapshot = read_progress(self.audit)
        text = format_progress(snapshot, live=True, now=(self.at + timedelta(seconds=65)).isoformat())
        self.assertIn('01:05 active', text)
        self.assertIn('Waiting for model', text)
        self.assertIn('unavailable', text)
        self.assertIn('Last recorded', format_progress(snapshot))
        self.event('provider_call_finished', seconds=5, usage={'input_tokens': 10, 'output_tokens': 2})
        snapshot = read_progress(self.audit)
        self.assertEqual(snapshot['active_seconds'], 5)
        self.assertIn('10 in / 2 out', format_progress(snapshot))
        self.event('provider_call_started', seconds=100)
        self.event('provider_call_failed', seconds=102)
        snapshot = read_progress(self.audit)
        self.assertEqual(snapshot['active_seconds'], 7)
        self.assertIn('(partial)', format_progress(snapshot))
        self.assertIn('Model call failed', format_progress(snapshot))

    def test_actual_file_changes_checks_and_staleness(self):
        self.event('tool_attempted', turn=1, action={'tool': 'write_file', 'path': 'app.py', 'content': 'PRIVATE BODY'})
        self.assertIn('Writing: app.py', read_progress(self.audit)['action'])
        self.assertNotIn('PRIVATE BODY', (self.audit.path / 'progress.json').read_text())
        self.event('file_written', path='app.py', changed=True)
        self.event('file_written', path='app.py', changed=True)
        self.event('file_written', path='unchanged.py', changed=False)
        self.event('tool_result', seconds=1, result={})
        self.event('verification_started', seconds=2, name='tests')
        self.event('verification_finished', seconds=3, name='tests', status='failed', exit_code=1)
        self.event('tool_result', seconds=3, result={'name': 'tests', 'status': 'failed', 'exit_code': 1})
        self.event('file_written', seconds=4, path='fixed.py', changed=True)
        result = read_progress(self.audit)
        self.assertEqual(result['changed_files'], ['app.py', 'fixed.py'])
        self.assertIn('tests: failed (exit 1); rerun after edits', format_progress(result))
        self.event('review_requested', seconds=5)
        self.event('tool_result', seconds=5, result={'status': 'review_required'})
        self.assertEqual(read_progress(self.audit)['action'], 'Review required')

    def test_observer_is_optional_isolated_and_does_not_change_state(self):
        before = self.audit.load()
        received = []
        with_progress(received.append, self.audit.event, 'provider_call_started', call_id='one')
        self.audit.event('provider_call_finished', call_id='one')
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]['action'], 'Waiting for model')
        def broken(_):
            raise RuntimeError('display failure')
        with_progress(broken, self.audit.event, 'plan_generated')
        self.assertEqual(self.audit.load(), before)
        self.assertEqual(read_progress(self.audit)['action'], 'Plan ready for review')

    def test_legacy_corrupt_snapshot_and_crash_recovery(self):
        path = self.audit.path / 'progress.json'
        path.unlink()
        self.assertIsNone(read_progress(self.audit))
        self.assertIn('unavailable', format_progress(None))
        path.write_text('{"version": 1}')
        self.assertIsNone(read_progress(self.audit))
        self.event('provider_call_started')
        self.assertTrue(read_progress(self.audit)['history_limited'])
        self.event('execution_started', seconds=10000)
        self.assertEqual(read_progress(self.audit)['active_seconds'], 0)
        self.assertIsNone(read_progress(self.audit)['active_since'])
        # A corrupt progress sidecar cannot prevent the authoritative event.
        path.write_text('not json')
        self.audit.event('review_requested')
        self.assertEqual(read_progress(self.audit)['action'], 'Review required')

    def test_call_usage_does_not_leak_between_calls_and_is_audited(self):
        provider = TextProvider(ProviderText('answer', {'input_tokens': 12, 'output_tokens': 4}), 'plain', ForgeError('offline'))
        self.assertEqual(call(self.audit, provider, 'system', []), 'answer')
        self.assertEqual(call(self.audit, provider, 'system', []), 'plain')
        with self.assertRaises(ForgeError):
            call(self.audit, provider, 'system', [])
        usages = [json.loads(path.read_text()) for path in (self.audit.path / 'calls').glob('*-usage.json')]
        self.assertEqual(usages.count(None), 2)
        result = read_progress(self.audit)['usage']
        self.assertEqual((result['input_tokens'], result['output_tokens'], result['calls']), (12, 4, 3))
        self.assertIn('(partial)', format_progress(read_progress(self.audit)))

    def test_stream_usage_without_visible_final_text(self):
        provider = HTTPProvider(Config(model='test'))
        data = b'{"message":{"content":"Hi"},"done":false}\n{"done":true,"prompt_eval_count":7,"eval_count":2}\n'
        with patch('solar_forge.providers.build_opener') as opener:
            opener.return_value.open.return_value = BytesIO(data)
            visible = []
            self.assertEqual(call(self.audit, provider, 'system', [], on_chunk=visible.append), 'Hi')
        self.assertEqual(visible, ['Hi'])
        self.assertEqual(read_progress(self.audit)['usage']['input_tokens'], 7)

    @patch.dict(os.environ, {'OPENAI_API_KEY': 'private', 'ANTHROPIC_API_KEY': 'private'})
    def test_provider_fields_and_cache_tokens(self):
        fixtures = {
            'openai': {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'ok'}]}],
                       'usage': {'input_tokens': 10, 'output_tokens': 4, 'input_tokens_details': {'cached_tokens': 5}}},
            'anthropic': {'content': [{'type': 'text', 'text': 'ok'}],
                          'usage': {'input_tokens': 3, 'cache_creation_input_tokens': 2, 'cache_read_input_tokens': 5, 'output_tokens': 4}},
            'compatible': {'choices': [{'message': {'content': 'ok'}}],
                           'usage': {'prompt_tokens': 10, 'completion_tokens': 4}},
            'ollama': {'message': {'content': 'ok'}, 'prompt_eval_count': 10, 'eval_count': 4}}
        for kind, data in fixtures.items():
            with self.subTest(kind=kind), patch('solar_forge.providers.post_json', return_value=data):
                answer = HTTPProvider(Config(kind=kind, model='test')).complete('system', [])
                self.assertEqual(answer, 'ok')
                self.assertEqual(answer.usage, {'input_tokens': 10, 'output_tokens': 4})

    def test_invalid_and_partial_usage_and_failed_response_counts(self):
        for value in [True, -1, 1.5, '7', None]:
            self.assertIsNone(normalize_usage('openai', {'usage': {'input_tokens': value}}))
        self.assertEqual(normalize_usage('openai', {'usage': {'input_tokens': 0}}),
                         {'input_tokens': 0, 'output_tokens': None})
        provider = HTTPProvider(Config(kind='compatible', model='test'))
        data = {'choices': [{'finish_reason': 'length', 'message': {'content': 'partial'}}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
        with patch('solar_forge.providers.post_json', return_value=data), self.assertRaises(ForgeError):
            call(self.audit, provider, 'system', [])
        result = read_progress(self.audit)
        self.assertEqual(result['usage']['output_tokens'], 5)
        self.assertEqual(result['action'], 'Model call failed')

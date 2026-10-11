import json
from pathlib import Path
import tempfile
import unittest

from solar_forge.audit import Audit
from solar_forge.chat import ChatService
from solar_forge.domain import Config, ForgeError
from solar_forge.requests import DEFAULT_REQUEST, write_request
from solar_forge.workspace import Workspace
from test_chat import TextProvider
from test_foundation import REQUEST
from test_workflow import QUESTION


class ContinuousWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.ws = Workspace(Path(temporary.name))
        write_request(self.ws, DEFAULT_REQUEST, REQUEST)

    def service(self, *responses):
        service = ChatService(self.ws, Config(model='test'), TextProvider(*responses))
        return service, service.new()['id']

    def test_start_builds_and_reviews_plan_but_never_approves(self):
        service, session = self.service(json.dumps({'questions': []}), json.dumps({'plan': '# Plan\nInspect files.'}),
                                        json.dumps({'tool': 'finish', 'summary': 'Reviewed.', 'verification': 'Manual review.'}))
        result = service.command(session, '/start')
        self.assertIsNone(result['command_error'])
        run = Audit.open(self.ws, result['workflow_run'])
        self.assertEqual(run.load()['status'], 'planned')
        self.assertIsNotNone(result['reviewed_plan'])
        self.assertFalse(run.load().get('approved_plan'))
        self.assertEqual(len(service.provider.calls), 2)
        again = service.command(session, '/next')
        self.assertEqual(again['workflow_run'], result['workflow_run'])
        self.assertEqual(len(service.provider.calls), 2)
        approved = service.command(session, '/approve')
        self.assertIsNone(approved['command_error'])
        self.assertEqual(run.load()['status'], 'review_required')

    def test_questions_and_advice_lead_directly_to_plan_after_last_answer(self):
        service, session = self.service(json.dumps(QUESTION), 'Use UTC.', json.dumps({'plan': '# Plan\nUse UTC.'}))
        result = service.command(session, '/start')
        self.assertEqual(result['input_mode'], 'answer')
        self.assertEqual(len(service.provider.calls), 1)
        service.send(session, 'Which timezone?')
        run = Audit.open(self.ws, result['workflow_run'])
        self.assertIsNone(run.load()['questions'][0]['answer'])
        result = service.command(session, 'UTC')
        self.assertIsNone(result['command_error'])
        self.assertEqual(run.load()['questions'][0]['answer'], 'UTC')
        self.assertEqual(run.load()['status'], 'planned')
        self.assertIsNone(result['input_mode'])
        self.assertFalse(run.load().get('approved_plan'))

    def test_next_retries_failed_plan_without_duplicate_discovery_or_run(self):
        service, session = self.service(json.dumps({'questions': []}), ForgeError('Provider timed out'), json.dumps({'plan': '# Plan\nInspect.'}))
        failed = service.command(session, '/start')
        self.assertIn('timed out', failed['command_error'])
        run = Audit.open(self.ws, failed['workflow_run'])
        self.assertEqual(run.load()['status'], 'ready_to_plan')
        self.assertIn('/next', failed['workflow_hint'])
        result = service.command(session, '/next')
        self.assertIsNone(result['command_error'])
        self.assertEqual(result['workflow_run'], failed['workflow_run'])
        self.assertEqual(run.load()['status'], 'planned')
        self.assertEqual(len(service.provider.calls), 3)
        self.assertEqual(len([audit for audit in Audit.discover(self.ws) if audit.load().get('run_kind') != 'chat']), 1)

    def test_stop_between_preparation_and_planning_saves_resumable_state(self):
        service, session = self.service(json.dumps({'questions': []}), json.dumps({'plan': '# Plan\nInspect.'}))
        stopped = service.command(session, '/start', cancelled=lambda: bool(service.provider.calls))
        self.assertIn('Stopped by user', stopped['command_error'])
        self.assertEqual(len(service.provider.calls), 1)
        run = Audit.open(self.ws, stopped['workflow_run'])
        self.assertEqual(run.load()['status'], 'ready_to_plan')
        resumed = service.command(session, '/next')
        self.assertIsNone(resumed['command_error'])
        self.assertEqual(run.load()['status'], 'planned')

    def test_changed_request_does_not_trigger_model_calls_on_resume(self):
        service, session = self.service(ForgeError('Provider timed out'))
        failed = service.command(session, '/start')
        write_request(self.ws, DEFAULT_REQUEST, REQUEST + '\nChanged details.\n')
        result = service.command(session, '/next')
        self.assertIn('/start "', result['command_error'])
        self.assertEqual(len(service.provider.calls), 1)
        self.assertEqual(result['workflow_run'], failed['workflow_run'])

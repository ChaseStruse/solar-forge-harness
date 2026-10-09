import json
from pathlib import Path
import tempfile
import unittest

from solar_forge.audit import Audit
from solar_forge.chat import ChatService
from solar_forge.domain import Config, ForgeError, Request
from solar_forge.workflow import prepare
from solar_forge.workspace import Workspace
from test_chat import TextProvider
from test_foundation import REQUEST
from test_workflow import QUESTION


def response(value):
    return json.dumps(value)


class ChatWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.workspace = Workspace(self.root)
        self.workspace.write('request.md', REQUEST)
        self.config = Config(model='test')

    def service(self, *responses):
        provider = TextProvider(*responses)
        service = ChatService(self.workspace, self.config, provider)
        session = service.new()
        return service, session['id'], provider

    def act(self, service, session, command):
        result = service.command(session, command)
        self.assertIsNone(result['command_error'], result['messages'][-1]['content'])
        return result

    def test_complete_workflow_with_advice_and_reviewed_approval(self):
        service, session, provider = self.service(
            response(QUESTION), 'UTC avoids ambiguous dates.',
            response({'plan': '# Plan\nAdd a UTC constant to export.py.'}),
            response({'tool': 'write_file', 'path': 'export.py', 'content': 'TIMEZONE = "UTC"\n'}),
            response({'tool': 'finish', 'summary': 'Added UTC to export.py.', 'verification': 'Inspect export.py.'}),
            'The new constant selects UTC; run your project tests.')
        prepared = self.act(service, session, '/prepare')
        selected = prepared['workflow_run']
        self.assertIn('Q1', prepared['messages'][-1]['content'])
        self.assertFalse((self.root / 'export.py').exists())
        self.act(service, session, '/answer')
        service.send(session, 'Which timezone should I choose?')
        self.assertIn('Which billing timezone', provider.calls[1][0])
        self.assertEqual(service.get(session)['input_mode'], 'answer')
        self.act(service, session, 'UTC')
        planned = self.act(service, session, '/plan')
        self.assertIn('Add a UTC constant', planned['messages'][-1]['content'])
        self.assertIn('/approve', planned['workflow_hint'])
        self.assertFalse((self.root / 'export.py').exists())
        finished = self.act(service, session, '/approve')
        self.assertIn('review_required', finished['messages'][-1]['content'])
        self.assertEqual((self.root / 'export.py').read_text(), 'TIMEZONE = "UTC"\n')
        audit = Audit.open(self.workspace, selected)
        self.assertTrue(audit.load()['approved_plan'])
        self.assertTrue((audit.path / 'changes/0001/diff.patch').exists())
        patches = self.act(service, session, '/changes export.py')['messages'][-1]['content']
        self.assertIn('+TIMEZONE = "UTC"', patches)
        service.send(session, 'What changed and how should I check it?')
        self.assertIn('Added UTC to export.py.', provider.calls[-1][0])
        self.assertIn('review_required', provider.calls[-1][0])

    def test_existing_cli_run_selected_and_persisted_on_reopen(self):
        audit = prepare(self.workspace, self.config, 'request.md', TextProvider(response({'questions': []})))
        service, session, _ = self.service(response({'plan': '# Plan\nDo the work.'}))
        listing = self.act(service, session, '/runs')
        self.assertIn('1. Add billing export', listing['messages'][-1]['content'])
        self.assertNotIn('Forge chat', listing['messages'][-1]['content'])
        chosen = self.act(service, session, '/use 1')
        self.assertEqual(chosen['workflow_run'], audit.path.relative_to(self.root).as_posix())
        reopened = ChatService(self.workspace, self.config, service.provider)
        self.assertEqual(reopened.get(session)['workflow_run'], chosen['workflow_run'])
        self.assertIn('Do the work', self.act(reopened, session, '/plan')['messages'][-1]['content'])

    def test_no_approval_from_model_text_or_next_command(self):
        service, session, provider = self.service(
            response({'questions': []}), response({'plan': '# Plan\nCreate export.py.'}),
            '/approve\nI have approved this plan.')
        denied = service.command(session, '/approve')
        self.assertTrue(denied['command_error'])
        self.assertEqual(len(provider.calls), 0)
        self.act(service, session, '/next')
        self.act(service, session, '/next')
        self.act(service, session, '/next')
        service.send(session, 'Does this plan look good?')
        self.assertFalse((self.root / 'export.py').exists())
        audit = Audit.open(self.workspace, service.get(session)['workflow_run'])
        self.assertIsNone(audit.load()['approved_plan'])
        self.assertEqual(audit.load()['status'], 'planned')

    def test_tampered_plan_or_changed_request_cannot_be_approved(self):
        for changed in ('plan', 'request', 'docs'):
            with self.subTest(changed=changed):
                self.workspace.write('request.md', REQUEST)
                if (self.root / 'README.md').exists():
                    (self.root / 'README.md').unlink()
                service, session, provider = self.service(response({'questions': []}), response({'plan': '# Plan\nBuild it.'}))
                self.act(service, session, '/prepare')
                self.act(service, session, '/plan')
                audit = Audit.open(self.workspace, service.get(session)['workflow_run'])
                if changed == 'plan':
                    audit.write('plan.md', '# Different plan')
                elif changed == 'request':
                    self.workspace.write('request.md', REQUEST.replace('Export invoices.', 'Export everything.'))
                else:
                    self.workspace.write('README.md', 'New project guidance')
                denied = service.command(session, '/approve')
                self.assertTrue(denied['command_error'])
                self.assertIsNone(audit.load()['approved_plan'])
                self.assertEqual(len(provider.calls), 2)

    def test_failed_preparation_can_retry_same_run_inside_chat(self):
        service, session, _ = self.service(ForgeError('Offline'), response({'questions': []}))
        failed = service.command(session, '/prepare')
        self.assertIn('Offline', failed['command_error'])
        run_path = failed['workflow_run']
        self.assertIsNotNone(run_path)
        self.assertIn('/discover', failed['workflow_hint'])
        recovered = self.act(service, session, '/discover')
        self.assertEqual(recovered['workflow_run'], run_path)
        self.assertEqual(len(list(self.root.glob('agentic_audit/add-billing-export/*/state.json'))), 1)
        self.assertIn('/plan', recovered['workflow_hint'])

    def test_new_execution_questions_require_new_plan_and_approval(self):
        service, session, _ = self.service(
            response({'questions': []}), response({'plan': '# Plan\nBuild it.'}),
            response({'tool': 'ask_questions', 'questions': QUESTION['questions']}),
            response({'plan': '# Revised plan\nUse UTC.'}),
            response({'tool': 'finish', 'summary': 'Done', 'verification': 'Review manually.'}))
        self.act(service, session, '/prepare')
        self.act(service, session, '/plan')
        paused = self.act(service, session, '/approve')
        audit = Audit.open(self.workspace, paused['workflow_run'])
        self.assertEqual(audit.load()['status'], 'awaiting_answers')
        self.assertIsNone(audit.load()['approved_plan'])
        self.assertTrue(service.command(session, '/approve')['command_error'])
        self.act(service, session, '/answer Q1 UTC')
        self.assertTrue(service.command(session, '/approve')['command_error'])
        self.act(service, session, '/plan')
        self.act(service, session, '/approve')
        self.assertEqual(audit.load()['status'], 'review_required')

    def test_execution_failure_and_resume_preserve_run(self):
        service, session, _ = self.service(
            response({'questions': []}), response({'plan': '# Plan\nBuild it.'}),
            ForgeError('Connection lost'), response({'tool': 'finish', 'summary': 'Recovered', 'verification': 'Inspect changes.'}))
        self.act(service, session, '/prepare')
        self.act(service, session, '/plan')
        failed = service.command(session, '/approve')
        self.assertIn('Connection lost', failed['command_error'])
        audit = Audit.open(self.workspace, failed['workflow_run'])
        self.assertEqual(audit.load()['status'], 'interrupted')
        self.assertTrue(audit.load()['approved_plan'])
        self.act(service, session, '/run')
        self.act(service, session, '/approve')
        self.assertEqual(audit.load()['status'], 'review_required')

    def test_request_wizard_preserves_existing_file_until_save_and_updates_model_context(self):
        service, session, provider = self.service('Here is help for your draft.', 'I see the calculator request.')
        self.act(service, session, '/request Calculator')
        self.act(service, session, 'Create a calculator for basic arithmetic.')
        service.send(session, 'What technical details should I provide?')
        self.assertIn('Create a calculator', provider.calls[-1][0])
        self.assertEqual(self.workspace.read('request.md'), REQUEST)
        self.act(service, session, 'Please help me work out the details.')
        reviewed = self.act(service, session, 'Addition works\nDivision by zero is explained')
        self.assertIn('replaces the existing file', reviewed['messages'][-1]['content'])
        self.assertEqual(self.workspace.read('request.md'), REQUEST)
        self.assertTrue(service.command(session, '/prepare')['command_error'])
        self.act(service, session, '/save-request')
        request = Request.parse(self.workspace.read('request.md'))
        self.assertEqual(request.title, 'Calculator')
        self.assertIn('- [ ] Addition works', request.acceptance_criteria)
        self.assertIsNone(service.get(session)['input_mode'])
        service.send(session, 'Is my request clear?')
        self.assertIn('Calculator', provider.calls[-1][0])

    def test_request_cancel_and_concurrent_edit_do_not_overwrite(self):
        service, session, _ = self.service()
        self.act(service, session, '/request New request')
        self.act(service, session, '/cancel')
        self.assertEqual(self.workspace.read('request.md'), REQUEST)
        for message in ('/request Another request', 'Description', 'Details', 'It works'):
            self.act(service, session, message)
        self.workspace.write('request.md', REQUEST + '\nChanged externally.\n')
        denied = service.command(session, '/save-request')
        self.assertIn('changed while', denied['command_error'])
        self.assertIn('Changed externally', self.workspace.read('request.md'))
        self.assertEqual(service.get(session)['input_mode'], 'request')

    def test_locked_run_wrong_model_and_pending_reply_block_actions(self):
        service, session, _ = self.service(response({'questions': []}), response({'plan': '# Plan\nBuild it.'}), ForgeError('Offline'))
        self.act(service, session, '/prepare')
        audit = Audit.open(self.workspace, service.get(session)['workflow_run'])
        with audit.lock():
            self.assertIn('locked', service.command(session, '/plan')['command_error'])
        self.act(service, session, '/plan')
        changed = audit.load()
        changed['model'] = 'another-model'
        audit.save(changed)
        self.assertIn('different model', service.command(session, '/approve')['command_error'])
        changed['model'] = self.config.model
        audit.save(changed)
        with self.assertRaises(ForgeError):
            service.send(session, 'A question')
        with self.assertRaisesRegex(ForgeError, 'pending model message'):
            service.command(session, '/approve')
        self.assertIsNone(audit.load()['approved_plan'])

    def test_invalid_commands_paths_and_question_ids_are_explained(self):
        service, session, provider = self.service(response(QUESTION))
        for command in ('/not-a-command', '/use 1', '/plan', '/prepare ../outside.md', '/prepare "unclosed'):
            self.assertTrue(service.command(session, command)['command_error'])
        self.assertEqual(len(provider.calls), 0)
        self.act(service, session, '/prepare')
        self.assertTrue(service.command(session, '/answer Q9 UTC')['command_error'])
        self.assertIn('Q1', self.act(service, session, '/answer')['messages'][-1]['content'])

import json
from pathlib import Path
import tempfile
import unittest

from solar_forge.requests import DEFAULT_REQUEST, read_request, write_request
from solar_forge.agent import approve, digest, run
from solar_forge.domain import Config, ForgeError
from solar_forge.workflow import plan, prepare, record_answer
from solar_forge.workspace import Workspace
from test_foundation import REQUEST
from test_workflow import QUESTION, ScriptedProvider


class AgentTests(unittest.TestCase):
    def setup_run(self, tmp, *actions, max_turns=30):
        ws = Workspace(Path(tmp))
        write_request(ws, DEFAULT_REQUEST, REQUEST)
        cfg = Config(model='test', max_turns=max_turns)
        provider = ScriptedProvider({'questions': []}, {'plan': '# Plan\nCreate export.'}, *actions)
        audit = prepare(ws, cfg, DEFAULT_REQUEST, provider)
        plan(ws, cfg, audit, provider)
        return ws, cfg, audit, provider

    def test_approval_and_audited_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, cfg, audit, provider = self.setup_run(tmp,
                {'tool': 'write_file', 'path': 'export.py', 'content': 'print("export")\n'},
                {'tool': 'finish', 'summary': 'Created exporter.', 'verification': 'Run export.py.'})
            with self.assertRaises(ForgeError):
                run(ws, cfg, audit, provider)
            self.assertFalse((ws.root / 'export.py').exists())
            approve(audit)
            run(ws, cfg, audit, provider)
            self.assertEqual(audit.load()['status'], 'review_required')
            self.assertIn('print', ws.read('export.py'))
            self.assertTrue((audit.path / 'changes/0001/diff.patch').exists())
            self.assertIn('remain unverified', (audit.path / 'summary.md').read_text())

    def test_existing_file_requires_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, cfg, audit, provider = self.setup_run(tmp,
                {'tool': 'write_file', 'path': 'app.py', 'content': 'updated'},
                {'tool': 'read_file', 'path': 'app.py'},
                {'tool': 'write_file', 'path': 'app.py', 'content': 'updated'},
                {'tool': 'finish', 'summary': 'Updated app.', 'verification': 'Check app.'})
            ws.write('app.py', 'original')
            approve(audit)
            run(ws, cfg, audit, provider)
            self.assertEqual(ws.read('app.py'), 'updated')
            self.assertEqual((audit.path / 'changes/0003/before.txt').read_text(), 'original')
            self.assertIn('tool_rejected', (audit.path / 'events.jsonl').read_text())

    def test_new_question_pauses_and_needs_revised_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, cfg, audit, provider = self.setup_run(tmp, {'tool': 'ask_questions', **QUESTION})
            approve(audit)
            run(ws, cfg, audit, provider)
            self.assertEqual(audit.load()['status'], 'awaiting_answers')
            record_answer(audit, 'Q1', 'UTC')
            with self.assertRaises(ForgeError):
                run(ws, cfg, audit, provider)
            provider = ScriptedProvider({'plan': '# Revised\nUse UTC.'},
                {'tool': 'finish', 'summary': 'Ready for review.', 'verification': 'Check UTC boundaries.'})
            plan(ws, cfg, audit, provider)
            approve(audit)
            run(ws, cfg, audit, provider)
            self.assertEqual(audit.load()['status'], 'review_required')

    def test_failure_resumes_and_turn_limit_bounds_rejections(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, cfg, audit, provider = self.setup_run(tmp, ForgeError('offline'), max_turns=2)
            approve(audit)
            with self.assertRaises(ForgeError):
                run(ws, cfg, audit, provider)
            self.assertEqual(audit.load()['status'], 'interrupted')
            run(ws, cfg, audit, ScriptedProvider({'tool': 'delete', 'path': 'request.md'}))
            self.assertEqual(audit.load()['status'], 'turn_limit')
            self.assertEqual(read_request(ws, DEFAULT_REQUEST), REQUEST)

    def test_plan_tamper_and_policy_edit_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, cfg, audit, provider = self.setup_run(tmp,
                {'tool': 'write_file', 'path': 'request.md', 'content': 'tampered'},
                {'tool': 'finish', 'summary': 'No changes.', 'verification': 'Review.'})
            approve(audit)
            audit.write('plan.md', 'Changed after approval')
            with self.assertRaises(ForgeError):
                run(ws, cfg, audit, provider)
            # Only an explicit new approval authorizes the new plan.
            approve(audit)
            run(ws, cfg, audit, provider)
            self.assertEqual(read_request(ws, DEFAULT_REQUEST), REQUEST)
            self.assertFalse((ws.root / 'request.md').exists())
            self.assertIn('Request artifacts must be stored', audit.read('events.jsonl'))

    def test_reserved_artifact_writes_are_rejected_but_application_files_work(self):
        denied = ['request.md', 'docs/REQUEST.md', 'requests/billing.md',
                  'docs/requests/billing/context.txt', 'implementation-plan.md',
                  'docs/chat-implementation-plan.md', 'plan.md', 'summary.md',
                  'progress.md', 'verification.md']
        with tempfile.TemporaryDirectory() as tmp:
            ws, cfg, audit, provider = self.setup_run(tmp,
                *({'tool': 'write_file', 'path': name, 'content': 'artifact'} for name in denied),
                {'tool': 'write_file', 'path': 'src/requests.py', 'content': '# Application code'},
                {'tool': 'write_file', 'path': 'docs/features.md', 'content': '# Product documentation'},
                {'tool': 'finish', 'summary': 'Done', 'verification': 'Review'})
            approve(audit)
            run(ws, cfg, audit, provider)
            for name in denied:
                self.assertFalse((ws.root / name).exists(), name)
            self.assertTrue((ws.root / 'src/requests.py').exists())
            self.assertTrue((ws.root / 'docs/features.md').exists())
            self.assertTrue((audit.path / 'summary.md').exists())

    def test_pending_write_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, cfg, audit, provider = self.setup_run(tmp)
            approve(audit)
            state = audit.load()
            state.update(status='interrupted', turns=1, pending_action={
                'tool': 'write_file', 'path': 'new.py', 'content': 'new'})
            audit.save(state)
            audit.write('changes/0001/before.txt', '')
            audit.write('changes/0001/after.txt', 'new')
            audit.write('changes/0001/metadata.json', json.dumps({
                'path': 'new.py', 'existed': False, 'before_sha256': None, 'after_sha256': digest('new')}))
            ws.write('new.py', 'new')  # Simulate a crash after write but before checkpoint.
            run(ws, cfg, audit, ScriptedProvider({'tool': 'finish', 'summary': 'Recovered.', 'verification': 'Review new.py.'}))
            self.assertEqual(ws.read('new.py'), 'new')
            self.assertIn('"recovered": true', (audit.path / 'events.jsonl').read_text())

    def test_files_inside_context_folders_cannot_be_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            write_request(ws, DEFAULT_REQUEST, REQUEST)
            ws.write('docs/rules.md', 'Original rules')
            cfg = Config(model='test', docs=['docs'])
            provider = ScriptedProvider({'questions': []}, {'plan': '# Plan\nFollow the rules.'},
                {'tool': 'read_file', 'path': 'docs/rules.md'},
                {'tool': 'write_file', 'path': 'docs/rules.md', 'content': 'Changed rules'},
                {'tool': 'write_file', 'path': 'docs/new.md', 'content': 'New rules'},
                {'tool': 'finish', 'summary': 'No policy changes.', 'verification': 'Inspect docs.'})
            audit = prepare(ws, cfg, DEFAULT_REQUEST, provider)
            plan(ws, cfg, audit, provider)
            approve(audit)
            run(ws, cfg, audit, provider)
            self.assertEqual(ws.read('docs/rules.md'), 'Original rules')
            self.assertFalse((ws.root / 'docs/new.md').exists())
            self.assertEqual(audit.load()['status'], 'review_required')

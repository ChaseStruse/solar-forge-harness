import json
from pathlib import Path
import tempfile
import unittest

from solar_forge.agent import approve, digest, run
from solar_forge.domain import Config, ForgeError
from solar_forge.workflow import plan, prepare, record_answer
from solar_forge.workspace import Workspace
from test_foundation import REQUEST
from test_workflow import QUESTION, ScriptedProvider


class AgentTests(unittest.TestCase):
    def setup_run(self, tmp, *actions, max_turns=30):
        ws = Workspace(Path(tmp))
        ws.write('request.md', REQUEST)
        cfg = Config(model='test', max_turns=max_turns)
        provider = ScriptedProvider({'questions': []}, {'plan': '# Plan\nCreate export.'}, *actions)
        audit = prepare(ws, cfg, 'request.md', provider)
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
            self.assertEqual(ws.read('request.md'), REQUEST)

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
            self.assertEqual(ws.read('request.md'), REQUEST)

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
            ws.write('request.md', REQUEST)
            ws.write('docs/rules.md', 'Original rules')
            cfg = Config(model='test', docs=['docs'])
            provider = ScriptedProvider({'questions': []}, {'plan': '# Plan\nFollow the rules.'},
                {'tool': 'read_file', 'path': 'docs/rules.md'},
                {'tool': 'write_file', 'path': 'docs/rules.md', 'content': 'Changed rules'},
                {'tool': 'write_file', 'path': 'docs/new.md', 'content': 'New rules'},
                {'tool': 'finish', 'summary': 'No policy changes.', 'verification': 'Inspect docs.'})
            audit = prepare(ws, cfg, 'request.md', provider)
            plan(ws, cfg, audit, provider)
            approve(audit)
            run(ws, cfg, audit, provider)
            self.assertEqual(ws.read('docs/rules.md'), 'Original rules')
            self.assertFalse((ws.root / 'docs/new.md').exists())
            self.assertEqual(audit.load()['status'], 'review_required')

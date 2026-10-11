import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from dataclasses import replace

from solar_forge.agent import approve, run, validate_action
from solar_forge.domain import Config, ForgeError, VerificationConfig
from solar_forge.requests import DEFAULT_REQUEST, write_request
from solar_forge.verification import run_check
from solar_forge.workflow import plan, prepare
from solar_forge.workspace import Workspace
from test_foundation import REQUEST
from test_workflow import ScriptedProvider


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = Workspace(Path(self.temp.name))
        write_request(self.ws, DEFAULT_REQUEST, REQUEST)

    def setup_run(self, code='print("ok")', **options):
        self.cfg = Config(model='test', verification=VerificationConfig(
            commands={'tests': [sys.executable, '-c', code]}, **options))
        provider = ScriptedProvider({'questions': []}, {'plan': 'Run tests and review.'})
        self.audit = prepare(self.ws, self.cfg, DEFAULT_REQUEST, provider)
        plan(self.ws, self.cfg, self.audit, provider)
        approve(self.audit)
        state = self.audit.load()
        state['turns'] = 1
        return state

    def check(self, state, **kwargs):
        return run_check(self.ws, self.cfg, self.audit, state, 'tests', **kwargs)

    def test_success_failure_and_environment(self):
        state = self.setup_run('import os; print(os.getcwd()); print(os.getenv("FORGE_TEST_SECRET")); print(os.getenv("PYTHONPATH"))',
                               env={'PYTHONPATH': 'src'})
        from unittest.mock import patch
        with patch.dict(os.environ, {'FORGE_TEST_SECRET': 'do-not-inherit'}):
            result = self.check(state)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['exit_code'], 0)
        self.assertIn(str(self.ws.root), result['output'])
        self.assertIn('None\nsrc', result['output'])
        self.assertNotIn('do-not-inherit', result['output'])
        self.assertEqual(json.loads(self.audit.read(result['evidence'])), result)

    def test_failure_is_evidence(self):
        state = self.setup_run('import sys; print("broken", file=sys.stderr); sys.exit(3)')
        result = self.check(state)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['exit_code'], 3)
        self.assertIn('broken', result['output'])

    def test_timeout_and_output_bound(self):
        state = self.setup_run('import time; print("x" * 100000, flush=True); time.sleep(10)',
                               timeout=1, max_output_bytes=100)
        result = self.check(state)
        self.assertEqual(result['status'], 'timed_out')
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['output']), 100)
        self.assertLess(result['duration_seconds'], 4)

    def test_cancellation(self):
        state = self.setup_run('import time; time.sleep(10)')
        polls = []
        def cancelled():
            polls.append(True)
            return len(polls) > 3
        result = self.check(state, cancelled=cancelled)
        self.assertEqual(result['status'], 'cancelled')
        self.assertLess(result['duration_seconds'], 2)

    def test_no_shell_interpolation(self):
        state = self.setup_run()
        self.cfg = replace(self.cfg, verification=VerificationConfig(commands={
            'tests': [sys.executable, '-c', 'import sys; print(sys.argv[1])', '$(touch unwanted); echo nope']}))
        result = self.check(state)
        self.assertEqual(result['status'], 'passed')
        self.assertIn('$(touch unwanted)', result['output'])
        self.assertFalse((self.ws.root / 'unwanted').exists())

    def test_unknown_disabled_and_extra_arguments(self):
        state = self.setup_run()
        with self.assertRaises(ForgeError):
            run_check(self.ws, self.cfg, self.audit, state, 'unknown')
        with self.assertRaises(ForgeError):
            run_check(self.ws, Config(), self.audit, state, 'tests')
        with self.assertRaises(ForgeError):
            validate_action({'tool': 'run_check', 'name': 'tests', 'argv': ['anything']})
        self.assertFalse((self.audit.path / 'verification').exists())

    def test_recovery_does_not_replay_commands(self):
        state = self.setup_run('from pathlib import Path; p=Path("counter"); p.write_text(p.read_text()+"x" if p.exists() else "x")')
        first = self.check(state)
        self.assertEqual(first, self.check(state))
        self.assertEqual(self.ws.read('counter'), 'x')
        (self.audit.path / first['evidence']).unlink()
        recovered = self.check(state)
        self.assertEqual(recovered['status'], 'interrupted')
        self.assertEqual(self.ws.read('counter'), 'x')

    def test_missing_executable_is_recorded(self):
        state = self.setup_run()
        self.cfg = replace(self.cfg, verification=VerificationConfig(commands={'tests': ['/nonexistent/forge-check']}))
        result = self.check(state)
        self.assertEqual(result['status'], 'error')
        self.assertIsNone(result['exit_code'])

    def test_policy_is_displayed_and_bound_to_run(self):
        self.setup_run()
        self.assertIn(sys.executable, self.audit.read('plan.md'))
        changed = replace(self.cfg, verification=VerificationConfig(commands={'tests': ['different']}))
        with self.assertRaisesRegex(ForgeError, 'Verification configuration changed'):
            run(self.ws, changed, self.audit, ScriptedProvider())
        state = self.audit.load()
        state.pop('verification')
        self.audit.save(state)
        with self.assertRaisesRegex(ForgeError, 'Verification configuration changed'):
            run(self.ws, self.cfg, self.audit, ScriptedProvider())

    def test_edit_failure_repair_pass_and_later_staleness(self):
        self.setup_run('from app import add; assert add(2, 3) == 5')
        actions = [
            {'tool': 'write_file', 'path': 'app.py', 'content': 'def add(a, b): return a - b\n'},
            {'tool': 'run_check', 'name': 'tests'},
            {'tool': 'read_file', 'path': 'app.py'},
            {'tool': 'write_file', 'path': 'app.py', 'content': 'def add(a, b):\n    return a + b\n'},
            {'tool': 'run_check', 'name': 'tests'},
            {'tool': 'write_file', 'path': 'note.txt', 'content': 'later edit'},
            {'tool': 'finish', 'summary': 'Fixed addition.', 'verification': 'See recorded checks.'}]
        provider = ScriptedProvider(*actions)
        run(self.ws, self.cfg, self.audit, provider)
        state = self.audit.load()
        self.assertEqual([r['status'] for r in state['verification_results']], ['failed', 'passed'])
        self.assertEqual(state['status'], 'review_required')
        summary = self.audit.read('summary.md')
        self.assertIn('predates later edits', summary)
        self.assertIn('not certification', summary)
        self.assertIn('tests: passed', summary)

    def test_timeout_terminates_descendants(self):
        import time
        child = 'import time; from pathlib import Path; time.sleep(2); Path("survived").write_text("bad")'
        state = self.setup_run(
            'import subprocess, sys, time; subprocess.Popen([sys.executable, "-c", ' + repr(child)
            + ']); time.sleep(10)', timeout=1)
        self.assertEqual(self.check(state)['status'], 'timed_out')
        time.sleep(1.2)
        self.assertFalse((self.ws.root / 'survived').exists())

    def test_agent_requires_approval_before_checks(self):
        self.setup_run('from pathlib import Path; Path("executed").touch()')
        state = self.audit.load()
        state['approved_plan'] = None
        self.audit.save(state)
        with self.assertRaisesRegex(ForgeError, 'not been approved'):
            run(self.ws, self.cfg, self.audit, ScriptedProvider({'tool': 'run_check', 'name': 'tests'}))
        self.assertFalse((self.ws.root / 'executed').exists())

    def test_resume_attaches_saved_result_without_reexecuting(self):
        state = self.setup_run('from pathlib import Path; p=Path("counter"); p.write_text(p.read_text()+"x" if p.exists() else "x")')
        result = self.check(state)
        state.update(status='interrupted', pending_action={'tool': 'run_check', 'name': 'tests'})
        self.audit.save(state)
        run(self.ws, self.cfg, self.audit, ScriptedProvider(
            {'tool': 'finish', 'summary': 'Recovered.', 'verification': 'Review result.'}))
        self.assertEqual(self.ws.read('counter'), 'x')
        self.assertEqual(self.audit.load()['verification_results'], [result])

    def test_checks_invalidate_previously_read_files(self):
        self.setup_run('from pathlib import Path; Path("app.py").write_text("changed by check")')
        self.ws.write('app.py', 'original')
        run(self.ws, self.cfg, self.audit, ScriptedProvider(
            {'tool': 'read_file', 'path': 'app.py'},
            {'tool': 'run_check', 'name': 'tests'},
            {'tool': 'write_file', 'path': 'app.py', 'content': 'overwrite'},
            {'tool': 'finish', 'summary': 'Review.', 'verification': 'Review.'}))
        self.assertEqual(self.ws.read('app.py'), 'changed by check')
        self.assertIn('Read the current file before writing', self.audit.read('events.jsonl'))

    def test_config_validation_and_loading(self):
        invalid = [dict(commands={'test': 'python'}), dict(commands={'test': []}),
                   dict(commands={'bad name': ['python']}), dict(timeout=True),
                   dict(max_output_bytes=0), dict(env={'INVALID=KEY': 'x'}),
                   dict(commands={'test': ['python', '\0']})]
        for options in invalid:
            with self.subTest(options=options), self.assertRaises(ForgeError):
                VerificationConfig(**options).snapshot()
        path = self.ws.root / 'config.toml'
        path.write_text('[verification]\ncommands = { tests = ["python", "-m", "unittest"] }\nenv = { PYTHONPATH = "src" }\n')
        config = Config.load(path)
        self.assertEqual(config.verification.commands['tests'], ['python', '-m', 'unittest'])
        self.assertEqual(config.verification.env, {'PYTHONPATH': 'src'})

import json
from pathlib import Path
import tempfile
import unittest

from solar_forge.domain import Config, ForgeError
from solar_forge.workflow import call, plan, prepare, record_answer
from solar_forge.workspace import Workspace
from test_foundation import REQUEST


class ScriptedProvider:
    def __init__(self, *responses):
        self.responses = iter(responses)

    def complete(self, system, messages):
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return json.dumps(response)


QUESTION = {'questions': [{'question': 'Which billing timezone applies?',
                           'rationale': 'Determines invoice date boundaries.', 'sources': ['request.md']}]}


class WorkflowTests(unittest.TestCase):
    def test_questions_block_plan_and_answers_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            ws.write('request.md', REQUEST)
            config = Config(model='test')
            provider = ScriptedProvider(QUESTION, {'plan': '# Plan\nUse recorded timezone.'})
            audit = prepare(ws, config, 'request.md', provider)
            self.assertEqual(audit.load()['status'], 'awaiting_answers')
            with self.assertRaises(ForgeError):
                plan(ws, config, audit, provider)
            record_answer(audit, 'Q1', 'UTC')
            self.assertIn('UTC', (audit.path / 'questions.md').read_text())
            plan(ws, config, audit, provider)
            self.assertEqual(audit.load()['status'], 'planned')
            ws.write('README.md', 'Changed policy')
            with self.assertRaises(ForgeError):
                plan(ws, config, audit, provider)

    def test_provider_failure_leaves_discoverable_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            ws.write('request.md', REQUEST)
            with self.assertRaises(ForgeError):
                prepare(ws, Config(), 'request.md', ScriptedProvider(ForgeError('offline')))
            state = next(Path(tmp).glob('agentic_audit/*/*/state.json'))
            self.assertEqual(json.loads(state.read_text())['status'], 'discovering')
            self.assertIn('provider_call_failed', (state.parent / 'events.jsonl').read_text())

    def test_unknown_question_sources_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            ws.write('request.md', REQUEST)
            bad = {'questions': [{'question': 'Q', 'rationale': 'R', 'sources': ['invented.md']}]}
            with self.assertRaises(ForgeError):
                prepare(ws, Config(), 'request.md', ScriptedProvider(bad))

    def test_prompt_budget_stops_before_provider_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            ws.write('request.md', REQUEST)
            audit = prepare(ws, Config(), 'request.md', ScriptedProvider({'questions': []}))
            with self.assertRaises(ForgeError):
                call(audit, ScriptedProvider(), 'system', [{'role': 'user', 'content': 'large'}], 1)
            self.assertIn('prompt_budget', (audit.path / 'events.jsonl').read_text())

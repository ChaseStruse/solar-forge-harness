import asyncio
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.data_structures import Size

from solar_forge.requests import DEFAULT_REQUEST, read_request, write_request
from solar_forge.chat import ChatService
from solar_forge.audit import Audit
from solar_forge.domain import Config, ForgeError
from solar_forge.terminal_chat import TerminalChat, display, run_terminal_chat
from solar_forge.workspace import Workspace
from test_chat import TextProvider
from test_foundation import REQUEST
from test_workflow import QUESTION


class WideOutput(DummyOutput):
    def get_size(self):
        return Size(rows=30, columns=120)


class TerminalChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_discard_pending_returns_editable_advice_during_request_draft(self):
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            service = ChatService(Workspace(Path(tmp)), Config(model='test', max_prompt_bytes=100), TextProvider())
            ui = TerminalChat(service, input=pipe, output=DummyOutput())
            ui.composer.text = '/request Calculator'
            await ui.send()
            session = ui.current['id']
            ui.composer.text = '/ask Help with this draft'
            await ui.send()
            self.assertEqual(ui.current['pending_message'], 'Help with this draft')
            ui.composer.text = '/discard-pending'
            await ui.send()
            self.assertEqual(ui.current['id'], session)
            self.assertIsNone(ui.current['pending_message'])
            self.assertEqual(ui.current['input_mode'], 'request')
            self.assertEqual(ui.composer.text, '/ask Help with this draft')
            ui.composer.text = '/cancel'
            await ui.send()
            self.assertIsNone(ui.current['input_mode'])
            self.assertFalse(ui.busy)

    async def test_workflow_actions_and_model_advice_inside_window(self):
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            root = Path(tmp)
            workspace = Workspace(root)
            write_request(workspace, DEFAULT_REQUEST, REQUEST)
            provider = TextProvider(json.dumps(QUESTION), 'Choose UTC.',
                                    json.dumps({'plan': '# Plan\nCreate export.py.'}),
                                    json.dumps({'tool': 'write_file', 'path': 'export.py', 'content': 'TIMEZONE = "UTC"\n'}),
                                    json.dumps({'tool': 'finish', 'summary': 'Created export.py.', 'verification': 'Inspect it.'}))
            service = ChatService(workspace, Config(model='test'), provider)
            ui = TerminalChat(service, input=pipe, output=WideOutput())
            for message in ('/prepare', '/answer', '/ask\nWhich timezone should I use?'):
                ui.composer.text = message
                await ui.send()
            audit = Audit.open(workspace, ui.current['workflow_run'])
            self.assertIsNone(audit.load()['questions'][0]['answer'])
            self.assertIn('Choose UTC', ui.conversation.text)
            self.assertEqual(ui.current['input_mode'], 'answer')
            self.assertIn('Which timezone should I use?', provider.calls[1][1][-1]['content'])
            ui.composer.text = 'UTC'
            await ui.send()
            self.assertEqual(audit.load()['questions'][0]['answer'], 'UTC')
            ui.composer.text = '/plan'
            await ui.send()
            self.assertIn('/approve', ui.current['workflow_hint'])
            self.assertFalse((root / 'export.py').exists())
            ui.composer.text = '/approve'
            await ui.send()
            self.assertEqual((root / 'export.py').read_text(), 'TIMEZONE = "UTC"\n')
            self.assertIn('review_required', ui.conversation.text)
            self.assertIsNone(ui.current['pending_message'])
            ui.composer.text = '/changes'
            await ui.send()
            self.assertIn('+TIMEZONE = "UTC"', ui.conversation.text)

    async def test_request_drafting_can_ask_and_resume_after_failed_reply(self):
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            root = Path(tmp)
            service = ChatService(Workspace(root), Config(model='test'),
                                  TextProvider(ForgeError('Offline'), 'Describe the desired user outcome.'))
            ui = TerminalChat(service, input=pipe, output=DummyOutput())
            ui.composer.text = '/request Calculator'
            await ui.send()
            ui.composer.text = '/ask What should I put in the description?'
            await ui.send()
            self.assertEqual(ui.current['input_mode'], 'request')
            self.assertEqual(ui.current['pending_message'], 'What should I put in the description?')
            await ui.send(retry=True)
            self.assertIn('Describe the desired user outcome', ui.conversation.text)
            for message in ('Build a calculator.', 'Please help me work out the details.', 'Addition works', '/save-request'):
                ui.composer.text = message
                await ui.send()
            self.assertIn('# Request: Calculator', (root / 'agentic_audit/requests/calculator/request.md').read_text())
            self.assertIsNone(ui.current['input_mode'])

    async def test_keyboard_workflow_commands_require_explicit_approval(self):
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            workspace = Workspace(Path(tmp))
            write_request(workspace, DEFAULT_REQUEST, REQUEST)
            provider = TextProvider(json.dumps({'questions': []}), json.dumps({'plan': '# Plan\nInspect the project.'}),
                                    json.dumps({'tool': 'finish', 'summary': 'Ready for review.', 'verification': 'Inspect manually.'}))
            ui = TerminalChat(ChatService(workspace, Config(model='test'), provider), input=pipe, output=WideOutput())
            task = asyncio.create_task(ui.run())
            try:
                await asyncio.sleep(.05)
                for message, pairs in (('/prepare', 2), ('/plan', 4), ('/approve', 6)):
                    pipe.send_text(message + '\r')
                    for _ in range(100):
                        if ui.current and len(ui.current['messages']) >= pairs and not ui.busy:
                            break
                        await asyncio.sleep(.01)
                    self.assertEqual(len(ui.current['messages']), pairs)
                    state = Audit.open(workspace, ui.current['workflow_run']).load()
                    if message != '/approve':
                        self.assertFalse(state.get('approved_plan'))
                self.assertEqual(state['status'], 'review_required')
                pipe.send_text('\x11')
                await asyncio.wait_for(task, timeout=2)
            finally:
                if ui.app.is_running:
                    ui.app.exit()
                await task

    async def test_send_new_resume_and_failure_retry(self):
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            provider = TextProvider('Hello', ForgeError('Offline'), 'Recovered')
            service = ChatService(Workspace(Path(tmp)), Config(model='test'), provider)
            ui = TerminalChat(service, input=pipe, output=WideOutput())
            ui.composer.text = 'First question'
            await ui.send()
            saved = ui.current['id']
            self.assertIn('Hello', ui.conversation.text)
            self.assertEqual(ui.composer.text, '')
            ui.composer.text = 'Second question'
            await ui.send()
            self.assertIn('Offline', ui.notice)
            self.assertEqual(ui.current['pending_message'], 'Second question')
            await ui.send(retry=True)
            self.assertIsNone(ui.current['pending_message'])
            self.assertEqual(len(ui.current['messages']), 4)
            ui.new_chat()
            self.assertIsNone(ui.current)
            ui.open_session(saved)
            self.assertIn('Recovered', ui.conversation.text)
            self.assertEqual(len(ui.sessions), 1)
            resumed = TerminalChat(service, resume=saved, input=pipe, output=DummyOutput())
            self.assertEqual(resumed.current['id'], saved)

    async def test_actual_keyboard_enter_newline_and_quit(self):
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            service = ChatService(Workspace(Path(tmp)), Config(model='test'), TextProvider('Reply'))
            ui = TerminalChat(service, input=pipe, output=WideOutput())
            task = asyncio.create_task(ui.run())
            try:
                await asyncio.sleep(.05)
                pipe.send_text('First linex\x7f\x1b\rSecond line\r')
                for _ in range(100):
                    if ui.current and len(ui.current['messages']) == 2:
                        break
                    await asyncio.sleep(.01)
                self.assertEqual(ui.current['messages'][0]['content'], 'First line\nSecond line')
                pipe.send_text('\x0e')  # Ctrl+N
                await asyncio.sleep(.05)
                self.assertIsNone(ui.current)
                pipe.send_text('\x0c\r')  # Ctrl+L focuses history, Enter reopens selection.
                await asyncio.sleep(.05)
                self.assertEqual(ui.current['title'], 'First line Second line')
                pipe.send_text('\x11')  # Ctrl+Q
                await asyncio.wait_for(task, timeout=2)
            finally:
                if ui.app.is_running:
                    ui.app.exit()
                await task

    async def test_exit_waits_for_active_reply_and_preserves_it(self):
        gate, started = Event(), Event()
        class SlowProvider:
            def complete(self, system, messages):
                started.set()
                if not gate.wait(3):
                    raise ForgeError('Test timed out')
                return 'Saved before exit'
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            service = ChatService(Workspace(Path(tmp)), Config(model='test'), SlowProvider())
            ui = TerminalChat(service, input=pipe, output=DummyOutput())
            task = asyncio.create_task(ui.run())
            try:
                await asyncio.sleep(.05)
                pipe.send_text('Question\r')
                for _ in range(100):
                    if started.is_set():
                        break
                    await asyncio.sleep(.01)
                self.assertTrue(started.is_set())
                pipe.send_text('\x11')
                await asyncio.sleep(.05)
                self.assertTrue(ui.exit_requested)
                self.assertFalse(task.done())
                gate.set()
                await asyncio.wait_for(task, timeout=2)
                self.assertEqual(service.get(ui.current['id'])['messages'][-1]['content'], 'Saved before exit')
            finally:
                gate.set()
                if ui.app.is_running:
                    ui.app.exit()
                await task

    async def test_draft_preserved_after_rejected_submission_and_history_command(self):
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            service = ChatService(Workspace(Path(tmp)), Config(model='test', max_turns=1), TextProvider('Reply'))
            ui = TerminalChat(service, input=pipe, output=DummyOutput())
            ui.composer.text = 'First'
            await ui.send()
            ui.composer.text = 'Second'
            await ui.send()
            self.assertEqual(ui.composer.text, 'Second')
            self.assertIn('turn limit', ui.notice)
            ui.new_chat()
            ui.composer.text = '/open 1'
            await ui.send()
            self.assertEqual(ui.current['title'], 'First')


class TerminalBoundaryTests(unittest.TestCase):
    def test_terminal_sequences_are_removed_from_display(self):
        self.assertEqual(display('\x1b[2Jhello\x1b]0;title\x07\nworld\x00'), 'hello\nworld')

    def test_noninteractive_terminal_is_rejected(self):
        with patch('solar_forge.terminal_chat.sys.stdin.isatty', return_value=False):
            with self.assertRaisesRegex(ForgeError, 'interactive terminal'):
                run_terminal_chat(None)

import asyncio
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from solar_forge.chat import ChatService
from solar_forge.domain import Config, ForgeError
from solar_forge.terminal_chat import TerminalChat, display, run_terminal_chat
from solar_forge.workspace import Workspace
from test_chat import TextProvider


class TerminalChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_new_resume_and_failure_retry(self):
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            provider = TextProvider('Hello', ForgeError('Offline'), 'Recovered')
            service = ChatService(Workspace(Path(tmp)), Config(model='test'), provider)
            ui = TerminalChat(service, input=pipe, output=DummyOutput())
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
            ui = TerminalChat(service, input=pipe, output=DummyOutput())
            task = asyncio.create_task(ui.run())
            try:
                await asyncio.sleep(.05)
                pipe.send_text('First line\x1b\rSecond line\r')
                for _ in range(100):
                    if ui.current and len(ui.current['messages']) == 2:
                        break
                    await asyncio.sleep(.01)
                self.assertEqual(ui.current['messages'][0]['content'], 'First line\nSecond line')
                pipe.send_text('\x0e')  # Ctrl+N
                await asyncio.sleep(.05)
                self.assertIsNone(ui.current)
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

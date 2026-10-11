import asyncio
import json
from pathlib import Path
import sys
import tempfile
from threading import Event
import unittest

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.data_structures import Size

from solar_forge.audit import Audit
from solar_forge.chat import ChatService
from solar_forge.domain import Config, VerificationConfig
from solar_forge.providers import ProviderText
from solar_forge.requests import DEFAULT_REQUEST, write_request
from solar_forge.terminal_chat import TerminalChat
from solar_forge.workspace import Workspace
from test_chat import TextProvider
from test_foundation import REQUEST
from test_terminal_chat import WideOutput


class NarrowOutput(DummyOutput):
    def get_size(self):
        return Size(rows=24, columns=48)


class LiveProgressTests(unittest.IsolatedAsyncioTestCase):
    async def wait_until(self, condition):
        for _ in range(200):
            if condition():
                return
            await asyncio.sleep(.01)
        self.fail('Expected live progress was not delivered')

    async def test_model_wait_is_visible_before_reply_and_reopens_with_usage(self):
        started, release = Event(), Event()
        class SlowProvider:
            def complete(self, system, messages):
                started.set()
                if not release.wait(3):
                    raise RuntimeError('Test timed out')
                return ProviderText('Done', {'input_tokens': 20, 'output_tokens': 3})
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            service = ChatService(Workspace(Path(tmp)), Config(model='test'), SlowProvider())
            ui = TerminalChat(service, input=pipe, output=WideOutput())
            ui.composer.text = 'Help with a task'
            task = asyncio.create_task(ui.send())
            try:
                await self.wait_until(lambda: started.is_set() and 'Waiting for model' in ui.activity_text())
                self.assertTrue(ui.busy)
                self.assertIn('unavailable', ui.activity_text())
                self.assertNotIn('Done', ui.conversation.text)
            finally:
                release.set()
                await asyncio.wait_for(task, 3)
            self.assertIn('20 in / 3 out', ui.activity_text())
            self.assertIn('Reply saved', ui.activity_text())
            session = ui.current['id']
            ui.new_chat()
            self.assertIsNone(ui.activity)
            ui.open_session(session)
            self.assertIn('20 in / 3 out', ui.activity_text())

    async def test_coding_files_live_check_keyboard_stop_and_saved_summary(self):
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            ws = Workspace(Path(tmp))
            write_request(ws, DEFAULT_REQUEST, REQUEST)
            cfg = Config(model='test', verification=VerificationConfig(
                commands={'tests': [sys.executable, '-c', 'import time; time.sleep(10)']}, timeout=15))
            provider = TextProvider(json.dumps({'questions': []}), json.dumps({'plan': 'Write and check.'}),
                json.dumps({'tool': 'write_file', 'path': 'app.py', 'content': 'value = 1\n'}),
                json.dumps({'tool': 'run_check', 'name': 'tests'}))
            service = ChatService(ws, cfg, provider)
            ui = TerminalChat(service, input=pipe, output=WideOutput())
            for command in ('/prepare', '/plan'):
                ui.composer.text = command
                await ui.send()
            app_task = asyncio.create_task(ui.run())
            await asyncio.sleep(.05)
            ui.composer.text = '/approve'
            task = asyncio.create_task(ui.send())
            try:
                await self.wait_until(lambda: 'Running check: tests' in ui.activity_text())
                self.assertIn('Changed (1): app.py', ui.activity_text())
                pipe.send_text('\x18')  # Ctrl+X through the actual key binding.
                await self.wait_until(ui.stop_requested.is_set)
                if ui.busy:
                    self.assertIn('Stop requested', ui.activity_text())
                await asyncio.wait_for(task, 3)
                self.assertIn('tests: cancelled', ui.activity_text())
                self.assertIn('Interrupted', ui.activity_text())
                self.assertEqual(Audit.open(ws, ui.current['workflow_run']).load()['status'], 'interrupted')
                ui.composer.text = '/status'
                await ui.send()
                self.assertIn('tests: cancelled', ui.conversation.text)
                self.assertIn('Changed (1): app.py', ui.conversation.text)
                session = ui.current['id']
                ui.open_session(session)
                self.assertIn('tests: cancelled', ui.activity_text())
            finally:
                ui.stop_requested.set()
                await asyncio.wait_for(task, 3)
                if ui.app.is_running:
                    ui.app.exit()
                await asyncio.wait_for(app_task, 3)

    async def test_narrow_panel_is_bounded_and_sanitizes_paths(self):
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            service = ChatService(Workspace(Path(tmp)), Config(model='test'), TextProvider('Hello'))
            ui = TerminalChat(service, input=pipe, output=NarrowOutput())
            ui.composer.text = 'Hello'
            await ui.send()
            ui.activity['changed_files'] = ['\x1b[31m' + 'long/path/' * 20 + '\x07']
            ui.activity['action'] = '\x1b[2JWriting a long path'
            text = ui.activity_text()
            self.assertNotIn('\x1b', text)
            self.assertNotIn('\x07', text)
            self.assertEqual(len(text.splitlines()), 4)
            self.assertTrue(all(len(line) <= 42 for line in text.splitlines()))

    async def test_model_failure_is_visible_and_next_call_does_not_show_old_usage(self):
        from solar_forge.domain import ForgeError
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            service = ChatService(Workspace(Path(tmp)), Config(model='test'),
                                  TextProvider(ProviderText('Hi', {'input_tokens': 3, 'output_tokens': 1}), ForgeError('offline')))
            ui = TerminalChat(service, input=pipe, output=WideOutput())
            ui.composer.text = 'Hi'
            await ui.send()
            ui.composer.text = 'Again'
            await ui.send()
            self.assertIn('Reply failed', ui.activity_text())
            self.assertIn('(partial)', ui.activity_text())
            self.assertEqual(ui.activity['usage']['calls'], 2)
            self.assertEqual(ui.activity['usage']['input_tokens'], 3)

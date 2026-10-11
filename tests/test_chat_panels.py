import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from solar_forge.audit import Audit
from solar_forge.chat import ChatService
from solar_forge.domain import Config, ForgeError
from solar_forge.requests import DEFAULT_REQUEST, write_request
from solar_forge.setup import render_config
from solar_forge.terminal_chat import TerminalChat
from solar_forge.workspace import Workspace, atomic_write
from test_chat import TextProvider
from test_foundation import REQUEST


class PanelTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, root, provider=None):
        ws = Workspace(Path(root))
        cfg = Config(model='test')
        atomic_write(ws.path('.forge/config.toml', internal=True), render_config(cfg))
        write_request(ws, DEFAULT_REQUEST, REQUEST)
        return ChatService(ws, cfg, provider or TextProvider())

    async def test_settings_apply_without_restart_and_model_change_preserves_old_chat(self):
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            service = self.make_service(tmp)
            ui = TerminalChat(service, input=pipe, output=DummyOutput())
            ui.current = service.new()
            original = ui.current['id']
            ui.composer.text = '/settings timeout 600'
            await ui.send()
            self.assertEqual(service.config.timeout, 600)
            self.assertEqual(Config.load(Path(tmp) / '.forge/config.toml').timeout, 600)
            self.assertEqual(ui.current['id'], original)
            ui.composer.text = '/settings max_prompt_bytes -1'
            await ui.send()
            self.assertIn('positive', ui.notice)
            self.assertEqual(service.config.max_prompt_bytes, 500000)
            ui.last_failed_command = '/prepare'
            ui.composer.text = '/settings model next-model'
            await ui.send()
            self.assertIsNone(ui.current)
            self.assertIsNone(ui.last_failed_command)
            self.assertEqual(service.config.model, 'next-model')
            self.assertEqual(service.get(original)['model'], 'test')
            self.assertEqual(service.new()['model'], 'next-model')

    async def test_settings_menu_and_recovery_actions_preserve_pending_reply(self):
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            service = self.make_service(tmp, TextProvider(ForgeError('Provider timed out'), 'Recovered'))
            ui = TerminalChat(service, input=pipe, output=DummyOutput())
            ui.composer.text = 'Help'
            await ui.send()
            self.assertEqual(ui.action_title, 'Recovery actions')
            self.assertEqual(ui.current['pending_message'], 'Help')
            labels = [choice['label'] for choice in ui.action_choices]
            self.assertIn('Adjust timeout', labels)
            self.assertIn('Export session logs', labels)
            await ui.accept_action()
            self.assertIsNone(ui.current['pending_message'])
            self.assertIn('Recovered', ui.conversation.text)
            ui.composer.text = '/settings'
            await ui.send()
            self.assertEqual(ui.action_title, 'Settings')
            ui.action_index = 1
            await ui.accept_action()
            self.assertEqual(ui.composer.text, '/settings timeout ')

    async def test_history_search_matches_errors_and_opens_selected_chat(self):
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            service = self.make_service(tmp, TextProvider(ForgeError('Unique provider failure')))
            original = service.new()['id']
            with self.assertRaises(ForgeError):
                service.send(original, 'Billing question')
            self.assertEqual(service.history('unique provider')[0]['id'], original)
            self.assertEqual(service.history('BILLING')[0]['id'], original)
            ui = TerminalChat(service, input=pipe, output=DummyOutput())
            ui.composer.text = '/history unique provider'
            await ui.send()
            self.assertEqual(len(ui.action_choices), 1)
            await ui.accept_action()
            self.assertEqual(ui.current['id'], original)
            self.assertEqual(ui.current['pending_message'], 'Billing question')

    async def test_plan_review_and_request_usage_indicators_preserve_approval(self):
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            service = self.make_service(tmp, TextProvider(json.dumps({'questions': []}), json.dumps({'plan': '# Plan\n\n## Affected files\ncalculator.py\n\n## Verification\nManual check\n\n## Risks\nZero division'})))
            ui = TerminalChat(service, input=pipe, output=DummyOutput())
            for command in ('/prepare', '/plan'):
                ui.composer.text = command
                await ui.send()
            self.assertTrue(ui.plan_visible)
            self.assertIn('calculator.py', ui.plan_screen.text)
            self.assertIn('Stage: planned', ui.context_indicator())
            self.assertIn('Request: default', ui.context_indicator())
            self.assertNotIn('not sent yet', ui.usage_indicator())
            self.assertIn('Tokens: unavailable', ui.usage_indicator())
            self.assertFalse(Audit.open(service.workspace, ui.current['workflow_run']).load().get('approved_plan'))
            self.assertEqual(len(service.provider.calls), 2)

    async def test_history_can_select_unprepared_request_without_model_call(self):
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            service = self.make_service(tmp)
            ui = TerminalChat(service, input=pipe, output=DummyOutput())
            ui.composer.text = '/history billing'
            await ui.send()
            self.assertEqual(ui.action_choices[0]['request'], DEFAULT_REQUEST)
            await ui.accept_action()
            self.assertEqual(ui.current['request_path'], DEFAULT_REQUEST)
            self.assertEqual(ui.composer.text, '/prepare')
            self.assertEqual(service.provider.calls, [])

    async def test_keyboard_recovery_can_edit_timeout_without_discarding_message(self):
        from test_terminal_chat import WideOutput
        with tempfile.TemporaryDirectory() as tmp, create_pipe_input() as pipe:
            service = self.make_service(tmp, TextProvider(ForgeError('Provider timed out')))
            ui = TerminalChat(service, input=pipe, output=WideOutput())
            ui.composer.text = 'Question'
            await ui.send()
            task = asyncio.create_task(ui.run())
            try:
                await asyncio.sleep(.05)
                pipe.send_text('\x1b[B\r')
                for _ in range(100):
                    if ui.composer.text == '/settings timeout ':
                        break
                    await asyncio.sleep(.01)
                self.assertEqual(ui.composer.text, '/settings timeout ')
                pipe.send_text('600\r')
                for _ in range(100):
                    if service.config.timeout == 600 and not ui.busy:
                        break
                    await asyncio.sleep(.01)
                self.assertEqual(service.config.timeout, 600)
                self.assertEqual(ui.current['pending_message'], 'Question')
                pipe.send_text('\x11')
                await asyncio.wait_for(task, 2)
            finally:
                if ui.app.is_running:
                    ui.app.exit()
                await task

    async def test_settings_reconfigure_http_adapter_and_preserve_unrelated_config(self):
        from solar_forge.providers import HTTPProvider
        with tempfile.TemporaryDirectory() as tmp:
            service = self.make_service(tmp)
            service.provider = HTTPProvider(service.config)
            path = Path(tmp) / '.forge/config.toml'
            path.write_text(path.read_text() + '\n# Preserve this local comment\n')
            before = service.provider
            service.settings(None, 'timeout 600')
            self.assertIsNot(service.provider, before)
            self.assertEqual(service.provider.config.timeout, 600)
            self.assertEqual(service.provider.audit_identity, before.audit_identity)
            self.assertIn('# Preserve this local comment', path.read_text())
            self.assertEqual(Config.load(path).verification, service.config.verification)

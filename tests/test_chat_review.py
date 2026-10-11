import asyncio
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from solar_forge.audit import Audit
from solar_forge.chat import ChatService
from solar_forge.chat_stream import StreamDisplay
from solar_forge.domain import Config, ForgeError
from solar_forge.requests import DEFAULT_REQUEST, write_request
from solar_forge.terminal_chat import TerminalChat, display
from solar_forge.workspace import Workspace
from test_chat import TextProvider
from test_foundation import REQUEST
from test_workflow import QUESTION


class ChatReviewTests(unittest.IsolatedAsyncioTestCase):
    def service(self, root, *responses):
        workspace = Workspace(Path(root))
        write_request(workspace, DEFAULT_REQUEST, REQUEST)
        return ChatService(workspace, Config(model='test'), TextProvider(*responses))

    async def test_continue_uses_real_draft_state_and_keeps_unsent_text(self):
        with tempfile.TemporaryDirectory() as root, create_pipe_input() as pipe:
            service = self.service(root)
            ui = TerminalChat(service, input=pipe, output=DummyOutput())
            ui.current = service.command(service.new()['id'], '/request')
            ui.composer.text = 'My unfinished task title'
            ui.show_continue()
            self.assertIsNone(ui.action_choices)
            self.assertEqual(ui.composer.text, 'My unfinished task title')
            self.assertIn('Enter saves', ui.notice)
            for answer in ('Task', 'Description', 'Constraints', 'Expected result'):
                ui.current = service.command(ui.current['id'], answer)
            ui.show_continue()
            self.assertEqual(ui.action_choices[0]['command'], '/save-request')
            await ui.accept_action()
            self.assertIsNone(ui.current['command_error'])
            self.assertEqual(ui.next_action()[1], '/start')
            self.assertEqual(service.provider.calls, [])

    async def test_continue_keeps_question_answer_and_recovers_pending_reply(self):
        with tempfile.TemporaryDirectory() as root, create_pipe_input() as pipe:
            service = self.service(root, json.dumps(QUESTION), ForgeError('Connection failed'))
            ui = TerminalChat(service, input=pipe, output=DummyOutput())
            ui.current = service.command(service.new()['id'], '/start')
            ui.composer.text = 'Use UTC and '
            ui.show_continue()
            self.assertEqual(ui.composer.text, 'Use UTC and ')
            self.assertIsNone(ui.action_choices)
            with self.assertRaises(ForgeError):
                service.send(ui.current['id'], 'Help me decide')
            ui.current = service.get(ui.current['id'])
            ui.show_continue()
            await ui.accept_action()
            self.assertEqual(ui.action_title, 'Recovery actions')
            self.assertTrue(ui.action_choices[0]['retry'])

    async def test_continue_reopens_unreviewed_plan_without_model_call_or_approval(self):
        with tempfile.TemporaryDirectory() as root, create_pipe_input() as pipe:
            service = self.service(root, json.dumps({'questions': []}), json.dumps({'plan': '# Plan\nInspect files.'}))
            session = service.new()['id']
            result = service.command(session, '/start')
            service.command(session, '/cancel')
            ui = TerminalChat(service, resume=session, input=pipe, output=DummyOutput())
            self.assertIsNone(ui.current['reviewed_plan'])
            ui.show_continue()
            await ui.accept_action()
            self.assertTrue(ui.plan_visible)
            self.assertIsNotNone(ui.current['reviewed_plan'])
            self.assertFalse(Audit.open(service.workspace, result['workflow_run']).load().get('approved_plan'))
            self.assertEqual(len(service.provider.calls), 2)

    async def test_turn_limit_continue_reflects_updated_setting(self):
        with tempfile.TemporaryDirectory() as root:
            service = self.service(root, json.dumps({'questions': []}), json.dumps({'plan': '# Plan\nInspect files.'}))
            session = service.new()['id']
            result = service.command(session, '/start')
            service.command(session, '/cancel')
            run = Audit.open(service.workspace, result['workflow_run'])
            state = run.load()
            state.update(status='turn_limit', turns=service.config.max_turns)
            run.save(state)
            self.assertEqual(service.get(session)['next_action'][1], '/settings')
            service.config = replace(service.config, max_turns=service.config.max_turns + 1)
            self.assertEqual(service.get(session)['next_action'][1], '/run')

    async def test_history_metadata_does_not_load_chat_views_or_progress(self):
        with tempfile.TemporaryDirectory() as root:
            service = self.service(root)
            session = service.new()['id']
            with patch.object(service, 'get', side_effect=AssertionError('Full chat view loaded')), \
                    patch('solar_forge.chat.read_progress', side_effect=AssertionError('Progress loaded')):
                self.assertEqual(service.list()[0]['id'], session)
                self.assertEqual(service.history()[0]['id'], session)
                self.assertEqual(service.history('new chat')[0]['id'], session)

    async def test_stream_batches_preserve_order_and_ignore_late_chunks(self):
        chunks = []
        stream = StreamDisplay(asyncio.get_running_loop(), chunks.append, interval=.01)
        await asyncio.to_thread(lambda: [stream.push(str(i) + ',') for i in range(1000)])
        await asyncio.sleep(.05)
        self.assertEqual(''.join(chunks), ''.join(str(i) + ',' for i in range(1000)))
        self.assertLess(len(chunks), 10)
        stream.push('not rendered before close')
        stream.close()
        stream.push('late callback')
        await asyncio.sleep(.05)
        self.assertNotIn('callback', ''.join(chunks))
        self.assertNotIn('close', ''.join(chunks))

    async def test_stream_render_reuses_history_and_preserves_reading_position(self):
        with tempfile.TemporaryDirectory() as root, create_pipe_input() as pipe:
            service = self.service(root)
            ui = TerminalChat(service, input=pipe, output=DummyOutput())
            ui.current = service.new()
            long_message = 'Earlier text\n' * 100
            ui.current['messages'] = [{'role': 'assistant', 'content': long_message}]
            ui.render()
            ui.conversation.buffer.cursor_position = 10
            ui.conversation.window.vertical_scroll = 3
            with patch('solar_forge.terminal_chat.display', wraps=display) as sanitize:
                for part in ('First', 'Second', 'Third'):
                    ui.partial_reply += part
                    ui.render()
                self.assertNotIn(long_message, [call.args[0] for call in sanitize.call_args_list])
            self.assertEqual(ui.conversation.buffer.cursor_position, 10)
            self.assertEqual(ui.conversation.window.vertical_scroll, 3)
            ui.conversation.buffer.cursor_position = len(ui.conversation.text)
            ui.partial_reply += 'Fourth'
            ui.render()
            self.assertEqual(ui.conversation.buffer.cursor_position, len(ui.conversation.text))

    async def test_burst_stream_saves_complete_response_without_late_preview(self):
        class BurstProvider:
            def stream(self, system, messages):
                yield from ('word ' for _ in range(1000))

        with tempfile.TemporaryDirectory() as root, create_pipe_input() as pipe:
            service = self.service(root)
            service.provider = BurstProvider()
            ui = TerminalChat(service, input=pipe, output=DummyOutput())
            ui.composer.text = 'Hello'
            with patch.object(ui, 'render', wraps=ui.render) as render:
                await ui.send()
                await asyncio.sleep(.1)
                self.assertLess(render.call_count, 20)
            self.assertEqual(ui.current['messages'][-1]['content'], 'word ' * 1000)
            self.assertEqual(service.get(ui.current['id'])['messages'], ui.current['messages'])
            self.assertEqual(ui.partial_reply, '')
            self.assertNotIn('Forge (streaming', ui.conversation.text)

    async def test_f2_keyboard_keeps_draft_text(self):
        from test_terminal_chat import WideOutput
        with tempfile.TemporaryDirectory() as root, create_pipe_input() as pipe:
            service = self.service(root)
            ui = TerminalChat(service, input=pipe, output=WideOutput())
            ui.current = service.command(service.new()['id'], '/request')
            ui.composer.text = 'Unsent title'
            task = asyncio.create_task(ui.run())
            try:
                await asyncio.sleep(.05)
                pipe.send_text('\x1bOQ')  # F2
                for _ in range(100):
                    if 'Enter saves' in ui.notice:
                        break
                    await asyncio.sleep(.01)
                self.assertIn('Enter saves', ui.notice)
                self.assertEqual(ui.composer.text, 'Unsent title')
                self.assertTrue(ui.app.layout.has_focus(ui.composer))
                self.assertIsNone(ui.action_choices)
            finally:
                if ui.app.is_running:
                    ui.app.exit()
                await task

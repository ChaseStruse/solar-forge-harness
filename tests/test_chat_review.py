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
from solar_forge.domain import Config, ForgeError
from solar_forge.requests import DEFAULT_REQUEST, write_request
from solar_forge.terminal_chat import TerminalChat
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

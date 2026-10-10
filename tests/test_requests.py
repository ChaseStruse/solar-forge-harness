from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from solar_forge.cli import main
from solar_forge.domain import Config, ForgeError
from solar_forge.requests import DEFAULT_REQUEST, current_request, read_request, write_request
from solar_forge.workflow import prepare, assert_current
from solar_forge.workspace import Workspace
from test_foundation import REQUEST
from test_workflow import ScriptedProvider


class RequestBundleTests(unittest.TestCase):
    def test_state_attachment_does_not_break_run_discovery(self):
        from solar_forge.audit import Audit
        from solar_forge.chat import ChatService
        from solar_forge.domain import Request
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            write_request(ws, DEFAULT_REQUEST, REQUEST)
            attachment = ws.root / Path(DEFAULT_REQUEST).parent / 'state.json'
            attachment.write_text('not even JSON')
            # A real run with the slug "requests" must still be discoverable.
            run = Audit.create(ws, Request.parse(REQUEST.replace('Add billing export', 'Requests')))
            service = ChatService(ws, Config(model='test'), ScriptedProvider())
            session = service.new()['id']
            self.assertEqual(len(service.list()), 1)
            result = service.command(session, '/runs')
            self.assertIsNone(result['command_error'])
            self.assertIn(run.path.relative_to(ws.root).as_posix(), result['messages'][-1]['content'])
            out = StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(['--project', tmp, 'status']), 0)
            self.assertIn('Requests', out.getvalue())
            run.write('state.json', '{broken')
            with self.assertWarnsRegex(RuntimeWarning, 'Skipping unreadable run'):
                self.assertEqual(len(service.list()), 1)

    def test_cli_requires_bundle_and_uses_title(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            root = Path(tmp)
            self.assertEqual(main(['--project', tmp, 'request', 'Billing export']), 0)
            self.assertTrue((root / 'agentic_audit/requests/billing-export/request.md').is_file())
            for name in ('request.md', 'requests/billing.md', 'docs/requests/billing.md',
                         'agentic_audit/requests/billing/other.md',
                         'agentic_audit/requests/../outside/request.md'):
                self.assertEqual(main(['--project', tmp, 'request', 'Bad', '--output', name]), 1)
            self.assertFalse((root / 'request.md').exists())

    def test_prepare_rejects_external_requests_without_model_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            (ws.root / 'request.md').write_text(REQUEST)
            with self.assertRaisesRegex(ForgeError, 'Requests must be'):
                prepare(ws, Config(), 'request.md', ScriptedProvider())
            self.assertFalse((ws.root / 'agentic_audit').exists())

    def test_bundle_context_is_scoped_and_changes_invalidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            write_request(ws, DEFAULT_REQUEST, REQUEST)
            folder = ws.root / Path(DEFAULT_REQUEST).parent
            (folder / 'context').mkdir()
            extra = folder / 'context/domain.txt'
            extra.write_text('Use UTC for invoice dates.')
            (folder / 'image.png').write_bytes(b'\x00binary')
            (folder / '.env').write_text('SECRET')
            (folder / 'linked.md').symlink_to(extra)
            write_request(ws, 'agentic_audit/requests/other/request.md', REQUEST)
            audit = prepare(ws, Config(), DEFAULT_REQUEST, ScriptedProvider({'questions': []}))
            docs = json.loads(audit.read('context.json'))['documents']
            selected = {k for k in docs if k.startswith('agentic_audit/')}
            self.assertEqual(selected, {'agentic_audit/requests/default/context/domain.txt'})
            assert_current(ws, Config(), audit)
            extra.write_text('Use local time.')
            with self.assertRaisesRegex(ForgeError, 'changed since discovery'):
                assert_current(ws, Config(), audit)
            with self.assertRaises(ForgeError):
                ws.write(DEFAULT_REQUEST, 'Agent tampering')
            self.assertEqual(read_request(ws, DEFAULT_REQUEST), REQUEST)

    def test_selection_symlinks_and_size_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            write_request(ws, DEFAULT_REQUEST, REQUEST)
            self.assertEqual(current_request(ws), DEFAULT_REQUEST)
            write_request(ws, 'agentic_audit/requests/second/request.md', REQUEST)
            with self.assertRaisesRegex(ForgeError, 'Multiple requests'):
                current_request(ws)
            link = ws.root / 'agentic_audit/requests/link'
            link.symlink_to(ws.root / Path(DEFAULT_REQUEST).parent, target_is_directory=True)
            with self.assertRaisesRegex(ForgeError, 'Symlink'):
                read_request(ws, 'agentic_audit/requests/link/request.md')
            with self.assertRaises(ForgeError):
                prepare(Workspace(ws.root, max_file_bytes=1), Config(), DEFAULT_REQUEST, ScriptedProvider())

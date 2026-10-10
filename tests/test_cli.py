from contextlib import redirect_stdout, redirect_stderr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

from solar_forge.requests import DEFAULT_REQUEST, read_request, write_request
from solar_forge.cli import main
from solar_forge.domain import CONFIG_TEMPLATE
from test_foundation import REQUEST


class CLITests(unittest.TestCase):
    def invoke(self, root, *arguments):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(['--project', str(root), *arguments])
        self.assertEqual(code, 0, err.getvalue())
        return out.getvalue()

    def test_existing_run_rejects_identity_overrides_before_call_or_approval(self):
        from solar_forge.domain import Config
        from solar_forge.workflow import prepare, plan
        from solar_forge.workspace import Workspace
        from test_workflow import ScriptedProvider
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = Workspace(root)
            write_request(ws, DEFAULT_REQUEST, REQUEST)
            cfg = Config(model='original')
            audit = prepare(ws, cfg, DEFAULT_REQUEST, ScriptedProvider({'questions': []}))
            plan(ws, cfg, audit, ScriptedProvider({'plan': '# Plan'}))
            (root / '.forge').mkdir()
            config_path = root / '.forge/config.toml'
            original = '[provider]\nkind = "ollama"\nmodel = "original"\n'
            relative = audit.path.relative_to(root).as_posix()
            cases = [(original, ['--model', 'replacement']),
                     (original, ['--provider', 'compatible']),
                     (original.replace('original', 'replacement'), []),
                     (original + 'base_url = "http://localhost:11435"\n', [])]
            for config_text, flags in cases:
                config_path.write_text(config_text)
                for command in ('discover', 'plan', 'run'):
                    with self.subTest(command=command, flags=flags, config=config_text), \
                            patch('solar_forge.providers.post_json') as post, \
                            redirect_stderr(StringIO()) as err, redirect_stdout(StringIO()):
                        args = ['--project', tmp, command, relative, *flags]
                        if command == 'run':
                            args.append('--approve')
                        self.assertEqual(main(args), 1)
                        self.assertIn('different model, provider, or endpoint', err.getvalue())
                        post.assert_not_called()
                        self.assertIsNone(audit.load()['approved_plan'])
            # Legacy audit state lacking endpoint remains usable with its saved model.
            config_path.write_text(original)
            state = audit.load()
            state.pop('endpoint')
            audit.save(state)
            with patch('solar_forge.providers.post_json', return_value={
                    'message': {'content': json.dumps({'plan': '# Updated plan'})}}):
                self.invoke(root, 'plan', relative)
            record = json.loads(next((audit.path / 'calls').glob('*-input.json')).read_text())
            self.assertIn('identity', record)

    def test_full_workflow_over_local_http(self):
        responses = iter([
            {'questions': [{'question': 'Which timezone?', 'rationale': 'Date boundary rule.', 'sources': ['request.md']}]},
            {'plan': '# Plan\nCreate export.py with UTC support.'},
            {'tool': 'write_file', 'path': 'export.py', 'content': 'TIMEZONE = "UTC"\n'},
            {'tool': 'finish', 'summary': 'Added UTC constant.', 'verification': 'Inspect export.py.'},
        ])
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(request)
                content = json.dumps({'message': {'content': json.dumps(next(responses))}}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server, tempfile.TemporaryDirectory() as tmp:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                root = Path(tmp)
                self.invoke(root, 'init')
                (root / DEFAULT_REQUEST).write_bytes(REQUEST.replace('\n', '\r\n').encode())
                # Repeat init preserves the user's request and configuration.
                self.invoke(root, 'init')
                self.assertEqual((root / DEFAULT_REQUEST).read_bytes(), REQUEST.replace('\n', '\r\n').encode())
                port = server.server_address[1]
                config = CONFIG_TEMPLATE.replace('"CHANGE_ME"', '"test-model"').replace(
                    '# base_url = "http://localhost:11434"', f'base_url = "http://127.0.0.1:{port}"')
                (root / '.forge/config.toml').write_text(config)
                self.invoke(root, 'prepare', '--no-interactive')
                run_path = next(root.glob('agentic_audit/*/*/state.json')).parent.relative_to(root).as_posix()
                self.invoke(root, 'answer', run_path, '--question', 'Q1', '--text', 'UTC')
                self.invoke(root, 'plan', run_path)
                self.invoke(root, 'run', run_path, '--approve')
                self.assertIn('review_required', self.invoke(root, 'status', run_path))
                self.assertEqual((root / 'export.py').read_text(), 'TIMEZONE = "UTC"\n')
                self.assertEqual(len(requests), 4)
                self.assertTrue(all(r['model'] == 'test-model' for r in requests))
                self.assertTrue(all(r['stream'] is False for r in requests))
            finally:
                server.shutdown()
                thread.join(timeout=2)

    def test_request_creation_and_missing_config_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.invoke(root, 'request', 'Export billing', '--output', 'agentic_audit/requests/export/request.md')
            self.assertIn('# Request: Export billing', (root / 'agentic_audit/requests/export/request.md').read_text())
            with redirect_stderr(StringIO()) as err:
                code = main(['--project', str(root), 'prepare'])
            self.assertEqual(code, 1)
            self.assertIn('config.toml', err.getvalue())

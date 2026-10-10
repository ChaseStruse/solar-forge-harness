"""Offline review probes. Run with PYTHONPATH=src python <this file>."""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from solar_forge.agent import approve, run
from solar_forge.chat import ChatService
from solar_forge.cli import main
from solar_forge.domain import Config, ForgeError
from solar_forge.requests import DEFAULT_REQUEST, write_request
from solar_forge.workflow import prepare, plan
from solar_forge.workspace import Workspace

REQUEST = '# Request: Review probe\n\n## Description\nProbe behavior.\n\n## Technical Details\nOffline.\n\n## Acceptance Criteria\n- Evidence recorded.\n'

class Provider:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = 0
    def complete(self, system, messages):
        self.calls += 1
        return json.dumps(next(self.responses))


def run_setup(root):
    ws = Workspace(root)
    cfg = Config(model='original')
    write_request(ws, DEFAULT_REQUEST, REQUEST)
    provider = Provider({'questions': []}, {'plan': '# Plan\nPerform the probe.'})
    audit = prepare(ws, cfg, DEFAULT_REQUEST, provider)
    plan(ws, cfg, audit, provider)
    approve(audit)
    return ws, cfg, audit


def discovery_collision():
    with tempfile.TemporaryDirectory() as tmp:
        ws, cfg, audit = run_setup(Path(tmp))
        attachment = ws.root / Path(DEFAULT_REQUEST).parent / 'state.json'
        attachment.write_text('{"example": "user context"}')
        service = ChatService(ws, cfg, Provider())
        try:
            service.list()
        except ForgeError as exc:
            print('F1 chat listing:', exc)
        else:
            raise AssertionError('Expected attachment/run collision')
        err = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(err):
            result = main(['--project', tmp, 'status'])
        assert result == 1
        print('F1 status exit:', result, err.getvalue().strip())


def external_request_write():
    with tempfile.TemporaryDirectory() as tmp:
        ws, cfg, audit = run_setup(Path(tmp))
        provider = Provider({'tool': 'write_file', 'path': 'request.md', 'content': REQUEST},
                            {'tool': 'finish', 'summary': 'Done', 'verification': 'Review'})
        run(ws, cfg, audit, provider)
        assert (ws.root / 'request.md').exists()
        print('F2 root request written:', (ws.root / 'request.md').exists(), 'status:', audit.load()['status'])


def pending_budget_trap():
    with tempfile.TemporaryDirectory() as tmp:
        service = ChatService(Workspace(Path(tmp)), Config(model='probe', max_prompt_bytes=100), Provider())
        session = service.new()['id']
        for label, operation in [
            ('send', lambda: service.send(session, 'hello')),
            ('retry', lambda: service.send(session, retry=True)),
            ('cancel', lambda: service.command(session, '/cancel')),
            ('status', lambda: service.command(session, '/status')),
        ]:
            try:
                operation()
            except ForgeError as exc:
                print('F3', label + ':', exc)
            else:
                raise AssertionError('Expected pending-message trap')
        assert service.get(session)['pending_message'] == 'hello'
        assert service.provider.calls == 0


def cli_model_provenance():
    with tempfile.TemporaryDirectory() as tmp:
        ws, cfg, audit = run_setup(Path(tmp))
        (ws.root / '.forge').mkdir()
        (ws.root / '.forge/config.toml').write_text('[provider]\nkind = "ollama"\nmodel = "original"\n')
        provider = Provider({'tool': 'finish', 'summary': 'Done', 'verification': 'Review'})
        with patch('solar_forge.cli.HTTPProvider', return_value=provider) as factory, redirect_stdout(StringIO()):
            result = main(['--project', tmp, 'run', audit.path.relative_to(ws.root).as_posix(), '--model', 'replacement', '--approve'])
        assert result == 0 and provider.calls == 1
        actual = factory.call_args.args[0].model
        recorded = audit.load()['model']
        assert actual != recorded
        print('F4 execution model:', actual, 'audit model:', recorded)


if __name__ == '__main__':
    discovery_collision()
    external_request_write()
    pending_budget_trap()
    cli_model_provenance()

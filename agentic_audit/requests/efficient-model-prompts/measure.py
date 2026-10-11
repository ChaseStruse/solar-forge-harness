"""Deterministic prompt-byte comparison; no model or network calls."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
from solar_forge.workspace import Workspace, atomic_write
from solar_forge.domain import Config, Request
from solar_forge.context import bundled_guidance
from solar_forge.requests import DEFAULT_REQUEST, write_request
from solar_forge.workflow import prepare, plan
from solar_forge.agent import approve, run
from solar_forge.chat import ChatService

class Provider:
    def __init__(self):
        self.calls = []
        self.answers = iter(['{"questions":[]}', '{"plan":"Implement calculator.py and main.py; document functions; manually run basic arithmetic and zero division checks."}', '{"tool":"finish","summary":"No edits in this measurement fixture.","verification":"Manual review."}', 'Use /prepare to start.'])
    def complete(self, system, messages):
        self.calls.append((system, messages.copy()))
        return next(self.answers)

with tempfile.TemporaryDirectory() as tmp:
    ws = Workspace(Path(tmp))
    for name, value in bundled_guidance().items():
        atomic_write(ws.path('.forge/standards/' + name.split('/')[-1], internal=True), value)
    write_request(ws, DEFAULT_REQUEST, '# Request: Calculator\n\n## Description\nBasic addition, subtraction, multiplication, division.\n\n## Technical Details\nTwo Python files: calculator.py and main.py, plus documentation.\n\n## Acceptance Criteria\nRun the calculator and see correct results.\n')
    cfg = Config(model='fixture', docs=['.forge/standards'])
    provider = Provider()
    audit = prepare(ws, cfg, DEFAULT_REQUEST, provider)
    plan(ws, cfg, audit, provider)
    approve(audit)
    run(ws, cfg, audit, provider)
    chat = ChatService(ws, cfg, provider)
    session = chat.new()
    chat.send(session['id'], 'How do I start?')
    print(json.dumps({stage: len(json.dumps({'system': system, 'messages': messages}, ensure_ascii=False).encode()) for stage, (system, messages) in zip(['discovery', 'planning', 'coding', 'chat'], provider.calls)}, indent=2))

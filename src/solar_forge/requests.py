"""Mandatory request bundles inside the audit directory."""
import re
from .domain import ForgeError
from .workspace import Workspace, atomic_write

ROOT = 'agentic_audit/requests'
DEFAULT_REQUEST = ROOT + '/default/request.md'


def request_name(title: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:80] or 'request'
    return f'{ROOT}/{slug}/request.md'


def request_path(workspace: Workspace, name: str):
    if not re.fullmatch(r'agentic_audit/requests/[a-z0-9][a-z0-9-]*/request\.md', name):
        raise ForgeError('Requests must be agentic_audit/requests/<request-name>/request.md. '
                         'Move the request and its supporting files there before preparing it.')
    return workspace.path(name, internal=True)


def read_request(workspace: Workspace, name: str) -> str:
    request_path(workspace, name)
    return workspace.read(name, internal=True)


def write_request(workspace: Workspace, name: str, text: str) -> None:
    path = request_path(workspace, name)
    if len(text.encode('utf-8')) > workspace.max_file_bytes:
        raise ForgeError('Request exceeds configured file size limit.')
    atomic_write(path, text)


def current_request(workspace: Workspace, name: str | None = None) -> str:
    if name:
        request_path(workspace, name)
        return name
    root = workspace.path(ROOT, internal=True)
    choices = sorted(p.relative_to(workspace.root).as_posix() for p in root.glob('*/request.md'))
    if len(choices) > 1:
        raise ForgeError('Multiple requests exist. Specify agentic_audit/requests/<request-name>/request.md.')
    return choices[0] if choices else DEFAULT_REQUEST

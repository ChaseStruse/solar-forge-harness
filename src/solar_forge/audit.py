"""Run artifacts, atomic state checkpoints, and append-only event records."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import uuid
import warnings

from .domain import ForgeError, Request
from .workspace import Workspace, atomic_write


RUN_PATH = re.compile(r"agentic_audit/[a-z0-9-]+/[0-9]{8}T[0-9]{6}-[a-f0-9]{10}")

def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Audit:
    def __init__(self, path: Path):
        self.path = path

    @classmethod
    def create(cls, workspace: Workspace, request: Request) -> "Audit":
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:10]
        path = workspace.path(f"agentic_audit/{request.slug}/{run_id}", internal=True)
        path.mkdir(parents=True)
        audit = cls(path)
        audit.write("request.md", request.markdown)
        audit.save({"version": 1, "title": request.title, "status": "discovering",
                    "created_at": now(), "questions": [], "messages": [], "turns": 0})
        audit.event("created", title=request.title)
        return audit

    @classmethod
    def open(cls, workspace: Workspace, relative: str) -> "Audit":
        if not RUN_PATH.fullmatch(relative.rstrip("/")):
            raise ForgeError("Run must be agentic_audit/<request-slug>/<run-id>.")
        path = workspace.path(relative.rstrip("/"), internal=True)
        if not path.is_dir() or not (path / "state.json").is_file():
            raise ForgeError("Run does not exist or has no state.json.")
        for child in path.rglob("*"):
            if child.is_symlink():
                raise ForgeError("Audit contains an unsafe symlink.")
        return cls(path)

    @classmethod
    def discover(cls, workspace: Workspace) -> list["Audit"]:
        """Enumerate run-shaped paths, leaving request attachments alone."""
        root = workspace.path('agentic_audit', internal=True)
        runs = []
        for state_path in sorted(root.glob('*/*/state.json')):
            relative = state_path.parent.relative_to(workspace.root).as_posix()
            if not RUN_PATH.fullmatch(relative):
                continue
            try:
                audit = cls.open(workspace, relative)
                audit.load()
            except (ForgeError, OSError) as exc:
                warnings.warn(f'Skipping unreadable run {relative}: {exc}', RuntimeWarning)
                continue
            runs.append(audit)
        return runs

    def write(self, name: str, content: str) -> None:
        path = self.path / name
        if path.is_symlink():
            raise ForgeError("Audit file is a symlink.")
        atomic_write(path, content)

    def save(self, state: dict) -> None:
        self.write("state.json", json.dumps(state, indent=2, ensure_ascii=False) + "\n")

    def read(self, name: str) -> str:
        # Preserve CRLF exactly, including request and change snapshots.
        return (self.path / name).read_bytes().decode("utf-8")

    def load(self) -> dict:
        try:
            state = json.loads((self.path / "state.json").read_text())
            if state.get("version") != 1:
                raise ForgeError("Unsupported audit state version.")
            return state
        except (OSError, ValueError, AttributeError) as exc:
            raise ForgeError("Cannot read audit state.json.") from exc

    def event(self, kind: str, **details) -> None:
        path = self.path / "events.jsonl"
        if path.is_symlink():
            raise ForgeError("Audit event file is a symlink.")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": now(), "type": kind, **details}, ensure_ascii=False) + "\n")

    @contextmanager
    def lock(self):
        path = self.path / ".lock"
        try:
            with path.open("x") as handle:
                handle.write(now())
        except FileExistsError as exc:
            raise ForgeError("Run is locked. If its process exited, remove its .lock file before resuming.") from exc
        try:
            yield
        finally:
            path.unlink(missing_ok=True)

    def questions(self, state: dict) -> None:
        text = "# Domain questions\n\n"
        for q in state["questions"]:
            text += (f"## {q['id']}: {q['question']}\n\n"
                     f"Why this matters: {q['rationale']}\n\n"
                     f"Sources: {', '.join(q['sources'])}\n\n"
                     f"Answer: {q.get('answer') or '(pending)'}\n\n")
        self.write("questions.md", text)

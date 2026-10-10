"""Bounded file access shared by context collection and agent tools."""
from pathlib import Path
import os
import tempfile

from .domain import ForgeError

PROTECTED = {".git", ".forge", "agentic_audit", ".agents", ".codex"}
EXCLUDED = PROTECTED | {".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
SENSITIVE = {".aws", ".ssh", ".gnupg", ".env", "credentials", "secrets", "id_rsa", "id_ed25519"}


# These names are reserved for harness artifacts, not application output.
ROOT_ARTIFACTS = {'plan.md', 'summary.md', 'questions.md', 'decisions.md',
                  'context.md', 'progress.md', 'verification.md'}


def request_artifact(path: Path) -> bool:
    parts = tuple(part.lower() for part in path.parts)
    name = parts[-1]
    return (name in {'request.md', 'implementation-plan.md'}
            or name.endswith('-implementation-plan.md')
            or parts[0] == 'requests'
            or parts[:2] == ('docs', 'requests')
            or (len(parts) == 1 and name in ROOT_ARTIFACTS))


def sensitive(part: str) -> bool:
    name = part.lower()
    return name in SENSITIVE or name.startswith(".env.") or name.endswith((".pem", ".key", ".p12", ".pfx"))


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".forge-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        if path.exists():
            os.chmod(temp, path.stat().st_mode & 0o777)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class Workspace:
    def __init__(self, root: Path, max_file_bytes: int = 100000):
        self.root = root.resolve()
        self.max_file_bytes = max_file_bytes

    def path(self, relative: str, *, write: bool = False, internal: bool = False) -> Path:
        rel = Path(relative)
        if not relative or rel.is_absolute() or ".." in rel.parts or rel == Path("."):
            raise ForgeError("Use a project-relative file path without '..'.")
        if any(sensitive(part) for part in rel.parts):
            raise ForgeError("Credential and secret paths are excluded.")
        if not internal and any(part in PROTECTED - {".forge"} for part in rel.parts):
            raise ForgeError("Harness, Git, and audit paths are protected.")
        if write and not internal and (any(part in PROTECTED for part in rel.parts) or rel.name == "AGENTS.md"):
            raise ForgeError("Project policies and audit records cannot be changed by agents.")
        if write and not internal and request_artifact(rel):
            raise ForgeError('Request artifacts must be stored under agentic_audit; '
                             'the model cannot write them through project file tools.')
        path = self.root
        for part in rel.parts:
            path = path / part
            if path.is_symlink():
                raise ForgeError("Symlink access is not allowed.")
        if not path.resolve().is_relative_to(self.root):
            raise ForgeError("Path escapes the project.")
        return path

    def read(self, relative: str, *, internal: bool = False) -> str:
        path = self.path(relative, internal=internal)
        if not path.is_file():
            raise ForgeError(f"Not a file: {relative}")
        if path.stat().st_size > self.max_file_bytes:
            raise ForgeError(f"File exceeds {self.max_file_bytes} bytes: {relative}")
        try:
            raw = path.read_bytes()
            if len(raw) > self.max_file_bytes or b"\0" in raw:
                raise ForgeError(f"Oversized or binary file: {relative}")
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ForgeError(f"Not UTF-8 text: {relative}") from exc

    def write(self, relative: str, content: str) -> None:
        if len(content.encode("utf-8")) > self.max_file_bytes:
            raise ForgeError("Write exceeds configured file size limit.")
        path = self.path(relative, write=True)
        if path.exists() and not path.is_file():
            raise ForgeError("Write target is not a regular file.")
        atomic_write(path, content)

    def inventory(self, limit: int = 500) -> list[str]:
        files: list[str] = []
        for directory, dirs, names in os.walk(self.root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not sensitive(d)
                             and not (Path(directory) / d).is_symlink())
            for name in sorted(names):
                if sensitive(name) or (Path(directory) / name).is_symlink():
                    continue
                files.append((Path(directory) / name).relative_to(self.root).as_posix())
                if len(files) >= limit:
                    return files
        return files

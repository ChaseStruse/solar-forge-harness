"""Collect explicit documentation with provenance and size limits."""
from importlib.resources import files
import os
from pathlib import Path

from .domain import Config, ForgeError
from .requests import request_path as validate_request_path
from .workspace import EXCLUDED, Workspace, sensitive

DOCUMENT_SUFFIXES = {'.md', '.txt', '.rst'}


def document_paths(workspace: Workspace, name: str, *, internal=False):
    path = workspace.path(name, internal=internal)
    if not path.is_dir():
        yield name
        return
    for directory, dirs, names in os.walk(path, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not sensitive(d)
                         and not (Path(directory) / d).is_symlink())
        for filename in sorted(names):
            child = Path(directory) / filename
            if (child.suffix.lower() in DOCUMENT_SUFFIXES and not sensitive(filename)
                    and not child.is_symlink() and child.is_file()):
                yield child.relative_to(workspace.root).as_posix()


def bundled_guidance() -> dict[str, str]:
    root = files("solar_forge").joinpath("guidance")
    return {f"builtin/{name}": root.joinpath(name).read_text(encoding="utf-8")
            for name in ("coding.md", "architecture.md", "deployment.md", "git.md", "testing.md")}


def collect(workspace: Workspace, config: Config, request_path: str | None = None) -> dict:
    if request_path:
        validate_request_path(workspace, request_path)
    documents = bundled_guidance()
    bundled = len(documents)
    used = sum(len(text.encode()) for text in documents.values())
    skipped: list[dict] = []
    names = list(dict.fromkeys(config.docs))
    bundle = str(Path(request_path).parent) if request_path else None
    if bundle:
        names.append(bundle)
    for name in names:
        internal = name == bundle
        path = workspace.path(name, internal=internal)
        if not path.exists():
            skipped.append({"path": name, "reason": "missing"})
            continue
        for document in document_paths(workspace, name, internal=internal):
            if document == request_path or document in documents:
                continue
            if len(documents) - bundled >= 500:
                raise ForgeError("More than 500 documentation files; narrow harness.docs.")
            text = workspace.read(document, internal=internal)
            size = len(text.encode())
            if used + size > config.max_context_bytes:
                raise ForgeError(f"Context exceeds max_context_bytes at {document}; narrow harness.docs.")
            documents[document] = text
            used += size
    if used > config.max_context_bytes:
        raise ForgeError("max_context_bytes is smaller than bundled guidance.")
    return {"documents": documents, "skipped": skipped, "inventory": workspace.inventory(),
            "inventory_limit": 500}

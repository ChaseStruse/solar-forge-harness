"""Collect explicit documentation with provenance and size limits."""
from importlib.resources import files

from .domain import Config, ForgeError
from .workspace import Workspace


def bundled_guidance() -> dict[str, str]:
    root = files("solar_forge").joinpath("guidance")
    return {f"builtin/{name}": root.joinpath(name).read_text(encoding="utf-8")
            for name in ("coding.md", "architecture.md", "deployment.md", "git.md", "testing.md")}


def collect(workspace: Workspace, config: Config) -> dict:
    documents = bundled_guidance()
    used = sum(len(text.encode()) for text in documents.values())
    skipped: list[dict] = []
    for name in dict.fromkeys(config.docs):
        path = workspace.path(name)
        if not path.exists():
            skipped.append({"path": name, "reason": "missing"})
            continue
        text = workspace.read(name)
        size = len(text.encode())
        if used + size > config.max_context_bytes:
            raise ForgeError(f"Context exceeds max_context_bytes at {name}; narrow harness.docs.")
        documents[name] = text
        used += size
    if used > config.max_context_bytes:
        raise ForgeError("max_context_bytes is smaller than bundled guidance.")
    return {"documents": documents, "skipped": skipped, "inventory": workspace.inventory(),
            "inventory_limit": 500}

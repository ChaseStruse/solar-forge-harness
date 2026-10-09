"""Provider-independent request and configuration models."""
from dataclasses import dataclass, field
from pathlib import Path
import re
import tomllib


class ForgeError(Exception):
    """An actionable error safe to display in the CLI."""


REQUEST_TEMPLATE = """# Request: Your request title

## Description
Describe the user problem and intended outcome.

## Technical Details
Describe relevant components, constraints, dependencies, and known decisions.

## Acceptance Criteria
- [ ] Describe an observable outcome and how it will be verified.
"""

CONFIG_TEMPLATE = '''# Choose an explicit model available from your provider.
[provider]
kind = "ollama" # openai | anthropic | ollama | compatible
model = "CHANGE_ME"
# base_url = "http://localhost:11434"
# api_key_env = "OPENAI_API_KEY"
timeout = 120

[harness]
max_turns = 30
max_file_bytes = 100000
max_context_bytes = 200000
max_prompt_bytes = 500000
# Add relevant domain documentation here; all paths are project-relative.
docs = ["README.md", "AGENTS.md", ".forge/standards/coding.md", ".forge/standards/architecture.md", ".forge/standards/deployment.md", ".forge/standards/git.md", ".forge/standards/testing.md"]

# Reserved for future document search; no index is built yet.
[rag]
storage = "deferred" # deferred | local
path = ""
'''


@dataclass(frozen=True)
class Request:
    title: str
    description: str
    technical_details: str
    acceptance_criteria: str
    markdown: str

    @classmethod
    def parse(cls, text: str) -> "Request":
        title = re.search(r"^#\s+(?:Request:\s*)?(.+?)\s*$", text, re.M)
        if not title:
            raise ForgeError("request.md needs a '# Request: Title' heading.")
        sections: dict[str, str] = {}
        headings = list(re.finditer(r"^##\s+(.+?)\s*$", text, re.M))
        for i, heading in enumerate(headings):
            name = heading[1].strip().lower()
            if name in sections:
                raise ForgeError(f"Duplicate request section: {heading[1]}")
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            sections[name] = text[heading.end():end].strip()
        required = ["description", "technical details", "acceptance criteria"]
        for name in required:
            if not sections.get(name):
                raise ForgeError(f"request.md needs a nonempty '## {name.title()}' section.")
        if title[1].strip() == "Your request title":
            raise ForgeError("Replace the request template with your actual request first.")
        return cls(title[1].strip(), *(sections[name] for name in required), text)

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")[:80] or "request"


@dataclass(frozen=True)
class RagConfig:
    storage: str = "deferred"
    path: str = ""


@dataclass(frozen=True)
class Config:
    kind: str = "ollama"
    model: str = "CHANGE_ME"
    base_url: str = ""
    api_key_env: str = ""
    timeout: int = 120
    max_turns: int = 30
    max_file_bytes: int = 100000
    max_context_bytes: int = 200000
    max_prompt_bytes: int = 500000
    docs: list[str] = field(default_factory=lambda: ["README.md", "AGENTS.md"])
    rag: RagConfig = field(default_factory=RagConfig)

    @classmethod
    def load(cls, path: Path) -> "Config":
        try:
            data = tomllib.loads(path.read_text())
            provider, harness = data.get("provider", {}), data.get("harness", {})
            config = cls(**provider, **harness, rag=RagConfig(**data.get("rag", {})))
        except (OSError, TypeError, AttributeError, tomllib.TOMLDecodeError) as exc:
            raise ForgeError(f"Invalid .forge/config.toml: {exc}") from exc
        for name in ("timeout", "max_turns", "max_file_bytes", "max_context_bytes", "max_prompt_bytes"):
            if type(getattr(config, name)) is not int or getattr(config, name) <= 0:
                raise ForgeError(f"{name} must be a positive integer.")
        for name in ("kind", "model", "base_url", "api_key_env"):
            if not isinstance(getattr(config, name), str):
                raise ForgeError(f"{name} must be a string.")
        if config.kind not in {"openai", "anthropic", "ollama", "compatible"}:
            raise ForgeError("Provider must be openai, anthropic, ollama, or compatible.")
        if not isinstance(config.docs, list) or not all(isinstance(p, str) for p in config.docs):
            raise ForgeError("harness.docs must be a list of project-relative paths.")
        if not isinstance(config.rag.storage, str) or config.rag.storage not in {"deferred", "local"}:
            raise ForgeError("rag.storage must be deferred or local.")
        if not isinstance(config.rag.path, str):
            raise ForgeError("rag.path must be a string.")
        if config.rag.storage == "local" and (not config.rag.path or Path(config.rag.path).is_absolute()
                                             or ".." in Path(config.rag.path).parts
                                             or Path(config.rag.path) == Path(".")):
            raise ForgeError("rag.path must be a folder inside the project for local storage.")
        return config

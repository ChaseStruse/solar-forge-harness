"""Minimal HTTP adapters: orchestration depends only on the Provider protocol."""
import ipaddress
import json
import os
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .domain import Config, ForgeError


class Provider(Protocol):
    def complete(self, system: str, messages: list[dict[str, str]]) -> str: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def local_host(host: str) -> bool:
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def post_json(url: str, headers: dict, payload: dict, timeout: int) -> dict:
    request = Request(url, json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ForgeError("Provider response exceeds 2 MB.")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ForgeError("Provider returned a non-object response.")
            return data
    except HTTPError as exc:
        # Response bodies may contain prompt data or credentials; do not log them.
        raise ForgeError(f"Provider HTTP {exc.code}; check credentials, model, and endpoint.") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise ForgeError("Provider connection failed or returned invalid JSON; check endpoint and timeout.") from exc


def validate_base_url(base: str) -> None:
    try:
        url = urlparse(base)
        port = url.port
    except ValueError as exc:
        raise ForgeError("Use a valid service address, including a valid host and port.") from exc
    if (url.scheme not in {"https", "http"} or not url.hostname or url.username
            or url.password or url.query or url.fragment or port == 0):
        raise ForgeError("Provider base_url must be an HTTP(S) URL without embedded credentials or query.")
    if url.scheme == "http" and not local_host(url.hostname):
        raise ForgeError("Remote provider endpoints require HTTPS; HTTP is allowed only on loopback.")


class HTTPProvider:
    def __init__(self, config: Config):
        self.config = config
        if not config.model.strip() or config.model == "CHANGE_ME":
            raise ForgeError("Set provider.model in .forge/config.toml or pass --model.")
        defaults = {"openai": "https://api.openai.com/v1", "anthropic": "https://api.anthropic.com/v1",
                    "ollama": "http://localhost:11434", "compatible": "http://localhost:8080/v1"}
        self.base = (config.base_url or defaults[config.kind]).rstrip("/")
        validate_base_url(self.base)
        url = urlparse(self.base)
        env = config.api_key_env or {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
                                    "compatible": "LOCAL_MODEL_API_KEY", "ollama": ""}[config.kind]
        self.key = os.environ.get(env, "") if env else ""
        if not self.key and (config.kind in {"openai", "anthropic"} or
                             (config.kind == "compatible" and not local_host(url.hostname))):
            raise ForgeError(f"Set the {env} environment variable for this provider.")

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        cfg = self.config
        headers = {}
        if cfg.kind == "openai":
            endpoint = "/responses"
            payload = {"model": cfg.model, "instructions": system, "input": messages, "store": False}
            headers = {"Authorization": f"Bearer {self.key}"}
        elif cfg.kind == "anthropic":
            endpoint = "/messages"
            payload = {"model": cfg.model, "system": system, "messages": messages, "max_tokens": 8192}
            headers = {"x-api-key": self.key, "anthropic-version": "2023-06-01"}
        else:
            endpoint = "/api/chat" if cfg.kind == "ollama" else "/chat/completions"
            payload = {"model": cfg.model, "messages": [{"role": "system", "content": system}, *messages],
                       "stream": False}
            if self.key:
                headers = {"Authorization": f"Bearer {self.key}"}
        data = post_json(self.base + endpoint, headers, payload, cfg.timeout)
        try:
            if cfg.kind == "openai":
                if data.get("status") not in (None, "completed"):
                    raise ForgeError("OpenAI response did not complete; no action was executed.")
                result = "\n".join(part["text"] for item in data.get("output", [])
                                   if item.get("type") == "message" for part in item.get("content", [])
                                   if part.get("type") == "output_text")
            elif cfg.kind == "anthropic":
                if data.get("stop_reason") not in (None, "end_turn", "stop_sequence"):
                    raise ForgeError("Claude response was truncated or needs unsupported tools.")
                result = "\n".join(part["text"] for part in data["content"] if part.get("type") == "text")
            elif cfg.kind == "ollama":
                if data.get("done") is False or data.get("done_reason") == "length":
                    raise ForgeError("Ollama response did not complete; no action was executed.")
                result = data["message"]["content"]
            else:
                if data["choices"][0].get("finish_reason") not in (None, "stop"):
                    raise ForgeError("Compatible provider response was truncated or needs unsupported tools.")
                result = data["choices"][0]["message"]["content"]
            if not isinstance(result, str) or not result.strip():
                raise ForgeError("Provider returned no usable text.")
            return result
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ForgeError("Provider returned an unexpected response shape.") from exc

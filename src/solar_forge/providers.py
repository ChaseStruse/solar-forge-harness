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


class ProviderText(str):
    """A backward-compatible text response with per-response reported usage."""
    def __new__(cls, text, usage=None):
        value = super().__new__(cls, text)
        value.usage = usage
        return value


def normalize_usage(kind, data):
    raw = data if kind == 'ollama' else data.get('usage')
    if not isinstance(raw, dict):
        return None
    keys = ('prompt_eval_count', 'eval_count') if kind == 'ollama' else (
        ('prompt_tokens', 'completion_tokens') if kind == 'compatible' else ('input_tokens', 'output_tokens'))
    values = [raw.get(key) for key in keys]
    values = [n if type(n) is int and n >= 0 else None for n in values]
    if kind == 'anthropic' and values[0] is not None:
        cache = [raw.get(key, 0) for key in ('cache_creation_input_tokens', 'cache_read_input_tokens')]
        values[0] = (values[0] + sum(cache) if all(type(n) is int and n >= 0 for n in cache) else None)
    if all(value is None for value in values):
        return None
    return dict(zip(('input_tokens', 'output_tokens'), values))


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


DEFAULT_BASES = {'openai': 'https://api.openai.com/v1', 'anthropic': 'https://api.anthropic.com/v1',
                 'ollama': 'http://localhost:11434', 'compatible': 'http://localhost:8080/v1'}
ENDPOINTS = {'openai': '/responses', 'anthropic': '/messages',
             'ollama': '/api/chat', 'compatible': '/chat/completions'}


def configured_identity(config: Config) -> dict:
    base = (config.base_url or DEFAULT_BASES[config.kind]).rstrip('/')
    validate_base_url(base)
    return {'provider': config.kind, 'model': config.model, 'endpoint': base + ENDPOINTS[config.kind]}


def assert_identity(state: dict, identity: dict) -> None:
    # Older audits have no endpoint; their provider/model are still enforced.
    if any(state.get(key) is not None and state[key] != identity.get(key)
           for key in ('provider', 'model', 'endpoint')):
        raise ForgeError('This run uses a different model, provider, or endpoint. '
                         'Restore its original configuration or prepare a new run.')


class HTTPProvider:
    def __init__(self, config: Config):
        self.config = config
        if not config.model.strip() or config.model == "CHANGE_ME":
            raise ForgeError("Set provider.model in .forge/config.toml or pass --model.")
        self.base = (config.base_url or DEFAULT_BASES[config.kind]).rstrip("/")
        validate_base_url(self.base)
        url = urlparse(self.base)
        env = config.api_key_env or {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
                                    "compatible": "LOCAL_MODEL_API_KEY", "ollama": ""}[config.kind]
        self.key = os.environ.get(env, "") if env else ""
        if not self.key and (config.kind in {"openai", "anthropic"} or
                             (config.kind == "compatible" and not local_host(url.hostname))):
            raise ForgeError(f"Set the {env} environment variable for this provider.")

    @property
    def audit_identity(self) -> dict:
        return {'provider': self.config.kind, 'model': self.config.model,
                'endpoint': self.base + ENDPOINTS[self.config.kind]}

    def stream(self, system: str, messages: list[dict[str, str]]):
        """Native Ollama NDJSON; other adapters retain their complete reply path."""
        if self.config.kind != 'ollama':
            yield self.complete(system, messages)
            return
        payload = {'model': self.config.model, 'stream': True,
                   'messages': [{'role': 'system', 'content': system}, *messages]}
        headers = {'Content-Type': 'application/json'}
        if self.key:
            headers['Authorization'] = f'Bearer {self.key}'
        request = Request(self.audit_identity['endpoint'], json.dumps(payload).encode(), headers, method='POST')
        used = 0
        usage = None
        try:
            with build_opener(NoRedirect()).open(request, timeout=self.config.timeout) as response:
                while True:
                    raw = response.readline(2_000_001)
                    if not raw:
                        raise ForgeError('Provider stream ended before completion.')
                    used += len(raw)
                    if used > 2_000_000:
                        raise ForgeError('Provider response exceeds 2 MB.')
                    data = json.loads(raw)
                    if not isinstance(data, dict) or data.get('error'):
                        raise ForgeError('Provider stream returned an error.')
                    usage = normalize_usage('ollama', data) or usage
                    if data.get('done_reason') == 'length':
                        raise ForgeError('Provider response was truncated.')
                    text = data.get('message', {}).get('content', '')
                    if not isinstance(text, str):
                        raise ForgeError('Provider stream returned invalid text.')
                    if text or (data.get('done') is True and usage is not None):
                        yield ProviderText(text, usage if data.get('done') is True else None)
                    if data.get('done') is True:
                        return
        except ForgeError as exc:
            exc.usage = usage
            raise
        except HTTPError as exc:
            raise ForgeError(f'Provider HTTP {exc.code}; check credentials, model, and endpoint.') from exc
        except (URLError, OSError, ValueError, AttributeError, TypeError) as exc:
            raise ForgeError('Provider stream failed; check endpoint and timeout.') from exc

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        cfg = self.config
        headers = {}
        if cfg.kind == "openai":
            payload = {"model": cfg.model, "instructions": system, "input": messages, "store": False}
            headers = {"Authorization": f"Bearer {self.key}"}
        elif cfg.kind == "anthropic":
            payload = {"model": cfg.model, "system": system, "messages": messages, "max_tokens": 8192}
            headers = {"x-api-key": self.key, "anthropic-version": "2023-06-01"}
        else:
            payload = {"model": cfg.model, "messages": [{"role": "system", "content": system}, *messages],
                       "stream": False}
            if self.key:
                headers = {"Authorization": f"Bearer {self.key}"}
        data = post_json(self.audit_identity["endpoint"], headers, payload, cfg.timeout)
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
            return ProviderText(result, normalize_usage(cfg.kind, data))
        except ForgeError as exc:
            exc.usage = normalize_usage(cfg.kind, data)
            raise
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            error = ForgeError("Provider returned an unexpected response shape.")
            error.usage = normalize_usage(cfg.kind, data)
            raise error from exc

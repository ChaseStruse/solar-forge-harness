"""Narrow, validated settings updates that preserve unrelated TOML and comments."""
from dataclasses import replace
import json
import re
from tempfile import TemporaryDirectory
from pathlib import Path

from .domain import Config, ForgeError
from .providers import HTTPProvider
from .workspace import atomic_write

FIELDS = {'model': 'provider', 'timeout': 'provider', 'max_turns': 'harness',
          'max_prompt_bytes': 'harness', 'max_context_bytes': 'harness', 'max_file_bytes': 'harness'}


def update(service, field, value):
    if field not in FIELDS:
        raise ForgeError('Choose model, timeout, max_turns, max_prompt_bytes, max_context_bytes, or max_file_bytes.')
    if field == 'model':
        if not value.strip() or value == 'CHANGE_ME':
            raise ForgeError('Enter an actual model name.')
    else:
        try:
            value = int(value)
        except ValueError as exc:
            raise ForgeError('Enter a positive whole number.') from exc
        if value <= 0:
            raise ForgeError('Enter a positive whole number.')
    path = service.workspace.path('.forge/config.toml', write=True, internal=True)
    if not path.is_file():
        raise ForgeError('Run forge init before saving settings.')
    text = path.read_text()
    section = FIELDS[field]
    match = re.search(r'^\[' + section + r'\][^\n]*\n(.*?)(?=^\[|\Z)', text, re.M | re.S)
    encoded = json.dumps(value, ensure_ascii=False)
    if match:
        body = match[1]
        pattern = r'^' + field + r'\s*=.*$'
        body = (re.sub(pattern, lambda _: field + ' = ' + encoded, body, count=1, flags=re.M)
                if re.search(pattern, body, re.M) else field + ' = ' + encoded + '\n' + body)
        candidate = text[:match.start(1)] + body + text[match.end(1):]
    else:
        candidate = text + '\n[' + section + ']\n' + field + ' = ' + encoded + '\n'
    with TemporaryDirectory() as temporary:
        validation = Path(temporary) / 'config.toml'
        validation.write_text(candidate)
        Config.load(validation)
    effective = replace(service.config, **{field: value})
    provider = HTTPProvider(effective) if isinstance(service.provider, HTTPProvider) else service.provider
    atomic_write(path, candidate)
    changed_model = field == 'model' and value != service.config.model
    service.config, service.provider = effective, provider
    service.workspace.max_file_bytes = effective.max_file_bytes
    return changed_model

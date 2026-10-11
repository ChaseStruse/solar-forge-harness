"""Lossless prompt packing: audit snapshots remain complete and unchanged."""
import json


def prompt_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def compact_context(context: dict) -> dict:
    """Keep all paths and unique text; prefer project paths for identical guidance."""
    documents = context.get('documents', {})
    canonical = {}
    for name in sorted(documents, key=lambda name: (name.startswith('builtin/'), name)):
        canonical.setdefault(documents[name], name)
    packed = dict(context)
    packed['documents'] = {}
    for name, text in documents.items():
        reference = f'Identical content: see {canonical[text]}.'
        packed['documents'][name] = (reference if canonical[text] != name and
                                     len(reference.encode()) < len(text.encode()) else text)
    return packed

"""Bounded local passage retrieval with explicit provenance and no model service."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import uuid

from .context import DOCUMENT_SUFFIXES, document_paths
from .domain import ForgeError
from .workspace import EXCLUDED, atomic_write, sensitive

VERSION = 1
MAX_FILES = 500
MAX_SOURCE_BYTES = 5_000_000
MAX_INDEX_BYTES = 20_000_000
CHUNK_BYTES = 2000
MAX_QUERY_BYTES = 2000
STOP_WORDS = set('a an and are as at be by for from how i in is it of on or that the this to was what when where which with you'.split())


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def policy(config):
    return config.rag.snapshot() | {'sources': config.rag.sources or config.docs,
                                    'max_file_bytes': config.max_file_bytes}


def storage_path(workspace, config):
    config.rag.snapshot()
    if config.rag.storage != 'local':
        raise ForgeError('Document search is disabled. Set rag.storage = "local" and rag.path = ".forge/rag" first.')
    relative = Path(config.rag.path)
    allowed_internal = relative.parts[:2] == ('.forge', 'rag')
    if not allowed_internal and any(part in EXCLUDED for part in relative.parts):
        raise ForgeError('RAG storage must be .forge/rag or an ordinary project folder.')
    target = workspace.path(relative.as_posix(), write=True, internal=allowed_internal)
    if target.exists() and not target.is_dir():
        raise ForgeError('rag.path must name a folder.')
    workspace.path((relative / 'index.json').as_posix(), internal=allowed_internal)
    return target


def source_documents(workspace, config):
    cache = storage_path(workspace, config)
    documents, skipped = {}, []
    used = 0
    for name in dict.fromkeys(policy(config)['sources']):
        source = workspace.path(name)
        parts = Path(name).parts
        standards = parts[:2] == ('.forge', 'standards')
        if (not standards and any(part in EXCLUDED for part in parts)) or any(sensitive(p) for p in parts):
            raise ForgeError(f'Excluded retrieval source: {name}')
        if source == cache or source.is_relative_to(cache):
            raise ForgeError('RAG storage cannot be a retrieval source.')
        if not source.exists():
            skipped.append({'path': name, 'reason': 'missing'})
            continue
        for filename in document_paths(workspace, name):
            path = workspace.path(filename)
            if path == cache or path.is_relative_to(cache) or path.suffix.lower() not in DOCUMENT_SUFFIXES:
                continue
            if filename in documents:
                continue
            if len(documents) >= MAX_FILES:
                raise ForgeError('Retrieval exceeds 500 documents; narrow rag.sources.')
            text = workspace.read(filename)
            if len(text.encode()) > config.max_file_bytes:
                raise ForgeError(f'Retrieval document exceeds max_file_bytes: {filename}')
            used += len(text.encode())
            if used > MAX_SOURCE_BYTES:
                raise ForgeError('Retrieval exceeds 5 MB of source text; narrow rag.sources.')
            documents[filename] = text
    return documents, skipped


def manifest(documents, skipped):
    return {'files': {name: hashlib.sha256(text.encode()).hexdigest() for name, text in sorted(documents.items())},
            'skipped': skipped}


def chunks_for(name, text, sha):
    lines = text.splitlines(keepends=True)
    buffer, size, start = [], 0, 1
    for number, line in enumerate(lines, 1):
        if buffer and size + len(line.encode()) > CHUNK_BYTES:
            yield {'path': name, 'start_line': start, 'end_line': number - 1,
                   'text': ''.join(buffer), 'source_sha256': sha}
            buffer, size = [], 0
        if not buffer:
            start = number
        # Long lines are split without losing exact line provenance or Unicode.
        while len(line.encode()) > CHUNK_BYTES:
            fragment = line.encode()[:CHUNK_BYTES].decode('utf-8', errors='ignore')
            yield {'path': name, 'start_line': number, 'end_line': number,
                   'text': fragment, 'source_sha256': sha}
            line = line[len(fragment):]
        if line:
            buffer.append(line)
            size += len(line.encode())
    if buffer:
        yield {'path': name, 'start_line': start, 'end_line': len(lines),
               'text': ''.join(buffer), 'source_sha256': sha}


def load_index(workspace, config):
    path = storage_path(workspace, config) / 'index.json'
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > MAX_INDEX_BYTES:
        raise ForgeError('Invalid or oversized retrieval index. Remove it and run forge index.')
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_INDEX_BYTES:
            raise ValueError('oversized')
        data = json.loads(raw)
        if (not isinstance(data, dict) or data.get('version') != VERSION
                or data.get('kind') != 'solar-forge-retrieval'
                or data.get('checksum') != digest({k: v for k, v in data.items() if k != 'checksum'})
                or not isinstance(data.get('policy'), dict)
                or not isinstance(data.get('chunks'), list)
                or not isinstance(data.get('manifest', {}).get('files'), dict)):
            raise ValueError('schema/checksum')
        for chunk in data['chunks']:
            if (not isinstance(chunk, dict) or not isinstance(chunk.get('path'), str)
                    or not isinstance(chunk.get('text'), str)
                    or type(chunk.get('start_line')) is not int or type(chunk.get('end_line')) is not int
                    or not 1 <= chunk['start_line'] <= chunk['end_line']
                    or chunk.get('source_sha256') != data['manifest']['files'].get(chunk['path'])):
                raise ValueError('chunk schema')
        return data
    except (ValueError, TypeError, AttributeError, RecursionError) as exc:
        raise ForgeError('Cannot read retrieval index. Remove index.json and run forge index to rebuild it.') from exc


def build_index(workspace, config):
    directory = storage_path(workspace, config)
    # Never silently overwrite an unrelated/corrupt file at the chosen destination.
    load_index(workspace, config)
    documents, skipped = source_documents(workspace, config)
    sources = manifest(documents, skipped)
    chunks = [chunk for name, text in sorted(documents.items())
              for chunk in chunks_for(name, text, sources['files'][name])]
    data = {'version': VERSION, 'kind': 'solar-forge-retrieval', 'policy': policy(config),
            'manifest': sources, 'chunks': chunks}
    data['checksum'] = digest(data)
    content = encoded(data)
    if len(content) > MAX_INDEX_BYTES:
        raise ForgeError('Retrieval index exceeds 20 MB; narrow rag.sources.')
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write(directory / 'index.json', content.decode())
    return {'status': 'ready', 'documents': len(documents), 'chunks': len(chunks),
            'skipped': skipped, 'fingerprint': digest(sources)}


def index_status(workspace, config):
    if config.rag.storage != 'local':
        return {'status': 'disabled', 'hint': 'Enable local RAG in .forge/config.toml.'}
    data = load_index(workspace, config)
    if data is None:
        return {'status': 'missing', 'hint': 'Run forge index or /index to build the document library.'}
    documents, skipped = source_documents(workspace, config)
    sources = manifest(documents, skipped)
    fresh = data['policy'] == policy(config) and data['manifest'] == sources
    return {'status': 'ready' if fresh else 'stale', 'documents': len(data['manifest']['files']),
            'chunks': len(data['chunks']), 'skipped': skipped, 'fingerprint': digest(sources),
            'hint': '' if fresh else 'Sources or settings changed. Run forge index or /index again.'}


def terms(text):
    return [word for word in re.findall(r'[^\W_]+', text.casefold()) if word not in STOP_WORDS]


def search(workspace, config, query):
    if not isinstance(query, str) or not query.strip() or len(query.encode()) > MAX_QUERY_BYTES:
        raise ForgeError('Search needs a nonempty query of at most 2000 UTF-8 bytes.')
    status = index_status(workspace, config)
    result = status | {'query': query, 'results': []}
    if status['status'] != 'ready':
        return result
    data = load_index(workspace, config)
    # A concurrent rebuild must not pair the old fingerprint with different text.
    if data is None or digest(data['manifest']) != status['fingerprint'] or data['policy'] != policy(config):
        raise ForgeError('Retrieval index changed during search; retry.')
    chunks = data['chunks']
    query_terms = set(terms(query))
    counts = [Counter(terms(chunk['text'])) for chunk in chunks]
    lengths = [sum(count.values()) for count in counts]
    average = sum(lengths) / max(len(chunks), 1) or 1
    frequency = {word: sum(word in count for count in counts) for word in query_terms}
    ranked = []
    for chunk, count, length in zip(chunks, counts, lengths):
        score = 0.0
        for word in query_terms:
            n = count[word]
            if n:
                inverse = math.log(1 + (len(chunks) - frequency[word] + .5) / (frequency[word] + .5))
                score += inverse * n * 2.2 / (n + 1.2 * (.25 + .75 * length / average))
        if score:
            ranked.append((score, chunk))
    ranked.sort(key=lambda item: (-item[0], item[1]['path'], item[1]['start_line']))
    used = 0
    for score, chunk in ranked:
        hit = chunk | {'score': round(score, 6),
                       'citation': f"{chunk['path']}:{chunk['start_line']}-{chunk['end_line']}"}
        size = len(encoded(hit))
        if used + size > config.rag.max_result_bytes:
            continue
        result['results'].append(hit)
        used += size
        if len(result['results']) >= config.rag.top_k:
            break
    result['result_bytes'] = used
    return result


def automatic_search(workspace, config, query):
    if config.rag.storage != 'local':
        return {'status': 'disabled', 'results': []}
    query = query.encode()[:MAX_QUERY_BYTES].decode('utf-8', errors='ignore').strip()
    return search(workspace, config, query) if query else index_status(workspace, config) | {'results': []}


def record_search(audit, result):
    name = f'retrieval/{uuid.uuid4().hex}.json'
    audit.write(name, json.dumps(result, indent=2, ensure_ascii=False))
    audit.event('documents_retrieved', query=result.get('query'), status=result['status'],
                evidence=name, citations=[hit['citation'] for hit in result.get('results', [])])


def format_result(result):
    lines = [f"Document search: {result['status']}"]
    if 'documents' in result:
        lines.append(f"{result['documents']} documents; {result['chunks']} passages.")
    if result.get('hint'):
        lines.append(result['hint'])
    for item in result.get('skipped', []):
        lines.append(f"Skipped {item['path']}: {item['reason']}")
    for hit in result.get('results', []):
        lines.append(f"\n{hit['citation']}\n{hit['text']}")
    if 'query' in result and result['status'] == 'ready' and not result['results']:
        lines.append('No matching passages within the result budget. Try more specific terms or raise rag.max_result_bytes.')
    return '\n'.join(lines)


def binding(workspace, config):
    if config.rag.storage != 'local':
        return None
    status = index_status(workspace, config)
    return {'policy': policy(config), 'status': status['status'], 'fingerprint': status.get('fingerprint')}


def context_sources(context):
    return set(context['documents']) | {'request.md'} | {
        hit['path'] for hit in context.get('retrieval', {}).get('results', [])}


def record_standalone(workspace, result):
    from datetime import datetime, timezone
    from .audit import Audit
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:10]
    directory = workspace.path('agentic_audit/document-retrieval/' + run_id, internal=True)
    directory.mkdir(parents=True)
    audit = Audit(directory)
    record_search(audit, result)
    return directory.relative_to(workspace.root).as_posix()

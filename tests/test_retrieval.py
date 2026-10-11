from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from solar_forge.agent import approve, run
from solar_forge.audit import Audit
from solar_forge.chat import ChatService
from solar_forge.cli import main
from solar_forge.context import collect
from solar_forge.domain import Config, ForgeError, RagConfig
from solar_forge.requests import DEFAULT_REQUEST, write_request
from solar_forge.retrieval import (build_index, search, index_status, chunks_for,
                                   MAX_QUERY_BYTES, load_index)
from solar_forge.workflow import prepare, plan, assert_current
from solar_forge.workspace import Workspace
from test_foundation import REQUEST
from test_workflow import ScriptedProvider
from test_chat import TextProvider


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Workspace(Path(self.tmp.name))
        self.cfg = Config(model='test', docs=[], rag=RagConfig('local', '.forge/rag', ['references']))
        self.ws.write('references/billing.md', '# Billing exports\n\nInvoices use UTC timestamps.\nRefunds require a receipt.\n')
        self.ws.write('references/garden.txt', 'Garden roses grow in sandy soil.\n')
        write_request(self.ws, DEFAULT_REQUEST, REQUEST)

    def test_ranked_results_and_exact_provenance(self):
        built = build_index(self.ws, self.cfg)
        self.assertEqual(built['documents'], 2)
        result = search(self.ws, self.cfg, 'invoice billing timestamps UTC')
        self.assertEqual(result['status'], 'ready')
        hit = result['results'][0]
        self.assertEqual(hit['path'], 'references/billing.md')
        lines = self.ws.read(hit['path']).splitlines(keepends=True)
        self.assertEqual(hit['text'], ''.join(lines[hit['start_line']-1:hit['end_line']]))
        self.assertEqual(hit['citation'], 'references/billing.md:1-4')
        self.assertEqual(result, search(self.ws, self.cfg, 'invoice billing timestamps UTC'))
        self.assertEqual(search(self.ws, self.cfg, 'unfindablexyz')['results'], [])

    def test_unicode_long_lines_are_bounded_and_preserved(self):
        text = 'Résumé 中文 ' * 1000 + '\nlast line'
        chunks = list(chunks_for('unicode.md', text, 'hash'))
        self.assertEqual(''.join(c['text'] for c in chunks), text)
        self.assertTrue(all(len(c['text'].encode()) <= 2000 for c in chunks))
        self.assertEqual(chunks[-1]['end_line'], 2)

    def test_missing_disabled_stale_and_refresh(self):
        self.assertEqual(index_status(self.ws, self.cfg)['status'], 'missing')
        self.assertEqual(search(self.ws, Config(), 'billing')['status'], 'disabled')
        build_index(self.ws, self.cfg)
        self.ws.write('references/billing.md', 'New billing policy: refunds are final.')
        stale = search(self.ws, self.cfg, 'billing')
        self.assertEqual(stale['status'], 'stale')
        self.assertEqual(stale['results'], [])
        build_index(self.ws, self.cfg)
        self.assertIn('final', search(self.ws, self.cfg, 'billing')['results'][0]['text'])
        (self.ws.root / 'references/garden.txt').unlink()
        self.assertEqual(index_status(self.ws, self.cfg)['status'], 'stale')
        build_index(self.ws, self.cfg)
        self.ws.write('references/new.md', 'Newly added document')
        self.assertEqual(index_status(self.ws, self.cfg)['status'], 'stale')

    def test_filters_symlinks_secrets_builds_and_unsupported_files(self):
        root = self.ws.root / 'references'
        (root / '.env').write_text('secret')
        (root / 'private.key').write_text('secret')
        (root / 'binary.pdf').write_bytes(b'%PDF')
        (root / 'node_modules').mkdir()
        (root / 'node_modules/hidden.md').write_text('secret')
        (root / 'link.md').symlink_to(root / 'billing.md')
        build_index(self.ws, self.cfg)
        self.assertEqual(set(load_index(self.ws, self.cfg)['manifest']['files']),
                         {'references/billing.md', 'references/garden.txt'})
        for source in ['references/link.md', '../escape', '.env', '.forge/config.toml', 'agentic_audit']:
            with self.subTest(source=source), self.assertRaises(ForgeError):
                build_index(self.ws, replace(self.cfg, rag=replace(self.cfg.rag, sources=[source])))

    def test_storage_cannot_escape_or_overwrite_protected_paths(self):
        for folder in ['../outside', '.git', 'agentic_audit', '.forge/standards', '.env', '.']:
            with self.subTest(folder=folder), self.assertRaises(ForgeError):
                build_index(self.ws, replace(self.cfg, rag=replace(self.cfg.rag, path=folder)))
        cache = self.ws.root / 'cache'
        cache.mkdir()
        (cache / 'index.json').write_text('existing user data')
        with self.assertRaises(ForgeError):
            build_index(self.ws, replace(self.cfg, rag=replace(self.cfg.rag, path='cache')))
        self.assertEqual((cache / 'index.json').read_text(), 'existing user data')
        (cache / 'index.json').unlink()
        (cache / 'index.json').symlink_to(self.ws.root / 'references/billing.md')
        with self.assertRaises(ForgeError):
            build_index(self.ws, replace(self.cfg, rag=replace(self.cfg.rag, path='cache')))

    def test_corruption_and_size_limits(self):
        build_index(self.ws, self.cfg)
        path = self.ws.root / '.forge/rag/index.json'
        data = json.loads(path.read_text())
        data['chunks'][0]['text'] = 'corrupted data'
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ForgeError, 'Cannot read retrieval index'):
            search(self.ws, self.cfg, 'billing')
        path.unlink()
        with self.assertRaisesRegex(ForgeError, 'max_file_bytes'):
            build_index(self.ws, replace(self.cfg, max_file_bytes=10))
        for query in ['', ' ', 'x' * (MAX_QUERY_BYTES + 1)]:
            with self.assertRaises(ForgeError):
                search(self.ws, self.cfg, query)

    def test_result_count_and_byte_budget(self):
        self.ws.write('references/many.md', ('billing refunds ' * 80 + '\n') * 20)
        cfg = replace(self.cfg, rag=replace(self.cfg.rag, top_k=2, max_result_bytes=3000))
        build_index(self.ws, cfg)
        result = search(self.ws, cfg, 'billing refunds')
        self.assertTrue(result['results'])
        self.assertLessEqual(len(result['results']), 2)
        self.assertLessEqual(result['result_bytes'], 3000)
        self.assertEqual(result['result_bytes'], len(json.dumps(result['results'], ensure_ascii=False,
                         sort_keys=True, separators=(',', ':')).encode()))

    def test_separate_library_does_not_fill_always_on_context(self):
        build_index(self.ws, self.cfg)
        context = collect(self.ws, self.cfg)
        self.assertNotIn('references/billing.md', context['documents'])
        self.assertEqual(len(context['documents']), 5)
        fallback = replace(self.cfg, docs=['references'], rag=replace(self.cfg.rag, sources=[]))
        build_index(self.ws, fallback)
        self.assertTrue(search(self.ws, fallback, 'billing')['results'])

    def test_preparation_citations_and_changed_library_invalidate_run(self):
        build_index(self.ws, self.cfg)
        provider = ScriptedProvider({'questions': [{'question': 'Which billing policy?',
            'rationale': 'Resolve billing exports', 'sources': ['references/billing.md']}]})
        audit = prepare(self.ws, self.cfg, DEFAULT_REQUEST, provider)
        self.assertEqual(audit.load()['status'], 'awaiting_answers')
        self.assertIn('references/billing.md', audit.read('context.md'))
        self.assertTrue(list((audit.path / 'retrieval').glob('*.json')))
        self.ws.write('references/garden.txt', 'changed reference')
        with self.assertRaisesRegex(ForgeError, 'Retrieval sources'):
            assert_current(self.ws, self.cfg, audit)
        build_index(self.ws, self.cfg)
        with self.assertRaisesRegex(ForgeError, 'Retrieval sources'):
            assert_current(self.ws, self.cfg, audit)

    def test_agent_search_and_library_write_protection(self):
        build_index(self.ws, self.cfg)
        provider = ScriptedProvider({'questions': []}, {'plan': 'Look up refund policy.'},
            {'tool': 'search_docs', 'query': 'refund receipt'},
            {'tool': 'read_file', 'path': 'references/billing.md'},
            {'tool': 'write_file', 'path': 'references/billing.md', 'content': 'change policy'},
            {'tool': 'write_file', 'path': '.forge/rag/index.json', 'content': 'replace cache'},
            {'tool': 'ask_questions', 'questions': [{'question': 'Require receipt?',
                'rationale': 'Resolve refund policy', 'sources': ['references/billing.md']}]})
        audit = prepare(self.ws, self.cfg, DEFAULT_REQUEST, provider)
        plan(self.ws, self.cfg, audit, provider)
        approve(audit)
        run(self.ws, self.cfg, audit, provider)
        self.assertEqual(audit.load()['status'], 'awaiting_answers')
        self.assertIn('receipt', self.ws.read('references/billing.md'))
        self.assertIn('references/billing.md', audit.load()['retrieved_sources'])
        self.assertEqual(index_status(self.ws, self.cfg)['status'], 'ready')
        self.assertIn('tool_rejected', audit.read('events.jsonl'))

    def test_chat_index_search_and_automatic_context(self):
        provider = TextProvider('Invoices use UTC [references/billing.md:1-4].')
        service = ChatService(self.ws, self.cfg, provider)
        session = service.new()['id']
        for command in ['/index', '/rag', '/search billing timestamps']:
            result = service.command(session, command)
            self.assertIsNone(result['command_error'])
            self.assertIn('Document search: ready', result['messages'][-1]['content'])
        service.send(session, 'Which timezone do billing invoices use?')
        self.assertIn('Invoices use UTC', provider.calls[-1][0])
        self.assertIn('references/billing.md:1-4', provider.calls[-1][0])
        audit = Audit.open(self.ws, session)
        self.assertGreaterEqual(len(list((audit.path / 'retrieval').glob('*.json'))), 4)

    def test_cli_index_and_search_do_not_need_provider(self):
        folder = self.ws.root / '.forge'
        folder.mkdir()
        (folder / 'config.toml').write_text('[rag]\nstorage="local"\npath=".forge/rag"\nsources=["references"]\n')
        for args in [['index'], ['index', '--status'], ['search', 'billing UTC']]:
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                status = main(['--project', str(self.ws.root), *args])
            self.assertEqual(status, 0, err.getvalue())
            self.assertIn('Document search: ready', out.getvalue())
            self.assertIn('Evidence: agentic_audit/', out.getvalue())
        self.assertFalse(Audit.discover(self.ws))

    def test_rebuild_unchanged_library_preserves_run_and_policy_changes_do_not(self):
        build_index(self.ws, self.cfg)
        audit = prepare(self.ws, self.cfg, DEFAULT_REQUEST, ScriptedProvider({'questions': []}))
        build_index(self.ws, self.cfg)
        assert_current(self.ws, self.cfg, audit)
        changed = replace(self.cfg, rag=replace(self.cfg.rag, top_k=1))
        self.assertEqual(index_status(self.ws, changed)['status'], 'stale')
        with self.assertRaisesRegex(ForgeError, 'Retrieval sources'):
            assert_current(self.ws, changed, audit)
        with self.assertRaisesRegex(ForgeError, 'Retrieval sources'):
            assert_current(self.ws, replace(self.cfg, rag=RagConfig()), audit)

    def test_source_and_index_budgets_fail_without_partial_cache(self):
        from unittest.mock import patch
        for constant, value, message in [('MAX_FILES', 1, '500 documents'),
                                         ('MAX_SOURCE_BYTES', 10, '5 MB'),
                                         ('MAX_INDEX_BYTES', 100, '20 MB')]:
            with self.subTest(constant=constant), patch('solar_forge.retrieval.' + constant, value):
                with self.assertRaisesRegex(ForgeError, message):
                    build_index(self.ws, self.cfg)
                self.assertFalse((self.ws.root / '.forge/rag/index.json').exists())

    def test_custom_cache_inside_source_is_not_indexed(self):
        cfg = replace(self.cfg, rag=replace(self.cfg.rag, path='references/cache'))
        self.ws.write('references/cache/copied.md', 'Do not retrieve internal cache files')
        build_index(self.ws, cfg)
        self.assertNotIn('references/cache/copied.md', load_index(self.ws, cfg)['manifest']['files'])
        self.assertEqual(index_status(self.ws, cfg)['status'], 'ready')
        bad = replace(cfg, rag=replace(cfg.rag, sources=['references/cache']))
        with self.assertRaisesRegex(ForgeError, 'cannot be a retrieval source'):
            build_index(self.ws, bad)

    def test_missing_index_is_visible_in_chat_and_preparation(self):
        provider = TextProvider('Please build the library with /index.')
        service = ChatService(self.ws, self.cfg, provider)
        session = service.new()['id']
        service.send(session, 'billing refunds')
        self.assertIn('"status": "missing"', provider.calls[0][0])
        audit = prepare(self.ws, self.cfg, DEFAULT_REQUEST, ScriptedProvider({'questions': []}))
        self.assertEqual(json.loads(audit.read('context.json'))['retrieval']['status'], 'missing')
        build_index(self.ws, self.cfg)
        with self.assertRaisesRegex(ForgeError, 'Retrieval sources'):
            assert_current(self.ws, self.cfg, audit)

    def test_missing_sources_reported_and_invalid_config_rejected(self):
        cfg = replace(self.cfg, rag=replace(self.cfg.rag, sources=['absent']))
        result = build_index(self.ws, cfg)
        self.assertEqual(result['documents'], 0)
        self.assertEqual(result['skipped'], [{'path': 'absent', 'reason': 'missing'}])
        for kwargs in [dict(top_k=True), dict(top_k=21), dict(sources='docs'),
                       dict(max_result_bytes=0), dict(storage=[]), dict(path=12)]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ForgeError):
                replace(self.cfg.rag, **kwargs).snapshot()

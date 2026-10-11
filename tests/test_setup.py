from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from solar_forge.requests import DEFAULT_REQUEST, read_request, write_request
from solar_forge.cli import main
from solar_forge.context import collect
from solar_forge.domain import Config, CONFIG_TEMPLATE, ForgeError
from solar_forge.workspace import Workspace


class SetupTests(unittest.TestCase):
    def invoke(self, root, answers=(), *flags, terminal=True):
        out, err = StringIO(), StringIO()
        with patch('solar_forge.cli.sys.stdin.isatty', return_value=terminal), \
                patch('builtins.input', side_effect=answers) as prompt, \
                redirect_stdout(out), redirect_stderr(err):
            code = main(['--project', str(root), 'init', *flags])
        return code, out.getvalue(), err.getvalue(), prompt

    def test_local_model_new_documents_and_deferred_rag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, out, err, _ = self.invoke(root, ['1', 'my-local-model', '', 'no', '2'])
            self.assertEqual(code, 0, err)
            config = Config.load(root / '.forge/config.toml')
            self.assertEqual(config.kind, 'ollama')
            self.assertEqual(config.model, 'my-local-model')
            self.assertEqual(config.rag.storage, 'deferred')
            self.assertIn('docs', config.docs)
            self.assertTrue((root / 'docs').is_dir())
            self.assertTrue((root / DEFAULT_REQUEST).is_file())
            self.assertTrue((root / '.forge/standards/coding.md').is_file())
            self.assertIn('forge chat', out)
            self.assertIn('request.md', out)
            self.assertIn('not available yet', out)
            self.assertIn(str(root), out)

    def test_all_providers_existing_folder_and_local_rag(self):
        for number, kind, key in [('1', 'ollama', ''), ('2', 'openai', 'OPENAI_API_KEY'),
                                  ('3', 'anthropic', 'ANTHROPIC_API_KEY'),
                                  ('4', 'compatible', 'LOCAL_MODEL_API_KEY')]:
            with self.subTest(provider=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                documents = root / 'project notes'
                documents.mkdir()
                (documents / 'overview.md').write_text('Project goals')
                answers = [number, 'my-model', ''] + ([''] if key else [])
                answers += ['yes', str(documents), '1', '']
                code, out, err, prompt = self.invoke(root, answers)
                self.assertEqual(code, 0, err)
                config = Config.load(root / '.forge/config.toml')
                self.assertEqual((config.kind, config.api_key_env), (kind, key))
                self.assertEqual(config.docs[-1], 'project notes')
                self.assertEqual((config.rag.storage, config.rag.path), ('local', '.forge/rag'))
                self.assertTrue((root / '.forge/rag').is_dir())
                self.assertEqual(collect(Workspace(root), config)['documents']['project notes/overview.md'], 'Project goals')
                self.assertIn('run forge index', out)
                if key:
                    self.assertIn('API key variable name', str(prompt.call_args_list))

    def test_bad_answers_retry_without_leaving_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'notes').mkdir()
            (root / 'link').symlink_to(root / 'notes', target_is_directory=True)
            answers = ['9', '1', '', 'CHANGE_ME', 'real-model', 'http://remote.example/v1',
                       'http://[invalid', 'http://localhost:bad', '',
                       'maybe', 'yes', '../outside', '/outside', 'missing', '.aws', 'link', 'notes',
                       '1', '.forge/standards', '../rag', '.env', 'search cache']
            code, out, err, _ = self.invoke(root, answers)
            self.assertEqual(code, 0, err)
            self.assertEqual(Config.load(root / '.forge/config.toml').rag.path, 'search cache')
            self.assertTrue((root / 'search cache').is_dir())
            self.assertIn('Choose 1, 2, 3, 4', out)
            self.assertIn('HTTPS', out)
            self.assertIn('Symlink', out)
            self.assertIn('does not exist', out)

    def test_repeat_setup_preserves_every_file_without_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(self.invoke(root, ['1', 'local-model', '', 'no', '2'])[0], 0)
            for relative in (DEFAULT_REQUEST, '.forge/standards/coding.md'):
                (root / relative).write_bytes(b'Custom content\r\n')
            paths = [p for p in root.rglob('*') if p.is_file()]
            before = {p: p.read_bytes() for p in paths}
            code, out, err, prompt = self.invoke(root)
            self.assertEqual(code, 0, err)
            prompt.assert_not_called()
            self.assertEqual(before, {p: p.read_bytes() for p in paths})
            self.assertIn('Keeping your model', out)

    def test_cancel_or_closed_input_writes_no_setup_files(self):
        for stop in (KeyboardInterrupt, EOFError):
            with self.subTest(stop=stop), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                code, out, err, _ = self.invoke(root, ['1', 'model', '', 'no', stop])
                self.assertEqual(code, 130)
                self.assertEqual(list(root.iterdir()), [])
                self.assertIn('Setup stopped', err)
                self.assertNotIn('agentic_audit', err)

    def test_scripts_skip_prompts_and_explain_remaining_setup(self):
        for terminal, flags in ((False, ()), (True, ('--no-interactive',))):
            with self.subTest(terminal=terminal), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                code, out, err, prompt = self.invoke(root, (), *flags, terminal=terminal)
                self.assertEqual(code, 0, err)
                prompt.assert_not_called()
                self.assertEqual(Config.load(root / '.forge/config.toml').model, 'CHANGE_ME')
                self.assertIn('Before chatting: set provider.model', out)

    def test_folder_conflict_in_script_does_not_create_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'docs').write_text('A file, not a folder')
            code, _, err, prompt = self.invoke(root, (), '--no-interactive')
            self.assertEqual(code, 1)
            prompt.assert_not_called()
            self.assertIn('path is a file', err)
            self.assertFalse((root / '.forge').exists())

    def test_old_config_works_and_new_rag_settings_are_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.toml'
            old = CONFIG_TEMPLATE.split('# Local passage search')[0]
            path.write_text(old)
            self.assertEqual(Config.load(path).rag.storage, 'deferred')
            for settings in ('storage = "unknown"', 'storage = "local"\npath = "../outside"',
                             'storage = "local"\npath = ""', 'storage = []', 'path = 5'):
                path.write_text(old + '\n[rag]\n' + settings)
                with self.assertRaises(ForgeError):
                    Config.load(path)

    def test_directory_context_filters_files_and_enforces_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / 'notes'
            (docs / 'nested').mkdir(parents=True)
            (docs / 'nested/rules.rst').write_text('Rules')
            (docs / 'overview.md').write_text('Overview')
            (docs / 'extra.txt').write_text('Extra')
            (docs / 'binary.png').write_bytes(b'\x00')
            (docs / '.env.txt').write_text('SECRET')
            (docs / 'linked.md').symlink_to(docs / 'overview.md')
            (docs / '.git').mkdir()
            (docs / '.git/hidden.md').write_text('Hidden')
            ws = Workspace(root)
            config = Config(docs=['notes', 'notes/overview.md'])
            context = collect(ws, config)
            selected = {k for k in context['documents'] if k.startswith('notes/')}
            self.assertEqual(selected, {'notes/nested/rules.rst', 'notes/overview.md', 'notes/extra.txt'})
            with self.assertRaises(ForgeError):
                collect(ws, Config(docs=['notes'], max_context_bytes=1))
            with self.assertRaises(ForgeError):
                collect(Workspace(root, max_file_bytes=3), config)

    def test_directory_document_count_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'docs').mkdir()
            for i in range(501):
                (root / 'docs' / f'{i:03}.md').write_text('Small document')
            with self.assertRaisesRegex(ForgeError, '500 documentation files'):
                collect(Workspace(root), Config(docs=['docs']))

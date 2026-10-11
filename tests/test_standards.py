from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from solar_forge.cli import main
from solar_forge.context import collect
from solar_forge.domain import Config, ForgeError
from solar_forge.standards import coding_standards, detect_languages
from solar_forge.workspace import Workspace


class LanguageStandardsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ws = Workspace(self.root)

    def init(self, *flags, answers=(), terminal=False):
        out, err = StringIO(), StringIO()
        with patch('solar_forge.cli.sys.stdin.isatty', return_value=terminal), \
                patch('builtins.input', side_effect=answers) as prompt, \
                redirect_stdout(out), redirect_stderr(err):
            code = main(['--project', str(self.root), 'init', *flags])
        return code, out.getvalue(), err.getvalue(), prompt

    def test_each_language_template_reaches_model_context(self):
        for name, heading in [('python', 'Python'), ('typescript', 'TypeScript'), ('javascript', 'JavaScript')]:
            with self.subTest(language=name):
                # Independent project roots ensure each init starts fresh.
                with tempfile.TemporaryDirectory() as tmp:
                    old_root = self.root
                    self.root = Path(tmp)
                    code, _, err, prompt = self.init('--language', name)
                    self.assertEqual(code, 0, err)
                    prompt.assert_not_called()
                    cfg = Config.load(self.root / '.forge/config.toml')
                    self.assertEqual(cfg.languages, [name])
                    context = collect(Workspace(self.root), cfg)
                    text = context['documents']['.forge/standards/coding.md']
                    self.assertIn('## ' + heading, text)
                    for other in {'Python', 'TypeScript', 'JavaScript'} - {heading}:
                        self.assertNotIn('## ' + other, text)
                    self.assertIn('starter defaults', text)
                    self.root = old_root

    def test_mixed_languages_flags_and_restoration_preserve_custom_files(self):
        code, _, err, _ = self.init('--language', 'typescript', '--language', 'python', '--language', 'typescript')
        self.assertEqual(code, 0, err)
        cfg_path = self.root / '.forge/config.toml'
        cfg_bytes = cfg_path.read_bytes()
        coding = self.root / '.forge/standards/coding.md'
        initial = coding.read_bytes()
        self.assertIn(b'## Python', initial)
        self.assertIn(b'## TypeScript', initial)
        coding.write_bytes(b'Custom project guidance\r\n')
        code, _, err, prompt = self.init(terminal=True)
        self.assertEqual(code, 0, err)
        prompt.assert_not_called()
        self.assertEqual(coding.read_bytes(), b'Custom project guidance\r\n')
        self.assertEqual(cfg_path.read_bytes(), cfg_bytes)
        coding.unlink()
        self.assertEqual(self.init()[0], 0)
        self.assertEqual(coding.read_bytes(), initial)

    def test_automatic_detection_markers_and_mixed_source_files(self):
        for name in ['pyproject.toml', 'web/tsconfig.app.json', 'web/src/page.jsx']:
            self.ws.write(name, '')
        self.assertEqual(detect_languages(self.ws), ['python', 'typescript', 'javascript'])
        code, out, err, _ = self.init()
        self.assertEqual(code, 0, err)
        self.assertEqual(Config.load(self.root / '.forge/config.toml').languages,
                         ['python', 'typescript', 'javascript'])
        self.assertIn('Python, TypeScript, JavaScript', out)

    def test_detection_filters_generated_dependencies_and_symlinks(self):
        for name in ['node_modules/pkg/a.ts', '.venv/lib/a.py', 'dist/a.js',
                     'agentic_audit/old/snapshot.py', '.env.hidden.py', 'build/a.ts']:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('ignored')
        (self.root / 'linked.py').symlink_to(self.root / '.venv/lib/a.py')
        self.assertEqual(detect_languages(self.ws), [])
        self.assertEqual(self.init()[0], 0)
        text = (self.root / '.forge/standards/coding.md').read_text()
        self.assertNotIn('## Python', text)
        self.assertEqual(Config.load(self.root / '.forge/config.toml').languages, [])

    def test_package_json_fallback_does_not_force_javascript_on_typescript(self):
        self.ws.write('package.json', '{}')
        self.assertEqual(detect_languages(self.ws), ['javascript'])
        self.ws.write('tsconfig.json', '{}')
        self.assertEqual(detect_languages(self.ws), ['typescript'])
        self.ws.write('src/main.cjs', '')
        self.assertEqual(detect_languages(self.ws), ['typescript', 'javascript'])

    def test_generic_and_explicit_language_override_detection(self):
        self.ws.write('project.py', '')
        code, _, err, _ = self.init('--language', 'generic')
        self.assertEqual(code, 0, err)
        cfg = Config.load(self.root / '.forge/config.toml')
        self.assertEqual(cfg.languages, [])
        self.assertNotIn('## Python', (self.root / '.forge/standards/coding.md').read_text())

    def test_interactive_selection_default_override_and_retry(self):
        self.ws.write('app.py', '')
        code, out, err, prompt = self.init(terminal=True,
            answers=['1', 'model', '', 'no', '2', 'rust', 'generic, python', 'typescript, javascript'])
        self.assertEqual(code, 0, err)
        self.assertIn('Detected from up to 500 project paths: Python', out)
        self.assertEqual(Config.load(self.root / '.forge/config.toml').languages, ['typescript', 'javascript'])
        self.assertIn('Coding standards [python]', str(prompt.call_args_list))

    def test_interactive_enter_accepts_detection_and_flags_skip_language_prompt(self):
        self.ws.write('app.py', '')
        code, _, err, _ = self.init(terminal=True, answers=['1', 'model', '', 'no', '2', ''])
        self.assertEqual(code, 0, err)
        self.assertEqual(Config.load(self.root / '.forge/config.toml').languages, ['python'])
        with tempfile.TemporaryDirectory() as tmp:
            self.root = Path(tmp)
            code, _, err, prompt = self.init('--language', 'javascript', terminal=True,
                                            answers=['1', 'model', '', 'no', '2'])
            self.assertEqual(code, 0, err)
            self.assertEqual(prompt.call_count, 5)

    def test_late_cancellation_and_invalid_combination_do_not_write_files(self):
        code, _, _, _ = self.init(terminal=True, answers=['1', 'model', '', 'no', '2', KeyboardInterrupt])
        self.assertEqual(code, 130)
        self.assertEqual(list(self.root.iterdir()), [])
        code, _, err, prompt = self.init('--language', 'generic', '--language', 'python')
        self.assertEqual(code, 1)
        self.assertIn('generic alone', err)
        self.assertEqual(list(self.root.iterdir()), [])
        prompt.assert_not_called()

    def test_conflicting_flags_on_existing_project_do_not_mutate_files(self):
        self.assertEqual(self.init('--language', 'python')[0], 0)
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        code, _, err, _ = self.init('--language', 'typescript')
        self.assertEqual(code, 1)
        self.assertIn('Edit that setting explicitly', err)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(self.init('--language', 'python')[0], 0)

    def test_legacy_config_is_generic_and_invalid_settings_rejected(self):
        path = self.root / 'config.toml'
        path.write_text('[harness]\ndocs=[]\n')
        self.assertEqual(Config.load(path).languages, [])
        for value in ['"python"', '["rust"]', '["python", "python"]', '[12]', '[{}]']:
            path.write_text('[harness]\nlanguages=' + value + '\n')
            with self.subTest(value=value), self.assertRaises(ForgeError):
                Config.load(path)
        for name in ['python', 'typescript', 'javascript']:
            self.assertIn('## ', coding_standards([name]))

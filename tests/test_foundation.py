from pathlib import Path
import tempfile
import unittest

from solar_forge.audit import Audit
from solar_forge.context import collect
from solar_forge.domain import Config, ForgeError, Request, REQUEST_TEMPLATE
from solar_forge.workspace import Workspace

REQUEST = '# Request: Add billing export\n\n## Description\nExport invoices.\n\n## Technical Details\nUse CSV.\n\n## Acceptance Criteria\n- [ ] Export includes totals.\n'


class FoundationTests(unittest.TestCase):
    def test_request_and_missing_sections(self):
        request = Request.parse(REQUEST)
        self.assertEqual(request.slug, 'add-billing-export')
        for text in (REQUEST_TEMPLATE, '# Incomplete', REQUEST.replace('## Description', '## Other')):
            with self.assertRaises(ForgeError):
                Request.parse(text)

    def test_paths_and_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp), 8)
            for path in ('../outside', '/tmp/outside', '.env', '.aws/credentials', '.git/config', 'agentic_audit/x'):
                with self.assertRaises(ForgeError):
                    ws.read(path)
            for path in ('.forge/config.toml', 'AGENTS.md'):
                with self.assertRaises(ForgeError):
                    ws.write(path, 'x')
            (Path(tmp) / 'link').symlink_to('/tmp', target_is_directory=True)
            with self.assertRaises(ForgeError):
                ws.write('link/file', 'x')
            with self.assertRaises(ForgeError):
                ws.write('big', 'x' * 9)
            ws.write('src/a.py', 'hello')
            self.assertEqual(ws.read('src/a.py'), 'hello')
            self.assertEqual(ws.inventory(), ['src/a.py'])

    def test_audit_unique_and_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            a = Audit.create(ws, Request.parse(REQUEST))
            b = Audit.create(ws, Request.parse(REQUEST))
            self.assertNotEqual(a.path, b.path)
            with a.lock():
                with self.assertRaises(ForgeError):
                    with a.lock():
                        pass
            self.assertFalse((a.path / '.lock').exists())
            self.assertEqual(Audit.open(ws, a.path.relative_to(ws.root).as_posix()).load()['status'], 'discovering')

    def test_context_provenance_and_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            ws.write('README.md', 'Domain rules')
            context = collect(ws, Config())
            self.assertEqual(context['documents']['README.md'], 'Domain rules')
            self.assertEqual(context['skipped'][0]['path'], 'AGENTS.md')
            with self.assertRaises(ForgeError):
                collect(ws, Config(max_context_bytes=10))


if __name__ == '__main__':
    unittest.main()

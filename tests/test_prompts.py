import copy
import json
import unittest

from solar_forge.prompts import compact_context, prompt_json
from solar_forge.retrieval import context_sources


class PromptTests(unittest.TestCase):
    def test_exact_duplicates_keep_project_text_and_all_source_paths(self):
        context = {'documents': {'builtin/coding.md': 'Same policy. ' * 20, '.forge/standards/coding.md': 'Same policy. ' * 20,
                                 'project.md': 'Unique rule'}, 'skipped': [{'path': 'missing.md', 'reason': 'missing'}],
                   'inventory': ['main.py']}
        original = copy.deepcopy(context)
        packed = compact_context(context)
        self.assertEqual(context, original)
        self.assertEqual(packed['documents']['.forge/standards/coding.md'], 'Same policy. ' * 20)
        self.assertIn('.forge/standards/coding.md', packed['documents']['builtin/coding.md'])
        self.assertEqual(packed['documents']['project.md'], 'Unique rule')
        self.assertEqual(context_sources(context), context_sources(packed))
        self.assertEqual(packed['skipped'], context['skipped'])
        self.assertEqual(packed['inventory'], context['inventory'])

    def test_conflicting_or_merely_similar_guidance_is_not_deduplicated(self):
        documents = {'builtin/coding.md': 'Use two spaces.', '.forge/standards/coding.md': 'Use four spaces.',
                     'notes.md': 'Use four spaces.\n'}
        self.assertEqual(compact_context({'documents': documents})['documents'], documents)

    def test_short_duplicates_are_not_expanded_into_longer_references(self):
        docs = {'a.md': 'Short', 'b.md': 'Short'}
        self.assertEqual(compact_context({'documents': docs})['documents'], docs)

    def test_compact_json_preserves_unicode_and_values(self):
        value = {'text': 'こんにちは', 'nested': [1, True, None], 'path': 'a b.py'}
        packed = prompt_json(value)
        self.assertEqual(json.loads(packed), value)
        self.assertLess(len(packed.encode()), len(json.dumps(value).encode()))

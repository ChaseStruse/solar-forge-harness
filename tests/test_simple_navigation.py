import unittest
from prompt_toolkit.document import Document
from solar_forge.chat_workflow import continue_action, PRIMARY_COMMANDS
from solar_forge.terminal_chat import SlashCompleter


class SimpleNavigationTests(unittest.TestCase):
    def test_default_menu_is_small_but_advanced_prefixes_work(self):
        completer = SlashCompleter()
        options = [item.text for item in completer.get_completions(Document('/'), None)]
        self.assertEqual(options, list(PRIMARY_COMMANDS))
        self.assertNotIn('/discover', options)
        self.assertIn('/discover', [item.text for item in completer.get_completions(Document('/dis'), None)])

    def test_continue_never_approves(self):
        for status, expected in [('awaiting_answers', '/answer'), ('planned', '/review'),
                                 ('discovering', '/next'), ('ready_to_plan', '/next'),
                                 ('review_required', '/status')]:
            label, command = continue_action({'run_status': status})
            self.assertTrue(label)
            self.assertEqual(command, expected)
        self.assertEqual(continue_action({'reviewed_plan': {'hash': 'abc'}})[1], '/review')
        self.assertEqual(continue_action({'request_draft': {'stage': 'review'}})[1], '/save-request')

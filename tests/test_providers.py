from dataclasses import replace
import os
import unittest
from unittest.mock import patch

from solar_forge.domain import Config, ForgeError
from solar_forge.providers import HTTPProvider


class ProviderTests(unittest.TestCase):
    @patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only', 'ANTHROPIC_API_KEY': 'test-only'})
    def test_all_provider_payloads(self):
        fixtures = {
            'openai': {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'ok'}]}]},
            'anthropic': {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'ok'}]},
            'ollama': {'message': {'content': 'ok'}},
            'compatible': {'choices': [{'finish_reason': 'stop', 'message': {'content': 'ok'}}]},
        }
        for kind, response in fixtures.items():
            with self.subTest(kind=kind), patch('solar_forge.providers.post_json', return_value=response) as post:
                provider = HTTPProvider(Config(kind=kind, model='chosen-model'))
                self.assertEqual(provider.complete('system', [{'role': 'user', 'content': 'hi'}]), 'ok')
                url, headers, body, timeout = post.call_args.args
                self.assertEqual(body['model'], 'chosen-model')
                self.assertEqual(timeout, 120)
                if kind == 'openai':
                    self.assertFalse(body['store'])
                    self.assertTrue(url.endswith('/v1/responses'))
                elif kind == 'anthropic':
                    self.assertEqual(headers['anthropic-version'], '2023-06-01')
                else:
                    self.assertFalse(body['stream'])
                    self.assertEqual(body['messages'][0]['role'], 'system')

    def test_invalid_endpoints(self):
        for url in ('http://example.com', 'https://key@example.com', 'file:///tmp/x', 'https://x/?key=y'):
            with self.assertRaises(ForgeError):
                HTTPProvider(Config(model='local', base_url=url))
        HTTPProvider(Config(model='local', base_url='http://127.0.0.1:11434'))

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_key_and_model(self):
        with self.assertRaises(ForgeError):
            HTTPProvider(Config(kind='openai', model='configured'))
        with self.assertRaises(ForgeError):
            HTTPProvider(Config())

    @patch('solar_forge.providers.post_json', return_value={'choices': [{'finish_reason': 'length', 'message': {'content': 'partial'}}]})
    def test_truncated_response_rejected(self, _):
        with self.assertRaises(ForgeError):
            HTTPProvider(Config(kind='compatible', model='local')).complete('system', [])

    def test_ollama_incomplete_and_malformed_outputs_rejected(self):
        for response in ({'done': False, 'message': {'content': 'partial'}},
                         {'done_reason': 'length', 'message': {'content': 'partial'}},
                         {'message': {'content': None}}):
            with patch('solar_forge.providers.post_json', return_value=response):
                with self.assertRaises(ForgeError):
                    HTTPProvider(Config(model='local')).complete('system', [])

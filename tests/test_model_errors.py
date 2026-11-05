import json
import unittest
from unittest.mock import patch

import httpx
from google.genai.errors import ClientError
from pydantic import ValidationError

from workbench.intelligence.client import AI, ModelError, error_message
from workbench.intelligence.models import Answer


class ModelErrorTests(unittest.TestCase):
    def test_gemini_codes_and_invalid_key_are_safe(self):
        for code in (400, 403, 404, 429):
            exc = ClientError(code, {'error': {'message': 'private-key-and-document'}})
            message = error_message(exc)
            self.assertIn('AI-' + str(code), message)
            self.assertNotIn('private-key', message)
        exc = ClientError(400, {'error': {'details': [{'reason': 'API_KEY_INVALID'}]}})
        self.assertIn('AI-KEY', error_message(exc))

    def test_network_format_and_unknown_do_not_expose_content(self):
        for exc, tag in ((httpx.ReadTimeout('private'), 'AI-TIMEOUT'),
                         (httpx.ConnectError('private'), 'AI-NETWORK'),
                         (RuntimeError('private'), 'AI-UNKNOWN')):
            self.assertIn(tag, error_message(exc))
            self.assertNotIn('private', error_message(exc))
        try:
            Answer.model_validate({'answer': {'private': 'document'}})
        except ValidationError as exc:
            self.assertIn('AI-FORMAT', error_message(exc))
            self.assertNotIn('document', error_message(exc))

    def test_provider_boundary_wraps_error_and_preserves_quota(self):
        class Store:
            calls = 0
            def reserve_call(self): self.calls += 1
        store = Store()
        ai = AI(store, 'gemini', 'fixture', 'fixture')
        with patch.object(ai, '_generate', side_effect=ClientError(404, {'message': 'private'})):
            with self.assertRaises(ModelError) as caught:
                ai.generate('system', 'private document', Answer)
        self.assertEqual(store.calls, 1)
        self.assertIn('AI-404', str(caught.exception))
        self.assertNotIn('private', str(caught.exception))
        self.assertEqual(error_message(caught.exception), str(caught.exception))

    def test_400_distinguishes_region_precondition_and_schema(self):
        for detail, tag in (({'message': 'User location is not supported for the API use.'}, 'AI-REGION'),
                            ({'status': 'FAILED_PRECONDITION', 'message': 'private'}, 'AI-PRECONDITION'),
                            ({'message': 'Invalid response_schema: private'}, 'AI-SCHEMA')):
            message = error_message(ClientError(400, {'error': detail}))
            self.assertIn(tag, message)
            self.assertNotIn('private', message)

    def test_gemini_sdk_sends_json_schema_and_validates_response(self):
        from google import genai
        original_client = genai.Client
        requests = []
        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={'candidates': [{'content': {'role': 'model', 'parts': [
                {'text': '{"answer":"ok","sources":[]}'}]}, 'finishReason': 'STOP'}]})
        def factory(**kwargs):
            return original_client(api_key='offline-fixture', http_options={
                'client_args': {'transport': httpx.MockTransport(handler)}})
        class Store:
            def reserve_call(self): pass
        with patch('google.genai.Client', side_effect=factory):
            result = AI(Store(), 'gemini', 'gemini-3.8-flash', 'fixture').generate('system', 'prompt', Answer)
        self.assertEqual(result.answer, 'ok')
        config = requests[0]['generationConfig']
        self.assertNotIn('responseSchema', config)
        self.assertEqual(config['responseJsonSchema']['additionalProperties'], False)
        self.assertEqual(config['responseJsonSchema']['required'], ['answer', 'sources'])

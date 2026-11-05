import json
import unittest
from unittest.mock import patch

import httpx
from google.genai.errors import ClientError, ServerError
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

    def test_transient_server_error_recovers_without_repeating_completed_work(self):
        class Store:
            calls = 0
            def reserve_call(self): self.calls += 1
        store = Store()
        ai = AI(store, 'gemini', 'fixture', 'fixture')
        success = Answer(answer='ok', sources=[])
        with patch.object(ai, '_generate', side_effect=[ServerError(503, {}), success]) as generate, \
                patch('workbench.intelligence.client.time.sleep') as sleep:
            self.assertEqual(ai.generate('system', 'prompt', Answer), success)
        self.assertEqual(store.calls, 2)
        self.assertEqual(generate.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_retry_is_bounded_and_client_errors_are_not_retried(self):
        class Store:
            calls = 0
            def reserve_call(self): self.calls += 1
        for code, attempts in ((503, 3), (400, 1), (429, 1)):
            store = Store()
            ai = AI(store, 'gemini', 'fixture', 'fixture')
            error = ServerError(code, {}) if code == 503 else ClientError(code, {})
            with patch.object(ai, '_generate', side_effect=error), patch('workbench.intelligence.client.time.sleep'):
                with self.assertRaises(ModelError) as caught:
                    ai.generate('system', 'prompt', Answer)
            self.assertEqual(store.calls, attempts)
            self.assertIn('AI-' + str(code), str(caught.exception))
            if code == 503: self.assertIn('2 次', str(caught.exception))

    def test_gemini_503_falls_back_to_prompt_json_with_strict_validation(self):
        from google import genai
        original_client = genai.Client
        requests = []
        def handler(request):
            requests.append(json.loads(request.content))
            if len(requests) == 1:
                return httpx.Response(503, json={'error': {'status': 'UNAVAILABLE'}})
            text = ('```json\n{"answer":"ok","sources":[]}\n```' if len(requests) == 2
                    else '{"answer":"ok","sources":[],"unexpected":"private"}')
            return httpx.Response(200, json={'candidates': [{'content': {'role': 'model',
                'parts': [{'text': text}]}, 'finishReason': 'STOP'}]})
        def factory(**kwargs):
            return original_client(api_key='offline-fixture', http_options={
                'retry_options': {'attempts': 1},
                'client_args': {'transport': httpx.MockTransport(handler)}})
        class Store:
            calls = 0
            def reserve_call(self): self.calls += 1
        store = Store()
        ai = AI(store, 'gemini', 'gemini-3.5-flash-lite', 'fixture')
        images = [{'mime': 'image/png', 'data': 'ZmFrZQ=='}]
        with patch('google.genai.Client', side_effect=factory), patch('workbench.intelligence.client.time.sleep'):
            self.assertEqual(ai.generate('system', 'prompt', Answer, images).answer, 'ok')
            with self.assertRaises(ModelError) as caught:
                ai.generate('system', 'next prompt', Answer)
        self.assertEqual(store.calls, 3)
        self.assertIn('responseJsonSchema', requests[0]['generationConfig'])
        for req in requests[1:]:
            self.assertNotIn('responseJsonSchema', req.get('generationConfig', {}))
            self.assertNotIn('responseMimeType', req.get('generationConfig', {}))
            self.assertIn('"required":["answer","sources"]', str(req['systemInstruction']))
        self.assertEqual(requests[0]['contents'], requests[1]['contents'])
        self.assertIn('AI-FORMAT', str(caught.exception))
        self.assertNotIn('private', str(caught.exception))

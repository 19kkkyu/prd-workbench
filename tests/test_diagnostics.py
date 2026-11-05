import json
import unittest
import httpx

from workbench.intelligence.diagnostics import probe_gemini


class Store:
    calls = 0
    def reserve_call(self): self.calls += 1


class DiagnosticTests(unittest.TestCase):
    def test_plain_failure_stops_and_redacts_key_and_urls(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(503, json={'error': {'status': 'UNAVAILABLE',
                'message': 'Busy fixture-key https://example.test/?key=fixture-key'}})
        store = Store()
        result = probe_gemini(store, 'fixture', 'fixture-key', httpx.MockTransport(handler))
        self.assertEqual(store.calls, 1)
        self.assertEqual(len(requests), 1)
        self.assertIn('HTTP 503', result[0]['detail'])
        self.assertNotIn('fixture-key', result[0]['detail'])
        self.assertNotIn('https://', result[0]['detail'])
        self.assertNotIn('generationConfig', json.loads(requests[0].content))
        self.assertNotIn('key=', str(requests[0].url))

    def test_plain_success_then_schema_failure_are_distinct(self):
        requests = []
        def handler(request):
            requests.append(json.loads(request.content))
            if len(requests) == 1:
                return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': 'OK'}]}}]})
            return httpx.Response(400, json={'error': {'message': 'Invalid schema'}})
        store = Store()
        result = probe_gemini(store, 'fixture', 'fixture', httpx.MockTransport(handler))
        self.assertEqual(store.calls, 2)
        self.assertTrue(result[0]['ok'])
        self.assertFalse(result[1]['ok'])
        self.assertIn('responseJsonSchema', requests[1]['generationConfig'])
        self.assertIn('HTTP 400', result[1]['detail'])

"""仅通过 HTTP 通信的客户端契约测试，不启动服务，也不调用模型。"""
import ast
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import httpx

from frontend.api_client import APIClient, APIError, backend_timeout, backend_url


class FrontendClientTests(unittest.TestCase):
    def test_proxy_environment_is_bypassed_only_for_loopback_owned_clients(self):
        cases = [
            ('http://localhost:8000', False), ('http://LOCALHOST:8000', False),
            ('http://localhost.:8000', False), ('http://127.0.0.1:8000', False),
            ('http://127.12.34.56:8000', False), ('http://[::1]:8000', False),
            ('https://api.example.com', True), ('http://192.168.1.20:8000', True),
            ('https://localhost.example.com', True),
        ]
        for url, expected in cases:
            with self.subTest(url=url), patch('frontend.api_client.httpx.Client') as constructor:
                with APIClient(url, timeout=12):
                    self.assertEqual(constructor.call_args.kwargs['trust_env'], expected)
        injected = Mock()
        with patch('frontend.api_client.httpx.Client') as constructor:
            with APIClient('http://127.0.0.1:8000', client=injected):
                constructor.assert_not_called()
        injected.close.assert_not_called()

    def test_every_route_uses_http_and_session_parameters(self):
        requests = []

        def handle(request):
            requests.append(request)
            if request.method == 'DELETE' and request.url.path.endswith('/item-1'):
                return httpx.Response(204)
            return httpx.Response(200, json={'ok': True})

        with APIClient('http://testserver', transport=httpx.MockTransport(handle)) as client:
            client.health()
            client.course()
            client.chapters()
            client.chapter('ch01')
            client.source('chunk-1')
            client.ask({'question': '智能体', 'session_id': 'session-1'})
            client.summarize({'chapter_id': 'ch01'})
            client.quiz({'chapter_id': 'ch01', 'count': 2})
            client.history('session-1', limit=10, offset=20)
            client.history_item('item-1', 'session-1')
            self.assertIsNone(client.delete_history_item('item-1', 'session-1'))
            client.clear_history('session-1')
        expected = [
            ('GET', '/api/health'), ('GET', '/api/course'), ('GET', '/api/chapters'),
            ('GET', '/api/chapters/ch01'), ('GET', '/api/sources/chunk-1'),
            ('POST', '/api/qa'), ('POST', '/api/summary'), ('POST', '/api/quiz'),
            ('GET', '/api/history'), ('GET', '/api/history/item-1'),
            ('DELETE', '/api/history/item-1'), ('DELETE', '/api/history'),
        ]
        self.assertEqual([(r.method, r.url.path) for r in requests], expected)
        self.assertEqual(json.loads(requests[5].content)['question'], '智能体')
        for request in requests[8:]:
            self.assertEqual(request.url.params['session_id'], 'session-1')
        self.assertEqual(requests[8].url.params['offset'], '20')
        self.assertEqual(requests[8].url.params['limit'], '10')

    def test_error_envelope_is_preserved(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(422,
            json={'error': {'code': 'validation_error', 'message': '请输入有效问题', 'details': [{'field': 'question'}]}, 'request_id': 'body-id'},
            headers={'X-Request-ID': 'header-id'}))
        with APIClient('http://testserver', transport=transport) as client:
            with self.assertRaises(APIError) as raised:
                client.ask({})
        error = raised.exception
        self.assertEqual((error.status_code, error.code, error.message, error.request_id),
                         (422, 'validation_error', '请输入有效问题', 'header-id'))
        self.assertEqual(error.details, [{'field': 'question'}])

    def test_timeout_and_disconnect_are_friendly(self):
        for exception, code in [(httpx.ReadTimeout, 'timeout'), (httpx.ConnectError, 'connection_error')]:
            with self.subTest(code=code):
                def handle(request):
                    raise exception('sensitive raw server failure', request=request)
                with APIClient('http://testserver', transport=httpx.MockTransport(handle)) as client:
                    with self.assertRaises(APIError) as raised:
                        client.health()
                self.assertEqual(raised.exception.code, code)
                self.assertNotIn('sensitive', str(raised.exception))

    def test_non_json_errors_and_invalid_success(self):
        for status, expected in [(502, 'http_error'), (200, 'invalid_response')]:
            with self.subTest(status=status):
                transport = httpx.MockTransport(lambda request: httpx.Response(status, text='<html>secret</html>'))
                with APIClient('http://testserver', transport=transport) as client:
                    with self.assertRaises(APIError) as raised:
                        client.health()
                self.assertEqual(raised.exception.code, expected)
                self.assertNotIn('secret', str(raised.exception))

    def test_injected_client_ownership_timeout_and_base_path(self):
        requests = []
        shared = httpx.Client(transport=httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(200, json={})))
        with APIClient('http://testserver/prefix/', timeout=17, client=shared) as client:
            client.health()
            self.assertEqual(client.pdf_url(10), 'http://testserver/prefix/api/course/source#page=10')
        self.assertFalse(shared.is_closed)
        self.assertEqual(requests[0].url.path, '/prefix/api/health')
        self.assertEqual(requests[0].extensions['timeout']['read'], 17)
        shared.close()

    def test_invalid_pdf_page_and_backend_url(self):
        with APIClient('http://testserver', transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))) as client:
            for page in [0, -1, True, 'https://unrelated.example']:
                with self.assertRaises(ValueError):
                    client.pdf_url(page)
        for url in ['file:///etc/passwd', 'https://user:token@testserver', 'http://testserver?next=1', 'http://testserver:bad']:
            with self.assertRaises(APIError):
                APIClient(url)

    def test_timeout_environment(self):
        for value, expected in [('30', 30), ('invalid', 90), ('-1', 90), ('9999', 90)]:
            with patch.dict('os.environ', {'BACKEND_TIMEOUT': value}):
                self.assertEqual(backend_timeout(), expected)

    def test_dotenv_is_root_relative_selective_and_does_not_override_environment(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.env').write_text(
                'BACKEND_URL=http://dotenv-server:8123\nBACKEND_TIMEOUT=42\nLLM_API_KEY=server-only\n',
                encoding='utf-8')
            with patch('frontend.api_client.PROJECT_ROOT', root), patch.dict('os.environ', {}, clear=True):
                self.assertEqual(backend_url(), 'http://dotenv-server:8123')
                self.assertEqual(backend_timeout(), 42)
                import os
                self.assertNotIn('LLM_API_KEY', os.environ)
            with patch('frontend.api_client.PROJECT_ROOT', root), patch.dict('os.environ', {
                    'BACKEND_URL': 'http://environment-server', 'BACKEND_TIMEOUT': '12'}, clear=True):
                self.assertEqual(backend_url(), 'http://environment-server')
                self.assertEqual(backend_timeout(), 12)

    def test_frontend_never_imports_backend(self):
        root = Path(__file__).resolve().parents[1] / 'frontend'
        for path in root.rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text('utf-8'))):
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or '').startswith('backend'), path)
                elif isinstance(node, ast.Import):
                    self.assertFalse(any(alias.name.startswith('backend') for alias in node.names), path)


if __name__ == '__main__':
    unittest.main()

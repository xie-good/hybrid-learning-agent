"""检查后端日志、校验说明和通用错误提示统一使用中文。"""
import ast
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException

from backend.config import Settings
from backend.main import create_app


ROOT = Path(__file__).resolve().parents[1]
CHINESE = re.compile(r'[\u3400-\u9fff]')


class BackendMessageTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.settings = Settings(processed_dir=directory / 'missing',
                                 database_path=directory / 'history.sqlite3',
                                 index_dir=directory / 'indexes', generation_mode='extractive')

    def test_history_initialization_log_is_chinese(self):
        with patch('backend.main.HistoryStore', side_effect=sqlite3.OperationalError('private-token')):
            with self.assertLogs('course_assistant', level='ERROR') as captured:
                with TestClient(create_app(self.settings)) as client:
                    self.assertFalse(client.get('/api/health').json()['history_ready'])
        self.assertIn('历史记录初始化失败', captured.output[0])
        self.assertNotIn('private-token', captured.output[0])

    def test_unexpected_request_error_log_is_chinese(self):
        app = create_app(self.settings)

        @app.get('/test-error')
        def fail_request():
            raise RuntimeError('private-token')

        with TestClient(app) as client:
            with self.assertLogs('course_assistant', level='ERROR') as captured:
                response = client.get('/test-error', headers={'X-Request-ID': 'chinese-log-test'})
        self.assertEqual(response.status_code, 500)
        self.assertIn('请求编号=chinese-log-test', captured.output[0])
        self.assertIn('异常类型=RuntimeError', captured.output[0])
        self.assertNotIn('private-token', response.text + captured.output[0])

    def test_request_validation_messages_are_chinese(self):
        cases = [
            ('/api/qa', {}), ('/api/qa', {'question': 1}),
            ('/api/qa', {'question': ' '}), ('/api/qa', {'question': '字' * 2001}),
            ('/api/qa', {'question': '测试', 'top_k': 0}),
            ('/api/qa', {'question': '测试', 'top_k': 11}),
            ('/api/qa', {'question': '测试', 'top_k': True}),
            ('/api/qa', {'question': '测试', 'retrieval_mode': 'unknown'}),
            ('/api/qa', {'question': '测试', 'session_id': 'private-token'}),
            ('/api/qa', {'question': '测试', 'debug': 'unknown'}),
            ('/api/qa', {'question': '测试', 'chapter_id': 'unknown'}),
            ('/api/qa', {'question': '测试', 'chapter_id': 'ch01', 'section_id': 'ch02-s001'}),
            ('/api/qa', {'question': '测试', 'extra': 'private-token'}),
            ('/api/qa', []),
        ]
        with TestClient(create_app(self.settings)) as client:
            responses = [client.post(path, json=payload) for path, payload in cases]
            responses.append(client.post('/api/qa', content='{private-token',
                                         headers={'Content-Type': 'application/json'}))
            responses.append(client.get('/api/history'))
            responses.append(client.get('/api/history', params={'session_id': 'bad', 'limit': 'bad'}))
        for response in responses:
            with self.subTest(response=response.text):
                self.assertEqual(response.status_code, 422)
                error = response.json()['error']
                self.assertEqual(error['code'], 'VALIDATION_ERROR')
                for detail in error['details']:
                    self.assertRegex(detail['message'], CHINESE)
                    self.assertNotIn('Value error,', detail['message'])
                    self.assertIn('field', detail)
                    self.assertIn('type', detail)
                self.assertNotIn('private-token', response.text)

    def test_http_error_messages_are_chinese(self):
        app = create_app(self.settings)

        @app.get('/test-chinese-error')
        def chinese_error():
            raise HTTPException(400, '自定义中文说明。')

        @app.get('/test-english-error')
        def english_error():
            raise HTTPException(400, 'private-token')

        with TestClient(app) as client:
            for response in (client.get('/not-a-route'), client.post('/api/health')):
                self.assertIn(response.status_code, (404, 405))
                self.assertEqual(response.json()['error']['code'], 'HTTP_ERROR')
                self.assertRegex(response.json()['error']['message'], CHINESE)
            self.assertEqual(client.get('/test-chinese-error').json()['error']['message'], '自定义中文说明。')
            response = client.get('/test-english-error')
            self.assertEqual(response.json()['error']['message'], '请求处理失败。')
            self.assertNotIn('private-token', response.text)

    def test_validation_translation_does_not_expose_input_or_context(self):
        from backend.errors import validation_error_message

        for error_type in ('future_error', 'value_error'):
            error = {'type': error_type, 'msg': 'Value error, private-token',
                     'input': 'private-token', 'ctx': {'error': ValueError('private-token')}}
            self.assertEqual(validation_error_message(error), '参数值不符合要求。')
        error = {'type': 'value_error', 'msg': 'Value error, 所选小节必须属于所选章节。'}
        self.assertEqual(validation_error_message(error), '所选小节必须属于所选章节。')

    def test_backend_diagnostic_literals_are_chinese(self):
        violations = []
        for path in (ROOT / 'backend').rglob('*.py'):
            tree = ast.parse(path.read_text('utf-8-sig'))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                message = None
                if isinstance(node.func, ast.Name):
                    if node.func.id == '_check':
                        message = node.args[-1]
                    elif node.func.id in {'ValueError', 'OSError', 'RuntimeError', 'TypeError'}:
                        message = node.args[0]
                    elif node.func.id == 'AppError' and len(node.args) >= 3:
                        message = node.args[2]
                elif (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                      and node.func.value.id == 'logger'):
                    if node.func.attr in {'debug', 'info', 'warning', 'error', 'exception', 'critical'}:
                        message = node.args[0]
                if isinstance(message, ast.Constant) and isinstance(message.value, str):
                    if not CHINESE.search(message.value):
                        violations.append(f'{path}:{node.lineno}: {message.value}')
        self.assertEqual(violations, [], '\n'.join(violations))


if __name__ == '__main__':
    unittest.main()

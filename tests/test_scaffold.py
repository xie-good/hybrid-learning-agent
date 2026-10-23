"""只验证骨架接线与显式占位，不测试尚未实现的RAG效果。"""
import ast
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend.main import app
from backend.services import generation, learning, retrieval
from pipeline.build_index import build_indexes
from pipeline.chunk_txt import chunk_text
from pipeline.clean_pdf import clean_pdf

ROOT = Path(__file__).resolve().parents[1]


class ScaffoldTests(unittest.TestCase):
    def test_health(self):
        # 服务就绪与知识库就绪是不同状态，不能混为一谈。
        with TestClient(app) as client:
            response = client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'status': 'ok', 'stage': 'skeleton', 'knowledge_base_ready': False,
        })

    def test_qa_placeholder(self):
        with TestClient(app) as client:
            response = client.post('/api/qa', json={'question': '什么是智能体？'})
        self.assertEqual(response.status_code, 501)
        self.assertIn('尚未实现', response.json()['detail'])

    def test_learning_placeholders(self):
        with TestClient(app) as client:
            for endpoint in ('summary', 'quiz'):
                with self.subTest(endpoint=endpoint):
                    response = client.post(f'/api/{endpoint}', json={'chapter_id': 'ch01'})
                    self.assertEqual(response.status_code, 501)

    def test_invalid_input(self):
        with TestClient(app) as client:
            for payload in ({}, {'question': ''}):
                with self.subTest(payload=payload):
                    self.assertEqual(client.post('/api/qa', json=payload).status_code, 422)

    def test_openapi(self):
        with TestClient(app) as client:
            response = client.get('/openapi.json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()['paths']), {
            '/api/health', '/api/qa', '/api/summary', '/api/quiz',
        })

    def test_service_boundaries(self):
        # 后续从这些函数开始实现；现在不使用假数据假装成功。
        calls = [
            lambda: retrieval.retrieve('智能体'),
            lambda: generation.generate_answer('智能体', []),
            lambda: learning.summarize('ch01'),
            lambda: learning.generate_quiz('ch01'),
        ]
        for call in calls:
            with self.assertRaises(NotImplementedError):
                call()

    def test_pipeline_has_no_writes(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            for stage in (clean_pdf, chunk_text):
                with self.subTest(stage=stage.__name__):
                    with self.assertRaises(FileNotFoundError):
                        stage(base / 'missing-input', base / 'output')
                    self.assertEqual(list(base.iterdir()), [])
            with self.assertRaises(NotImplementedError):
                build_indexes(base / 'missing-input', base / 'output')

    def test_frontend_pages(self):
        # AppTest实际执行页面脚本，不要求先启动前端服务器。
        at = AppTest.from_file(str(ROOT / 'frontend/app.py')).run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        self.assertTrue(at.text_area[0].disabled)
        self.assertTrue(at.button[0].disabled)
        for name, title in [('summary', '章节总结'), ('quiz', '练习自测'),
                            ('history', '会话历史')]:
            at.switch_page(f'pages/{name}.py').run(timeout=15)
            self.assertEqual(len(at.exception), 0)
            self.assertTrue(any(item.value == title for item in at.title))

    def test_python_syntax(self):
        # AST解析不产生__pycache__，也不启动离线数据处理。
        for folder in ('backend', 'frontend', 'pipeline', 'tests'):
            for path in (ROOT / folder).rglob('*.py'):
                with self.subTest(file=str(path)):
                    ast.parse(path.read_text('utf-8'), filename=str(path))


if __name__ == '__main__':
    unittest.main()

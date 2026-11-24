"""端到端 HTTP 契约测试：真实合成 PDF、真实检索与 SQLite，不调用外部模型。"""
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from pipeline.build_index import build_indexes
from pipeline.run_preprocess import preprocess
from tests.corpus_fixture import make_corpus
from test_preprocess import make_pdf


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        cls.pdf = cls.base / 'course.pdf'
        make_pdf(cls.pdf)
        cls.processed = cls.base / 'processed'
        preprocess(cls.pdf, cls.processed, max_chars=300, overlap=30)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        # 此组专测无向量服务的本地能力；产品默认混合检索由下方独立夹具覆盖。
        self.settings = Settings(processed_dir=self.processed,
            database_path=self.base / f'{uuid4()}.sqlite3', index_dir=self.base / 'indexes',
            generation_mode='extractive', default_retrieval_mode='bm25', source_pdf=self.pdf,
            llm_base_url='', llm_model='', llm_api_key='', embedding_base_url='',
            embedding_model='', embedding_api_key='')
        self.app = create_app(self.settings)
        self.client = self.enterContext(TestClient(self.app))
        self.session = str(uuid4())

    def ask(self, **kwargs):
        return self.client.post('/api/qa', json={
            'question': 'Agent knowledge', 'session_id': self.session, **kwargs})

    def test_health_and_course(self):
        response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['knowledge_base_ready'])
        self.assertEqual(response.json()['retrieval_modes'], ['bm25'])
        self.assertEqual(response.json()['default_retrieval_mode'], 'bm25')
        self.assertEqual(response.json()['generation_mode'], 'extractive')
        self.assertTrue(response.json()['retrieval_ready'])
        course = self.client.get('/api/course')
        self.assertEqual(course.status_code, 200, course.text)
        self.assertEqual(course.json()['course_id'], 'hello_agents')
        self.assertEqual(course.json()['chapter_count'], 2)

    def test_directory_and_source(self):
        result = self.client.get('/api/chapters')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(result.json()['chapters']), 2)
        self.assertEqual(self.client.get('/api/chapters/ch01').status_code, 200)
        self.assertEqual(self.client.get('/api/chapters/ch13').status_code, 404)
        response = self.ask()
        self.assertEqual(response.status_code, 200, response.text)
        evidence = response.json()['citations'][0]
        source = self.client.get('/api/sources/' + evidence['chunk_id'])
        self.assertEqual(source.status_code, 200, source.text)
        self.assertEqual(source.json()['text'], evidence['text'])
        self.assertEqual(self.client.get('/api/sources/unknown').status_code, 404)

    def test_fixed_pdf_and_range(self):
        response = self.client.get('/api/course/source')
        self.assertEqual(response.status_code, 200, response.text[:100])
        self.assertEqual(response.headers['content-type'], 'application/pdf')
        self.assertEqual(response.content, self.pdf.read_bytes())
        partial = self.client.get('/api/course/source', headers={'Range': 'bytes=0-3'})
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(partial.content, b'%PDF')

    def test_question_citations_and_metadata(self):
        response = self.ask(chapter_id='ch01', debug=True)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body['insufficient_evidence'])
        self.assertEqual(body['generation_mode'], 'extractive')
        self.assertEqual(body['retrieval_mode'], 'bm25')
        self.assertIn('[1]', body['answer'])
        self.assertTrue(body['citations'])
        self.assertTrue(all(e['chapter_id'] == 'ch01' for e in body['citations']))
        self.assertEqual(body['session_id'], self.session)
        self.assertEqual(body['request_id'], response.headers['X-Request-ID'])
        self.assertGreaterEqual(body['latency_ms'], 0)
        self.assertIsInstance(body['debug'], dict)

    def test_empty_evidence_is_not_invented(self):
        result = self.ask(question='zxqvnonexistenttoken')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()['insufficient_evidence'])
        self.assertEqual(result.json()['citations'], [])

    def test_section_scope(self):
        response = self.ask(section_id='ch01-s001')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['scope'], {'chapter_id': 'ch01', 'section_id': 'ch01-s001'})
        self.assertTrue(all(c['section_id'] == 'ch01-s001' for c in response.json()['citations']))
        self.assertEqual(self.ask(chapter_id='ch01', section_id='ch02-s001').status_code, 422)
        self.assertEqual(self.ask(section_id='ch01-s999').status_code, 404)

    def test_input_validation_and_errors(self):
        for payload in ({}, {'question': ''}, {'question': '   '}, {'question': 'a' * 2001},
                        {'question': 'x', 'top_k': 0}, {'question': 'x', 'top_k': True},
                        {'question': 'x', 'retrieval_mode': 'fake'}, {'question': 'x', 'session_id': 'abc'},
                        {'question': 'x', 'unexpected_secret': 'do-not-echo'}):
            with self.subTest(payload=str(payload)[:50]):
                response = self.client.post('/api/qa', json=payload)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()['error']['code'], 'VALIDATION_ERROR')
                self.assertNotIn('do-not-echo', response.text)
        self.assertEqual(self.ask(chapter_id='ch99').status_code, 404)
        self.assertEqual(self.ask(retrieval_mode='vector').status_code, 503)
        self.assertEqual(self.ask(retrieval_mode='hybrid').status_code, 503)
        malformed = self.client.post('/api/qa', content='{bad', headers={'Content-Type': 'application/json'})
        self.assertEqual(malformed.status_code, 422)

    def test_summary_and_quiz(self):
        summary = self.client.post('/api/summary', json={'chapter_id': 'ch01'})
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertTrue(summary.json()['summary'])
        self.assertTrue(summary.json()['citations'])
        self.assertIn('coverage', summary.json())
        quiz = self.client.post('/api/quiz', json={'chapter_id': 'ch01', 'count': 1})
        self.assertEqual(quiz.status_code, 200, quiz.text)
        self.assertEqual(len(quiz.json()['questions']), 1)
        question = quiz.json()['questions'][0]
        self.assertTrue(question['answer'])
        self.assertTrue(question['citation_ids'])
        for endpoint in ('summary', 'quiz'):
            self.assertEqual(self.client.post('/api/' + endpoint, json={'chapter_id': 'ch99'}).status_code, 404)
        for payload in ({'chapter_id': 'ch01', 'count': 11}, {'chapter_id': 'ch01', 'count': 0},
                        {'chapter_id': 'ch01', 'question_types': []},
                        {'chapter_id': 'ch01', 'question_types': ['short_answer', 'short_answer']},
                        {'chapter_id': 'ch01', 'count': 1, 'question_types': ['short_answer', 'multiple_choice']},
                        {'chapter_id': 'ch01', 'difficulty': 'expert'}):
            self.assertEqual(self.client.post('/api/quiz', json=payload).status_code, 422)

    def test_history_isolation_pagination_and_deletion(self):
        one = self.ask().json()
        two = self.ask().json()
        params = {'session_id': self.session}
        result = self.client.get('/api/history', params={**params, 'limit': 1, 'offset': 1})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['total'], 2)
        self.assertEqual(len(result.json()['items']), 1)
        uri = '/api/history/' + one['history_id']
        self.assertEqual(self.client.get(uri, params=params).json()['question'], 'Agent knowledge')
        outsider = {'session_id': str(uuid4())}
        self.assertEqual(self.client.get('/api/history', params=outsider).json()['total'], 0)
        self.assertEqual(self.client.get(uri, params=outsider).status_code, 404)
        self.assertEqual(self.client.delete(uri, params=outsider).status_code, 404)
        self.assertEqual(self.client.delete(uri, params=params).status_code, 204)
        self.assertEqual(self.client.get(uri, params=params).status_code, 404)
        self.assertEqual(self.client.delete('/api/history', params=params).json(), {'deleted': 1})
        self.assertEqual(self.client.get('/api/history', params=params).json()['total'], 0)
        self.assertEqual(self.client.get('/api/history').status_code, 422)
        self.assertEqual(self.client.get('/api/history', params={**params, 'limit': 101}).status_code, 422)

    def test_session_creation_and_persistence(self):
        response = self.client.post('/api/qa', json={'question': 'Agent'})
        self.assertEqual(response.status_code, 200, response.text)
        session_id = response.json()['session_id']
        with TestClient(create_app(self.settings)) as second_client:
            result = second_client.get('/api/history', params={'session_id': session_id})
        self.assertEqual(result.json()['total'], 1)

    def test_request_id_cors_and_internal_errors(self):
        response = self.client.get('/api/health', headers={'X-Request-ID': 'test-123'})
        self.assertEqual(response.headers['X-Request-ID'], 'test-123')
        result = self.client.options('/api/qa', headers={'Origin': 'http://localhost:8501',
            'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['access-control-allow-origin'], 'http://localhost:8501')
        with patch.object(self.app.state.generation, 'answer', side_effect=RuntimeError('secret-token-123')):
            failed = self.ask()
        self.assertEqual(failed.status_code, 500)
        self.assertNotIn('secret-token-123', failed.text)
        self.assertIn('request_id', failed.json())
        self.assertEqual(self.client.get('/api/history', params={'session_id': self.session}).json()['total'], 0)

    def test_concurrent_history_writes(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.ask(), range(6)))
        self.assertTrue(all(r.status_code == 200 for r in results), [r.text for r in results])
        self.assertEqual(self.client.get('/api/history', params={'session_id': self.session}).json()['total'], 6)

    def test_missing_data_is_explicit(self):
        settings = Settings(processed_dir=self.base / 'missing', database_path=self.base / 'missing.sqlite3',
                            generation_mode='extractive', embedding_base_url='', embedding_model='')
        with TestClient(create_app(settings)) as client:
            health = client.get('/api/health')
            self.assertEqual(health.status_code, 200)
            self.assertFalse(health.json()['knowledge_base_ready'])
            self.assertEqual(health.json()['status'], 'degraded')
            for method, path, body in [('GET', '/api/course', None), ('GET', '/api/chapters', None),
                ('POST', '/api/qa', {'question': 'Agent'}), ('POST', '/api/summary', {'chapter_id': 'ch01'})]:
                result = client.request(method, path, json=body)
                self.assertEqual(result.status_code, 503, result.text)

    def test_missing_default_mode_or_model_degrades_health(self):
        from dataclasses import replace
        for config in (replace(self.settings, default_retrieval_mode='hybrid'),
                       replace(self.settings, generation_mode='llm', llm_base_url='', llm_model='')):
            with TestClient(create_app(config)) as client:
                response = client.get('/api/health')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['status'], 'degraded')
                self.assertTrue(response.json()['knowledge_base_ready'])
                self.assertEqual(client.post('/api/qa', json={'question': 'Agent'}).status_code, 503)

    def test_openapi_contract(self):
        spec = self.client.get('/openapi.json').json()
        expected = {'/api/health', '/api/course', '/api/chapters', '/api/chapters/{chapter_id}',
                    '/api/sources/{chunk_id}', '/api/course/source', '/api/qa', '/api/summary',
                    '/api/quiz', '/api/history', '/api/history/{record_id}'}
        self.assertEqual(set(spec['paths']), expected)
        self.assertEqual(len([m for p in spec['paths'].values() for m in p if m in {'get', 'post', 'delete'}]), 13)
        for path in ('/api/qa', '/api/summary', '/api/quiz'):
            self.assertIn('$ref', spec['paths'][path]['post']['responses']['200']['content']['application/json']['schema'])
        static = json.loads((Path(__file__).resolve().parents[1] / 'docs/openapi.json').read_text('utf-8'))
        self.assertEqual(static['paths'], spec['paths'])
        self.assertEqual(static['components'], spec['components'])
        self.assertEqual(self.client.get('/docs').status_code, 200)
        self.assertEqual(self.client.get('/redoc').status_code, 200)


class HybridDefaultAPITests(unittest.TestCase):
    """使用产品默认值验证混合检索路由，仅替换外部向量服务边界。"""

    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.settings = make_corpus(root, default_retrieval_mode=Settings().default_retrieval_mode,
            embedding_base_url='http://localhost:5678/v1', embedding_model='test-embedding')

    def test_omitted_mode_uses_hybrid_and_explicit_bm25_remains_available(self):
        with patch('pipeline.build_index.fetch_embeddings',
                   side_effect=lambda config, texts: [[1.0, 0.0] for text in texts]):
            build_indexes(self.settings.processed_dir / 'chunks.jsonl', self.settings.index_dir,
                          settings=self.settings, mode='hybrid')
        with TestClient(create_app(self.settings)) as client:
            health = client.get('/api/health').json()
            self.assertEqual(health['default_retrieval_mode'], 'hybrid')
            self.assertEqual(health['retrieval_modes'], ['bm25', 'vector', 'hybrid'])
            self.assertTrue(health['retrieval_ready'])
            with patch('backend.services.retrieval.fetch_embeddings', return_value=[[1.0, 0.0]]):
                for options in ({}, {'retrieval_mode': None}):
                    with self.subTest(options=options):
                        response = client.post('/api/qa', json={
                            'question': 'get_weather', 'debug': True, **options})
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(response.json()['retrieval_mode'], 'hybrid')
                        self.assertFalse(response.json()['insufficient_evidence'])
                        self.assertTrue(response.json()['citations'])
                        gate = response.json()['debug']['evidence_gate']
                        self.assertEqual(gate['gate_version'], 'rank-bm25-returned-evidence-v1')
                        self.assertTrue(gate['passed'])
            with patch('backend.services.retrieval.fetch_embeddings', side_effect=AssertionError('network')):
                response = client.post('/api/qa', json={
                    'question': 'get_weather', 'retrieval_mode': 'bm25'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['retrieval_mode'], 'bm25')

    def test_missing_hybrid_index_reports_degraded_and_does_not_fall_back(self):
        with TestClient(create_app(self.settings)) as client:
            health = client.get('/api/health').json()
            self.assertEqual(health['default_retrieval_mode'], 'hybrid')
            self.assertEqual(health['retrieval_modes'], ['bm25'])
            self.assertFalse(health['retrieval_ready'])
            self.assertEqual(health['status'], 'degraded')
            response = client.post('/api/qa', json={'question': 'get_weather'})
            self.assertEqual(response.status_code, 503, response.text)


if __name__ == '__main__':
    unittest.main()

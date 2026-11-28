"""语料库、BM25、离线索引与真实 HTTP 嵌入接口的契约测试。

PDF 测试夹具使用生产预处理流程。所有外部调用均由 HTTPX MockTransport
处理，其中包含调用失败与响应格式异常的分支。
"""
from collections import Counter
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx
from rank_bm25 import BM25Okapi

from backend.errors import AppError
from backend.services.corpus import CorpusRepository, DATA_FILES
from backend.services.retrieval import (
    BM25_ALGORITHM, BM25_BACKEND_VERSION, BM25Index, RetrievalService, embedding_endpoint, embedding_fingerprint,
    fetch_embeddings, normalized_vector, read_index_file, tokenize,
)
from corpus_fixture import make_corpus
from pipeline.build_index import build_indexes


def read_json(path):
    return json.loads(Path(path).read_text('utf-8'))


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False), 'utf-8')


def write_jsonl(path, payload):
    Path(path).write_text(''.join(json.dumps(item, ensure_ascii=False) + '\n'
                                 for item in payload), 'utf-8')


def transport_post(client):
    """将顶层请求选项适配到已构建的模拟客户端。"""
    def post(*args, trust_env=True, **kwargs):
        return client.post(*args, **kwargs)
    return post


class CorpusFixtureTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = make_corpus(Path(self.directory.name))
        self.repo = CorpusRepository(self.settings)
        self.assertTrue(self.repo.status()['ready'])

    def assert_error(self, status, code, action):
        with self.assertRaises(AppError) as context:
            action()
        self.assertEqual((context.exception.status_code, context.exception.code), (status, code))
        return context.exception

    def update_hash(self, filename):
        report_path = self.settings.processed_dir / 'report.json'
        report = read_json(report_path)
        report['output_sha256'][filename] = hashlib.sha256(
            (self.settings.processed_dir / filename).read_bytes()).hexdigest()
        write_json(report_path, report)

    def assert_unready(self):
        repo = CorpusRepository(self.settings)
        self.assertEqual(repo.status()['chunk_count'], 0)
        self.assertIsNone(repo.status()['dataset_version'])
        self.assert_error(503, 'corpus_not_ready', repo.require_ready)


class CorpusTests(CorpusFixtureTest):
    def test_real_preprocessed_pdf_and_catalog_are_ready(self):
        course = self.repo.course()
        self.assertEqual((course['chapter_count'], course['section_count']), (2, 3))
        self.assertEqual((course['page_start'], course['page_end']), (1, 3))
        self.assertTrue(course['source_available'])
        self.assertGreater(course['chunk_count'], 3)
        self.assertEqual(self.repo.source_path(), self.settings.source_pdf.resolve())
        self.assertEqual([c['chapter_id'] for c in self.repo.chapters()], ['ch01', 'ch02'])

    def test_evidence_exact_text_offsets_source_and_copy_isolation(self):
        chunk = self.repo.scoped_chunks()[0]
        citation = self.repo.evidence(chunk['chunk_id'])
        self.assertEqual(citation['text'], chunk['text'])
        self.assertEqual(citation['source_url'], '/api/course/source#page=1')
        self.assertEqual(citation['citation_id'], 1)
        self.assertIsNone(citation['score'])
        citation['review_flags'].append('mutated')
        chunk['text'] = 'mutated'
        self.assertNotIn('mutated', self.repo.evidence(chunk['chunk_id'])['review_flags'])
        self.assertNotEqual(self.repo.evidence(chunk['chunk_id'])['text'], 'mutated')
        chapters = self.repo.chapters()
        chapters[0]['title'] = 'mutated'
        self.assertNotEqual(self.repo.chapter('ch01')['title'], 'mutated')

    def test_scope_filters_and_unknown_scope(self):
        scoped = self.repo.scoped_chunks('ch01', 'ch01-s002')
        self.assertTrue(scoped)
        self.assertTrue(all(c['page_start'] == 2 for c in scoped))
        self.assertEqual(scoped, self.repo.scoped_chunks(section_id='ch01-s002'))
        self.assert_error(404, 'chapter_not_found', lambda: self.repo.scoped_chunks('ch13'))
        self.assert_error(404, 'section_not_found',
                          lambda: self.repo.scoped_chunks('ch02', 'ch01-s001'))
        self.assert_error(404, 'section_not_found',
                          lambda: self.repo.scoped_chunks(section_id='unknown'))
        self.assert_error(404, 'source_not_found', lambda: self.repo.evidence('../report.json'))

    def test_missing_artifact_or_malformed_report_yields_degraded_snapshot(self):
        path = self.settings.processed_dir / 'report.json'
        original = path.read_bytes()
        for content in (b'{', b'[]', b'null'):
            with self.subTest(content=content):
                path.write_bytes(content)
                self.assert_unready()
        path.write_bytes(original)
        (self.settings.processed_dir / 'chunks.jsonl').unlink()
        self.assert_unready()

    def test_all_four_report_file_hashes_are_checked(self):
        for filename in DATA_FILES:
            with self.subTest(filename=filename):
                path = self.settings.processed_dir / filename
                original = path.read_bytes()
                path.write_bytes(original + b' ')
                self.assert_unready()
                path.write_bytes(original)

    def test_dataset_version_is_recomputed(self):
        path = self.settings.processed_dir / 'report.json'
        report = read_json(path)
        report['dataset_version'] = '0' * 16
        write_json(path, report)
        self.assert_unready()

    def test_valid_hash_does_not_bypass_chunk_metadata_validation(self):
        path = self.settings.processed_dir / 'chunks.jsonl'
        original = [json.loads(line) for line in path.read_text('utf-8').splitlines()]
        mutations = {
            'duplicate_id': lambda chunks: chunks[1].update(chunk_id=chunks[0]['chunk_id']),
            'mixed_version': lambda chunks: chunks[0].update(dataset_version='wrong'),
            'wrong_source_hash': lambda chunks: chunks[0].update(source_sha256='0' * 64),
            'wrong_source_file': lambda chunks: chunks[0].update(source_file='other.pdf'),
            'chapter_outside_course': lambda chunks: chunks[0].update(chapter_id='ch13'),
            'wrong_text': lambda chunks: chunks[0].update(text='invented'),
            'wrong_page': lambda chunks: chunks[0].update(page_start=999, page_end=999),
            'wrong_offset': lambda chunks: chunks[0].update(char_start=-1),
            'mismatched_section': lambda chunks: chunks[0].update(section_id='ch02-s001'),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                chunks = json.loads(json.dumps(original))
                mutate(chunks)
                write_jsonl(path, chunks)
                self.update_hash('chunks.jsonl')
                self.assert_unready()

    def test_report_counts_and_course_limit_are_checked(self):
        path = self.settings.processed_dir / 'report.json'
        original = read_json(path)
        for field in ('included_pages', 'chapter_count', 'section_count', 'chunk_count',
                      'text_chars', 'course_chapter_limit'):
            with self.subTest(field=field):
                report = dict(original)
                report[field] += 1
                write_json(path, report)
                self.assert_unready()

    def test_source_hash_is_verified_and_cache_invalidates_after_change(self):
        self.assertTrue(self.repo.source_available())
        self.settings.source_pdf.write_bytes(b'%PDF-1.7 different source')
        self.assert_error(409, 'source_hash_mismatch', self.repo.source_path)
        self.assertFalse(self.repo.source_available())
        self.assertIsNone(self.repo.evidence(self.repo.scoped_chunks()[0]['chunk_id'])['source_url'])
        self.assertTrue(self.repo.status()['ready'])

    def test_missing_source_does_not_disable_text_search(self):
        self.settings.source_pdf.unlink()
        self.assert_error(404, 'source_unavailable', self.repo.source_path)
        self.assertFalse(self.repo.course()['source_available'])
        result = RetrievalService(self.repo, self.settings).search('Agent')
        self.assertTrue(result['citations'])
        self.assertTrue(all(c['source_url'] is None for c in result['citations']))


class BM25Tests(unittest.TestCase):
    def test_tokenizer_is_deterministic_chinese_bigram_and_identifier_aware(self):
        tokens = tokenize('什么是智能体？ get_weather HelloAgentsLLM ＢＭ２５')
        self.assertEqual(tokens, tokenize('什么是智能体？ get_weather HelloAgentsLLM ＢＭ２５'))
        self.assertIn('智能', tokens)
        self.assertIn('能体', tokens)
        self.assertNotIn('什么', tokens)
        for token in ('get_weather', 'get', 'weather', 'helloagentsllm', 'hello', 'agents', 'llm', 'bm25'):
            self.assertIn(token, tokens)
        self.assertEqual(tokenize('the what how 什么'), [])

    def test_score_matches_okapi_bm25_formula_not_keyword_overlap(self):
        chunks = [{'chunk_id': 'a', 'text': 'rare rare common'},
                  {'chunk_id': 'b', 'text': 'rare common extra extra extra'},
                  {'chunk_id': 'c', 'text': 'unrelated'},
                  {'chunk_id': 'd', 'text': 'different'},
                  {'chunk_id': 'e', 'text': 'another'}]
        index = BM25Index(chunks)
        ranked = dict(index.rank(['rare'], {'a', 'b', 'c'}))
        idf = math.log((5 - 2 + 0.5) / (2 + 0.5))
        expected = idf * 2 * 2.5 / (2 + 1.5 * (0.25 + 0.75 * 3 / (11 / 5)))
        self.assertAlmostEqual(ranked['a'], expected)
        self.assertGreater(ranked['a'], ranked['b'])
        self.assertNotIn('c', ranked)
        self.assertEqual(index.rank(['rare'], {'b'}), [('b', ranked['b'])])

    def test_scores_are_delegated_to_rank_bm25_with_query_deduplication(self):
        chunks = [{'chunk_id': str(i), 'text': text} for i, text in enumerate(
            ('rare rare common', 'common', 'other', 'different', 'another'))]
        index = BM25Index(chunks)
        library = BM25Okapi([tokenize(chunk['text']) for chunk in chunks])
        self.assertIsInstance(index._engine, BM25Okapi)
        with patch.object(index._engine, 'get_batch_scores',
                          wraps=index._engine.get_batch_scores) as score:
            ranked = index.rank(['rare', 'rare'], {'0'})
        score.assert_called_once_with(['rare'], [0])
        self.assertAlmostEqual(ranked[0][1], float(library.get_scores(['rare'])[0]))
        self.assertEqual(index.rank(['rare'], {'0'}), ranked)

    def test_empty_vocabulary_and_small_corpus_zero_or_negative_scores(self):
        self.assertEqual(BM25Index([{'chunk_id': 'a', 'text': 'the what how'}]).rank(['x'], {'a'}), [])
        for chunks in ([{'chunk_id': 'a', 'text': 'token'}],
                       [{'chunk_id': 'a', 'text': 'token'}, {'chunk_id': 'b', 'text': 'other'}]):
            with self.subTest(chunks=chunks):
                index = BM25Index(chunks)
                expected = float(index._engine.get_scores(['token'])[0])
                self.assertEqual(index.rank(['token'], set(index.ids)), [('a', expected)])
                self.assertEqual(index.rank(['missing'], set(index.ids)), [])

    def test_reload_reuses_frequencies_without_retokenizing_identifiers(self):
        chunks = [{'chunk_id': 'a', 'text': 'get_weather get_weather'},
                  {'chunk_id': 'b', 'text': 'unrelated'}]
        original = BM25Index(chunks)
        restored = BM25Index(chunks, frequencies=original.frequencies)
        self.assertEqual(original.frequencies, restored.frequencies)
        self.assertEqual(original.rank(['weather'], {'a', 'b'}), restored.rank(['weather'], {'a', 'b'}))

    def test_empty_index_tokens_zero_overlap_and_ties_are_deterministic(self):
        self.assertEqual(BM25Index([]).rank(['x'], set()), [])
        index = BM25Index([{'chunk_id': 'b', 'text': 'token'}, {'chunk_id': 'a', 'text': 'token'}])
        self.assertEqual(index.rank([], {'a', 'b'}), [])
        self.assertEqual(index.rank(['missing'], {'a', 'b'}), [])
        self.assertEqual([item[0] for item in index.rank(['token'], {'a', 'b'})], ['a', 'b'])


class RetrievalTests(CorpusFixtureTest):
    def test_startup_and_default_search_never_call_external_service(self):
        with patch('backend.services.retrieval.httpx.post', side_effect=AssertionError('network')):
            service = RetrievalService(self.repo, self.settings)
            self.assertEqual(service.available_modes(), ['bm25'])
            result = service.search('get_weather', debug=True)
        self.assertFalse(result['insufficient_evidence'])
        self.assertEqual(result['retrieval_mode'], 'bm25')
        self.assertEqual(result['citations'][0]['section_id'], 'ch01-s001')
        self.assertIn('get_weather', result['citations'][0]['text'])
        self.assertEqual(result['debug']['algorithm'], BM25_ALGORITHM)
        self.assertFalse(result['debug']['reranker_applied'])

    def test_scope_and_top_k_are_enforced_before_ranking(self):
        service = RetrievalService(self.repo, self.settings)
        result = service.search('memory', chapter_id='ch02', section_id='ch02-s001', top_k=1)
        self.assertEqual(len(result['citations']), 1)
        self.assertEqual(result['citations'][0]['chapter_id'], 'ch02')
        self.assertGreater(result['citations'][0]['score'], 0)
        self.assertEqual(result['citations'][0]['citation_id'], 1)
        self.assertIsNone(result['debug'])

    def test_zero_overlap_and_stopword_only_questions_return_no_evidence(self):
        service = RetrievalService(self.repo, self.settings)
        for question in ('zzzxqvnomatch', 'the what how'):
            with self.subTest(question=question):
                result = service.search(question)
                self.assertEqual(result['citations'], [])
                self.assertTrue(result['insufficient_evidence'])

    def test_single_generic_overlap_does_not_turn_course_external_question_into_evidence(self):
        service = RetrievalService(self.repo, self.settings)
        questions = ('How does quantum memory enable teleportation?',
                     'How should a university Agent choose a major?')
        for question in questions:
            with self.subTest(question=question):
                result = service.search(question, debug=True)
                self.assertEqual(result['citations'], [])
                self.assertTrue(result['insufficient_evidence'])
                self.assertFalse(result['debug']['evidence_gate']['passed'])

    def test_precise_single_term_and_supported_multi_term_questions_pass_evidence_gate(self):
        service = RetrievalService(self.repo, self.settings)
        for question in ('Agent', 'How does BM25 rank documents?'):
            with self.subTest(question=question):
                result = service.search(question, debug=True)
                self.assertTrue(result['citations'])
                self.assertFalse(result['insufficient_evidence'])
                self.assertTrue(result['debug']['evidence_gate']['passed'])

    def test_evidence_normalization_uses_the_library_idf(self):
        service = RetrievalService(self.repo, self.settings)
        result = service.search('get_weather', debug=True)
        best = service._bm25.rank(tokenize('get_weather'), set(service._bm25.ids))[0][1]
        weight = sum(service._bm25.idf.get(term, 0.0) for term in set(tokenize('get_weather')))
        self.assertAlmostEqual(result['debug']['evidence_gate']['normalized_score'], best / weight, places=6)

    def test_fused_gate_requires_evidence_inside_the_returned_window(self):
        service = RetrievalService(self.repo, self.settings)
        chunks = [{'chunk_id': 'supported', 'text': 'alpha beta gamma delta'},
                  {'chunk_id': 'weak', 'text': 'alpha alpha alpha'}]
        chunks.extend({'chunk_id': f'other-{i:02d}', 'text': f'unrelated{i}'} for i in range(30))
        service._bm25 = BM25Index(chunks)
        question = 'alpha beta gamma delta'
        sparse = service._bm25.rank(tokenize(question), set(service._bm25.ids))
        dense = [('weak', 0.99)] + [(f'other-{i:02d}', 0.9) for i in range(30)]
        dense.append(('supported', 0.8))
        fused = service._fuse_rankings(sparse, dense, top_k=1)
        self.assertEqual([chunk_id for chunk_id, _ in fused[:2]], ['weak', 'supported'])
        self.assertTrue(service._evidence_gate(question, sparse, 'bm25', 1)['passed'])
        narrow = service._evidence_gate(question, fused, 'hybrid', 1)
        self.assertFalse(narrow['passed'], 'BM25-side evidence outside top_k must not release citations')
        self.assertEqual(narrow['best_chunk_coverage'], 0.25)
        self.assertIsNone(narrow['evidence_chunk_id'])
        wide = service._evidence_gate(question, fused, 'hybrid', 2)
        self.assertTrue(wide['passed'])
        self.assertEqual(wide['evidence_chunk_id'], 'supported')
        self.assertEqual(wide['best_chunk_coverage'], 1.0)

    def test_dense_gate_rejects_keywords_scattered_across_chunks(self):
        service = RetrievalService(self.repo, self.settings)
        chunks = [{'chunk_id': str(i), 'text': text} for i, text in enumerate(
            ('alpha', 'beta', 'gamma', 'delta', 'unrelated', 'different'))]
        service._bm25 = BM25Index(chunks)
        # 关键词分散且向量相似度低于阈值时，应当拒答。
        ranked = [(chunk['chunk_id'], 0.30) for chunk in chunks]
        for mode in ('hybrid', 'vector'):
            with self.subTest(mode=mode):
                gate = service._evidence_gate('alpha beta gamma delta', ranked, mode, 5)
                self.assertFalse(gate['passed'])
                self.assertEqual(gate['passed_by'], 'none')
                self.assertEqual(gate['coverage'], 1.0)
                self.assertEqual(gate['best_chunk_coverage'], 0.25)

    def test_dense_gate_accepts_high_vector_score_without_keyword_overlap(self):
        """同义提问即使字面不重合，只要向量相似度达标也应放行。"""
        service = RetrievalService(self.repo, self.settings)
        chunks = [{'chunk_id': 'c1', 'text': '智能体能够感知环境并自主决策'}]
        service._bm25 = BM25Index(chunks)
        gate_vec = service._evidence_gate('AI助手如何自动做事', [('c1', 0.72)], 'vector', 5)
        self.assertTrue(gate_vec['passed'])
        self.assertEqual(gate_vec['passed_by'], 'vector')
        self.assertEqual(gate_vec['evidence_chunk_id'], 'c1')

        gate_hyb = service._evidence_gate(
            'AI助手如何自动做事', [('c1', 0.016)], 'hybrid', 5, vec_score_map={'c1': 0.72}
        )
        self.assertTrue(gate_hyb['passed'])
        self.assertEqual(gate_hyb['passed_by'], 'vector')

    def test_overview_question_returns_representative_chunks(self):
        """问当前资料的整体框架/主要内容时应均匀抽样放行，课程外问题仍拒答。"""
        service = RetrievalService(self.repo, self.settings)
        res_ok = service.search('这份资料的核心概念和整体框架是什么？', mode='bm25', top_k=3, debug=True)
        self.assertFalse(res_ok['insufficient_evidence'])
        self.assertGreater(len(res_ok['citations']), 0)
        self.assertEqual(res_ok['citations'][0]['hit_type'], 'overview')
        self.assertEqual(res_ok['debug']['evidence_gate']['passed_by'], 'overview')

        res_bad = service.search('《红楼梦》的主要内容和人物关系是什么？', mode='bm25', top_k=3, debug=True)
        self.assertTrue(res_bad['insufficient_evidence'])
        self.assertEqual(res_bad['citations'], [])

    def test_dense_gate_accepts_cohesive_evidence_below_lexical_best(self):
        service = RetrievalService(self.repo, self.settings)
        terms = [f'term{chr(97 + i)}' for i in range(10)]
        chunks = [{'chunk_id': 'repeated', 'text': ' '.join(terms[:4] * 10)},
                  {'chunk_id': 'cohesive', 'text': ' '.join(terms[4:] * 2 + ['padding'] * 28)}]
        chunks.extend({'chunk_id': f'other-{i:02d}', 'text': ' '.join(['padding'] * 40)}
                      for i in range(40))
        service._bm25 = BM25Index(chunks)
        question = ' '.join(terms)
        lexical = service._bm25.rank(tokenize(question), {'repeated', 'cohesive'})
        self.assertEqual([chunk_id for chunk_id, _ in lexical], ['repeated', 'cohesive'])
        self.assertFalse(service._evidence_gate(question, lexical, 'bm25', 2)['passed'])
        for mode in ('hybrid', 'vector'):
            with self.subTest(mode=mode):
                gate = service._evidence_gate(question, [('repeated', 0.99), ('cohesive', 0.8)], mode, 2)
                self.assertTrue(gate['passed'])
                self.assertEqual(gate['evidence_chunk_id'], 'cohesive')
                self.assertEqual(gate['best_chunk_coverage'], 0.6)

    def test_unconfigured_optional_modes_return_503_without_synthetic_vectors(self):
        with patch('backend.services.retrieval.httpx.post', side_effect=AssertionError('network')):
            service = RetrievalService(self.repo, self.settings)
            for mode in ('vector', 'hybrid'):
                self.assert_error(503, 'vector_index_not_ready', lambda: service.search('Agent', mode=mode))

    def test_invalid_service_inputs_and_scope_errors(self):
        service = RetrievalService(self.repo, self.settings)
        for question in ('', '  ', 'x' * 2001, None):
            self.assert_error(422, 'invalid_question', lambda: service.search(question))
        for options in ({'mode': 'fake'}, {'top_k': 0}, {'top_k': 21}, {'top_k': True}):
            self.assert_error(422, 'invalid_retrieval_options', lambda: service.search('Agent', **options))
        self.assert_error(404, 'section_not_found',
                          lambda: service.search('memory', 'ch02', 'ch01-s001'))


class EmbeddingFixtureTest(CorpusFixtureTest):
    def setUp(self):
        super().setUp()
        self.config = replace(self.settings, embedding_base_url='https://fixture.invalid/v1',
                              embedding_model='fixture-embedding', embedding_api_key='fixture-secret')

    def use_transport(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        mocked = patch('backend.services.retrieval.httpx.post', side_effect=transport_post(client))
        self.addCleanup(mocked.stop)
        return mocked.start()


class EmbeddingTests(EmbeddingFixtureTest):
    def test_loopback_requests_bypass_system_proxy_but_remote_requests_keep_it(self):
        cases = [('http://127.0.0.1:8100/v1', False), ('http://localhost:8100/v1', False),
                 ('http://[::1]:8100/v1', False), ('https://fixture.invalid/v1', True)]
        for base, expected in cases:
            with self.subTest(base=base):
                config = replace(self.config, embedding_base_url=base)
                response = httpx.Response(200, request=httpx.Request('POST', base + '/embeddings'),
                                          json={'data': [{'index': 0, 'embedding': [1, 0]}]})
                with patch('backend.services.retrieval.httpx.post', return_value=response) as mocked:
                    self.assertEqual(fetch_embeddings(config, ['text']), [[1.0, 0.0]])
                    self.assertEqual(mocked.call_args.kwargs['trust_env'], expected)

    def test_request_shape_normalization_and_out_of_order_response(self):
        requests = []
        def handler(request):
            requests.append(request)
            self.assertEqual(str(request.url), 'https://fixture.invalid/v1/embeddings')
            self.assertEqual(request.headers['authorization'], 'Bearer fixture-secret')
            self.assertEqual(json.loads(request.content), {
                'model': 'fixture-embedding', 'input': ['first', 'second']})
            return httpx.Response(200, json={'data': [
                {'index': 1, 'embedding': [0, 2]}, {'index': 0, 'embedding': [3, 4]}]})
        self.use_transport(handler)
        self.assertEqual(fetch_embeddings(self.config, ['first', 'second']), [[0.6, 0.8], [0.0, 1.0]])
        self.assertEqual(len(requests), 1)

    def test_endpoint_validation_and_fingerprint_include_model_not_key(self):
        self.assertEqual(embedding_endpoint(replace(self.config, embedding_base_url='https://fixture.invalid/v1/')),
                         'https://fixture.invalid/v1/embeddings')
        self.assertEqual(embedding_fingerprint(self.config),
                         embedding_fingerprint(replace(self.config, embedding_api_key='changed')))
        self.assertNotEqual(embedding_fingerprint(self.config),
                            embedding_fingerprint(replace(self.config, embedding_model='changed')))
        for base in ('', 'file:///etc/passwd', 'https://u:secret@fixture.invalid',
                     'https://fixture.invalid?key=secret', 'https://fixture.invalid/#fragment',
                     'http://[bad', 'https://fixture.invalid:bad', 'https://fixture.invalid:99999',
                     'https://fixture.invalid:0', 'https://bad host/v1'):
            self.assert_error(503, 'embedding_not_configured',
                              lambda: embedding_endpoint(replace(self.config, embedding_base_url=base)))
        self.assert_error(503, 'embedding_not_configured',
                          lambda: embedding_endpoint(replace(self.config, embedding_model=' ')))

    def test_timeout_and_http_failure_are_mapped_without_upstream_details(self):
        def timeout(request):
            raise httpx.ReadTimeout('fixture-secret internal body', request=request)
        with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
            with patch('backend.services.retrieval.httpx.post', side_effect=transport_post(client)):
                error = self.assert_error(504, 'embedding_timeout',
                                          lambda: fetch_embeddings(self.config, ['text']))
                self.assertNotIn('fixture-secret', error.message)
        for status in (302, 401, 429, 500):
            with self.subTest(status=status):
                with httpx.Client(transport=httpx.MockTransport(
                        lambda request: httpx.Response(status, text='fixture-secret internal body'))) as client:
                    with patch('backend.services.retrieval.httpx.post', side_effect=transport_post(client)):
                        error = self.assert_error(502, 'embedding_upstream_error',
                                                  lambda: fetch_embeddings(self.config, ['text']))
                        self.assertNotIn('fixture-secret', error.message)
                        self.assertNotIn('internal', error.message)

    def test_malformed_embedding_payloads_are_rejected(self):
        payloads = [None, {}, {'data': []}, {'data': [{'index': 1, 'embedding': [1, 0]}]},
                    {'data': [{'index': True, 'embedding': [1, 0]}]},
                    {'data': [{'index': 0, 'embedding': [0, 0]}]},
                    {'data': [{'index': 0, 'embedding': [True, 0]}]},
                    {'data': [{'index': 0, 'embedding': [10 ** 400, 1]}]},
                    {'data': [{'index': 0, 'embedding': ['1', 0]}]},
                    {'data': [{'index': 0, 'embedding': []}]},
                    {'data': [{'index': 0, 'embedding': [1] * 8193}]}]
        for payload in payloads:
            with self.subTest(payload_type=type(payload).__name__):
                with httpx.Client(transport=httpx.MockTransport(
                        lambda request: httpx.Response(200, json=payload))) as client:
                    with patch('backend.services.retrieval.httpx.post', side_effect=transport_post(client)):
                        self.assert_error(502, 'embedding_invalid_response',
                                          lambda: fetch_embeddings(self.config, ['text']))
        for body in ('not-json', '{"data":[{"index":0,"embedding":[NaN,1]}]}'):
            with httpx.Client(transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, text=body))) as client:
                with patch('backend.services.retrieval.httpx.post', side_effect=transport_post(client)):
                    self.assert_error(502, 'embedding_invalid_response',
                                      lambda: fetch_embeddings(self.config, ['text']))

    def test_duplicate_indices_or_mixed_dimensions_are_rejected(self):
        for data in ([{'index': 0, 'embedding': [1, 0]}, {'index': 0, 'embedding': [0, 1]}],
                     [{'index': 0, 'embedding': [1, 0]}, {'index': 1, 'embedding': [0, 1, 0]}]):
            with httpx.Client(transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json={'data': data}))) as client:
                with patch('backend.services.retrieval.httpx.post', side_effect=transport_post(client)):
                    self.assert_error(502, 'embedding_invalid_response',
                                      lambda: fetch_embeddings(self.config, ['one', 'two']))

    def test_nonfinite_vector_values_are_rejected(self):
        for value in (float('nan'), float('inf'), -float('inf'), 10 ** 400):
            with self.assertRaises(ValueError):
                normalized_vector([value, 1])


class IndexTests(EmbeddingFixtureTest):
    def test_offline_cli_build_and_overwrite_error(self):
        command = [sys.executable, '-X', 'utf8', '-m', 'pipeline.build_index', '--processed-dir',
                   str(self.settings.processed_dir), '--output', str(self.settings.index_dir)]
        completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                   cwd=Path(__file__).resolve().parents[1], timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['dataset_version'], self.repo.dataset_version)
        completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                   cwd=Path(__file__).resolve().parents[1], timeout=30)
        self.assertEqual(completed.returncode, 2)
        self.assertIn('--force', completed.stderr)

    def test_offline_bm25_manifest_hashes_and_reload(self):
        with patch('backend.services.retrieval.httpx.post', side_effect=AssertionError('network')):
            result = build_indexes(self.settings.processed_dir / 'chunks.jsonl',
                                   self.settings.index_dir, settings=self.settings)
            self.assertEqual(result['modes'], ['bm25'])
            manifest = read_json(self.settings.index_dir / 'manifest.json')
            self.assertEqual(manifest['dataset_version'], self.repo.dataset_version)
            self.assertEqual(manifest['chunk_count'], self.repo.status()['chunk_count'])
            for filename, digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256((self.settings.index_dir / filename).read_bytes()).hexdigest(), digest)
            sparse = read_index_file(self.settings.index_dir, manifest, 'bm25.index.json')
            self.assertEqual(sparse['algorithm'], BM25_ALGORITHM)
            self.assertEqual(sparse['backend_version'], BM25_BACKEND_VERSION)
            self.assertEqual(sparse['epsilon'], 0.25)
            service = RetrievalService(self.repo, self.settings)
            self.assertTrue(service.search('BM25')['citations'])
            self.assertEqual(service._bm25.frequencies, BM25Index(self.repo.scoped_chunks()).frequencies)

    def test_index_overwrite_and_output_separation_protect_artifacts(self):
        source = self.settings.processed_dir / 'chunks.jsonl'
        for output in (source.parent, source.parent / 'indexes', source.parent.parent):
            with self.assertRaises(ValueError):
                build_indexes(source, output, settings=self.settings)
        build_indexes(source, self.settings.index_dir, settings=self.settings)
        with self.assertRaises(FileExistsError):
            build_indexes(source, self.settings.index_dir, settings=self.settings)
        self.assertEqual(build_indexes(source, self.settings.index_dir, settings=self.settings,
                                       force=True)['modes'], ['bm25'])
        for options in ({'mode': 'fake'}, {'batch_size': 0}, {'batch_size': 129}, {'batch_size': True}):
            with self.assertRaises(ValueError):
                build_indexes(source, self.settings.index_dir, settings=self.settings, force=True, **options)

    def test_bad_sparse_hash_falls_back_to_validated_in_memory_bm25(self):
        build_indexes(self.settings.processed_dir / 'chunks.jsonl', self.settings.index_dir,
                      settings=self.settings)
        path = self.settings.index_dir / 'bm25.index.json'
        path.write_bytes(path.read_bytes() + b' ')
        service = RetrievalService(self.repo, self.settings)
        self.assertEqual(service.available_modes(), ['bm25'])
        self.assertTrue(service.search('BM25')['citations'])

    def test_legacy_or_mismatched_sparse_backend_is_not_loaded(self):
        build_indexes(self.settings.processed_dir / 'chunks.jsonl', self.settings.index_dir,
                      settings=self.settings)
        path = self.settings.index_dir / 'bm25.index.json'
        manifest_path = self.settings.index_dir / 'manifest.json'
        payload = read_json(path)
        manifest = read_json(manifest_path)
        cases = [('algorithm', 'okapi_bm25'), ('backend_version', '0.0.0'), ('epsilon', 1.0)]
        cases.extend((field, None) for field in payload)
        for field, value in cases:
            with self.subTest(field=field):
                path.write_text(json.dumps(dict(payload, **{field: value})), encoding='utf-8')
                manifest['files']['bm25.index.json'] = hashlib.sha256(path.read_bytes()).hexdigest()
                manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
                with patch('backend.services.retrieval.BM25Index', wraps=BM25Index) as constructor:
                    service = RetrievalService(self.repo, self.settings)
                self.assertEqual(constructor.call_count, 1)
                self.assertTrue(service.search('BM25')['citations'])

    def test_sparse_additional_metadata_does_not_change_ranking(self):
        build_indexes(self.settings.processed_dir / 'chunks.jsonl', self.settings.index_dir,
                      settings=self.settings)
        expected = RetrievalService(self.repo, self.settings).search('BM25', debug=True)
        path = self.settings.index_dir / 'bm25.index.json'
        payload = read_json(path)
        payload['description'] = '允许保留额外的索引说明。'
        write_json(path, payload)
        manifest_path = self.settings.index_dir / 'manifest.json'
        manifest = read_json(manifest_path)
        manifest['files']['bm25.index.json'] = hashlib.sha256(path.read_bytes()).hexdigest()
        write_json(manifest_path, manifest)
        with patch('backend.services.retrieval.BM25Index', wraps=BM25Index) as constructor:
            service = RetrievalService(self.repo, self.settings)
        self.assertEqual(constructor.call_count, 2)
        self.assertEqual(service.search('BM25', debug=True), expected)

    def dense_handler(self, request):
        payload = json.loads(request.content)
        def vector(text):
            low = text.lower()
            # 课程外无关问题给单独维度，使其与教材片段仅有极低正相似度。
            if ('zzzxqv' in low or 'the what how' in low
                    or 'teleportation' in low or 'university' in low):
                return [0.1, 0.1, 0.1, 0.98]
            if 'memory' in low:
                return [0, 1, 0, 0]
            if 'BM25' in text or 'Retrieval' in text:
                return [1, 0, 0, 0]
            return [0.2, 0.2, 0.96, 0]
        return httpx.Response(200, json={'data': [
            {'index': index, 'embedding': vector(text)}
            for index, text in reversed(list(enumerate(payload['input'])))]})

    def build_dense(self):
        return build_indexes(self.config.processed_dir / 'chunks.jsonl', self.config.index_dir,
                             settings=self.config, mode='hybrid', batch_size=2)

    def test_vector_and_rrf_search_use_version_matched_offline_embeddings(self):
        mocked = self.use_transport(self.dense_handler)
        result = self.build_dense()
        self.assertEqual(result['modes'], ['bm25', 'vector', 'hybrid'])
        self.assertGreater(mocked.call_count, 1)
        before = mocked.call_count
        service = RetrievalService(self.repo, self.config)
        self.assertEqual(mocked.call_count, before, 'startup must only read offline artifacts')
        self.assertEqual(service.available_modes(), ['bm25', 'vector', 'hybrid'])
        sparse = service.search('BM25', top_k=20)
        dense = service.search('BM25', top_k=20, mode='vector', debug=True)
        hybrid = service.search('BM25', top_k=20, mode='hybrid', debug=True)
        self.assertEqual(dense['debug']['algorithm'], 'cosine')
        self.assertEqual(hybrid['debug']['algorithm'], 'rrf_k60')
        expected = Counter()
        for response in (sparse, dense):
            for rank, citation in enumerate(response['citations'], 1):
                expected[citation['chunk_id']] += 1 / (60 + rank)
        expected_ids = sorted(expected, key=lambda chunk_id: (-expected[chunk_id], chunk_id))
        self.assertEqual([c['chunk_id'] for c in hybrid['citations']], expected_ids)
        for number, citation in enumerate(hybrid['citations'], 1):
            self.assertEqual(citation['citation_id'], number)
            self.assertAlmostEqual(citation['score'], expected[citation['chunk_id']], places=7)
        scoped = service.search('memory', chapter_id='ch02', mode='vector')
        self.assertTrue(scoped['citations'])
        self.assertTrue(all(c['chapter_id'] == 'ch02' for c in scoped['citations']))

    def test_dense_modes_abstain_despite_positive_vector_candidates(self):
        self.use_transport(self.dense_handler)
        self.build_dense()
        service = RetrievalService(self.repo, self.config)
        questions = ('zzzxqvnomatch', 'the what how',
                     'How does quantum memory enable teleportation?',
                     'How should a university Agent choose a major?')
        for mode in ('hybrid', 'vector'):
            for question in questions:
                with self.subTest(mode=mode, question=question):
                    result = service.search(question, mode=mode, debug=True)
                    self.assertGreater(result['debug']['vector_candidates'], 0)
                    self.assertTrue(result['insufficient_evidence'])
                    self.assertEqual(result['citations'], [])
                    gate = result['debug']['evidence_gate']
                    self.assertFalse(gate['passed'])
                    self.assertEqual(gate['gate_version'], 'hybrid-vector-bm25-gate-v2')

    def test_dense_modes_pass_supported_questions_using_lexical_not_fused_scores(self):
        self.use_transport(self.dense_handler)
        self.build_dense()
        service = RetrievalService(self.repo, self.config)
        for mode in ('hybrid', 'vector'):
            for question in ('Agent', 'How does BM25 rank documents?'):
                with self.subTest(mode=mode, question=question):
                    result = service.search(question, mode=mode, top_k=20, debug=True)
                    self.assertFalse(result['insufficient_evidence'])
                    gate = result['debug']['evidence_gate']
                    self.assertTrue(gate['passed'])
                    returned_ids = {citation['chunk_id'] for citation in result['citations']}
                    self.assertIn(gate['evidence_chunk_id'], returned_ids)
                    lexical = service._bm25.rank(tokenize(question), returned_ids)
                    expected = service._evidence_gate(question, lexical, 'bm25', 20)
                    self.assertEqual(gate['normalized_score'], expected['normalized_score'])
                    self.assertEqual(gate['best_chunk_coverage'], expected['best_chunk_coverage'])
                    self.assertEqual(gate['evidence_chunk_id'], lexical[0][0])
                    if mode == 'hybrid':
                        self.assertLess(result['citations'][0]['score'], 0.04)
                        self.assertGreaterEqual(gate['normalized_score'], 0.7)

    def test_dense_evidence_cannot_leak_from_outside_the_requested_scope(self):
        self.use_transport(self.dense_handler)
        self.build_dense()
        service = RetrievalService(self.repo, self.config)
        for mode in ('hybrid', 'vector'):
            with self.subTest(mode=mode):
                self.assertTrue(service.search('BM25', mode=mode, top_k=20)['citations'])
                result = service.search('BM25', chapter_id='ch02', mode=mode, debug=True)
                self.assertGreater(result['debug']['vector_candidates'], 0)
                self.assertEqual(result['citations'], [])
                self.assertTrue(result['insufficient_evidence'])

    def test_vector_index_rejects_changed_model_corpus_version_or_hash(self):
        self.use_transport(self.dense_handler)
        self.build_dense()
        changed = replace(self.config, embedding_model='different-model')
        service = RetrievalService(self.repo, changed)
        self.assertEqual(service.available_modes(), ['bm25'])
        self.assert_error(503, 'vector_index_not_ready', lambda: service.search('BM25', mode='vector'))
        manifest_path = self.settings.index_dir / 'manifest.json'
        original = manifest_path.read_bytes()
        manifest = read_json(manifest_path)
        manifest['dataset_version'] = 'stale'
        write_json(manifest_path, manifest)
        self.assertEqual(RetrievalService(self.repo, self.config).available_modes(), ['bm25'])
        manifest_path.write_bytes(original)
        dense_path = self.settings.index_dir / 'vector.index.json'
        dense_path.write_bytes(dense_path.read_bytes() + b' ')
        self.assertEqual(RetrievalService(self.repo, self.config).available_modes(), ['bm25'])

    def test_valid_hash_does_not_bypass_vector_dimension_validation(self):
        self.use_transport(self.dense_handler)
        self.build_dense()
        path = self.settings.index_dir / 'vector.index.json'
        payload = read_json(path)
        payload['vectors'][0] = [0, 0]
        write_json(path, payload)
        manifest_path = self.settings.index_dir / 'manifest.json'
        manifest = read_json(manifest_path)
        manifest['files']['vector.index.json'] = hashlib.sha256(path.read_bytes()).hexdigest()
        write_json(manifest_path, manifest)
        self.assertEqual(RetrievalService(self.repo, self.config).available_modes(), ['bm25'])

    def test_query_dimension_mismatch_maps_to_502(self):
        self.use_transport(self.dense_handler)
        self.build_dense()
        service = RetrievalService(self.repo, self.config)
        with patch('backend.services.retrieval.fetch_embeddings', return_value=[[1, 0, 0]]):
            self.assert_error(502, 'embedding_dimension_mismatch',
                              lambda: service.search('BM25', mode='vector'))

    def test_failed_dense_build_does_not_publish_partial_artifacts(self):
        with patch('pipeline.build_index.fetch_embeddings',
                   side_effect=AppError(504, 'embedding_timeout', 'timeout')):
            self.assert_error(504, 'embedding_timeout', self.build_dense)
        self.assertFalse((self.settings.index_dir / 'manifest.json').exists())
        self.assertFalse((self.settings.index_dir / 'bm25.index.json').exists())

    def test_dense_build_detects_cross_batch_dimension_change(self):
        with patch('pipeline.build_index.fetch_embeddings', side_effect=[
                [[1, 0], [0, 1]], [[1, 0, 0], [0, 1, 0]]]):
            self.assert_error(502, 'embedding_dimension_mismatch', self.build_dense)
        self.assertFalse((self.settings.index_dir / 'manifest.json').exists())


if __name__ == '__main__':
    unittest.main()

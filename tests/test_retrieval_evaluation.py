"""检索效果评测工具测试：功能测试与效果指标分开报告。"""
from contextlib import redirect_stdout
from dataclasses import replace
import json
import hashlib
import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend.services.corpus import CorpusRepository
from backend.services.retrieval import RetrievalService
from corpus_fixture import make_corpus
from pipeline.build_index import build_indexes
from tools.evaluate_retrieval import evaluate_cases, load_cases, main

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RetrievalEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(TemporaryDirectory())
        self.settings = make_corpus(Path(self.temp))
        self.repo = CorpusRepository(self.settings)
        self.service = RetrievalService(self.repo, self.settings)

    def cases(self):
        version = self.repo.dataset_version
        return [
            {'case_id': 'agent', 'dataset_version': version, 'split': 'validation',
             'question': 'What is an Agent?', 'answerable': True,
             'expected_section_ids': ['ch01-s001']},
            {'case_id': 'retrieval', 'dataset_version': version, 'split': 'holdout',
             'question': 'How does BM25 rank documents?', 'answerable': True,
             'expected_section_ids': ['ch01-s002']},
            {'case_id': 'outside', 'dataset_version': version, 'split': 'holdout',
             'question': 'zzzxqv unrelated astronomy', 'answerable': False,
             'expected_section_ids': []},
        ]

    def test_metrics_are_computed_per_split_and_keep_raw_case_results(self):
        report = evaluate_cases(self.service, self.repo, self.cases(), mode='bm25', top_ks=(1, 5))
        self.assertEqual(report['case_count'], 3)
        self.assertEqual(report['metrics']['answerable_count'], 2)
        self.assertEqual(report['metrics']['unanswerable_count'], 1)
        self.assertEqual(report['metrics']['recall_at_1'], 1.0)
        self.assertEqual(report['metrics']['mrr_at_5'], 1.0)
        self.assertEqual(report['metrics']['abstained_count'], 1)
        self.assertEqual(report['metrics']['citation_valid_count'], 2)
        self.assertEqual(set(report['splits']), {'validation', 'holdout'})
        self.assertEqual(len(report['cases']), 3)

    def test_case_loader_rejects_duplicate_or_wrong_version_records(self):
        path = Path(self.temp) / 'cases.jsonl'
        rows = self.cases()
        path.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
        self.assertEqual(len(load_cases(path, self.repo.dataset_version)), 3)
        path.write_text('\n'.join(json.dumps(row) for row in [rows[0], rows[0]]), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_cases(path, self.repo.dataset_version)
        wrong = dict(rows[0], dataset_version='stale')
        path.write_text(json.dumps(wrong), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_cases(path, self.repo.dataset_version)

    def test_frozen_seed_set_covers_all_chapters_without_modifying_source(self):
        path = PROJECT_ROOT / 'data/evaluation/hello-agents-v1/cases.jsonl'
        original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        rows = load_cases(path, 'caeb372d8f756b87')
        answerable = [row for row in rows if row['answerable']]
        chapters = {section.split('-')[0] for row in answerable
                    for section in row['expected_section_ids']}
        self.assertEqual(len(rows), 20)
        self.assertEqual(len(answerable), 14)
        self.assertEqual(len(rows) - len(answerable), 6)
        self.assertEqual(chapters, {f'ch{number:02d}' for number in range(1, 13)})
        self.assertEqual({row['split'] for row in rows}, {'calibration', 'regression'})
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), original_hash)

    def test_cli_records_inputs_code_and_gate_for_reproduction(self):
        cases_path = Path(self.temp) / 'cli-cases.jsonl'
        output_path = Path(self.temp) / 'report.json'
        cases_path.write_text('\n'.join(json.dumps(row) for row in self.cases()), encoding='utf-8')
        arguments = ['evaluate_retrieval', '--cases', str(cases_path),
                     '--processed-dir', str(self.settings.processed_dir),
                     '--index-dir', str(self.settings.index_dir), '--output', str(output_path)]
        with patch('sys.argv', arguments), redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)
        report = json.loads(output_path.read_text('utf-8'))
        metadata = report['reproducibility']
        self.assertEqual(metadata['cases_sha256'],
                         hashlib.sha256(cases_path.read_bytes()).hexdigest())
        self.assertEqual(metadata['evidence_gate_version'], 'rank-bm25-cohesive-evidence-v2')
        self.assertEqual(metadata['evidence_min_chunk_coverage'], 0.5)
        self.assertEqual(metadata['evidence_min_normalized_score'], 0.7)
        self.assertIsNotNone(metadata['evaluator_sha256'])
        self.assertIsNotNone(metadata['retrieval_source_sha256'])

    def test_rank_bm25_sample_cases_are_versioned_and_cover_answerability(self):
        path = PROJECT_ROOT / 'data/evaluation/hello-agents-rank-bm25-sample/cases.jsonl'
        rows = load_cases(path, 'ba0e75f4bc5dcdf1')
        self.assertEqual(len(rows), 8)
        self.assertEqual(sum(row['answerable'] for row in rows), 5)
        self.assertEqual({section for row in rows for section in row['expected_section_ids']},
                         {'ch01-s001', 'ch01-s002', 'ch01-s003'})
        self.assertTrue(any(row.get('section_id') == 'ch01-s002' for row in rows))

    def test_cli_reads_embedding_environment_and_explicit_paths_take_priority(self):
        settings = replace(self.settings, embedding_base_url='http://localhost:5678/v1',
                           embedding_model='test-embedding', embedding_api_key='test-only')
        with patch('pipeline.build_index.fetch_embeddings',
                   side_effect=lambda config, texts: [[1.0, 0.0] for text in texts]):
            build_indexes(settings.processed_dir / 'chunks.jsonl', settings.index_dir,
                          mode='vector', settings=settings)
        cases_path = Path(self.temp) / 'env-cases.jsonl'
        output_path = Path(self.temp) / 'env-report.json'
        cases_path.write_text('\n'.join(json.dumps(row) for row in self.cases()), encoding='utf-8')
        environment = {
            'PROCESSED_DIR': str(Path(self.temp) / 'missing'),
            'INDEX_DIR': str(Path(self.temp) / 'missing-index'),
            'EMBEDDING_BASE_URL': settings.embedding_base_url,
            'EMBEDDING_MODEL': settings.embedding_model,
            'EMBEDDING_API_KEY': settings.embedding_api_key,
            'MODEL_TIMEOUT': '12.5',
        }

        def embeddings(config, texts):
            self.assertEqual(config.embedding_base_url, settings.embedding_base_url)
            self.assertEqual(config.embedding_model, settings.embedding_model)
            self.assertEqual(config.embedding_api_key, settings.embedding_api_key)
            self.assertEqual(config.model_timeout, 12.5)
            return [[1.0, 0.0] for text in texts]

        arguments = ['evaluate_retrieval', '--cases', str(cases_path), '--mode', 'hybrid',
                     '--processed-dir', str(settings.processed_dir),
                     '--index-dir', str(settings.index_dir), '--output', str(output_path)]
        with patch.dict(os.environ, environment, clear=True), patch('sys.argv', arguments), \
                patch('backend.services.retrieval.fetch_embeddings', side_effect=embeddings), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)
        report = json.loads(output_path.read_text('utf-8'))
        self.assertEqual(report['retrieval_mode'], 'hybrid')
        self.assertEqual(report['case_count'], 3)
        self.assertEqual(report['reproducibility']['evidence_gate_version'],
                         'hybrid-vector-bm25-gate-v2')
        self.assertEqual(report['reproducibility']['evidence_min_chunk_coverage'], 0.5)
        self.assertEqual(report['reproducibility']['evidence_min_normalized_score'], 0.7)

    def test_cli_uses_environment_paths_but_keeps_bm25_default_mode(self):
        cases_path = Path(self.temp) / 'env-path-cases.jsonl'
        output_path = Path(self.temp) / 'env-path-report.json'
        cases_path.write_text('\n'.join(json.dumps(row) for row in self.cases()), encoding='utf-8')
        environment = {'PROCESSED_DIR': str(self.settings.processed_dir),
                       'INDEX_DIR': str(self.settings.index_dir),
                       'DEFAULT_RETRIEVAL_MODE': 'hybrid'}
        arguments = ['evaluate_retrieval', '--cases', str(cases_path), '--output', str(output_path)]
        with patch.dict(os.environ, environment, clear=True), patch('sys.argv', arguments), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)
        report = json.loads(output_path.read_text('utf-8'))
        self.assertEqual(report['retrieval_mode'], 'bm25')
        self.assertEqual(report['dataset_version'], self.repo.dataset_version)
        self.assertEqual(report['reproducibility']['processed_report_sha256'],
                         hashlib.sha256((self.settings.processed_dir / 'report.json').read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()

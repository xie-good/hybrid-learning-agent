"""配置默认值、环境读取、参数校验及生产入口的回归测试。"""
from contextlib import redirect_stdout
from dataclasses import asdict, fields, replace
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend.config import DATA_DIR, PROJECT_ROOT, Settings, should_trust_env
from backend.main import create_app
from pipeline.build_index import build_indexes, main
from tests.corpus_fixture import make_corpus


class SettingsTests(unittest.TestCase):
    """默认对象不读取环境，环境工厂显式转换并校验配置。"""

    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))

    def test_constructor_is_independent_of_environment(self):
        os.environ.update(GENERATION_MODE='llm', DEFAULT_RETRIEVAL_MODE='bm25', MODEL_TIMEOUT='12')
        config = Settings()
        self.assertEqual(config.generation_mode, 'extractive')
        self.assertEqual(config.default_retrieval_mode, 'hybrid')
        self.assertEqual(config.model_timeout, 30)

    def test_defaults_match_environment_factory_without_overrides(self):
        config = Settings.from_env()
        self.assertEqual(asdict(config), asdict(Settings()))
        self.assertEqual(config.default_retrieval_mode, 'hybrid')
        self.assertEqual(len(fields(config)), 14)
        self.assertEqual(config.processed_dir, DATA_DIR / 'processed/hello-agents')
        self.assertEqual(config.database_path, DATA_DIR / 'runtime/history.sqlite3')
        self.assertEqual(config.index_dir, DATA_DIR / 'indexes/hello-agents')
        self.assertIsNone(config.source_pdf)
        self.assertEqual(config.cors_origins, ('http://127.0.0.1:8501', 'http://localhost:8501'))

    def test_environment_factory_reads_every_field(self):
        os.environ.update(
            PROCESSED_DIR='custom/processed', DATABASE_PATH='custom/history.sqlite3',
            INDEX_DIR='custom/indexes', SOURCE_PDF='custom/book.pdf', GENERATION_MODE='llm',
            LLM_BASE_URL='http://localhost:1234/v1', LLM_MODEL='chat-test', LLM_API_KEY='test-only',
            MODEL_TIMEOUT='12.5', EMBEDDING_BASE_URL='http://localhost:5678/v1',
            EMBEDDING_MODEL='embedding-test', EMBEDDING_API_KEY='test-only',
            DEFAULT_RETRIEVAL_MODE='hybrid', CORS_ORIGINS=' https://a.test, ,https://b.test, ')
        config = Settings.from_env()
        self.assertEqual(asdict(config), {
            'processed_dir': (PROJECT_ROOT / 'custom/processed').resolve(),
            'database_path': (PROJECT_ROOT / 'custom/history.sqlite3').resolve(),
            'index_dir': (PROJECT_ROOT / 'custom/indexes').resolve(),
            'source_pdf': (PROJECT_ROOT / 'custom/book.pdf').resolve(),
            'generation_mode': 'llm', 'llm_base_url': 'http://localhost:1234/v1',
            'llm_model': 'chat-test', 'llm_api_key': 'test-only', 'model_timeout': 12.5,
            'embedding_base_url': 'http://localhost:5678/v1', 'embedding_model': 'embedding-test',
            'embedding_api_key': 'test-only', 'default_retrieval_mode': 'hybrid',
            'cors_origins': ('https://a.test', 'https://b.test'),
        })

    def test_environment_is_read_at_each_factory_call(self):
        os.environ['MODEL_TIMEOUT'] = '10'
        first = Settings.from_env()
        os.environ['MODEL_TIMEOUT'] = '20'
        second = Settings.from_env()
        self.assertEqual((first.model_timeout, second.model_timeout), (10, 20))

    def test_environment_can_override_hybrid_default_for_evaluation(self):
        for mode in ('bm25', 'vector', 'hybrid'):
            with self.subTest(mode=mode), patch.dict(os.environ, DEFAULT_RETRIEVAL_MODE=mode):
                self.assertEqual(Settings.from_env().default_retrieval_mode, mode)

    def test_dotenv_loads_once_and_process_environment_takes_priority(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'backend').mkdir()
            (root / 'backend/__init__.py').write_text('', encoding='utf-8')
            shutil.copy2(PROJECT_ROOT / 'backend/config.py', root / 'backend/config.py')
            (root / '.env').write_text('MODEL_TIMEOUT=11\nGENERATION_MODE=llm\n', encoding='utf-8')
            script = (
                'import json; from pathlib import Path; from backend.config import Settings; '
                'first = Settings.from_env(); '
                'Path(".env").write_text("MODEL_TIMEOUT=33\\nGENERATION_MODE=extractive\\n"); '
                'second = Settings.from_env(); '
                'print(json.dumps([first.model_timeout, second.model_timeout, '
                'first.generation_mode, second.generation_mode]))'
            )
            result = subprocess.run([sys.executable, '-B', '-c', script], cwd=root,
                                    env={**os.environ, 'MODEL_TIMEOUT': '22'},
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [22, 22, 'llm', 'llm'])

    def test_empty_paths_use_defaults_and_empty_source_stays_none(self):
        os.environ.update(PROCESSED_DIR='', DATABASE_PATH='', INDEX_DIR='', SOURCE_PDF='')
        self.assertEqual(asdict(Settings.from_env()), asdict(Settings()))

    def test_absolute_and_home_paths_are_supported(self):
        home = PROJECT_ROOT / 'test-home'
        os.environ.update(HOME=str(home), USERPROFILE=str(home))
        os.environ['PROCESSED_DIR'] = str(PROJECT_ROOT / 'custom/../processed')
        os.environ['SOURCE_PDF'] = '~/course.pdf'
        config = Settings.from_env()
        self.assertEqual(config.processed_dir, (PROJECT_ROOT / 'processed').resolve())
        self.assertEqual(config.source_pdf, (home / 'course.pdf').resolve())

    def test_relative_path_does_not_depend_on_current_directory(self):
        os.environ['INDEX_DIR'] = 'custom/indexes'
        previous = Path.cwd()
        with TemporaryDirectory() as temp:
            try:
                os.chdir(temp)
                self.assertEqual(Settings.from_env().index_dir, (PROJECT_ROOT / 'custom/indexes').resolve())
            finally:
                os.chdir(previous)

    def test_empty_origins_disable_cross_origin_access(self):
        os.environ['CORS_ORIGINS'] = ' , '
        self.assertEqual(Settings.from_env().cors_origins, ())

    def test_explicit_config_and_replace_ignore_invalid_environment(self):
        os.environ.update(MODEL_TIMEOUT='invalid', GENERATION_MODE='invalid')
        config = Settings(processed_dir='custom', source_pdf='book.pdf', model_timeout=15)
        changed = replace(config, index_dir='indexes')
        self.assertEqual(changed.processed_dir, Path('custom'))
        self.assertEqual(changed.source_pdf, Path('book.pdf'))
        self.assertEqual(changed.index_dir, Path('indexes'))
        self.assertEqual(changed.model_timeout, 15)

    def test_invalid_modes_are_reported_in_chinese(self):
        for name in ('GENERATION_MODE', 'DEFAULT_RETRIEVAL_MODE'):
            with self.subTest(name=name), patch.dict(os.environ, {name: 'unknown'}):
                with self.assertRaisesRegex(ValueError, name + '.*[\u3400-\u9fff]'):
                    Settings.from_env()

    def test_invalid_timeouts_are_reported_in_chinese(self):
        for value in ('', 'invalid', '0', '-1', '180.1', 'nan', 'inf', '-inf'):
            with self.subTest(value=value), patch.dict(os.environ, MODEL_TIMEOUT=value):
                with self.assertRaisesRegex(ValueError, 'MODEL_TIMEOUT.*[\u3400-\u9fff]'):
                    Settings.from_env()

    def test_timeout_boundaries_are_supported(self):
        for value in ('0.001', '180'):
            with self.subTest(value=value), patch.dict(os.environ, MODEL_TIMEOUT=value):
                self.assertEqual(Settings.from_env().model_timeout, float(value))

    def test_application_reads_environment_and_respects_injected_config(self):
        os.environ.update(GENERATION_MODE='llm', MODEL_TIMEOUT='17', CORS_ORIGINS='https://a.test')
        app = create_app()
        self.assertEqual(app.state.settings.generation_mode, 'llm')
        self.assertEqual(app.state.settings.model_timeout, 17)
        self.assertEqual(app.user_middleware[1].kwargs['allow_origins'], ['https://a.test'])
        explicit = Settings()
        os.environ['MODEL_TIMEOUT'] = 'invalid'
        self.assertIs(create_app(explicit).state.settings, explicit)

    def test_proxy_behavior_is_unchanged(self):
        for url in ('http://localhost:1234', 'http://LOCALHOST.:1234', 'http://127.0.0.1', 'http://[::1]'):
            with self.subTest(url=url):
                self.assertFalse(should_trust_env(url))
        self.assertTrue(should_trust_env('https://models.example.test'))


class IndexConfigTests(unittest.TestCase):
    """离线入口真实构建索引，仅替换外部模型请求边界。"""

    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.config = make_corpus(self.root)

    def test_builder_without_explicit_settings_reads_embedding_environment(self):
        os.environ.update(EMBEDDING_BASE_URL='http://localhost:5678/v1',
                          EMBEDDING_MODEL='test-embedding', EMBEDDING_API_KEY='test-only')

        def embeddings(config, texts):
            self.assertEqual(config.embedding_model, 'test-embedding')
            self.assertEqual(config.embedding_base_url, 'http://localhost:5678/v1')
            self.assertEqual(config.embedding_api_key, 'test-only')
            return [[1.0, 0.0] for text in texts]

        with patch('pipeline.build_index.fetch_embeddings', side_effect=embeddings):
            result = build_indexes(self.config.processed_dir / 'chunks.jsonl', self.config.index_dir, mode='vector')
        vector = json.loads((self.config.index_dir / 'vector.index.json').read_text('utf-8'))
        self.assertEqual(vector['embedding_model'], 'test-embedding')
        self.assertIn('vector', result['modes'])

    def test_cli_uses_paths_from_environment(self):
        os.environ.update(PROCESSED_DIR=str(self.config.processed_dir), INDEX_DIR=str(self.config.index_dir))
        output = io.StringIO()
        with patch('sys.argv', ['build_index']), redirect_stdout(output):
            main()
        self.assertGreater(json.loads(output.getvalue())['chunk_count'], 0)
        self.assertTrue((self.config.index_dir / 'bm25.index.json').is_file())


if __name__ == '__main__':
    unittest.main()

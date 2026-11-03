"""基础架构回归：语法、模块边界与离线入口的参数保护。"""
import ast
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pipeline.clean_pdf import clean_pdf
from pipeline.chunk_txt import chunk_text

ROOT = Path(__file__).resolve().parents[1]


class StructureTests(unittest.TestCase):
    def test_python_syntax(self):
        for folder in ('backend', 'frontend', 'pipeline', 'tests'):
            for path in (ROOT / folder).rglob('*.py'):
                with self.subTest(file=str(path)):
                    ast.parse(path.read_text('utf-8-sig'), filename=str(path))

    def test_pipeline_missing_inputs_do_not_write(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            for stage in (clean_pdf, chunk_text):
                with self.assertRaises(FileNotFoundError):
                    stage(base / 'missing-input', base / 'output')
                self.assertEqual(list(base.iterdir()), [])

    def test_frontend_does_not_import_backend(self):
        for path in (ROOT / 'frontend').rglob('*.py'):
            tree = ast.parse(path.read_text('utf-8-sig'))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or '').startswith('backend'), str(path))
                if isinstance(node, ast.Import):
                    self.assertFalse(any(n.name.startswith('backend') for n in node.names), str(path))


if __name__ == '__main__':
    unittest.main()

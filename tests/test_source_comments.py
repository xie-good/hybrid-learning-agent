"""防止项目源码重新引入纯英文说明性注释或文档字符串。"""
import ast
import io
from pathlib import Path
import re
import tokenize
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ('backend', 'frontend', 'pipeline', 'tests', 'tools')
CHINESE = re.compile(r'[\u3400-\u9fff]')
LETTERS = re.compile(r'[A-Za-z\u3400-\u9fff]')
DIRECTIVE = re.compile(r'^#\s*(?:!|.*coding[:=]|noqa\b|type:\s*ignore\b|pragma:\s*no cover\b)')


class SourceCommentTests(unittest.TestCase):
    """只核查注释节点，不误改教材引文、测试样例或运行时字符串。"""

    def test_explanatory_comments_and_docstrings_are_chinese(self):
        """机器指令保持原语法，人工阅读的解释至少包含中文。"""
        violations = []
        for folder in SOURCE_DIRS:
            for path in sorted((ROOT / folder).rglob('*.py')):
                source = path.read_text('utf-8-sig')
                entries = [(token.start[0], token.string) for token in
                           tokenize.generate_tokens(io.StringIO(source).readline)
                           if token.type == tokenize.COMMENT]
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                        docstring = ast.get_docstring(node, clean=False)
                        if docstring:
                            entries.append((node.body[0].lineno, docstring))
                for line, text in entries:
                    if LETTERS.search(text) and not DIRECTIVE.match(text) and not CHINESE.search(text):
                        violations.append(f'{path.relative_to(ROOT).as_posix()}:{line}: {text}')
        self.assertEqual(violations, [], '以下说明性注释尚未中文化：\n' + '\n'.join(violations))

    def test_configuration_comments_are_chinese(self):
        """配置示例和依赖清单的说明同样采用中文。"""
        for name in ('.env.example', 'requirements.txt'):
            for number, line in enumerate((ROOT / name).read_text('utf-8-sig').splitlines(), 1):
                if line.lstrip().startswith('#') and LETTERS.search(line):
                    with self.subTest(file=name, line=number):
                        self.assertRegex(line, CHINESE)


if __name__ == '__main__':
    unittest.main()

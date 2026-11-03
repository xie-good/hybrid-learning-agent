"""验证知识正文过滤、跨页状态、可审计偏移和分块入口的拒绝保护。"""
import hashlib
import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend.config import Settings
from backend.services.corpus import CorpusRepository
from pipeline.chunk_txt import chunk_text
from pipeline.clean_pdf import (CLEANING_VERSION, knowledge_only, page_segments,
                                section_exclusion_reason)
from pipeline.run_preprocess import preprocess


def load_rows(path):
    """读取测试产物中的逐行记录。"""
    return [json.loads(line) for line in path.read_text('utf-8').splitlines() if line.strip()]


def make_knowledge_pdf(path, *, bookmarks=True):
    """用真实字体与内容流生成跨页习题、参考文献和恢复知识节的最小PDF。"""
    texts = ['1.1 Basics\nKnowledge mentions exercises without deleting the sentence.\n'
             '    print("exercise")\nExercises\nQUESTION_ONE',
             'QUESTION_TWO_CONTINUED\nReferences\n[1] REFERENCE_ONLY',
             '[2] REFERENCE_CONTINUED\n1.2 Memory\nMEMORY_KNOWLEDGE\n'
             'Citations [1] remain in the explanatory paragraph.']
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
            NameObject('/F1'): writer._add_object(font)})})
        commands = []
        for line in text.splitlines():
            escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            commands.append(f'({escaped}) Tj T*')
        content = DecodedStreamObject()
        content.set_data(('BT /F1 12 Tf 14 TL 50 740 Td ' + ' '.join(commands) + ' ET').encode())
        page[NameObject('/Contents')] = writer._add_object(content)
    if bookmarks:
        chapter = writer.add_outline_item('第一章 课程知识', 0)
        for title, page in [('1.1 Basics', 0), ('Exercises', 0), ('References', 1), ('1.2 Memory', 2)]:
            writer.add_outline_item(title, page, parent=chapter)
    with path.open('wb') as stream:
        writer.write(stream)


class KnowledgePreprocessTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'course.pdf'
        self.output = self.base / 'processed'
        make_knowledge_pdf(self.source)

    def test_strict_heading_classification(self):
        for title in ['习题', '课后练习', '1.6 习题', '思考与练习', 'Exercises', 'Review Questions']:
            with self.subTest(title=title):
                self.assertEqual(section_exclusion_reason(title), 'exercises')
        self.assertEqual(section_exclusion_reason('参考文献'), 'references')
        self.assertEqual(section_exclusion_reason('💬 讨论与交流'), 'community')
        for title in ['我们通过习题解释原理。', '1.4 练习题生成方法', '参考文献检索技术',
                      'print("习题")', '# 习题是一种测试数据', 'Exercises improve learning.']:
            self.assertIsNone(section_exclusion_reason(title))

    def test_same_page_tail_excluded_and_offsets_rebuilt(self):
        chapter = {'chapter_id': 'ch01', 'sections': [
            {'section_id': 'ch01-s001', 'title': '1.1 知识', 'page_start': 1},
            {'section_id': 'ch01-s002', 'title': '习题', 'page_start': 1}]}
        text = '1.1 知识\n保留讲解与正文引用[1]。\n习题\n请设计一个智能体。'
        segments, current = page_segments(text, chapter, 1, None)
        retained, pieces, excluded, mappings = knowledge_only(text, segments)
        self.assertEqual(retained, text[:text.index('习题')])
        self.assertEqual(current['title'], '习题')
        self.assertEqual(excluded[0]['source_char_start'], text.index('习题'))
        self.assertEqual(excluded[0]['char_count'], len(text) - text.index('习题'))
        self.assertEqual(pieces[-1]['char_end'], len(retained))
        for mapping in mappings:
            self.assertEqual(retained[mapping['char_start']:mapping['char_end']],
                             text[mapping['source_char_start']:mapping['source_char_end']])

    def test_fallback_heading_cross_page_and_resume(self):
        chapter = {'chapter_id': 'ch01', 'sections': []}
        current = None
        pages = ['1.1 原理\n正文提及习题但不删除。\n习题\n第一题',
                 '第二题的跨页内容\n参考文献\n[1] 文献',
                 '[2] 文献续页\n1.2 记忆\n知识解释与示例代码']
        results = []
        for number, text in enumerate(pages, 1):
            segments, current = page_segments(text, chapter, number, current)
            results.append(knowledge_only(text, segments)[0])
        self.assertIn('正文提及习题但不删除', results[0])
        self.assertEqual(results[1], '')
        self.assertEqual(results[2], '1.2 记忆\n知识解释与示例代码')

    def test_exercises_before_and_after_references_are_both_excluded(self):
        chapter = {'chapter_id': 'ch01', 'sections': []}
        text = '参考文献\n[1] source\n习题\n问题正文\n1.2 下一知识节\n保留知识'
        segments, _ = page_segments(text, chapter, 1, None)
        kept, _, removed, _ = knowledge_only(text, segments)
        self.assertEqual(kept, '1.2 下一知识节\n保留知识')
        self.assertEqual([s['reason'] for s in removed], ['references', 'exercises'])

    def test_fenced_and_indented_teaching_code_preserved(self):
        chapter = {'chapter_id': 'ch01', 'sections': []}
        text = '1.1 教学示例\n```text\nExercises\n参考文献\n```\n    习题\nprint("习题")\n正文知识'
        segments, _ = page_segments(text, chapter, 1, None)
        self.assertEqual(knowledge_only(text, segments)[0], text)

    def test_figure_reference_is_not_a_new_section(self):
        chapter = {'chapter_id': 'ch05', 'sections': []}
        text = '见图\n5.52 所示。\n图注与解释'
        segments, _ = page_segments(text, chapter, 157, None)
        self.assertEqual(chapter['sections'], [])
        self.assertEqual(knowledge_only(text, segments)[0], text)

    def test_unlocatable_nonknowledge_bookmark_rejects_instead_of_leaking(self):
        chapter = {'chapter_id': 'ch01', 'sections': [
            {'section_id': 'ch01-s002', 'title': '习题', 'page_start': 1}]}
        with self.assertRaisesRegex(ValueError, '非知识书签标题未能定位'):
            page_segments('知识正文\n损坏的标题\n请回答问题', chapter, 1, None)

    def test_real_pdf_knowledge_only_and_corpus_integrity(self):
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        report = preprocess(self.source, self.output)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)
        self.assertEqual(report['cleaning_version'], CLEANING_VERSION)
        self.assertEqual(report['content_policy'], 'knowledge-only-v1')
        self.assertEqual(report['excluded_section_count'], 2)
        self.assertEqual(report['excluded_content_pages'], 3)
        self.assertEqual(report['fully_excluded_content_pages'], 1)
        self.assertGreater(report['excluded_content_chars'], 0)
        pages = load_rows(self.output / 'pages.jsonl')
        self.assertEqual(pages[1]['text'], '')
        self.assertEqual(pages[1]['segments'], [])
        chapters = json.loads((self.output / 'chapters.json').read_text('utf-8'))
        self.assertEqual([s['title'] for s in chapters[0]['sections']], ['1.1 Basics', '1.2 Memory'])
        self.assertEqual(report['section_count'], 2)
        chunks = load_rows(self.output / 'chunks.jsonl')
        combined = '\n'.join(c['text'] for c in chunks)
        self.assertIn('MEMORY_KNOWLEDGE', combined)
        self.assertIn('Knowledge mentions exercises', combined)
        self.assertIn('print("exercise")', combined)
        self.assertIn('Citations [1] remain', combined)
        for marker in ['QUESTION_ONE', 'QUESTION_TWO', 'REFERENCE_ONLY', 'REFERENCE_CONTINUED']:
            self.assertNotIn(marker, combined)
        for page in pages:
            for item in page['knowledge_spans']:
                self.assertEqual(page['text'][item['char_start']:item['char_end']],
                                 page['normalized_text'][item['source_char_start']:item['source_char_end']])
            for item in page['excluded_spans']:
                self.assertEqual(item['char_count'], item['source_char_end'] - item['source_char_start'])
        repo = CorpusRepository(replace(Settings(), processed_dir=self.output))
        self.assertTrue(repo.status()['ready'], repo.status())

    def test_bookmarkless_partial_range_does_not_leak_continuation(self):
        make_knowledge_pdf(self.source, bookmarks=False)
        report = preprocess(self.source, self.output, start_page=2, end_page=3)
        pages = load_rows(self.output / 'pages.jsonl')
        self.assertEqual(pages[0]['text'], '')
        self.assertTrue(pages[0]['excluded_spans'])
        self.assertIn('MEMORY_KNOWLEDGE', pages[1]['text'])
        self.assertNotIn('QUESTION', (self.output / 'cleaned.txt').read_text('utf-8'))
        self.assertEqual(report['included_pages'], 2)

    def test_bookmarked_partial_range_keeps_catalog_and_page_offsets_valid(self):
        preprocess(self.source, self.output, start_page=2, end_page=3)
        repo = CorpusRepository(replace(Settings(), processed_dir=self.output))
        self.assertTrue(repo.status()['ready'], repo.status())
        self.assertEqual({c['page_start'] for c in repo.scoped_chunks()}, {3})

    def test_only_nonknowledge_range_not_published(self):
        with self.assertRaisesRegex(ValueError, '未提取到可分块正文'):
            preprocess(self.source, self.output, start_page=2, end_page=2)
        self.assertFalse(self.output.exists())

    def test_chunk_entry_rejects_nonknowledge_metadata_before_writing(self):
        preprocess(self.source, self.output)
        rows = load_rows(self.output / 'pages.jsonl')
        rows[0]['segments'][0]['section_title'] = '习题'
        bad = self.base / 'bad.jsonl'
        bad.write_text('\n'.join(json.dumps(r) for r in rows), 'utf-8')
        target = self.base / 'bad-chunks.jsonl'
        with self.assertRaisesRegex(ValueError, '非知识小节'):
            chunk_text(bad, target)
        self.assertFalse(target.exists())

    def test_chunk_entry_rejects_hidden_nonknowledge_heading_before_writing(self):
        preprocess(self.source, self.output)
        rows = load_rows(self.output / 'pages.jsonl')
        rows[0]['text'] = 'Knowledge\nExercises\nDO_NOT_INDEX'
        rows[0]['segments'] = [{**rows[0]['segments'][0], 'char_end': len(rows[0]['text'])}]
        bad = self.base / 'bad.jsonl'
        bad.write_text('\n'.join(json.dumps(r) for r in rows), 'utf-8')
        target = self.base / 'bad-chunks.jsonl'
        with self.assertRaisesRegex(ValueError, '独立非知识标题'):
            chunk_text(bad, target)
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()

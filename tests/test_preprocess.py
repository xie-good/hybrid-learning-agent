"""使用本地合成PDF测试预处理，不依赖下载资料、模型或外部网络。"""
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from pipeline.clean_pdf import clean_pdf, normalize_text, page_segments
from pipeline.chunk_txt import chunk_text, split_spans
from pipeline.run_preprocess import preprocess, OUTPUT_NAMES


def make_pdf(path: Path, *, bookmarks=True, blank=False, with_graduation=False):
    """嵌入ASCII文字和中文书签，确保用真实PDF解析链路测试，不伪造解析结果。"""
    writer = PdfWriter()
    texts = ['Cover', '1.1 Intro\n' + 'Agent knowledge. ' * 160,
             'Tail from old section\n1.2 Next\n    print("code")\nCaption Figure 1.1',
             '2.1 Other\nSecond chapter text.']
    if with_graduation:
        texts.append('3.1 Graduation\nSubmit your project and Pull Request.')
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        if blank:
            continue
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        lines = []
        for line in text.splitlines():
            escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            lines.append(f'({escaped}) Tj T*')
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 12 Tf 14 TL 50 740 Td ' + ' '.join(lines) + ' ET').encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    if bookmarks:
        first = writer.add_outline_item('第一章 基础', 1)
        writer.add_outline_item('1.1 Intro', 1, parent=first)
        writer.add_outline_item('1.2 Next', 2, parent=first)
        second = writer.add_outline_item('第二章 进阶', 3)
        writer.add_outline_item('2.1 Other', 3, parent=second)
        if with_graduation:
            graduation = writer.add_outline_item('第三章 毕业设计', 4)
            writer.add_outline_item('3.1 Graduation', 4, parent=graduation)
    with path.open('wb') as stream:
        writer.write(stream)


def load_lines(path):
    return [json.loads(line) for line in path.read_text('utf-8').splitlines() if line.strip()]


class PreprocessTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'course.pdf'
        make_pdf(self.source)
        self.output = self.base / 'processed'

    def test_normalization_preserves_code_and_punctuation(self):
        text = '⼈⼯智能与汽⻋⻢\r\n    print("中文，标点")  \r\n\r\n\r\n尾\x00'
        self.assertEqual(normalize_text(text), '人工智能与汽车马\n    print("中文，标点")\n\n尾')

    def test_end_to_end_and_source_unchanged(self):
        before = self.source.read_bytes()
        report = preprocess(self.source, self.output, max_chars=300, overlap=30)
        self.assertEqual(set(p.name for p in self.output.iterdir()), set(OUTPUT_NAMES))
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(report['source_sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual((report['start_page'], report['end_page'], report['included_pages']), (2, 4, 3))
        self.assertEqual(report['chapter_count'], 2)
        pages = {p['page']: p for p in load_lines(self.output / 'pages.jsonl')}
        chunks = load_lines(self.output / 'chunks.jsonl')
        self.assertEqual(len(chunks), report['chunk_count'])
        self.assertEqual(len({c['chunk_id'] for c in chunks}), len(chunks))
        for chunk in chunks:
            page = pages[chunk['page_start']]
            self.assertEqual(chunk['page_start'], chunk['page_end'])
            self.assertEqual(chunk['chapter_id'], page['chapter_id'])
            self.assertLessEqual(len(chunk['text']), 300)
            self.assertEqual(chunk['text'], page['text'][chunk['char_start']:chunk['char_end']])
        # 每个非空白字符都必须被至少一个块覆盖，避免丢掉短尾段和章节开头。
        for number, page in pages.items():
            covered = set()
            for c in chunks:
                if c['page_start'] == number:
                    covered.update(range(c['char_start'], c['char_end']))
            self.assertTrue(all(i in covered for i, char in enumerate(page['text']) if not char.isspace()))
        self.assertIn('ch01', {c['chapter_id'] for c in chunks})
        self.assertIn('ch02', {c['chapter_id'] for c in chunks})

    def test_same_page_section_boundary(self):
        chapter = {'sections': [{'section_id': 'new', 'title': '1.2 Next', 'page_start': 3}]}
        old = {'section_id': 'old', 'title': '1.1 Intro'}
        text = 'old tail\n1.2 Next\nnew text'
        segments, current = page_segments(text, chapter, 3, old)
        self.assertEqual([s['section_id'] for s in segments], ['old', 'new'])
        self.assertEqual(segments[0]['char_end'], text.index('1.2'))
        self.assertEqual(current['section_id'], 'new')

    def test_graduation_chapter_excluded_by_default(self):
        make_pdf(self.source, with_graduation=True)
        report = preprocess(self.source, self.output)
        self.assertEqual((report['start_page'], report['end_page'], report['included_pages']), (2, 4, 3))
        self.assertEqual(report['requested_end_page'], 5)
        self.assertEqual(report['chapter_count'], 2)
        self.assertEqual(report['excluded_chapters'][0]['chapter_id'], 'ch03')
        self.assertEqual(report['excluded_chapters'][0]['page_start'], 5)
        self.assertNotIn('Submit your project', (self.output / 'cleaned.txt').read_text('utf-8'))
        for name in ('pages.jsonl', 'chunks.jsonl'):
            self.assertNotIn('ch03', {row['chapter_id'] for row in load_lines(self.output / name)})
        chapters = json.loads((self.output / 'chapters.json').read_text('utf-8'))
        self.assertEqual([c['chapter_id'] for c in chapters], ['ch01', 'ch02'])

    def test_explicit_end_cannot_reinclude_graduation(self):
        make_pdf(self.source, with_graduation=True)
        report = preprocess(self.source, self.output, end_page=5)
        self.assertEqual(report['end_page'], 4)
        self.assertEqual(report['included_pages'], 3)

    def test_graduation_only_range_not_published(self):
        make_pdf(self.source, with_graduation=True)
        with self.assertRaisesRegex(ValueError, '非课程章节'):
            preprocess(self.source, self.output, start_page=5, end_page=5)
        self.assertFalse(self.output.exists())

    def test_chunk_repeatability_and_parameter_versioning(self):
        preprocess(self.source, self.output, max_chars=300, overlap=30)
        first = (self.output / 'chunks.jsonl').read_bytes()
        stats = chunk_text(self.output / 'pages.jsonl', self.base / 'repeat.jsonl', max_chars=300, overlap=30)
        self.assertEqual(first, (self.base / 'repeat.jsonl').read_bytes())
        other = chunk_text(self.output / 'pages.jsonl', self.base / 'other.jsonl', max_chars=400, overlap=30)
        self.assertNotEqual(stats['dataset_version'], other['dataset_version'])

    def test_requires_explicit_overwrite(self):
        preprocess(self.source, self.output)
        before = {p.name: p.read_bytes() for p in self.output.iterdir()}
        with self.assertRaises(FileExistsError):
            preprocess(self.source, self.output)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.output.iterdir()})
        (self.output / 'user-notes.txt').write_text('keep me')
        preprocess(self.source, self.output, force=True)
        self.assertEqual((self.output / 'user-notes.txt').read_text(), 'keep me')

    def test_mixed_sources_and_bad_offsets_rejected(self):
        preprocess(self.source, self.output)
        rows = load_lines(self.output / 'pages.jsonl')
        rows[1]['source_sha256'] = 'different'
        path = self.base / 'bad.jsonl'
        path.write_text('\n'.join(json.dumps(r) for r in rows), 'utf-8')
        target = self.base / 'bad-chunks.jsonl'
        with self.assertRaises(ValueError):
            chunk_text(path, target)
        self.assertFalse(target.exists())
        rows[1]['source_sha256'] = rows[0]['source_sha256']
        rows[0]['segments'][0]['char_start'] = 1
        path.write_text('\n'.join(json.dumps(r) for r in rows), 'utf-8')
        with self.assertRaises(ValueError):
            chunk_text(path, target)
        self.assertFalse(target.exists())

    def test_invalid_parameters_leave_no_outputs(self):
        for kwargs in ({'start_page': 0}, {'end_page': 99}, {'start_page': 4, 'end_page': 2},
                       {'max_chars': 10}, {'overlap': -1}, {'max_chars': 100, 'overlap': 50}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    preprocess(self.source, self.output, **kwargs)
                self.assertFalse(self.output.exists())

    def test_bookmarkless_requires_start(self):
        make_pdf(self.source, bookmarks=False)
        with self.assertRaises(ValueError):
            preprocess(self.source, self.output)
        report = preprocess(self.source, self.output, start_page=2, end_page=3)
        self.assertEqual(report['chapter_count'], 1)
        self.assertEqual(report['included_pages'], 2)

    def test_blank_pdf_not_published(self):
        make_pdf(self.source, blank=True)
        with self.assertRaises(ValueError):
            preprocess(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_no_source_output_collision(self):
        with self.assertRaises(ValueError):
            preprocess(self.source, self.base, force=True)
        with self.assertRaises(ValueError):
            clean_pdf(self.source, self.base)
        self.assertTrue(self.source.exists())

    def test_split_bounds_overlap_and_tail(self):
        text = 'x' * 981
        spans = list(split_spans(text, 300, 30))
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1][1], len(text))
        for left, right in zip(spans, spans[1:]):
            self.assertEqual(left[1] - right[0], 30)
        self.assertTrue(all(0 < end - start <= 300 for start, end, _ in spans))
        self.assertTrue(spans[0][2])
        self.assertEqual(list(split_spans('short', 300, 30)), [(0, 5, False)])


if __name__ == '__main__':
    unittest.main()

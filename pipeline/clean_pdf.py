"""离线提取PDF正文：只生成新数据，不修改教材，也不执行教材中的代码。"""
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pypdf
from pypdf import PdfReader

CLEANING_VERSION = 'hello-agents-clean-v2-course-only'
# 按章标题排除作业/提交流程，不能按正文关键词删除，否则会误删课程讲解。
EXCLUDED_CHAPTER_KEYWORDS = ('毕业设计',)
CHAPTER_RE = re.compile(r'^第[一二三四五六七八九十百零\d]+章\s*\S+')
# 康熙部首可NFKC还原，部分补充部首需显式映射。仅处理已知字形，
# 不对全文做NFKC，避免改变代码字符串中的全角标点等原有字符。
RADICALS = str.maketrans({
    **{chr(n): unicodedata.normalize('NFKC', chr(n)) for n in range(0x2F00, 0x2FE0)},
    **dict(zip('⻋⻨⻛⻅⻆⻓⻔⻚⻜⻥⻩⻬⻮⻰⻳', '车麦风见角长门页飞鱼黄齐齿龙龟')),
    **dict(zip('⻢⻝⻉⺟⻣⻄⻁⺠⻘⻤', '马食贝母骨西虎民青鬼')),
    '\u00a0': ' ', '\x00': '', '\u200b': '', '\ufeff': '',
})


def normalize_text(text: str) -> str:
    """修复已知字形/控制字符、行尾空格及连续空行；保留换行和代码缩进。"""
    text = text.replace('\r\n', '\n').replace('\r', '\n').translate(RADICALS)
    lines = [line.rstrip() for line in text.split('\n')]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip('\n')


def compact(text: str) -> str:
    """仅用于标题匹配，不用于改写正文。"""
    return re.sub(r'\s+', '', normalize_text(text))


def read_chapters(reader: PdfReader) -> list[dict]:
    """优先使用PDF书签，避免把目录中出现的章名误认为正文起点。"""
    entries = []

    def visit(items, depth=0):
        for item in items:
            if isinstance(item, list):
                visit(item, depth + 1)
            else:
                page = reader.get_destination_page_number(item)
                if page is not None and page >= 0:
                    entries.append((depth, normalize_text(item.title).strip(), page + 1))

    visit(reader.outline)
    chapters = []
    for depth, title, page in entries:
        if depth == 0 and CHAPTER_RE.match(title):
            chapters.append({'chapter_id': f'ch{len(chapters) + 1:02d}',
                             'title': title, 'page_start': page, 'sections': []})
        elif depth == 1 and chapters and page >= chapters[-1]['page_start']:
            chapter = chapters[-1]
            chapter['sections'].append({
                'section_id': f"{chapter['chapter_id']}-s{len(chapter['sections']) + 1:03d}",
                'title': title, 'page_start': page,
            })
    for index, chapter in enumerate(chapters):
        chapter['page_end'] = (chapters[index + 1]['page_start'] - 1
                               if index + 1 < len(chapters) else len(reader.pages))
    return chapters


def page_segments(text: str, chapter: dict, page: int,
                  current: dict | None) -> tuple[list[dict], dict | None]:
    """在实际标题行处分节；同页新节不会覆盖上一节的内容。"""
    headings = {compact(s['title']): s for s in chapter['sections']
                if s['page_start'] == page}
    segments, start, offset = [], 0, 0
    for line in text.splitlines(keepends=True):
        heading = headings.get(compact(line))
        if heading:
            if offset > start:
                segments.append({'char_start': start, 'char_end': offset,
                                 'section_id': current['section_id'] if current else None,
                                 'section_title': current['title'] if current else None})
            start, current = offset, heading
        offset += len(line)
    if len(text) > start:
        segments.append({'char_start': start, 'char_end': len(text),
                         'section_id': current['section_id'] if current else None,
                         'section_title': current['title'] if current else None})
    return segments, current


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')


def clean_pdf(source: Path, output_dir: Path, *, start_page: int | None = None,
              end_page: int | None = None) -> dict:
    """从指定物理页范围提取课程知识；无论是否指定终点，均排除毕业设计章。"""
    source, output_dir = Path(source).resolve(), Path(output_dir).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.is_relative_to(output_dir):
        raise ValueError('输出目录必须与原始PDF分离。')
    reader = PdfReader(source)
    if reader.is_encrypted:
        raise ValueError('请使用可直接读取的PDF。')
    chapters = read_chapters(reader)
    if start_page is None:
        if not chapters:
            raise ValueError('未发现章节书签，请通过 --start-page 指定正文起点。')
        start_page = chapters[0]['page_start']
    end_page = len(reader.pages) if end_page is None else end_page
    if not 1 <= start_page <= end_page <= len(reader.pages):
        raise ValueError('页码范围必须满足 1 <= start <= end <= PDF总页数。')
    if not chapters:
        chapters = [{'chapter_id': 'unclassified', 'title': '未分类正文',
                     'page_start': start_page, 'page_end': end_page, 'sections': []}]
    selected = [c for c in chapters if c['page_start'] <= end_page
                and c['page_end'] >= start_page]
    if not selected or selected[0]['page_start'] > start_page:
        selected.insert(0, {'chapter_id': 'front-matter', 'title': '前置内容',
                           'page_start': start_page,
                           'page_end': selected[0]['page_start'] - 1 if selected else end_page,
                           'sections': []})
    requested_start, requested_end = start_page, end_page
    excluded_chapters = [
        {'chapter_id': c['chapter_id'], 'title': c['title'],
         'page_start': max(start_page, c['page_start']),
         'page_end': min(end_page, c['page_end']),
         'reason': 'non_course_graduation_design'}
        for c in selected if any(word in c['title'] for word in EXCLUDED_CHAPTER_KEYWORDS)
    ]
    selected = [c for c in selected
                if not any(word in c['title'] for word in EXCLUDED_CHAPTER_KEYWORDS)]
    if not selected:
        raise ValueError('指定范围只有已排除的非课程章节，没有可处理的课程知识。')
    for c in selected:
        c['included_page_start'] = max(start_page, c['page_start'])
        c['included_page_end'] = min(end_page, c['page_end'])
    # 支持排除范围中间的章节，不用简单截断或重新编号，始终保留原始物理页码。
    included_page_numbers = [n for c in selected
                             for n in range(c['included_page_start'], c['included_page_end'] + 1)]
    start_page, end_page = included_page_numbers[0], included_page_numbers[-1]
    with source.open('rb') as source_stream:
        source_sha = hashlib.file_digest(source_stream, 'sha256').hexdigest()
    report = {
        'source_file': source.name, 'source_path': str(source), 'source_sha256': source_sha,
        'cleaning_version': CLEANING_VERSION, 'parser': f'pypdf {pypdf.__version__}',
        'total_pdf_pages': len(reader.pages), 'start_page': start_page, 'end_page': end_page,
        'requested_start_page': requested_start, 'requested_end_page': requested_end,
        'included_pages': len(included_page_numbers),
        'excluded_pages': len(reader.pages) - len(included_page_numbers),
        'excluded_chapters': excluded_chapters,
        'chapter_count': len(selected), 'text_chars': 0, 'review_pages': [],
        'notes': ['仅收录课程知识，按章标题排除毕业设计；排除记录仅用于审计，不进入文本块。',
                  '物理页码从1开始。正文保留原有换行、代码缩进、图注及参考文献。',
                  '不做OCR或图表内容识别；图片、表格、低文本量及异常字形页列入复核。',
                  'PDF文本提取不保证代码可直接执行；本流程从不运行教材代码。'],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    current, previous_chapter = None, None
    matched_sections = set()
    with (output_dir / 'pages.jsonl').open('w', encoding='utf-8', newline='\n') as pages, \
            (output_dir / 'cleaned.txt').open('w', encoding='utf-8', newline='\n') as readable:
        for number in included_page_numbers:
            chapter = next(c for c in selected if c['page_start'] <= number <= c['page_end'])
            if chapter['chapter_id'] != previous_chapter:
                earlier = [s for s in chapter['sections'] if s['page_start'] < number]
                current = earlier[-1] if earlier else None
                previous_chapter = chapter['chapter_id']
            page = reader.pages[number - 1]
            raw = page.extract_text() or ''
            text = normalize_text(raw)
            # 仅移除页边缘的已知品牌行，不按频次删除正文，也不删除独立数字。
            lines = text.splitlines()
            removed = []
            while lines and lines[0].strip() in {'Hello-Agents', 'Datawhale'}:
                removed.append(lines.pop(0))
            while lines and lines[-1].strip() in {'Hello-Agents', 'Datawhale'}:
                removed.append(lines.pop())
            text = '\n'.join(lines)
            segments, current = page_segments(text, chapter, number, current)
            matched_sections.update(s['section_id'] for s in segments if s['section_id'])
            flags = []
            if len(text.strip()) < 80:
                flags.append('low_text')
            # 只检查资源引用，不解码百兆图片；这是保守复核提示。
            resources = page.get('/Resources')
            resources = resources.get_object() if resources else {}
            objects = resources.get('/XObject', {})
            objects = objects.get_object() if hasattr(objects, 'get_object') else objects
            if any(obj.get_object().get('/Subtype') == '/Image' for obj in objects.values()):
                flags.append('image_resource')
            if re.search(r'(?:图|表)\s*\d+[.．-]\d+', text):
                flags.append('figure_or_table_reference')
            if '\ufffd' in text or any(0x2E80 <= ord(c) < 0x3000 for c in text):
                flags.append('unresolved_glyph')
            record = {'source_file': source.name, 'source_sha256': source_sha,
                      'cleaning_version': CLEANING_VERSION, 'page': number,
                      'chapter_id': chapter['chapter_id'], 'chapter_title': chapter['title'],
                      'raw_text': raw, 'text': text, 'segments': segments,
                      'removed_edge_lines': removed, 'review_flags': flags}
            pages.write(json.dumps(record, ensure_ascii=False) + '\n')
            readable.write(f"\n--- PDF第{number}页 | {chapter['title']} ---\n{text}\n")
            report['text_chars'] += len(text)
            if flags:
                report['review_pages'].append({'page': number, 'flags': flags})
    sections = [s for c in selected for s in c['sections']
                if start_page <= s['page_start'] <= end_page]
    report['section_count'] = len(sections)
    report['matched_section_count'] = sum(s['section_id'] in matched_sections for s in sections)
    report['unmatched_sections'] = [s for s in sections if s['section_id'] not in matched_sections]
    report['review_flag_counts'] = dict(Counter(flag for p in report['review_pages'] for flag in p['flags']))
    write_json(output_dir / 'chapters.json', selected)
    write_json(output_dir / 'report.json', report)
    return report


if __name__ == '__main__':
    print('请运行 python -m pipeline.run_preprocess --help 查看离线处理命令。')

"""离线提取PDF正文：只生成新数据，不修改教材，也不执行教材中的代码。"""
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pypdf
from pypdf import PdfReader

CLEANING_VERSION = 'hello-agents-clean-v4-knowledge-only'
# 第一版课程范围固定到第12章。即使显式指定更晚的终页，也不收录案例进阶等后续章节。
MAX_COURSE_CHAPTER = 12
# 按章标题排除作业/提交流程，不能按正文关键词删除，否则会误删课程讲解。
EXCLUDED_CHAPTER_KEYWORDS = ('毕业设计',)
CHAPTER_RE = re.compile(r'^第[一二三四五六七八九十百零\d]+章\s*\S+')
# 只识别独立标题，不以正文中是否出现“习题”等词语作为删除依据。
NON_KNOWLEDGE_HEADINGS = {
    'exercises': ('习题', '练习', '练习题', '课后习题', '课后练习', '课后练习题',
                  '思考题', '思考与练习', '练习与思考', '习题与思考', '思考与习题',
                  '复习题', '课后作业', '本章习题', '本章练习', '练习与作业',
                  'exercises', 'exercise', 'practicequestions', 'reviewquestions'),
    'references': ('参考文献', '参考资料', '参考书目', 'references', 'bibliography'),
    'community': ('讨论与交流', '讨论交流', '社区交流', '习题讨论与问答'),
}
SECTION_HEADING_RE = re.compile(r'^(\d+)\.(\d+)\s+\S[^\n]*$')
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


def section_exclusion_reason(title: str | None) -> str | None:
    """严格匹配小节标题；编号、装饰和空白不影响分类，普通讲解句不会命中。"""
    if not title:
        return None
    title = normalize_text(title).strip()
    title = re.sub(r'^[\s#*💬📝📚]+', '', title)
    title = re.sub(r'^(?:第[一二三四五六七八九十百零\d]+[章节]|\d+(?:[.．]\d+)*[.、．]?)\s*', '', title)
    title = compact(title).strip(':：。.!！*#').casefold()
    return next((reason for reason, headings in NON_KNOWLEDGE_HEADINGS.items()
                 if title in headings), None)


def chapter_exclusion_reason(chapter: dict) -> str | None:
    """只在章节层面筛选，保留前12章内正常提及案例名称的知识性讲解。"""
    if any(word in chapter['title'] for word in EXCLUDED_CHAPTER_KEYWORDS):
        return 'non_course_graduation_design'
    match = re.fullmatch(r'ch(\d+)', chapter['chapter_id'])
    if match and int(match.group(1)) > MAX_COURSE_CHAPTER:
        return 'outside_course_chapter_range'
    return None


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
    """按书签或独立标题分节，并把知识/排除状态延续到下一页。"""
    headings = {compact(s['title']): s for s in chapter['sections']
                if s['page_start'] == page}
    segments, start, offset, fence = [], 0, 0, None
    expected_exclusions = {section_exclusion_reason(s['title']) for s in headings.values()
                           if section_exclusion_reason(s['title'])}
    matched_exclusions = set()

    def append_segment(end):
        if end > start:
            reason = section_exclusion_reason(current['title'] if current else None)
            segments.append({'char_start': start, 'char_end': end,
                             'section_id': current['section_id'] if current else None,
                             'section_title': current['title'] if current else None,
                             'content_kind': reason or 'knowledge'})

    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        marker = re.match(r'^(`{3,}|~{3,})', stripped)
        if marker:
            if fence is None:
                fence = marker.group()[0]
            elif marker.group()[0] == fence:
                fence = None
            offset += len(line)
            continue
        heading = headings.get(compact(line)) if fence is None else None
        if heading is None and fence is None and not line[:1].isspace():
            reason = section_exclusion_reason(stripped)
            number = SECTION_HEADING_RE.fullmatch(stripped)
            chapter_number = re.fullmatch(r'ch(\d+)', chapter.get('chapter_id', ''))
            numbered_knowledge = bool(number and not re.search(r'[。；;]', stripped)
                and (not chapter_number or int(number.group(1)) == int(chapter_number.group(1))))
            same_excluded_section = bool(reason and current
                and reason == section_exclusion_reason(current['title']))
            if (reason and not same_excluded_section) or numbered_knowledge:
                heading = {'section_id': f"{chapter.get('chapter_id', 'unclassified')}-sf-p{page:04d}-o{offset:05d}",
                           'title': stripped, 'page_start': page,
                           'heading_offset': offset, 'heading_source': 'standalone_heading'}
                chapter['sections'].append(heading)
                headings[compact(stripped)] = heading
        if heading:
            append_segment(offset)
            heading['heading_offset'] = offset
            reason = section_exclusion_reason(heading['title'])
            if reason:
                matched_exclusions.add(reason)
            start, current = offset, heading
        offset += len(line)
    append_segment(len(text))
    if expected_exclusions - matched_exclusions:
        raise ValueError(f'PDF第{page}页的非知识书签标题未能定位，请先复核该页，避免习题混入知识。')
    return segments, current


def knowledge_only(text: str, segments: list[dict]) -> tuple[str, list[dict], list[dict], list[dict]]:
    """只拼接知识段，重建连续偏移；源清洗页的排除范围另存供审计。"""
    parts, retained, excluded, mappings = [], [], [], []
    offset = 0
    for segment in segments:
        a, b = segment['char_start'], segment['char_end']
        reason = segment['content_kind'] if segment['content_kind'] != 'knowledge' else None
        if reason:
            excluded.append({'source_char_start': a, 'source_char_end': b,
                             'char_count': b - a, 'section_id': segment['section_id'],
                             'section_title': segment['section_title'], 'reason': reason})
            continue
        parts.append(text[a:b])
        retained.append({**segment, 'char_start': offset, 'char_end': offset + b - a})
        mappings.append({'source_char_start': a, 'source_char_end': b,
                         'char_start': offset, 'char_end': offset + b - a})
        offset += b - a
    return ''.join(parts), retained, excluded, mappings


def extract_page_text(page) -> tuple[str, str, list[str]]:
    """提取并清理页边品牌行；知识过滤之前的文本用于源偏移审计。"""
    raw = page.extract_text() or ''
    lines = normalize_text(raw).splitlines()
    removed = []
    while lines and lines[0].strip() in {'Hello-Agents', 'Datawhale'}:
        removed.append(lines.pop(0))
    while lines and lines[-1].strip() in {'Hello-Agents', 'Datawhale'}:
        removed.append(lines.pop())
    return raw, '\n'.join(lines), removed


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')


def clean_pdf(source: Path, output_dir: Path, *, start_page: int | None = None,
              end_page: int | None = None) -> dict:
    """提取前12章知识正文，排除习题、独立参考文献及社区交流小节。"""
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
                     'page_start': 1, 'page_end': len(reader.pages), 'sections': []}]
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
         'reason': chapter_exclusion_reason(c)}
        for c in selected if chapter_exclusion_reason(c)
    ]
    selected = [c for c in selected if not chapter_exclusion_reason(c)]
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
        'course_chapter_limit': MAX_COURSE_CHAPTER,
        'chapter_count': len(selected), 'text_chars': 0, 'review_pages': [],
        'content_policy': 'knowledge-only-v1', 'excluded_sections': [],
        'excluded_content_pages': 0, 'fully_excluded_content_pages': 0,
        'excluded_content_chars': 0, 'excluded_content_span_count': 0,
        'notes': ['课程范围仅第1—12章，第13—16章整章排除；排除记录仅用于审计，不进入文本块。',
                  '只收录知识讲解、教学示例代码及知识图注；习题、独立参考文献、社区交流整节排除。',
                  '物理页码从1开始；字符偏移对应过滤后text，源页范围由normalized_text和审计映射核对。',
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
                current = None
                # 从章起预读结构状态，防止只提取习题中段时因没有标题而把题目误作知识。
                for preceding in range(chapter['page_start'], number):
                    _, prior_text, _ = extract_page_text(reader.pages[preceding - 1])
                    _, current = page_segments(prior_text, chapter, preceding, current)
                previous_chapter = chapter['chapter_id']
            page = reader.pages[number - 1]
            raw, normalized, removed = extract_page_text(page)
            original_segments, current = page_segments(normalized, chapter, number, current)
            text, segments, excluded, mappings = knowledge_only(normalized, original_segments)
            matched_sections.update(s['section_id'] for s in segments if s['section_id'])
            report['excluded_content_pages'] += bool(excluded)
            report['fully_excluded_content_pages'] += bool(excluded and not text.strip())
            report['excluded_content_chars'] += sum(s['char_count'] for s in excluded)
            report['excluded_content_span_count'] += len(excluded)
            flags = []
            if text.strip() and len(text.strip()) < 80:
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
                      'normalized_text': normalized, 'knowledge_spans': mappings,
                      'excluded_spans': excluded, 'content_policy': 'knowledge-only-v1',
                      'removed_edge_lines': removed, 'review_flags': flags}
            pages.write(json.dumps(record, ensure_ascii=False) + '\n')
            readable.write(f"\n--- PDF第{number}页 | {chapter['title']} ---\n{text}\n")
            report['text_chars'] += len(text)
            if flags:
                report['review_pages'].append({'page': number, 'flags': flags})
    for chapter in selected:
        all_sections = sorted(chapter['sections'],
                              key=lambda s: (s['page_start'], s.get('heading_offset', -1)))
        report['excluded_sections'].extend(
            {**s, 'chapter_id': chapter['chapter_id'], 'reason': section_exclusion_reason(s['title'])}
            for s in all_sections if section_exclusion_reason(s['title']))
        chapter['sections'] = [s for s in all_sections if not section_exclusion_reason(s['title'])]
    sections = [s for c in selected for s in c['sections']]
    report['excluded_section_count'] = len(report['excluded_sections'])
    report['section_count'] = len(sections)
    report['matched_section_count'] = sum(s['section_id'] in matched_sections for s in sections)
    report['unmatched_sections'] = [s for s in sections if s['section_id'] not in matched_sections]
    report['review_flag_counts'] = dict(Counter(flag for p in report['review_pages'] for flag in p['flags']))
    write_json(output_dir / 'chapters.json', selected)
    write_json(output_dir / 'report.json', report)
    return report


if __name__ == '__main__':
    print('请运行 python -m pipeline.run_preprocess --help 查看离线处理命令。')

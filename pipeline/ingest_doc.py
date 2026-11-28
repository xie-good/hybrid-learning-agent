"""学习文档解析与结构化分块：仅支持 PDF（转 Markdown 精洗）与 Markdown。"""
from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

from pypdf import PdfReader

from pipeline.chunk_txt import split_spans
from pipeline.clean_pdf import (
    CHAPTER_RE,
    SECTION_HEADING_RE,
    compact,
    normalize_text,
    read_chapters,
    section_exclusion_reason,
)

SUPPORTED_EXTENSIONS = {'.pdf', '.md', '.markdown'}
MARKDOWN_HEADING_PATTERN = re.compile(r'^(#{1,3})\s+(.+?)\s*$')
CHINESE_HEADING_PATTERN = re.compile(r'^(?:第[一二三四五六七八九十百零\d]+[章节]|[0-9]+(?:\.[0-9]+){1,2})\s+\S.*$')
FIRST_CHAPTER_PATTERN = re.compile(r'^第[一1]章\s*\S+')
TOC_LINE_PATTERN = re.compile(r'^(?:目\s*录|contents|table\s+of\s+contents)$', re.IGNORECASE)
PAGE_ANCHOR_PATTERN = re.compile(r'^<!--\s*page:(\d+)\s*-->$')
DEFAULT_MAX_CHUNK_CHARS = 1200
DEFAULT_CHUNK_OVERLAP = 150


def decode_text_bytes(file_bytes: bytes) -> str:
    """按常见中文编码顺序把文件字节解码成字符串。"""
    for encoding_name in ('utf-8-sig', 'utf-8', 'gb18030', 'gbk'):
        try:
            return file_bytes.decode(encoding_name)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode('utf-8', errors='replace')


def _is_toc_page(text: str) -> bool:
    """判断页面是否为目录页，避免把目录里的章标题误判为正文起点。"""
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if not lines:
        return False
    if any(TOC_LINE_PATTERN.match(line) for line in lines[:4]):
        return True
    dotted_lines = sum(1 for line in lines if re.search(r'[.·…]{3,}\s*\d+\s*$', line))
    return dotted_lines >= 3


def _detect_body_start_page(pages: list[dict], outline_chapters: list[dict]) -> int:
    """定位 PDF 正文起始页：优先使用书签第 1 章，其次扫描正文首章标题，否则从首页开始。"""
    if outline_chapters:
        return outline_chapters[0]['page_start']

    max_scan_index = min(len(pages), max(10, len(pages) // 4))
    for page_item in pages[:max_scan_index]:
        page_text = page_item['text']
        if _is_toc_page(page_text):
            continue
        for raw_line in page_text.split('\n'):
            stripped = raw_line.strip()
            if FIRST_CHAPTER_PATTERN.match(stripped) and len(stripped) <= 80:
                return page_item['page']
    return pages[0]['page']


def _extract_pdf_pages(file_bytes: bytes) -> tuple[list[dict], list[dict]]:
    """逐页读取 PDF 的文字内容和书签目录，保留真实物理页码。"""
    try:
        pdf_reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as exc:
        raise ValueError('PDF 解析失败，请确认文件为未加密的文本型 PDF。') from exc

    if pdf_reader.is_encrypted:
        raise ValueError('暂不支持加密 PDF，请先解除密码后再上传。')
    if not pdf_reader.pages:
        raise ValueError('PDF 文件不包含任何页面。')

    try:
        outline_chapters = read_chapters(pdf_reader)
    except Exception:
        outline_chapters = []

    pages: list[dict] = []
    for page_number, page in enumerate(pdf_reader.pages, start=1):
        page_text = normalize_text(page.extract_text() or '')
        if page_text:
            pages.append({'page': page_number, 'text': page_text})

    if not pages:
        raise ValueError('未能从 PDF 中提取到有效文本（可能是纯扫描图片型 PDF）。')
    return pages, outline_chapters


def _convert_pdf_to_clean_markdown(pages: list[dict], outline_chapters: list[dict]) -> str:
    """把 PDF 正文清洗为带物理页码锚点的 Markdown：跳过封面目录并剔除练习题等非知识板块。"""
    body_start_page = _detect_body_start_page(pages, outline_chapters)

    # 收集书签的页码与标题映射，用于辅助识别章/节与排除板块。
    bookmarks_by_page: dict[int, dict[str, tuple[int, str]]] = {}
    for chapter_item in outline_chapters:
        page_num = chapter_item['page_start']
        bookmarks_by_page.setdefault(page_num, {})[compact(chapter_item['title'])] = (1, chapter_item['title'])
        for section_item in chapter_item.get('sections', []):
            sec_page = section_item['page_start']
            bookmarks_by_page.setdefault(sec_page, {})[compact(section_item['title'])] = (2, section_item['title'])

    md_lines: list[str] = []
    excluded_reason: str | None = None

    for page_item in pages:
        page_number = page_item['page']
        if page_number < body_start_page:
            continue

        page_bookmarks = bookmarks_by_page.get(page_number, {})
        kept_lines: list[str] = []
        inside_code_block = False

        for raw_line in page_item['text'].split('\n'):
            stripped = raw_line.strip()
            if stripped.startswith('```') or stripped.startswith('~~~'):
                inside_code_block = not inside_code_block
                if not excluded_reason:
                    kept_lines.append(raw_line)
                continue

            if not inside_code_block and stripped:
                compact_line = compact(stripped)
                bookmark_hit = page_bookmarks.get(compact_line)
                if bookmark_hit:
                    level, bm_title = bookmark_hit
                    reason = section_exclusion_reason(bm_title)
                    if reason:
                        excluded_reason = reason
                        continue
                    excluded_reason = None
                    prefix = '#' if level == 1 else '##'
                    kept_lines.append(f'{prefix} {bm_title}')
                    continue

                if not raw_line[:1].isspace():
                    reason = section_exclusion_reason(stripped)
                    if reason:
                        excluded_reason = reason
                        continue

                    if CHAPTER_RE.match(stripped) and len(stripped) <= 80:
                        excluded_reason = None
                        kept_lines.append(f'# {stripped}')
                        continue

                    if (
                        SECTION_HEADING_RE.fullmatch(stripped)
                        and len(stripped) <= 80
                        and not re.search(r'[。；;]', stripped)
                    ):
                        excluded_reason = None
                        kept_lines.append(f'## {stripped}')
                        continue

            if not excluded_reason:
                kept_lines.append(raw_line)

        cleaned_page_text = normalize_text('\n'.join(kept_lines))
        if cleaned_page_text:
            md_lines.append(f'<!-- page:{page_number} -->')
            md_lines.append(cleaned_page_text)
            md_lines.append('')

    cleaned_markdown = normalize_text('\n'.join(md_lines))
    if cleaned_markdown:
        return cleaned_markdown

    # 极端情况下若精洗后为空，安全回退为完整文本加页码锚点，避免误伤普通讲义。
    fallback_lines: list[str] = []
    for page_item in pages:
        fallback_lines.append(f"<!-- page:{page_item['page']} -->")
        fallback_lines.append(page_item['text'])
        fallback_lines.append('')
    return normalize_text('\n'.join(fallback_lines))


def _extract_markdown_blocks(markdown_text: str, *, has_page_anchors: bool) -> list[tuple[str | None, str, int, int]]:
    """按 Markdown 标题（与可选页码锚点）切分文本段，返回 (标题, 正文, 起始页, 结束页)。"""
    full_text = normalize_text(markdown_text)
    if not full_text:
        return []

    extracted_blocks: list[tuple[str | None, str, int, int]] = []
    current_heading: str | None = None
    paragraph_lines: list[str] = []
    inside_code_block = False
    current_page = 1
    block_page_start: int | None = None
    block_page_end = 1
    logical_page = 0

    def save_current_block():
        nonlocal block_page_start, logical_page
        if not paragraph_lines:
            return
        combined_text = normalize_text('\n'.join(paragraph_lines))
        if combined_text:
            if has_page_anchors:
                p_start = block_page_start if block_page_start is not None else current_page
                p_end = max(p_start, block_page_end)
            else:
                logical_page += 1
                p_start = logical_page
                p_end = logical_page
            extracted_blocks.append((current_heading, combined_text, p_start, p_end))
        paragraph_lines.clear()
        block_page_start = None

    for raw_line in full_text.split('\n'):
        stripped_line = raw_line.strip()
        if has_page_anchors:
            anchor_match = PAGE_ANCHOR_PATTERN.match(stripped_line)
            if anchor_match:
                current_page = int(anchor_match.group(1))
                continue

        # 代码块内部的 # 号是代码注释，不当作章节标题切分。
        if stripped_line.startswith('```') or stripped_line.startswith('~~~'):
            inside_code_block = not inside_code_block
            if block_page_start is None:
                block_page_start = current_page
            block_page_end = current_page
            paragraph_lines.append(raw_line)
            continue

        if not inside_code_block:
            markdown_match = MARKDOWN_HEADING_PATTERN.match(stripped_line)
            if markdown_match:
                save_current_block()
                current_heading = markdown_match.group(2).strip()
                continue
            if CHINESE_HEADING_PATTERN.match(stripped_line) and len(stripped_line) <= 80:
                save_current_block()
                current_heading = stripped_line
                continue

        if stripped_line and block_page_start is None:
            block_page_start = current_page
        if stripped_line:
            block_page_end = current_page
        paragraph_lines.append(raw_line)

    save_current_block()
    return extracted_blocks


def parse_uploaded_document(
    *,
    doc_id: str,
    filename: str,
    raw: bytes,
    chapter_id: str,
    kb_id: str,
    max_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> tuple[dict, list[dict]]:
    """把上传的 PDF（经转 Markdown 精洗）或 Markdown 文档解析成章节目录项与文本块列表。"""
    file_extension = Path(filename).suffix.casefold()
    if file_extension not in SUPPORTED_EXTENSIONS:
        display_ext = file_extension or '未知'
        raise ValueError(f'暂不支持 {display_ext} 格式，仅支持 PDF (.pdf) 与 Markdown (.md) 文件。')
    if not raw.strip():
        raise ValueError('上传文件内容为空。')

    file_sha256 = hashlib.sha256(raw).hexdigest()
    document_title = Path(filename).stem.strip() or filename
    sections: list[dict] = []
    chunks: list[dict] = []
    section_id_by_title: dict[str, str] = {}

    def get_or_create_section(section_title: str | None, p_start: int, p_end: int) -> tuple[str | None, str | None]:
        clean_title = (section_title or '').strip()
        if not clean_title:
            return None, None
        if clean_title not in section_id_by_title:
            new_section_id = f'{chapter_id}-s{len(sections) + 1:03d}'
            section_id_by_title[clean_title] = new_section_id
            sections.append({
                'section_id': new_section_id,
                'title': clean_title,
                'page_start': p_start,
                'page_end': p_end,
                'chunk_count': 0,
            })
            return new_section_id, clean_title

        existing_section_id = section_id_by_title[clean_title]
        for section_item in sections:
            if section_item['section_id'] == existing_section_id:
                section_item['page_start'] = min(section_item['page_start'], p_start)
                section_item['page_end'] = max(section_item['page_end'], p_end)
                break
        return existing_section_id, clean_title

    is_pdf = file_extension == '.pdf'
    if is_pdf:
        pages, outline_chapters = _extract_pdf_pages(raw)
        markdown_text = _convert_pdf_to_clean_markdown(pages, outline_chapters)
        text_blocks = _extract_markdown_blocks(markdown_text, has_page_anchors=True)
    else:
        markdown_text = decode_text_bytes(raw)
        text_blocks = _extract_markdown_blocks(markdown_text, has_page_anchors=False)

    if not text_blocks:
        raise ValueError('未能从文档中解析出有效正文内容。')

    for heading_title, block_text, p_start, p_end in text_blocks:
        section_id, section_title = get_or_create_section(heading_title, p_start, p_end)
        for char_start, char_end, is_hard_split in split_spans(block_text, max_chars, overlap):
            chunk_text = block_text[char_start:char_end].strip()
            if not chunk_text:
                continue
            source_url = (
                f'/api/kbs/{kb_id}/documents/{doc_id}/source#page={p_start}'
                if is_pdf else f'/api/kbs/{kb_id}/documents/{doc_id}/source'
            )
            chunks.append({
                'chunk_id': f'{doc_id}-p{p_start:04d}-{len(chunks) + 1:05d}',
                'doc_id': doc_id,
                'source_file': filename,
                'source_sha256': file_sha256,
                'chapter_id': chapter_id,
                'chapter_title': document_title,
                'section_id': section_id,
                'section_title': section_title,
                'page_start': p_start,
                'page_end': p_end,
                'char_start': char_start,
                'char_end': char_end,
                'text': chunk_text,
                'char_count': len(chunk_text),
                'hard_split': is_hard_split,
                'review_flags': [],
                'source_url': source_url,
            })

    if not chunks:
        raise ValueError('文档切分后未产生可用文本块，请检查文件内容。')

    page_start = min(chunk['page_start'] for chunk in chunks)
    page_end = max(chunk['page_end'] for chunk in chunks)

    section_chunk_counts: dict[str, int] = {}
    for chunk_item in chunks:
        sid = chunk_item.get('section_id')
        if sid:
            section_chunk_counts[sid] = section_chunk_counts.get(sid, 0) + 1

    for section_item in sections:
        sid = section_item['section_id']
        section_item['chunk_count'] = section_chunk_counts.get(sid, 0)

    chapter_entry = {
        'chapter_id': chapter_id,
        'title': document_title,
        'doc_id': doc_id,
        'source_file': filename,
        'page_start': page_start,
        'page_end': page_end,
        'chunk_count': len(chunks),
        'sections': sections,
    }
    return chapter_entry, chunks

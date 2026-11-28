"""多格式学习文档解析与结构化分块：支持 PDF、Word（DOCX）与 Markdown。"""
from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from pypdf import PdfReader

from pipeline.chunk_txt import split_spans
from pipeline.clean_pdf import normalize_text, read_chapters

SUPPORTED_EXTENSIONS = {'.pdf', '.md', '.markdown', '.docx'}
MARKDOWN_HEADING_PATTERN = re.compile(r'^(#{1,3})\s+(.+?)\s*$')
CHINESE_HEADING_PATTERN = re.compile(r'^(?:第[一二三四五六七八九十百零\d]+[章节]|[0-9]+(?:\.[0-9]+){1,2})\s+\S.*$')
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


def _extract_docx_blocks(file_bytes: bytes) -> list[tuple[str | None, str]]:
    """从 DOCX 压缩包中读取段落和标题样式，不依赖外部解析库。"""
    xml_namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as docx_zip:
            if 'word/document.xml' not in docx_zip.namelist():
                raise ValueError('DOCX 文件缺少正文数据。')
            document_xml_bytes = docx_zip.read('word/document.xml')
    except zipfile.BadZipFile as exc:
        raise ValueError('无法打开 DOCX 文件，请确认文件未损坏。') from exc

    xml_root = ET.fromstring(document_xml_bytes)
    extracted_blocks: list[tuple[str | None, str]] = []
    current_heading: str | None = None
    paragraph_lines: list[str] = []

    def save_current_block():
        if not paragraph_lines:
            return
        combined_text = normalize_text('\n'.join(paragraph_lines))
        if combined_text:
            extracted_blocks.append((current_heading, combined_text))
        paragraph_lines.clear()

    # 遍历 Word 正文里的每一个段落节点。
    for paragraph_node in xml_root.findall('.//w:body/w:p', xml_namespaces):
        text_pieces: list[str] = []
        for text_node in paragraph_node.findall('.//w:t', xml_namespaces):
            if text_node.text:
                text_pieces.append(text_node.text)
        line_text = normalize_text(''.join(text_pieces))
        if not line_text:
            continue

        style_node = paragraph_node.find('./w:pPr/w:pStyle', xml_namespaces)
        style_name = ''
        if style_node is not None:
            style_name = style_node.attrib.get(f"{{{xml_namespaces['w']}}}val", '')

        is_heading_style = style_name.lower().startswith('heading') or style_name.startswith('标题')
        is_chinese_heading = bool(CHINESE_HEADING_PATTERN.match(line_text))
        if (is_heading_style or is_chinese_heading) and len(line_text) <= 80:
            save_current_block()
            current_heading = line_text
        else:
            paragraph_lines.append(line_text)

    save_current_block()
    return extracted_blocks


def _extract_text_blocks(file_bytes: bytes) -> list[tuple[str | None, str]]:
    """按 Markdown 标题或中文章节标题切分纯文本段落。"""
    full_text = normalize_text(decode_text_bytes(file_bytes))
    if not full_text:
        return []

    extracted_blocks: list[tuple[str | None, str]] = []
    current_heading: str | None = None
    paragraph_lines: list[str] = []
    inside_code_block = False

    def save_current_block():
        if not paragraph_lines:
            return
        combined_text = normalize_text('\n'.join(paragraph_lines))
        if combined_text:
            extracted_blocks.append((current_heading, combined_text))
        paragraph_lines.clear()

    for raw_line in full_text.split('\n'):
        stripped_line = raw_line.strip()
        # 代码块内部的 # 号是代码注释，不当作章节标题切分。
        if stripped_line.startswith('```') or stripped_line.startswith('~~~'):
            inside_code_block = not inside_code_block
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

        paragraph_lines.append(raw_line)

    save_current_block()
    return extracted_blocks


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
    """把上传的单个文档解析成章节目录项和带页码出处的文本块列表。"""
    file_extension = Path(filename).suffix.casefold()
    if file_extension not in SUPPORTED_EXTENSIONS:
        display_ext = file_extension or '未知'
        raise ValueError(f'暂不支持 {display_ext} 格式，请上传 PDF、Word (.docx) 或 Markdown (.md) 文件。')
    if not raw.strip():
        raise ValueError('上传文件内容为空。')

    file_sha256 = hashlib.sha256(raw).hexdigest()
    document_title = Path(filename).stem.strip() or filename
    sections: list[dict] = []
    chunks: list[dict] = []
    section_id_by_title: dict[str, str] = {}

    def get_or_create_section(section_title: str | None, page_number: int) -> tuple[str | None, str | None]:
        clean_title = (section_title or '').strip()
        if not clean_title:
            return None, None
        if clean_title not in section_id_by_title:
            new_section_id = f'{chapter_id}-s{len(sections) + 1:03d}'
            section_id_by_title[clean_title] = new_section_id
            sections.append({
                'section_id': new_section_id,
                'title': clean_title,
                'page_start': page_number,
                'page_end': page_number,
                'chunk_count': 0,
            })
            return new_section_id, clean_title

        existing_section_id = section_id_by_title[clean_title]
        for section_item in sections:
            if section_item['section_id'] == existing_section_id:
                section_item['page_end'] = max(section_item['page_end'], page_number)
                break
        return existing_section_id, clean_title

    if file_extension == '.pdf':
        pages, outline_chapters = _extract_pdf_pages(raw)
        # 收集书签里的起始页码和标题，用来标记每一页属于哪个小节。
        bookmark_entries: list[tuple[int, str]] = []
        for chapter_item in outline_chapters:
            bookmark_entries.append((chapter_item['page_start'], chapter_item['title']))
            for section_item in chapter_item.get('sections', []):
                bookmark_entries.append((section_item['page_start'], section_item['title']))
        bookmark_entries.sort(key=lambda pair: pair[0])

        page_start = pages[0]['page']
        page_end = pages[-1]['page']
        for page_item in pages:
            page_number = page_item['page']
            matched_heading = None
            for bookmark_page, bookmark_title in bookmark_entries:
                if bookmark_page <= page_number:
                    matched_heading = bookmark_title
                else:
                    break

            section_id, section_title = get_or_create_section(matched_heading, page_number)
            page_text = page_item['text']
            for char_start, char_end, is_hard_split in split_spans(page_text, max_chars, overlap):
                chunk_text = page_text[char_start:char_end].strip()
                if not chunk_text:
                    continue
                chunks.append({
                    'chunk_id': f'{doc_id}-p{page_number:04d}-{len(chunks) + 1:05d}',
                    'doc_id': doc_id,
                    'source_file': filename,
                    'source_sha256': file_sha256,
                    'chapter_id': chapter_id,
                    'chapter_title': document_title,
                    'section_id': section_id,
                    'section_title': section_title,
                    'page_start': page_number,
                    'page_end': page_number,
                    'char_start': char_start,
                    'char_end': char_end,
                    'text': chunk_text,
                    'char_count': len(chunk_text),
                    'hard_split': is_hard_split,
                    'review_flags': [],
                    'source_url': f'/api/kbs/{kb_id}/documents/{doc_id}/source#page={page_number}',
                })
    else:
        if file_extension == '.docx':
            text_blocks = _extract_docx_blocks(raw)
        else:
            text_blocks = _extract_text_blocks(raw)

        if not text_blocks:
            raise ValueError('未能从文档中解析出有效正文内容。')

        logical_page = 0
        for heading_title, block_text in text_blocks:
            logical_page += 1
            section_id, section_title = get_or_create_section(heading_title, logical_page)
            for char_start, char_end, is_hard_split in split_spans(block_text, max_chars, overlap):
                chunk_text = block_text[char_start:char_end].strip()
                if not chunk_text:
                    continue
                chunks.append({
                    'chunk_id': f'{doc_id}-p{logical_page:04d}-{len(chunks) + 1:05d}',
                    'doc_id': doc_id,
                    'source_file': filename,
                    'source_sha256': file_sha256,
                    'chapter_id': chapter_id,
                    'chapter_title': document_title,
                    'section_id': section_id,
                    'section_title': section_title,
                    'page_start': logical_page,
                    'page_end': logical_page,
                    'char_start': char_start,
                    'char_end': char_end,
                    'text': chunk_text,
                    'char_count': len(chunk_text),
                    'hard_split': is_hard_split,
                    'review_flags': [],
                    'source_url': f'/api/kbs/{kb_id}/documents/{doc_id}/source',
                })
        page_start = 1
        page_end = max(1, logical_page)

    if not chunks:
        raise ValueError('文档切分后未产生可用文本块，请检查文件内容。')

    # 统计每个小节下面有多少个文本块，方便目录展示。
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

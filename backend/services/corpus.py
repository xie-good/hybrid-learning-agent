"""只读课程仓库，校验数据集和引用的完整性。

仅读取四个固定的预处理产物。校验失败后仍保留健康检查和状态查询，
但不会向调用方提供只加载了一部分的语料。
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from threading import RLock

from backend.config import COURSE_ID, COURSE_NAME, Settings
from backend.errors import AppError

DATA_FILES = ('pages.jsonl', 'cleaned.txt', 'chapters.json', 'chunks.jsonl')
CHAPTER_ID = re.compile(r'ch(?:0[1-9]|1[0-2])\Z')
SHA256 = re.compile(r'[0-9a-f]{64}\Z')


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _integer(value) -> bool:
    return type(value) is int


def _json_lines(raw: bytes) -> list[dict]:
    return [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]


class CorpusRepository:
    """经过校验的内存快照；文件系统变更后需要重新加载应用。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._ready = False
        self._reason: str | None = None
        self._report: dict = {}
        self._chunks: list[dict] = []
        self._by_id: dict[str, dict] = {}
        self._index_by_id: dict[str, int] = {}
        self._chapters: dict[str, dict] = {}
        self._sections: dict[str, tuple[str, dict]] = {}
        self._source_cache: tuple | None = None
        self._source_lock = RLock()
        try:
            self._load()
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
            # 不向外暴露绝对路径、源文件内容或解析器内部细节。
            self._reason = '课程数据缺失或完整性校验失败，请重新执行离线预处理并重启服务。'
        else:
            self._ready = True

    def _load(self) -> None:
        root = Path(self.settings.processed_dir)
        report = self._read_report(root)
        files = self._read_verified_files(root, report)
        chapters, sections = self._read_catalog(files['chapters.json'], report)
        pages = self._read_pages(files['pages.jsonl'], report, chapters, sections)
        chunks, chunks_by_id = self._read_chunks(files['chunks.jsonl'], report, chapters, pages)

        chapter_counts = Counter(chunk['chapter_id'] for chunk in chunks)
        section_counts = Counter(chunk['section_id'] for chunk in chunks)
        for chapter_id, chapter in chapters.items():
            chapter['chunk_count'] = chapter_counts[chapter_id]
            for section in chapter['sections']:
                section['chunk_count'] = section_counts[section['section_id']]
        # 完整校验结束后才发布快照，避免失败时暴露部分语料。
        self._report, self._chunks, self._by_id = report, chunks, chunks_by_id
        self._index_by_id = {chunk['chunk_id']: idx for idx, chunk in enumerate(chunks)}
        self._chapters, self._sections = chapters, sections

    @staticmethod
    def _read_report(root: Path) -> dict:
        report = json.loads((root / 'report.json').read_text('utf-8'))
        _check(isinstance(report, dict), '预处理报告必须是对象。')
        _check(isinstance(report['source_sha256'], str)
               and bool(SHA256.fullmatch(report['source_sha256'])), '源文件哈希值格式无效。')
        _check(isinstance(report['source_file'], str)
               and bool(report['source_file'])
               and '/' not in report['source_file'] and '\\' not in report['source_file'],
               '源文件名称必须是文件名，且不含路径。')
        _check(isinstance(report['cleaning_version'], str), '清洗版本格式无效。')
        _check(report['course_chapter_limit'] == 12, '课程章节范围与预期不符。')
        for key in ('start_page', 'end_page', 'total_pdf_pages', 'included_pages',
                    'chapter_count', 'section_count', 'chunk_count', 'text_chars'):
            _check(_integer(report[key]) and report[key] >= 0, '报告中的统计数量必须是非负整数。')
        _check(1 <= report['start_page'] <= report['end_page'] <= report['total_pdf_pages'],
               '报告中的页码范围无效。')
        return report

    @staticmethod
    def _read_verified_files(root: Path, report: dict) -> dict[str, bytes]:
        files = {}
        for name in DATA_FILES:
            expected = report['output_sha256'][name]
            _check(isinstance(expected, str) and bool(SHA256.fullmatch(expected)), '产物文件的哈希值格式无效。')
            files[name] = (root / name).read_bytes()
            _check(hashlib.sha256(files[name]).hexdigest() == expected, '产物文件内容与报告中的哈希值不一致。')
        return files

    @staticmethod
    def _read_catalog(raw: bytes, report: dict) -> tuple[dict, dict]:
        chapters = json.loads(raw.decode('utf-8'))
        _check(isinstance(chapters, list) and len(chapters) == report['chapter_count']
               and 0 < len(chapters) <= 12, '章节数量与报告不一致。')
        chapter_map, section_map = {}, {}
        previous_end = 0
        for chapter in chapters:
            chapter_id = chapter['chapter_id']
            _check(isinstance(chapter_id, str) and bool(CHAPTER_ID.fullmatch(chapter_id))
                   and chapter_id not in chapter_map, '章节编号无效或重复。')
            _check(isinstance(chapter['title'], str) and bool(chapter['title'].strip()), '章节标题缺失或为空。')
            page_start, page_end = chapter['page_start'], chapter['page_end']
            included_start = chapter.get('included_page_start', page_start)
            included_end = chapter.get('included_page_end', page_end)
            _check(all(_integer(page) for page in (page_start, page_end, included_start, included_end))
                   and previous_end < page_start <= included_start <= included_end <= page_end
                   and report['start_page'] <= included_start <= included_end <= report['end_page'],
                   '章节页码范围无效。')
            previous_end = page_end
            sections = chapter['sections']
            _check(isinstance(sections, list), '小节目录必须是列表。')
            previous_start = page_start
            for index, section in enumerate(sections):
                section_id = section['section_id']
                _check(isinstance(section_id, str) and section_id.startswith(chapter_id + '-s')
                       and section_id not in section_map, '小节编号无效或重复。')
                _check(isinstance(section['title'], str) and bool(section['title'].strip()),
                       '小节标题缺失或为空。')
                _check(_integer(section['page_start'])
                       and previous_start <= section['page_start'] <= page_end, '小节起始页码无效。')
                previous_start = section['page_start']
                section['page_end'] = (sections[index + 1]['page_start'] if index + 1 < len(sections) else page_end)
                section_map[section_id] = (chapter_id, section)
            chapter_map[chapter_id] = chapter
        _check(len(section_map) == report['section_count'], '小节数量与报告不一致。')
        return chapter_map, section_map

    def _read_pages(self, raw: bytes, report: dict, chapters: dict, sections: dict) -> list[dict]:
        pages = _json_lines(raw)
        _check(len(pages) == report['included_pages'] and bool(pages), '入库页面数量与报告不一致。')
        matched_sections = set()
        previous_page = 0
        for page in pages:
            page_number = page['page']
            chapter_id = page['chapter_id']
            _check(_integer(page_number) and previous_page < page_number <= report['end_page']
                   and page_number >= report['start_page'], '页面编号顺序或范围无效。')
            previous_page = page_number
            _check(chapter_id in chapters, '页面不属于已入库的课程章节。')
            chapter = chapters[chapter_id]
            _check(chapter['included_page_start'] <= page_number <= chapter['included_page_end'],
                   '页面编号超出所属章节范围。')
            self._check_metadata(page, report, chapter)
            _check(isinstance(page['text'], str), '页面正文必须是文本。')
            offset = 0
            for segment in page['segments']:
                char_start, char_end = segment['char_start'], segment['char_end']
                _check(_integer(char_start) and _integer(char_end)
                       and char_start == offset < char_end <= len(page['text']),
                       '页面片段的字符偏移范围无效。')
                offset = char_end
                section_id = segment['section_id']
                if section_id is not None:
                    _check(section_id in sections and sections[section_id][0] == chapter_id,
                           '页面片段所属小节与章节不一致。')
                    section = sections[section_id][1]
                    _check(segment['section_title'] == section['title']
                           and section['page_start'] <= page_number <= section['page_end'],
                           '页面片段的小节标题或页码不一致。')
                    matched_sections.add(section_id)
                else:
                    _check(segment['section_title'] is None, '未归属小节的页面片段应使用空的小节标题。')
            _check(offset == len(page['text']), '页面片段未完整覆盖正文。')
        _check(pages[0]['page'] == report['start_page'] and pages[-1]['page'] == report['end_page'],
               '入库页面的起止页码与报告不一致。')
        _check(sum(len(page['text']) for page in pages) == report['text_chars'], '正文字数与报告不一致。')
        if 'matched_section_count' in report:
            _check(len(matched_sections) == report['matched_section_count'], '已匹配小节数量与报告不一致。')
        return pages

    def _read_chunks(self, raw: bytes, report: dict, chapters: dict, pages: list[dict]) -> tuple[list[dict], dict]:
        config = report['chunk_config']
        _check(config['chunking_version'] == 'page-section-char-v1', '分块格式版本不受支持。')
        _check(_integer(config['max_chars']) and config['max_chars'] >= 100
               and _integer(config['overlap']) and 0 <= config['overlap'] < config['max_chars'] // 2,
               '分块长度或重叠参数无效。')
        fingerprint = {'source': report['source_sha256'],
                       'pages_sha256': report['output_sha256']['pages.jsonl'],
                       'cleaning': report['cleaning_version'],
                       'page_start': pages[0]['page'], 'page_end': pages[-1]['page'], **config}
        version = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()[:16]
        _check(report['dataset_version'] == version, '数据集版本与计算结果不一致。')
        chunks = _json_lines(raw)
        _check(len(chunks) == report['chunk_count'] and bool(chunks), '文本块数量与报告不一致。')
        pages_by_id = {page['page']: page for page in pages}
        chunks_by_id = {}
        for index, chunk in enumerate(chunks, 1):
            chapter_id = chunk['chapter_id']
            page_start, page_end = chunk['page_start'], chunk['page_end']
            _check(_integer(page_start) and page_start == page_end and page_start in pages_by_id, '文本块页码无效。')
            page = pages_by_id[page_start]
            _check(chapter_id in chapters and chapter_id == page['chapter_id'], '文本块所属章节与页面不一致。')
            self._check_metadata(chunk, report, chapters[chapter_id])
            _check(chunk['dataset_version'] == version, '文本块包含不一致的数据集版本。')
            chunk_id = chunk['chunk_id']
            _check(chunk_id == f'{version}-p{page_start:04d}-{index:05d}' and chunk_id not in chunks_by_id,
                   '文本块编号无效或重复。')
            char_start, char_end = chunk['char_start'], chunk['char_end']
            _check(_integer(char_start) and _integer(char_end)
                   and 0 <= char_start < char_end <= len(page['text']), '文本块的字符偏移范围无效。')
            text = chunk['text']
            _check(isinstance(text, str) and bool(text.strip()) and text == page['text'][char_start:char_end]
                   and chunk['char_count'] == len(text) <= config['max_chars'], '文本块正文、字数或长度与页面不一致。')
            _check(any(segment['char_start'] <= char_start < char_end <= segment['char_end']
                       and segment['section_id'] == chunk['section_id']
                       and segment['section_title'] == chunk['section_title'] for segment in page['segments']),
                   '文本块的小节信息或字符偏移与页面片段不一致。')
            chunks_by_id[chunk_id] = chunk
        return chunks, chunks_by_id

    @staticmethod
    def _check_metadata(record: dict, report: dict, chapter: dict) -> None:
        _check(all(record[key] == report[key] for key in ('source_file', 'source_sha256', 'cleaning_version')),
               '源文件元数据与报告不一致。')
        _check(record['chapter_title'] == chapter['title'], '章节标题与目录不一致。')
        _check(isinstance(record['review_flags'], list)
               and all(isinstance(flag, str) for flag in record['review_flags']), '复核标记必须是文本列表。')

    @property
    def dataset_version(self) -> str | None:
        return self._report.get('dataset_version')

    @property
    def chunks_sha256(self) -> str | None:
        return self._report.get('output_sha256', {}).get('chunks.jsonl')

    def require_ready(self) -> None:
        if not self._ready:
            raise AppError(503, 'corpus_not_ready', self._reason or '课程数据尚未就绪。')

    def status(self) -> dict:
        return {'ready': self._ready, 'reason': self._reason,
                'dataset_version': self.dataset_version, 'chunk_count': len(self._chunks)}

    def course(self) -> dict:
        self.require_ready()
        return {'course_id': COURSE_ID, 'name': COURSE_NAME, 'course_name': COURSE_NAME,
                'dataset_version': self.dataset_version, 'chapter_count': len(self._chapters),
                'section_count': len(self._sections), 'chunk_count': len(self._chunks),
                'page_start': self._report['start_page'], 'page_end': self._report['end_page'],
                'source_file': self._report['source_file'], 'source_available': self.source_available()}

    def chapters(self) -> list[dict]:
        self.require_ready()
        return deepcopy(list(self._chapters.values()))

    def chapter(self, chapter_id: str) -> dict:
        self.require_ready()
        if chapter_id not in self._chapters:
            raise AppError(404, 'chapter_not_found', '未找到指定章节。')
        return deepcopy(self._chapters[chapter_id])

    def scoped_chunks(self, chapter_id: str | None = None, section_id: str | None = None) -> list[dict]:
        self.require_ready()
        if chapter_id is not None:
            self.chapter(chapter_id)
        if section_id is not None:
            if (section_id not in self._sections
                    or chapter_id is not None and self._sections[section_id][0] != chapter_id):
                raise AppError(404, 'section_not_found', '指定小节不存在或不属于所选章节。')
        return deepcopy([chunk for chunk in self._chunks
                         if (chapter_id is None or chunk['chapter_id'] == chapter_id)
                         and (section_id is None or chunk['section_id'] == section_id)])

    def neighbor_chunks(self, chunk_id: str, window: int = 1) -> list[dict]:
        """获取同章节下相邻的前后文本块，用于补全长回答所需的上下文。"""
        if not self._ready or chunk_id not in self._index_by_id or window <= 0:
            return []
        idx = self._index_by_id[chunk_id]
        anchor = self._chunks[idx]
        neighbors = []
        for pos in range(max(0, idx - window), min(len(self._chunks), idx + window + 1)):
            if pos == idx:
                continue
            candidate = self._chunks[pos]
            if candidate['chapter_id'] == anchor['chapter_id']:
                neighbors.append(deepcopy(candidate))
        return neighbors

    def evidence(self, chunk_id: str) -> dict:
        self.require_ready()
        if chunk_id not in self._by_id:
            raise AppError(404, 'source_not_found', '未找到指定原文证据。')
        chunk = self._by_id[chunk_id]
        fields = ('chunk_id', 'text', 'source_file', 'chapter_id', 'chapter_title',
                  'section_id', 'section_title', 'page_start', 'page_end', 'review_flags')
        result = {key: deepcopy(chunk[key]) for key in fields}
        result.update(citation_id=1, score=None,
                      source_url=f"/api/course/source#page={chunk['page_start']}" if self.source_available() else None)
        return result

    def source_available(self) -> bool:
        try:
            self.source_path()
        except AppError:
            return False
        return True

    def source_path(self) -> Path:
        self.require_ready()
        configured = self.settings.source_pdf or self._report.get('source_path')
        if not configured:
            raise AppError(404, 'source_unavailable', '原始教材 PDF 尚未配置。')
        path = Path(configured).expanduser()
        with self._source_lock:
            try:
                stat = path.stat()
                if not path.is_file():
                    raise OSError('源路径未指向文件。')
                cache_key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
                if self._source_cache is None or self._source_cache[:4] != cache_key:
                    digest = hashlib.sha256()
                    with path.open('rb') as source:
                        for block in iter(lambda: source.read(1024 * 1024), b''):
                            digest.update(block)
                    self._source_cache = (*cache_key, digest.hexdigest() == self._report['source_sha256'])
                if not self._source_cache[4]:
                    raise AppError(409, 'source_hash_mismatch', '教材 PDF 与当前数据版本不匹配，请检查教材配置。')
            except OSError:
                raise AppError(404, 'source_unavailable', '当前环境未找到对应的原始教材 PDF。') from None
        return path.resolve()

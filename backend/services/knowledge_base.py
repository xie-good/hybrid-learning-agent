"""多知识库与自定义文档管理：支持上传、切块并构建 BM25 与向量混合索引。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from threading import RLock
from uuid import uuid4

from backend.config import COURSE_ID, COURSE_NAME, Settings
from backend.errors import AppError
from backend.services.corpus import CorpusRepository
from backend.services.retrieval import (
    BM25Index, INDEX_FORMAT_VERSION, RetrievalService, TOKENIZER_VERSION,
    embedding_fingerprint, fetch_embeddings,
)
from pipeline.ingest_doc import SUPPORTED_EXTENSIONS, parse_uploaded_document

BUILTIN_KB_ID = COURSE_ID
MAX_UPLOAD_BYTES = 30 * 1024 * 1024


def _clean_upload_filename(filename: str) -> str:
    """去掉上传文件名中的路径和特殊符号，避免写入本地目录时出错。"""
    base_name = Path(filename or '').name.strip()
    cleaned_name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', base_name)
    return cleaned_name or 'document.md'


def _guess_media_type(filename: str) -> str:
    """根据文件后缀名返回浏览器在线预览需要的 Content-Type。"""
    extension = Path(filename).suffix.casefold()
    media_type_map = {
        '.pdf': 'application/pdf',
        '.md': 'text/markdown; charset=utf-8',
        '.markdown': 'text/markdown; charset=utf-8',
    }
    return media_type_map.get(extension, 'application/octet-stream')


class CustomCorpusRepository:
    """用户自定义知识库仓库：对外提供与预置课程仓库完全一致的查询方法。"""

    def __init__(self, knowledge_base_dir: Path):
        self.kb_dir = Path(knowledge_base_dir)
        self._ready = False
        self._reason: str | None = None
        self._meta: dict = {}
        self._chapters: dict[str, dict] = {}
        self._sections: dict[str, tuple[str, dict]] = {}
        self._chunks: list[dict] = []
        self._by_id: dict[str, dict] = {}
        self._index_by_id: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        """从硬盘读取知识库信息、章节目录以及切分好的文本块。"""
        meta_path = self.kb_dir / 'kb.json'
        if not meta_path.is_file():
            self._reason = '知识库元数据缺失。'
            return
        self._meta = json.loads(meta_path.read_text('utf-8'))

        chapters_path = self.kb_dir / 'processed' / 'chapters.json'
        chunks_path = self.kb_dir / 'processed' / 'chunks.jsonl'
        if not chapters_path.is_file() or not chunks_path.is_file():
            self._reason = '请先上传至少一份文档以完成知识库索引构建。'
            return

        chapters_list = json.loads(chapters_path.read_text('utf-8'))
        chunks: list[dict] = []
        for line in chunks_path.read_text('utf-8').splitlines():
            if line.strip():
                chunks.append(json.loads(line))

        if not chunks:
            self._reason = '当前知识库尚无可用文本块，请上传包含正文的文档。'
            return

        chapter_lookup: dict[str, dict] = {}
        section_lookup: dict[str, tuple[str, dict]] = {}
        for chapter_item in chapters_list:
            chapter_id = chapter_item['chapter_id']
            chapter_lookup[chapter_id] = chapter_item
            for section_item in chapter_item.get('sections', []):
                section_lookup[section_item['section_id']] = (chapter_id, section_item)

        chunks_by_id: dict[str, dict] = {}
        position_by_id: dict[str, int] = {}
        for index, chunk_item in enumerate(chunks):
            chunk_id = chunk_item['chunk_id']
            chunks_by_id[chunk_id] = chunk_item
            position_by_id[chunk_id] = index

        self._chapters = chapter_lookup
        self._sections = section_lookup
        self._chunks = chunks
        self._by_id = chunks_by_id
        self._index_by_id = position_by_id
        self._ready = True
        self._reason = None

    @property
    def dataset_version(self) -> str | None:
        """返回当前知识库的版本号。"""
        return self._meta.get('dataset_version')

    @property
    def chunks_sha256(self) -> str | None:
        """返回文本块文件的哈希值，用来和索引文件对齐版本。"""
        return self._meta.get('chunks_sha256')

    def require_ready(self) -> None:
        """如果知识库还没有文档或未建好索引，直接抛出 503 提示。"""
        if not self._ready:
            raise AppError(503, 'corpus_not_ready', self._reason or '当前知识库尚未就绪，请先上传文档。')

    def status(self) -> dict:
        """返回当前知识库是否可检索以及文本块总数。"""
        return {
            'ready': self._ready,
            'reason': self._reason,
            'dataset_version': self.dataset_version,
            'chunk_count': len(self._chunks),
        }

    def course(self) -> dict:
        """返回前端展示用的知识库基本信息。"""
        documents = self._meta.get('documents', [])
        first_file = documents[0]['filename'] if documents else ''
        return {
            'course_id': self._meta.get('kb_id', ''),
            'name': self._meta.get('name', '自定义知识库'),
            'course_name': self._meta.get('name', '自定义知识库'),
            'description': self._meta.get('description', ''),
            'dataset_version': self.dataset_version or 'empty',
            'chapter_count': len(self._chapters),
            'section_count': len(self._sections),
            'chunk_count': len(self._chunks),
            'document_count': len(documents),
            'source_file': first_file,
            'source_available': bool(documents),
            'builtin': False,
        }

    def chapters(self) -> list[dict]:
        """返回所有文档或章节目录的深拷贝，防止调用方误改内部数据。"""
        if not self._ready:
            return []
        return deepcopy(list(self._chapters.values()))

    def chapter(self, chapter_id: str) -> dict:
        """获取单个文档或章节的详情。"""
        self.require_ready()
        if chapter_id not in self._chapters:
            raise AppError(404, 'chapter_not_found', '未找到指定文档或章节。')
        return deepcopy(self._chapters[chapter_id])

    def scoped_chunks(self, chapter_id: str | None = None, section_id: str | None = None) -> list[dict]:
        """按指定的文档或小节范围筛选出对应的文本块。"""
        self.require_ready()
        if chapter_id is not None:
            self.chapter(chapter_id)
        if section_id is not None:
            if section_id not in self._sections:
                raise AppError(404, 'section_not_found', '指定小节不存在或不属于所选章节。')
            if chapter_id is not None and self._sections[section_id][0] != chapter_id:
                raise AppError(404, 'section_not_found', '指定小节不存在或不属于所选章节。')

        matched_chunks: list[dict] = []
        for chunk_item in self._chunks:
            if chapter_id is not None and chunk_item['chapter_id'] != chapter_id:
                continue
            if section_id is not None and chunk_item['section_id'] != section_id:
                continue
            matched_chunks.append(deepcopy(chunk_item))
        return matched_chunks

    def neighbor_chunks(self, chunk_id: str, window: int = 1) -> list[dict]:
        """取出同一个文档内紧挨着的前后文本块，给长回答提供完整上下文。"""
        if not self._ready or chunk_id not in self._index_by_id or window <= 0:
            return []
        center_pos = self._index_by_id[chunk_id]
        anchor_chunk = self._chunks[center_pos]
        start_pos = max(0, center_pos - window)
        end_pos = min(len(self._chunks), center_pos + window + 1)

        neighbors: list[dict] = []
        for pos in range(start_pos, end_pos):
            if pos == center_pos:
                continue
            candidate = self._chunks[pos]
            if candidate['chapter_id'] == anchor_chunk['chapter_id']:
                neighbors.append(deepcopy(candidate))
        return neighbors

    def evidence(self, chunk_id: str) -> dict:
        """按文本块编号返回带出处链接的原文证据。"""
        self.require_ready()
        if chunk_id not in self._by_id:
            raise AppError(404, 'source_not_found', '未找到指定原文证据。')
        chunk_item = self._by_id[chunk_id]
        fields = (
            'chunk_id', 'text', 'source_file', 'chapter_id', 'chapter_title',
            'section_id', 'section_title', 'page_start', 'page_end', 'review_flags', 'source_url',
        )
        result = {}
        for field_name in fields:
            result[field_name] = deepcopy(chunk_item.get(field_name))
        result['citation_id'] = 1
        result['score'] = None
        if result.get('review_flags') is None:
            result['review_flags'] = []
        return result

    def document_path(self, doc_id: str) -> tuple[Path, str, str]:
        """根据文档编号查找硬盘上的原文件路径与格式。"""
        for doc_record in self._meta.get('documents', []):
            if doc_record['doc_id'] == doc_id:
                file_path = self.kb_dir / 'raw' / doc_record['stored_name']
                if not file_path.is_file():
                    raise AppError(404, 'source_unavailable', '未找到对应的原始文档文件。')
                return file_path.resolve(), doc_record['filename'], _guess_media_type(doc_record['filename'])
        raise AppError(404, 'document_not_found', '未找到指定文档。')

    def source_path(self) -> Path:
        """返回知识库第一份原文件的路径。"""
        documents = self._meta.get('documents', [])
        if not documents:
            raise AppError(404, 'source_unavailable', '当前知识库尚未上传文档。')
        file_path, _, _ = self.document_path(documents[0]['doc_id'])
        return file_path


class KnowledgeBaseManager:
    """统一管理内置课程与用户自定义知识库，并保证并发上传和检索时数据一致。"""

    def __init__(self, settings: Settings, builtin_corpus: CorpusRepository, builtin_retrieval: RetrievalService):
        self.settings = settings
        self.builtin_corpus = builtin_corpus
        self.builtin_retrieval = builtin_retrieval
        self.root = (Path(settings.database_path).parent / 'custom_kbs').resolve()
        self._lock = RLock()
        self._custom_repos: dict[str, CustomCorpusRepository] = {}
        self._custom_retrievals: dict[str, RetrievalService] = {}
        self._load_all_custom_kbs()

    def _load_all_custom_kbs(self) -> None:
        """启动时扫描磁盘目录，把之前创建过的自定义知识库加载进内存。"""
        if not self.root.is_dir():
            return
        for kb_folder in sorted(self.root.iterdir()):
            if kb_folder.is_dir() and (kb_folder / 'kb.json').is_file():
                self._mount_custom_kb(kb_folder.name)

    def _mount_custom_kb(self, kb_id: str) -> None:
        """挂载或刷新指定自定义知识库的语料仓库和检索服务。"""
        kb_dir = self.root / kb_id
        repository = CustomCorpusRepository(kb_dir)
        kb_settings = replace(
            self.settings,
            processed_dir=kb_dir / 'processed',
            index_dir=kb_dir / 'indexes',
        )
        retrieval_service = RetrievalService(repository, kb_settings)
        self._custom_repos[kb_id] = repository
        self._custom_retrievals[kb_id] = retrieval_service

    def resolve(self, kb_id: str | None = None):
        """根据知识库编号返回对应的 (语料仓库, 检索服务, 实际知识库编号)。"""
        target_id = (kb_id or BUILTIN_KB_ID).strip() or BUILTIN_KB_ID
        if target_id == BUILTIN_KB_ID:
            return self.builtin_corpus, self.builtin_retrieval, BUILTIN_KB_ID
        with self._lock:
            if target_id not in self._custom_repos:
                raise AppError(404, 'kb_not_found', '指定的知识库不存在。')
            return self._custom_repos[target_id], self._custom_retrievals[target_id], target_id

    def list_kbs(self) -> list[dict]:
        """列出预置课程以及用户自建的全部知识库。"""
        builtin_status = self.builtin_corpus.status()
        builtin_ready = builtin_status['ready']
        builtin_chapters = self.builtin_corpus.chapters() if builtin_ready else []
        kb_list = [{
            'kb_id': BUILTIN_KB_ID,
            'name': COURSE_NAME,
            'description': '系统预置课程《Hello-Agents》，涵盖智能体基础、框架、记忆与检索等第 1—12 章正文。',
            'builtin': True,
            'ready': builtin_ready,
            'reason': builtin_status.get('reason'),
            'dataset_version': builtin_status.get('dataset_version') or '',
            'document_count': 1 if builtin_ready else 0,
            'chapter_count': len(builtin_chapters),
            'chunk_count': builtin_status.get('chunk_count', 0),
            'retrieval_modes': self.builtin_retrieval.available_modes(),
            'created_at': '2026-10-26T00:00:00+00:00',
        }]
        with self._lock:
            for kb_id, repository in self._custom_repos.items():
                metadata = repository._meta
                status = repository.status()
                kb_list.append({
                    'kb_id': kb_id,
                    'name': metadata.get('name', kb_id),
                    'description': metadata.get('description', ''),
                    'builtin': False,
                    'ready': status['ready'],
                    'reason': status.get('reason'),
                    'dataset_version': status.get('dataset_version') or 'empty',
                    'document_count': len(metadata.get('documents', [])),
                    'chapter_count': len(repository.chapters()),
                    'chunk_count': status.get('chunk_count', 0),
                    'retrieval_modes': self._custom_retrievals[kb_id].available_modes(),
                    'created_at': metadata.get('created_at', ''),
                })
        return kb_list

    def create_kb(self, name: str, description: str = '') -> dict:
        """在本地新建一个空的自定义知识库目录。"""
        clean_name = name.strip()
        if not clean_name or len(clean_name) > 80:
            raise AppError(422, 'invalid_kb_name', '知识库名称须为 1—80 个字符。')
        clean_desc = description.strip()[:400]
        kb_id = f'kb_{uuid4().hex[:10]}'
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            kb_dir = self.root / kb_id
            (kb_dir / 'raw').mkdir(parents=True, exist_ok=True)
            (kb_dir / 'processed').mkdir(parents=True, exist_ok=True)
            (kb_dir / 'indexes').mkdir(parents=True, exist_ok=True)
            metadata = {
                'kb_id': kb_id,
                'name': clean_name,
                'description': clean_desc,
                'created_at': now,
                'updated_at': now,
                'dataset_version': 'empty',
                'chunks_sha256': '',
                'documents': [],
            }
            (kb_dir / 'kb.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), 'utf-8')
            self._mount_custom_kb(kb_id)
        return self.get_kb_info(kb_id)

    def get_kb_info(self, kb_id: str) -> dict:
        """查找并返回单个知识库的概览信息。"""
        for kb_item in self.list_kbs():
            if kb_item['kb_id'] == kb_id:
                return kb_item
        raise AppError(404, 'kb_not_found', '指定的知识库不存在。')

    def delete_kb(self, kb_id: str) -> None:
        """删除自定义知识库目录和内存中的索引对象。"""
        if kb_id == BUILTIN_KB_ID:
            raise AppError(403, 'builtin_kb_protected', '预置课程知识库不可删除。')
        with self._lock:
            if kb_id not in self._custom_repos:
                raise AppError(404, 'kb_not_found', '指定的知识库不存在。')
            self._custom_repos.pop(kb_id, None)
            self._custom_retrievals.pop(kb_id, None)
            kb_dir = self.root / kb_id
            if kb_dir.exists():
                shutil.rmtree(kb_dir)

    def list_documents(self, kb_id: str) -> list[dict]:
        """列出指定知识库内的所有文档。"""
        if kb_id == BUILTIN_KB_ID:
            course_info = self.builtin_corpus.course()
            return [{
                'doc_id': 'builtin_hello_agents',
                'filename': course_info['source_file'],
                'media_type': 'application/pdf',
                'size_bytes': 0,
                'chapter_id': 'ch01',
                'chapter_title': course_info['name'],
                'page_count': course_info['page_end'],
                'chunk_count': course_info['chunk_count'],
                'uploaded_at': '2026-10-26T00:00:00+00:00',
                'builtin': True,
            }]
        with self._lock:
            if kb_id not in self._custom_repos:
                raise AppError(404, 'kb_not_found', '指定的知识库不存在。')
            document_list: list[dict] = []
            for doc_record in self._custom_repos[kb_id]._meta.get('documents', []):
                item = dict(doc_record)
                item['builtin'] = False
                document_list.append(item)
            return document_list

    def list_chunks(self, kb_id: str, chapter_id: str | None = None, limit: int = 30, offset: int = 0) -> dict:
        """分页获取知识库里的切分文本块。"""
        repository, _, _ = self.resolve(kb_id)
        if not repository.status()['ready']:
            return {'items': [], 'total': 0, 'limit': limit, 'offset': offset}
        scoped_chunks = repository.scoped_chunks(chapter_id=chapter_id)
        total = len(scoped_chunks)
        page_items = scoped_chunks[offset:offset + limit]
        return {'items': page_items, 'total': total, 'limit': limit, 'offset': offset}

    def upload_document(self, kb_id: str, filename: str, raw: bytes) -> dict:
        """校验上传文件并写入知识库，然后重新构建混合检索索引。"""
        if kb_id == BUILTIN_KB_ID:
            raise AppError(403, 'builtin_kb_readonly', '预置课程不可直接修改，请先新建或选择自定义知识库。')
        if not raw:
            raise AppError(422, 'empty_upload_file', '上传文件不能为空。')
        if len(raw) > MAX_UPLOAD_BYTES:
            raise AppError(422, 'upload_too_large', '单个文件大小不能超过 30 MB。')

        safe_filename = _clean_upload_filename(filename)
        file_extension = Path(safe_filename).suffix.casefold()
        if file_extension not in SUPPORTED_EXTENSIONS:
            raise AppError(422, 'unsupported_file_type', f'暂不支持 {file_extension or "未知"} 格式，仅支持 PDF (.pdf) 与 Markdown (.md)。')

        file_hash = hashlib.sha256(raw).hexdigest()
        with self._lock:
            if kb_id not in self._custom_repos:
                raise AppError(404, 'kb_not_found', '指定的知识库不存在。')
            kb_dir = self.root / kb_id
            metadata = deepcopy(self._custom_repos[kb_id]._meta)

            for existing_doc in metadata['documents']:
                if existing_doc['sha256'] == file_hash:
                    raise AppError(409, 'duplicate_document', '该知识库中已存在内容完全相同的文档。')

            doc_id = f'doc_{uuid4().hex[:8]}'
            stored_name = f'{doc_id}_{safe_filename}'
            next_chapter_id = f'ch{len(metadata["documents"]) + 1:02d}'

            # 先尝试解析文本与切片；如果解析出错则立刻停止，不破坏现有知识库。
            try:
                chapter_info, parsed_chunks = parse_uploaded_document(
                    doc_id=doc_id,
                    filename=safe_filename,
                    raw=raw,
                    chapter_id=next_chapter_id,
                    kb_id=kb_id,
                )
            except ValueError as exc:
                raise AppError(422, 'document_parse_failed', str(exc)) from None

            existing_repo = self._custom_repos[kb_id]
            doc_record = {
                'doc_id': doc_id,
                'filename': safe_filename,
                'stored_name': stored_name,
                'media_type': _guess_media_type(safe_filename),
                'size_bytes': len(raw),
                'sha256': file_hash,
                'chapter_id': next_chapter_id,
                'chapter_title': chapter_info['title'],
                'page_count': chapter_info['page_end'],
                'chunk_count': len(parsed_chunks),
                'uploaded_at': datetime.now(timezone.utc).isoformat(),
            }
            # 优先复用内存中已有文档的解析结果，只追加本次新文档，避免重复解析旧文件。
            if existing_repo.status()['ready'] and len(existing_repo._chapters) == len(metadata['documents']):
                chapters = existing_repo.chapters()
                all_chunks = deepcopy(existing_repo._chunks)
                chapters.append(chapter_info)
                all_chunks.extend(parsed_chunks)
                precomputed = (chapters, all_chunks)
            else:
                precomputed = None

            metadata['documents'].append(doc_record)
            saved_raw_path = kb_dir / 'raw' / stored_name
            if precomputed is not None:
                # 先增量计算新增切片的向量（最易因网络/上游失败），成功后再统一写盘，保证异常时原库完好。
                vector_bundle = self._prepare_incremental_vectors(kb_dir, precomputed[1])
                saved_raw_path.write_bytes(raw)
                try:
                    self._rebuild_custom_kb_locked(
                        kb_dir,
                        metadata,
                        precomputed=precomputed,
                        vector_bundle=vector_bundle,
                    )
                except Exception:
                    saved_raw_path.unlink(missing_ok=True)
                    raise
            else:
                saved_raw_path.write_bytes(raw)
                try:
                    self._rebuild_custom_kb_locked(kb_dir, metadata)
                except Exception:
                    saved_raw_path.unlink(missing_ok=True)
                    raise
            return {'document': doc_record, 'kb': self.get_kb_info(kb_id)}

    def delete_document(self, kb_id: str, doc_id: str) -> dict:
        """删除自定义知识库中的一份文档，并增量更新索引（复用剩余文档切片与向量）。"""
        if kb_id == BUILTIN_KB_ID:
            raise AppError(403, 'builtin_kb_readonly', '预置课程不可删除文档。')
        with self._lock:
            if kb_id not in self._custom_repos:
                raise AppError(404, 'kb_not_found', '指定的知识库不存在。')
            kb_dir = self.root / kb_id
            existing_repo = self._custom_repos[kb_id]
            metadata = deepcopy(existing_repo._meta)

            target_doc = None
            remaining_docs: list[dict] = []
            for doc_record in metadata['documents']:
                if doc_record['doc_id'] == doc_id:
                    target_doc = doc_record
                else:
                    remaining_docs.append(doc_record)

            if target_doc is None:
                raise AppError(404, 'document_not_found', '未找到指定文档。')

            metadata['documents'] = remaining_docs
            precomputed = None
            if remaining_docs and existing_repo.status()['ready']:
                precomputed = self._filter_and_reindex_existing(existing_repo, metadata, doc_id)

            (kb_dir / 'raw' / target_doc['stored_name']).unlink(missing_ok=True)
            self._rebuild_custom_kb_locked(kb_dir, metadata, precomputed=precomputed)
            return {'deleted_doc_id': doc_id, 'kb': self.get_kb_info(kb_id)}

    def _clear_empty_kb_files(self, kb_dir: Path, metadata: dict) -> None:
        """当知识库没有任何文档时，清理旧的切块与索引文件。"""
        processed_dir = kb_dir / 'processed'
        index_dir = kb_dir / 'indexes'
        for filename in ('chapters.json', 'chunks.jsonl'):
            (processed_dir / filename).unlink(missing_ok=True)
        for filename in ('bm25.index.json', 'vector.index.json', 'manifest.json'):
            (index_dir / filename).unlink(missing_ok=True)

        metadata['dataset_version'] = 'empty'
        metadata['chunks_sha256'] = ''
        metadata['updated_at'] = datetime.now(timezone.utc).isoformat()
        (kb_dir / 'kb.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), 'utf-8')
        self._mount_custom_kb(metadata['kb_id'])

    def _collect_documents_chunks(self, kb_dir: Path, metadata: dict) -> tuple[list[dict], list[dict]]:
        """把知识库内保留的每份文档按顺序重新编号并切分成文本块。"""
        kb_id = metadata['kb_id']
        chapters: list[dict] = []
        all_chunks: list[dict] = []

        for index, doc_record in enumerate(metadata['documents'], start=1):
            chapter_id = f'ch{index:02d}'
            doc_record['chapter_id'] = chapter_id
            raw_bytes = (kb_dir / 'raw' / doc_record['stored_name']).read_bytes()
            chapter_info, doc_chunks = parse_uploaded_document(
                doc_id=doc_record['doc_id'],
                filename=doc_record['filename'],
                raw=raw_bytes,
                chapter_id=chapter_id,
                kb_id=kb_id,
            )
            doc_record['chunk_count'] = len(doc_chunks)
            doc_record['chapter_title'] = chapter_info['title']
            chapters.append(chapter_info)
            all_chunks.extend(doc_chunks)

        return chapters, all_chunks

    def _write_processed_corpus(self, kb_dir: Path, metadata: dict, chapters: list[dict], all_chunks: list[dict]) -> tuple[str, str]:
        """把切好的章节目录、文本块和版本号写到 processed 目录。"""
        processed_dir = kb_dir / 'processed'
        processed_dir.mkdir(parents=True, exist_ok=True)

        lines_before_version: list[str] = []
        for chunk_item in all_chunks:
            lines_before_version.append(json.dumps(chunk_item, ensure_ascii=False) + '\n')
        initial_hash = hashlib.sha256(''.join(lines_before_version).encode('utf-8')).hexdigest()
        dataset_version = initial_hash[:16]

        lines_with_version: list[str] = []
        for chunk_item in all_chunks:
            chunk_item['dataset_version'] = dataset_version
            lines_with_version.append(json.dumps(chunk_item, ensure_ascii=False) + '\n')

        chunks_bytes = ''.join(lines_with_version).encode('utf-8')
        chunks_sha256 = hashlib.sha256(chunks_bytes).hexdigest()

        (processed_dir / 'chapters.json').write_text(json.dumps(chapters, ensure_ascii=False, indent=2), 'utf-8')
        (processed_dir / 'chunks.jsonl').write_bytes(chunks_bytes)

        metadata['dataset_version'] = dataset_version
        metadata['chunks_sha256'] = chunks_sha256
        metadata['updated_at'] = datetime.now(timezone.utc).isoformat()
        (kb_dir / 'kb.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), 'utf-8')
        return dataset_version, chunks_sha256

    def _filter_and_reindex_existing(
        self,
        existing_repo: CustomCorpusRepository,
        metadata: dict,
        removed_doc_id: str,
    ) -> tuple[list[dict], list[dict]] | None:
        """删除文档时直接过滤内存中的已有章节与切片，并按新顺序重排 chapter_id/section_id。"""
        chapters_by_doc: dict[str, dict] = {}
        for chapter_item in existing_repo.chapters():
            doc_id = chapter_item.get('doc_id')
            if doc_id and doc_id != removed_doc_id:
                chapters_by_doc[doc_id] = chapter_item

        if len(chapters_by_doc) != len(metadata['documents']):
            return None

        reindexed_chapters: list[dict] = []
        doc_to_new_chapter: dict[str, str] = {}
        section_id_map: dict[str, str] = {}
        for index, doc_record in enumerate(metadata['documents'], start=1):
            doc_id = doc_record['doc_id']
            new_chapter_id = f'ch{index:02d}'
            doc_record['chapter_id'] = new_chapter_id
            doc_to_new_chapter[doc_id] = new_chapter_id

            chapter_item = chapters_by_doc[doc_id]
            chapter_item['chapter_id'] = new_chapter_id
            for sec_index, section_item in enumerate(chapter_item.get('sections', []), start=1):
                old_section_id = section_item['section_id']
                new_section_id = f'{new_chapter_id}-s{sec_index:03d}'
                section_id_map[old_section_id] = new_section_id
                section_item['section_id'] = new_section_id
            reindexed_chapters.append(chapter_item)

        remaining_chunks: list[dict] = []
        for chunk_item in existing_repo._chunks:
            doc_id = chunk_item.get('doc_id')
            if doc_id == removed_doc_id or doc_id not in doc_to_new_chapter:
                continue
            updated_chunk = deepcopy(chunk_item)
            updated_chunk['chapter_id'] = doc_to_new_chapter[doc_id]
            old_section_id = updated_chunk.get('section_id')
            if old_section_id in section_id_map:
                updated_chunk['section_id'] = section_id_map[old_section_id]
            remaining_chunks.append(updated_chunk)

        return reindexed_chapters, remaining_chunks

    def _load_reusable_vectors(self, kb_dir: Path, fingerprint: str) -> tuple[dict[str, list[float]], int | None]:
        """读取现有向量索引中与当前模型一致的缓存，返回 (chunk_id -> vector, 维度)。"""
        vector_path = kb_dir / 'indexes' / 'vector.index.json'
        if not vector_path.is_file():
            return {}, None
        try:
            payload = json.loads(vector_path.read_text('utf-8'))
        except Exception:
            return {}, None

        if (
            payload.get('format_version') != INDEX_FORMAT_VERSION
            or payload.get('embedding_model') != self.settings.embedding_model
            or payload.get('embedding_fingerprint') != fingerprint
        ):
            return {}, None

        dimension = payload.get('dimension')
        chunk_ids = payload.get('chunk_ids')
        vectors = payload.get('vectors')
        if (
            not isinstance(dimension, int)
            or dimension <= 0
            or not isinstance(chunk_ids, list)
            or not isinstance(vectors, list)
            or len(chunk_ids) != len(vectors)
        ):
            return {}, None

        cached: dict[str, list[float]] = {}
        for chunk_id, vector in zip(chunk_ids, vectors):
            if isinstance(chunk_id, str) and isinstance(vector, list) and len(vector) == dimension:
                cached[chunk_id] = vector
        return cached, dimension

    def _prepare_incremental_vectors(
        self,
        kb_dir: Path,
        all_chunks: list[dict],
    ) -> tuple[list[list[float]] | None, int | None, str | None]:
        """增量构建向量列表：已有切片直接复用缓存，仅对新增或缺失的切片调用向量模型。"""
        has_embedding = bool(self.settings.embedding_base_url.strip() and self.settings.embedding_model.strip())
        if not has_embedding:
            return None, None, None

        fingerprint = embedding_fingerprint(self.settings)
        cached_vectors, vector_dimension = self._load_reusable_vectors(kb_dir, fingerprint)

        missing_chunks = [chunk for chunk in all_chunks if chunk['chunk_id'] not in cached_vectors]
        if missing_chunks:
            batch_size = 32
            for offset in range(0, len(missing_chunks), batch_size):
                batch_chunks = missing_chunks[offset:offset + batch_size]
                batch_texts = [chunk['text'] for chunk in batch_chunks]
                batch_vectors = fetch_embeddings(self.settings, batch_texts)
                if len(batch_vectors) != len(batch_chunks):
                    raise AppError(502, 'embedding_count_mismatch', '向量服务返回条数与请求文本数不一致。')

                if vector_dimension is None:
                    vector_dimension = len(batch_vectors[0])
                for chunk_item, vector in zip(batch_chunks, batch_vectors):
                    if len(vector) != vector_dimension:
                        raise AppError(502, 'embedding_dimension_mismatch', '向量服务批次维数不一致，索引构建中止。')
                    cached_vectors[chunk_item['chunk_id']] = vector

        ordered_vectors = [cached_vectors[chunk['chunk_id']] for chunk in all_chunks]
        return ordered_vectors, vector_dimension, fingerprint

    def _build_bm25_and_vector_indexes(
        self,
        kb_dir: Path,
        repository: CustomCorpusRepository,
        all_chunks: list[dict],
        dataset_version: str,
        chunks_sha256: str,
        vector_bundle: tuple[list[list[float]] | None, int | None, str | None] | None = None,
    ) -> None:
        """构建 BM25 稀疏索引，并写入增量复用后的向量索引。"""
        index_dir = kb_dir / 'indexes'
        index_dir.mkdir(parents=True, exist_ok=True)

        if vector_bundle is None:
            ordered_vectors, vector_dimension, fingerprint = self._prepare_incremental_vectors(kb_dir, all_chunks)
        else:
            ordered_vectors, vector_dimension, fingerprint = vector_bundle

        bm25_index = BM25Index(all_chunks)
        index_payloads = {'bm25.index.json': bm25_index.payload(repository)}

        if ordered_vectors is not None and vector_dimension is not None and fingerprint is not None:
            index_payloads['vector.index.json'] = {
                'format_version': INDEX_FORMAT_VERSION,
                'dataset_version': dataset_version,
                'chunks_sha256': chunks_sha256,
                'embedding_model': self.settings.embedding_model,
                'embedding_fingerprint': fingerprint,
                'dimension': vector_dimension,
                'chunk_ids': bm25_index.ids,
                'vectors': ordered_vectors,
            }
        else:
            (index_dir / 'vector.index.json').unlink(missing_ok=True)

        file_hashes: dict[str, str] = {}
        for filename, payload in index_payloads.items():
            json_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n'
            file_bytes = json_text.encode('utf-8')
            (index_dir / filename).write_bytes(file_bytes)
            file_hashes[filename] = hashlib.sha256(file_bytes).hexdigest()

        manifest = {
            'format_version': INDEX_FORMAT_VERSION,
            'dataset_version': dataset_version,
            'chunks_sha256': chunks_sha256,
            'tokenizer_version': TOKENIZER_VERSION,
            'chunk_count': len(all_chunks),
            'files': file_hashes,
        }
        (index_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', 'utf-8')

    def _rebuild_custom_kb_locked(
        self,
        kb_dir: Path,
        metadata: dict,
        precomputed: tuple[list[dict], list[dict]] | None = None,
        vector_bundle: tuple[list[list[float]] | None, int | None, str | None] | None = None,
    ) -> None:
        """文档变化后，按“复用/切片 → 写语料 → 增量建混合索引 → 热加载”四步更新知识库。"""
        if not metadata['documents']:
            self._clear_empty_kb_files(kb_dir, metadata)
            return

        if precomputed is not None:
            chapters, all_chunks = precomputed
        else:
            chapters, all_chunks = self._collect_documents_chunks(kb_dir, metadata)

        if vector_bundle is None:
            vector_bundle = self._prepare_incremental_vectors(kb_dir, all_chunks)

        dataset_version, chunks_sha256 = self._write_processed_corpus(kb_dir, metadata, chapters, all_chunks)
        repository = CustomCorpusRepository(kb_dir)
        self._build_bm25_and_vector_indexes(
            kb_dir,
            repository,
            all_chunks,
            dataset_version,
            chunks_sha256,
            vector_bundle=vector_bundle,
        )
        self._mount_custom_kb(metadata['kb_id'])

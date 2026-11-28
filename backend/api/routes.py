"""HTTP 接口层：校验请求参数、调用检索与学习服务，并返回结构化结果。"""
import io
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
import pypdfium2 as pdfium

from backend.config import COURSE_ID
from backend.errors import AppError
from backend.schemas.models import (
    ChapterInfo, ChapterList, ChapterRequest, ChunkPreviewListResponse, Citation,
    CourseResponse, DeletedResponse, DocumentDeleteResponse, DocumentListResponse,
    DocumentUploadResponse, ErrorResponse, HealthResponse, HistoryItem,
    HistoryResponse, KnowledgeBaseCreateRequest, KnowledgeBaseId, KnowledgeBaseInfo,
    KnowledgeBaseListResponse, QAResponse, QuestionRequest, QuizFromQARequest,
    QuizRequest, QuizResponse, SummaryResponse,
)
from backend.services.retrieval import build_expanded_contexts

ERRORS = {
    403: {'model': ErrorResponse, 'description': '受保护的内置资源不可修改'},
    404: {'model': ErrorResponse, 'description': '资源不存在或不属于该会话'},
    409: {'model': ErrorResponse, 'description': '原文件冲突或重复上传'},
    422: {'model': ErrorResponse, 'description': '参数或文件解析错误'},
    500: {'model': ErrorResponse, 'description': '内部处理失败'},
    502: {'model': ErrorResponse, 'description': '模型上游或输出校验失败'},
    503: {'model': ErrorResponse, 'description': '数据、索引、模型配置或存储未就绪'},
    504: {'model': ErrorResponse, 'description': '模型超时'},
}
router = APIRouter(prefix='/api', responses=ERRORS)


def _build_metadata(request: Request, started_at: float, chapter_id=None, section_id=None, *, repository=None):
    """组装所有业务响应共用的耗时、数据版本与检索范围信息。"""
    if chapter_id is None and section_id:
        chapter_id = section_id.split('-')[0]
    active_repository = repository or request.app.state.corpus
    dataset_version = active_repository.status().get('dataset_version') or 'empty'
    elapsed_ms = round((perf_counter() - started_at) * 1000, 3)
    return {
        'request_id': request.state.request_id,
        'dataset_version': dataset_version,
        'latency_ms': elapsed_ms,
        'scope': {'chapter_id': chapter_id, 'section_id': section_id},
    }


def _get_history_store(request: Request):
    """获取历史记录存储实例；未初始化时返回明确的 503 错误。"""
    history_store = request.app.state.history
    if history_store is None:
        raise AppError(503, 'HISTORY_UNAVAILABLE', '历史存储尚未就绪。')
    return history_store


def _resolve_knowledge_base(request: Request, knowledge_base_id: str | None = None):
    """根据知识库编号获取对应的语料仓库和检索服务。"""
    return request.app.state.kb_manager.resolve(knowledge_base_id)


@router.get('/health', tags=['状态'], response_model=HealthResponse, summary='服务、语料与配置就绪状态')
def health(request: Request, kb_id: KnowledgeBaseId | None = None):
    """检查当前知识库、检索索引、模型配置和历史数据库是否就绪。"""
    app_state = request.app.state
    repository, retrieval_service, _ = _resolve_knowledge_base(request, kb_id)
    corpus_status = repository.status()
    generation_ready = app_state.settings.generation_mode == 'extractive' or bool(
        app_state.settings.llm_base_url.strip() and app_state.settings.llm_model.strip()
    )
    history_ready = app_state.history is not None
    available_modes = retrieval_service.available_modes()
    retrieval_ready = app_state.settings.default_retrieval_mode in available_modes
    all_ready = corpus_status['ready'] and retrieval_ready and generation_ready and history_ready

    return {
        'status': 'ok' if all_ready else 'degraded',
        'stage': 'api_v1',
        'knowledge_base_ready': corpus_status['ready'],
        'dataset_version': corpus_status.get('dataset_version'),
        'chunk_count': corpus_status.get('chunk_count', 0),
        'retrieval_modes': available_modes,
        'default_retrieval_mode': app_state.settings.default_retrieval_mode,
        'retrieval_ready': retrieval_ready,
        'generation_mode': app_state.settings.generation_mode,
        'generation_ready': generation_ready,
        'history_ready': history_ready,
        'reason': corpus_status.get('reason'),
    }


@router.get('/kbs', tags=['知识库管理'], response_model=KnowledgeBaseListResponse, summary='列出预置课程与用户自定义知识库')
def list_kbs(request: Request):
    """返回所有知识库的列表与索引就绪状态。"""
    return {'items': request.app.state.kb_manager.list_kbs()}


@router.post('/kbs', tags=['知识库管理'], response_model=KnowledgeBaseInfo, status_code=201, summary='新建自定义学习知识库')
def create_kb(body: KnowledgeBaseCreateRequest, request: Request):
    """创建一个新的自定义知识库。"""
    return request.app.state.kb_manager.create_kb(body.name, body.description)


@router.delete('/kbs/{kb_id}', tags=['知识库管理'], status_code=204, summary='删除自定义知识库')
def delete_kb(kb_id: KnowledgeBaseId, request: Request):
    """删除指定的自定义知识库及其索引文件。"""
    request.app.state.kb_manager.delete_kb(kb_id)
    return Response(status_code=204)


@router.get('/kbs/{kb_id}/documents', tags=['知识库管理'], response_model=DocumentListResponse, summary='查看知识库内的文档列表')
def list_kb_documents(kb_id: KnowledgeBaseId, request: Request):
    """查看某个知识库下已经上传的所有文档。"""
    return {'kb_id': kb_id, 'items': request.app.state.kb_manager.list_documents(kb_id)}


@router.post('/kbs/{kb_id}/documents', tags=['知识库管理'], response_model=DocumentUploadResponse, status_code=201, summary='上传文档并构建混合检索索引')
async def upload_kb_document(kb_id: KnowledgeBaseId, request: Request, file: UploadFile = File(...)):
    """接收上传的学习文档，完成解析、切块并重建 BM25 与向量索引。"""
    file_bytes = await file.read()
    filename = file.filename or 'document.md'
    return request.app.state.kb_manager.upload_document(kb_id, filename, file_bytes)


@router.delete('/kbs/{kb_id}/documents/{doc_id}', tags=['知识库管理'], response_model=DocumentDeleteResponse, summary='移除知识库中的指定文档并更新索引')
def delete_kb_document(kb_id: KnowledgeBaseId, doc_id: str, request: Request):
    """从自定义知识库中移除一份文档并重新构建索引。"""
    return request.app.state.kb_manager.delete_document(kb_id, doc_id)


@router.get('/kbs/{kb_id}/documents/{doc_id}/source', tags=['知识库管理'], summary='在线查看上传的原始文档')
def view_kb_document_source(kb_id: KnowledgeBaseId, doc_id: str, request: Request):
    """返回原始文件以便在浏览器中预览或下载。"""
    if kb_id == COURSE_ID:
        source_pdf_path = request.app.state.corpus.source_path()
        return FileResponse(
            source_pdf_path,
            media_type='application/pdf',
            filename=source_pdf_path.name,
            content_disposition_type='inline',
        )
    repository, _, _ = _resolve_knowledge_base(request, kb_id)
    file_path, filename, media_type = repository.document_path(doc_id)
    return FileResponse(file_path, media_type=media_type, filename=filename, content_disposition_type='inline')


@router.get('/kbs/{kb_id}/documents/{doc_id}/page/{page_num}', tags=['知识库管理'], summary='把 PDF 指定页渲染为纯白底 PNG 图片')
def render_pdf_page(kb_id: KnowledgeBaseId, doc_id: str, page_num: int, request: Request):
    """按页把 PDF 渲染成清晰图片，供前端无黑边伴读预览。"""
    if page_num < 1:
        raise AppError(422, 'invalid_page_num', '页码必须大于等于 1。')

    if kb_id == COURSE_ID:
        pdf_path = request.app.state.corpus.source_path()
    else:
        repository, _, _ = _resolve_knowledge_base(request, kb_id)
        pdf_path, filename, _ = repository.document_path(doc_id)
        if not filename.lower().endswith('.pdf'):
            raise AppError(422, 'not_a_pdf', '只有 PDF 文档支持按页渲染预览。')

    try:
        pdf_doc = pdfium.PdfDocument(str(pdf_path))
    except Exception:
        raise AppError(500, 'pdf_open_failed', '无法打开该 PDF 文件进行预览。') from None

    try:
        total_pages = len(pdf_doc)
        if page_num > total_pages:
            raise AppError(404, 'page_not_found', f'页码超出范围，该文档共有 {total_pages} 页。')
        page = pdf_doc[page_num - 1]
        img = page.render(scale=1.6).to_pil()
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return Response(content=buf.getvalue(), media_type='image/png')
    finally:
        pdf_doc.close()


@router.get('/kbs/{kb_id}/chunks', tags=['知识库管理'], response_model=ChunkPreviewListResponse, summary='分页浏览知识库切分后的文本块')
def list_kb_chunks(
    kb_id: KnowledgeBaseId,
    request: Request,
    chapter_id: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """分页返回切分后的文本块，方便核对文档解析结果。"""
    return request.app.state.kb_manager.list_chunks(kb_id, chapter_id=chapter_id, limit=limit, offset=offset)


@router.get('/course', tags=['课程与来源'], response_model=CourseResponse, summary='当前知识库基本信息与数据版本')
def course(request: Request, kb_id: KnowledgeBaseId | None = None):
    """返回指定知识库的名称、章节数和文本块数量。"""
    repository, _, _ = _resolve_knowledge_base(request, kb_id)
    return repository.course()


@router.get('/chapters', tags=['课程与来源'], response_model=ChapterList, summary='已入库的章、节或文档目录')
def chapters(request: Request, kb_id: KnowledgeBaseId | None = None):
    """返回指定知识库的章节与小节列表。"""
    repository, _, active_kb_id = _resolve_knowledge_base(request, kb_id)
    dataset_version = repository.status().get('dataset_version') or ''
    return {'course_id': active_kb_id, 'dataset_version': dataset_version, 'chapters': repository.chapters()}


@router.get('/chapters/{chapter_id}', tags=['课程与来源'], response_model=ChapterInfo, summary='章节详情与覆盖范围')
def chapter(chapter_id: str, request: Request, kb_id: KnowledgeBaseId | None = None):
    """返回单个章节或文档的详细信息。"""
    repository, _, _ = _resolve_knowledge_base(request, kb_id)
    return repository.chapter(chapter_id)


@router.get('/sources/{chunk_id}', tags=['课程与来源'], response_model=Citation, summary='核对原文、章节与物理页码')
def source(chunk_id: str, request: Request, kb_id: KnowledgeBaseId | None = None):
    """根据文本块编号返回完整的原文及来源位置。"""
    repository, _, _ = _resolve_knowledge_base(request, kb_id)
    return repository.evidence(chunk_id)


@router.get(
    '/course/source',
    tags=['课程与来源'],
    response_class=FileResponse,
    summary='原 PDF（支持 #page=N 定位）',
    responses={200: {'description': '原 PDF，可使用 #page=N 定位', 'content': {'application/pdf': {}}}},
)
def course_source(request: Request, kb_id: KnowledgeBaseId | None = None):
    """返回知识库对应的原始 PDF 文件。"""
    repository, _, _ = _resolve_knowledge_base(request, kb_id)
    source_pdf_path = repository.source_path()
    return FileResponse(
        source_pdf_path,
        media_type='application/pdf',
        filename=source_pdf_path.name,
        content_disposition_type='inline',
    )


@router.post('/qa', tags=['问答'], response_model=QAResponse, summary='多轮指代补全、混合检索证据并生成深度回答')
def question_answer(question_request: QuestionRequest, request: Request):
    """执行一次问答：先结合历史补全指代，再用混合检索找证据，最后生成带引用的回答。"""
    started_at = perf_counter()
    app_state = request.app.state
    history_store = _get_history_store(request)
    repository, retrieval_service, active_kb_id = _resolve_knowledge_base(request, question_request.kb_id)

    # 第一步：获取当前会话近期历史，并在需要时补全追问里的省略词（如“它”“这个方法”）。
    session_id = str(question_request.session_id or uuid4())
    if question_request.session_id:
        recent_turns = history_store.recent(session_id, knowledge_base_id=active_kb_id, limit=4)
    else:
        recent_turns = []

    search_query = app_state.generation.rewrite_query(question_request.question, recent_turns)
    rewritten_question = search_query if search_query != question_request.question else None

    # 第二步：执行 BM25 / 向量 / 混合检索，并校验返回的引用格式。
    retrieval_mode = question_request.retrieval_mode or app_state.settings.default_retrieval_mode
    retrieval_result = retrieval_service.search(
        search_query,
        chapter_id=question_request.chapter_id,
        section_id=question_request.section_id,
        top_k=question_request.top_k,
        mode=retrieval_mode,
        debug=question_request.debug,
    )
    citations = []
    for raw_citation in retrieval_result['citations']:
        validated = Citation.model_validate(raw_citation).model_dump()
        citations.append(validated)

    # 第三步：大模型模式下，为命中切片补充前后相邻段落，再结合历史生成结构化教学回答。
    expanded_contexts = {}
    if app_state.generation.mode == 'llm':
        expanded_contexts = build_expanded_contexts(repository, citations)

    answer_result = app_state.generation.answer(
        question_request.question,
        citations,
        history=recent_turns or None,
        expanded_contexts=expanded_contexts or None,
    )

    debug_info = retrieval_result.get('debug') if question_request.debug else None
    metadata = _build_metadata(
        request, started_at, question_request.chapter_id, question_request.section_id, repository=repository
    )
    qa_response = {
        **answer_result,
        **metadata,
        'kb_id': active_kb_id,
        'rewritten_question': rewritten_question,
        'citations': citations,
        'retrieval_mode': retrieval_result['retrieval_mode'],
        'session_id': session_id,
        'debug': debug_info,
    }

    # 第四步：先校验完整响应格式，确认无误后再存入 SQLite 历史表。
    QAResponse.model_validate(dict(qa_response, history_id='pending'))
    history_payload = dict(qa_response)
    history_payload.pop('debug', None)
    history_payload['question'] = question_request.question
    qa_response['history_id'] = history_store.add(history_payload)
    return qa_response


@router.post('/summary', tags=['学习辅助'], response_model=SummaryResponse, summary='生成指定章或节的有来源总结')
def chapter_summary(summary_request: ChapterRequest, request: Request):
    """围绕指定章节或文档生成带出处引用的重点总结。"""
    started_at = perf_counter()
    repository, _, active_kb_id = _resolve_knowledge_base(request, summary_request.kb_id)
    summary_result = request.app.state.learning.summary(
        summary_request.chapter_id,
        section_id=summary_request.section_id,
        repo=repository,
    )
    metadata = _build_metadata(
        request, started_at, summary_request.chapter_id, summary_request.section_id, repository=repository
    )
    return {**summary_result, **metadata, 'kb_id': active_kb_id}


@router.post('/quiz', tags=['学习辅助'], response_model=QuizResponse, summary='生成带答案、解析和引用的练习')
def chapter_quiz(quiz_request: QuizRequest, request: Request):
    """围绕指定章节或文档生成单选与简答自测题。"""
    started_at = perf_counter()
    repository, _, active_kb_id = _resolve_knowledge_base(request, quiz_request.kb_id)
    quiz_result = request.app.state.learning.quiz(
        quiz_request.chapter_id,
        section_id=quiz_request.section_id,
        count=quiz_request.count,
        question_types=quiz_request.question_types,
        difficulty=quiz_request.difficulty,
        repo=repository,
    )
    metadata = _build_metadata(
        request, started_at, quiz_request.chapter_id, quiz_request.section_id, repository=repository
    )
    return {**quiz_result, **metadata, 'kb_id': active_kb_id}


@router.post('/quiz/from-qa', tags=['学习辅助'], response_model=QuizResponse, summary='基于问答命中的原文切片生成随堂巩固练习')
def qa_follow_up_quiz(quiz_request: QuizFromQARequest, request: Request):
    """直接使用问答命中的原文切片出题，形成提问后的即时巩固。"""
    started_at = perf_counter()
    repository, _, active_kb_id = _resolve_knowledge_base(request, quiz_request.kb_id)
    quiz_result = request.app.state.learning.quiz_from_chunks(
        quiz_request.chunk_ids,
        count=quiz_request.count,
        question_types=quiz_request.question_types,
        difficulty=quiz_request.difficulty,
        repo=repository,
    )
    metadata = _build_metadata(request, started_at, repository=repository)
    return {**quiz_result, **metadata, 'kb_id': active_kb_id}


@router.get('/history', tags=['会话历史'], response_model=HistoryResponse, summary='当前会话问答历史（倒序分页）')
def history(
    request: Request,
    session_id: UUID,
    kb_id: KnowledgeBaseId | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """分页获取当前会话的问答记录。"""
    return _get_history_store(request).list(str(session_id), limit, offset, knowledge_base_id=kb_id)


@router.get('/history/{record_id}', tags=['会话历史'], response_model=HistoryItem, summary='当前会话的单条问答')
def history_item(record_id: UUID, request: Request, session_id: UUID):
    """获取当前会话中的单条问答详情。"""
    return _get_history_store(request).get(str(record_id), str(session_id))


@router.delete('/history/{record_id}', tags=['会话历史'], status_code=204, summary='删除当前会话的一条问答')
def delete_history_item(record_id: UUID, request: Request, session_id: UUID):
    """删除当前会话中的单条问答。"""
    _get_history_store(request).delete(str(record_id), str(session_id))
    return Response(status_code=204)


@router.delete('/history', tags=['会话历史'], response_model=DeletedResponse, summary='清空当前会话历史')
def clear_history(request: Request, session_id: UUID):
    """清空当前会话的全部问答历史。"""
    return {'deleted': _get_history_store(request).clear(str(session_id))}

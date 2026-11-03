"""HTTP 接口层：校验输入、调度真实服务、返回强类型响应。"""
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import FileResponse

from backend.config import COURSE_ID
from backend.errors import AppError
from backend.schemas.models import (ChapterInfo, ChapterList, ChapterRequest, Citation,
    CourseResponse, DeletedResponse, ErrorResponse, HealthResponse, HistoryItem,
    HistoryResponse, QAResponse, QuestionRequest, QuizRequest, QuizResponse, SummaryResponse)

ERRORS = {status: {'model': ErrorResponse, 'description': description} for status, description in {
    404: '资源不存在或不属于该会话', 409: '原 PDF 与数据版本冲突', 422: '参数错误', 500: '内部处理失败',
    502: '模型上游或输出校验失败', 503: '数据、索引、模型配置或存储未就绪', 504: '模型超时'}.items()}
router = APIRouter(prefix='/api', responses=ERRORS)


def _metadata(request: Request, started: float, chapter_id=None, section_id=None):
    if chapter_id is None and section_id:
        chapter_id = section_id.split('-')[0]
    return {'request_id': request.state.request_id,
            'dataset_version': request.app.state.corpus.status()['dataset_version'],
            'latency_ms': round((perf_counter() - started) * 1000, 3),
            'scope': {'chapter_id': chapter_id, 'section_id': section_id}}


def _history(request: Request):
    store = request.app.state.history
    if store is None:
        raise AppError(503, 'HISTORY_UNAVAILABLE', '历史存储尚未就绪。')
    return store


@router.get('/health', tags=['状态'], response_model=HealthResponse, summary='服务、语料与配置就绪状态')
def health(request: Request):
    state = request.app.state
    status = state.corpus.status()
    generation_ready = state.settings.generation_mode == 'extractive' or bool(
        state.settings.llm_base_url.strip() and state.settings.llm_model.strip())
    history_ready = state.history is not None
    modes = state.retrieval.available_modes()
    retrieval_ready = state.settings.default_retrieval_mode in modes
    return {'status': 'ok' if status['ready'] and retrieval_ready and generation_ready and history_ready else 'degraded',
            'stage': 'api_v1', 'knowledge_base_ready': status['ready'],
            'dataset_version': status.get('dataset_version'), 'chunk_count': status.get('chunk_count', 0),
            'retrieval_modes': modes, 'default_retrieval_mode': state.settings.default_retrieval_mode,
            'retrieval_ready': retrieval_ready,
            'generation_mode': state.settings.generation_mode, 'generation_ready': generation_ready,
            'history_ready': history_ready, 'reason': status.get('reason')}


@router.get('/course', tags=['课程与来源'], response_model=CourseResponse, summary='固定课程与数据版本')
def course(request: Request):
    return request.app.state.corpus.course()


@router.get('/chapters', tags=['课程与来源'], response_model=ChapterList, summary='已入库的章、节目录')
def chapters(request: Request):
    repo = request.app.state.corpus
    return {'course_id': COURSE_ID, 'dataset_version': repo.status().get('dataset_version') or '',
            'chapters': repo.chapters()}


@router.get('/chapters/{chapter_id}', tags=['课程与来源'], response_model=ChapterInfo, summary='章节详情与覆盖范围')
def chapter(chapter_id: str, request: Request):
    return request.app.state.corpus.chapter(chapter_id)


@router.get('/sources/{chunk_id}', tags=['课程与来源'], response_model=Citation, summary='核对原文、章节与物理页码')
def source(chunk_id: str, request: Request):
    return request.app.state.corpus.evidence(chunk_id)


@router.get('/course/source', tags=['课程与来源'], response_class=FileResponse, summary='预置原 PDF（固定来源）',
            responses={200: {'description': '原 PDF，可使用 #page=N 定位', 'content': {'application/pdf': {}}}})
def course_source(request: Request):
    path = request.app.state.corpus.source_path()
    return FileResponse(path, media_type='application/pdf', filename=path.name, content_disposition_type='inline')


@router.post('/qa', tags=['问答'], response_model=QAResponse, summary='检索证据、回答问题并保存会话历史')
def question_answer(payload: QuestionRequest, request: Request):
    started = perf_counter()
    state = request.app.state
    store = _history(request)
    mode = payload.retrieval_mode or state.settings.default_retrieval_mode
    found = state.retrieval.search(payload.question, chapter_id=payload.chapter_id,
        section_id=payload.section_id, top_k=payload.top_k, mode=mode, debug=payload.debug)
    citations = [Citation.model_validate(item).model_dump() for item in found['citations']]
    result = state.generation.answer(payload.question, citations)
    session_id = str(payload.session_id or uuid4())
    response = {**result, 'citations': citations, 'retrieval_mode': found['retrieval_mode'],
                'session_id': session_id, 'debug': found.get('debug') if payload.debug else None,
                **_metadata(request, started, payload.chapter_id, payload.section_id)}
    # 先校验响应再持久化，模型输出错误时不留下成功记录。
    QAResponse.model_validate(dict(response, history_id='pending'))
    record = {key: value for key, value in response.items() if key != 'debug'}
    response['history_id'] = store.add(dict(record, question=payload.question))
    return response


@router.post('/summary', tags=['学习辅助'], response_model=SummaryResponse, summary='生成指定章或节的有来源总结')
def chapter_summary(payload: ChapterRequest, request: Request):
    started = perf_counter()
    result = request.app.state.learning.summary(payload.chapter_id, section_id=payload.section_id)
    return {**result, **_metadata(request, started, payload.chapter_id, payload.section_id)}


@router.post('/quiz', tags=['学习辅助'], response_model=QuizResponse, summary='生成带答案、解析和引用的练习')
def chapter_quiz(payload: QuizRequest, request: Request):
    started = perf_counter()
    result = request.app.state.learning.quiz(payload.chapter_id, section_id=payload.section_id,
        count=payload.count, question_types=payload.question_types, difficulty=payload.difficulty)
    return {**result, **_metadata(request, started, payload.chapter_id, payload.section_id)}


@router.get('/history', tags=['会话历史'], response_model=HistoryResponse, summary='当前会话问答历史（倒序分页）')
def history(request: Request, session_id: UUID, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    return _history(request).list(str(session_id), limit, offset)


@router.get('/history/{record_id}', tags=['会话历史'], response_model=HistoryItem, summary='当前会话的单条问答')
def history_item(record_id: UUID, request: Request, session_id: UUID):
    return _history(request).get(str(record_id), str(session_id))


@router.delete('/history/{record_id}', tags=['会话历史'], status_code=204, summary='删除当前会话的一条问答')
def delete_history_item(record_id: UUID, request: Request, session_id: UUID):
    _history(request).delete(str(record_id), str(session_id))
    return Response(status_code=204)


@router.delete('/history', tags=['会话历史'], response_model=DeletedResponse, summary='清空当前会话历史')
def clear_history(request: Request, session_id: UUID):
    return {'deleted': _history(request).clear(str(session_id))}

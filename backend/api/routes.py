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


def _metadata(request: Request, started_at: float, chapter_id=None, section_id=None):
    if chapter_id is None and section_id:
        chapter_id = section_id.split('-')[0]
    return {'request_id': request.state.request_id,
            'dataset_version': request.app.state.corpus.status()['dataset_version'],
            'latency_ms': round((perf_counter() - started_at) * 1000, 3),
            'scope': {'chapter_id': chapter_id, 'section_id': section_id}}


def _history(request: Request):
    history_store = request.app.state.history
    if history_store is None:
        raise AppError(503, 'HISTORY_UNAVAILABLE', '历史存储尚未就绪。')
    return history_store


@router.get('/health', tags=['状态'], response_model=HealthResponse, summary='服务、语料与配置就绪状态')
def health(request: Request):
    app_state = request.app.state
    corpus_status = app_state.corpus.status()
    generation_ready = app_state.settings.generation_mode == 'extractive' or bool(
        app_state.settings.llm_base_url.strip() and app_state.settings.llm_model.strip())
    history_ready = app_state.history is not None
    available_retrieval_modes = app_state.retrieval.available_modes()
    retrieval_ready = app_state.settings.default_retrieval_mode in available_retrieval_modes
    return {'status': 'ok' if corpus_status['ready'] and retrieval_ready and generation_ready and history_ready else 'degraded',
            'stage': 'api_v1', 'knowledge_base_ready': corpus_status['ready'],
            'dataset_version': corpus_status.get('dataset_version'), 'chunk_count': corpus_status.get('chunk_count', 0),
            'retrieval_modes': available_retrieval_modes, 'default_retrieval_mode': app_state.settings.default_retrieval_mode,
            'retrieval_ready': retrieval_ready,
            'generation_mode': app_state.settings.generation_mode, 'generation_ready': generation_ready,
            'history_ready': history_ready, 'reason': corpus_status.get('reason')}


@router.get('/course', tags=['课程与来源'], response_model=CourseResponse, summary='固定课程与数据版本')
def course(request: Request):
    return request.app.state.corpus.course()


@router.get('/chapters', tags=['课程与来源'], response_model=ChapterList, summary='已入库的章、节目录')
def chapters(request: Request):
    corpus_repository = request.app.state.corpus
    return {'course_id': COURSE_ID, 'dataset_version': corpus_repository.status().get('dataset_version') or '',
            'chapters': corpus_repository.chapters()}


@router.get('/chapters/{chapter_id}', tags=['课程与来源'], response_model=ChapterInfo, summary='章节详情与覆盖范围')
def chapter(chapter_id: str, request: Request):
    return request.app.state.corpus.chapter(chapter_id)


@router.get('/sources/{chunk_id}', tags=['课程与来源'], response_model=Citation, summary='核对原文、章节与物理页码')
def source(chunk_id: str, request: Request):
    return request.app.state.corpus.evidence(chunk_id)


@router.get('/course/source', tags=['课程与来源'], response_class=FileResponse, summary='预置原 PDF（固定来源）',
            responses={200: {'description': '原 PDF，可使用 #page=N 定位', 'content': {'application/pdf': {}}}})
def course_source(request: Request):
    source_pdf_path = request.app.state.corpus.source_path()
    return FileResponse(source_pdf_path, media_type='application/pdf', filename=source_pdf_path.name, content_disposition_type='inline')


@router.post('/qa', tags=['问答'], response_model=QAResponse, summary='检索证据、回答问题并保存会话历史')
def question_answer(question_request: QuestionRequest, request: Request):
    started_at = perf_counter()
    app_state = request.app.state
    history_store = _history(request)
    retrieval_mode = question_request.retrieval_mode or app_state.settings.default_retrieval_mode
    retrieval_result = app_state.retrieval.search(question_request.question, chapter_id=question_request.chapter_id,
        section_id=question_request.section_id, top_k=question_request.top_k, mode=retrieval_mode, debug=question_request.debug)
    citations = [Citation.model_validate(item).model_dump() for item in retrieval_result['citations']]
    answer_result = app_state.generation.answer(question_request.question, citations)
    session_id = str(question_request.session_id or uuid4())
    qa_response = {**answer_result, 'citations': citations, 'retrieval_mode': retrieval_result['retrieval_mode'],
                'session_id': session_id, 'debug': retrieval_result.get('debug') if question_request.debug else None,
                **_metadata(request, started_at, question_request.chapter_id, question_request.section_id)}
    # 先校验响应再持久化，模型输出错误时不留下成功记录。
    QAResponse.model_validate(dict(qa_response, history_id='pending'))
    history_record = {key: value for key, value in qa_response.items() if key != 'debug'}
    qa_response['history_id'] = history_store.add(dict(history_record, question=question_request.question))
    return qa_response


@router.post('/summary', tags=['学习辅助'], response_model=SummaryResponse, summary='生成指定章或节的有来源总结')
def chapter_summary(summary_request: ChapterRequest, request: Request):
    started_at = perf_counter()
    summary_result = request.app.state.learning.summary(summary_request.chapter_id, section_id=summary_request.section_id)
    return {**summary_result, **_metadata(request, started_at, summary_request.chapter_id, summary_request.section_id)}


@router.post('/quiz', tags=['学习辅助'], response_model=QuizResponse, summary='生成带答案、解析和引用的练习')
def chapter_quiz(quiz_request: QuizRequest, request: Request):
    started_at = perf_counter()
    quiz_result = request.app.state.learning.quiz(quiz_request.chapter_id, section_id=quiz_request.section_id,
        count=quiz_request.count, question_types=quiz_request.question_types, difficulty=quiz_request.difficulty)
    return {**quiz_result, **_metadata(request, started_at, quiz_request.chapter_id, quiz_request.section_id)}


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

"""应用工厂、生命周期、跨域、追踪标识和统一错误响应。"""
import logging
import re
import sqlite3
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend.api.routes import router
from backend.config import APP_NAME, Settings
from backend.errors import AppError, validation_error_message
from backend.services.corpus import CorpusRepository
from backend.services.retrieval import RetrievalService
from backend.services.generation import GenerationService
from backend.services.knowledge_base import KnowledgeBaseManager
from backend.services.learning import LearningService
from backend.storage.history import HistoryStore

logger = logging.getLogger('course_assistant')


def error_response(request: Request, status: int, code: str, message: str, details=None):
    error = {'code': code, 'message': message}
    if details is not None:
        error['details'] = details
    return JSONResponse(status_code=status, content={
        'error': error, 'request_id': request.state.request_id})


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = config
        app.state.corpus = CorpusRepository(config)
        app.state.retrieval = RetrievalService(app.state.corpus, config)
        app.state.kb_manager = KnowledgeBaseManager(config, app.state.corpus, app.state.retrieval)
        app.state.generation = GenerationService(config)
        app.state.learning = LearningService(app.state.corpus, app.state.generation)
        try:
            app.state.history = HistoryStore(config.database_path)
        except (OSError, sqlite3.Error) as exc:
            logger.error('历史记录初始化失败：%s', type(exc).__name__)
            app.state.history = None
        yield

    app = FastAPI(
        title=APP_NAME, version='1.0.0', lifespan=lifespan,
        description='基于混合检索的学习助手 API：支持自定义文档上传、BM25 与向量混合检索、多轮问答、章节总结与练习自测。',
        openapi_tags=[{'name': name} for name in ('状态', '知识库管理', '课程与来源', '问答', '学习辅助', '会话历史')],
    )
    app.state.settings = config
    app.include_router(router)
    app.add_middleware(CORSMiddleware, allow_origins=list(config.cors_origins),
                       allow_methods=['GET', 'POST', 'PATCH', 'DELETE', 'OPTIONS'],
                       allow_headers=['Content-Type', 'X-Request-ID'],
                       expose_headers=['X-Request-ID'])

    @app.middleware('http')
    async def trace_request(request: Request, call_next):
        incoming = request.headers.get('X-Request-ID', '')
        request.state.request_id = incoming if re.fullmatch(r'[A-Za-z0-9._-]{1,64}', incoming) else str(uuid4())
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error('请求编号=%s，异常类型=%s', request.state.request_id, type(exc).__name__)
            response = error_response(request, 500, 'INTERNAL_ERROR', '服务处理失败，请稍后重试并保留请求编号。')
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(AppError)
    async def service_error(request: Request, exc: AppError):
        return error_response(request, exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # 不回显原始请求内容、上下文异常对象或可能包含密钥的字段值。
        details = [{
            'field': '.'.join(str(part) for part in error['loc']),
            'message': validation_error_message(error),
            'type': error['type'],
        } for error in exc.errors()]
        return error_response(request, 422, 'VALIDATION_ERROR', '请求参数校验失败。', details)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        message = str(exc.detail)
        if not re.search(r'[\u3400-\u9fff]', message):
            message = {404: '请求的资源不存在。', 405: '请求方法不受支持。'}.get(exc.status_code, '请求处理失败。')
        return error_response(request, exc.status_code, 'HTTP_ERROR', message)

    return app


app = create_app()

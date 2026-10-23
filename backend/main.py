"""FastAPI入口：只装配应用与路由，不在这里写检索或生成算法。"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.api.routes import router
from backend.config import APP_NAME

app = FastAPI(title=APP_NAME, version='0.1.0', description='项目骨架，业务尚未实现')
app.include_router(router)


@app.exception_handler(NotImplementedError)
async def unfinished_feature(_request: Request, exc: NotImplementedError):
    """占位服务明确返回501，避免空列表或假答案被误认为真实处理结果。"""
    return JSONResponse(status_code=501, content={'detail': str(exc)})

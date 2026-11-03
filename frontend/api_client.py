"""支持依赖注入的 HTTP 边界，不导入后端实现，也不保存会话状态。"""
from __future__ import annotations

import os
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_frontend_env() -> None:
    """仅加载前端配置，不受启动目录影响。

    进程环境变量优先。模型凭据保留在服务端；
    导入此 HTTP 客户端不会将凭据加载到 Streamlit 的环境中。
    """
    values = dotenv_values(PROJECT_ROOT / ".env")
    for name in ("BACKEND_URL", "BACKEND_TIMEOUT"):
        value = values.get(name)
        if value is not None:
            os.environ.setdefault(name, value)


class APIError(Exception):
    """面向用户的 API 异常，不暴露上游原始响应体或凭据。"""

    def __init__(self, message: str, *, code: str = "request_failed",
                 status_code: int | None = None, request_id: str | None = None,
                 details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.request_id = request_id
        self.details = details


def backend_url() -> str:
    load_frontend_env()
    return os.getenv("BACKEND_URL", "http://127.0.0.1:8000").strip().rstrip("/")


def backend_timeout() -> float:
    load_frontend_env()
    try:
        timeout = float(os.getenv("BACKEND_TIMEOUT", "90"))
    except ValueError:
        return 90.0
    return timeout if 0 < timeout <= 600 else 90.0


class APIClient:
    def __init__(self, base_url: str | None = None,
                 timeout: float | httpx.Timeout | None = None, *,
                 client: httpx.Client | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = (base_url or backend_url()).strip().rstrip("/")
        try:
            parsed = urlsplit(self.base_url)
            parsed.port  # 在界面组件发出请求前拒绝无效端口。
        except ValueError as exc:
            raise APIError("后端地址配置无效，请检查地址格式和端口。", code="invalid_backend_url") from exc
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment):
            raise APIError("后端地址配置无效，请检查地址格式和端口。", code="invalid_backend_url")
        if client is not None and transport is not None:
            raise ValueError("客户端和传输适配器只能传入其中一项。")
        self.timeout = timeout if timeout is not None else backend_timeout()
        self._owns_client = client is None
        host = parsed.hostname or ""
        try:
            loopback = ip_address(host).is_loopback
        except ValueError:
            loopback = host.lower().rstrip(".") == "localhost"
        # 即使未设置 HTTP_PROXY，Windows 也可能提供隐式系统代理。
        # 本地请求直连本地服务，远程后端保留正常的代理支持；
        # 注入的客户端继续使用调用方配置。
        self._client = client if client is not None else httpx.Client(
            transport=transport, timeout=self.timeout, follow_redirects=False,
            trust_env=not loopback)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> APIClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any] | None:
        try:
            response = self._client.request(method, f"{self.base_url}{path}", timeout=self.timeout, **kwargs)
        except httpx.TimeoutException as exc:
            raise APIError("请求超时，请稍后重试或检查后端模型服务。", code="timeout") from exc
        except httpx.RequestError as exc:
            raise APIError("后端连接中断，请确认服务已启动，并检查后端地址配置。", code="connection_error") from exc
        request_id = response.headers.get("X-Request-ID")
        try:
            payload = response.json() if response.content else None
        except ValueError:
            payload = None
        if response.is_error or response.is_redirect:
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            if not isinstance(error, dict):
                error = {}
            defaults = {
                404: "请求的章节、原文或历史记录不存在。",
                422: "提交参数有误，请检查输入后重试。",
                502: "后端模型服务暂时异常，请稍后重试。",
                503: "所需知识库或模型服务尚未就绪。",
                504: "后端模型服务响应超时，请稍后重试。",
            }
            message = error.get("message")
            if not isinstance(message, str) or not message.strip():
                message = defaults.get(response.status_code, "请求处理失败，请稍后重试。")
            body_id = payload.get("request_id") if isinstance(payload, dict) else None
            raise APIError(message, code=str(error.get("code", "http_error")),
                           status_code=response.status_code, request_id=request_id or body_id,
                           details=error.get("details"))
        if response.status_code == 204:
            return None
        if not isinstance(payload, dict):
            raise APIError("后端响应格式异常，请检查服务版本。", code="invalid_response", request_id=request_id)
        return payload

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/api/health") or {}

    def course(self) -> dict[str, Any]:
        return self._request("GET", "/api/course") or {}

    def chapters(self) -> dict[str, Any]:
        return self._request("GET", "/api/chapters") or {}

    def chapter(self, chapter_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/chapters/{quote(chapter_id, safe='')}") or {}

    def source(self, chunk_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/sources/{quote(chunk_id, safe='')}") or {}

    def ask(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/qa", json=payload) or {}

    def summarize(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/summary", json=payload) or {}

    def quiz(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/quiz", json=payload) or {}

    def history(self, session_id: str, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return self._request("GET", "/api/history", params={"session_id": session_id, "limit": limit, "offset": offset}) or {}

    def history_item(self, record_id: str, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/history/{quote(str(record_id), safe='')}", params={"session_id": session_id}) or {}

    def delete_history_item(self, record_id: str, session_id: str) -> None:
        self._request("DELETE", f"/api/history/{quote(str(record_id), safe='')}", params={"session_id": session_id})

    def clear_history(self, session_id: str) -> dict[str, Any]:
        return self._request("DELETE", "/api/history", params={"session_id": session_id}) or {}

    def pdf_url(self, page: int) -> str:
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError("教材页码必须是正整数。")
        return f"{self.base_url}/api/course/source#page={page}"

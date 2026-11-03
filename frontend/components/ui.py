"""可复用的界面展示辅助函数，所有数据均通过 HTTP 获取。"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import streamlit as st

from frontend.api_client import APIClient, APIError, backend_timeout, backend_url


RETRIEVAL_LABELS = {'bm25': '关键词检索', 'vector': '向量检索', 'hybrid': '混合检索'}
REVIEW_LABELS = {
    'low_text': '文字较少',
    'image_resource': '含图片资源',
    'figure_or_table_reference': '含图表引用',
    'unresolved_glyph': '存在待核对字符',
}


def learning_text(text: str) -> str:
    """兼容已有结果的模式说明；教材原文和存储内容保持不变。"""
    prefixes = {
        '原文摘录（extractive）：': '原文摘录：',
        '原文摘录总结（extractive）：': '原文摘录总结：',
        '代表性小节总结（llm，非逐段完整覆盖）：': '代表性小节总结（大模型生成，非逐段完整覆盖）：',
    }
    for original, chinese in prefixes.items():
        if text.startswith(original):
            return chinese + text[len(original):]
    return text


@st.cache_resource(show_spinner=False)
def _cached_client(base_url: str, timeout: float) -> APIClient:
    return APIClient(base_url=base_url, timeout=timeout)


def get_api_client() -> APIClient:
    return _cached_client(backend_url(), backend_timeout())


def session_uuid() -> str:
    value = st.session_state.get("session_uuid")
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        st.session_state["session_uuid"] = str(uuid4())
        return st.session_state["session_uuid"]


def show_api_error(error: APIError) -> None:
    st.error(error.message)
    if error.request_id:
        st.caption(f"请求标识：{error.request_id}")


def course_context() -> tuple[APIClient | None, dict[str, Any], list[dict[str, Any]]]:
    try:
        client = get_api_client()
        health = client.health()
        if not health.get("knowledge_base_ready", False):
            st.warning("知识库尚未就绪，请先完成课程数据预处理并检查后端配置。")
            return client, health, []
        course = client.course()
        chapters = client.chapters().get("chapters", [])
        st.caption(f"{course.get('name', '课程教材')} · "
                   f"数据版本 {course.get('dataset_version') or health.get('dataset_version') or '未标注'} · "
                   f"{course.get('chunk_count', health.get('chunk_count', 0))} 个文本块")
        return client, health, chapters if isinstance(chapters, list) else []
    except APIError as error:
        show_api_error(error)
        return None, {}, []


def scope_selector(chapters: list[dict[str, Any]], prefix: str, *, allow_all: bool) -> tuple[str | None, str | None]:
    by_id = {str(row.get("chapter_id", row.get("id"))): row for row in chapters if row.get("chapter_id", row.get("id"))}
    options = ([None] if allow_all else []) + list(by_id)
    if not options:
        st.selectbox("章节范围", ["暂无可用章节"], disabled=True, key=f"{prefix}_chapter_empty")
        return None, None
    chapter_id = st.selectbox("章节范围", options,
        format_func=lambda value: "全部课程章节" if value is None else by_id[value].get("title", value),
        key=f"{prefix}_chapter", disabled=not chapters)
    if chapter_id is None:
        return None, None
    sections = by_id[chapter_id].get("sections", [])
    section_by_id = {str(row.get("section_id", row.get("id"))): row
        for row in sections if isinstance(row, dict) and row.get("section_id", row.get("id"))}
    section_id = st.selectbox("小节范围", [None] + list(section_by_id),
        format_func=lambda value: "本章全部小节" if value is None else section_by_id[value].get("title", value),
        key=f"{prefix}_section_{chapter_id}")
    return chapter_id, section_id


def render_sources(citations: list[dict[str, Any]], client: APIClient) -> None:
    if not citations:
        return
    st.subheader("教材引用")
    for number, citation in enumerate(citations, 1):
        citation_id = citation.get("citation_id", number)
        page_start = citation.get("page_start")
        page_end = citation.get("page_end", page_start)
        pages = f"教材第 {page_start} 页" if page_start == page_end else f"教材第 {page_start}—{page_end} 页"
        title = citation.get("section_title") or citation.get("chapter_title") or citation.get("chunk_id", "教材原文")
        with st.expander(f"[{citation_id}] {title} · {pages}", expanded=False):
            st.write(citation.get("text", ""))
            st.caption(f"{citation.get('source_file', '课程教材')} · {citation.get('chunk_id', '')}")
            if citation.get("review_flags"):
                st.caption("文本抽取标记：" + "、".join(
                    REVIEW_LABELS.get(flag, '需要人工复核') for flag in citation["review_flags"]))
            if citation.get("source_url") and isinstance(page_start, int) and page_start > 0:
                # 始终避免将响应中的 URL 直接用作导航目标。
                st.link_button("打开教材对应页", client.pdf_url(page_start))


def render_coverage(coverage: dict[str, Any]) -> None:
    """将接口统计字段转成用户可读的中文，不展示原始协议数据。"""
    st.write(f"小节覆盖：{coverage.get('sections_covered', 0)} / {coverage.get('sections_total', 0)}")
    st.write(f"文本块选取：{coverage.get('chunks_selected', 0)} / {coverage.get('chunks_total', 0)}")
    st.caption('选取方式：每个小节选取代表性片段，不表示逐段覆盖全部原文。')
    if coverage.get('chapter_intro_included'):
        st.caption('已包含章节导读。')
    if coverage.get('note'):
        st.caption(coverage['note'])


def render_metadata(result: dict[str, Any]) -> None:
    scope = result.get("scope")
    if isinstance(scope, dict):
        description = scope.get("chapter_id") or "全部课程章节"
        if scope.get("section_id"):
            description += " / " + scope["section_id"]
        st.caption(f"本次结果范围：{description}")
    mode = result.get("generation_mode")
    if mode == "extractive":
        st.caption("生成方式：教材原文摘录（本地抽取式，未调用大模型）。")
    elif mode == "llm":
        st.caption("生成方式：大模型依据教材证据生成，请结合原文核对。")
    if result.get("latency_ms") is not None:
        st.caption(f"处理耗时：{result['latency_ms']} 毫秒 · 请求标识：{result.get('request_id', '—')}")


def render_learning_next_steps(current: str) -> None:
    """在结果末尾提供下一步，让学习流程可以连续完成。"""
    pages = [
        ('summary', 'pages/summary.py', '回顾章节总结'),
        ('qa', 'pages/qa.py', '继续提出问题'),
        ('quiz', 'pages/quiz.py', '完成练习自测'),
        ('history', 'pages/history.py', '查看会话历史'),
    ]
    targets = [(page, label) for name, page, label in pages if name != current]
    st.divider()
    st.subheader('继续学习')
    for column, (page, label) in zip(st.columns(len(targets)), targets):
        with column:
            st.page_link(page, label=label, use_container_width=True)

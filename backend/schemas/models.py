"""最小数据约定；后续实现引用、出题等功能时再补充响应结构。"""
from pydantic import BaseModel, Field


class QuestionRequest(BaseModel):
    """问答输入：chapter_id为空表示在预置课程全文范围内检索。"""
    question: str = Field(min_length=1, max_length=2000)
    chapter_id: str | None = None


class ChapterRequest(BaseModel):
    """总结和出题共同使用的章节范围。"""
    chapter_id: str = Field(min_length=1)


class Evidence(BaseModel):
    """检索服务将来返回的原文证据；页码采用从1开始的PDF物理页码。"""
    chunk_id: str
    text: str
    chapter_id: str
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)

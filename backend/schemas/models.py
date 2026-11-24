"""HTTP 请求与响应契约；由 FastAPI 自动导出 OpenAPI。"""
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ChapterId = Annotated[str, Field(pattern=r'^ch\d{2}$')]
SectionId = Annotated[str, Field(pattern=r'^ch\d{2}-s\d{3}$')]
RetrievalMode = Literal['bm25', 'vector', 'hybrid']
GenerationMode = Literal['extractive', 'llm']


class InputModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class QuestionRequest(InputModel):
    """问答输入：chapter_id为空表示在预置课程全文范围内检索。"""
    question: str = Field(min_length=1, max_length=2000)
    chapter_id: ChapterId | None = None
    section_id: SectionId | None = None
    session_id: UUID | None = Field(default=None, description='省略时创建会话；客户端须保存响应中的 UUID')
    retrieval_mode: RetrievalMode | None = Field(default=None, description='省略时使用服务端默认模式，默认 hybrid')
    top_k: int = Field(default=5, ge=1, le=10, strict=True)
    debug: bool = False

    @model_validator(mode='after')
    def scope_matches(self):
        if self.chapter_id and self.section_id and not self.section_id.startswith(self.chapter_id + '-'):
            raise ValueError('所选小节必须属于所选章节。')
        return self


class ChapterRequest(InputModel):
    """总结和出题共同使用的章节范围。"""
    chapter_id: ChapterId
    section_id: SectionId | None = None

    @model_validator(mode='after')
    def scope_matches(self):
        if self.section_id and not self.section_id.startswith(self.chapter_id + '-'):
            raise ValueError('所选小节必须属于所选章节。')
        return self


class QuizRequest(ChapterRequest):
    count: int = Field(default=5, ge=1, le=10, strict=True)
    question_types: list[Literal['short_answer', 'multiple_choice']] = Field(default_factory=lambda: ['short_answer'], min_length=1, max_length=2)
    difficulty: Literal['easy', 'medium', 'hard'] = 'medium'

    @model_validator(mode='after')
    def unique_types(self):
        if len(set(self.question_types)) != len(self.question_types):
            raise ValueError('题型列表中不得包含重复项。')
        if self.count < len(self.question_types):
            raise ValueError('题量必须不少于所选题型的数量。')
        return self


class Evidence(BaseModel):
    """检索服务将来返回的原文证据；页码采用从1开始的PDF物理页码。"""
    chunk_id: str
    text: str
    chapter_id: str
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)


class Citation(Evidence):
    citation_id: int = Field(ge=1)
    source_file: str
    chapter_title: str
    section_id: str | None = None
    section_title: str | None = None
    source_url: str | None = None
    score: float | None = None
    review_flags: list[str] = Field(default_factory=list)


class Scope(BaseModel):
    chapter_id: str | None = None
    section_id: str | None = None


class Metadata(BaseModel):
    request_id: str
    dataset_version: str
    latency_ms: float = Field(ge=0)
    scope: Scope


class QAResponse(Metadata):
    answer: str
    citations: list[Citation]
    retrieval_mode: RetrievalMode
    generation_mode: GenerationMode
    insufficient_evidence: bool
    session_id: UUID
    history_id: str
    debug: dict[str, Any] | None = None


class SummaryResponse(Metadata):
    summary: str
    key_points: list[str]
    citations: list[Citation]
    coverage: dict[str, Any]
    generation_mode: GenerationMode


class QuizOption(BaseModel):
    key: str
    text: str


class QuizQuestion(BaseModel):
    question_id: str
    type: Literal['short_answer', 'multiple_choice']
    question: str
    options: list[QuizOption] = Field(default_factory=list)
    answer: str
    explanation: str
    citation_ids: list[int] = Field(min_length=1)


class QuizResponse(Metadata):
    questions: list[QuizQuestion]
    citations: list[Citation]
    generation_mode: GenerationMode


class SectionInfo(BaseModel):
    model_config = ConfigDict(extra='allow')
    section_id: str
    title: str
    page_start: int


class ChapterInfo(BaseModel):
    model_config = ConfigDict(extra='allow')
    chapter_id: str
    title: str
    page_start: int
    page_end: int
    sections: list[SectionInfo] = Field(default_factory=list)


class ChapterList(BaseModel):
    course_id: str
    dataset_version: str
    chapters: list[ChapterInfo]


class CourseResponse(BaseModel):
    model_config = ConfigDict(extra='allow')
    course_id: str
    name: str
    dataset_version: str
    source_file: str
    chapter_count: int
    chunk_count: int
    description: str = ''


class HealthResponse(BaseModel):
    status: Literal['ok', 'degraded']
    stage: str
    knowledge_base_ready: bool
    dataset_version: str | None = None
    chunk_count: int = 0
    retrieval_modes: list[str]
    default_retrieval_mode: RetrievalMode
    retrieval_ready: bool
    generation_mode: GenerationMode
    generation_ready: bool
    history_ready: bool
    reason: str | None = None


class HistoryItem(BaseModel):
    id: str
    session_id: UUID
    question: str
    answer: str
    citations: list[Citation]
    retrieval_mode: RetrievalMode
    generation_mode: GenerationMode
    scope: Scope
    dataset_version: str
    insufficient_evidence: bool
    created_at: str
    latency_ms: float
    request_id: str


class HistoryResponse(BaseModel):
    items: list[HistoryItem]
    total: int
    limit: int
    offset: int


class DeletedResponse(BaseModel):
    deleted: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
    request_id: str

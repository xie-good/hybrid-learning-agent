"""HTTP 请求与响应数据模型；由 FastAPI 自动校验参数并生成接口文档。"""
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ChapterId = Annotated[str, Field(pattern=r'^ch\d{2,3}$')]
SectionId = Annotated[str, Field(pattern=r'^ch\d{2,3}-s\d{3}$')]
KnowledgeBaseId = Annotated[str, Field(pattern=r'^[a-z0-9][a-z0-9_-]{1,47}$')]
RetrievalMode = Literal['bm25', 'vector', 'hybrid']
GenerationMode = Literal['extractive', 'llm']


class InputModel(BaseModel):
    """所有输入模型的基类：禁止传入多余字段，并自动去除首尾空白。"""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class QuestionRequest(InputModel):
    """问答请求参数：不传章节编号时表示在整个知识库范围内检索。"""

    question: str = Field(min_length=1, max_length=2000)
    kb_id: KnowledgeBaseId | None = None
    chapter_id: ChapterId | None = None
    section_id: SectionId | None = None
    session_id: UUID | None = Field(default=None, description='省略时创建新会话；前端需保存返回的 UUID')
    retrieval_mode: RetrievalMode | None = Field(default=None, description='省略时使用服务端默认检索方式')
    top_k: int = Field(default=5, ge=1, le=10, strict=True)
    debug: bool = False

    @model_validator(mode='after')
    def scope_matches(self):
        """检查所选小节是否属于所选章节。"""
        if self.chapter_id and self.section_id and not self.section_id.startswith(self.chapter_id + '-'):
            raise ValueError('所选小节必须属于所选章节。')
        return self


class ChapterRequest(InputModel):
    """章节总结的范围参数。"""

    kb_id: KnowledgeBaseId | None = None
    chapter_id: ChapterId
    section_id: SectionId | None = None

    @model_validator(mode='after')
    def scope_matches(self):
        """检查所选小节是否属于所选章节。"""
        if self.section_id and not self.section_id.startswith(self.chapter_id + '-'):
            raise ValueError('所选小节必须属于所选章节。')
        return self


class Evidence(BaseModel):
    """检索命中的原文片段信息。"""

    chunk_id: str
    text: str
    chapter_id: str
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)


class Citation(Evidence):
    """返回给前端展示的带编号原文引用。"""

    citation_id: int = Field(ge=1)
    source_file: str
    chapter_title: str
    section_id: str | None = None
    section_title: str | None = None
    source_url: str | None = None
    score: float | None = None
    # 混合检索明细：命中来源（both/bm25/vector）、BM25排名、向量相似度、RRF融合分。
    hit_type: str | None = None
    bm25_rank: int | None = None
    vec_score: float | None = None
    rrf_score: float | None = None
    review_flags: list[str] = Field(default_factory=list)


class Scope(BaseModel):
    """本次请求限定的章节与小节范围。"""

    chapter_id: str | None = None
    section_id: str | None = None


class Metadata(BaseModel):
    """接口响应的公共追踪元信息。"""

    request_id: str
    dataset_version: str
    latency_ms: float = Field(ge=0)
    scope: Scope


class QAResponse(Metadata):
    """问答接口的响应结构。"""

    kb_id: str = 'hello_agents'
    answer: str
    rewritten_question: str | None = None
    follow_up_questions: list[str] = Field(default_factory=list)
    citations: list[Citation]
    retrieval_mode: RetrievalMode
    generation_mode: GenerationMode
    insufficient_evidence: bool
    session_id: UUID
    history_id: str
    debug: dict[str, Any] | None = None


class SummaryResponse(Metadata):
    """章节总结接口的响应结构。"""

    kb_id: str = 'hello_agents'
    summary: str
    key_points: list[str]
    citations: list[Citation]
    coverage: dict[str, Any]
    generation_mode: GenerationMode


class SectionInfo(BaseModel):
    """小节目录信息。"""

    model_config = ConfigDict(extra='allow')
    section_id: str
    title: str
    page_start: int


class ChapterInfo(BaseModel):
    """章节或文档目录信息。"""

    model_config = ConfigDict(extra='allow')
    chapter_id: str
    title: str
    page_start: int
    page_end: int
    sections: list[SectionInfo] = Field(default_factory=list)


class ChapterList(BaseModel):
    """知识库目录列表响应。"""

    course_id: str
    dataset_version: str
    chapters: list[ChapterInfo]


class CourseResponse(BaseModel):
    """知识库概要信息响应。"""

    model_config = ConfigDict(extra='allow')
    course_id: str
    name: str
    dataset_version: str
    source_file: str
    chapter_count: int
    chunk_count: int
    description: str = ''


class HealthResponse(BaseModel):
    """健康检查响应。"""

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
    """单条问答历史记录。"""

    id: str
    session_id: UUID
    kb_id: str = 'hello_agents'
    question: str
    rewritten_question: str | None = None
    answer: str
    follow_up_questions: list[str] = Field(default_factory=list)
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
    """分页历史记录响应。"""

    items: list[HistoryItem]
    total: int
    limit: int
    offset: int


class KnowledgeBaseCreateRequest(InputModel):
    """新建自定义知识库的请求参数。"""

    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default='', max_length=400)


class KnowledgeBaseInfo(BaseModel):
    """知识库概览信息。"""

    kb_id: str
    name: str
    description: str = ''
    builtin: bool = False
    ready: bool = False
    reason: str | None = None
    dataset_version: str = ''
    document_count: int = 0
    chapter_count: int = 0
    chunk_count: int = 0
    retrieval_modes: list[str] = Field(default_factory=list)
    created_at: str = ''


class KnowledgeBaseListResponse(BaseModel):
    """所有可用知识库列表响应。"""

    items: list[KnowledgeBaseInfo]


class DocumentInfo(BaseModel):
    """已上传文档的元信息。"""

    doc_id: str
    filename: str
    media_type: str
    size_bytes: int
    chapter_id: str
    chapter_title: str
    page_count: int
    chunk_count: int
    uploaded_at: str
    builtin: bool = False


class DocumentListResponse(BaseModel):
    """知识库下文档列表响应。"""

    kb_id: str
    items: list[DocumentInfo]


class DocumentUploadResponse(BaseModel):
    """上传文档成功后的响应。"""

    document: DocumentInfo
    kb: KnowledgeBaseInfo


class DocumentDeleteResponse(BaseModel):
    """删除文档成功后的响应。"""

    deleted_doc_id: str
    kb: KnowledgeBaseInfo


class ChunkPreviewListResponse(BaseModel):
    """分页预览文档切片的响应。"""

    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class DeletedResponse(BaseModel):
    """批量删除结果响应。"""

    deleted: int


class ErrorBody(BaseModel):
    """统一错误体结构。"""

    code: str
    message: str
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    """统一错误响应外壳。"""

    error: ErrorBody
    request_id: str

"""仅提供健康检查及三个业务占位接口，后续按需拆分路由文件。"""
from fastapi import APIRouter

from backend.schemas.models import ChapterRequest, QuestionRequest
from backend.services import generation, learning, retrieval

router = APIRouter(prefix='/api')


@router.get('/health', tags=['状态'])
def health():
    """只说明服务正常启动，不代表知识库已经清洗、索引或加载。"""
    return {'status': 'ok', 'stage': 'skeleton', 'knowledge_base_ready': False}


@router.post('/qa', tags=['问答'])
def question_answer(request: QuestionRequest):
    """预留检索→生成的调用位置；检索占位函数目前会明确抛出异常。"""
    evidence = retrieval.retrieve(request.question, request.chapter_id)
    return {'answer': generation.generate_answer(request.question, evidence)}


@router.post('/summary', tags=['学习辅助'])
def chapter_summary(request: ChapterRequest):
    """章节总结仅留入口，目前返回501。"""
    return {'summary': learning.summarize(request.chapter_id)}


@router.post('/quiz', tags=['学习辅助'])
def chapter_quiz(request: ChapterRequest):
    """练习生成仅留入口，题型和题量参数在实现时再扩展。"""
    return {'questions': learning.generate_quiz(request.chapter_id)}

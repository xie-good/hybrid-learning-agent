"""检索服务骨架：以后在此组织BM25、向量检索、RRF和重排序。"""
from backend.schemas.models import Evidence


def retrieve(question: str, chapter_id: str | None = None) -> list[Evidence]:
    """输入问题及可选章节；将来返回排序后的原文证据，不返回最终答案。"""
    # 后续顺序：范围过滤→两路召回→RRF去重→重排→选择证据。
    # 此阶段不安装模型、不读取索引，也不返回虚构命中结果。
    raise NotImplementedError('课程检索尚未实现：当前仅为项目骨架。')

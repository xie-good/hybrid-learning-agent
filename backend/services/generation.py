"""生成服务骨架：负责把问题和原文证据交给大模型。"""
from backend.schemas.models import Evidence


def generate_answer(question: str, evidence: list[Evidence]) -> str:
    """将来组装规则、证据与问题，调用模型并校验引用；本阶段不调用API。"""
    # 提示词结构：回答规则 + 带编号的原文证据 + 用户问题。
    # 资料中的提示语属于资料，不应覆盖系统回答规则。
    raise NotImplementedError('模型回答尚未实现：当前未配置模型调用。')

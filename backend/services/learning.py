"""提供具有原文依据和覆盖统计的代表性章节摘要。"""
from __future__ import annotations

from pydantic import Field, ValidationError

from backend.errors import AppError
from backend.services.generation import (
    GenerationService, _StrictModel,
    reading_passages, representative_excerpt, validate_cited_text,
)


class _Summary(_StrictModel):
    summary: str = Field(min_length=1, max_length=20_000)
    key_points: list[str] = Field(min_length=1, max_length=100)


class LearningService:
    def __init__(self, repo, generator: GenerationService):
        self.repo = repo
        self.generator = generator

    def summary(self, chapter_id: str, section_id: str | None = None, *, repo=None) -> dict:
        active_repo = repo or self.repo
        chunks = active_repo.scoped_chunks(chapter_id, section_id)
        groups = self._groups(chunks)
        selected = [max(group, key=self._summary_priority) for group in groups.values()]
        citations = self._citations(selected, repo=active_repo)
        section_ids = list(dict.fromkeys(
            chunk['section_id'] for chunk in selected if chunk.get('section_id')
        ))
        coverage = {
            'strategy': 'one_representative_chunk_per_section',
            'sections_total': len({chunk['section_id'] for chunk in chunks if chunk.get('section_id')}),
            'sections_covered': len(section_ids),
            'chunks_total': len(chunks),
            'chunks_selected': len(citations),
            'representative_only': True,
            'section_ids': section_ids,
            'chapter_intro_included': any(not chunk.get('section_id') for chunk in selected),
            'note': '每个小节选择一个代表性文本块；章节导读单独纳入。覆盖小节不等于逐段覆盖全部原文。',
        }
        if self.generator.mode == 'extractive':
            points = []
            for citation in citations:
                title = citation.get('section_title') or citation['chapter_title']
                excerpt = representative_excerpt(citation['text'])
                points.append(f"{title}：{excerpt} [{citation['citation_id']}]")
            summary = (
                '原文摘录总结（extractive）：按小节提供代表性原文要点，并非逐段完整概括。\n\n'
                + '\n\n'.join(f'- {point}' for point in points)
            )
        else:
            result = self._llm_summary(citations, coverage)
            summary = '代表性小节总结（llm，非逐段完整覆盖）：\n\n' + result.summary
            points = result.key_points
        return {'summary': summary, 'key_points': points, 'citations': citations,
                'coverage': coverage, 'generation_mode': self.generator.mode}

    @staticmethod
    def _summary_priority(chunk: dict) -> tuple[int, int, int]:
        """依次优先正文片段多、复核标记少、文本较完整的材料；同分保留原顺序。"""
        return (
            min(len(reading_passages(chunk['text'])), 4),
            -len(chunk.get('review_flags', [])),
            min(len(chunk['text']), 1000),
        )

    def _llm_summary(self, citations: list[dict], coverage: dict) -> _Summary:
        raw = self.generator.complete_json(
            'summary', {'evidence': self.generator.context(citations), 'coverage': coverage},
            '返回 {"summary":"带 [N] 引用的代表性小节概述", "key_points":["要点 [N]"]}。'
            '每个小节都要有带引用的要点，所有提供的 citation_id 必须至少引用一次；每个要点都要有引用。'
            '明确这是代表性材料总结，不宣称完整覆盖整章。',
        )
        try:
            result = _Summary.model_validate(raw)
        except ValidationError:
            raise AppError(502, 'invalid_model_output', '模型总结格式校验失败，请重试。') from None
        used_ids = validate_cited_text(result.summary, citations)
        for point in result.key_points:
            used_ids |= validate_cited_text(point, citations)
        if used_ids != {citation['citation_id'] for citation in citations}:
            raise AppError(502, 'incomplete_model_summary', '模型总结未覆盖全部已选小节引用，请重试。')
        return result

    @staticmethod
    def _groups(chunks: list[dict]) -> dict[str | None, list[dict]]:
        groups = {}
        for chunk in chunks:
            if chunk.get('text', '').strip():
                groups.setdefault(chunk.get('section_id'), []).append(chunk)
        if not groups:
            raise AppError(422, 'insufficient_learning_material', '所选范围尚无可用的教材正文。')
        return groups

    def _citations(self, chunks: list[dict], *, repo=None) -> list[dict]:
        active_repo = repo or self.repo
        return [{**active_repo.evidence(chunk['chunk_id']), 'citation_id': index}
                for index, chunk in enumerate(chunks, start=1)]

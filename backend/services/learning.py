"""提供具有代表性的章节摘要，以及有原文依据的阅读练习。"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import Field, ValidationError, field_validator

from backend.errors import AppError
from backend.services.generation import (
    GenerationService, _StrictModel, normalized_text,
    reading_passages, representative_excerpt, validate_cited_text,
)


class _Summary(_StrictModel):
    summary: str = Field(min_length=1, max_length=20_000)
    key_points: list[str] = Field(min_length=1, max_length=100)


class _Option(_StrictModel):
    key: str = Field(min_length=1, max_length=1)
    text: str = Field(min_length=1, max_length=1200)

    @field_validator('text')
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        if not normalized_text(value):
            raise ValueError('选项文本必须包含非空白内容。')
        return value


class _Question(_StrictModel):
    type: Literal['short_answer', 'multiple_choice']
    question: str = Field(min_length=8, max_length=3000)
    options: list[_Option] = Field(max_length=4)
    answer: str = Field(min_length=1, max_length=2000)
    explanation: str = Field(min_length=1, max_length=3000)
    citation_ids: list[int] = Field(min_length=1, max_length=20)
    evidence_quote: str = Field(min_length=12, max_length=2000)

    @field_validator('question', 'answer', 'explanation', 'evidence_quote')
    @classmethod
    def nonblank_content(cls, value: str, info) -> str:
        minimum = {'question': 8, 'evidence_quote': 12}.get(info.field_name, 1)
        if len(normalized_text(value)) < minimum:
            raise ValueError('练习字段必须包含足够的非空白内容。')
        return value


class _Quiz(_StrictModel):
    questions: list[_Question] = Field(min_length=1, max_length=20)


# 仅生成候选子串：术语只有出现在当前原文中时才会被采用。
READING_TERMS = (
    '大语言模型', '人工智能', '强化学习', '监督学习', '深度学习', '机器学习',
    '神经网络', '提示工程', '知识图谱', '向量数据库', '上下文', '智能体',
    '知识库', '工作流', '注意力', '检索', '向量', '记忆', '规划', '环境',
    '工具', '推理', '模型', '训练', '数据', '任务', '问题', '系统', '函数',
)


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

    def quiz(self, chapter_id: str, section_id: str | None = None, count: int = 5,
             question_types: list[str] | None = None, difficulty: str = 'medium', *, repo=None) -> dict:
        active_repo = repo or self.repo
        question_types = question_types if question_types is not None else ['short_answer']
        if (type(count) is not int or not 1 <= count <= 20 or not question_types
                or len(question_types) != len(set(question_types))
                or not set(question_types) <= {'short_answer', 'multiple_choice'}
                or difficulty not in {'easy', 'medium', 'hard'}):
            raise AppError(422, 'invalid_quiz_request', '题量、题型或难度标签无效。')
        if count < len(question_types):
            raise AppError(422, 'invalid_quiz_request', '题量应不少于所选题型数量。')
        chunks = active_repo.scoped_chunks(chapter_id, section_id)
        if self.generator.mode == 'llm':
            return self._llm_quiz(chunks, count, question_types, difficulty, repo=active_repo)
        chosen = self._select_quiz_material(chunks, count, question_types)
        selected = list({chunk['chunk_id']: chunk for chunk, _, _, _ in chosen}.values())
        citations = self._citations(selected, repo=active_repo)
        questions = self._extractive_questions(chosen, citations, difficulty)
        return {'questions': questions, 'citations': citations, 'generation_mode': 'extractive'}

    def quiz_from_chunks(self, chunk_ids: list[str], *, count: int = 3,
                         question_types: list[str] | None = None,
                         difficulty: str = 'medium', repo=None) -> dict:
        """基于问答命中的指定文本块生成随堂巩固练习，串联问与练的闭环。"""
        active_repository = repo or self.repo
        selected_types = question_types if question_types is not None else ['multiple_choice', 'short_answer']
        if len(selected_types) > count:
            selected_types = selected_types[:count]

        if (
            type(count) is not int
            or not 1 <= count <= 10
            or not selected_types
            or len(selected_types) != len(set(selected_types))
            or not set(selected_types) <= {'short_answer', 'multiple_choice'}
            or difficulty not in {'easy', 'medium', 'hard'}
        ):
            raise AppError(422, 'invalid_quiz_request', '随堂练习参数无效。')

        selected_chunks: list[dict] = []
        seen_chunk_ids: set[str] = set()
        for single_chunk_id in chunk_ids:
            if single_chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(single_chunk_id)
            chunk_evidence = active_repository.evidence(single_chunk_id)
            selected_chunks.append(chunk_evidence)

        if not selected_chunks:
            raise AppError(422, 'insufficient_learning_material', '没有可用于生成随堂练习的资料片段。')

        if self.generator.mode == 'llm':
            return self._llm_quiz(selected_chunks, count, selected_types, difficulty, repo=active_repository)

        chosen_items = self._select_quiz_material(selected_chunks, count, selected_types)
        unique_chunks: dict[str, dict] = {}
        for chunk_item, _, _, _ in chosen_items:
            unique_chunks[chunk_item['chunk_id']] = chunk_item

        citations = self._citations(list(unique_chunks.values()), repo=active_repository)
        questions = self._extractive_questions(chosen_items, citations, difficulty)
        return {'questions': questions, 'citations': citations, 'generation_mode': 'extractive'}

    def _select_quiz_material(self, chunks: list[dict], count: int, question_types: list[str]) -> list[tuple]:
        groups = self._groups(chunks)
        section_passages = []
        for group in groups.values():
            passages = []
            for chunk in group:
                passages.extend((chunk, passage) for passage in reading_passages(chunk['text'])[:4])
            section_passages.append(passages)
        # 按小节轮流取材，避免前一个小节耗尽全部题量。
        candidates = []
        for offset in range(max(map(len, section_passages))):
            for passages in section_passages:
                if offset < len(passages):
                    candidates.append(passages[offset])
        chosen = []
        used_passages = set()
        for index in range(count):
            question_type = question_types[index % len(question_types)]
            for chunk, passage in candidates:
                identity = (chunk['chunk_id'], passage)
                if identity in used_passages:
                    continue
                term_choices = None
                if question_type == 'multiple_choice':
                    term_choices = self._cloze_terms(passage, chunk['text'])
                if question_type == 'multiple_choice' and not term_choices:
                    continue
                chosen.append((chunk, passage, question_type, term_choices))
                used_passages.add(identity)
                break
            else:
                raise AppError(422, 'insufficient_quiz_material', '所选范围的可用原文不足以生成指定题量，请减少题量或扩大范围。')
        return chosen

    def _extractive_questions(self, chosen: list[tuple], citations: list[dict], difficulty: str) -> list[dict]:
        source_ids = {citation['chunk_id']: citation['citation_id'] for citation in citations}
        questions = []
        for index, (chunk, passage, question_type, term_choices) in enumerate(chosen):
            citation_id = source_ids[chunk['chunk_id']]
            prefix = f"原文阅读（难度标签：{difficulty}），《{chunk.get('section_title') or chunk['chapter_title']}》第 {chunk['page_start']} 页。"
            if question_type == 'short_answer':
                question = prefix + f'请依据引用原文，复述以下片段的主要意思：\n“{passage[:90]}”'
                options = []
                answer = passage
                explanation = f'参考答案直接摘录教材；作答时可在保留原意的前提下转述。难度为请求标签，未作难度测评。 [{citation_id}]'
            else:
                target, distractors = term_choices
                words = [target, *distractors]
                shift = index % 4
                words = words[shift:] + words[:shift]
                options = [{'key': chr(65 + position), 'text': word} for position, word in enumerate(words)]
                answer = chr(65 + words.index(target))
                question = prefix + '以下哪个词填入空白后，可以逐字还原本题引用的原文？\n“' + passage.replace(target, '______', 1) + '”'
                explanation = f'原文对应片段为：“{passage}”。选项均取自教材，正确词为“{target}”。难度为请求标签，未作难度测评。 [{citation_id}]'
            questions.append({
                'question_id': self._question_id(chunk['chunk_id'], passage, question_type, difficulty),
                'type': question_type, 'question': question, 'options': options, 'answer': answer,
                'explanation': explanation, 'citation_ids': [citation_id],
            })
        return questions

    def _llm_quiz(self, chunks: list[dict], count: int, question_types: list[str], difficulty: str, *, repo=None) -> dict:
        active_repo = repo or self.repo
        groups = list(self._groups(chunks).values())
        limit = min(len(chunks), max(count, len(groups)))
        selected = []
        for offset in range(max(map(len, groups))):
            for group in groups:
                if offset < len(group):
                    selected.append(group[offset])
        selected = selected[:limit]
        citations = self._citations(selected, repo=active_repo)
        expected_types = [question_types[index % len(question_types)] for index in range(count)]
        raw = self.generator.complete_json(
            'quiz', {'count': count, 'expected_types': expected_types, 'difficulty_label': difficulty,
                     'evidence': self.generator.context(citations)},
            '返回 {"questions":[{"type":"short_answer 或 multiple_choice","question":"问题",'
            '"options":[],"answer":"答案","explanation":"解析 [N]","citation_ids":[1],'
            '"evidence_quote":"从引用原文逐字复制的连续片段，至少12字"}]}。'
            '题目数量和顺序必须与 expected_types 一致。每题引用至少一个现有 citation_id。'
            '简答题 options=[]，answer 必须直接摘录 evidence_quote 中的连续原文，不加引用编号。'
            '单选题必须四个选项，key 顺序为 A B C D，answer 是唯一正确的 key；'
            '正确选项 text 必须是 evidence_quote 中的连续原文，其余选项 text 不得出现在 evidence_quote 中。'
            '单选题采用原文填空或原文辨识，保证仅一个正确选项。所有解析均附 [N] 引用。'
            '题干显示 difficulty_label 为难度标签，不宣称经过难度测评。不得重复题目。',
        )
        try:
            result = _Quiz.model_validate(raw)
        except ValidationError:
            raise AppError(502, 'invalid_model_output', '模型练习格式校验失败，请重试。') from None
        if len(result.questions) != count:
            raise AppError(502, 'invalid_model_quiz', '模型返回的题量与请求不一致，请重试。')
        seen_questions = set()
        questions = []
        for index, question in enumerate(result.questions):
            self._validate_model_question(question, expected_types[index], citations, seen_questions)
            public = question.model_dump(exclude={'evidence_quote'})
            public['question'] = f'难度标签：{difficulty}。' + public['question']
            public['question_id'] = self._question_id(
                json.dumps(question.citation_ids), question.question, question.type, difficulty,
            )
            questions.append(public)
        return {'questions': questions, 'citations': citations, 'generation_mode': 'llm'}

    def _validate_model_question(self, question: _Question, expected_type: str,
                                 citations: list[dict], seen_questions: set[str]) -> None:
        citations_by_id = {citation['citation_id']: citation for citation in citations}
        question_citation_ids = set(question.citation_ids)
        question_text = normalized_text(question.question)
        if (question.type != expected_type or len(question_citation_ids) != len(question.citation_ids)
                or not question_citation_ids <= citations_by_id.keys() or question_text in seen_questions):
            raise AppError(502, 'invalid_model_quiz', '模型练习题型、重复题或引用校验失败，请重试。')
        seen_questions.add(question_text)
        quote = normalized_text(question.evidence_quote)
        if not any(quote in normalized_text(citations_by_id[citation_id]['text'])
                   for citation_id in question_citation_ids):
            raise AppError(502, 'ungrounded_model_quiz', '模型练习的证据摘录与教材不一致，请重试。')
        text_citation_ids = validate_cited_text(question.explanation, citations)
        text_citation_ids |= validate_cited_text(question.question, citations, required=False)
        if not text_citation_ids <= question_citation_ids:
            raise AppError(502, 'invalid_model_citations', '题干或解析引用与本题证据不一致，请重试。')
        self._validate_model_answer(question, quote)

    @staticmethod
    def _validate_model_answer(question: _Question, quote: str) -> None:
        if question.type == 'short_answer':
            if question.options or normalized_text(question.answer) not in quote:
                raise AppError(502, 'ungrounded_model_quiz', '模型简答题的参考答案与证据摘录不一致，请重试。')
            return
        option_keys = [option.key for option in question.options]
        unique_options = {normalized_text(option.text).casefold() for option in question.options}
        if option_keys != list('ABCD') or question.answer not in ('A', 'B', 'C', 'D') or len(unique_options) != 4:
            raise AppError(502, 'invalid_model_quiz', '模型单选题选项或正确答案格式无效，请重试。')
        matches = [option.key for option in question.options if normalized_text(option.text) in quote]
        if matches != [question.answer]:
            raise AppError(502, 'ungrounded_model_quiz', '模型单选题的正确选项与证据摘录不一致，请重试。')

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

    @staticmethod
    def _question_id(chunk_id: str, passage: str, qtype: str, difficulty: str) -> str:
        value = '\0'.join((chunk_id, passage, qtype, difficulty)).encode('utf-8')
        return 'q_' + hashlib.sha256(value).hexdigest()[:16]

    @staticmethod
    def _cloze_terms(passage: str, text: str) -> tuple[str, list[str]] | None:
        candidates = [term for term in READING_TERMS if term in passage]
        candidates += re.findall(r'\b[A-Za-z][A-Za-z0-9_]{2,24}\b', passage)
        candidates += [piece[:3] for piece in re.findall(r'[\u4e00-\u9fff]{3,}', passage)]
        full = normalized_text(text)
        all_terms = [term for term in READING_TERMS if term in full]
        all_terms += re.findall(r'\b[A-Za-z][A-Za-z0-9_]{2,24}\b', full)
        all_terms += [piece[:3] for piece in re.findall(r'[\u4e00-\u9fff]{3,}', full)]
        # 仅大小写不同的答案选项仍视为同一选项。
        all_terms = list({term.casefold(): term for term in reversed(all_terms)}.values())[::-1]
        for target in candidates:
            distractors = [term for term in all_terms if term.casefold() != target.casefold()
                           and term not in target and target not in term
                           and passage.replace(target, term, 1) not in full]
            if len(distractors) >= 3:
                return target, distractors[:3]
        return None

"""生成与学习功能测试：所有模型响应均使用 MockTransport。"""
import copy
import json
import unittest
from unittest.mock import patch

import httpx

from backend.config import Settings
from backend.errors import AppError
from backend.services.generation import (
    GenerationService, INSUFFICIENT_ANSWER, normalized_text, reading_passages,
    validate_cited_text,
)
from backend.services.learning import LearningService


TEXT_A = (
    '智能体通过感知环境中的信息，使用模型规划任务，并借助工具与外部系统进行交互。'
    '人工智能系统需要根据任务目标选择合适的工具，同时在执行后检查返回的数据和反馈。'
    '在这个工作流中，记忆保存历史信息，规划模块负责拆解问题，模型负责完成推理。'
)
TEXT_B = (
    '检索系统先将知识库中的文本转换为向量，再根据问题与文本的相似程度选择相关内容。'
    '向量数据库保存文本对应的向量，检索模型使用这些数据为后续的回答提供原文证据。'
    '问答系统将问题和原文交给大语言模型，并为每条需要核查的结论保留对应的教材来源。'
)


def source(index=1, section='s1', text=TEXT_A):
    return {
        'citation_id': index, 'chunk_id': f'chunk-{index}', 'text': text,
        'source_file': 'fixture.pdf', 'chapter_id': 'ch01', 'chapter_title': '第一章 智能体',
        'section_id': section, 'section_title': f'小节 {section}' if section else None,
        'page_start': index + 10, 'page_end': index + 10,
        'source_url': f'/api/course/source#page={index + 10}', 'score': None, 'review_flags': [],
    }


class FakeRepo:
    def __init__(self, chunks=None):
        self.chunks = chunks if chunks is not None else [source(), source(2, 's2', TEXT_B)]

    def scoped_chunks(self, chapter_id, section_id=None):
        if chapter_id != 'ch01' or (section_id and section_id not in {c['section_id'] for c in self.chunks}):
            raise AppError(404, 'unknown_scope', '章节不存在。')
        return [c for c in self.chunks if not section_id or c['section_id'] == section_id]

    def evidence(self, chunk_id):
        return next(c for c in self.chunks if c['chunk_id'] == chunk_id)


def settings(**kwargs):
    defaults = {'generation_mode': 'extractive', 'llm_base_url': '', 'llm_model': '', 'llm_api_key': ''}
    defaults.update(kwargs)
    return Settings(**defaults)


def model_response(data, finish_reason='stop'):
    return httpx.Response(200, json={'choices': [{'finish_reason': finish_reason, 'message': {
        'role': 'assistant', 'content': json.dumps(data, ensure_ascii=False),
    }}]})


def llm_generator(data=None, handler=None, **overrides):
    config = {'generation_mode': 'llm', 'llm_base_url': 'https://fixture.invalid/v1', 'llm_model': 'fixture-model'}
    config.update(overrides)
    client = httpx.Client(transport=httpx.MockTransport(handler or (lambda request: model_response(data))))
    return GenerationService(settings(**config), client=client)


class GenerationTests(unittest.TestCase):
    def assert_app_error(self, status, code, call):
        with self.assertRaises(AppError) as caught:
            call()
        self.assertEqual(caught.exception.status_code, status)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_default_extractive_is_grounded_and_never_opens_network(self):
        with patch('backend.services.generation.httpx.Client', side_effect=AssertionError('network')):
            result = GenerationService(settings()).answer('什么是智能体？', [source()])
        self.assertEqual(result['generation_mode'], 'extractive')
        self.assertFalse(result['insufficient_evidence'])
        self.assertIn('原文摘录', result['answer'])
        self.assertIn('[1]', result['answer'])
        quoted = result['answer'].split('- ', 1)[1].rsplit(' [1]', 1)[0]
        self.assertIn(quoted, normalized_text(TEXT_A))

    def test_empty_evidence_skips_unconfigured_llm(self):
        with patch('backend.services.generation.httpx.Client', side_effect=AssertionError('network')):
            result = GenerationService(settings(generation_mode='llm')).answer('问题', [])
        self.assertTrue(result['insufficient_evidence'])
        self.assertEqual(result['answer'], INSUFFICIENT_ANSWER)

    def test_unrelated_extractive_evidence_reports_insufficient(self):
        result = GenerationService(settings()).answer('火星的地质年龄是多少？', [source()])
        self.assertTrue(result['insufficient_evidence'])

    def test_blank_evidence_reports_insufficient(self):
        result = GenerationService(settings()).answer('智能体', [source(text=' ')])
        self.assertTrue(result['insufficient_evidence'])

    def test_invalid_duplicate_evidence_id_is_rejected(self):
        self.assert_app_error(500, 'invalid_evidence', lambda: GenerationService(settings()).answer('智能体', [source(), source()]))

    def test_missing_llm_configuration_is_explicit(self):
        service = GenerationService(settings(generation_mode='llm'))
        self.assert_app_error(503, 'model_not_configured', lambda: service.answer('智能体', [source()]))

    def test_invalid_llm_url_rejected_before_request(self):
        for url in ['file:///tmp/service', 'https://user:password@fixture.invalid/v1',
                    'https://fixture.invalid/v1?token=private', 'http://fixture.invalid:not-a-port/v1',
                    'http://fixture.invalid:99999/v1', 'http://:8000/v1']:
            with self.subTest(url=url):
                service = llm_generator(llm_base_url=url)
                self.assert_app_error(503, 'model_not_configured', lambda: service.answer('智能体', [source()]))

    def test_valid_llm_request_is_json_mode_and_evidence_is_data(self):
        seen = []
        def handle(request):
            seen.append(request)
            return model_response({'answer': '智能体感知环境并执行任务。[1]', 'insufficient_evidence': False})
        service = llm_generator(handler=handle, llm_api_key='test-only-key', model_timeout=4.0)
        result = service.answer('什么是智能体？', [source()])
        self.assertEqual(result['generation_mode'], 'llm')
        request = seen[0]
        self.assertEqual(str(request.url), 'https://fixture.invalid/v1/chat/completions')
        self.assertEqual(request.headers['Authorization'], 'Bearer test-only-key')
        body = json.loads(request.content)
        self.assertEqual(body['response_format'], {'type': 'json_object'})
        self.assertFalse(body['stream'])
        self.assertLessEqual(body['max_tokens'], 4096)
        self.assertIn('JSON', body['messages'][0]['content'])
        self.assertEqual(json.loads(body['messages'][1]['content'])['evidence'][0]['text'], TEXT_A)
        self.assertEqual(request.extensions['timeout']['read'], 4.0)

    def test_local_compatible_service_can_omit_key(self):
        def handle(request):
            self.assertNotIn('Authorization', request.headers)
            return model_response({'answer': '智能体感知环境。[1]', 'insufficient_evidence': False})
        self.assertEqual(llm_generator(handler=handle).answer('智能体', [source()])['generation_mode'], 'llm')

    def test_owned_model_client_bypasses_system_proxy_only_for_loopback(self):
        cases = [
            ('http://localhost:9000/v1', False),
            ('http://LOCALHOST:9000/v1', False),
            ('http://127.0.0.1:9000/v1', False),
            ('http://127.22.33.44:9000/v1', False),
            ('http://[::1]:9000/v1', False),
            ('http://[0:0:0:0:0:0:0:1]:9000/v1', False),
            ('https://fixture.invalid/v1', True),
            ('http://192.168.1.10:9000/v1', True),
            ('https://localhost.fixture.invalid/v1', True),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                client = httpx.Client(transport=httpx.MockTransport(lambda request: model_response({
                    'answer': '智能体使用工具。[1]', 'insufficient_evidence': False,
                })), trust_env=False)
                service = GenerationService(settings(
                    generation_mode='llm', llm_base_url=url, llm_model='fixture-model'))
                with patch('backend.services.generation.httpx.Client', return_value=client) as constructor:
                    self.assertEqual(service.answer('智能体', [source()])['generation_mode'], 'llm')
                    constructor.assert_called_once_with(follow_redirects=False, trust_env=expected)
                self.assertTrue(client.is_closed)

    def test_injected_model_client_is_not_recreated_or_closed(self):
        service = llm_generator({'answer': '智能体使用工具。[1]', 'insufficient_evidence': False},
                                llm_base_url='http://127.0.0.1:9000/v1')
        with patch('backend.services.generation.httpx.Client', side_effect=AssertionError('new client')):
            self.assertEqual(service.answer('智能体', [source()])['generation_mode'], 'llm')
        self.assertFalse(service.client.is_closed)
        service.client.close()

    def test_already_complete_endpoint_is_not_duplicated(self):
        service = llm_generator(llm_base_url='http://localhost:9000/v1/chat/completions/')
        self.assertEqual(service._endpoint(), 'http://localhost:9000/v1/chat/completions')

    def test_http_failures_are_sanitized(self):
        for status in (301, 401, 429, 500):
            with self.subTest(status=status):
                handler = lambda request: httpx.Response(status, text='private-key upstream stack trace', headers={'Location': 'https://other.invalid'})
                service = llm_generator(handler=handler)
                error = self.assert_app_error(502, 'model_upstream_error', lambda: service.answer('智能体', [source()]))
                self.assertNotIn('private-key', error.message)
                self.assertNotIn('stack trace', error.message)

    def test_timeout_maps_to_504(self):
        def handle(request):
            raise httpx.ReadTimeout('private-key upstream error', request=request)
        error = self.assert_app_error(504, 'model_timeout', lambda: llm_generator(handler=handle).answer('智能体', [source()]))
        self.assertNotIn('private-key', error.message)

    def test_invalid_upstream_url_error_is_sanitized(self):
        def handle(request):
            raise httpx.InvalidURL('private-key upstream detail')
        error = self.assert_app_error(502, 'model_upstream_error', lambda: llm_generator(handler=handle).answer('智能体', [source()]))
        self.assertNotIn('private-key', error.message)

    def test_deeply_nested_upstream_json_is_controlled(self):
        response = httpx.Response(200, content='[' * 2000 + '0' + ']' * 2000)
        service = llm_generator(handler=lambda request: response)
        with self.assertRaises(AppError) as caught:
            service.answer('智能体', [source()])
        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn(caught.exception.code, {'model_upstream_error', 'invalid_model_output'})

    def test_connect_error_maps_to_502(self):
        def handle(request):
            raise httpx.ConnectError('private host', request=request)
        self.assert_app_error(502, 'model_upstream_error', lambda: llm_generator(handler=handle).answer('智能体', [source()]))

    def test_invalid_envelopes_and_truncated_output_are_rejected(self):
        responses = [httpx.Response(200, json={}), httpx.Response(200, json={'choices': []}),
                     httpx.Response(200, text='not JSON'),
                     model_response({'answer': '内容 [1]', 'insufficient_evidence': False}, 'length'),
                     model_response(['not an object'])]
        for response in responses:
            with self.subTest(response=response):
                service = llm_generator(handler=lambda request: response)
                with self.assertRaises(AppError) as caught:
                    service.answer('智能体', [source()])
                self.assertEqual(caught.exception.status_code, 502)

    def test_output_schema_is_strict(self):
        for data in [
            {'answer': '', 'insufficient_evidence': False},
            {'answer': '内容 [1]', 'insufficient_evidence': 'false'},
            {'answer': '内容 [1]', 'insufficient_evidence': False, 'injected': True},
            {'answer': '内容 [1]'},
        ]:
            with self.subTest(data=data):
                self.assert_app_error(502, 'invalid_model_output', lambda: llm_generator(data).answer('智能体', [source()]))

    def test_missing_unknown_or_malformed_citations_are_rejected(self):
        for answer in ['未标注引用', '引用未知来源 [99]', '非法合并 [1, 99]', '非法范围 [1-99]',
                       '非规范编号 [01]', '非 ASCII 编号 [١]', '超长编号 [' + '9' * 5000 + ']']:
            with self.subTest(answer=answer):
                service = llm_generator({'answer': answer, 'insufficient_evidence': False})
                self.assert_app_error(502, 'invalid_model_citations', lambda: service.answer('智能体', [source()]))

    def test_model_insufficient_flag_never_returns_unsupported_content(self):
        result = llm_generator({'answer': '未证实的杜撰答案', 'insufficient_evidence': True}).answer('问题', [source()])
        self.assertTrue(result['insufficient_evidence'])
        self.assertEqual(result['answer'], INSUFFICIENT_ANSWER)

    def test_context_and_response_are_bounded(self):
        service = llm_generator({'answer': '内容 [1]', 'insufficient_evidence': False})
        with patch('backend.services.generation.MAX_CONTEXT_CHARS', 20):
            self.assert_app_error(422, 'generation_context_too_large', lambda: service.answer('智能体', [source()]))
        with patch('backend.services.generation.MAX_RESPONSE_BYTES', 20):
            self.assert_app_error(502, 'model_response_too_large', lambda: service.answer('智能体', [source()]))


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRepo()
        self.service = LearningService(self.repo, GenerationService(settings()))

    def test_summary_covers_each_section_with_real_sources(self):
        result = self.service.summary('ch01')
        self.assertEqual(result['generation_mode'], 'extractive')
        self.assertEqual(result['coverage']['sections_total'], 2)
        self.assertEqual(result['coverage']['sections_covered'], 2)
        self.assertTrue(result['coverage']['representative_only'])
        self.assertEqual(len(result['key_points']), 2)
        self.assertEqual({c['section_id'] for c in result['citations']}, {'s1', 's2'})
        self.assertEqual(validate_cited_text(result['summary'], result['citations']), {1, 2})

    def test_summary_scope_and_chapter_intro_are_explicit(self):
        self.repo.chunks.insert(0, source(3, None, '本章介绍智能体、人工智能和模型，讨论工具与环境如何配合完成任务。'))
        full = self.service.summary('ch01')
        self.assertTrue(full['coverage']['chapter_intro_included'])
        self.assertEqual(full['coverage']['sections_total'], 2)
        scoped = self.service.summary('ch01', 's2')
        self.assertEqual(scoped['coverage']['section_ids'], ['s2'])
        self.assertEqual(len(scoped['citations']), 1)
        # 对指定范围内的结果重新编号，不应修改语料仓库状态。
        self.assertEqual(self.repo.chunks[-1]['citation_id'], 2)

    def test_summary_keeps_section_order_and_first_candidate_on_ties(self):
        repo = FakeRepo([source(3, None), source(2, 's2'), source(1, 's1'), source(4, 's1')])
        original = copy.deepcopy(repo.chunks)
        result = LearningService(repo, GenerationService(settings())).summary('ch01')
        self.assertEqual([c['chunk_id'] for c in result['citations']], ['chunk-3', 'chunk-2', 'chunk-1'])
        self.assertEqual([c['citation_id'] for c in result['citations']], [1, 2, 3])
        self.assertEqual(repo.chunks, original)

    def test_unknown_scope_keeps_repository_404(self):
        for call in [lambda: self.service.summary('ch99'), lambda: self.service.quiz('ch01', 'missing')]:
            with self.assertRaises(AppError) as caught:
                call()
            self.assertEqual(caught.exception.status_code, 404)

    def test_default_short_answer_quiz_has_exact_count_and_grounding(self):
        result = self.service.quiz('ch01')
        self.assertEqual(len(result['questions']), 5)
        self.assertEqual(result['generation_mode'], 'extractive')
        sources = {c['citation_id']: normalized_text(c['text']) for c in result['citations']}
        self.assertEqual(len({q['question_id'] for q in result['questions']}), 5)
        for q in result['questions']:
            self.assertEqual(q['type'], 'short_answer')
            self.assertEqual(q['options'], [])
            self.assertIn(q['answer'], sources[q['citation_ids'][0]])
            self.assertIn('medium', q['question'])

    def test_multiple_choice_options_restore_source_exactly(self):
        result = self.service.quiz('ch01', count=5, question_types=['multiple_choice'], difficulty='hard')
        sources = {c['citation_id']: normalized_text(c['text']) for c in result['citations']}
        for q in result['questions']:
            self.assertEqual([o['key'] for o in q['options']], list('ABCD'))
            self.assertEqual(len({o['text'].casefold() for o in q['options']}), 4)
            original = sources[q['citation_ids'][0]]
            masked = q['question'].split('“', 1)[1].rsplit('”', 1)[0]
            correct = next(o['text'] for o in q['options'] if o['key'] == q['answer'])
            self.assertIn(masked.replace('______', correct, 1), original)
            for option in q['options']:
                self.assertIn(option['text'], original)
                if option['key'] != q['answer']:
                    self.assertNotIn(masked.replace('______', option['text'], 1), original)
            self.assertIn('hard', q['question'])

    def test_local_multiple_choice_excludes_alternative_source_restorations(self):
        passage = '智能体通过感知环境中的信息，使用模型规划任务，并借助工具与外部系统进行交互。'
        alternate = passage.replace('智能体', '工作流', 1)
        text = passage + alternate + '人工智能与机器学习通过数据和训练执行检索任务。'
        choice = self.service._cloze_terms(passage, text)
        self.assertIsNotNone(choice)
        target, distractors = choice
        for distractor in distractors:
            self.assertNotIn(passage.replace(target, distractor, 1), normalized_text(text))

    def test_local_multiple_choice_distractors_are_case_insensitively_unique(self):
        passage = 'AgentAlpha performs several useful planning and execution tasks for users.'
        text = passage + ' Delta DELTA Epsilon Zeta represent identifiers in the same example.'
        target, distractors = self.service._cloze_terms(passage, text)
        self.assertEqual(len({word.casefold() for word in [target, *distractors]}), 4)

    def test_mixed_quiz_preserves_requested_order_and_determinism(self):
        first = self.service.quiz('ch01', count=4, question_types=['multiple_choice', 'short_answer'])
        second = self.service.quiz('ch01', count=4, question_types=['multiple_choice', 'short_answer'])
        self.assertEqual(first, second)
        self.assertEqual([q['type'] for q in first['questions']], ['multiple_choice', 'short_answer'] * 2)

    def test_empty_or_insufficient_material_is_explicit(self):
        empty = LearningService(FakeRepo([]), GenerationService(settings()))
        for call in [lambda: empty.summary('ch01'), lambda: empty.quiz('ch01'), lambda: self.service.quiz('ch01', count=20)]:
            with self.assertRaises(AppError) as caught:
                call()
            self.assertEqual(caught.exception.status_code, 422)

    def test_invalid_quiz_requests_do_not_silently_change_count(self):
        for kwargs in [{'count': 0}, {'count': 21}, {'count': True}, {'question_types': []},
                       {'question_types': ['essay']}, {'difficulty': 'unmeasured'},
                       {'count': 1, 'question_types': ['short_answer', 'multiple_choice']}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(AppError) as caught:
                self.service.quiz('ch01', **kwargs)
            self.assertEqual(caught.exception.status_code, 422)

    def test_llm_summary_validates_every_selected_section(self):
        data = {'summary': '智能体与检索的代表性概述。[1][2]', 'key_points': ['智能体使用工具。[1]', '检索保留证据。[2]']}
        result = LearningService(self.repo, llm_generator(data)).summary('ch01')
        self.assertEqual(result['generation_mode'], 'llm')
        self.assertIn('代表性', result['summary'])
        for bad in [dict(data, key_points=['不带引用']), {'summary': '智能体概述。[1]', 'key_points': ['智能体使用工具。[1]']}]:
            with self.subTest(data=bad), self.assertRaises(AppError) as caught:
                LearningService(self.repo, llm_generator(bad)).summary('ch01')
            self.assertEqual(caught.exception.status_code, 502)

    @staticmethod
    def llm_question(qtype='short_answer'):
        quote = reading_passages(TEXT_A)[0]
        return {
            'type': qtype,
            'question': '根据教材原文，哪个词可以补全句子“______通过感知环境中的信息”？',
            'options': [] if qtype == 'short_answer' else [
                {'key': 'A', 'text': '智能体'}, {'key': 'B', 'text': '计算机鼠标'},
                {'key': 'C', 'text': '电子邮件'}, {'key': 'D', 'text': '分布式数据库'},
            ],
            'answer': quote if qtype == 'short_answer' else 'A',
            'explanation': '根据引用的原文，智能体通过感知环境中的信息完成相关活动。[1]',
            'citation_ids': [1], 'evidence_quote': quote,
        }

    def test_llm_quiz_valid_structured_short_and_multiple_choice(self):
        for qtype in ['short_answer', 'multiple_choice']:
            with self.subTest(qtype=qtype):
                data = {'questions': [self.llm_question(qtype)]}
                result = LearningService(self.repo, llm_generator(data)).quiz('ch01', count=1, question_types=[qtype])
                q = result['questions'][0]
                self.assertNotIn('evidence_quote', q)
                self.assertTrue(q['question_id'].startswith('q_'))
                self.assertIn('medium', q['question'])

    def test_llm_quiz_samples_uneven_sections_in_round_robin_order(self):
        chunks = [source(1, 's1'), source(2, 's1'), source(3, 's1'), source(4, None),
                  source(5, 's2'), source(6, 's2'), source(7, 's3', '   ')]
        original = copy.deepcopy(chunks)
        order = ['chunk-1', 'chunk-4', 'chunk-5', 'chunk-2', 'chunk-6', 'chunk-3']
        for count in (1, 4, 7):
            with self.subTest(count=count):
                questions = [dict(self.llm_question(), question=f'教材原文阅读第 {i + 1} 题，请概括智能体的活动。')
                             for i in range(count)]
                service = LearningService(FakeRepo(chunks), llm_generator({'questions': questions}))
                result = service.quiz('ch01', count=count)
                self.assertEqual([c['chunk_id'] for c in result['citations']], order[:max(count, 3)])
                self.assertEqual(len(result['questions']), count)
                self.assertEqual(chunks, original)

    def test_llm_quiz_wrong_count_type_quote_answer_and_citations_fail(self):
        original = self.llm_question()
        bad_cases = [
            {'questions': [original, original]},
            {'questions': [dict(original, type='multiple_choice')]},
            {'questions': [dict(original, evidence_quote='这段捏造的内容在真实教材中从未出现。')]},
            {'questions': [dict(original, answer='没有任何教材证据支持的答案')]},
            {'questions': [dict(original, citation_ids=[99])]},
            {'questions': [dict(original, citation_ids=[1, 1])]},
            {'questions': [dict(original, explanation='引用其他材料。[2]')]},
            {'questions': [dict(original, citation_ids=['1'])]},
        ]
        for data in bad_cases:
            with self.subTest(data=data), self.assertRaises(AppError) as caught:
                LearningService(self.repo, llm_generator(data)).quiz('ch01', count=1)
            self.assertEqual(caught.exception.status_code, 502)

    def test_llm_quiz_whitespace_fields_are_rejected(self):
        original = self.llm_question()
        bad_cases = [dict(original, answer=' '), dict(original, question=' ' * 8),
                     dict(original, evidence_quote=' ' * 12),
                     dict(original, evidence_quote='  很短  ' + ' ' * 12)]
        multiple_choice = self.llm_question('multiple_choice')
        multiple_choice['options'][0]['text'] = ' '
        bad_cases.append(multiple_choice)
        for question in bad_cases:
            with self.subTest(question=question), self.assertRaises(AppError) as caught:
                LearningService(self.repo, llm_generator({'questions': [question]})).quiz(
                    'ch01', count=1, question_types=[question['type']])
            self.assertEqual(caught.exception.status_code, 502)

    def test_llm_multiple_choice_rejects_ambiguous_options(self):
        original = self.llm_question('multiple_choice')
        bad_cases = [dict(original, answer='B'), dict(original, answer='E'),
                     dict(original, answer='AB'), dict(original, answer='CD'),
                     dict(original, options=original['options'][:3])]
        duplicate = copy.deepcopy(original)
        duplicate['options'][1]['text'] = duplicate['options'][0]['text']
        bad_cases.append(duplicate)
        ambiguous = copy.deepcopy(original)
        ambiguous['options'][1]['text'] = '环境'
        bad_cases.append(ambiguous)
        for q in bad_cases:
            with self.subTest(question=q), self.assertRaises(AppError) as caught:
                LearningService(self.repo, llm_generator({'questions': [q]})).quiz('ch01', count=1, question_types=['multiple_choice'])
            self.assertEqual(caught.exception.status_code, 502)


if __name__ == '__main__':
    unittest.main()

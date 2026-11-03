"""通过 HTTP 模拟传输执行全部五个 Streamlit 页面。"""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import UUID

import httpx
import streamlit as st
from streamlit.testing.v1 import AppTest

from frontend.api_client import APIClient


ROOT = Path(__file__).resolve().parents[1]
CITATION = {
    'citation_id': 1, 'chunk_id': 'chunk-1', 'text': '智能体通过感知、决策和行动与环境交互。',
    'source_file': 'course.pdf', 'chapter_id': 'ch01', 'chapter_title': '第一章 初识智能体',
    'section_id': 'ch01-s001', 'section_title': '1.1 什么是智能体', 'page_start': 10, 'page_end': 11,
    'source_url': 'https://untrusted.example/ignored', 'review_flags': [],
}
CHAPTERS = [{'chapter_id': 'ch01', 'title': '第一章 初识智能体', 'sections': [
    {'section_id': 'ch01-s001', 'title': '1.1 什么是智能体'}]},
    {'chapter_id': 'ch02', 'title': '第二章 发展史', 'sections': [{'section_id': 'ch02-s001', 'title': '2.1 历史'}]}]


class FakeAPI:
    def __init__(self):
        self.requests = []
        self.records = []
        self.ready = True
        self.fail_qa = False
        self.generation_mode = 'extractive'
        self.retrieval_modes = ['bm25']
        self.answer = '智能体能够感知并行动。[1]'
        self.summary = '章节原文摘要。[1]'
        self.citation = dict(CITATION)

    def handle(self, request):
        self.requests.append(request)
        path = request.url.path
        if path == '/api/health':
            return httpx.Response(200, json={'status': 'ok', 'knowledge_base_ready': self.ready,
                'retrieval_modes': self.retrieval_modes, 'generation_mode': 'extractive', 'chunk_count': 2})
        if path == '/api/course':
            return httpx.Response(200, json={'id': 'course', 'name': '课程教材', 'dataset_version': 'v1', 'chunk_count': 2})
        if path == '/api/chapters':
            return httpx.Response(200, json={'chapters': CHAPTERS})
        if path == '/api/qa':
            if self.fail_qa:
                return httpx.Response(503, json={'error': {'code': 'model_not_ready', 'message': '模型服务尚未配置'}, 'request_id': 'request-error'})
            body = json.loads(request.content)
            answer = {'answer': self.answer, 'citations': [self.citation],
                'generation_mode': self.generation_mode, 'retrieval_mode': 'bm25', 'insufficient_evidence': False,
                'scope': {'chapter_id': body.get('chapter_id'), 'section_id': body.get('section_id')},
                'request_id': 'request-1', 'latency_ms': 10, 'session_id': body['session_id'], 'history_id': 'item-1'}
            self.records.append({**answer, 'id': 'item-1', 'question': body['question'], 'created_at': '2026-10-25T12:00:00Z'})
            return httpx.Response(200, json=answer)
        if path == '/api/summary':
            return httpx.Response(200, json={'summary': self.summary, 'key_points': ['智能体通过感知和行动与环境交互。[1]'],
                'citations': [self.citation], 'coverage': {'sections_covered': 1, 'sections_total': 2,
                    'chunks_selected': 1, 'chunks_total': 4, 'representative_only': True,
                    'chapter_intro_included': True}, 'generation_mode': self.generation_mode})
        if path == '/api/quiz':
            body = json.loads(request.content)
            questions = []
            for number in range(body['count']):
                kind = body['question_types'][number % len(body['question_types'])]
                questions.append({'question_id': f'q-{number}', 'type': kind, 'question': '请根据教材说明智能体的构成。',
                    'options': [{'key': 'A', 'text': '感知与行动'}, {'key': 'B', 'text': '单纯存储'}] if kind == 'multiple_choice' else [],
                    'answer': 'A' if kind == 'multiple_choice' else '感知与行动', 'explanation': '教材说明智能体感知环境并行动。[1]', 'citation_ids': [1]})
            return httpx.Response(200, json={'questions': questions, 'citations': [self.citation], 'generation_mode': 'extractive'})
        if path == '/api/history' and request.method == 'DELETE':
            deleted = len(self.records)
            self.records.clear()
            return httpx.Response(200, json={'deleted': deleted})
        if path == '/api/history':
            records = [item for item in self.records if item['session_id'] == request.url.params['session_id']]
            return httpx.Response(200, json={'items': records, 'total': len(records), 'limit': 10, 'offset': 0})
        if path == '/api/history/item-1' and request.method == 'DELETE':
            self.records.clear()
            return httpx.Response(204)
        return httpx.Response(404, json={'error': {'code': 'not_found', 'message': '记录不存在'}})


class FrontendPagesTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.client = APIClient('http://testserver', transport=httpx.MockTransport(self.api.handle))
        self.patcher = patch('frontend.components.ui.get_api_client', return_value=self.client)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.client.close)

    def app(self, page='pages/qa.py'):
        at = AppTest.from_file(str(ROOT / 'frontend/app.py')).run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        if page:
            at.switch_page(page).run(timeout=15)
            self.assertEqual(len(at.exception), 0)
        return at

    def test_learning_workspace_is_the_default_entry(self):
        at = self.app(page=None)
        self.assertTrue(any(item.value == '学习工作台' for item in at.title))
        content = '\n'.join(item.value for item in [*at.markdown, *at.caption])
        for text in ('先了解', '再提问', '后练习', '再回顾'):
            self.assertIn(text, content)
        self.assertTrue(any(item.label == '课程章节' and item.value == '2' for item in at.metric))
        self.assertTrue(any(item.label == '本次会话提问' and item.value == '0' for item in at.metric))
        self.assertTrue(any(item.value == '课程目录' for item in at.subheader))
        for label in ('学习本章总结', '针对本章提问', '开始本章练习'):
            self.assertTrue(any(item.label == label for item in at.button))
        self.assertTrue(any(request.url.path == '/api/history' for request in self.api.requests))

    def test_workspace_keeps_selected_chapter_when_opening_summary(self):
        at = self.app(page=None)
        at.selectbox(key='overview_chapter').set_value('ch02').run(timeout=15)
        next(item for item in at.button if item.label == '学习本章总结').click().run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        self.assertTrue(any(item.value == '章节总结' for item in at.title))
        self.assertEqual(at.selectbox(key='summary_chapter').value, 'ch02')

    def ask(self, at):
        at.text_area[0].input('什么是智能体？')
        next(button for button in at.button if button.label == '发送').click().run(timeout=15)
        self.assertEqual(len(at.exception), 0)

    def test_question_scope_citations_and_session_history(self):
        at = self.app()
        self.assertFalse(at.text_area[0].disabled)
        at.selectbox(key='qa_chapter').set_value('ch01').run()
        at.selectbox(key='qa_section_ch01').set_value('ch01-s001').run()
        self.ask(at)
        body = json.loads(next(request for request in self.api.requests if request.url.path == '/api/qa').content)
        self.assertEqual((body['chapter_id'], body['section_id']), ('ch01', 'ch01-s001'))
        UUID(body['session_id'])
        self.assertTrue(any('能够感知并行动' in item.value for item in at.markdown))
        self.assertTrue(any('教材原文摘录' in item.value for item in at.caption))
        self.assertEqual(at.get('link_button')[0].proto.url, 'http://testserver/api/course/source#page=10')
        at.switch_page('pages/history.py').run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        request = next(request for request in reversed(self.api.requests) if request.url.path == '/api/history')
        self.assertEqual(request.url.params['session_id'], body['session_id'])
        at.button(key='history_delete_item-1').click().run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(self.api.records, [])
        self.assertTrue(any('已删除' in item.value for item in at.success))

    def test_summary_scope_and_coverage(self):
        at = self.app()
        at.switch_page('pages/summary.py').run(timeout=15)
        at.selectbox(key='summary_chapter').set_value('ch02').run()
        at.selectbox(key='summary_section_ch02').set_value('ch02-s001').run()
        at.button(key='summary_submit').click().run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        body = json.loads(next(request for request in self.api.requests if request.url.path == '/api/summary').content)
        self.assertEqual(body, {'chapter_id': 'ch02', 'section_id': 'ch02-s001'})
        self.assertTrue(any('章节原文摘要' in item.value for item in at.markdown))
        self.assertTrue(any(item.label == '证据覆盖情况' for item in at.expander))

    def test_quiz_options_answer_hidden_and_payload(self):
        at = self.app()
        at.switch_page('pages/quiz.py').run(timeout=15)
        at.number_input[0].set_value(2)
        at.multiselect[0].set_value(['short_answer', 'multiple_choice'])
        next(item for item in at.selectbox if item.label == '难度').set_value('hard')
        at.button(key='quiz_submit').click().run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        body = json.loads(next(request for request in self.api.requests if request.url.path == '/api/quiz').content)
        self.assertEqual((body['count'], body['difficulty']), (2, 'hard'))
        self.assertEqual(body['question_types'], ['short_answer', 'multiple_choice'])
        self.assertFalse(any('答案与解析' in item.label for item in at.expander))
        self.assertTrue(at.button(key='quiz_check').disabled is False)
        self.assertEqual(len(at.radio), 1)
        self.assertIsNone(at.radio[0].value)

    def test_quiz_requires_complete_answers_then_scores_objective_questions(self):
        at = self.app()
        at.switch_page('pages/quiz.py').run(timeout=15)
        at.number_input[0].set_value(2)
        at.multiselect[0].set_value(['short_answer', 'multiple_choice'])
        at.button(key='quiz_submit').click().run(timeout=15)
        at.button(key='quiz_check').click().run(timeout=15)
        self.assertTrue(any('请完成全部题目' in item.value for item in at.warning))
        self.assertFalse(any('答案与解析' in item.label for item in at.expander))
        at.text_area[0].input('智能体通过感知和行动与环境交互。')
        at.radio[0].set_value('A. 感知与行动').run(timeout=15)
        at.button(key='quiz_check').click().run(timeout=15)
        self.assertTrue(any('单选题答对 1 / 1' in item.value for item in at.success))
        self.assertTrue(any('简答题已完成 1 / 1' in item.value for item in at.info))
        self.assertEqual(len([item for item in at.expander if '答案与解析' in item.label]), 2)

    def test_quiz_marks_wrong_multiple_choice_without_semantic_short_answer_scoring(self):
        at = self.app()
        at.switch_page('pages/quiz.py').run(timeout=15)
        at.number_input[0].set_value(1)
        at.multiselect[0].set_value(['multiple_choice'])
        at.button(key='quiz_submit').click().run(timeout=15)
        at.radio[0].set_value('B. 单纯存储').run(timeout=15)
        at.button(key='quiz_check').click().run(timeout=15)
        self.assertTrue(any('单选题答对 0 / 1' in item.value for item in at.error))
        self.assertTrue(any('题回答错误' in item.value for item in at.error))
        self.assertFalse(any('简答题' in item.value and '答对' in item.value for item in at.success))

    def test_quiz_submission_locks_snapshot_and_retries_marked_questions(self):
        at = self.app()
        at.switch_page('pages/quiz.py').run(timeout=15)
        at.number_input[0].set_value(2)
        at.multiselect[0].set_value(['short_answer', 'multiple_choice'])
        at.button(key='quiz_submit').click().run(timeout=15)
        at.text_area[0].input('智能体通过感知和行动与环境交互。')
        at.radio[0].set_value('A. 感知与行动').run(timeout=15)
        at.button(key='quiz_check').click().run(timeout=15)
        self.assertEqual(at.session_state['quiz_submitted_answers'],
                         ['智能体通过感知和行动与环境交互。', 'A'])
        self.assertTrue(at.text_area[0].disabled)
        self.assertTrue(next(item for item in at.radio if item.label == '你的选择').disabled)
        review = next(item for item in at.radio if item.label == '第 1 题自评')
        review.set_value('待复习').run(timeout=15)
        self.assertTrue(any(item.label == '已标记待复习' and item.value == '1'
                            for item in at.metric))
        at.button(key='quiz_retry_marked_1').click().run(timeout=15)
        self.assertEqual(len(at.session_state['quiz_result']['questions']), 1)
        self.assertEqual(at.session_state['quiz_result']['questions'][0]['type'], 'short_answer')
        self.assertFalse(at.text_area[0].disabled)
        self.assertFalse(any('答案与解析' in item.label for item in at.expander))

    def test_history_clear_requires_explicit_confirmation(self):
        at = self.app()
        self.ask(at)
        at.switch_page('pages/history.py').run(timeout=15)
        self.assertTrue(at.button(key='history_clear').disabled)
        at.checkbox(key='history_clear_confirm').check().run()
        at.button(key='history_clear').click().run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(self.api.records, [])
        self.assertTrue(any('已清空 1 条' in item.value for item in at.success))
        self.assertFalse(at.checkbox(key='history_clear_confirm').value)
        self.assertEqual(at.number_input(key='history_page').value, 1)
        self.assertFalse(any('default value' in warning.value for warning in at.warning))

    def test_history_page_session_default_has_no_widget_warning(self):
        at = self.app()
        at.session_state['history_page'] = 2
        at.switch_page('pages/history.py').run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(at.number_input(key='history_page').value, 2)
        self.assertFalse(any('default value' in warning.value for warning in at.warning))
        request = next(request for request in reversed(self.api.requests) if request.url.path == '/api/history')
        self.assertEqual(request.url.params['offset'], '10')

    def test_quiz_regeneration_resets_previous_answers(self):
        at = self.app()
        at.switch_page('pages/quiz.py').run(timeout=15)
        at.number_input[0].set_value(2)
        at.multiselect[0].set_value(['short_answer', 'multiple_choice'])
        at.button(key='quiz_submit').click().run(timeout=15)
        at.text_area[0].input('旧的简答作答')
        at.radio[0].set_value('A. 感知与行动').run()
        at.button(key='quiz_submit').click().run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(at.text_area[0].value, '')
        self.assertIsNone(at.radio[0].value)

    def test_quiz_count_covers_selected_types_before_http_request(self):
        at = self.app()
        at.switch_page('pages/quiz.py').run(timeout=15)
        at.number_input[0].set_value(1)
        at.multiselect[0].set_value(['short_answer', 'multiple_choice'])
        at.button(key='quiz_submit').click().run(timeout=15)
        self.assertTrue(any('题量应不少于' in item.value for item in at.warning))
        self.assertFalse(any(request.url.path == '/api/quiz' for request in self.api.requests))

    def test_llm_mode_is_not_mislabeled_as_local_extraction(self):
        self.api.generation_mode = 'llm'
        at = self.app()
        self.ask(at)
        self.assertTrue(any('大模型依据教材证据生成' in item.value for item in at.caption))
        self.assertFalse(any('未调用大模型' in item.value for item in at.caption))

    def test_degraded_knowledge_base_disables_submission(self):
        self.api.ready = False
        at = self.app()
        self.assertTrue(at.text_area[0].disabled)
        self.assertTrue(next(button for button in at.button if button.label == '发送').disabled)
        for page, button in [('summary', 'summary_submit'), ('quiz', 'quiz_submit')]:
            at.switch_page(f'pages/{page}.py').run(timeout=15)
            self.assertEqual(len(at.exception), 0)
            self.assertTrue(at.button(key=button).disabled)
        self.assertFalse(any(request.url.path == '/api/course' for request in self.api.requests))

    def test_backend_failure_is_visible_without_traceback(self):
        def fail(request):
            raise httpx.ConnectError('offline', request=request)
        with APIClient('http://testserver', transport=httpx.MockTransport(fail)) as offline:
            with patch('frontend.components.ui.get_api_client', return_value=offline):
                at = self.app()
                self.assertTrue(at.text_area[0].disabled)
                self.assertTrue(any('后端连接中断' in item.value for item in at.error))
                for page in ('summary', 'quiz', 'history'):
                    at.switch_page(f'pages/{page}.py').run(timeout=15)
                    self.assertEqual(len(at.exception), 0)
                    self.assertTrue(any('后端连接中断' in item.value for item in at.error))

    def test_submission_error_uses_request_id(self):
        self.api.fail_qa = True
        at = self.app()
        self.ask(at)
        self.assertTrue(any('模型服务尚未配置' in item.value for item in at.error))
        self.assertTrue(any('request-error' in item.value for item in at.caption))

    def test_independent_browser_sessions_have_distinct_ids(self):
        first = self.app()
        second = self.app()
        self.assertNotEqual(first.session_state['session_uuid'], second.session_state['session_uuid'])

    def test_framework_uses_minimal_toolbar(self):
        self.app()
        self.assertEqual(st.get_option('client.toolbarMode'), 'minimal')

    def test_chinese_retrieval_labels_keep_protocol_values(self):
        self.api.retrieval_modes = ['bm25', 'vector', 'hybrid']
        at = self.app()
        select = at.selectbox(key='qa_retrieval_mode')
        self.assertEqual(select.options, ['关键词检索', '向量检索', '混合检索'])
        select.set_value('hybrid').run()
        self.assertTrue(any('实验能力' in item.value and '拒答' in item.value for item in at.warning))
        self.ask(at)
        body = json.loads(next(request for request in self.api.requests if request.url.path == '/api/qa').content)
        self.assertEqual(body['retrieval_mode'], 'hybrid')

    def test_coverage_uses_chinese_labels_instead_of_json(self):
        at = self.app()
        at.switch_page('pages/summary.py').run()
        at.button(key='summary_submit').click().run()
        self.assertEqual(len(at.json), 0)
        self.assertTrue(any('小节覆盖：1 / 2' in item.value for item in at.markdown))
        self.assertTrue(any('文本块选取：1 / 4' in item.value for item in at.markdown))
        self.assertTrue(any('已包含章节导读' in item.value for item in at.caption))

    def test_legacy_mode_label_is_chinese_in_answers_and_history(self):
        self.api.answer = '原文摘录（extractive）：Agent（智能体）能够感知并行动。[1]'
        at = self.app()
        self.ask(at)
        for page in (None, 'pages/history.py'):
            if page:
                at.switch_page(page).run()
            content = '\n'.join(item.value for item in at.markdown)
            self.assertNotIn('extractive', content)
            self.assertIn('Agent（智能体）', content)
        self.assertIn('（extractive）', self.api.records[0]['answer'])

    def test_summary_mode_label_is_chinese(self):
        self.api.summary = '原文摘录总结（extractive）：章节原文摘要。[1]'
        at = self.app()
        at.switch_page('pages/summary.py').run()
        at.button(key='summary_submit').click().run()
        content = '\n'.join(item.value for item in at.markdown)
        self.assertNotIn('extractive', content)
        self.assertIn('原文摘录总结：', content)

    def test_llm_summary_mode_label_is_chinese(self):
        self.api.generation_mode = 'llm'
        self.api.summary = '代表性小节总结（llm，非逐段完整覆盖）：\n\n教材中的 llm 原文保持。[1]'
        at = self.app()
        at.switch_page('pages/summary.py').run()
        at.button(key='summary_submit').click().run()
        content = '\n'.join(item.value for item in at.markdown)
        self.assertNotIn('（llm，', content)
        self.assertIn('代表性小节总结（大模型生成，非逐段完整覆盖）：', content)
        self.assertIn('教材中的 llm 原文保持。[1]', content)
        self.assertTrue(any('大模型依据教材证据生成' in item.value for item in at.caption))

    def test_learning_text_does_not_change_prefix_words_inside_original_text(self):
        from frontend.components.ui import learning_text

        original = '教材例句中出现“原文摘录（extractive）：”，这部分属于原文。'
        self.assertEqual(learning_text(original), original)

    def test_metadata_and_review_flags_are_chinese(self):
        self.api.citation['review_flags'] = ['low_text', 'image_resource', 'figure_or_table_reference', 'unresolved_glyph', 'future_flag']
        at = self.app()
        self.ask(at)
        captions = '\n'.join(item.value for item in at.caption)
        self.assertIn('处理耗时：10 毫秒', captions)
        self.assertIn('文字较少', captions)
        self.assertIn('含图片资源', captions)
        self.assertIn('含图表引用', captions)
        self.assertIn('存在待核对字符', captions)
        self.assertIn('需要人工复核', captions)
        for flag in self.api.citation['review_flags']:
            self.assertNotIn(flag, captions)
        self.assertTrue(any('教材第 10—11 页' in item.label for item in at.expander))

    def test_quiz_has_chinese_empty_selection_prompt(self):
        at = self.app()
        at.switch_page('pages/quiz.py').run()
        self.assertEqual(at.multiselect[0].proto.placeholder, '请选择题型')


if __name__ == '__main__':
    unittest.main()

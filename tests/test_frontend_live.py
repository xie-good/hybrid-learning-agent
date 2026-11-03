"""五个页面与真实 ASGI HTTP、语料库、BM25 及 SQLite 的集成测试。

前端不导入任何后端代码。仅由此测试组装生产 FastAPI 应用，
并在前端边界注入对应的 HTTP 客户端。
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend.main import create_app
from frontend.api_client import APIClient, APIError
from tests.corpus_fixture import make_corpus

ROOT = Path(__file__).resolve().parents[1]


class FrontendLiveContractTests(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(TemporaryDirectory())
        settings = make_corpus(Path(temp))
        self.http = self.enterContext(TestClient(create_app(settings)))
        self.api = self.enterContext(APIClient('http://testserver', client=self.http))
        self.enterContext(patch('frontend.components.ui.get_api_client', return_value=self.api))

    def test_five_pages_use_real_http_contract_and_persist_history(self):
        at = AppTest.from_file(str(ROOT / 'frontend/app.py')).run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        self.assertTrue(any(item.value == '学习工作台' for item in at.title))
        at.switch_page('pages/qa.py').run(timeout=15)
        at.selectbox(key='qa_chapter').set_value('ch01').run()
        at.selectbox(key='qa_section_ch01').set_value('ch01-s001').run()
        at.text_area[0].input('How does an Agent perceive the environment?')
        next(button for button in at.button if button.label == '发送').click().run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(len(at.error), 0)
        result = at.session_state['qa_result']
        self.assertFalse(result['insufficient_evidence'])
        self.assertIn('[1]', result['answer'])
        self.assertEqual(result['generation_mode'], 'extractive')
        self.assertTrue(result['citations'])
        self.assertTrue(any('ch01 / ch01-s001' in item.value for item in at.caption))
        citation = result['citations'][0]
        self.assertEqual(self.api.source(citation['chunk_id'])['text'], citation['text'])
        self.assertEqual(self.api.chapter('ch01')['chapter_id'], 'ch01')
        self.assertEqual(self.api.history_item(result['history_id'], result['session_id'])['question'],
                         'How does an Agent perceive the environment?')
        self.assertEqual(self.http.get('/api/course/source').status_code, 200)

        at.switch_page('pages/summary.py').run(timeout=15)
        at.button(key='summary_submit').click().run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(len(at.error), 0)
        summary = at.session_state['summary_result']
        self.assertTrue(summary['coverage'])
        self.assertTrue(summary['citations'])
        self.assertEqual(summary['scope']['chapter_id'], 'ch01')

        at.switch_page('pages/quiz.py').run(timeout=15)
        at.number_input[0].set_value(2)
        at.multiselect[0].set_value(['short_answer', 'multiple_choice'])
        at.button(key='quiz_submit').click().run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(len(at.error), 0)
        quiz = at.session_state['quiz_result']
        self.assertEqual([q['type'] for q in quiz['questions']], ['short_answer', 'multiple_choice'])
        self.assertFalse(any('答案与解析' in item.label for item in at.expander))
        self.assertIsNone(at.radio[0].value)
        at.text_area[0].input('智能体通过感知、决策和行动与环境交互。')
        at.radio[0].set_value(at.radio[0].options[0]).run(timeout=15)
        at.button(key='quiz_check').click().run(timeout=15)
        self.assertEqual(len([item for item in at.expander if '答案与解析' in item.label]), 2)

        at.switch_page('pages/history.py').run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(self.api.history(result['session_id'])['total'], 1)
        self.assertEqual(self.api.history(str(uuid4()))['total'], 0)
        at.button(key=f"history_delete_{result['history_id']}").click().run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(self.api.history(result['session_id'])['total'], 0)
        self.assertTrue(any('已删除' in item.value for item in at.success))

    def test_validation_envelope_survives_the_real_http_boundary(self):
        with self.assertRaises(APIError) as raised:
            self.api.ask({'question': ' '})
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.code, 'VALIDATION_ERROR')
        self.assertTrue(raised.exception.request_id)
        self.assertTrue(raised.exception.details)
        self.assertFalse(self.http.is_closed)


if __name__ == '__main__':
    unittest.main()

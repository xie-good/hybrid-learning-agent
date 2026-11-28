"""多知识库文档上传、多轮指代补全问答与随堂巩固测试。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx

from backend.main import create_app
from pipeline.ingest_doc import _convert_pdf_to_clean_markdown, _extract_markdown_blocks, parse_uploaded_document
from tests.corpus_fixture import make_corpus


class MultiKBAndContinuityTests(unittest.TestCase):
    """验证自定义知识库上传、混合检索问答与连续追问闭环。"""

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = make_corpus(
            self.root,
            generation_mode='extractive',
            default_retrieval_mode='bm25',
            embedding_base_url='',
            embedding_model='',
        )
        self.app = create_app(self.settings)
        self.client = self.enterContext(TestClient(self.app))

    def test_custom_kb_upload_markdown_and_reject_docx(self):
        # 1. 查看预置知识库并新建自定义知识库。
        kbs = self.client.get('/api/kbs').json()['items']
        self.assertEqual(kbs[0]['kb_id'], 'hello_agents')
        created = self.client.post('/api/kbs', json={
            'name': '操作系统课程资料',
            'description': '进程调度与虚拟内存讲义',
        })
        self.assertEqual(created.status_code, 201, created.text)
        kb_id = created.json()['kb_id']

        # 2. 上传两份 Markdown 学习资料，并验证 .docx 格式会被 422 拦截。
        markdown_bytes = (
            '# 进程与线程\n'
            '进程是资源分配的基本单位，线程是调度的基本单位。上下文切换会保存寄存器和程序计数器。\n\n'
            '## 调度算法\n'
            '时间片轮转适合交互式系统，多级反馈队列兼顾响应时间与吞吐量。\n'
        ).encode('utf-8')
        upload_md = self.client.post(
            f'/api/kbs/{kb_id}/documents',
            files={'file': ('os-notes.md', markdown_bytes, 'text/markdown')},
        )
        self.assertEqual(upload_md.status_code, 201, upload_md.text)
        doc_md_id = upload_md.json()['document']['doc_id']

        markdown_bytes_2 = (
            '# 虚拟内存分页机制\n'
            '分页管理通过页表将逻辑地址转换为物理地址，缺页中断发生时操作系统从磁盘调入页面。\n'
        ).encode('utf-8')
        upload_md_2 = self.client.post(
            f'/api/kbs/{kb_id}/documents',
            files={'file': ('memory.md', markdown_bytes_2, 'text/markdown')},
        )
        self.assertEqual(upload_md_2.status_code, 201, upload_md_2.text)

        reject_docx = self.client.post(
            f'/api/kbs/{kb_id}/documents',
            files={'file': ('legacy.docx', b'fake-docx-content', 'application/octet-stream')},
        )
        self.assertEqual(reject_docx.status_code, 422)
        self.assertEqual(reject_docx.json()['error']['code'], 'unsupported_file_type')

        # 3. 验证重复文件拦截、原文件浏览与切片分页。
        duplicate_resp = self.client.post(
            f'/api/kbs/{kb_id}/documents',
            files={'file': ('dup.md', markdown_bytes, 'text/markdown')},
        )
        self.assertEqual(duplicate_resp.status_code, 409)

        source_resp = self.client.get(f'/api/kbs/{kb_id}/documents/{doc_md_id}/source')
        self.assertEqual(source_resp.status_code, 200)
        self.assertIn('上下文切换', source_resp.text)

        chunks_resp = self.client.get(f'/api/kbs/{kb_id}/chunks').json()
        self.assertGreaterEqual(chunks_resp['total'], 2)

        # 4. 在自定义知识库上执行问答，并基于检索切片生成随堂巩固题。
        session_id = str(uuid4())
        qa_resp = self.client.post('/api/qa', json={
            'kb_id': kb_id,
            'question': '多级反馈队列和吞吐量',
            'session_id': session_id,
        })
        self.assertEqual(qa_resp.status_code, 200, qa_resp.text)
        qa_body = qa_resp.json()
        self.assertEqual(qa_body['kb_id'], kb_id)
        self.assertFalse(qa_body['insufficient_evidence'])
        self.assertTrue(qa_body['citations'])

        cited_chunk_ids = []
        for citation_item in qa_body['citations']:
            cited_chunk_ids.append(citation_item['chunk_id'])

        quiz_resp = self.client.post('/api/quiz/from-qa', json={
            'kb_id': kb_id,
            'chunk_ids': cited_chunk_ids,
            'count': 1,
            'question_types': ['short_answer'],
        })
        self.assertEqual(quiz_resp.status_code, 200, quiz_resp.text)
        self.assertEqual(len(quiz_resp.json()['questions']), 1)

        # 5. 内置知识库不可删除；自定义文档与知识库可正常移除。
        self.assertEqual(self.client.delete('/api/kbs/hello_agents').status_code, 403)
        delete_doc_resp = self.client.delete(f'/api/kbs/{kb_id}/documents/{doc_md_id}')
        self.assertEqual(delete_doc_resp.status_code, 200)
        self.assertEqual(delete_doc_resp.json()['kb']['document_count'], 1)
        self.assertEqual(self.client.delete(f'/api/kbs/{kb_id}').status_code, 204)

    def test_multi_turn_query_rewrite_and_structured_llm_answer(self):
        seen_payloads = []

        def mock_handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            user_payload = json.loads(body['messages'][1]['content'])
            seen_payloads.append(user_payload)
            if user_payload['task'] == 'rewrite':
                return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
                    'role': 'assistant',
                    'content': json.dumps({'rewritten_question': 'get_weather'}, ensure_ascii=False),
                }}]})
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
                'role': 'assistant',
                'content': json.dumps({
                    'answer': '### 核心结论\n智能体通过工具与环境交互 [1]。\n\n### 详细解析\n本轮结合上下文进行深入说明 [1]。',
                    'insufficient_evidence': False,
                    'follow_up_questions': ['工具返回异常时如何重试？'],
                }, ensure_ascii=False),
            }}]})

        llm_settings = make_corpus(
            self.root / 'llm_case',
            generation_mode='llm',
            default_retrieval_mode='bm25',
            llm_base_url='https://fixture.invalid/v1',
            llm_model='fixture-chat',
            embedding_base_url='',
            embedding_model='',
        )
        llm_app = create_app(llm_settings)
        with TestClient(llm_app) as client:
            llm_app.state.generation.client = httpx.Client(transport=httpx.MockTransport(mock_handler))
            session_id = str(uuid4())

            turn1 = client.post('/api/qa', json={'question': 'get_weather', 'session_id': session_id})
            self.assertEqual(turn1.status_code, 200, turn1.text)
            self.assertEqual(turn1.json()['follow_up_questions'], ['工具返回异常时如何重试？'])
            self.assertIsNone(turn1.json()['rewritten_question'])

            # 第二轮用指代词追问，验证多轮改写与上下文传入。
            turn2 = client.post('/api/qa', json={'question': '它的局限性是什么？', 'session_id': session_id})
            self.assertEqual(turn2.status_code, 200, turn2.text)
            self.assertEqual(turn2.json()['rewritten_question'], 'get_weather')

            answer_payloads = []
            for payload_item in seen_payloads:
                if payload_item['task'] == 'answer':
                    answer_payloads.append(payload_item)
            self.assertIn('conversation_history', answer_payloads[-1])

    def test_incremental_vector_index_and_rollback(self):
        """验证自定义知识库上传/删除文档时增量复用向量，且上游失败时原库不受损。"""
        vec_settings = make_corpus(
            self.root / 'incremental_vec',
            generation_mode='extractive',
            default_retrieval_mode='bm25',
            embedding_base_url='https://fixture.invalid/v1',
            embedding_model='fixture-embed',
        )
        vec_app = create_app(vec_settings)
        embed_calls: list[list[str]] = []
        fail_next = {'flag': False}

        def fake_fetch_embeddings(_settings, texts):
            embed_calls.append(list(texts))
            if fail_next['flag']:
                from backend.errors import AppError
                raise AppError(502, 'embedding_upstream_error', '模拟向量服务异常')
            vectors = []
            for text in texts:
                if '分页' in text or '虚拟内存' in text:
                    vectors.append([0.0, 1.0, 0.0, 0.0])
                else:
                    vectors.append([1.0, 0.0, 0.0, 0.0])
            return vectors

        with patch('backend.services.knowledge_base.fetch_embeddings', side_effect=fake_fetch_embeddings), \
             TestClient(vec_app) as client:
            created = client.post('/api/kbs', json={'name': '增量索引测试库'})
            self.assertEqual(created.status_code, 201, created.text)
            kb_id = created.json()['kb_id']

            # 1. 上传第一份文档：仅对文档 1 的切片计算向量。
            doc1_bytes = '# 进程管理\n进程控制块保存进程状态、寄存器和打开文件描述符。\n'.encode('utf-8')
            up1 = client.post(
                f'/api/kbs/{kb_id}/documents',
                files={'file': ('doc1.md', doc1_bytes, 'text/markdown')},
            )
            self.assertEqual(up1.status_code, 201, up1.text)
            doc1_id = up1.json()['document']['doc_id']
            self.assertEqual(len(embed_calls), 1)
            self.assertEqual(len(embed_calls[0]), 1)
            self.assertIn('进程控制块', embed_calls[0][0])

            # 2. 上传第二份文档：复用文档 1 向量，只对文档 2 的新切片调 Embedding。
            doc2_bytes = '# 虚拟内存\n分页机制通过页表完成逻辑地址到物理地址的映射。\n'.encode('utf-8')
            up2 = client.post(
                f'/api/kbs/{kb_id}/documents',
                files={'file': ('doc2.md', doc2_bytes, 'text/markdown')},
            )
            self.assertEqual(up2.status_code, 201, up2.text)
            self.assertEqual(len(embed_calls), 2)
            self.assertEqual(len(embed_calls[1]), 1)
            self.assertIn('分页机制', embed_calls[1][0])

            # 3. 上传第三份文档时模拟 Embedding 失败：应返回 502 且原库保持 2 份文档不受破坏。
            fail_next['flag'] = True
            doc3_bytes = '# 死锁\n互斥、占有并等待、不可剥夺和循环等待是死锁的四个必要条件。\n'.encode('utf-8')
            up3 = client.post(
                f'/api/kbs/{kb_id}/documents',
                files={'file': ('doc3.md', doc3_bytes, 'text/markdown')},
            )
            self.assertEqual(up3.status_code, 502)
            fail_next['flag'] = False
            docs_after_fail = client.get(f'/api/kbs/{kb_id}/documents').json()['items']
            self.assertEqual(len(docs_after_fail), 2)

            # 4. 删除第一份文档：剩余文档向量 100% 复用，0 次调用 Embedding。
            calls_before_delete = len(embed_calls)
            del_resp = client.delete(f'/api/kbs/{kb_id}/documents/{doc1_id}')
            self.assertEqual(del_resp.status_code, 200, del_resp.text)
            self.assertEqual(len(embed_calls), calls_before_delete)

            # 5. 验证删除后章节重排为 ch01，且剩余文档仍可正常检索。
            chapters = client.get('/api/chapters', params={'kb_id': kb_id}).json()['chapters']
            self.assertEqual(len(chapters), 1)
            self.assertEqual(chapters[0]['chapter_id'], 'ch01')
            self.assertEqual(chapters[0]['sections'][0]['section_id'], 'ch01-s001')

            qa_resp = client.post('/api/qa', json={
                'kb_id': kb_id,
                'question': '分页机制如何映射地址',
                'session_id': str(uuid4()),
            })
            self.assertEqual(qa_resp.status_code, 200, qa_resp.text)
            self.assertFalse(qa_resp.json()['insufficient_evidence'])
            self.assertIn('页表', qa_resp.json()['citations'][0]['text'])

    def test_pdf_to_markdown_cleaning_skips_toc_and_exercises(self):
        """验证 PDF 转 Markdown 精洗能跳过封面目录、剔除跨页习题并保留真实物理页码。"""
        pages = [
            {'page': 1, 'text': '封面标题\n作者：测试团队'},
            {'page': 2, 'text': '目录\n第1章 智能体基础 ...... 3\n1.1 核心定义 ...... 3\n1.2 工具调用 ...... 4'},
            {
                'page': 3,
                'text': (
                    '第1章 智能体基础\n'
                    '1.1 核心定义\n'
                    '智能体通过感知环境并采取行动实现目标。\n'
                    '课后习题\n'
                    '1. 请简述智能体的四个组成要素？'
                ),
            },
            {
                'page': 4,
                'text': (
                    '2. 尝试用 Python 实现一个简单循环。\n'
                    '1.2 工具调用\n'
                    '工具调用允许模型访问外部检索器和计算器。'
                ),
            },
        ]
        cleaned_md = _convert_pdf_to_clean_markdown(pages, outline_chapters=[])
        self.assertNotIn('封面标题', cleaned_md)
        self.assertNotIn('目录', cleaned_md)
        self.assertNotIn('课后习题', cleaned_md)
        self.assertNotIn('简单循环', cleaned_md)
        self.assertIn('<!-- page:3 -->', cleaned_md)
        self.assertIn('<!-- page:4 -->', cleaned_md)
        self.assertIn('# 第1章 智能体基础', cleaned_md)
        self.assertIn('## 1.2 工具调用', cleaned_md)

        blocks = _extract_markdown_blocks(cleaned_md, has_page_anchors=True)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0][0], '1.1 核心定义')
        self.assertEqual(blocks[0][2], 3)
        self.assertEqual(blocks[1][0], '1.2 工具调用')
        self.assertEqual(blocks[1][2], 4)

        with patch('pipeline.ingest_doc._extract_pdf_pages', return_value=(pages, [])):
            chapter, chunks = parse_uploaded_document(
                doc_id='doc_pdf1',
                filename='agent-book.pdf',
                raw=b'%PDF-1.4 mock',
                chapter_id='ch01',
                kb_id='kb_test',
            )
        self.assertEqual(chapter['page_start'], 3)
        self.assertEqual(chapter['page_end'], 4)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]['page_start'], 3)
        self.assertTrue(chunks[0]['source_url'].endswith('#page=3'))
        self.assertEqual(chunks[1]['page_start'], 4)
        self.assertTrue(chunks[1]['source_url'].endswith('#page=4'))


if __name__ == '__main__':
    unittest.main()

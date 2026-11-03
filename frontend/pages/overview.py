"""把已有能力组织成清晰的学习闭环，而不是展示功能清单。"""
import streamlit as st

from frontend.api_client import APIError
from frontend.components.ui import course_context, session_uuid, show_api_error


st.title('学习工作台')
st.write('按照“了解知识—提出问题—完成练习—回顾记录”的顺序学习，每一步都可以核对教材原文。')

client, health, chapters = course_context()
history_total = None
if client and health.get('knowledge_base_ready'):
    try:
        history_total = int(client.history(session_uuid(), limit=1, offset=0).get('total', 0))
    except APIError as error:
        show_api_error(error)

chapter_count = len(chapters)
chunk_count = int(health.get('chunk_count', 0) or 0)
column_chapters, column_chunks, column_history = st.columns(3)
column_chapters.metric('课程章节', chapter_count)
column_chunks.metric('知识文本块', chunk_count)
column_history.metric('本次会话提问', history_total if history_total is not None else '暂不可用')
retrieval_names = {'bm25': '关键词检索', 'vector': '向量检索', 'hybrid': '混合检索'}
generation_names = {'extractive': '教材原文摘录', 'llm': '大模型依据教材生成'}
if health.get('knowledge_base_ready'):
    current_retrieval = retrieval_names.get(health.get('default_retrieval_mode'), '关键词检索')
    current_generation = generation_names.get(health.get('generation_mode'), '教材原文摘录')
    st.caption(f'当前能力：{current_retrieval} + {current_generation}。页面不会把摘录模式包装成大模型回答。')
elif health:
    st.caption('当前能力：知识库尚未就绪。')
else:
    st.caption('当前能力：暂未确认，请先检查后端连接。')

st.subheader('推荐学习闭环')
steps = [
    ('1. 先了解', '阅读章节总结，快速建立知识框架。', 'pages/summary.py', '打开章节总结'),
    ('2. 再提问', '针对不理解的概念检索教材并核对引用。', 'pages/qa.py', '进入智能问答'),
    ('3. 后练习', '完成自测后统一提交，再查看得分与解析。', 'pages/quiz.py', '开始练习自测'),
    ('4. 再回顾', '回看本次会话的问题、回答和教材来源。', 'pages/history.py', '查看会话历史'),
]
for column, (title, description, page, label) in zip(st.columns(4), steps):
    with column:
        st.markdown(f'**{title}**')
        st.caption(description)
        st.page_link(page, label=label, use_container_width=True)

if client and chapters:
    st.subheader('课程目录')
    chapter_by_id = {chapter['chapter_id']: chapter for chapter in chapters}
    selected_chapter = st.selectbox(
        '当前学习章节', list(chapter_by_id),
        format_func=lambda value: chapter_by_id[value].get('title', value),
        key='overview_chapter',
    )
    selected = chapter_by_id[selected_chapter]
    st.caption(f"本章包含 {len(selected.get('sections', []))} 个小节、"
               f"{selected.get('chunk_count', 0)} 个知识文本块。")
    action_summary, action_question, action_quiz = st.columns(3)
    if action_summary.button('学习本章总结', use_container_width=True):
        st.session_state['summary_chapter'] = selected_chapter
        st.switch_page('pages/summary.py')
    if action_question.button('针对本章提问', use_container_width=True):
        st.session_state['qa_chapter'] = selected_chapter
        st.switch_page('pages/qa.py')
    if action_quiz.button('开始本章练习', use_container_width=True):
        st.session_state['quiz_chapter'] = selected_chapter
        st.switch_page('pages/quiz.py')

    for left, right in zip(st.columns(2), (chapters[::2], chapters[1::2])):
        with left:
            for chapter in right:
                st.markdown(f"**{chapter.get('title', chapter.get('chapter_id', '未命名章节'))}**")
                st.caption(f"{len(chapter.get('sections', []))} 个小节 · "
                           f"{chapter.get('chunk_count', 0)} 个知识文本块")
else:
    st.warning('知识库就绪后即可开始学习；请先根据上方提示检查后端和课程数据。')

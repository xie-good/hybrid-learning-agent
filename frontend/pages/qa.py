"""支持章节筛选与原文引用的问答页面。"""
import streamlit as st

from frontend.api_client import APIError
from frontend.components.ui import (RETRIEVAL_LABELS, course_context, learning_text,
                                    render_learning_next_steps, render_metadata, render_sources,
                                    scope_selector, session_uuid, show_api_error)

st.title('智能问答')
client, health, chapters = course_context()
ready = bool(client and health.get('knowledge_base_ready') and chapters)
chapter_id, section_id = scope_selector(chapters, 'qa', allow_all=True)
available_modes = health.get('retrieval_modes') or ['bm25']
if isinstance(available_modes, dict):
    available_modes = [name for name, available in available_modes.items() if available]
available_modes = [mode for mode in available_modes if mode in {'bm25', 'vector', 'hybrid'}] or ['bm25']
with st.expander('检索设置'):
    default_mode = health.get('default_retrieval_mode', 'bm25')
    default_index = available_modes.index(default_mode) if default_mode in available_modes else 0
    retrieval_mode = st.selectbox('检索方式', available_modes, index=default_index,
        format_func=lambda mode: RETRIEVAL_LABELS[mode], key='qa_retrieval_mode', disabled=not ready)
    top_k = st.slider('返回证据数', min_value=1, max_value=10, value=5, key='qa_top_k', disabled=not ready)
    if retrieval_mode != 'bm25':
        st.warning('当前向量/混合检索属于实验能力，课程外问题拒答尚未完成正式校准，请逐条核对教材引用。')
with st.form('qa_form'):
    question = st.text_area('你的问题', placeholder='例如：智能体的核心构成是什么？', max_chars=2000, disabled=not ready)
    submitted = st.form_submit_button('发送', disabled=not ready)
if submitted and client:
    if not question.strip():
        st.warning('请输入问题后再发送。')
    else:
        st.session_state.pop('qa_result', None)
        try:
            with st.spinner('正在检索教材并组织回答…'):
                result = client.ask({
                    'question': question.strip(), 'chapter_id': chapter_id, 'section_id': section_id,
                    'session_id': session_uuid(), 'retrieval_mode': retrieval_mode, 'top_k': top_k,
                })
            st.session_state['qa_result'] = result
            st.session_state['qa_result_question'] = question.strip()
        except APIError as error:
            show_api_error(error)
result = st.session_state.get('qa_result')
if result and client:
    st.subheader('回答')
    st.caption(f"问题：{st.session_state.get('qa_result_question', '')}")
    if result.get('insufficient_evidence'):
        st.warning('本次检索证据不足；请补充教材相关关键词或调整章节范围。')
    st.markdown(learning_text(result.get('answer', '')))
    render_metadata(result)
    render_sources(result.get('citations', []), client)
    render_learning_next_steps('qa')

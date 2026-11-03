"""生成指定范围内、关联原文证据的课程总结。"""
import streamlit as st

from frontend.api_client import APIError
from frontend.components.ui import (course_context, learning_text, render_coverage,
                                    render_learning_next_steps, render_metadata, render_sources,
                                    scope_selector, show_api_error)

st.title('章节总结')
client, health, chapters = course_context()
ready = bool(client and health.get('knowledge_base_ready') and chapters)
chapter_id, section_id = scope_selector(chapters, 'summary', allow_all=False)
if st.button('生成总结', disabled=not ready, key='summary_submit') and client:
    st.session_state.pop('summary_result', None)
    try:
        with st.spinner('正在整理所选章节的教材证据…'):
            st.session_state['summary_result'] = client.summarize({'chapter_id': chapter_id, 'section_id': section_id})
    except APIError as error:
        show_api_error(error)
result = st.session_state.get('summary_result')
if result and client:
    st.subheader('总结结果')
    st.markdown(learning_text(result.get('summary', '')))
    if result.get('key_points'):
        st.subheader('关键要点')
        for point in result['key_points']:
            st.markdown(f'- {point}')
    coverage = result.get('coverage')
    if coverage:
        with st.expander('证据覆盖情况', expanded=True):
            st.caption('以下覆盖统计描述所选材料的代表性证据，不表示完整覆盖章节的全部知识点。')
            render_coverage(coverage)
    render_metadata(result)
    render_sources(result.get('citations', []), client)
    render_learning_next_steps('summary')

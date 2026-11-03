"""读取并删除当前浏览器会话中持久化保存的问答历史。"""
import streamlit as st

from frontend.api_client import APIError
from frontend.components.ui import (get_api_client, learning_text, render_metadata,
                                    render_learning_next_steps, render_sources, session_uuid, show_api_error)

st.title('会话历史')
session_id = session_uuid()
st.caption('此页仅查询当前会话的问答记录；章节总结和练习不进入问答历史。')
notice = st.session_state.pop('history_notice', None)
if notice:
    st.success(notice)
if st.session_state.pop('history_reset', False):
    st.session_state['history_page'] = 1
    st.session_state['history_clear_confirm'] = False
st.session_state.setdefault('history_page', 1)
try:
    client = get_api_client()
    confirmed = st.checkbox('确认清空当前会话全部问答', key='history_clear_confirm')
    if st.button('清空当前会话', disabled=not confirmed, key='history_clear'):
        response = client.clear_history(session_id)
        st.session_state['history_notice'] = f"已清空 {response.get('deleted', 0)} 条问答记录。"
        st.session_state['history_reset'] = True
        st.session_state.pop('qa_result', None)
        st.rerun()
    # 默认值仅来自会话状态。若同时传入 value=1，
    # 重新运行或重置后可能触发 Streamlit 的默认值冲突警告。
    page = st.number_input('页码', min_value=1, value=None, step=1, key='history_page')
    limit = 10
    payload = client.history(session_id, limit=limit, offset=(int(page or 1) - 1) * limit)
    st.caption(f"共 {payload.get('total', 0)} 条记录，每页 {limit} 条。")
    items = payload.get('items', [])
    if not items:
        st.info('本页暂无问答记录；在智能问答页提交问题后可在这里查看。')
    for item in items:
        record_id = str(item['id'])
        with st.expander(f"{item.get('created_at', '')} · {item.get('question', '问答记录')}"):
            st.markdown(learning_text(item.get('answer', '')))
            render_metadata(item)
            render_sources(item.get('citations', []), client)
            if st.button('删除这条记录', key=f'history_delete_{record_id}'):
                client.delete_history_item(record_id, session_id)
                st.session_state['history_notice'] = '该问答记录已删除。'
                st.rerun()
    render_learning_next_steps('history')
except APIError as error:
    show_api_error(error)

"""Streamlit入口：只提供页面导航，不实现最终UI或后端业务联调。"""
import streamlit as st

st.set_page_config(page_title='课程学习助手', layout='wide')
st.sidebar.title('课程学习助手')
st.sidebar.caption('预置课程：智能体系统设计与实现')
st.sidebar.info('项目骨架：教材尚未入库，业务功能尚未接入。')

# 明确列出页面，不将公共组件或临时文件自动当作页面。
page = st.navigation([
    st.Page('pages/qa.py', title='智能问答', default=True),
    st.Page('pages/summary.py', title='章节总结'),
    st.Page('pages/quiz.py', title='练习自测'),
    st.Page('pages/history.py', title='会话历史'),
])
page.run()

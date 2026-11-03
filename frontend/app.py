"""Streamlit 入口，与 FastAPI 服务分别启动。"""
from pathlib import Path
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frontend.components.ui import session_uuid

# 学习页面不展示框架的英文部署入口和开发菜单。
st.set_option('client.toolbarMode', 'minimal')
st.set_page_config(page_title='课程学习助手', layout='wide',
                   menu_items={'Get Help': None, 'Report a bug': None, 'About': None})
st.sidebar.title('课程学习助手')
st.sidebar.caption('预置课程：智能体系统设计与实现')
st.sidebar.caption(f'当前会话：{session_uuid()[:8]}')
st.sidebar.info('问答、总结和练习均通过后端服务获取结果。引用页码按教材文件的实际页码显示。')
st.sidebar.caption('历史按当前浏览器会话隔离；刷新或重新连接可能开启新会话。')

# 明确列出页面，不将公共组件或临时文件自动当作页面。
page = st.navigation([
    st.Page('pages/overview.py', title='学习工作台', default=True),
    st.Page('pages/qa.py', title='智能问答'),
    st.Page('pages/summary.py', title='章节总结'),
    st.Page('pages/quiz.py', title='练习自测'),
    st.Page('pages/history.py', title='会话历史'),
])
page.run()

"""问答页面占位：将来提交问题并展示答案、引用和教材物理页码。"""
import streamlit as st

st.title('智能问答')
st.caption('数据来源：Hello-Agents V1.0.3；当前尚未解析或建立索引。')
st.info('这里将放置章节范围、问题输入、回答和原文引用。')
# 未接入后端前禁用提交，不制造已经具备问答功能的假象。
st.text_area('你的问题', placeholder='检索服务完成后开放输入', disabled=True)
st.button('发送', disabled=True)

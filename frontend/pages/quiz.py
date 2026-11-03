"""依据原文生成阅读自测，并在提交后锁定作答、展示反馈。"""
import streamlit as st

from frontend.api_client import APIError
from frontend.components.ui import (course_context, render_learning_next_steps, render_metadata,
                                    render_sources, scope_selector, show_api_error)

st.title('练习自测')
client, health, chapters = course_context()
ready = bool(client and health.get('knowledge_base_ready') and chapters)
chapter_id, section_id = scope_selector(chapters, 'quiz', allow_all=False)
count = st.number_input('题量', min_value=1, max_value=10, value=5, step=1, disabled=not ready)
question_types = st.multiselect('题型', ['short_answer', 'multiple_choice'], default=['short_answer'],
    format_func=lambda value: {'short_answer': '简答题', 'multiple_choice': '单选题'}[value],
    placeholder='请选择题型', disabled=not ready)
difficulty = st.selectbox('难度', ['easy', 'medium', 'hard'], index=1,
    format_func=lambda value: {'easy': '基础', 'medium': '中等', 'hard': '进阶'}[value], disabled=not ready)
st.caption('难度为生成要求；本地抽取式练习用于教材阅读自测，不代表经评测的难度等级。')
if st.button('生成练习', disabled=not ready, key='quiz_submit') and client:
    if not question_types:
        st.warning('请至少选择一种题型。')
    elif int(count) < len(question_types):
        st.warning('题量应不少于所选题型数量。')
    else:
        st.session_state.pop('quiz_result', None)
        try:
            with st.spinner('正在生成教材阅读练习…'):
                st.session_state['quiz_result'] = client.quiz({
                    'chapter_id': chapter_id, 'section_id': section_id, 'count': int(count),
                    'question_types': question_types, 'difficulty': difficulty,
                })
                st.session_state['quiz_generation'] = st.session_state.get('quiz_generation', 0) + 1
                st.session_state.pop('quiz_checked_generation', None)
                st.session_state.pop('quiz_submitted_answers', None)
        except APIError as error:
            show_api_error(error)
result = st.session_state.get('quiz_result')
if result and client:
    render_metadata(result)
    generation = st.session_state.get('quiz_generation', 0)
    checked = st.session_state.get('quiz_checked_generation') == generation
    answers = []
    for number, question in enumerate(result.get('questions', []), 1):
        st.subheader(f"第 {number} 题 · {'单选' if question.get('type') == 'multiple_choice' else '简答'}")
        st.write(question.get('question', ''))
        question_id = f"{generation}_{question.get('question_id', str(number))}"
        if question.get('type') == 'multiple_choice':
            options = question.get('options', [])
            selected = st.radio('你的选择', [f"{item['key']}. {item['text']}" for item in options],
                                index=None, key=f"quiz_choice_{question_id}", disabled=checked)
            answers.append(selected.split('.', 1)[0] if selected else '')
        else:
            answers.append(st.text_area('你的作答', key=f"quiz_answer_{question_id}",
                                        disabled=checked).strip())

    if not checked:
        st.caption('完成全部题目并提交后，系统才会显示参考答案、解析和教材原文。')
        if st.button('提交本次作答', key='quiz_check', type='primary'):
            if not answers or any(not answer for answer in answers):
                st.warning('请完成全部题目后再提交，参考答案仍保持隐藏。')
            else:
                st.session_state['quiz_submitted_answers'] = list(answers)
                st.session_state['quiz_checked_generation'] = generation
                st.rerun()

    if checked:
        questions = result.get('questions', [])
        submitted_answers = st.session_state.get('quiz_submitted_answers', [])
        if len(submitted_answers) != len(questions):
            submitted_answers = list(answers)
        objective = [(question, answer) for question, answer in zip(questions, submitted_answers)
                     if question.get('type') == 'multiple_choice']
        objective_correct = sum(answer == question.get('answer') for question, answer in objective)
        short_count = sum(question.get('type') == 'short_answer' for question in questions)
        completed_metric, correct_metric, review_metric, revisit_metric = st.columns(4)
        completed_metric.metric('已完成题目', f'{len(submitted_answers)} / {len(questions)}')
        correct_metric.metric('单选题答对', f'{objective_correct} / {len(objective)}')
        reviews = []
        retry_indexes = []
        for index, (question, answer) in enumerate(zip(questions, submitted_answers)):
            if question.get('type') == 'multiple_choice' and answer != question.get('answer'):
                retry_indexes.append(index)
            elif question.get('type') == 'short_answer':
                question_id = f"{generation}_{question.get('question_id', str(index + 1))}"
                review = st.radio(f'第 {index + 1} 题自评', ['已掌握', '待复习'], index=None,
                                  horizontal=True, key=f'quiz_review_{question_id}')
                reviews.append(review)
                if review == '待复习':
                    retry_indexes.append(index)
        review_metric.metric('简答题待自评', sum(review is None for review in reviews))
        revisit_metric.metric('已标记待复习', len(retry_indexes))
        if objective:
            message = f'单选题答对 {objective_correct} / {len(objective)}。'
            (st.success if objective_correct == len(objective) else st.error)(message)
        if short_count:
            st.info(f'简答题已完成 {short_count} / {short_count}；系统不做语义自动判分，请对照参考答案自评。')

        for number, (question, answer) in enumerate(zip(questions, submitted_answers), 1):
            if question.get('type') == 'multiple_choice':
                if answer == question.get('answer'):
                    st.success(f'第 {number} 题回答正确。')
                else:
                    st.error(f'第 {number} 题回答错误，请结合解析和教材原文复习。')
            else:
                st.info(f'第 {number} 题为简答题，请根据参考答案核对核心含义。')
            with st.expander(f'查看第 {number} 题答案与解析', expanded=False):
                st.write(f"参考答案：{question.get('answer', '')}")
                st.write(f"解析：{question.get('explanation', '')}")
                st.caption('教材依据：' + ' '.join(
                    f'[{citation_id}]' for citation_id in question.get('citation_ids', [])))
        retry_all, retry_marked = st.columns(2)
        if retry_all.button('重新作答本组题', use_container_width=True,
                            key=f'quiz_retry_all_{generation}'):
            st.session_state['quiz_generation'] = generation + 1
            st.session_state.pop('quiz_checked_generation', None)
            st.session_state.pop('quiz_submitted_answers', None)
            st.rerun()
        if retry_marked.button('重做待复习题', use_container_width=True,
                               disabled=not retry_indexes, key=f'quiz_retry_marked_{generation}'):
            new_result = dict(result)
            new_result['questions'] = [questions[index] for index in retry_indexes]
            st.session_state['quiz_result'] = new_result
            st.session_state['quiz_generation'] = generation + 1
            st.session_state.pop('quiz_checked_generation', None)
            st.session_state.pop('quiz_submitted_answers', None)
            st.rerun()
        render_sources(result.get('citations', []), client)
        render_learning_next_steps('quiz')

<script setup>
// 问答页内嵌的随堂巩固练习卡片：直接围绕本轮检索命中的资料切片出题并立即核对答案。
import { computed, ref } from "vue";
import AppIcon from "./AppIcon.vue";
import { gradeChoices } from "../lib/api.js";
import { useWorkspace } from "../composables/useWorkspace.js";

const props = defineProps({
  quiz: { type: Object, required: true },
});

const { errorMessage } = useWorkspace();

const userAnswers = ref({});
const isSubmitted = ref(false);

const choiceScore = computed(() => {
  const questionList = props.quiz?.questions || [];
  return gradeChoices(questionList, userAnswers.value);
});

function submitInlineQuiz() {
  const questionList = props.quiz?.questions || [];
  for (const questionItem of questionList) {
    const answerText = userAnswers.value[questionItem.question_id] || "";
    if (!answerText.trim()) {
      errorMessage.value = "请完成全部随堂练习后再提交。";
      return;
    }
  }
  isSubmitted.value = true;
  errorMessage.value = "";
}
</script>

<template>
  <div class="inline-quiz-box">
    <div class="panel-title"><AppIcon name="quiz" /> 随堂巩固练习</div>
    <div v-if="isSubmitted" class="message success">
      单选题答对 {{ choiceScore.correct }} / {{ choiceScore.total }}，请核对下方答案与依据解析。
    </div>
    <div
      v-for="(questionItem, questionIndex) in quiz.questions"
      :key="questionItem.question_id"
      class="inline-quiz-item"
    >
      <p class="inline-q-title">
        <strong>{{ questionIndex + 1 }}.</strong> {{ questionItem.question }}
      </p>
      <div v-if="questionItem.type === 'multiple_choice'" class="quiz-options">
        <label
          v-for="optionItem in questionItem.options"
          :key="optionItem.key"
          :class="{ chosen: userAnswers[questionItem.question_id] === optionItem.key }"
        >
          <input
            v-model="userAnswers[questionItem.question_id]"
            type="radio"
            :name="`inline-${questionItem.question_id}`"
            :value="optionItem.key"
            :disabled="isSubmitted"
          />
          <span>{{ optionItem.key }}.</span> {{ optionItem.text }}
        </label>
      </div>
      <textarea
        v-else
        v-model="userAnswers[questionItem.question_id]"
        rows="2"
        placeholder="写下你的理解…"
        :disabled="isSubmitted"
      ></textarea>
      <div v-if="isSubmitted" class="answer-feedback">
        <p><strong>参考答案：</strong>{{ questionItem.answer }}</p>
        <p><strong>依据解析：</strong>{{ questionItem.explanation }}</p>
      </div>
    </div>
    <button v-if="!isSubmitted" type="button" class="button primary" @click="submitInlineQuiz">
      提交核对答案
    </button>
  </div>
</template>

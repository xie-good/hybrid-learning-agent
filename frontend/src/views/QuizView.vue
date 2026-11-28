<script setup>
// 本页面独立负责练习配置、生成、作答与反馈；课程范围和请求提示来自共享工作区。
// App.vue 只装配页面，切换页面后的本轮作答由上层 KeepAlive 保留。
import { computed, ref, watch } from "vue";
import AppIcon from "../components/AppIcon.vue";
import LearningLayout from "../components/layout/LearningLayout.vue";
import SourceList from "../components/SourceList.vue";
import { useWorkspace } from "../composables/useWorkspace.js";
import { gradeChoices, request } from "../lib/api.js";
import { modeLabel } from "../lib/presentation.js";

const {
  serviceHealth,
  isLearningReady,
  activeTask,
  errorMessage,
  selectedKbId,
  selectedChapterId,
  selectedSectionId,
  buildLearningScope,
  runTask,
} = useWorkspace();
const quizResult = ref(null);
const questionCount = ref(5);
const quizDifficulty = ref("medium");
const selectedQuestionTypes = ref(["short_answer"]);
// 答案、自评都以 question_id 为键；重新练习时统一清空，不沿用上一轮的作答。
const answersByQuestionId = ref({});
const selfReviewsByQuestionId = ref({});
const isQuizSubmitted = ref(false);
const multipleChoiceScore = computed(() =>
  gradeChoices(quizResult.value?.questions || [], answersByQuestionId.value),
);

// 范围或知识库改变时丢弃旧题组，避免选择了新章节却还展示上一章的练习。
watch([selectedKbId, selectedChapterId, selectedSectionId], () => {
  quizResult.value = null;
});

// 题型不能为空，题数也不能少于题型数，否则无法保证每种所选题型至少一题。
function generateQuiz() {
  if (
    !selectedQuestionTypes.value.length ||
    questionCount.value < selectedQuestionTypes.value.length
  ) {
    errorMessage.value = "请至少选择一种题型，且题量不少于题型数量。";
    return;
  }
  quizResult.value = null;
  const scopeParams = buildLearningScope();
  const quizRequest = {
    chapter_id: scopeParams.chapter_id,
    section_id: scopeParams.section_id,
    count: questionCount.value,
    difficulty: quizDifficulty.value,
    question_types: [...selectedQuestionTypes.value],
  };
  if (selectedKbId?.value && selectedKbId.value !== "hello_agents") {
    quizRequest.kb_id = selectedKbId.value;
  }
  runTask("quiz", async () => {
    quizResult.value = await request("/quiz", {
      method: "POST",
      body: quizRequest,
      timeout: 120000,
    });
    resetQuiz();
  });
}
// 全部题目完成后才展示答案。注意：参考答案已随接口返回，这只是教学展示控制，
// 不是考试防作弊机制；客观分数只计算单选题，简答题由学习者对照原文自评。
function submitQuiz() {
  if (
    quizResult.value.questions.some(
      (question) => !answersByQuestionId.value[question.question_id]?.trim(),
    )
  ) {
    errorMessage.value = "请完成全部题目后再提交。";
    return;
  }
  isQuizSubmitted.value = true;
  errorMessage.value = "";
}
// 普通重答保留全部题目；专项重答仅保留答错的单选题和自评“待复习”的简答题。
// 必须先按旧答案筛选，再清空作答，否则会丢失筛选依据。
function resetQuiz(reviewOnly = false) {
  if (reviewOnly)
    quizResult.value = {
      ...quizResult.value,
      questions: quizResult.value.questions.filter((question) =>
        question.type === "multiple_choice"
          ? answersByQuestionId.value[question.question_id] !== question.answer
          : selfReviewsByQuestionId.value[question.question_id] === "待复习",
      ),
    };
  answersByQuestionId.value = {};
  selfReviewsByQuestionId.value = {};
  isQuizSubmitted.value = false;
  errorMessage.value = "";
}
// 单选题在提交后才能判断对错；简答题是否待复习完全取决于用户的自评。
const reviewQuestionCount = computed(
  () =>
    (quizResult.value?.questions || []).filter((question) =>
      question.type === "multiple_choice"
        ? isQuizSubmitted.value &&
          answersByQuestionId.value[question.question_id] !== question.answer
        : selfReviewsByQuestionId.value[question.question_id] === "待复习",
    ).length,
);
</script>

<template>
  <LearningLayout page-id="quiz" :has-result="!!quizResult">
    <!-- 题型、题量与难度采用紧凑横向配置栏，节省首屏空间。 -->
    <form class="panel quiz-config-panel" @submit.prevent="generateQuiz">
      <div class="quiz-config-row">
        <label class="quiz-field"
          >题目数量<input
            v-model.number="questionCount"
            type="number"
            name="quiz-count"
            autocomplete="off"
            inputmode="numeric"
            min="1"
            max="10"
            required
            :disabled="!!activeTask" /></label
        ><label class="quiz-field"
          >难度要求<select
            v-model="quizDifficulty"
            name="quiz-difficulty"
            autocomplete="off"
            :disabled="!!activeTask"
          >
            <option value="easy">基础</option>
            <option value="medium">中等</option>
            <option value="hard">进阶</option>
          </select></label
        >
        <fieldset class="question-types-pills" :disabled="!!activeTask">
          <legend>选择题型</legend>
          <div class="type-pill-row">
            <label
              class="type-pill"
              :class="{ active: selectedQuestionTypes.includes('short_answer') }"
              ><input v-model="selectedQuestionTypes" type="checkbox" value="short_answer" />
              简答题</label
            ><label
              class="type-pill"
              :class="{ active: selectedQuestionTypes.includes('multiple_choice') }"
              ><input v-model="selectedQuestionTypes" type="checkbox" value="multiple_choice" />
              单选题</label
            >
          </div>
        </fieldset>
        <button class="button primary quiz-submit-btn" :disabled="!isLearningReady || !selectedChapterId || !!activeTask">
          <span v-if="activeTask === 'quiz'" class="spinner"></span
          ><AppIcon v-else name="spark" :size="16" />{{
            activeTask === "quiz" ? "正在生成练习…" : "生成练习"
          }}
        </button>
      </div>
      <p v-if="serviceHealth?.generation_mode === 'extractive'" class="field-note">
        当前为本地原文摘录模式，难度要求仅作标签展示。
      </p>
    </form>

    <!-- 结果与答案的可见性由本轮 isQuizSubmitted 状态控制，提交前不显示解析。 -->
    <form
      v-if="quizResult"
      class="panel result-panel"
      aria-live="polite"
      @submit.prevent="submitQuiz"
    >
      <div class="result-kicker">
        <AppIcon name="quiz" :size="17" /> 本次自测
        <span class="pill">{{ modeLabel(quizResult.generation_mode) }}</span>
      </div>
      <div v-if="isQuizSubmitted" class="message success" role="status">
        已提交 {{ quizResult.questions.length }} 题；单选答对 {{ multipleChoiceScore.correct }} /
        {{ multipleChoiceScore.total }}。简答题请对照参考答案自评。
      </div>
      <section
        v-for="(question, questionIndex) in quizResult.questions"
        :key="question.question_id"
        class="quiz-question"
      >
        <span class="tiny-label"
          >QUESTION {{ String(questionIndex + 1).padStart(2, "0") }} ·
          {{ question.type === "multiple_choice" ? "单选题" : "简答题" }}</span
        >
        <h3>{{ question.question }}</h3>
        <fieldset
          v-if="question.type === 'multiple_choice'"
          class="quiz-options"
          :disabled="isQuizSubmitted"
        >
          <legend class="sr-only">第 {{ questionIndex + 1 }} 题你的选择</legend>
          <label
            v-for="option in question.options"
            :key="option.key"
            :class="{
              chosen: answersByQuestionId[question.question_id] === option.key,
            }"
            ><input
              v-model="answersByQuestionId[question.question_id]"
              type="radio"
              :name="question.question_id"
              :value="option.key"
            /><span>{{ option.key }}.</span> {{ option.text }}</label
          >
        </fieldset>
        <textarea
          v-else
          v-model="answersByQuestionId[question.question_id]"
          :aria-label="`第${questionIndex + 1}题你的作答`"
          rows="4"
          placeholder="用自己的话描述你的理解…"
          :disabled="isQuizSubmitted"
        ></textarea>
        <!-- 提交前不渲染参考答案与解析；提交后按题型显示客观反馈或简答自评。 -->
        <div v-if="isQuizSubmitted" class="answer-feedback">
          <strong
            v-if="question.type === 'multiple_choice'"
            :class="
              answersByQuestionId[question.question_id] === question.answer
                ? 'correct'
                : 'incorrect'
            "
            >{{
              answersByQuestionId[question.question_id] === question.answer ? "回答正确" : "待复习"
            }}</strong
          >
          <p><strong>参考答案：</strong>{{ question.answer }}</p>
          <p><strong>解析：</strong>{{ question.explanation }}</p>
          <small
            >教材依据：{{
              question.citation_ids.map((citationId) => `[${citationId}]`).join(" ")
            }}</small
          ><label v-if="question.type === 'short_answer'" class="review-select"
            >你的自评<select
              v-model="selfReviewsByQuestionId[question.question_id]"
              name="quiz-review"
              autocomplete="off"
            >
              <option :value="undefined" disabled>请选择</option>
              <option>已掌握</option>
              <option>待复习</option>
            </select></label
          >
        </div>
      </section>
      <template v-if="!isQuizSubmitted"
        ><p class="field-note">
          完成全部题目并提交后，才会显示参考答案、解析与教材原文。
        </p>
        <button class="button primary">
          提交本次作答
          <AppIcon name="check" :size="17" /></button></template
      ><template v-else
        ><div class="button-group">
          <button type="button" class="button secondary" @click="resetQuiz()">
            重新作答本组题</button
          ><button
            type="button"
            class="button secondary"
            :disabled="!reviewQuestionCount"
            @click="resetQuiz(true)"
          >
            重做待复习题（{{ reviewQuestionCount }}）
          </button>
        </div>
        <SourceList :citations="quizResult.citations"
      /></template>
    </form>
  </LearningLayout>
</template>

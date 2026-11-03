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

const { ready, busy, error, chapterId, sectionId, scope, run } = useWorkspace();
const quiz = ref(null);
const count = ref(5);
const difficulty = ref("medium");
const types = ref(["short_answer"]);
// 答案、自评都以 question_id 为键；重新练习时统一清空，不沿用上一轮的作答。
const answers = ref({});
const reviews = ref({});
const submitted = ref(false);
const score = computed(() =>
  gradeChoices(quiz.value?.questions || [], answers.value),
);

// 范围改变时丢弃旧题组，避免选择了新章节却还展示上一章的练习。
watch([chapterId, sectionId], () => {
  quiz.value = null;
});

// 题型不能为空，题数也不能少于题型数，否则无法保证每种所选题型至少一题。
function generateQuiz() {
  if (!types.value.length || count.value < types.value.length) {
    error.value = "请至少选择一种题型，且题量不少于题型数量。";
    return;
  }
  quiz.value = null;
  const payload = {
    ...scope(),
    count: count.value,
    difficulty: difficulty.value,
    question_types: [...types.value],
  };
  run("quiz", async () => {
    quiz.value = await request("/quiz", { method: "POST", body: payload });
    resetQuiz();
  });
}
// 全部题目完成后才展示答案。注意：参考答案已随接口返回，这只是教学展示控制，
// 不是考试防作弊机制；客观分数只计算单选题，简答题由学习者对照原文自评。
function submitQuiz() {
  if (quiz.value.questions.some((q) => !answers.value[q.question_id]?.trim())) {
    error.value = "请完成全部题目后再提交。";
    return;
  }
  submitted.value = true;
  error.value = "";
}
// 普通重答保留全部题目；专项重答仅保留答错的单选题和自评“待复习”的简答题。
// 必须先按旧答案筛选，再清空作答，否则会丢失筛选依据。
function resetQuiz(markedOnly = false) {
  if (markedOnly)
    quiz.value = {
      ...quiz.value,
      questions: quiz.value.questions.filter((q) =>
        q.type === "multiple_choice"
          ? answers.value[q.question_id] !== q.answer
          : reviews.value[q.question_id] === "待复习",
      ),
    };
  answers.value = {};
  reviews.value = {};
  submitted.value = false;
  error.value = "";
}
// 单选题在提交后才能判断对错；简答题是否待复习完全取决于用户的自评。
const markedCount = computed(
  () =>
    (quiz.value?.questions || []).filter((q) =>
      q.type === "multiple_choice"
        ? submitted.value && answers.value[q.question_id] !== q.answer
        : reviews.value[q.question_id] === "待复习",
    ).length,
);
</script>

<template>
  <LearningLayout page-id="quiz" :has-result="!!quiz">
    <!-- 题型、题量与难度只属于本页面，不让根组件承担练习配置。 -->
    <form class="panel" @submit.prevent="generateQuiz">
      <div class="panel-title"><AppIcon name="quiz" /> 配置本次练习</div>
      <div class="form-grid">
        <label
          >题目数量<input
            v-model.number="count"
            type="number"
            min="1"
            max="10"
            required
            :disabled="!!busy" /></label
        ><label
          >难度要求<select v-model="difficulty" :disabled="!!busy">
            <option value="easy">基础</option>
            <option value="medium">中等</option>
            <option value="hard">进阶</option>
          </select></label
        >
      </div>
      <fieldset class="question-types" :disabled="!!busy">
        <legend>选择题型</legend>
        <label
          ><input v-model="types" type="checkbox" value="short_answer" />
          简答题</label
        ><label
          ><input v-model="types" type="checkbox" value="multiple_choice" />
          单选题</label
        >
      </fieldset>
      <p class="field-note">
        本地摘录模式为教材阅读自测，难度要求不代表经评测的难度等级。
      </p>
      <button class="button primary" :disabled="!ready || !chapterId || !!busy">
        <span v-if="busy === 'quiz'" class="spinner"></span
        ><AppIcon v-else name="spark" :size="17" />{{
          busy === "quiz" ? "正在生成练习…" : "生成练习"
        }}
      </button>
    </form>

    <!-- 结果与答案的可见性由本轮 submitted 状态控制，提交前不显示解析。 -->
    <form v-if="quiz" class="panel result-panel" @submit.prevent="submitQuiz">
      <div class="result-kicker">
        <AppIcon name="quiz" :size="17" /> 本次自测
        <span class="pill">{{ modeLabel(quiz.generation_mode) }}</span>
      </div>
      <div v-if="submitted" class="message success" role="status">
        已提交 {{ quiz.questions.length }} 题；单选答对 {{ score.correct }} /
        {{ score.total }}。简答题请对照参考答案自评。
      </div>
      <section
        v-for="(item, index) in quiz.questions"
        :key="item.question_id"
        class="quiz-question"
      >
        <span class="tiny-label"
          >QUESTION {{ String(index + 1).padStart(2, "0") }} ·
          {{ item.type === "multiple_choice" ? "单选题" : "简答题" }}</span
        >
        <h3>{{ item.question }}</h3>
        <fieldset
          v-if="item.type === 'multiple_choice'"
          class="quiz-options"
          :disabled="submitted"
        >
          <legend class="sr-only">第 {{ index + 1 }} 题你的选择</legend>
          <label
            v-for="option in item.options"
            :key="option.key"
            :class="{
              chosen: answers[item.question_id] === option.key,
            }"
            ><input
              v-model="answers[item.question_id]"
              type="radio"
              :name="item.question_id"
              :value="option.key"
            /><span>{{ option.key }}.</span> {{ option.text }}</label
          >
        </fieldset>
        <textarea
          v-else
          v-model="answers[item.question_id]"
          :aria-label="`第${index + 1}题你的作答`"
          rows="4"
          placeholder="用自己的话描述你的理解…"
          :disabled="submitted"
        ></textarea>
        <!-- 提交前不渲染参考答案与解析；提交后按题型显示客观反馈或简答自评。 -->
        <div v-if="submitted" class="answer-feedback">
          <strong
            v-if="item.type === 'multiple_choice'"
            :class="
              answers[item.question_id] === item.answer
                ? 'correct'
                : 'incorrect'
            "
            >{{
              answers[item.question_id] === item.answer ? "回答正确" : "待复习"
            }}</strong
          >
          <p><strong>参考答案：</strong>{{ item.answer }}</p>
          <p><strong>解析：</strong>{{ item.explanation }}</p>
          <small
            >教材依据：{{
              item.citation_ids.map((id) => `[${id}]`).join(" ")
            }}</small
          ><label v-if="item.type === 'short_answer'" class="review-select"
            >你的自评<select v-model="reviews[item.question_id]">
              <option :value="undefined" disabled>请选择</option>
              <option>已掌握</option>
              <option>待复习</option>
            </select></label
          >
        </div>
      </section>
      <template v-if="!submitted"
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
            :disabled="!markedCount"
            @click="resetQuiz(true)"
          >
            重做待复习题（{{ markedCount }}）
          </button>
        </div>
        <SourceList :citations="quiz.citations"
      /></template>
    </form>
  </LearningLayout>
</template>

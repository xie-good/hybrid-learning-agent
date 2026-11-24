<script setup>
// 问答页独立管理输入、证据数和回答；检索方式、课程范围与会话通过共享工作区读取。
import { ref, watch } from "vue";
import AppIcon from "../components/AppIcon.vue";
import SourceList from "../components/SourceList.vue";
import LearningLayout from "../components/layout/LearningLayout.vue";
import { useWorkspace } from "../composables/useWorkspace.js";
import { request } from "../lib/api.js";
import { modeLabel, retrievalLabels, displayLearningText } from "../lib/presentation.js";

const {
  serviceHealth,
  isLearningReady,
  activeTask,
  errorMessage,
  selectedChapterId,
  selectedSectionId,
  buildLearningScope,
  runTask,
  currentSessionId,
  historyOffset,
  loadHistory,
  historyClearCount,
} = useWorkspace();
const question = ref("");
// 发送后固定标题，后续编辑输入不会改变已有回答对应的问题。
const askedQuestion = ref("");
const questionAnswerResult = ref(null);
const topK = ref(5);

// KeepAlive 保留跨页面输入与结果；学习范围变化或历史清空时，不继续展示旧回答。
watch([selectedChapterId, selectedSectionId], () => {
  questionAnswerResult.value = null;
});
watch(historyClearCount, () => {
  questionAnswerResult.value = null;
});

function ask() {
  if (!question.value.trim()) {
    errorMessage.value = "请输入问题后再发送。";
    return;
  }
  const questionText = question.value.trim();
  const questionRequest = {
    ...buildLearningScope(),
    question: questionText,
    session_id: currentSessionId,
    retrieval_mode: serviceHealth.value?.default_retrieval_mode || "hybrid",
    top_k: topK.value,
  };
  questionAnswerResult.value = null;
  // 历史由后端持久化；回答返回后刷新共享快照，工作台与历史页便能及时看到新记录。
  runTask("qa", async () => {
    questionAnswerResult.value = await request("/qa", { method: "POST", body: questionRequest });
    askedQuestion.value = questionText;
    historyOffset.value = 0;
    await loadHistory();
  });
}
</script>

<template>
  <LearningLayout page-id="qa" :has-result="!!questionAnswerResult">
    <!-- v-model 把输入框与状态绑定，submit.prevent 避免表单提交刷新整个页面。 -->
    <form class="panel question-panel" @submit.prevent="ask">
      <div class="panel-title"><AppIcon name="chat" /> 你想了解什么？</div>
      <textarea
        v-model="question"
        name="question"
        autocomplete="off"
        aria-label="你的问题"
        maxlength="2000"
        rows="5"
        placeholder="例如：智能体的核心构成是什么？它与传统程序有什么不同…"
        :disabled="!!activeTask"
      ></textarea>
      <div class="question-footer">
        <span>{{ question.length }} / 2000</span
        ><button
          class="button primary"
          :disabled="!isLearningReady || !!activeTask || !question.trim()"
        >
          <span v-if="activeTask === 'qa'" class="spinner"></span
          ><AppIcon v-else name="send" :size="17" />{{
            activeTask === "qa" ? "正在检索教材…" : "发送问题"
          }}
        </button>
      </div>
      <details class="retrieval-settings">
        <summary>检索设置</summary>
        <div class="form-grid">
          <label
            >返回证据数：{{ topK
            }}<input
              v-model.number="topK"
              type="range"
              min="1"
              max="10"
              :disabled="!!activeTask"
          /></label>
        </div>
      </details>
    </form>

    <!-- 结果区只在对应请求返回后出现；引用组件复用于问答、总结和提交后的练习。 -->
    <section v-if="questionAnswerResult" class="panel result-panel" aria-live="polite">
      <div class="result-kicker">
        <AppIcon name="spark" :size="17" /> 回答
        <span class="pill">{{ modeLabel(questionAnswerResult.generation_mode) }}</span>
      </div>
      <h2>{{ askedQuestion }}</h2>
      <p v-if="questionAnswerResult.insufficient_evidence" class="message warning">
        本次教材证据不足，请补充相关关键词或调整范围。
      </p>
      <p class="prose">{{ displayLearningText(questionAnswerResult.answer) }}</p>
      <div class="result-meta">
        {{ questionAnswerResult.latency_ms }} ms · {{ retrievalLabels[questionAnswerResult.retrieval_mode] }} ·
        {{ questionAnswerResult.dataset_version }}
      </div>
      <SourceList :citations="questionAnswerResult.citations" />
    </section>
  </LearningLayout>
</template>

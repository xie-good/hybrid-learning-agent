<script setup>
// 问答页独立管理输入、检索选项和回答；课程范围与会话通过共享工作区读取。
import { ref, watch } from "vue";
import AppIcon from "../components/AppIcon.vue";
import SourceList from "../components/SourceList.vue";
import LearningLayout from "../components/layout/LearningLayout.vue";
import { useWorkspace } from "../composables/useWorkspace.js";
import { request } from "../lib/api.js";
import { modeLabel, retrievalLabels } from "../lib/presentation.js";

const {
  health,
  ready,
  busy,
  error,
  chapterId,
  sectionId,
  scope,
  run,
  session,
  historyOffset,
  loadHistory,
  historyCleared,
} = useWorkspace();
const question = ref("");
// 发送后固定标题，后续编辑输入不会改变已有回答对应的问题。
const askedQuestion = ref("");
const qa = ref(null);
const retrieval = ref(health.value?.default_retrieval_mode || "bm25");
const topK = ref(5);

// 页面可能早于后端初始化创建，因此默认检索方式需等真实能力返回后同步。
// 重新连接时即使默认名称未变，也按本次健康响应重新采用服务端默认值。
watch(health, (state) => {
  if (state?.default_retrieval_mode) retrieval.value = state.default_retrieval_mode;
});
// KeepAlive 保留跨页面输入与结果；学习范围变化或历史清空时，不继续展示旧回答。
watch([chapterId, sectionId], () => {
  qa.value = null;
});
watch(historyCleared, () => {
  qa.value = null;
});

function ask() {
  if (!question.value.trim()) {
    error.value = "请输入问题后再发送。";
    return;
  }
  const text = question.value.trim();
  const payload = {
    ...scope(),
    question: text,
    session_id: session,
    retrieval_mode: retrieval.value,
    top_k: topK.value,
  };
  qa.value = null;
  // 历史由后端持久化；回答返回后刷新共享快照，工作台与历史页便能及时看到新记录。
  run("qa", async () => {
    qa.value = await request("/qa", { method: "POST", body: payload });
    askedQuestion.value = text;
    historyOffset.value = 0;
    await loadHistory();
  });
}
</script>

<template>
  <LearningLayout page-id="qa" :has-result="!!qa">
    <!-- v-model 把输入框与状态绑定，submit.prevent 避免表单提交刷新整个页面。 -->
    <form class="panel question-panel" @submit.prevent="ask">
      <div class="panel-title"><AppIcon name="chat" /> 你想了解什么？</div>
      <textarea
        v-model="question"
        aria-label="你的问题"
        maxlength="2000"
        rows="5"
        placeholder="例如：智能体的核心构成是什么？它与传统程序有什么不同？"
        :disabled="!!busy"
      ></textarea>
      <div class="question-footer">
        <span>{{ question.length }} / 2000</span
        ><button
          class="button primary"
          :disabled="!ready || !!busy || !question.trim()"
        >
          <span v-if="busy === 'qa'" class="spinner"></span
          ><AppIcon v-else name="send" :size="17" />{{
            busy === "qa" ? "正在检索教材…" : "发送问题"
          }}
        </button>
      </div>
      <details class="retrieval-settings">
        <summary>检索设置</summary>
        <div class="form-grid">
          <label
            >检索方式<select v-model="retrieval" :disabled="!!busy">
              <option
                v-for="mode in health?.retrieval_modes || ['bm25']"
                :key="mode"
                :value="mode"
              >
                {{ retrievalLabels[mode] }}
              </option>
            </select></label
          ><label
            >返回证据数：{{ topK
            }}<input
              v-model.number="topK"
              type="range"
              min="1"
              max="10"
              :disabled="!!busy"
          /></label>
        </div>
        <p v-if="retrieval !== 'bm25'" class="field-note">
          实验检索模式，请逐条核对教材引用。
        </p>
      </details>
    </form>

    <!-- 结果区只在对应请求返回后出现；引用组件复用于问答、总结和提交后的练习。 -->
    <section v-if="qa" class="panel result-panel" aria-live="polite">
      <div class="result-kicker">
        <AppIcon name="spark" :size="17" /> 回答
        <span class="pill">{{ modeLabel(qa.generation_mode) }}</span>
      </div>
      <h2>{{ askedQuestion }}</h2>
      <p v-if="qa.insufficient_evidence" class="message warning">
        本次教材证据不足，请补充相关关键词或调整范围。
      </p>
      <p class="prose">{{ qa.answer }}</p>
      <div class="result-meta">
        {{ qa.latency_ms }} ms · {{ retrievalLabels[qa.retrieval_mode] }} ·
        {{ qa.dataset_version }}
      </div>
      <SourceList :citations="qa.citations" />
    </section>
  </LearningLayout>
</template>

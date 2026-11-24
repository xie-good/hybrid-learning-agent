<script setup>
// 总结页只维护总结请求与结果；章/节范围、请求进度和错误提示与其他页面共享。
import { ref, watch } from "vue";
import AppIcon from "../components/AppIcon.vue";
import SourceList from "../components/SourceList.vue";
import LearningLayout from "../components/layout/LearningLayout.vue";
import { useWorkspace } from "../composables/useWorkspace.js";
import { request } from "../lib/api.js";
import { modeLabel, displayLearningText } from "../lib/presentation.js";

const {
  isLearningReady,
  activeTask,
  selectedChapterId,
  selectedSectionId,
  buildLearningScope,
  runTask,
  navigate,
} = useWorkspace();
const summaryResult = ref(null);
// 即使页面暂时被 KeepAlive 缓存，范围变化也会清掉旧章节的总结。
watch([selectedChapterId, selectedSectionId], () => {
  summaryResult.value = null;
});

// 前端只发送学习范围；代表性要点、原文引用及实际生成方式都由后端返回。
function summarize() {
  summaryResult.value = null;
  const summaryRequest = buildLearningScope();
  runTask("summary", async () => {
    summaryResult.value = await request("/summary", {
      method: "POST",
      body: summaryRequest,
    });
  });
}
</script>

<template>
  <LearningLayout page-id="summary" :has-result="!!summaryResult">
    <section class="panel action-panel">
      <div>
        <h3>从全貌开始理解</h3>
        <p>提取章节重点，整理代表性教材证据。</p>
      </div>
      <button
        class="button primary"
        :disabled="!isLearningReady || !selectedChapterId || !!activeTask"
        @click="summarize"
      >
        <span v-if="activeTask === 'summary'" class="spinner"></span
        ><AppIcon v-else name="spark" :size="17" />{{
          activeTask === "summary" ? "正在整理教材…" : "生成总结"
        }}
      </button>
    </section>

    <section v-if="summaryResult" class="panel result-panel" aria-live="polite">
      <div class="result-kicker">
        <AppIcon name="summary" :size="17" /> 总结结果
        <span class="pill">{{ modeLabel(summaryResult.generation_mode) }}</span>
      </div>
      <p class="prose">{{ displayLearningText(summaryResult.summary) }}</p>
      <h3>关键要点</h3>
      <ul class="key-points">
        <li v-for="keyPoint in summaryResult.key_points" :key="keyPoint">
          {{ displayLearningText(keyPoint) }}
        </li>
      </ul>
      <!-- 覆盖数量表示代表性原文片段的覆盖，不等于整章全部知识点已经讲完。 -->
      <details v-if="summaryResult.coverage" class="coverage">
        <summary>证据覆盖情况</summary>
        <p class="field-note">代表性证据的覆盖统计，不等于全部知识点覆盖。</p>
        <dl class="coverage-stats">
          <div>
            <dt>小节覆盖</dt>
            <dd>
              {{ summaryResult.coverage.sections_covered }} /
              {{ summaryResult.coverage.sections_total }}
            </dd>
          </div>
          <div>
            <dt>代表性文本块</dt>
            <dd>
              {{ summaryResult.coverage.chunks_selected }} /
              {{ summaryResult.coverage.chunks_total }}
            </dd>
          </div>
        </dl>
      </details>
      <SourceList :citations="summaryResult.citations" /><a
        class="button secondary"
        :href="'#quiz'"
        @click.exact.prevent="navigate('quiz')"
      >
        练习巩固本章 <AppIcon name="arrow" :size="16" />
      </a>
    </section>
  </LearningLayout>
</template>

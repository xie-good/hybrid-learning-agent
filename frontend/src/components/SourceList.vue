<script setup>
// 通用教材引用组件：展示命中来源标签（双路/BM25/向量）、检索分数明细、原文内容与左侧定位按钮。
import AppIcon from "./AppIcon.vue";

defineProps({
  citations: { type: Array, default: () => [] },
  showLocate: { type: Boolean, default: false },
});

const emit = defineEmits(["locate"]);

function hitLabel(hitType) {
  if (hitType === "both") return "双路共同命中";
  if (hitType === "bm25") return "BM25 词法命中";
  if (hitType === "vector") return "向量语义命中";
  if (hitType === "overview") return "全文概览抽样";
  return "";
}

function hitBadgeClass(hitType) {
  if (hitType === "both") return "hit-badge hit-both";
  if (hitType === "bm25") return "hit-badge hit-bm25";
  if (hitType === "vector") return "hit-badge hit-vector";
  if (hitType === "overview") return "hit-badge hit-overview";
  return "hit-badge";
}

function scoreSummary(source) {
  const parts = [];
  if (source.bm25_rank != null) {
    parts.push(`BM25 第${source.bm25_rank}名`);
  }
  if (source.vec_score != null) {
    parts.push(`向量 ${Number(source.vec_score).toFixed(3)}`);
  }
  if (source.rrf_score != null) {
    parts.push(`RRF ${Number(source.rrf_score).toFixed(4)}`);
  }
  return parts.join(" · ");
}
</script>

<template>
  <!-- 原生 details/summary 提供可键盘操作的展开面板，展示每条引用的混合检索命中明细。 -->
  <section v-if="citations.length" class="sources">
    <h3>
      <AppIcon name="book" :size="18" /> 教材依据
      <span class="pill">{{ citations.length }} 条引用</span>
    </h3>
    <details
      v-for="source in citations"
      :key="source.chunk_id"
      class="source-item"
    >
      <summary>
        <span class="citation-number">{{ source.citation_id }}</span>
        <span class="source-summary-main">
          <span class="source-title-row">
            <span>{{ source.section_title || source.chapter_title }}</span>
            <small>第 {{ source.page_start }}–{{ source.page_end }} 页</small>
            <span v-if="hitLabel(source.hit_type)" :class="hitBadgeClass(source.hit_type)">
              {{ hitLabel(source.hit_type) }}
            </span>
          </span>
          <span v-if="scoreSummary(source)" class="source-score-line">
            {{ scoreSummary(source) }}
          </span>
        </span>
        <AppIcon name="chevron" :size="16" />
      </summary>
      <div class="source-body">
        <!-- 使用文本插值而非 v-html，教材内容会按文本呈现，不执行其中的 HTML。 -->
        <p class="prose">{{ source.text }}</p>
        <div class="source-actions">
          <button
            v-if="showLocate"
            type="button"
            class="source-locate-btn"
            @click="emit('locate', source)"
          >
            <AppIcon name="book" :size="14" /> 在左侧原文定位
          </button>
          <!-- 后端提供来源链接时才显示原文入口；PDF 附带 #page 定位物理页码。 -->
          <a
            v-if="source.source_url"
            :href="source.source_url"
            target="_blank"
            rel="noopener"
            >新窗口打开原文档 <AppIcon name="external" :size="14"
          /></a>
        </div>
      </div>
    </details>
  </section>
</template>

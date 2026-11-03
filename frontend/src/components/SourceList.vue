<script setup>
// 通用教材引用组件：父页面传入 citations，展示编号、章/节、PDF 物理页码和原文。
// 组件只负责阅读，不重新调用问答/生成接口。
import AppIcon from "./AppIcon.vue";
defineProps({ citations: { type: Array, default: () => [] } });
</script>

<template>
  <!-- 原生 details/summary 提供可键盘操作的展开面板，避免为每条引用维护额外开关。 -->
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
        <span class="citation-number">{{ source.citation_id }}</span
        ><span
          >{{ source.section_title || source.chapter_title
          }}<small
            >教材第 {{ source.page_start }}–{{ source.page_end }} 页</small
          ></span
        ><AppIcon name="chevron" :size="16" />
      </summary>
      <div class="source-body">
        <!-- 使用文本插值而非 v-html，教材内容会按文本呈现，不执行其中的 HTML。 -->
        <p class="prose">{{ source.text }}</p>
        <!-- 后端提供来源链接时才显示 PDF 入口；#page 用于跳到实际 PDF 页码。 -->
        <a
          v-if="source.source_url"
          :href="`/api/course/source#page=${source.page_start}`"
          target="_blank"
          rel="noopener"
          >打开教材原文 <AppIcon name="external" :size="14"
        /></a>
      </div>
    </details>
  </section>
</template>

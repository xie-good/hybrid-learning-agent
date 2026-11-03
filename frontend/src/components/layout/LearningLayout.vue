<script setup>
import { computed } from "vue";
import AppIcon from "../AppIcon.vue";
import ScopeSelector from "../ScopeSelector.vue";
import { useWorkspace } from "../../composables/useWorkspace.js";
import { modeLabel, pages } from "../../lib/presentation.js";

// 共用学习页布局，不负责问答、总结或练习的业务；插槽内容由各自 View 提供。
const props = defineProps({ pageId: String, hasResult: Boolean });
const { busy, health } = useWorkspace();
const currentPage = computed(() =>
  pages.find((item) => item.id === props.pageId),
);
</script>

<template>
  <div class="learning-layout">
    <section class="learning-main">
      <ScopeSelector :allow-all="pageId === 'qa'" />
      <slot />
      <div v-if="!hasResult" class="learning-placeholder">
        <span class="placeholder-symbol"
          ><AppIcon :name="currentPage.icon" :size="32"
        /></span>
        <h3>{{ busy ? "正在连接知识与理解…" : "准备好，开启一次新的探索" }}</h3>
        <p>
          {{
            busy
              ? "正在处理教材证据，请稍候。"
              : "选择学习范围，在这里收获有依据的理解。"
          }}
        </p>
      </div>
    </section>
    <aside class="learning-aside">
      <section class="panel tip-panel">
        <span class="tiny-label">LEARNING NOTES</span>
        <h3>让理解，多走一步。</h3>
        <p>
          {{
            pageId === "qa"
              ? "具体的问题，往往带来更清晰的答案。试着加入教材中的术语，或缩小到一个章节。"
              : pageId === "summary"
                ? "总结是知识地图，而不是阅读的替代。结合教材引用回到上下文，再用自己的话复述一遍。"
                : "先独立作答，再查看解析。简答题不做语义自动判分，请对照原文诚实自评。"
          }}
        </p>
        <div class="tip-divider"></div>
        <AppIcon name="book" :size="23" /><strong
          >基于教材，而非凭空回答</strong
        >
        <p>每条引用都保留章节与 PDF 实际页码，展开即可核对原文。</p>
      </section>
      <div class="mode-note">
        <span class="online-dot"></span> 当前模式：{{
          health ? modeLabel(health.generation_mode) : "正在连接"
        }}
      </div>
    </aside>
  </div>
</template>

<script setup>
import { computed } from "vue";
import AppIcon from "../AppIcon.vue";
import ScopeSelector from "../ScopeSelector.vue";
import { useWorkspace } from "../../composables/useWorkspace.js";
import { pages } from "../../lib/presentation.js";

// 章节总结页单栏容器，不承担具体业务状态。
const props = defineProps({ pageId: String, hasResult: Boolean });
const { activeTask } = useWorkspace();
const pageConfig = computed(() =>
  pages.find((navigationPage) => navigationPage.id === props.pageId),
);
</script>

<template>
  <div class="learning-layout">
    <section class="learning-main">
      <ScopeSelector :allow-all="pageId === 'qa'">
        <template #action>
          <slot name="scope-action" />
        </template>
      </ScopeSelector>
      <slot />
      <div v-if="!hasResult" class="learning-placeholder">
        <span class="placeholder-symbol"
          ><AppIcon :name="pageConfig.icon" :size="28"
        /></span>
        <h3>{{ activeTask ? "正在连接…" : pageConfig.title }}</h3>
        <p>
          {{
            activeTask
              ? "正在处理知识库证据，请稍候…"
              : pageConfig.subtitle
          }}
        </p>
      </div>
    </section>
  </div>
</template>

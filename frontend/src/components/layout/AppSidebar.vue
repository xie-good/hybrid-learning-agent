<script setup>
// 侧栏采用“3 个核心工作区 + 折叠学习工具”的精简导航，突出知识库、多轮问答与笔记闭环。
import AppIcon from "../AppIcon.vue";
import { useWorkspace } from "../../composables/useWorkspace.js";
import { primaryPages, toolPages } from "../../lib/presentation.js";

const {
  isSidebarOpen,
  currentPageId,
  knowledgeBases,
  selectedKbId,
  selectKnowledgeBase,
  navigate,
} = useWorkspace();
</script>

<template>
  <!-- 桌面常驻、移动端抽屉展示；一级入口精简为 AI 问答、知识库与学习笔记。 -->
  <aside class="sidebar" :class="{ open: isSidebarOpen }">
    <a class="brand" href="#qa" @click.prevent="navigate('qa')"
      ><span class="brand-mark"><AppIcon name="book" :size="20" /></span
      ><span>知序<span class="brand-en">混合检索学习助手</span></span></a
    >
    <div class="workspace-label">学习空间</div>
    <nav aria-label="主导航">
      <a
        v-for="navigationPage in primaryPages"
        :key="navigationPage.id"
        :href="`#${navigationPage.id}`"
        :class="['nav-item', { active: currentPageId === navigationPage.id }]"
        :aria-current="currentPageId === navigationPage.id ? 'page' : undefined"
        @click.prevent="navigate(navigationPage.id)"
        ><AppIcon :name="navigationPage.icon" :size="18" /><span>{{ navigationPage.title }}</span
        ><span v-if="currentPageId === navigationPage.id" class="nav-dot"></span
      ></a>

      <details class="nav-group" open>
        <summary>
          <AppIcon name="grid" :size="16" />
          <span>学习工具</span>
          <AppIcon name="chevron" :size="14" class="nav-group-chevron" />
        </summary>
        <div class="nav-group-items">
          <a
            v-for="toolPage in toolPages"
            :key="toolPage.id"
            :href="`#${toolPage.id}`"
            :class="['nav-item', { active: currentPageId === toolPage.id }]"
            :aria-current="currentPageId === toolPage.id ? 'page' : undefined"
            @click.prevent="navigate(toolPage.id)"
            ><AppIcon :name="toolPage.icon" :size="17" /><span>{{ toolPage.title }}</span
            ><span v-if="currentPageId === toolPage.id" class="nav-dot"></span
          ></a>
        </div>
      </details>
    </nav>

    <div class="sidebar-bottom">
      <div v-if="knowledgeBases?.length" class="sidebar-kb-box">
        <span class="sidebar-kb-label">当前检索知识库</span>
        <select
          :value="selectedKbId"
          aria-label="切换知识库"
          class="sidebar-kb-select"
          @change="selectKnowledgeBase($event.target.value)"
        >
          <option v-for="kb in knowledgeBases" :key="kb.kb_id" :value="kb.kb_id">
            {{ kb.name }}（{{ kb.chunk_count }}块）
          </option>
        </select>
      </div>
      <div class="session-user">
        <span class="avatar">学</span>
        <div>学习者<small>原文可溯源 · 多轮可追问</small></div>
        <span class="online-dot"></span>
      </div>
    </div>
  </aside>
</template>

<script setup>
// 根组件只负责工作区生命周期、精简公共外壳和五页装配，保持单向数据流。
import { onMounted, onUnmounted, provide } from "vue";
import AppIcon from "./components/AppIcon.vue";
import AppSidebar from "./components/layout/AppSidebar.vue";
import AppTopbar from "./components/layout/AppTopbar.vue";
import OverviewView from "./views/OverviewView.vue";
import KnowledgeView from "./views/KnowledgeView.vue";
import QuestionView from "./views/QuestionView.vue";
import SummaryView from "./views/SummaryView.vue";
import HistoryView from "./views/HistoryView.vue";
import { createWorkspace, workspaceKey } from "./composables/useWorkspace.js";

// 每次挂载创建独立工作区；provide/inject 让页面和公共区域共用课程与会话数据。
const workspace = createWorkspace();
provide(workspaceKey, workspace);
const {
  currentPageId,
  isSidebarOpen,
  serviceHealth,
  isInitializing,
  activeTask,
  errorMessage,
  noticeMessage,
  initializeWorkspace,
} = workspace;
const pageComponents = {
  overview: OverviewView,
  knowledge: KnowledgeView,
  qa: QuestionView,
  summary: SummaryView,
  history: HistoryView,
};

onMounted(() => {
  initializeWorkspace();
  window.addEventListener("hashchange", workspace.syncPageFromHash);
});
onUnmounted(() =>
  window.removeEventListener("hashchange", workspace.syncPageFromHash),
);
</script>

<template>
  <!-- 公共侧栏与顶栏始终保留，主区域直接展示当前功能工作区，去除冗余多层标题。 -->
  <a class="skip-link" href="#main">跳转到主要内容</a>
  <button
    v-if="isSidebarOpen"
    class="drawer-overlay"
    aria-label="关闭导航"
    @click="isSidebarOpen = false"
  ></button>
  <AppSidebar />
  <div class="app-shell">
    <AppTopbar />
    <main
      id="main"
      class="main-content"
      :class="{ 'wide-stage': currentPageId === 'qa' }"
      tabindex="-1"
    >
      <div v-if="errorMessage" class="message error" role="alert">
        <AppIcon name="info" /><span>{{ errorMessage }}</span
        ><button
          class="text-button"
          :disabled="isInitializing || !!activeTask"
          @click="initializeWorkspace"
        >
          重新连接</button
        ><button class="icon-button" aria-label="关闭提示" @click="errorMessage = ''">
          <AppIcon name="close" :size="16" />
        </button>
      </div>
      <div v-if="noticeMessage" class="message success" role="status">
        <AppIcon name="check" />{{ noticeMessage }}
      </div>
      <div
        v-if="!isInitializing && serviceHealth && serviceHealth.status !== 'ok' && currentPageId !== 'knowledge'"
        class="message warning"
        role="status"
      >
        当前知识库部分能力尚未就绪，可前往「知识库」上传文档或检查后端配置。
      </div>

      <KeepAlive>
        <component :is="pageComponents[currentPageId]" :key="currentPageId" />
      </KeepAlive>
    </main>
  </div>
</template>

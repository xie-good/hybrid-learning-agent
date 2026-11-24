<script setup>
// 根组件只负责工作区生命周期、公共外壳和页面装配，不包含五个页面的业务函数。
import { onMounted, onUnmounted, provide } from "vue";
import AppIcon from "./components/AppIcon.vue";
import AppSidebar from "./components/layout/AppSidebar.vue";
import AppTopbar from "./components/layout/AppTopbar.vue";
import OverviewView from "./views/OverviewView.vue";
import QuestionView from "./views/QuestionView.vue";
import SummaryView from "./views/SummaryView.vue";
import QuizView from "./views/QuizView.vue";
import HistoryView from "./views/HistoryView.vue";
import { createWorkspace, workspaceKey } from "./composables/useWorkspace.js";

// 每次挂载创建独立工作区；provide/inject 让页面和公共区域共用课程与会话数据。
const workspace = createWorkspace();
provide(workspaceKey, workspace);
const {
  currentPageId,
  activePageConfig,
  isSidebarOpen,
  courseInfo,
  serviceHealth,
  isInitializing,
  activeTask,
  errorMessage,
  noticeMessage,
  initializeWorkspace,
} = workspace;
const pageComponents = {
  overview: OverviewView,
  qa: QuestionView,
  summary: SummaryView,
  quiz: QuizView,
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
  <!-- 公共导航与手机遮罩始终保留，切换页面只替换 main 中的 View。 -->
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
    <main id="main" class="main-content" tabindex="-1">
      <div class="page-heading">
        <div>
          <div class="eyebrow">
            {{ currentPageId === "overview" ? "学习相连" : "探索 · 理解 · 记忆" }}
          </div>
          <h1>
            {{ activePageConfig.title
            }}<span v-if="currentPageId === 'overview'" class="heading-dot">.</span>
          </h1>
          <p>{{ activePageConfig.subtitle }}</p>
        </div>
        <span class="heading-badge"
          ><AppIcon name="book" :size="16" />
          {{ courseInfo?.name || "Hello-Agents 课程" }}</span
        >
      </div>
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
        v-if="!isInitializing && serviceHealth && serviceHealth.status !== 'ok'"
        class="message warning"
        role="status"
      >
        服务部分能力尚未就绪：请检查知识库、检索、生成及历史存储配置。
      </div>

      <!-- 缓存已访问页面：离开再回来时，搜索词、提问内容和本轮作答仍保留。
           章/节变化时，由各 View 的 watch 主动清除失效结果，而非依赖卸载重置。 -->
      <KeepAlive>
        <component :is="pageComponents[currentPageId]" :key="currentPageId" />
      </KeepAlive>

      <footer class="page-footer">
        <span
          ><span class="footer-mark">知序</span> 让知识有序，让学习发生。</span
        ><span>教材为源 · 理解为本</span>
      </footer>
    </main>
  </div>
</template>

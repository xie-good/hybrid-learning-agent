<script setup>
// 顶栏精简展示当前工作区标题、激活知识库与服务状态，并提供移动端菜单开关。
import AppIcon from "../AppIcon.vue";
import { useWorkspace } from "../../composables/useWorkspace.js";

const {
  isSidebarOpen,
  activePageConfig,
  courseInfo,
  serviceHealth,
  isInitializing,
} = useWorkspace();
</script>

<template>
  <header class="topbar">
    <div class="breadcrumb">
      <button
        class="mobile-menu icon-button"
        :aria-label="isSidebarOpen ? '关闭导航' : '打开导航'"
        :aria-expanded="isSidebarOpen"
        @click="isSidebarOpen = !isSidebarOpen"
      >
        <AppIcon name="menu" /></button
      ><strong>{{ activePageConfig.title }}</strong>
    </div>
    <div class="topbar-right">
      <span class="topbar-kb-pill">
        <AppIcon name="book" :size="14" />
        {{ courseInfo?.name || "Hello-Agents" }}
      </span>
      <span class="service-status" :class="{ offline: serviceHealth?.status !== 'ok' }"
        ><i></i
        >{{
          isInitializing
            ? "正在连接…"
            : serviceHealth?.status === "ok"
              ? "已连接"
              : "待就绪"
        }}</span
      >
    </div>
  </header>
</template>

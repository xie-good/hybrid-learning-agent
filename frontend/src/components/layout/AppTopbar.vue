<script setup>
// 顶栏只显示当前页面和真实服务状态，并为手机提供导航开关，不处理页面业务。
import AppIcon from "../AppIcon.vue";
import { useWorkspace } from "../../composables/useWorkspace.js";

const { drawer, activePage, health, loading } = useWorkspace();
</script>

<template>
  <header class="topbar">
    <div class="breadcrumb">
      <button
        class="mobile-menu icon-button"
        aria-label="打开导航"
        :aria-expanded="drawer"
        @click="drawer = !drawer"
      >
        <AppIcon name="menu" /></button
      ><span>学习空间</span><AppIcon name="chevron" :size="13" /><strong>{{
        activePage.title
      }}</strong>
    </div>
    <div class="topbar-right">
      <span class="service-status" :class="{ offline: health?.status !== 'ok' }"
        ><i></i
        >{{
          loading
            ? "正在连接"
            : health?.status === "ok"
              ? "服务已连接"
              : "服务待就绪"
        }}</span
      ><span class="topbar-divider"></span
      ><span class="avatar avatar-small">学</span>
    </div>
  </header>
</template>

<script setup>
// 侧栏负责主导航与课程信息；抽屉开关由工作区共享，顶栏按钮和遮罩可同步关闭它。
import AppIcon from "../AppIcon.vue";
import { useWorkspace } from "../../composables/useWorkspace.js";
import { pages } from "../../lib/presentation.js";

const {
  isSidebarOpen,
  currentPageId,
  chapters,
  navigate,
  courseInfo,
} = useWorkspace();
</script>

<template>
  <!-- 桌面常驻、手机展开为抽屉；导航文字与高亮统一来自页面配置和当前 currentPageId。 -->
  <aside class="sidebar" :class="{ open: isSidebarOpen }">
    <a class="brand" href="#overview" @click.prevent="navigate('overview')"
      ><span class="brand-mark"><AppIcon name="book" :size="25" /></span
      ><span>知序<span class="brand-en">学习伙伴</span></span></a
    >
    <div class="workspace-label">我的学习空间</div>
    <nav aria-label="主导航">
      <a
        v-for="navigationPage in pages"
        :key="navigationPage.id"
        :href="`#${navigationPage.id}`"
        :class="['nav-item', { active: currentPageId === navigationPage.id }]"
        :aria-current="currentPageId === navigationPage.id ? 'page' : undefined"
        @click.prevent="navigate(navigationPage.id)"
        ><AppIcon :name="navigationPage.icon" /><span>{{ navigationPage.title }}</span
        ><span v-if="currentPageId === navigationPage.id" class="nav-dot"></span
      ></a>
    </nav>
    <div class="sidebar-course">
      <span class="tiny-label">正在探索的课程</span>
      <div class="sidebar-course-title">
        <span class="mini-book"><AppIcon name="book" /></span>
        <div>{{ courseInfo?.name || "Hello-Agents" }}<small>智能体系统设计与实现</small></div>
      </div>
      <span class="course-version"
        >预置课程 · {{ chapters.length || "—" }} 个章节</span
      >
    </div>
    <div class="sidebar-bottom">
      <div class="study-note">
        <AppIcon name="spark" :size="18" />
        <p>知识不止于读过，<br />更在于真正理解。</p>
      </div>
      <div class="session-user">
        <span class="avatar">学</span>
        <div>学习者<small>专注今天的每一点进步</small></div>
        <span class="online-dot"></span>
      </div>
    </div>
  </aside>
</template>

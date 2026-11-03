<script setup>
// 侧栏负责导航和使用说明；抽屉开关由工作区共享，顶栏按钮和遮罩可同步关闭它。
import { ref } from "vue";
import AppIcon from "../AppIcon.vue";
import { useWorkspace } from "../../composables/useWorkspace.js";
import { pages } from "../../lib/presentation.js";

const { drawer, page, chapters, session, navigate } = useWorkspace();
const help = ref(false);
</script>

<template>
  <!-- 桌面常驻、手机展开为抽屉；导航文字与高亮统一来自页面配置和当前 page。 -->
  <aside class="sidebar" :class="{ open: drawer }">
    <a class="brand" href="#overview" @click.prevent="navigate('overview')"
      ><span class="brand-mark"><AppIcon name="book" :size="25" /></span
      ><span>知序<span class="brand-en">LEARNING COMPANION</span></span></a
    >
    <div class="workspace-label">我的学习空间 <span>WORKSPACE</span></div>
    <nav aria-label="主导航">
      <a
        v-for="item in pages"
        :key="item.id"
        :href="`#${item.id}`"
        :class="['nav-item', { active: page === item.id }]"
        :aria-current="page === item.id ? 'page' : undefined"
        @click.prevent="navigate(item.id)"
        ><AppIcon :name="item.icon" /><span>{{ item.title }}</span
        ><span v-if="page === item.id" class="nav-dot"></span
      ></a>
    </nav>
    <div class="sidebar-course">
      <span class="tiny-label">正在探索的课程</span>
      <div class="sidebar-course-title">
        <span class="mini-book"><AppIcon name="book" /></span>
        <div>Hello-Agents<small>智能体系统设计与实现</small></div>
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
      <button class="help-button" @click="help = !help">
        <AppIcon name="info" :size="18" /> 使用与连接信息
        <AppIcon :name="help ? 'close' : 'chevron'" :size="14" />
      </button>
      <div v-if="help" class="help-panel">
        先启动
        FastAPI，再通过本工作台学习。总结和练习不计入问答历史；当前标签页刷新后会话保留，关闭后结束。<br />会话
        {{ session.slice(0, 8) }}<br /><a
          href="/api/health"
          target="_blank"
          rel="noopener"
          >查看服务状态 ↗</a
        >
      </div>
      <div class="session-user">
        <span class="avatar">学</span>
        <div>学习者<small>专注今天的每一点进步</small></div>
        <span class="online-dot"></span>
      </div>
    </div>
  </aside>
</template>

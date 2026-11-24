<script setup>
// 工作台只管理目录搜索与展开状态；课程、连接状态和历史摘要由共享工作区提供。
// 父级使用 KeepAlive，离开再返回时会保留搜索词，不必重新请求整份课程目录。
import { computed, ref } from "vue";
import AppIcon from "../components/AppIcon.vue";
import { useWorkspace } from "../composables/useWorkspace.js";
import { dateLabel, titleWithoutNumber } from "../lib/presentation.js";

const {
  isLearningReady,
  isInitializing,
  chapters,
  serviceHealth,
  historyResult,
  recentHistoryItems,
  navigate,
  initializeWorkspace,
} = useWorkspace();
const chapterSearchText = ref("");
const showAllChapters = ref(false);
// 搜索覆盖全部章/节名称，不受“默认只展示前六章”影响，也不改变学习范围。
const filteredChapters = computed(() =>
  chapters.value.filter((chapter) =>
    `${chapter.title} ${chapter.sections.map((section) => section.title).join(" ")}`
      .toLowerCase()
      .includes(chapterSearchText.value.toLowerCase()),
  ),
);
const visibleChapters = computed(() =>
  chapterSearchText.value || showAllChapters.value
    ? filteredChapters.value
    : filteredChapters.value.slice(0, 6),
);
</script>

<template>
  <!-- 课程介绍、真实统计、课程目录和学习闭环入口组成工作台，不包含公共页标题。 -->
  <section class="hero">
    <div class="hero-content">
      <div class="hero-tag"><span></span> 从知识到理解，从这里开始</div>
      <h2>把零散的知识，<br />连成自己的<span>体系。</span></h2>
      <p>
        以 Hello-Agents 为起点，让总结、提问与练习<br
          class="desktop-break"
        />串联每一次探索，每一步都有教材可循。
      </p>
      <div class="hero-actions">
        <a
          class="button hero-primary"
          :href="isLearningReady ? '#summary' : undefined"
          :aria-disabled="!isLearningReady ? 'true' : undefined"
          :tabindex="!isLearningReady ? -1 : undefined"
          @click.exact.prevent="isLearningReady && navigate('summary')"
        >
          开始章节学习 <AppIcon name="arrow" :size="17" /></a
        ><a class="hero-secondary" href="#qa" @click.exact.prevent="navigate('qa')">
          向教材提个问题 <AppIcon name="arrow" :size="16" />
        </a>
      </div>
    </div>
    <!-- 封面插画由 CSS 绘制，仅作装饰，因此对辅助阅读工具隐藏。 -->
    <div class="hero-art" aria-hidden="true">
      <div class="orbit orbit-one"></div>
      <div class="orbit orbit-two"></div>
      <div class="art-dot dot-one"></div>
      <div class="art-dot dot-two"></div>
      <div class="art-dot dot-three"></div>
      <div class="floating-label label-knowledge">
        <AppIcon name="layers" :size="15" /> 知识连接
      </div>
      <div class="book-object">
        <span class="book-spine"></span
        ><span class="book-top"
          >智能体<br />入门<span class="book-rule"></span
          ><small>探索智能体的世界</small
          ><AppIcon name="spark" :size="40" /><span class="book-bottom"
            >理解指南</span
          ></span
        >
      </div>
      <div class="floating-label label-evidence">
        <span class="evidence-check"><AppIcon name="check" :size="12" /></span>
        每一步，皆有依据
      </div>
      <span class="art-caption">在语境中学习</span>
    </div>
  </section>

  <!-- 数字分别来自 chapters、serviceHealth 与当前会话历史，不是写死的演示统计。 -->
  <section class="stats-grid" aria-label="课程统计">
    <div class="stat-card">
      <span class="stat-icon green"><AppIcon name="book" :size="23" /></span>
      <div>
        <span>课程章节</span
        ><strong>{{ isInitializing ? "—" : chapters.length }}<small>章</small></strong>
      </div>
      <span class="stat-note">系统化的知识脉络</span>
    </div>
    <div class="stat-card">
      <span class="stat-icon lavender"
        ><AppIcon name="layers" :size="23"
      /></span>
      <div>
        <span>知识文本块</span
        ><strong
          >{{ serviceHealth ? serviceHealth.chunk_count.toLocaleString() : "—"
          }}<small>块</small></strong
        >
      </div>
      <span class="stat-note">可追溯的教材证据</span>
    </div>
    <div class="stat-card">
      <span class="stat-icon peach"><AppIcon name="chat" :size="23" /></span>
      <div>
        <span>本次会话提问</span
        ><strong>{{ historyResult.total }}<small>次</small></strong>
      </div>
      <a class="stat-link" href="#history" @click.exact.prevent="navigate('history')">
        回顾记录 <AppIcon name="arrow" :size="14" />
      </a>
    </div>
  </section>

  <div class="workbench-grid">
    <section class="catalog">
      <div class="section-heading">
        <div>
          <h2>
            探索课程目录
            <span class="pill">{{ chapters.length }} 章</span>
          </h2>
          <p>选一个章节，开启今天的学习。</p>
        </div>
        <button class="text-button" @click="showAllChapters = !showAllChapters">
          {{ showAllChapters ? "收起目录" : "全部章节" }}
          <AppIcon name="arrow" :size="15" />
        </button>
      </div>
      <label class="search-box"
        ><AppIcon name="search" :size="18" /><input
          v-model="chapterSearchText"
          type="search"
          name="chapter-search"
          autocomplete="off"
          aria-label="搜索章节"
          placeholder="搜索章节名称或知识点…"
        /><kbd>/</kbd></label
      >
      <div v-if="isInitializing" class="empty-state" role="status">
        <span class="spinner"></span>正在加载课程目录…
      </div>
      <div v-else-if="!visibleChapters.length" class="empty-state">
        <AppIcon name="search" :size="30" />
        <h3>{{ chapterSearchText ? "没有找到相关章节" : "课程目录尚未就绪" }}</h3>
        <p>
          {{
            chapterSearchText
              ? "试试其他章节名称或关键词。"
              : "连接后端并加载课程后，即可开始学习。"
          }}
        </p>
        <button
          class="button secondary"
          @click="chapterSearchText ? (chapterSearchText = '') : initializeWorkspace()"
        >
          {{ chapterSearchText ? "清除搜索" : "重新加载" }}
        </button>
      </div>
      <div v-else class="chapter-grid">
        <article
          v-for="(chapter, index) in visibleChapters"
          :key="chapter.chapter_id"
          class="chapter-card"
        >
          <div class="chapter-card-top">
            <span
              class="chapter-number"
              :class="`chapter-color-${index % 4}`"
              >{{ chapter.chapter_id.slice(2) }}</span
            ><span class="chapter-pages"
              >P.{{ chapter.page_start }}–{{ chapter.page_end }}</span
            >
          </div>
          <h3>{{ titleWithoutNumber(chapter.title) }}</h3>
          <p>
            {{
              chapter.sections
                .slice(0, 2)
                .map((section) => section.title.replace(/^\d+(\.\d+)*\s*/, ""))
                .join(" · ") || "从核心概念到系统理解"
            }}
          </p>
          <div class="chapter-card-bottom">
            <span
              >{{ chapter.sections.length }} 个小节
              <span class="muted-dot">·</span>
              {{ chapter.chunk_count ?? "—" }} 个文本块</span
            ><a
              href="#summary"
              :aria-label="`学习${chapter.title}`"
              @click.exact.prevent="navigate('summary', chapter.chapter_id)"
            >
              <AppIcon name="arrow" :size="17" />
            </a>
          </div>
        </article>
      </div>
      <div
        v-if="
          visibleChapters.length && !chapterSearchText && !showAllChapters && chapters.length > 6
        "
        class="catalog-footer"
      >
        <span>好的理解，始于有序的探索。</span
        ><button class="text-button" @click="showAllChapters = true">
          查看其余 {{ chapters.length - 6 }} 章
          <AppIcon name="chevron" :size="14" />
        </button>
      </div>
    </section>
    <aside class="right-column">
      <section class="path-card">
        <div class="section-heading">
          <h2>让学习形成闭环</h2>
          <AppIcon name="spark" :size="19" />
        </div>
        <p class="muted">不止于读懂，更要学会运用。</p>
        <div class="learning-steps">
          <a
            v-for="(step, index) in [
              {
                id: 'summary',
                label: '先了解',
                desc: '阅读总结，建立知识框架',
              },
              {
                id: 'qa',
                label: '再提问',
                desc: '深入概念，核对教材依据',
              },
              {
                id: 'quiz',
                label: '后练习',
                desc: '主动回忆，检验学习效果',
              },
              {
                id: 'history',
                label: '常回顾',
                desc: '回访问题，串联所学知识',
              },
            ]"
            :key="step.id"
            :href="`#${step.id}`"
            @click.exact.prevent="navigate(step.id)"
          >
            <span class="step-number">0{{ index + 1 }}</span>
            <div>
              <strong>{{ step.label }}</strong
              ><small>{{ step.desc }}</small>
            </div>
            <AppIcon name="chevron" :size="15" />
          </a>
        </div>
        <div class="path-footnote">
          <AppIcon name="check" :size="15" /> 每个答案，都能回到教材原文
        </div>
      </section>
      <section class="recent-card">
        <div class="section-heading">
          <h2>最近的思考</h2>
          <AppIcon name="history" :size="18" />
        </div>
        <a
          v-for="historyItem in recentHistoryItems"
          :key="historyItem.id"
          class="recent-item"
          href="#history"
          @click.exact.prevent="navigate('history')"
        >
          <span>{{ historyItem.question }}</span
          ><small>{{ dateLabel(historyItem.created_at) }}</small>
        </a>
        <div v-if="!recentHistoryItems.length" class="recent-empty">
          <span class="recent-empty-icon"
            ><AppIcon name="chat" :size="23"
          /></span>
          <p>你的下一个好问题，<br />就是新的学习起点。</p>
          <a class="text-button" href="#qa" @click.exact.prevent="navigate('qa')">
            发起第一次提问 <AppIcon name="arrow" :size="14" />
          </a>
        </div>
      </section>
    </aside>
  </div>
</template>

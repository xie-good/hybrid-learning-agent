<script setup>
// AI 伴读问答页：左侧文档伴读（PDF 原页预览或文档切片阅读）+ 右侧混合检索问答与引用定位联动。
import { computed, nextTick, onMounted, ref, watch } from "vue";
import AppIcon from "../components/AppIcon.vue";
import SourceList from "../components/SourceList.vue";
import { useWorkspace } from "../composables/useWorkspace.js";
import { request } from "../lib/api.js";
import {
  dateLabel,
  modeLabel,
  parseAnswerBlocks,
  retrievalLabels,
} from "../lib/presentation.js";

const {
  serviceHealth,
  courseInfo,
  chapters,
  isInitializing,
  isLearningReady,
  activeTask,
  errorMessage,
  selectedKbId,
  selectedChapterId,
  selectedSectionId,
  buildLearningScope,
  runTask,
  currentSessionId,
  historyResult,
  historyOffset,
  loadHistory,
  historyClearCount,
  startNewConversation,
  navigate,
} = useWorkspace();

const question = ref("");
const topK = ref(5);
const latestTurn = ref(null);
const showHistoryDrawer = ref(false);

// 左侧文档伴读面板状态。
const showReader = ref(true);
const docList = ref([]);
const activeDocId = ref("");
const readerPage = ref(1);
const pageInput = ref("1");
const pdfZoom = ref(100);
const isPageLoading = ref(false);
const pageLoadError = ref(false);
const readerChunks = ref([]);
const isReaderLoading = ref(false);
const highlightChunkId = ref("");
const pdfScrollBox = ref(null);

// 左右分栏拖拽宽度状态（左侧占总宽度的百分比）。
const splitBox = ref(null);
const leftWidth = ref(45);
const isResizing = ref(false);

const splitStyle = computed(() => {
  if (!showReader.value) return {};
  return {
    gridTemplateColumns: `${leftWidth.value}% 10px minmax(0, 1fr)`,
  };
});

function startResize(event) {
  event.preventDefault();
  isResizing.value = true;
  const onMove = (moveEvent) => {
    if (!splitBox.value) return;
    const rect = splitBox.value.getBoundingClientRect();
    if (rect.width <= 0) return;
    const percent = ((moveEvent.clientX - rect.left) / rect.width) * 100;
    if (percent < 28) {
      leftWidth.value = 28;
    } else if (percent > 68) {
      leftWidth.value = 68;
    } else {
      leftWidth.value = Math.round(percent * 10) / 10;
    }
  };
  const onUp = () => {
    isResizing.value = false;
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
  };
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
}

const activeDoc = computed(() => {
  if (!docList.value.length) return null;
  return (
    docList.value.find((item) => item.doc_id === activeDocId.value) ||
    docList.value[0]
  );
});

const isPdfDoc = computed(() => {
  if (!activeDoc.value) return false;
  const name = (activeDoc.value.filename || "").toLowerCase();
  return (
    activeDoc.value.media_type === "application/pdf" || name.endsWith(".pdf")
  );
});

const rawDocUrl = computed(() => {
  if (!activeDoc.value) return "";
  const kbId = selectedKbId?.value || "hello_agents";
  if (kbId === "hello_agents") {
    return "/api/course/source";
  }
  return `/api/kbs/${encodeURIComponent(kbId)}/documents/${encodeURIComponent(activeDoc.value.doc_id)}/source`;
});

const pdfPageImgUrl = computed(() => {
  if (!isPdfDoc.value || !activeDoc.value) return "";
  const kbId = selectedKbId?.value || "hello_agents";
  const docId = activeDoc.value.doc_id || "builtin_hello_agents";
  return `/api/kbs/${encodeURIComponent(kbId)}/documents/${encodeURIComponent(docId)}/page/${readerPage.value || 1}`;
});

function setReaderPage(num) {
  const maxPage = activeDoc.value?.page_count || 9999;
  let target = Number(num);
  if (!Number.isFinite(target) || target < 1) {
    target = 1;
  }
  target = Math.floor(target);
  if (target > maxPage) {
    target = maxPage;
  }
  readerPage.value = target;
  pageInput.value = String(target);
  if (pdfScrollBox.value) {
    pdfScrollBox.value.scrollTop = 0;
  }
}

function changeReaderPage(step) {
  setReaderPage((readerPage.value || 1) + step);
}

function submitPageInput() {
  setReaderPage(pageInput.value);
}

function changeZoom(step) {
  const next = pdfZoom.value + step;
  if (next < 60) {
    pdfZoom.value = 60;
  } else if (next > 180) {
    pdfZoom.value = 180;
  } else {
    pdfZoom.value = next;
  }
}

function cleanDocTitle(name) {
  if (!name) return "";
  return name.replace(/\.(pdf|md|markdown)$/i, "").trim();
}

// 根据当前文档和真实章节标题动态生成推荐提问，避免写死空泛问题导致无命中。
const starterPrompts = computed(() => {
  const docName =
    cleanDocTitle(activeDoc.value?.filename) ||
    courseInfo.value?.name ||
    "当前资料";

  const chapterList = chapters?.value || [];
  let topicList = [];
  for (const ch of chapterList) {
    if (selectedChapterId?.value && ch.chapter_id !== selectedChapterId.value) {
      continue;
    }
    if (ch.sections && ch.sections.length > 0) {
      for (const sec of ch.sections) {
        if (sec.title) topicList.push(sec.title);
      }
    } else if (ch.title) {
      topicList.push(ch.title);
    }
  }

  const list = [`这份资料《${docName}》的核心内容和整体框架是什么？`];
  if (topicList.length >= 1) {
    list.push(`请结合原文详细解释「${topicList[0]}」的核心原理与关键要点`);
  } else {
    list.push(`请结合这份资料的原文，总结其中的关键方法与示例`);
  }
  if (topicList.length >= 2) {
    list.push(`「${topicList[1]}」主要讲了什么？有哪些需要特别注意的地方？`);
  } else {
    list.push(`这份资料提到了哪些核心概念或适用限制？请梳理一下`);
  }
  return list;
});

// 把后端按最新到最旧返回的记录反转，按正常的对话顺序从上往下展示。
const conversationTurns = computed(() => {
  const historyItems = historyResult.value?.items || [];
  const chronologicalTurns = [...historyItems].reverse();

  if (latestTurn.value) {
    const alreadyExists = chronologicalTurns.some(
      (item) => item.id === latestTurn.value.history_id,
    );
    if (!alreadyExists) {
      chronologicalTurns.push({
        id: latestTurn.value.history_id,
        question: latestTurn.value.askedQuestion,
        ...latestTurn.value,
        created_at: new Date().toISOString(),
      });
    }
  }
  return chronologicalTurns;
});

async function loadReaderDocs() {
  const kbId = selectedKbId?.value || "hello_agents";
  isReaderLoading.value = true;
  try {
    const res = await request(`/kbs/${encodeURIComponent(kbId)}/documents`);
    docList.value = res.items || [];
    activeDocId.value = docList.value[0]?.doc_id || "";
    readerPage.value = 1;
    highlightChunkId.value = "";
    await loadReaderChunksIfNeeded();
  } catch {
    docList.value = [];
    readerChunks.value = [];
  } finally {
    isReaderLoading.value = false;
  }
}

async function loadReaderChunksIfNeeded() {
  if (!activeDoc.value || isPdfDoc.value) {
    readerChunks.value = [];
    return;
  }
  const kbId = selectedKbId?.value || "hello_agents";
  const chapterParam = activeDoc.value.chapter_id
    ? `&chapter_id=${encodeURIComponent(activeDoc.value.chapter_id)}`
    : "";
  try {
    const res = await request(
      `/kbs/${encodeURIComponent(kbId)}/chunks?limit=100&offset=0${chapterParam}`,
    );
    readerChunks.value = res.items || [];
  } catch {
    readerChunks.value = [];
  }
}

onMounted(() => {
  loadReaderDocs();
});

watch(selectedKbId, () => {
  latestTurn.value = null;
  loadReaderDocs();
});

watch([selectedChapterId, selectedSectionId], () => {
  latestTurn.value = null;
});

watch(activeDocId, () => {
  setReaderPage(1);
  highlightChunkId.value = "";
  loadReaderChunksIfNeeded();
});

watch(pdfPageImgUrl, (url) => {
  if (url) {
    isPageLoading.value = true;
    pageLoadError.value = false;
  }
});

watch(historyClearCount, () => {
  latestTurn.value = null;
});

async function locateCitation(source) {
  showReader.value = true;
  // 先尝试切换到引用所属的文档。
  const matchedDoc = docList.value.find(
    (item) =>
      item.chapter_id === source.chapter_id ||
      item.filename === source.source_file,
  );
  if (matchedDoc && matchedDoc.doc_id !== activeDocId.value) {
    activeDocId.value = matchedDoc.doc_id;
    await loadReaderChunksIfNeeded();
  }
  setReaderPage(source.page_start || 1);
  highlightChunkId.value = source.chunk_id || "";

  if (!isPdfDoc.value && source.chunk_id) {
    await nextTick();
    const targetEl = document.getElementById(`reader-chunk-${source.chunk_id}`);
    if (targetEl) {
      targetEl.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }
}

function ask(overrideText = "") {
  const hasOverride = typeof overrideText === "string" && overrideText.length > 0;
  const rawText = hasOverride ? overrideText : question.value;
  const cleanedQuestion = rawText.trim();
  if (!cleanedQuestion) {
    errorMessage.value = "请输入问题后再发送。";
    return;
  }

  const retrievalMode = serviceHealth.value?.default_retrieval_mode || "hybrid";
  const scopeParams = buildLearningScope();
  const requestBody = {
    chapter_id: scopeParams.chapter_id,
    section_id: scopeParams.section_id,
    question: cleanedQuestion,
    session_id: currentSessionId,
    retrieval_mode: retrievalMode,
    top_k: topK.value,
  };
  if (selectedKbId?.value && selectedKbId.value !== "hello_agents") {
    requestBody.kb_id = selectedKbId.value;
  }

  runTask("qa", async () => {
    const responseData = await request("/qa", {
      method: "POST",
      body: requestBody,
      timeout: 120000,
    });
    latestTurn.value = { ...responseData, askedQuestion: cleanedQuestion };
    if (!hasOverride) {
      question.value = "";
    }
    historyOffset.value = 0;
    await loadHistory();
  });
}

function handleEnterSubmit(keyboardEvent) {
  if (keyboardEvent.shiftKey || keyboardEvent.isComposing) return;
  if (!isLearningReady.value || !!activeTask.value || !question.value.trim()) return;
  ask();
}

</script>

<template>
  <div
    ref="splitBox"
    class="qa-split-layout"
    :class="{ 'reader-hidden': !showReader, 'is-resizing': isResizing }"
    :style="splitStyle"
  >
    <!-- 左侧文档伴读区：PDF 按页渲染为纯白高清图，无黑边；支持页码跳转与缩放。 -->
    <section v-if="showReader" class="reader-pane" aria-label="文档伴读区">
      <div class="reader-header">
        <div class="reader-header-left">
          <AppIcon name="book" :size="16" />
          <select
            v-if="docList.length > 1"
            v-model="activeDocId"
            class="reader-doc-select"
            aria-label="切换伴读文档"
          >
            <option v-for="doc in docList" :key="doc.doc_id" :value="doc.doc_id">
              {{ doc.filename }}
            </option>
          </select>
          <strong v-else class="reader-doc-title">
            {{ activeDoc?.filename || courseInfo?.name || "当前学习资料" }}
          </strong>
        </div>
        <div class="reader-header-actions">
          <div v-if="isPdfDoc" class="reader-pager">
            <button
              type="button"
              class="pager-btn"
              :disabled="readerPage <= 1"
              title="上一页"
              @click="changeReaderPage(-1)"
            >
              ‹
            </button>
            <input
              v-model="pageInput"
              type="text"
              inputmode="numeric"
              class="pager-input"
              aria-label="当前页码"
              @keydown.enter.prevent="submitPageInput"
              @blur="submitPageInput"
            />
            <span v-if="activeDoc?.page_count" class="pager-total">/ {{ activeDoc.page_count }}</span>
            <button
              type="button"
              class="pager-btn"
              :disabled="activeDoc?.page_count && readerPage >= activeDoc.page_count"
              title="下一页"
              @click="changeReaderPage(1)"
            >
              ›
            </button>
          </div>
          <div v-if="isPdfDoc" class="reader-zoom">
            <button type="button" class="pager-btn" title="缩小" @click="changeZoom(-15)">−</button>
            <span class="pager-num">{{ pdfZoom }}%</span>
            <button type="button" class="pager-btn" title="放大" @click="changeZoom(15)">+</button>
          </div>
          <a
            v-if="rawDocUrl"
            :href="isPdfDoc ? `${rawDocUrl}#page=${readerPage}` : rawDocUrl"
            target="_blank"
            rel="noopener"
            class="icon-button"
            title="新标签页打开原文档"
          >
            <AppIcon name="external" :size="15" />
          </a>
          <button
            type="button"
            class="icon-button"
            title="收起原文伴读"
            aria-label="收起原文伴读"
            @click="showReader = false"
          >
            <AppIcon name="close" :size="16" />
          </button>
        </div>
      </div>

      <div class="reader-body">
        <div v-if="isReaderLoading" class="reader-empty">
          <span class="spinner"></span>
          <p>正在加载原文资料…</p>
        </div>
        <div v-else-if="!activeDoc" class="reader-empty">
          <p>当前知识库还没有上传学习文档。</p>
          <a class="button secondary" href="#knowledge" @click.exact.prevent="navigate('knowledge')">
            去上传 PDF / 文档
          </a>
        </div>
        <div v-else-if="isPdfDoc" ref="pdfScrollBox" class="reader-pdf-scroll">
          <div v-if="isPageLoading" class="reader-page-status">
            <span class="spinner"></span> 正在渲染第 {{ readerPage }} 页…
          </div>
          <div v-if="pageLoadError" class="reader-empty">
            <p>第 {{ readerPage }} 页预览加载失败。</p>
            <a :href="`${rawDocUrl}#page=${readerPage}`" target="_blank" rel="noopener" class="button secondary">
              在新窗口打开原 PDF
            </a>
          </div>
          <img
            v-show="!pageLoadError"
            :src="pdfPageImgUrl"
            :alt="`第 ${readerPage} 页预览`"
            class="reader-pdf-img"
            :style="{ width: `${pdfZoom}%` }"
            @load="isPageLoading = false"
            @error="isPageLoading = false; pageLoadError = true"
          />
        </div>
        <div v-else class="reader-chunk-list">
          <p class="reader-tip">
            当前为文本文档，共 {{ readerChunks.length }} 段；点击右侧引用中的「在左侧原文定位」可自动高亮跳转。
          </p>
          <article
            v-for="(chunk, idx) in readerChunks"
            :id="`reader-chunk-${chunk.chunk_id}`"
            :key="chunk.chunk_id"
            class="reader-chunk-card"
            :class="{ active: highlightChunkId === chunk.chunk_id }"
          >
            <div class="reader-chunk-meta">
              <strong>#{{ idx + 1 }} · {{ chunk.section_title || chunk.chapter_title }}</strong>
              <span>第 {{ chunk.page_start }} 页</span>
            </div>
            <p class="prose">{{ chunk.text }}</p>
          </article>
        </div>
      </div>
    </section>

    <!-- 中间可拖动分割条：按住鼠标左右拉动即可调整原文与问答区宽度。 -->
    <div
      v-if="showReader"
      class="split-resizer"
      role="separator"
      aria-orientation="vertical"
      aria-label="左右拖动调整伴读宽度"
      title="按住左右拖动调整宽度"
      @mousedown="startResize"
    >
      <span class="split-resizer-bar"></span>
    </div>

    <!-- 右侧混合检索问答区 -->
    <div class="chat-workspace">
      <div class="chat-toolbar">
        <div class="chat-toolbar-left">
          <button
            type="button"
            class="button secondary"
            @click="showReader = !showReader"
          >
            <AppIcon name="book" :size="15" />
            {{ showReader ? "收起原文" : "打开原文伴读" }}
          </button>
          <select
            v-if="chapters?.length"
            v-model="selectedChapterId"
            aria-label="限定检索章节"
            class="chat-scope-select"
          >
            <option value="">全部章节 / 文档</option>
            <option v-for="ch in chapters" :key="ch.chapter_id" :value="ch.chapter_id">
              {{ ch.title }}
            </option>
          </select>
        </div>
        <div class="chat-toolbar-right">
          <button
            type="button"
            class="button secondary"
            @click="showHistoryDrawer = true; loadHistory()"
          >
            <AppIcon name="history" :size="15" /> 历史
            <span v-if="historyResult.total" class="pill">{{ historyResult.total }}</span>
          </button>
          <button
            type="button"
            class="button secondary"
            :disabled="!!activeTask"
            @click="startNewConversation"
          >
            <AppIcon name="plus" :size="15" /> 新对话
          </button>
        </div>
      </div>

      <div class="chat-scroll-area" aria-live="polite">
        <div v-if="isInitializing" class="panel empty-state" role="status">
          <span class="spinner"></span>
          <h3>正在切换知识库…</h3>
          <p>正在加载目录与检索索引，请稍候…</p>
        </div>

        <div v-else-if="!isLearningReady" class="panel empty-state">
          <h3>当前知识库尚未上传文档</h3>
          <p>前往「知识库」上传 PDF (.pdf) 或 Markdown (.md) 后，即可开始混合检索问答。</p>
          <a class="button primary" href="#knowledge" @click.exact.prevent="navigate('knowledge')">
            上传学习文档 <AppIcon name="arrow" :size="16" />
          </a>
        </div>

        <div v-else-if="!conversationTurns.length" class="chat-welcome">
          <span class="placeholder-symbol"><AppIcon name="spark" :size="28" /></span>
          <h2>混合检索伴读助手</h2>
          <p>
            当前资料：<strong>{{ courseInfo?.name || "Hello-Agents" }}</strong>（{{
              courseInfo?.chunk_count || 0
            }}
            个片段）。左侧边读文档，右侧用 BM25 + 向量混合检索提问，点引用可直达原页。
          </p>
          <div class="starter-grid">
            <button
              v-for="promptText in starterPrompts"
              :key="promptText"
              type="button"
              class="starter-card"
              :disabled="!!activeTask"
              @click="ask(promptText)"
            >
              {{ promptText }}
            </button>
          </div>
        </div>

        <template v-else>
          <div v-for="turnItem in conversationTurns" :key="turnItem.id" class="chat-turn-block">
            <div class="chat-user-row">
              <div class="chat-user-pill">{{ turnItem.question }}</div>
            </div>

            <div class="chat-assistant-row">
              <span class="assistant-avatar"><AppIcon name="spark" :size="17" /></span>
              <div class="assistant-content">
                <details class="retrieval-trace">
                  <summary>
                    <span>混合检索与上下文过程</span>
                    <span class="pill">{{ retrievalLabels[turnItem.retrieval_mode] || "混合检索" }}</span>
                    <span class="muted">
                      命中 {{ turnItem.citations?.length || 0 }} 条 · {{ turnItem.latency_ms }} ms
                    </span>
                  </summary>
                  <div class="retrieval-trace-body">
                    <div>
                      <strong>生成方式：</strong>{{ modeLabel(turnItem.generation_mode) }}
                    </div>
                    <div v-if="turnItem.rewritten_question">
                      <strong>多轮指代补全：</strong>「{{ turnItem.question }}」→「{{
                        turnItem.rewritten_question
                      }}」
                    </div>
                    <div>
                      <strong>数据版本：</strong>{{ turnItem.dataset_version }}
                    </div>
                  </div>
                </details>

                <p v-if="turnItem.insufficient_evidence" class="message warning">
                  当前资料库证据不足以回答该问题，请补充关键词、切换知识库或上传相关资料。
                </p>

                <div class="structured-answer">
                  <template
                    v-for="(blockItem, blockIndex) in parseAnswerBlocks(turnItem.answer)"
                    :key="`${turnItem.id}-${blockIndex}`"
                  >
                    <h3 v-if="blockItem.type === 'heading'" class="answer-heading">
                      {{ blockItem.text }}
                    </h3>
                    <ul v-else-if="blockItem.type === 'list'" class="answer-list">
                      <li v-for="(listLine, lineIndex) in blockItem.items" :key="lineIndex">
                        {{ listLine }}
                      </li>
                    </ul>
                    <pre v-else-if="blockItem.type === 'code'" class="answer-code"><code>{{ blockItem.text }}</code></pre>
                    <p v-else class="prose">{{ blockItem.text }}</p>
                  </template>
                </div>

                <SourceList
                  :citations="turnItem.citations || []"
                  :show-locate="true"
                  @locate="locateCitation"
                />

                <div v-if="turnItem.follow_up_questions?.length" class="follow-up-bar">
                  <span class="tiny-label">推荐追问：</span>
                  <button
                    v-for="followUpQuestion in turnItem.follow_up_questions"
                    :key="followUpQuestion"
                    type="button"
                    class="follow-up-chip"
                    :disabled="!isLearningReady || !!activeTask"
                    @click="ask(followUpQuestion)"
                  >
                    {{ followUpQuestion }}
                  </button>
                </div>

              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- 底部悬浮输入框：默认采用 BM25 + 向量混合检索 (RRF)，保留召回证据条数调节。 -->
      <form class="chat-composer-dock" @submit.prevent="ask()">
        <div class="chat-composer-row">
          <textarea
            v-model="question"
            name="question"
            autocomplete="off"
            aria-label="你的问题"
            maxlength="2000"
            rows="2"
            placeholder="输入你的问题，支持继续追问（Enter 发送，Shift+Enter 换行）…"
            :disabled="!!activeTask"
            @keydown.enter.prevent="handleEnterSubmit"
          ></textarea>
          <button
            class="button primary"
            :disabled="!isLearningReady || !!activeTask || !question.trim()"
          >
            <span v-if="activeTask === 'qa'" class="spinner"></span
            ><AppIcon v-else name="send" :size="17" />
          </button>
        </div>
        <div class="chat-composer-footer">
          <span class="hybrid-tag">BM25 + 向量 · RRF 混合检索</span>
          <label class="composer-topk">
            证据 {{ topK }} 条
            <input
              v-model.number="topK"
              type="range"
              min="1"
              max="10"
              :disabled="!!activeTask"
            />
          </label>
          <span>{{ question.length }} / 2000</span>
        </div>
      </form>
    </div>

    <div
      v-if="showHistoryDrawer"
      class="drawer-backdrop"
      @click.self="showHistoryDrawer = false"
    >
      <aside class="side-drawer" aria-label="历史对话">
        <div class="side-drawer-header">
          <h3>本轮会话问答历史（{{ historyResult.total }}）</h3>
          <button
            type="button"
            class="icon-button"
            aria-label="关闭历史抽屉"
            @click="showHistoryDrawer = false"
          >
            <AppIcon name="close" :size="18" />
          </button>
        </div>
        <div class="side-drawer-body">
          <div v-if="!historyResult.items.length" class="empty-state">
            <p>当前会话暂无问答记录。</p>
          </div>
          <div
            v-for="historyItem in historyResult.items"
            :key="historyItem.id"
            class="history-drawer-item"
          >
            <strong>{{ historyItem.question }}</strong>
            <small>
              {{ dateLabel(historyItem.created_at) }} · 命中 {{ historyItem.citations?.length || 0 }} 条引用
            </small>
          </div>
          <a
            class="button secondary"
            href="#history"
            @click.exact.prevent="showHistoryDrawer = false; navigate('history')"
          >
            查看完整问答历史
          </a>
        </div>
      </aside>
    </div>
  </div>
</template>

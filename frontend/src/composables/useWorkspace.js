import { computed, inject, ref, watch } from "vue";
import { createFreshSessionId, historyPath, request, sessionId } from "../lib/api.js";
import { pages } from "../lib/presentation.js";

// 只共享跨页面的数据：当前知识库、课程目录、学习范围、会话与历史。
// 提问内容、总结结果、练习作答等局部交互状态由对应 View 自己管理。
export const workspaceKey = Symbol("learning-workspace");

// App.vue 提供同一个工作区，子组件读取它；不创建全局单例，避免多次挂载互相污染。
export function useWorkspace() {
  return inject(workspaceKey);
}

const DEFAULT_KB_ID = "hello_agents";

function readStoredKbId() {
  try {
    return globalThis.localStorage?.getItem("zhixu-kb-id") || DEFAULT_KB_ID;
  } catch {
    return DEFAULT_KB_ID;
  }
}

function writeStoredKbId(kbId) {
  try {
    globalThis.localStorage?.setItem("zhixu-kb-id", kbId);
  } catch {
    // 忽略无 localStorage 的测试或受限环境。
  }
}

export function createWorkspace() {
  const readPageIdFromHash = () =>
    pages.some((pageConfig) => pageConfig.id === location.hash.slice(1))
      ? location.hash.slice(1)
      : "qa";
  const currentPageId = ref(readPageIdFromHash());
  const activePageConfig = computed(() =>
    pages.find((pageConfig) => pageConfig.id === currentPageId.value),
  );
  const isSidebarOpen = ref(false);
  const serviceHealth = ref(null);
  const knowledgeBases = ref([]);
  const selectedKbId = ref(readStoredKbId());
  const courseInfo = ref(null);
  const chapters = ref([]);
  const isInitializing = ref(true);
  const activeTask = ref("");
  const errorMessage = ref("");
  const noticeMessage = ref("");
  const activeSessionId = ref(sessionId());
  const selectedChapterId = ref("");
  const selectedSectionId = ref("");
  const selectedChapter = computed(() =>
    chapters.value.find(
      (chapter) => chapter.chapter_id === selectedChapterId.value,
    ),
  );
  const activeKb = computed(() =>
    knowledgeBases.value.find((item) => item.kb_id === selectedKbId.value) || null,
  );
  const isLearningReady = computed(
    () =>
      chapters.value.length > 0 &&
      serviceHealth.value?.knowledge_base_ready &&
      serviceHealth.value?.generation_ready &&
      serviceHealth.value?.retrieval_ready,
  );

  // 问答写入后端历史；工作台、对话流与抽屉共用此快照。
  const historyResult = ref({ items: [], total: 0 });
  const historyOffset = ref(0);
  const isHistoryLoading = ref(false);
  const recentHistoryItems = ref([]);
  // 历史清空或新建对话时通过这个计数通知问答页清理局部状态。
  const historyClearCount = ref(0);

  const kbQuerySuffix = (kbId = selectedKbId.value) =>
    kbId && kbId !== DEFAULT_KB_ID
      ? `?kb_id=${encodeURIComponent(kbId)}`
      : "";

  const buildLearningScope = () => ({
    chapter_id: selectedChapterId.value || null,
    section_id: selectedSectionId.value || null,
  });

  const buildKbRequestScope = () => ({
    ...(selectedKbId.value && selectedKbId.value !== DEFAULT_KB_ID
      ? { kb_id: selectedKbId.value }
      : {}),
    ...buildLearningScope(),
  });

  function navigate(pageId, targetChapterId) {
    if (targetChapterId) selectedChapterId.value = targetChapterId;
    if (
      ["summary", "quiz"].includes(pageId) &&
      !selectedChapterId.value
    ) {
      selectedChapterId.value = chapters.value[0]?.chapter_id || "";
    }
    currentPageId.value = pageId;
    location.hash = pageId;
    isSidebarOpen.value = false;
    errorMessage.value = "";
    noticeMessage.value = "";
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  // 浏览器前进/后退也需要同步页面；地址监听由 App.vue 在挂载/卸载时注册/移除。
  function syncPageFromHash() {
    currentPageId.value = readPageIdFromHash();
    isSidebarOpen.value = false;
  }
  watch(currentPageId, (pageId) => {
    if (["summary", "quiz"].includes(pageId) && !selectedChapterId.value)
      selectedChapterId.value = chapters.value[0]?.chapter_id || "";
  });
  // 这里只维护章/节从属关系，各页面自行监听范围变化并清除自己的旧结果。
  watch(selectedChapterId, () => {
    selectedSectionId.value = "";
  });

  // 统一请求进度和中文提示，finally 让失败后的按钮也能恢复。
  async function runTask(taskName, taskAction) {
    activeTask.value = taskName;
    errorMessage.value = "";
    noticeMessage.value = "";
    try {
      await taskAction();
    } catch (requestError) {
      errorMessage.value = requestError.message;
    } finally {
      activeTask.value = "";
    }
  }

  async function loadKnowledgeBases() {
    try {
      const response = await request("/kbs");
      knowledgeBases.value = response.items || [];
    } catch {
      // 最小测试夹具不提供 /kbs 时忽略，不影响默认课程运行。
    }
  }

  async function loadHistory() {
    isHistoryLoading.value = true;
    try {
      const kbFilter =
        selectedKbId.value && selectedKbId.value !== DEFAULT_KB_ID
          ? selectedKbId.value
          : "";
      const historyResponse = await request(
        historyPath(activeSessionId.value, historyOffset.value, kbFilter),
      );
      historyResult.value = historyResponse;
      if (historyOffset.value === 0)
        recentHistoryItems.value = historyResponse.items.slice(0, 3);
    } catch (requestError) {
      errorMessage.value = requestError.message;
    } finally {
      isHistoryLoading.value = false;
    }
  }

  async function selectKnowledgeBase(kbId) {
    const nextKbId = kbId || DEFAULT_KB_ID;
    selectedKbId.value = nextKbId;
    writeStoredKbId(nextKbId);
    selectedChapterId.value = "";
    selectedSectionId.value = "";
    historyOffset.value = 0;
    await initializeWorkspace();
  }

  async function startNewConversation() {
    activeSessionId.value = createFreshSessionId();
    historyOffset.value = 0;
    historyResult.value = { items: [], total: 0 };
    recentHistoryItems.value = [];
    historyClearCount.value += 1;
    await loadHistory();
  }

  // 首屏先确认知识库，再取课程目录，最后读取当前会话历史；不填充演示数据。
  async function initializeWorkspace() {
    isInitializing.value = true;
    errorMessage.value = "";
    try {
      const suffix = kbQuerySuffix(selectedKbId.value);
      let healthResponse;
      try {
        healthResponse = await request(`/health${suffix}`);
      } catch (err) {
        if (selectedKbId.value !== DEFAULT_KB_ID) {
          selectedKbId.value = DEFAULT_KB_ID;
          writeStoredKbId(DEFAULT_KB_ID);
          healthResponse = await request("/health");
        } else {
          throw err;
        }
      }
      serviceHealth.value = healthResponse;

      if (!serviceHealth.value.knowledge_base_ready) {
        if (selectedKbId.value !== DEFAULT_KB_ID) {
          await loadKnowledgeBases();
          const courseResp = await request(`/course${kbQuerySuffix(selectedKbId.value)}`);
          courseInfo.value = courseResp;
          chapters.value = [];
          await loadHistory();
          return;
        }
        throw new Error(
          serviceHealth.value.reason || "课程知识库尚未就绪，请检查后端数据配置。",
        );
      }

      const activeSuffix = kbQuerySuffix(selectedKbId.value);
      const [courseResponse, chapterListResponse] = await Promise.all([
        request(`/course${activeSuffix}`),
        request(`/chapters${activeSuffix}`),
      ]);
      courseInfo.value = courseResponse;
      chapters.value = chapterListResponse.chapters;
      // 问答页默认全库检索（chapter_id 为空），只在总结和练习页自动选首章。
      if (["summary", "quiz"].includes(currentPageId.value) && !selectedChapterId.value) {
        selectedChapterId.value =
          chapterListResponse.chapters[0]?.chapter_id || "";
      }
      await loadKnowledgeBases();
      await loadHistory();
    } catch (requestError) {
      errorMessage.value = requestError.message;
    } finally {
      isInitializing.value = false;
    }
  }

  return {
    currentPageId,
    activePageConfig,
    isSidebarOpen,
    serviceHealth,
    knowledgeBases,
    selectedKbId,
    activeKb,
    courseInfo,
    chapters,
    isInitializing,
    activeTask,
    errorMessage,
    noticeMessage,
    activeSessionId,
    get currentSessionId() {
      return activeSessionId.value;
    },
    selectedChapterId,
    selectedSectionId,
    selectedChapter,
    isLearningReady,
    historyResult,
    historyOffset,
    isHistoryLoading,
    recentHistoryItems,
    historyClearCount,
    buildLearningScope,
    buildKbRequestScope,
    navigate,
    syncPageFromHash,
    runTask,
    loadKnowledgeBases,
    selectKnowledgeBase,
    startNewConversation,
    loadHistory,
    initializeWorkspace,
  };
}

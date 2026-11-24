import { computed, inject, ref, watch } from "vue";
import { historyPath, request, sessionId } from "../lib/api.js";
import { pages } from "../lib/presentation.js";

// 只共享跨页面的数据：课程、学习范围、会话、历史和公共提示。
// 提问内容、总结结果、练习作答等业务状态由对应 View 自己管理，不放进这里。
export const workspaceKey = Symbol("learning-workspace");

// App.vue 提供同一个工作区，子组件读取它；不创建全局单例，避免多次挂载互相污染。
export function useWorkspace() {
  return inject(workspaceKey);
}

export function createWorkspace() {
  const readPageIdFromHash = () =>
    pages.some((pageConfig) => pageConfig.id === location.hash.slice(1))
      ? location.hash.slice(1)
      : "overview";
  const currentPageId = ref(readPageIdFromHash());
  const activePageConfig = computed(() =>
    pages.find((pageConfig) => pageConfig.id === currentPageId.value),
  );
  const isSidebarOpen = ref(false);
  const serviceHealth = ref(null);
  const courseInfo = ref(null);
  const chapters = ref([]);
  const isInitializing = ref(true);
  const activeTask = ref("");
  const errorMessage = ref("");
  const noticeMessage = ref("");
  const currentSessionId = sessionId();
  const selectedChapterId = ref("");
  const selectedSectionId = ref("");
  const selectedChapter = computed(() =>
    chapters.value.find(
      (chapter) => chapter.chapter_id === selectedChapterId.value,
    ),
  );
  const isLearningReady = computed(
    () =>
      chapters.value.length > 0 &&
      serviceHealth.value?.knowledge_base_ready &&
      serviceHealth.value?.generation_ready &&
      serviceHealth.value?.retrieval_ready,
  );

  // 问答写入后端历史；工作台和历史页共用此快照，分页仍按每页十条计算。
  const historyResult = ref({ items: [], total: 0 });
  const historyOffset = ref(0);
  const isHistoryLoading = ref(false);
  const recentHistoryItems = ref([]);
  // 历史页通过这个计数通知问答页清除旧回答，避免页面间直接操作彼此的局部状态。
  const historyClearCount = ref(0);
  const buildLearningScope = () => ({
    chapter_id: selectedChapterId.value || null,
    section_id: selectedSectionId.value || null,
  });

  function navigate(pageId, targetChapterId) {
    if (targetChapterId) selectedChapterId.value = targetChapterId;
    if (pageId !== "qa" && !selectedChapterId.value)
      selectedChapterId.value = chapters.value[0]?.chapter_id || "";
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

  async function loadHistory() {
    isHistoryLoading.value = true;
    try {
      const historyResponse = await request(
        historyPath(currentSessionId, historyOffset.value),
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

  // 首屏先确认知识库，再取课程目录，最后读取当前会话历史；不填充演示数据。
  async function initializeWorkspace() {
    isInitializing.value = true;
    errorMessage.value = "";
    try {
      serviceHealth.value = await request("/health");
      if (!serviceHealth.value.knowledge_base_ready)
        throw new Error(
          serviceHealth.value.reason || "课程知识库尚未就绪，请检查后端数据配置。",
        );
      const [courseResponse, chapterListResponse] = await Promise.all([
        request("/course"),
        request("/chapters"),
      ]);
      courseInfo.value = courseResponse;
      chapters.value = chapterListResponse.chapters;
      if (!selectedChapterId.value)
        selectedChapterId.value =
          chapterListResponse.chapters[0]?.chapter_id || "";
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
    courseInfo,
    chapters,
    isInitializing,
    activeTask,
    errorMessage,
    noticeMessage,
    currentSessionId,
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
    navigate,
    syncPageFromHash,
    runTask,
    loadHistory,
    initializeWorkspace,
  };
}

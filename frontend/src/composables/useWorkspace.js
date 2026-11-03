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
  const readPage = () =>
    pages.some((p) => p.id === location.hash.slice(1))
      ? location.hash.slice(1)
      : "overview";
  const page = ref(readPage());
  const activePage = computed(() => pages.find((p) => p.id === page.value));
  const drawer = ref(false);
  const health = ref(null);
  const course = ref(null);
  const chapters = ref([]);
  const loading = ref(true);
  const busy = ref("");
  const error = ref("");
  const notice = ref("");
  const session = sessionId();
  const chapterId = ref("");
  const sectionId = ref("");
  const selectedChapter = computed(() =>
    chapters.value.find((chapter) => chapter.chapter_id === chapterId.value),
  );
  const ready = computed(
    () =>
      chapters.value.length > 0 &&
      health.value?.knowledge_base_ready &&
      health.value?.generation_ready &&
      health.value?.retrieval_ready,
  );

  // 问答写入后端历史；工作台和历史页共用此快照，分页仍按每页十条计算。
  const history = ref({ items: [], total: 0 });
  const historyOffset = ref(0);
  const historyLoading = ref(false);
  const recent = ref([]);
  // 历史页通过这个计数通知问答页清除旧回答，避免页面间直接操作彼此的局部状态。
  const historyCleared = ref(0);
  const scope = () => ({
    chapter_id: chapterId.value || null,
    section_id: sectionId.value || null,
  });

  function navigate(id, chapter) {
    if (chapter) chapterId.value = chapter;
    if (id !== "qa" && !chapterId.value)
      chapterId.value = chapters.value[0]?.chapter_id || "";
    page.value = id;
    location.hash = id;
    drawer.value = false;
    error.value = "";
    notice.value = "";
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  // 浏览器前进/后退也需要同步页面；地址监听由 App.vue 在挂载/卸载时注册/移除。
  function hashChanged() {
    page.value = readPage();
    drawer.value = false;
  }
  watch(page, (value) => {
    if (["summary", "quiz"].includes(value) && !chapterId.value)
      chapterId.value = chapters.value[0]?.chapter_id || "";
  });
  // 这里只维护章/节从属关系，各页面自行监听范围变化并清除自己的旧结果。
  watch(chapterId, () => {
    sectionId.value = "";
  });

  // 统一请求进度和中文提示，finally 让失败后的按钮也能恢复。
  async function run(task, action) {
    busy.value = task;
    error.value = "";
    notice.value = "";
    try {
      await action();
    } catch (e) {
      error.value = e.message;
    } finally {
      busy.value = "";
    }
  }

  async function loadHistory() {
    historyLoading.value = true;
    try {
      const data = await request(historyPath(session, historyOffset.value));
      history.value = data;
      if (historyOffset.value === 0) recent.value = data.items.slice(0, 3);
    } catch (e) {
      error.value = e.message;
    } finally {
      historyLoading.value = false;
    }
  }

  // 首屏先确认知识库，再取课程目录，最后读取当前会话历史；不填充演示数据。
  async function init() {
    loading.value = true;
    error.value = "";
    try {
      health.value = await request("/health");
      if (!health.value.knowledge_base_ready)
        throw new Error(
          health.value.reason || "课程知识库尚未就绪，请检查后端数据配置。",
        );
      const [info, list] = await Promise.all([
        request("/course"),
        request("/chapters"),
      ]);
      course.value = info;
      chapters.value = list.chapters;
      if (!chapterId.value)
        chapterId.value = list.chapters[0]?.chapter_id || "";
      await loadHistory();
    } catch (e) {
      error.value = e.message;
    } finally {
      loading.value = false;
    }
  }

  return {
    page,
    activePage,
    drawer,
    health,
    course,
    chapters,
    loading,
    busy,
    error,
    notice,
    session,
    chapterId,
    sectionId,
    selectedChapter,
    ready,
    history,
    historyOffset,
    historyLoading,
    recent,
    historyCleared,
    scope,
    navigate,
    hashChanged,
    run,
    loadHistory,
    init,
  };
}

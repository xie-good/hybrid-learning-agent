import { afterEach, beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { effectScope, nextTick } from "vue";
import { createWorkspace } from "../src/composables/useWorkspace.js";

// 用内存中的浏览器边界测试共享状态，不启动服务，也不访问真实会话历史。
const original = Object.fromEntries(
  ["fetch", "location", "window", "sessionStorage"].map((key) => [
    key,
    globalThis[key],
  ]),
);
let effects;
beforeEach(() => {
  const values = new Map();
  globalThis.location = { hash: "" };
  globalThis.window = { scrollTo() {} };
  globalThis.sessionStorage = {
    getItem: (key) => values.get(key),
    setItem: (key, value) => values.set(key, value),
  };
  effects = effectScope();
});
afterEach(() => {
  effects.stop();
  for (const [key, value] of Object.entries(original)) {
    if (value === undefined) delete globalThis[key];
    else globalThis[key] = value;
  }
});
const create = () => effects.run(createWorkspace);
const health = {
  status: "ok",
  knowledge_base_ready: true,
  generation_ready: true,
  retrieval_ready: true,
};
const chapters = [
  { chapter_id: "ch01", title: "第一章", sections: [] },
  { chapter_id: "ch02", title: "第二章", sections: [] },
];

test("章/节范围共享，切换章节清空小节；全部课程发送 null", async () => {
  const workspace = create();
  assert.deepEqual(workspace.buildLearningScope(), { chapter_id: null, section_id: null });
  workspace.selectedChapterId.value = "ch01";
  await nextTick();
  workspace.selectedSectionId.value = "ch01-s001";
  workspace.selectedChapterId.value = "ch02";
  await nextTick();
  assert.deepEqual(workspace.buildLearningScope(), { chapter_id: "ch02", section_id: null });
});

test("导航同步地址并收起抽屉；总结自动选择首章", async () => {
  const workspace = create();
  workspace.chapters.value = chapters;
  workspace.isSidebarOpen.value = true;
  workspace.errorMessage.value = "旧错误";
  workspace.navigate("summary");
  await nextTick();
  assert.equal(workspace.currentPageId.value, "summary");
  assert.equal(location.hash, "summary");
  assert.equal(workspace.selectedChapterId.value, "ch01");
  assert.equal(workspace.isSidebarOpen.value, false);
  assert.equal(workspace.errorMessage.value, "");
  workspace.navigate("qa");
  await nextTick();
  location.hash = "#summary";
  workspace.selectedChapterId.value = "";
  workspace.syncPageFromHash();
  await nextTick();
  assert.equal(workspace.selectedChapterId.value, "ch01");
  location.hash = "#unknown";
  workspace.syncPageFromHash();
  assert.equal(workspace.currentPageId.value, "qa");
});

test("旧练习地址回到问答页，不自动选择章节", () => {
  location.hash = "#quiz";
  const workspace = create();
  assert.equal(workspace.currentPageId.value, "qa");
  workspace.chapters.value = chapters;
  workspace.navigate("summary");
  workspace.selectedChapterId.value = "";
  location.hash = "#quiz";
  workspace.syncPageFromHash();
  assert.equal(workspace.currentPageId.value, "qa");
  assert.equal(workspace.selectedChapterId.value, "");
});

test("可用状态取决于章节和后端三项实际能力", () => {
  const workspace = create();
  workspace.serviceHealth.value = { ...health };
  assert.equal(workspace.isLearningReady.value, false);
  workspace.chapters.value = chapters;
  assert.equal(workspace.isLearningReady.value, true);
  for (const key of [
    "knowledge_base_ready",
    "generation_ready",
    "retrieval_ready",
  ]) {
    workspace.serviceHealth.value = { ...health, [key]: false };
    assert.equal(workspace.isLearningReady.value, false);
  }
});

test("请求成功或失败都会释放 activeTask，并用公共区域展示错误", async () => {
  const workspace = create();
  await workspace.runTask("qa", async () => {
    assert.equal(workspace.activeTask.value, "qa");
  });
  assert.equal(workspace.activeTask.value, "");
  await workspace.runTask("summary", async () => {
    throw new Error("生成失败");
  });
  assert.equal(workspace.activeTask.value, "");
  assert.equal(workspace.errorMessage.value, "生成失败");
});

test("初始化先检查知识库，再加载课程目录和同一会话的历史", async () => {
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(url);
    if (url === "/api/health") return Response.json(health);
    if (url === "/api/course") return Response.json({ name: "测试课程" });
    if (url === "/api/chapters") return Response.json({ chapters });
    return Response.json({ items: [], total: 0 });
  };
  const workspace = create();
  await workspace.initializeWorkspace();
  assert.equal(calls[0], "/api/health");
  assert.match(calls.at(-1), new RegExp(workspace.currentSessionId));
  assert.equal(workspace.courseInfo.value.name, "测试课程");
  assert.equal(workspace.selectedChapterId.value, "");
  assert.equal(workspace.isInitializing.value, false);
  assert.equal(workspace.isLearningReady.value, true);
});

test("知识库未就绪时停止初始化，保留原因且恢复加载状态", async () => {
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(url);
    return Response.json({
      knowledge_base_ready: false,
      reason: "课程数据缺失",
    });
  };
  const workspace = create();
  await workspace.initializeWorkspace();
  assert.deepEqual(calls, ["/api/health"]);
  assert.equal(workspace.errorMessage.value, "课程数据缺失");
  assert.equal(workspace.isInitializing.value, false);
});

test("只有第一页更新最近三条记录，翻页保留会话参数", async () => {
  const workspace = create();
  const items = Array.from({ length: 5 }, (_, index) => ({ id: `${index}` }));
  globalThis.fetch = async (url) => {
    const params = new URL(url, "http://localhost").searchParams;
    assert.equal(params.get("session_id"), workspace.currentSessionId);
    assert.equal(params.get("offset"), String(workspace.historyOffset.value));
    return Response.json({ items, total: 15 });
  };
  await workspace.loadHistory();
  assert.equal(workspace.recentHistoryItems.value.length, 3);
  workspace.historyOffset.value = 10;
  await workspace.loadHistory();
  assert.deepEqual(
    workspace.recentHistoryItems.value.map((item) => item.id),
    ["0", "1", "2"],
  );
  assert.equal(workspace.isHistoryLoading.value, false);
});

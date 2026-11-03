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
  assert.deepEqual(workspace.scope(), { chapter_id: null, section_id: null });
  workspace.chapterId.value = "ch01";
  await nextTick();
  workspace.sectionId.value = "ch01-s001";
  workspace.chapterId.value = "ch02";
  await nextTick();
  assert.deepEqual(workspace.scope(), { chapter_id: "ch02", section_id: null });
});

test("导航同步地址并收起抽屉；总结和练习自动选择首章", async () => {
  const workspace = create();
  workspace.chapters.value = chapters;
  workspace.drawer.value = true;
  workspace.error.value = "旧错误";
  workspace.navigate("summary");
  await nextTick();
  assert.equal(workspace.page.value, "summary");
  assert.equal(location.hash, "summary");
  assert.equal(workspace.chapterId.value, "ch01");
  assert.equal(workspace.drawer.value, false);
  assert.equal(workspace.error.value, "");
  location.hash = "#quiz";
  workspace.chapterId.value = "";
  workspace.hashChanged();
  await nextTick();
  assert.equal(workspace.chapterId.value, "ch01");
  location.hash = "#unknown";
  workspace.hashChanged();
  assert.equal(workspace.page.value, "overview");
});

test("可用状态取决于章节和后端三项实际能力", () => {
  const workspace = create();
  workspace.health.value = { ...health };
  assert.equal(workspace.ready.value, false);
  workspace.chapters.value = chapters;
  assert.equal(workspace.ready.value, true);
  for (const key of [
    "knowledge_base_ready",
    "generation_ready",
    "retrieval_ready",
  ]) {
    workspace.health.value = { ...health, [key]: false };
    assert.equal(workspace.ready.value, false);
  }
});

test("请求成功或失败都会释放 busy，并用公共区域展示错误", async () => {
  const workspace = create();
  await workspace.run("qa", async () => {
    assert.equal(workspace.busy.value, "qa");
  });
  assert.equal(workspace.busy.value, "");
  await workspace.run("quiz", async () => {
    throw new Error("生成失败");
  });
  assert.equal(workspace.busy.value, "");
  assert.equal(workspace.error.value, "生成失败");
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
  await workspace.init();
  assert.equal(calls[0], "/api/health");
  assert.match(calls.at(-1), new RegExp(workspace.session));
  assert.equal(workspace.course.value.name, "测试课程");
  assert.equal(workspace.chapterId.value, "ch01");
  assert.equal(workspace.loading.value, false);
  assert.equal(workspace.ready.value, true);
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
  await workspace.init();
  assert.deepEqual(calls, ["/api/health"]);
  assert.equal(workspace.error.value, "课程数据缺失");
  assert.equal(workspace.loading.value, false);
});

test("只有第一页更新最近三条记录，翻页保留会话参数", async () => {
  const workspace = create();
  const items = Array.from({ length: 5 }, (_, index) => ({ id: `${index}` }));
  globalThis.fetch = async (url) => {
    const params = new URL(url, "http://localhost").searchParams;
    assert.equal(params.get("session_id"), workspace.session);
    assert.equal(params.get("offset"), String(workspace.historyOffset.value));
    return Response.json({ items, total: 15 });
  };
  await workspace.loadHistory();
  assert.equal(workspace.recent.value.length, 3);
  workspace.historyOffset.value = 10;
  await workspace.loadHistory();
  assert.deepEqual(
    workspace.recent.value.map((item) => item.id),
    ["0", "1", "2"],
  );
  assert.equal(workspace.historyLoading.value, false);
});

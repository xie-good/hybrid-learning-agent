import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { parse, compileScript, compileTemplate } from "@vue/compiler-sfc";
import { compile } from "@vue/compiler-dom";
import * as Vue from "vue";
import { effectScope, ref, watch } from "vue";
import { retrievalLabels } from "../src/lib/presentation.js";

const source = fileURLToPath(new URL("../src/", import.meta.url));
const read = (name) => readFileSync(path.join(source, name), "utf8");

function templateElements(name) {
  const { descriptor } = parse(read(name));
  function walk(node) {
    return [
      ...(node.type === 1 ? [node] : []),
      ...(node.children || []).flatMap(walk),
    ];
  }
  return walk(descriptor.template.ast);
}

const attribute = (node, name) =>
  node.props.find((prop) => prop.type === 6 && prop.name === name)?.value?.content;

function renderElement(node, context) {
  // 只编译控件本身的属性与事件，图标等子组件不参与这些交互断言。
  const { code } = compile(node.loc.source, {
    mode: "function",
    nodeTransforms: [(element) => {
      if (element.type === 1) element.children = [];
    }],
  });
  return new Function("Vue", code)(Vue)(context, []);
}

test("根组件组装六个页面，缓存切页状态，不再实现业务函数", () => {
  const app = read("App.vue");
  for (const name of [
    "OverviewView",
    "KnowledgeView",
    "QuestionView",
    "SummaryView",
    "QuizView",
    "HistoryView",
  ])
    assert.ok(app.includes(`./views/${name}.vue`));
  assert.ok(app.includes("<KeepAlive>"));
  assert.doesNotMatch(
    app,
    /function (ask|summarize|generateQuiz|submitQuiz|deleteRecord|clearHistory)\(/,
  );
  assert.doesNotMatch(
    read("composables/useWorkspace.js"),
    /function (ask|summarize|generateQuiz|submitQuiz|resetQuiz)\(/,
  );
});

test("每个 Vue 组件均能独立解析和编译，且保留中文职责说明", () => {
  function walk(directory) {
    return readdirSync(directory, { withFileTypes: true }).flatMap((entry) =>
      entry.isDirectory()
        ? walk(path.join(directory, entry.name))
        : entry.name.endsWith(".vue")
          ? [path.join(directory, entry.name)]
          : [],
    );
  }
  for (const filename of walk(source)) {
    const text = readFileSync(filename, "utf8");
    const { descriptor, errors } = parse(text, { filename });
    assert.deepEqual(errors, [], filename);
    const script = compileScript(descriptor, { id: filename });
    const compiled = compileTemplate({
      source: descriptor.template.content,
      filename,
      id: filename,
      compilerOptions: { bindingMetadata: script.bindings },
    });
    assert.deepEqual(compiled.errors, [], filename);
    assert.match(
      descriptor.scriptSetup.content,
      /\/\/.*[\u3400-\u9fff]/,
      filename,
    );
  }
});

test("问答页提供原文伴读与证据数调节，默认固定走混合检索不提供模式切换", () => {
  const { descriptor } = parse(read("views/QuestionView.vue"));
  assert.match(descriptor.template.content, /v-model.number="topK"/);
  assert.match(descriptor.template.content, /class="reader-pane"/);
  assert.doesNotMatch(descriptor.template.content, /class="mode-switch"/);
  assert.equal(retrievalLabels.hybrid, "BM25 + 向量混合检索 (RRF)");
  assert.equal(retrievalLabels.vector, "向量语义检索");
});

test("问答每次发送均采用最新健康响应的默认检索方式，缺省为混合检索", async () => {
  const { descriptor } = parse(read("views/QuestionView.vue"));
  const script = descriptor.scriptSetup.content.replace(/^import[\s\S]*?from\s+["'][^"']+["'];\r?$/gm, "");
  const requests = [];
  let pending;
  const workspace = {
    serviceHealth: ref(null),
    courseInfo: ref(null),
    chapters: ref([]),
    isLearningReady: ref(true),
    activeTask: ref(""),
    selectedKbId: ref("hello_agents"),
    selectedChapterId: ref("ch01"),
    selectedSectionId: ref(""),
    historyResult: ref({ items: [], total: 0 }),
    historyClearCount: ref(0),
    errorMessage: ref(""),
    noticeMessage: ref(""),
    historyOffset: ref(0),
    buildLearningScope: () => ({ chapter_id: "ch01", section_id: null }),
    currentSessionId: "test-session",
    loadHistory: async () => {},
    startNewConversation: async () => {},
    navigate: () => {},
    runTask: (_, action) => {
      pending = action();
    },
  };
  const request = async (url, options = {}) => {
    if (url === "/qa") {
      requests.push({ url, body: options.body });
    }
    return { items: [] };
  };
  // 执行真实页面脚本，只替换工作区和 HTTP 边界，不复制问答逻辑。
  const setup = new Function(
    "computed",
    "nextTick",
    "onMounted",
    "ref",
    "watch",
    "useWorkspace",
    "request",
    "dateLabel",
    "modeLabel",
    "parseAnswerBlocks",
    "retrievalLabels",
    `${script}\nreturn { question, topK, ask };`,
  );
  const effects = effectScope();
  try {
    const page = effects.run(() =>
      setup(
        Vue.computed,
        Vue.nextTick,
        () => {},
        ref,
        watch,
        () => workspace,
        request,
        () => "",
        () => "",
        () => [],
        retrievalLabels,
      ),
    );
    page.topK.value = 7;
    for (const mode of [null, "hybrid", "vector", "hybrid"]) {
      page.question.value = "  智能体是什么？  ";
      workspace.serviceHealth.value = mode && {
        default_retrieval_mode: mode,
        retrieval_modes: ["bm25", "vector", "hybrid"],
      };
      page.ask();
      await pending;
      assert.deepEqual(requests.at(-1), {
        url: "/qa",
        body: {
          chapter_id: "ch01",
          section_id: null,
          question: "智能体是什么？",
          session_id: "test-session",
          retrieval_mode: mode || "hybrid",
          top_k: 7,
        },
      });
    }
  } finally {
    effects.stop();
  }
});

test("页内跳页入口使用真实链接，修饰键先于默认事件拦截处理", () => {
  for (const [name, count] of [
    ["OverviewView", 9],
    ["SummaryView", 2],
    ["HistoryView", 1],
  ]) {
    const links = templateElements(`views/${name}.vue`).filter((node) =>
      node.props.some((prop) =>
        prop.type === 7 && prop.name === "on" && /navigate\(/.test(prop.exp?.content),
      ),
    );
    assert.equal(links.length, count, name);
    for (const link of links) {
      assert.equal(link.tag, "a", name);
      assert.ok(
        attribute(link, "href") || link.props.some((prop) =>
          prop.type === 7 && prop.name === "bind" && prop.arg?.content === "href",
        ),
        `${name} 导航链接应有 href`,
      );
      const click = link.props.find((prop) => prop.name === "on" && prop.arg?.content === "click");
      const modifiers = click.modifiers.map((modifier) => modifier.content);
      assert.ok(modifiers.includes("exact"), name);
      assert.ok(modifiers.indexOf("exact") < modifiers.indexOf("prevent"), name);
    }
  }
});

test("真实链接普通点击走现有导航，Ctrl/Cmd/Shift 点击保留浏览器默认行为", () => {
  const link = templateElements("views/OverviewView.vue").find((node) =>
    attribute(node, "class") === "hero-secondary",
  );
  const navigations = [];
  const vnode = renderElement(link, { navigate: (id) => navigations.push(id) });
  assert.equal(vnode.props.href, "#qa");
  assert.equal(vnode.props.onAuxclick, undefined);
  for (const modifier of ["ctrlKey", "metaKey", "shiftKey", "altKey"]) {
    let prevented = false;
    vnode.props.onClick({
      [modifier]: true,
      preventDefault: () => { prevented = true; },
    });
    assert.equal(prevented, false, modifier);
    assert.deepEqual(navigations, [], modifier);
  }
  let prevented = false;
  vnode.props.onClick({ preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
  assert.deepEqual(navigations, ["qa"]);
});

test("学习表单显式命名并关闭自动填充，题量使用数字键盘", () => {
  for (const [name, tags, count] of [
    ["components/ScopeSelector.vue", ["select"], 2],
    ["views/OverviewView.vue", ["input"], 1],
    ["views/QuestionView.vue", ["textarea"], 1],
    ["views/QuizView.vue", ["input", "select"], 3],
  ]) {
    const controls = templateElements(name).filter((node) =>
      tags.includes(node.tag) && !["checkbox", "radio"].includes(attribute(node, "type")),
    );
    assert.equal(controls.length, count, name);
    for (const control of controls) {
      assert.ok(attribute(control, "name") || control.props.some((prop) =>
        prop.type === 7 && prop.name === "bind" && prop.arg?.content === "name",
      ), `${name} 表单控件应有 name`);
      assert.equal(attribute(control, "autocomplete"), "off", name);
      if (attribute(control, "type") === "number")
        assert.equal(attribute(control, "inputmode"), "numeric");
    }
  }
});

test("练习结果可被礼貌播报，连接与问题占位文案使用中文省略号", () => {
  const result = templateElements("views/QuizView.vue").find((node) =>
    attribute(node, "class")?.includes("result-panel"),
  );
  assert.equal(attribute(result, "aria-live"), "polite");
  const question = templateElements("views/QuestionView.vue").find((node) => node.tag === "textarea");
  assert.match(attribute(question, "placeholder"), /…$/);
  for (const name of ["AppTopbar", "LearningLayout"]) {
    const messages = read(`components/layout/${name}.vue`).match(/"[^"\r\n]*(?:请稍候|正在连接)[^"\r\n]*"/g);
    assert.ok(messages?.length, name);
    for (const message of messages) assert.match(message, /…"$/, name);
  }
});

test("未就绪的章节学习链接保持禁用，普通点击不导航", () => {
  const link = templateElements("views/OverviewView.vue").find((node) =>
    attribute(node, "class")?.includes("hero-primary"),
  );
  const navigations = [];
  for (const isLearningReady of [false, true]) {
    const vnode = renderElement(link, { isLearningReady, navigate: (id) => navigations.push(id) });
    assert.equal(vnode.props.href, isLearningReady ? "#summary" : undefined);
    assert.equal(vnode.props["aria-disabled"], isLearningReady ? undefined : "true");
    vnode.props.onClick({ preventDefault() {} });
    assert.deepEqual(navigations, isLearningReady ? ["summary"] : []);
  }
});

test("单条删除必须再次确认，取消或改选记录不会发送删除；清空闸保持勾选确认", async () => {
  const { descriptor } = parse(read("views/HistoryView.vue"));
  const script = descriptor.scriptSetup.content.replace(/^import .*;\r?$/gm, "");
  const requests = [];
  let pending;
  let reloads = 0;
  const workspace = {
    activeTask: ref(""),
    noticeMessage: ref(""),
    historyResult: ref({ items: [{ id: "record/b" }], total: 11 }),
    historyOffset: ref(10),
    currentSessionId: "test-session",
    loadHistory: async () => { reloads += 1; },
    runTask: (_, action) => { pending = action(); },
  };
  const setup = new Function(
    "ref", "onActivated", "useWorkspace", "request", "dateLabel", "modeLabel", "parseAnswerBlocks",
    `${script}\nreturn { pendingDeleteHistoryId, requestDelete };`,
  );
  const page = setup(
    ref, () => {}, () => workspace,
    async (url, options) => { requests.push({ url, ...options }); },
    () => "", () => "", () => [],
  );
  page.requestDelete("record/a");
  assert.equal(page.pendingDeleteHistoryId.value, "record/a");
  assert.deepEqual(requests, []);

  const cancel = templateElements("views/HistoryView.vue").find((node) =>
    node.props.some((prop) => prop.name === "on" && prop.exp?.content === "pendingDeleteHistoryId = null"),
  );
  const context = { pendingDeleteHistoryId: page.pendingDeleteHistoryId.value, historyItem: { id: "record/a" }, activeTask: "" };
  renderElement(cancel, context).props.onClick();
  page.pendingDeleteHistoryId.value = context.pendingDeleteHistoryId;
  assert.equal(page.pendingDeleteHistoryId.value, null);
  page.requestDelete("record/a");
  assert.deepEqual(requests, []);
  page.requestDelete("record/b");
  assert.deepEqual(requests, []);
  page.requestDelete("record/b");
  await pending;
  assert.deepEqual(requests, [{
    url: "/history/record%2Fb?session_id=test-session", method: "DELETE",
  }]);
  assert.equal(page.pendingDeleteHistoryId.value, null);
  assert.equal(workspace.historyOffset.value, 0);
  assert.equal(reloads, 1);
  assert.equal(workspace.noticeMessage.value, "该问答记录已删除。");

  const clear = templateElements("views/HistoryView.vue").find((node) =>
    node.props.some((prop) => prop.name === "on" && prop.exp?.content === "clearHistory"),
  );
  for (const [isClearHistoryConfirmed, activeTask, disabled] of [[false, "", true], [true, "", false], [true, "delete", true]])
    assert.equal(renderElement(clear, { isClearHistoryConfirmed, activeTask, clearHistory() {} }).props.disabled, disabled);
});

test("移动导航按钮名称与展开状态同步", () => {
  const button = templateElements("components/layout/AppTopbar.vue").find((node) =>
    attribute(node, "class") === "mobile-menu icon-button",
  );
  const context = { isSidebarOpen: false };
  let vnode = renderElement(button, context);
  assert.equal(vnode.props["aria-expanded"], false);
  assert.equal(vnode.props["aria-label"], "打开导航");
  vnode.props.onClick();
  vnode = renderElement(button, context);
  assert.equal(vnode.props["aria-expanded"], true);
  assert.equal(vnode.props["aria-label"], "关闭导航");
});

test("练习提交与待复习重答保留原有计分、自评和清空行为", async () => {
  const { descriptor } = parse(read("views/QuizView.vue"));
  const script = descriptor.scriptSetup.content.replace(/^import .*;\r?$/gm, "");
  const workspace = {
    isLearningReady: ref(true),
    activeTask: ref(""),
    errorMessage: ref(""),
    noticeMessage: ref(""),
    selectedKbId: ref("hello_agents"),
    selectedChapterId: ref("ch01"),
    selectedSectionId: ref(""),
    currentSessionId: "test-session",
    buildLearningScope: () => ({ chapter_id: "ch01", section_id: null }),
    runTask: async (_, action) => action(),
  };
  const { gradeChoices } = await import("../src/lib/api.js");
  const setup = new Function(
    "computed", "ref", "watch", "useWorkspace", "gradeChoices", "request",
    `${script}\nreturn {
      quizResult, answersByQuestionId, selfReviewsByQuestionId,
      isQuizSubmitted, multipleChoiceScore, reviewQuestionCount,
      submitQuiz, resetQuiz
    };`,
  );
  const effects = effectScope();
  try {
    const quizPage = effects.run(() =>
      setup(Vue.computed, ref, watch, () => workspace, gradeChoices, async () => {}),
    );
    quizPage.quizResult.value = {
      questions: [
        { question_id: "choice-correct", type: "multiple_choice", answer: "A" },
        { question_id: "choice-wrong", type: "multiple_choice", answer: "B" },
        { question_id: "short-review", type: "short_answer" },
        { question_id: "short-mastered", type: "short_answer" },
      ],
      citations: [{ chunk_id: "evidence-1" }],
    };
    quizPage.submitQuiz();
    assert.equal(quizPage.isQuizSubmitted.value, false);
    assert.equal(workspace.errorMessage.value, "请完成全部题目后再提交。");
    quizPage.answersByQuestionId.value = {
      "choice-correct": "A", "choice-wrong": "A",
      "short-review": "我的回答", "short-mastered": "已经理解",
    };
    quizPage.selfReviewsByQuestionId.value = {
      "short-review": "待复习", "short-mastered": "已掌握",
    };
    quizPage.submitQuiz();
    assert.equal(quizPage.isQuizSubmitted.value, true);
    assert.equal(workspace.errorMessage.value, "");
    assert.deepEqual(quizPage.multipleChoiceScore.value, { total: 2, correct: 1 });
    assert.equal(quizPage.reviewQuestionCount.value, 2);
    quizPage.resetQuiz(true);
    assert.deepEqual(
      quizPage.quizResult.value.questions.map((question) => question.question_id),
      ["choice-wrong", "short-review"],
    );
    assert.deepEqual(quizPage.quizResult.value.citations, [{ chunk_id: "evidence-1" }]);
    assert.deepEqual(quizPage.answersByQuestionId.value, {});
    assert.deepEqual(quizPage.selfReviewsByQuestionId.value, {});
    assert.equal(quizPage.isQuizSubmitted.value, false);
  } finally {
    effects.stop();
  }
});

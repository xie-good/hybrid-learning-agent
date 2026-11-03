import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { parse, compileScript, compileTemplate } from "@vue/compiler-sfc";

const source = fileURLToPath(new URL("../src/", import.meta.url));
const read = (name) => readFileSync(path.join(source, name), "utf8");

test("根组件只组装五个页面，缓存切页状态，不再实现业务函数", () => {
  const app = read("App.vue");
  for (const name of [
    "OverviewView",
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

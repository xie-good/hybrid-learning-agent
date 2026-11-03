import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// 只检查样式拆分边界，不启动浏览器，也不改变层叠顺序。
const source = fileURLToPath(new URL("../src/", import.meta.url));
const read = (name) => readFileSync(path.join(source, name), "utf8");
const stripComments = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "");
const importRule = /@import\s+["']([^"']+)["']\s*;/g;
const imports = (text) => [...stripComments(text).matchAll(importRule)].map((match) => match[1]);
const expected = [
  "./styles/base.css",
  "./styles/layout.css",
  "./styles/views/overview.css",
  "./styles/footer.css",
  "./styles/components/learning.css",
  "./styles/views/quiz.css",
  "./styles/views/history.css",
  "./styles/motion.css",
  "./styles/responsive.css",
  "./styles/accessibility.css",
];

test("主入口保留公共样式引用，样式入口只按原层叠顺序导入模块", () => {
  assert.match(read("main.js"), /import\s+["']\.\/style\.css["']\s*;/);
  const entry = read("style.css");
  assert.match(entry, /\/\*[\s\S]*?[\u3400-\u9fff][\s\S]*?\*\//);
  assert.deepEqual(imports(entry), expected);
  assert.equal(stripComments(entry).replace(importRule, "").trim(), "");
});

test("所有样式模块均且仅被入口导入一次，并保留非空内容与中文职责说明", () => {
  function walk(directory) {
    return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
      const filename = path.join(directory, entry.name);
      return entry.isDirectory() ? walk(filename) : entry.name.endsWith(".css") ? [filename] : [];
    });
  }
  const files = walk(path.join(source, "styles"));
  const names = files.map((filename) => `./${path.relative(source, filename).split(path.sep).join("/")}`);
  assert.deepEqual(imports(read("style.css")).sort(), names.sort());
  for (const filename of files) {
    const content = readFileSync(filename, "utf8");
    assert.ok(stripComments(content).trim(), `${filename} 应包含样式内容`);
    const comments = content.match(/\/\*[\s\S]*?\*\//g) || [];
    assert.ok(comments.some((comment) => /[\u3400-\u9fff]/.test(comment)), `${filename} 应说明中文职责`);
  }
});

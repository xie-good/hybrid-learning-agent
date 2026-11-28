import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// 检查样式模块边界和可访问性规则，不启动浏览器，也不改变层叠顺序。
const source = fileURLToPath(new URL("../src/", import.meta.url));
const read = (name) => readFileSync(path.join(source, name), "utf8");
const stripComments = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "");
const importRule = /@import\s+["']([^"']+)["']\s*;/g;
const imports = (text) => [...stripComments(text).matchAll(importRule)].map((match) => match[1]);
const expected = [
  "./styles/base.css",
  "./styles/layout.css",
  "./styles/views/overview.css",
  "./styles/views/knowledge.css",
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

test("主区保留键盘焦点环，移动抽屉隔离滚动，基础排版沿用主题", () => {
  assert.match(read("App.vue"), /<main\b[^>]*id="main"[^>]*tabindex="-1"/);
  const layout = read("styles/layout.css");
  assert.match(layout, /\.main-content:focus-visible\s*\{[^}]*outline:\s*3px solid #69ad9e;/);
  assert.match(layout, /\.main-content:focus-visible\s*\{[^}]*outline-offset:\s*-3px;/);
  const base = read("styles/base.css");
  assert.match(base, /:root\s*\{[^}]*color-scheme:\s*light;/);
  assert.match(base, /h1,\s*h2,\s*h3\s*\{[^}]*text-wrap:\s*balance;/);
  for (const selector of [".stat-card strong", ".pagination", ".quiz-question .tiny-label"])
    assert.ok(base.includes(selector));
  assert.match(base, /font-variant-numeric:\s*tabular-nums;/);
  const mobile = read("styles/responsive.css") + read("styles/accessibility.css");
  assert.match(mobile, /@media[^{}]+\{[\s\S]*?\.sidebar(?:\.open)?\s*\{[^}]*overscroll-behavior:\s*contain;/);
  assert.doesNotMatch(read("styles/views/overview.css") + mobile, /\.(?:learning-steps|chapter-card-bottom) button/);
});

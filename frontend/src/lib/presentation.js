// 页面配置按“主工作区（4 项，课程目录置顶）+ 学习工具（2 项）”组织，保持导航精简清晰。
export const primaryPages = [
  {
    id: "overview",
    title: "课程目录",
    icon: "grid",
    subtitle: "浏览知识库章节结构与学习路径。",
  },
  {
    id: "qa",
    title: "AI 问答",
    icon: "chat",
    subtitle: "混合检索资料库，支持多轮追问与原文溯源。",
  },
  {
    id: "knowledge",
    title: "知识库",
    icon: "layers",
    subtitle: "管理预置课程与个人上传文档，查看结构切片。",
  },
  {
    id: "history",
    title: "问答历史",
    icon: "history",
    subtitle: "回看多轮提问记录、检索过程与原文依据。",
  },
];

export const toolPages = [
  {
    id: "summary",
    title: "章节总结",
    icon: "book",
    subtitle: "提炼指定章节或文档的代表性要点与出处。",
  },
  {
    id: "quiz",
    title: "练习自测",
    icon: "quiz",
    subtitle: "按章节生成随堂测验，提交后自动批改单选并支持错题重练。",
  },
];

export const pages = [...primaryPages, ...toolPages];

// 原文摘录与模型生成在界面上明确区分。
export const modeLabel = (mode) =>
  mode === "llm" ? "混合检索 · 大模型讲解" : "混合检索 · 原文摘录";
export const retrievalLabels = {
  bm25: "BM25 关键词检索",
  vector: "向量语义检索",
  hybrid: "BM25 + 向量混合检索 (RRF)",
};

// 仅用于界面展示：去掉生成方式英文前缀，不改动后端原始字段。
const DISPLAY_PREFIXES = [
  ["原文摘录总结（extractive）：", "原文摘录总结："],
  ["原文摘录（extractive）：", "原文摘录："],
  ["代表性小节总结（llm，非逐段完整覆盖）：", "代表性小节总结（大模型生成，非逐段完整覆盖）："],
];
export const displayLearningText = (text) => {
  if (!text) return "";
  let value = String(text).trim();
  for (const [original, chinese] of DISPLAY_PREFIXES) {
    if (value.startsWith(original)) {
      value = chinese + value.slice(original.length);
      break;
    }
  }
  return value;
};

/**
 * 将结构化 Markdown 文本安全拆分为标题、列表、代码块和段落，
 * 避免使用 v-html，防止文档或模型输出引入脚本注入风险。
 */
export function parseAnswerBlocks(text) {
  const normalized = displayLearningText(text);
  if (!normalized) return [];
  const lines = normalized.split(/\r?\n/);
  const blocks = [];
  let paragraph = [];
  let listItems = [];
  let inCode = false;
  let codeLines = [];

  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push({ type: "paragraph", text: paragraph.join("\n") });
      paragraph = [];
    }
  };
  const flushList = () => {
    if (listItems.length) {
      blocks.push({ type: "list", items: listItems });
      listItems = [];
    }
  };

  for (const rawLine of lines) {
    const trimmed = rawLine.trim();
    if (trimmed.startsWith("```")) {
      flushParagraph();
      flushList();
      if (!inCode) {
        inCode = true;
        codeLines = [];
      } else {
        blocks.push({ type: "code", text: codeLines.join("\n") });
        inCode = false;
        codeLines = [];
      }
      continue;
    }
    if (inCode) {
      codeLines.push(rawLine);
      continue;
    }
    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }
    const headingMatch = trimmed.match(/^#{1,4}\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      blocks.push({ type: "heading", text: headingMatch[1].replace(/\*\*/g, "") });
      continue;
    }
    const listMatch = trimmed.match(/^(?:[-*•]|\d+[.)])\s+(.+)$/);
    if (listMatch) {
      flushParagraph();
      listItems.push(listMatch[1].replace(/\*\*([^*]+)\*\*/g, "$1"));
      continue;
    }
    flushList();
    paragraph.push(trimmed.replace(/\*\*([^*]+)\*\*/g, "$1"));
  }
  if (inCode && codeLines.length) {
    blocks.push({ type: "code", text: codeLines.join("\n") });
  }
  flushParagraph();
  flushList();
  return blocks;
}

// 卡片标题和历史时间的展示格式，不改变后端原始数据。
export const titleWithoutNumber = (title) =>
  title?.replace(/^第[一二三四五六七八九十百\d]+章\s*/, "");
export const dateLabel = (value) =>
  new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });

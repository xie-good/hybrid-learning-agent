// 页面配置和展示格式放在这里统一复用；不保存状态，也不发送请求。
export const pages = [
  {
    id: "overview",
    title: "学习工作台",
    icon: "grid",
    subtitle: "让每一次学习，都有迹可循。",
  },
  {
    id: "qa",
    title: "智能问答",
    icon: "chat",
    subtitle: "带着问题探索，让每一个答案都有教材依据。",
  },
  {
    id: "summary",
    title: "章节总结",
    icon: "summary",
    subtitle: "从章节脉络出发，建立自己的知识框架。",
  },
  {
    id: "quiz",
    title: "练习自测",
    icon: "quiz",
    subtitle: "用一次主动回忆，检验真正理解的知识。",
  },
  {
    id: "history",
    title: "会话历史",
    icon: "history",
    subtitle: "重访那些好问题，连接每一次新的理解。",
  },
];

// 原文摘录与模型生成在界面上明确区分。
export const modeLabel = (mode) =>
  mode === "llm" ? "模型生成 · 教材依据" : "教材原文摘录";
export const retrievalLabels = {
  bm25: "BM25 关键词检索",
  vector: "向量检索",
  hybrid: "混合检索",
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

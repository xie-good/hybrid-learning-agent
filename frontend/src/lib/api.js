/**
 * 浏览器与 FastAPI 的统一通信入口，页面只需要传路径和业务数据。
 * 例如 request('/qa', { method: 'POST', body: { question: '智能体是什么？' } })。
 * 开发/预览时 /api 由 Vite 代理；生产部署由 Web 服务配置同样的转发路径。
 */
export async function request(
  path,
  { method = "GET", body, timeout = 90000 } = {},
) {
  // 默认等候 90 秒，超时后主动中止；比无限等待更容易让用户判断何时重试。
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(`/api${path}`, {
      method,
      signal: controller.signal,
      // 有请求数据才声明 JSON；GET 与无请求体的 DELETE 不附加空的业务数据。
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    // 删除单条历史成功时返回 204，没有响应体；此时不能继续尝试读取 JSON。
    if (response.status === 204) return null;
    // 代理异常可能返回 HTML，解析失败后交给下方的统一错误分支处理。
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      // 保留后端给出的可读错误与请求编号，便于用户描述问题、开发者定位日志。
      const requestId = response.headers.get("X-Request-ID") || payload?.request_id;
      throw new Error(
        `${payload?.error?.message || "请求失败，请稍后重试。"}${requestId ? `（请求编号：${requestId}）` : ""}`,
      );
    }
    // 本项目的业务成功响应均为 JSON 对象；空值或数组说明服务契约不匹配。
    if (!payload || typeof payload !== "object" || Array.isArray(payload))
      throw new Error("服务响应格式异常。");
    return payload;
  } catch (error) {
    // 浏览器的技术异常转换成中文提示；业务层抛出的错误继续原样交给页面展示。
    if (error.name === "AbortError") throw new Error("请求超时，请稍后重试。");
    if (error instanceof TypeError)
      throw new Error("连接中断，请确认后端服务已启动。");
    throw error;
  } finally {
    // 请求提前完成或失败都要释放定时器，避免之后再触发一次无意义的中止。
    clearTimeout(timer);
  }
}

/** 当前标签页复用随机 UUID，刷新后仍能查到同一会话的问答历史。 */
export function sessionId(storage = sessionStorage) {
  const sessionStorageKey = "zhixu-session";
  let storedSessionId = storage.getItem(sessionStorageKey);
  // 只接受本客户端生成的 UUID v4 格式；缺失或损坏时重新生成，避免提交无效标识。
  // 这不是登录鉴权：session_id 是查询历史的会话参数，不代表已验证的用户身份。
  if (
    !/^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/i.test(
      storedSessionId || "",
    )
  ) {
    storedSessionId = crypto.randomUUID();
    storage.setItem(sessionStorageKey, storedSessionId);
  }
  return storedSessionId;
}

// 分页固定每页十条；URLSearchParams 统一编码参数，每次翻页都保留同一个会话。
export const historyPath = (currentSessionId, offset = 0) =>
  `/history?${new URLSearchParams({ session_id: currentSessionId, limit: 10, offset })}`;

// 只对选项键完全匹配的单选题计分；简答题的含义需要人工判断，不参与自动评分。
export function gradeChoices(questions, answers) {
  const choices = questions.filter(
    (question) => question.type === "multiple_choice",
  );
  return {
    total: choices.length,
    correct: choices.filter(
      (question) => answers[question.question_id] === question.answer,
    ).length,
  };
}

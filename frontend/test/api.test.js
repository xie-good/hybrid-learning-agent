import { afterEach, test } from "node:test";
import assert from "node:assert/strict";
import {
  historyPath,
  request,
  sessionId,
} from "../src/lib/api.js";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("问答通过同源 API 发送 JSON 与会话，不传入后端凭据", async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/qa");
    assert.equal(options.method, "POST");
    assert.equal(options.headers["Content-Type"], "application/json");
    assert.deepEqual(JSON.parse(options.body), {
      question: "智能体是什么？",
      session_id: "test-session",
    });
    assert.ok(options.signal instanceof AbortSignal);
    return Response.json({ answer: "教材原文", citations: [] });
  };
  assert.equal(
    (
      await request("/qa", {
        method: "POST",
        body: { question: "智能体是什么？", session_id: "test-session" },
      })
    ).answer,
    "教材原文",
  );
});

test("删除 204 空响应正常返回", async () => {
  globalThis.fetch = async () => new Response(null, { status: 204 });
  assert.equal(
    await request("/history/item?session_id=s", { method: "DELETE" }),
    null,
  );
});

test("结构化错误保留消息与请求编号，不回显原始响应", async () => {
  globalThis.fetch = async () =>
    Response.json(
      { error: { message: "教材尚未就绪" } },
      { status: 503, headers: { "X-Request-ID": "req-123" } },
    );
  await assert.rejects(request("/course"), /教材尚未就绪.*req-123/);
  globalThis.fetch = async () =>
    new Response("<html>private failure</html>", { status: 502 });
  await assert.rejects(request("/course"), {
    message: "请求失败，请稍后重试。",
  });
});

test("拒绝异常成功响应，连接失败提供可读消息", async () => {
  for (const payload of [null, [], "bad"]) {
    globalThis.fetch = async () => Response.json(payload);
    await assert.rejects(request("/health"), /服务响应格式异常/);
  }
  globalThis.fetch = async () => {
    throw new TypeError("fetch failed");
  };
  await assert.rejects(request("/health"), /连接中断/);
});

test("超时中止请求并显示可读消息", async () => {
  globalThis.fetch = (_, { signal }) =>
    new Promise((resolve, reject) => {
      signal.addEventListener("abort", () =>
        reject(new DOMException("Aborted", "AbortError")),
      );
    });
  await assert.rejects(request("/qa", { timeout: 5 }), /请求超时/);
});

test("会话使用随机 UUID，同一标签页刷新复用，损坏标识重新生成", () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key),
    setItem: (key, value) => values.set(key, value),
  };
  const id = sessionId(storage);
  assert.match(id, /^[\da-f-]{36}$/);
  assert.equal(sessionId(storage), id);
  values.set("zhixu-session", "bad-value");
  assert.notEqual(sessionId(storage), id);
});

test("历史翻页始终携带会话与页码", () => {
  const path = new URL(`http://localhost${historyPath("session-a", 20)}`);
  assert.equal(path.searchParams.get("session_id"), "session-a");
  assert.equal(path.searchParams.get("offset"), "20");
  assert.equal(path.searchParams.get("limit"), "10");
});

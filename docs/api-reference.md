# 课程学习助手 API v1 接口文档

更新：2026-11-28。契约来源为后端 Pydantic 模型与路由；静态机器文档见 [openapi.json](F:/桌面/毕设/docs/openapi.json)。默认 API 根地址为 `http://127.0.0.1:8000`。在线 Swagger：`/docs`，ReDoc：`/redoc`，OpenAPI：`/openapi.json`。初次阅读先看 [项目运行流程](F:/桌面/毕设/docs/project-runtime-flow.md)。

## 1. 当前实现与运行模式

- 共 **21 个 HTTP 操作（17 条路径）**，覆盖状态检查、多知识库与文档管理、PDF 按页纯白渲染、目录与原文来源、混合检索问答、章节总结及会话历史。
- 默认 `hybrid` 混合检索：`rank-bm25==0.2.2`（`BM25Okapi`）+ `numpy` 向量余弦召回，经 RRF（`k=60`）融合；内置词法与向量双保险门控（`VECTOR_MIN_SCORE=0.54`），并对指向当前资料的概览/总结类提问自动均匀抽样放行（`hit_type="overview"`）。
- `GENERATION_MODE` 支持 `extractive`（本地原文摘录）与 `llm`（Chat Completions 兼容大模型）；缺配置返回 `503`，超时返回 `504`，上游异常或引用校验失败返回 `502`。
- 多知识库支持预置课程 `hello_agents`（第 1—12 章）以及用户自定义知识库；上传文档严格限制为 **PDF (`.pdf`)、Markdown (`.md`)**，其中 PDF 自动转为 Markdown 精洗（跳过封面目录与习题），增删文档时增量复用已有切片与向量缓存。
- 问答历史按 `session_id`（UUID）持久化在 SQLite 中，前端存于标签页 `sessionStorage`；总结不写入问答历史。

## 2. 公共约定

- JSON 统一使用 UTF-8，请求头 `Content-Type: application/json`；文档上传使用 `multipart/form-data`。
- 所有响应附带 `X-Request-ID`；参数校验或业务失败返回统一错误结构：

```json
{
  "error": {
    "code": "invalid_page_num",
    "message": "页码必须大于等于 1。",
    "details": []
  },
  "request_id": "example-request-id"
}
```

常见状态码：`200` 成功、`201` 创建成功、`204` 删除成功无响应体、`404` 资源不存在、`409` 版本/重名冲突、`422` 参数或文件格式校验失败、`502` 上游模型错误、`503` 知识库/索引/配置未就绪、`504` 模型超时。

## 3. 接口总表（21 个操作）

| 分组 | 方法 | 路径 | 作用 |
|---|---|---|---|
| 状态 | GET | `/api/health` | 服务、预置语料、检索模式、生成配置与历史存储状态 |
| 知识库管理 | GET | `/api/kbs` | 列出预置课程与全部自定义知识库 |
| 知识库管理 | POST | `/api/kbs` | 新建自定义知识库（`name`、`description`） |
| 知识库管理 | DELETE | `/api/kbs/{kb_id}` | 删除指定自定义知识库（预置不可删） |
| 知识库管理 | GET | `/api/kbs/{kb_id}/documents` | 查看指定知识库内的文档列表与页数/切片数 |
| 知识库管理 | POST | `/api/kbs/{kb_id}/documents` | 上传 `.pdf`/`.md` 文档并增量构建索引 |
| 知识库管理 | DELETE | `/api/kbs/{kb_id}/documents/{doc_id}` | 移除文档并增量更新该知识库索引（0 次重算剩余向量） |
| 知识库管理 | GET | `/api/kbs/{kb_id}/documents/{doc_id}/source` | 在线内联预览或下载原始文档 |
| 知识库管理 | GET | `/api/kbs/{kb_id}/documents/{doc_id}/page/{page_num}` | 用 `pypdfium2` 把 PDF 指定页渲染为纯白底 PNG 图片 |
| 知识库管理 | GET | `/api/kbs/{kb_id}/chunks` | 分页浏览知识库切分后的文本块（支持 `chapter_id`、`limit`、`offset`） |
| 课程与来源 | GET | `/api/course` | 当前知识库基本信息与数据版本（支持 `?kb_id=`） |
| 课程与来源 | GET | `/api/chapters` | 当前知识库已入库章/节目录（支持 `?kb_id=`） |
| 课程与来源 | GET | `/api/chapters/{chapter_id}` | 指定章节详情与页码覆盖范围 |
| 课程与来源 | GET | `/api/sources/{chunk_id}` | 按文本块 ID 核对原文、章节与物理页码 |
| 课程与来源 | GET | `/api/course/source` | 返回预置教材原 PDF（支持 Range） |
| 问答 | POST | `/api/qa` | 多轮指代补全、混合检索证据、生成回答并写入历史 |
| 学习辅助 | POST | `/api/summary` | 生成指定章/节的代表性总结、要点与覆盖统计 |
| 会话历史 | GET | `/api/history` | 当前会话问答历史（倒序分页，支持 `kb_id` 过滤） |
| 会话历史 | GET | `/api/history/{record_id}` | 查询当前会话单条历史详情 |
| 会话历史 | DELETE | `/api/history/{record_id}` | 删除当前会话单条历史 |
| 会话历史 | DELETE | `/api/history` | 清空当前会话全部历史 |

## 4. 核心数据结构说明

### Citation（统一原文引用与混合检索命中明细）

| 字段 | 类型 | 说明 |
|---|---|---|
| `citation_id` | integer | 响应内 1 起算编号，对应正文 `[1]` |
| `chunk_id` | string | 稳定文本块标识 |
| `text` | string | 清洗后的文档原文片段 |
| `source_file` | string | 来源文件名 |
| `chapter_id` / `chapter_title` | string | 所属章节或文档标识与标题 |
| `section_id` / `section_title` | string | 所属小节标识与标题 |
| `page_start` / `page_end` | integer | 原文档物理起止页码（从 1 开始） |
| `score` | float | 最终排序得分（混合模式下为 RRF 分数） |
| `hit_type` | string \| null | 命中来源：`both`（双路共同命中）、`bm25`、`vector`、`overview`（全文概览抽样） |
| `bm25_rank` | integer \| null | BM25 词法召回排名 |
| `vec_score` | float \| null | 向量语义余弦相似度 |
| `rrf_score` | float \| null | RRF 融合得分 |

### POST /api/qa 请求与响应要点

请求体：

```json
{
  "kb_id": "hello_agents",
  "question": "ReAct 的核心流程是什么？",
  "chapter_id": null,
  "section_id": null,
  "session_id": "d7d96af0-8afb-4d73-8bf2-213031cd9fea",
  "retrieval_mode": "hybrid",
  "top_k": 5,
  "debug": false
}
```

- `kb_id` 可选，默认预置课程 `hello_agents`。
- 响应包含 `answer`、`citations`、`insufficient_evidence`、`retrieval_mode`、`generation_mode`、`rewritten_question`（多轮指代补全后的问题）、`follow_up_questions`（推荐追问列表）、`history_id`、`session_id`、`latency_ms`、`dataset_version`、`request_id`。

### GET /api/kbs/{kb_id}/documents/{doc_id}/page/{page_num}

- 将 PDF 指定物理页（`page_num >= 1`）按 `scale=1.6` 实时渲染为纯白底 `image/png` 返回。
- 若非 PDF 文档返回 `422`（`not_a_pdf`）；页码越界返回 `404`（`page_not_found`）。

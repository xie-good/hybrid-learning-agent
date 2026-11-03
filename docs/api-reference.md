# 课程学习助手 API v1 接口文档

更新：2026-10-25。契约来源为后端 Pydantic 模型与路由；静态机器文档见同目录 `openapi.json`。默认 API 根地址为 `http://127.0.0.1:8000`。在线 Swagger：`/docs`，ReDoc：`/redoc`，OpenAPI：`/openapi.json`。

## 1. 当前实现与运行模式

- 13 个 HTTP 操作覆盖课程、章/节、原文/PDF、问答、总结、练习和当前会话历史；业务不再使用 501 占位。
- 默认 `bm25 + extractive`：中文字符词项和英文标识符参与真实 BM25 检索；回答、总结与阅读练习依据实际教材原文形成，响应明确标记 `generation_mode=extractive`，不冒充模型推理。
- `GENERATION_MODE=llm` 接入配置的 Chat Completions 兼容服务。缺少配置返回 503；超时 504；上游错误或引用/结构验证失败 502。测试使用模拟上游，不等于真实云服务已验收。
- `vector`/`hybrid` 要求真实 Embedding 服务配置和匹配数据版本的离线向量索引；未就绪返回 503。`hybrid` 使用 BM25、向量及 RRF；本次没有将 Reranker 模型列为已实现功能。
- 数据仍限第 1—12 章。图片/OCR和跨页代码重建不在当前语料处理能力内，引用携带 `review_flags`。
- 历史只保存问答结果；总结与练习不写入问答历史。会话 UUID 是访问该会话记录的凭据，保存在浏览器会话中，不是账号登录体系。

## 2. 公共约定

- JSON 使用 UTF-8；请求头 `Content-Type: application/json`。
- 所有响应附 `X-Request-ID`。可传入 1—64 位字母/数字/点/下划线/短横线组成的值，其余自动生成。
- JSON 请求禁止额外字段。字符串去除首尾空白后校验；题量和 top_k 要求整数。
- `chapter_id` 格式 `ch01`；`section_id` 格式 `ch01-s001`。格式正确但不存在的范围返回 404；章/节冲突返回 422。
- `session_id` 为 UUID。问答省略该值时创建新会话，前端应保存响应值并在后续请求中复用；历史接口必须携带。
- `latency_ms` 为服务端检索/生成及响应组装耗时，不包括浏览器网络时间，问答不包括 SQLite 插入阶段。
- `dataset_version` 绑定清洗规则和文本块版本；PDF 页码从 1 开始。
- 默认允许 `http://127.0.0.1:8501` 和 `http://localhost:8501` 的跨域请求，可用 `CORS_ORIGINS` 调整。

### 统一错误结构

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "请求参数校验失败。",
    "details": [{"field": "body.question", "message": "String should have at least 1 character", "type": "string_too_short"}]
  },
  "request_id": "example-request-id"
}
```

`details` 仅在参数错误时出现，不回显整个请求、密钥或异常堆栈。状态码：200 成功、204 删除成功无响应体、206 PDF 范围内容、404 资源不存在或不属于当前会话、409 原 PDF 与数据版本冲突、422 参数错误、500 内部异常、502 模型返回错误、503 数据/索引/配置/存储未就绪、504 模型超时。

## 3. 接口总表

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/health` | 服务与语料、生成配置、历史存储状态 |
| GET | `/api/course` | 固定课程、来源和版本 |
| GET | `/api/chapters` | 已入库章/节目录 |
| GET | `/api/chapters/{chapter_id}` | 章节详情与覆盖范围 |
| GET | `/api/sources/{chunk_id}` | 一条原文及章节、页码 |
| GET | `/api/course/source` | 固定原 PDF；支持页码定位与 Range |
| POST | `/api/qa` | 课程问答与历史写入 |
| POST | `/api/summary` | 指定章/节总结 |
| POST | `/api/quiz` | 练习题、答案、解析与引用 |
| GET | `/api/history` | 当前会话历史分页 |
| GET | `/api/history/{record_id}` | 当前会话单条记录 |
| DELETE | `/api/history/{record_id}` | 删除当前会话单条记录 |
| DELETE | `/api/history` | 清空当前会话记录 |

## 4. 状态、目录与来源

### GET /api/health

存活检查始终返回 200。`status=ok|degraded`；字段包括 `stage`、`knowledge_base_ready`、`dataset_version`、`chunk_count`、`retrieval_modes`、`default_retrieval_mode`、`retrieval_ready`、`generation_mode`、`generation_ready`、`history_ready` 和 `reason`。缺少或损坏语料、默认检索模式不可用、模型配置不全或历史存储失败时为 degraded。`generation_ready` 只说明本地模式可用或模型配置齐全，不执行远程探活；向量可用状态同样不承诺外部服务连通。

### GET /api/course

返回 `course_id`、`name`、`description`、`source_file`、`dataset_version`、`chapter_count`、`chunk_count` 及覆盖/来源可用信息。不接受用户指定课程或任意文件路径。

### GET /api/chapters 与 GET /api/chapters/{chapter_id}

目录返回 `{course_id,dataset_version,chapters:[...]}`。章节包含 `chapter_id,title,page_start,page_end,sections`；小节至少包含 `section_id,title,page_start`，并提供可计算的覆盖信息。章节详情直接返回一个章节对象。按节检索可直接传 `section_id`；如果同时传 `chapter_id`，二者必须一致。

### Citation：统一原文引用结构

| 字段 | 类型 | 说明 |
|---|---|---|
| citation_id | integer | 当前响应内 1 起算编号，对应正文 `[1]` |
| chunk_id | string | 稳定文本块标识，可查询来源接口 |
| text | string | 教材清洗后的原文，不是模型生成内容 |
| source_file | string | 来源文件名 |
| chapter_id / chapter_title | string | 章节标识和名称 |
| section_id / section_title | string/null | 小节标识和名称 |
| page_start / page_end | integer | 原 PDF 物理页范围 |
| source_url | string/null | 固定 PDF 接口加 `#page=N` 的相对链接 |
| score | number/null | 检索分数，不是答案正确率 |
| review_flags | string[] | 图表、低文本量等覆盖提示 |

`GET /api/sources/{chunk_id}` 返回一个 Citation。`GET /api/course/source` 返回 `application/pdf`；只服务环境配置或报告登记且通过来源 SHA256 校验的 PDF。文件不存在或来源不匹配时返回错误，不读取请求携带的路径。前端定位形式为 `http://127.0.0.1:8000/api/course/source#page=10`；`#page` 由浏览器 PDF 阅读器处理。

## 5. POST /api/qa

```json
{
  "question": "什么是智能体？",
  "chapter_id": "ch01",
  "section_id": null,
  "session_id": "6a69df9b-695b-4f6c-ae41-e582408791ee",
  "retrieval_mode": "bm25",
  "top_k": 5,
  "debug": false
}
```

| 字段 | 必填 | 默认/范围 |
|---|---|---|
| question | 是 | 去除首尾空白后 1—2000 字符 |
| chapter_id | 否 | null，全课程；也可按 section_id 定位章节 |
| section_id | 否 | null，不限定小节 |
| session_id | 否 | 服务端生成 UUID |
| retrieval_mode | 否 | 服务端 `DEFAULT_RETRIEVAL_MODE`，出厂 bm25；允许 bm25/vector/hybrid |
| top_k | 否 | 5，1—10 |
| debug | 否 | false |

返回字段：`answer,citations,retrieval_mode,generation_mode,insufficient_evidence,scope,dataset_version,latency_ms,request_id,session_id,history_id,debug`。

`scope` 为 `{chapter_id,section_id}`。没有词项命中时仍返回 200，但 `insufficient_evidence=true,citations=[]`，说明证据不足，不调用模型凭空补全；BM25 得分不证明语义充分性，实际回答质量仍需独立评测。普通响应 `debug=null`；调试模式提供实际检索阶段信息，不表示配置了尚未启用的模型精排。

响应中的 `[N]` 必须映射到本次 citations 的编号。编号校验只是结构约束，不等于自动验证所有事实支持关系。

## 6. POST /api/summary

请求：`{"chapter_id":"ch01","section_id":null}`。`chapter_id` 必填，`section_id` 可选。

返回：`summary,key_points,citations,coverage,generation_mode,scope,dataset_version,latency_ms,request_id`。`coverage` 记录总小节/块数、实际选取数、覆盖的小节和代表性采样说明；总结不把少量证据声称为整章逐字覆盖。模型模式与摘录模式均显式标识。

## 7. POST /api/quiz

```json
{
  "chapter_id": "ch01",
  "section_id": null,
  "count": 5,
  "question_types": ["short_answer", "multiple_choice"],
  "difficulty": "medium"
}
```

- `count` 默认 5，范围 1—10。
- `question_types` 默认 `["short_answer"]`；允许 `short_answer` 和 `multiple_choice`，列表不可为空、不可重复，题量不可小于所选题型数量。
- `difficulty` 为 `easy|medium|hard`，默认 medium。默认摘录模式生成原文阅读理解/填空题；难度是题目组织参数，不代表经过教学测量的难度等级。
- 返回 `questions,citations,generation_mode,scope,dataset_version,latency_ms,request_id`。
- 每题包含 `question_id,type,question,options,answer,explanation,citation_ids`。单选选项为 `[{key,text},...]`，answer 为正确选项 key；简答 options 为空列表，answer 为参考答案。
- UI 默认折叠答案和解析。后端同时返回答案供本地自测；这不是隐藏答案的考试系统。
- 所选章/节的可用原文不足以生成请求题量时返回 422；不会静默少出题或编造内容。

## 8. 会话历史

所有历史操作必须附 `?session_id=UUID`。

- 列表：`GET /api/history?session_id=UUID&limit=20&offset=0`。limit 1—100，offset ≥0，按创建时间倒序；返回 `{items,total,limit,offset}`。
- 单条：`GET /api/history/{record_id}?session_id=UUID`。
- 删除一条：`DELETE /api/history/{record_id}?session_id=UUID`，成功 204 无响应体。
- 清空当前会话：`DELETE /api/history?session_id=UUID`，返回 `{"deleted":数量}`。

历史对象包含 `id,session_id,question,answer,citations,retrieval_mode,generation_mode,scope,dataset_version,insufficient_evidence,created_at,latency_ms,request_id`。`created_at` 是 UTC ISO 时间。持久化使用 SQLite；重启后同一 UUID 可查询，其他 UUID 查询/删除该记录返回 404。历史内容不自动拼入下次模型提示词。

## 9. 配置与启动

完整变量见项目根目录 `.env.example`；现有 `.env` 不会被安装或测试覆盖。`DATABASE_PATH` 默认 `data/runtime/history.sqlite3`；模型密钥仅服务端读取，前端只配置 `BACKEND_URL` 和超时。

访问 localhost、127.0.0.0/8、::1 的前端 HTTP 和模型 HTTP 客户端使用直连，避免 Windows 系统代理拦截本机服务；远程目标仍遵循部署环境的代理配置。

```powershell
Set-Location 'F:/桌面/毕设'
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
# 另一个终端：
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -m streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501
```

前端封装、方法映射、页面状态和错误处理见 `frontend-api.md`。离线预处理和索引构建不暴露为网络写入接口；没有上传、账号或管理员 API。

## 10. 测试

```powershell
Set-Location 'F:/桌面/毕设'
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -B -m unittest discover -s tests -v
```

测试使用真实合成 PDF、隔离 SQLite、TestClient、MockTransport 和 Streamlit AppTest；覆盖参数错误、来源与范围、引用、模型错误/超时、会话隔离、删除、并发写入、持久化和前端交互。具体执行次数与结果记录在交付验证报告中。

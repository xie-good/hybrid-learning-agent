# 知序 · 基于混合检索增强生成的课程学习助手

基于 FastAPI + Vue 3 + SQLite + NumPy 的混合检索增强课程学习与文档伴读应用。内置 Hello-Agents 第 1—12 章预置课程语料，并支持自建多知识库上传 **PDF (`.pdf`) / Markdown (`.md`)** 文档，提供双栏无黑边原文伴读、混合检索问答、章节总结与会话历史管理。前端组件说明见 [Vue 工作台](F:/桌面/毕设/frontend/README.md)。

## 第一次读这个项目

文档对齐日期：2026-11-28。推荐阅读顺序：

1. [项目运行流程与阅读路线](F:/桌面/毕设/docs/project-runtime-flow.md)：理解前后端数据流与核心模块协作。
2. [实际目录与职责](F:/桌面/毕设/目录.md)：速查所有源码、测试与文档目录。
3. [Vue 前端说明](F:/桌面/毕设/frontend/README.md) 与 [前端接口文档](F:/桌面/毕设/docs/frontend-api.md)：查看 5 个页面与伴读工作台实现。
4. [后端接口文档](F:/桌面/毕设/docs/api-reference.md) 与 [OpenAPI 契约](F:/桌面/毕设/docs/openapi.json)：核对 21 个接口字段与错误码。

## 当前已实现功能

- **21 个 HTTP 接口（17 条路径）**：完整覆盖多知识库管理、PDF 按页纯白渲染、文档切块浏览、课程目录、混合检索问答、章节总结与会话历史；附带 Swagger、ReDoc 与静态 OpenAPI 文档。
- **混合检索与双保险门控**：默认采用 `BM25Okapi`（`rank-bm25==0.2.2`）+ `numpy` 矩阵加速向量检索 + RRF（`k=60`）融合；内置词法与向量双保险门控（`VECTOR_MIN_SCORE = 0.54`），课程外问题准确拒答，同时支持“总结这份资料/整体框架”等概览类提问的均匀抽样放行。
- **多知识库与增量入库**：内置 Hello-Agents 第 1—12 章（67 节、759 块），支持新建自定义知识库并上传 **PDF (`.pdf`)、Markdown (`.md`)** 文档；PDF 自动转为 Markdown 精洗（跳过封面目录、剔除习题并保留物理页码锚点），增删文档时增量复用已有切片与向量缓存（删文档 0 次调用 Embedding）。
- **双栏无黑边文档伴读工作台**：Vue 3 浅蓝白统一主题，包含 5 个页面（课程目录、AI 问答、知识库、问答历史、章节总结）。AI 问答页左侧通过后端 `pypdfium2` 按页渲染纯白高清 PNG（无浏览器黑边，支持输页码直达与缩放），中间提供可拖拽分割条（28%–68%），右侧展示混合检索命中来源（双路共同命中 / BM25 / 向量 / 全文概览抽样）及分数明细，支持一键定位左侧原文。
- **多轮问答与大模型讲解**：支持 `extractive`（本地原文摘录）与 `llm`（Chat Completions 兼容大模型）双模式；支持多轮指代补全、推荐追问与严格引用编号校验。
- **章节总结**：提供单行控制栏、代表性要点、证据覆盖统计与原文引用，并支持跳转到本章问答。
- **会话隔离历史**：SQLite 按随机 `session_id`（UUID）与 `kb_id` 持久化问答历史，支持分页查看、单条删除与确认清空。
- **自动化测试与开发评测**：后端与前端配有自动化测试，运行命令见下文；120 题前六章开发集混合检索 `Recall@5` 达 `0.9804`，课程外拒答率 `100%`。

> **待完成（对照任务书后续目标）**：将预置 Hello-Agents 语料从第 1—12 章扩展至第 1—15 章；构建 80 题独立验证/盲测集并产出三组对照实验报告；补充问答流式输出（SSE）。

历史参考资料：[20 题历史种子基线](F:/桌面/毕设/docs/evaluation/bm25-seed-baseline.md) · [120 题开发集说明](F:/桌面/毕设/data/evaluation/hello-agents-ch01-06-v1/README.md) · [历史产品需求 V1.2](F:/桌面/毕设/docs/product/prd-v1.2.md)。

## 安装与配置

Windows PowerShell：

```powershell
Set-Location 'F:/桌面/毕设'
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -m pip install -r requirements.txt
# 按需将 .env.example 的变量合并进本地 .env；不要把真实密钥提交到仓库。
```

核心配置位于 `F:/桌面/毕设/backend/config.py`，分为 5 组（14 个字段）：

| 分组 | 作用 | 默认运行需要填写吗 |
| --- | --- | --- |
| 数据路径（4 项） | 预处理目录、历史数据库、索引目录、教材 PDF | 不需要；默认路径或预处理报告提供来源 |
| 运行模式（2 项） | 原文摘录/模型生成、BM25/向量/混合检索 | 不需要；默认 `extractive` + `hybrid` |
| 大模型服务（3 项） | 地址、模型名、密钥 | 启用 `GENERATION_MODE=llm` 时填写 |
| 向量模型服务（3 项） | 地址、模型名、密钥 | 默认混合检索需要；密钥按服务要求填写 |
| 通用参数（2 项） | 模型超时（1—180s）、允许跨域的前端地址 | 不需要；已有默认值 |

启用大模型生成与向量服务示例（写入 `.env`）：

```dotenv
DEFAULT_RETRIEVAL_MODE=hybrid
GENERATION_MODE=llm
LLM_BASE_URL=https://api.example.com/v1
LLM_MODEL=your-chat-model
LLM_API_KEY=your-api-key
EMBEDDING_BASE_URL=https://api.example.com/v1
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_API_KEY=your-api-key
MODEL_TIMEOUT=60
```

## 本地启动

后端（端口 8000）：

```powershell
Set-Location 'F:/桌面/毕设'
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

前端（端口 5173，另开终端）：

```powershell
Set-Location 'F:/桌面/毕设/frontend'
npm ci
npm run dev
```

- 前端工作台：[http://127.0.0.1:5173](http://127.0.0.1:5173)（Node.js 20.19+ 或 22.12+）
- Swagger 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- ReDoc 文档：[http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- 健康检查：[http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

## 接口一览

完整字段与示例见 [后端接口文档](F:/桌面/毕设/docs/api-reference.md)、[前端接口文档](F:/桌面/毕设/docs/frontend-api.md) 与 [OpenAPI JSON](F:/桌面/毕设/docs/openapi.json)。

```text
GET    /api/health                                        服务与语料/模型就绪状态
GET    /api/kbs                                           列出预置课程与自定义知识库
POST   /api/kbs                                           新建自定义知识库
DELETE /api/kbs/{kb_id}                                   删除自定义知识库
GET    /api/kbs/{kb_id}/documents                         查看知识库内文档列表
POST   /api/kbs/{kb_id}/documents                         上传 PDF/MD 并增量构建索引
DELETE /api/kbs/{kb_id}/documents/{doc_id}                移除文档并增量更新索引
GET    /api/kbs/{kb_id}/documents/{doc_id}/source         在线查看或下载原文档
GET    /api/kbs/{kb_id}/documents/{doc_id}/page/{page_num} 按页渲染 PDF 为纯白 PNG
GET    /api/kbs/{kb_id}/chunks                            分页浏览切分后的文本块
GET    /api/course                                        当前知识库基本信息与版本
GET    /api/chapters                                      已入库章/节目录
GET    /api/chapters/{chapter_id}                         章节详情与覆盖范围
GET    /api/sources/{chunk_id}                            核对单条原文与页码
GET    /api/course/source                                 预置课程原 PDF
POST   /api/qa                                            混合检索问答与历史写入
POST   /api/summary                                       生成指定章/节总结
GET    /api/history                                       当前会话历史分页
GET    /api/history/{record_id}                           当前会话单条历史
DELETE /api/history/{record_id}                           删除单条历史
DELETE /api/history                                       清空当前会话历史
```

## 测试与离线预处理

运行全部自动化测试：

```powershell
# 后端测试
Set-Location 'F:/桌面/毕设'
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -m unittest discover -s tests -p 'test_*.py'

# 前端测试
Set-Location 'F:/桌面/毕设/frontend'
npm test
```

离线预处理与索引重建详见 [知识正文预处理说明](F:/桌面/毕设/docs/preprocessing.md)；同步静态 OpenAPI 契约运行：

```powershell
Set-Location 'F:/桌面/毕设'
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -m tools.export_openapi
```

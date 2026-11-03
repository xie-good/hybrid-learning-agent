# 课程学习助手

基于 FastAPI + Vue 3（HTML / CSS / JavaScript）的预置课程学习应用。课程资料为 Hello-Agents，第 1—12 章已完成离线清洗和分块。现在提供真实可调用的课程、章节、来源、问答、总结、练习和会话历史接口。新前端说明见 [Vue 工作台](F:/桌面/毕设/frontend/README.md)，原 Streamlit 页面保留供回退。

## 当前功能

- 13 个 HTTP 操作；Swagger、ReDoc 与静态 OpenAPI 文档。
- 默认使用 `rank-bm25==0.2.2` 的 `BM25Okapi` 检索 + 有引用的原文摘录，无模型密钥也可运行。
- BM25 增加证据充分性门控；关键词只零散出现在教材中时明确返回证据不足，不把课程外问题包装成有依据的答案。
- 可选 Chat Completions 兼容大模型；缺配置、超时、无效引用和无效结构都有明确错误。
- 可选真实 Embedding 向量索引及 RRF 混合召回；未配置时只报告 BM25 可用，不冒充语义向量检索。vector/hybrid 当前是实验能力，须单独完成课程外拒答评测后才可成为默认模式。
- 五个 Vue 页面通过同源 `/api` 连接后端；响应式学习工作台提供课程搜索和“总结—提问—练习—回顾”路径，保留教材引用、会话隔离与提交后展示答案。
- 练习提交前隐藏答案；提交后单选题客观计分，简答题只提供参考答案和自评，不冒充语义自动评分。
- SQLite 持久化问答历史，以随机会话 UUID 隔离；不建设账号、上传、自建课程或管理员后台。
- 请求/响应模型、统一错误、请求编号、分页和参数校验。
- 已建立 20 题版本化种子评测和逐题报告，用于开发期防回归；60—100 题人工正式评测、Reranker、OCR 和跨页代码重建仍是后续工作。

当前执行基线：[产品需求 V1.2](F:/桌面/毕设/docs/product/prd-v1.2.md) · [问题定义](F:/桌面/毕设/docs/product/problem-statement.md) · [优先级计划](F:/桌面/毕设/docs/product/prioritized-action-plan.md) · [种子评测](F:/桌面/毕设/docs/evaluation/bm25-seed-baseline.md)

## 安装和配置

Windows PowerShell：

```powershell
Set-Location 'F:/桌面/毕设'
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -m pip install -r requirements.txt
# 按需将 .env.example 的变量合并进现有 .env；不要覆盖已有配置。
```

默认模式为 `GENERATION_MODE=extractive`、`DEFAULT_RETRIEVAL_MODE=bm25`。响应与界面会显示原文摘录模式，不将其标记为大模型回答。

### 配置代码怎么看

配置集中在 `F:/桌面/毕设/backend/config.py`，14 个字段按职责分组，不需要全部填写：

| 分组 | 作用 | 默认运行需要填写吗 |
| --- | --- | --- |
| 数据路径（4 项） | 预处理目录、历史数据库、索引目录、教材 PDF | 不需要；默认路径或预处理报告提供来源 |
| 运行模式（2 项） | 原文摘录/模型生成、BM25/向量/混合检索 | 不需要；默认原文摘录 + BM25 |
| 大模型服务（3 项） | 地址、模型名、密钥 | 仅启用模型生成时填写 |
| 向量模型服务（3 项） | 地址、模型名、密钥 | 仅构建向量索引时填写 |
| 通用参数（2 项） | 模型超时、允许跨域的前端地址 | 不需要；已有默认值 |

代码把“默认值”和“读取环境”分开：

```python
from backend.config import Settings

defaults = Settings()                  # 只使用默认值，不读取环境变量
config = Settings.from_env()           # 服务启动：读取环境变量并校验
test_config = Settings(model_timeout=5)  # 测试或显式传入配置
```

FastAPI 应用工厂和离线索引入口已统一使用 `Settings.from_env()`；显式传入的配置优先。`.env` 在配置模块导入时加载，进程环境变量优先于 `.env`，没有设置的字段使用代码默认值。修改 `.env` 后重启进程；`from_env()` 不重复读取文件。

路径留空使用默认值，相对路径从项目根目录定位；`SOURCE_PDF` 留空时从预处理报告定位来源。`MODEL_TIMEOUT` 必须大于 0 且不超过 180 秒。`CORS_ORIGINS` 用英文逗号分隔，忽略空白项，留空表示不允许跨域访问。

使用模型生成时设置：

```dotenv
GENERATION_MODE=llm
LLM_BASE_URL=http://127.0.0.1:1234/v1
LLM_MODEL=your-model-name
LLM_API_KEY=
MODEL_TIMEOUT=30
```

本地兼容服务允许空密钥；云服务按实际要求填写。密钥只存服务端环境，不进入前端、接口响应、测试产物或仓库。模型输出的引用编号和结构会被校验，教材对结论的实际支持程度仍需人工评测。

## 启动

后端：

```powershell
Set-Location 'F:/桌面/毕设'
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

前端（另一个终端）：

```powershell
Set-Location 'F:/桌面/毕设/frontend'
npm ci
npm run dev
```

- 前端：[http://127.0.0.1:5173](http://127.0.0.1:5173)（Node.js 20.19+ 或 22.12+）
- Swagger：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- ReDoc：[http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- 健康检查：[http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

服务启动时加载并验证已有语料；不重跑 PDF 清洗，不自动下载模型或调用模型 API。数据缺失/损坏时健康状态为 degraded，相关业务返回 503；其他异常通过统一错误对象说明。

## 接口

完整说明：[后端接口文档](F:/桌面/毕设/docs/api-reference.md) · [前端接口文档](F:/桌面/毕设/docs/frontend-api.md) · [OpenAPI JSON](F:/桌面/毕设/docs/openapi.json)

```text
GET    /api/health
GET    /api/course
GET    /api/chapters
GET    /api/chapters/{chapter_id}
GET    /api/sources/{chunk_id}
GET    /api/course/source
POST   /api/qa
POST   /api/summary
POST   /api/quiz
GET    /api/history
GET    /api/history/{record_id}
DELETE /api/history/{record_id}
DELETE /api/history
```

Vue 前端通过 Vite 的 `/api` 代理访问后端，默认 http://127.0.0.1:8000；可在 Vite 进程环境或 `frontend/.env.local` 设置 `BACKEND_URL`，请求超时 90 秒。随机会话标识由前端生成，存于当前标签页的 sessionStorage 并在刷新后复用；历史接口要求 session_id。旧 Streamlit HTTP 客户端仍使用根目录的 `BACKEND_URL` / `BACKEND_TIMEOUT`，可按原启动方式回退。

## 数据与离线入口

### rank_bm25 分支：先用小样本验证

先处理教材物理第 10—20 页（11 页），输出到独立目录，不覆盖完整语料。保留原有中文/代码分词、章节过滤与引用；评分使用库默认的 `k1=1.5`、`b=0.75`、`epsilon=0.25` 和 IDF，不再使用原手写的正值平滑 IDF。证据门控同步采用库的 IDF，版本为 `rank-bm25-cohesive-evidence-v2`；原有完整语料评测结论需要重新验证。

```powershell
Set-Location 'F:/桌面/毕设'
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -m pip install -r 'F:/桌面/毕设/requirements.txt'
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -m pipeline.run_preprocess --source 'F:/下载/Hello-Agents-V1.0.3-20260717.pdf' --output 'F:/桌面/毕设/data/processed/hello-agents-rank-bm25-sample' --start-page 10 --end-page 20
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -m pipeline.build_index --processed-dir 'F:/桌面/毕设/data/processed/hello-agents-rank-bm25-sample' --output 'F:/桌面/毕设/data/indexes/hello-agents-rank-bm25-sample' --mode bm25
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -m tools.evaluate_retrieval --cases 'F:/桌面/毕设/data/evaluation/hello-agents-rank-bm25-sample/cases.jsonl' --processed-dir 'F:/桌面/毕设/data/processed/hello-agents-rank-bm25-sample' --index-dir 'F:/桌面/毕设/data/indexes/hello-agents-rank-bm25-sample' --top-k 5 --output 'F:/桌面/毕设/tmp/rank_bm25-change-20261029/sample-evaluation.json'
```

该样本固定为 8 题（5 题有依据、3 题超出样本范围），仅用于开发验证，不代表完整教材效果；本次没有根据结果调整门控阈值。首次构建不加 `--force`；确认重建同名预处理或索引产物时，在对应命令后添加 `--force`。前后端联调前，在启动后端的终端设置：

```powershell
$env:PROCESSED_DIR='F:/桌面/毕设/data/processed/hello-agents-rank-bm25-sample'
$env:INDEX_DIR='F:/桌面/毕设/data/indexes/hello-agents-rank-bm25-sample'
$env:DEFAULT_RETRIEVAL_MODE='bm25'
$env:GENERATION_MODE='extractive'
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

极小语料下库的默认分数可能为零或负值；候选过滤检查实际词元命中，不把“分数大于零”当作命中的必要条件。旧手写 BM25 的磁盘索引会因算法标识不匹配而跳过，服务仍可从当前语料创建库索引。

### 完整语料入口

预处理保留第 1—12 章（物理第 10—560 页）的知识讲解、知识小结与教学示例，排除习题、课后练习、独立参考文献和讨论交流等非知识正文。过滤发生在清洗和分块之前，跨页习题不会进入检索；同页习题之前的知识内容仍保留。具体规模、排除记录和数据版本以 `report.json` 为准，规则见[预处理说明](F:/桌面/毕设/docs/preprocessing.md)。原 PDF 通过预处理报告的来源路径或 `SOURCE_PDF` 配置定位，下载前验证 SHA256；未配置/文件缺失时阅读链接不可用，文本引用仍可查看。

```powershell
Set-Location 'F:/桌面/毕设'
# 当前目录已有产物，使用 --force 按知识正文规则重建；首次处理时可省略。
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -m pipeline.run_preprocess --source 'F:/下载/Hello-Agents-V1.0.3-20260717.pdf' --force
# 数据版本变化后同步重建索引，并重启后端以加载新快照。
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -m pipeline.build_index --processed-dir 'F:/桌面/毕设/data/processed/hello-agents' --output 'F:/桌面/毕设/data/indexes/hello-agents' --mode bm25 --force
```

向量/混合模式须先配置 `EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`、可选密钥，并显式使用 `--mode vector` 或 `--mode hybrid` 构建索引。构建时会发送课程文本给所配置的 Embedding 服务；普通启动和默认测试不会外呼。更换数据或模型应重新构建，不混用版本。

默认 SQLite：`F:/桌面/毕设/data/runtime/history.sqlite3`。数据和运行库不进入版本管理。默认摘录总结使用分节代表性原文并返回 coverage；练习属于有出处的阅读自测，不伪装为经过测量的高质量考试题库。

## 验证

```powershell
Set-Location 'F:/桌面/毕设'
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -B -m unittest discover -s tests -v

# 用完整语料评测库版本，另存结果，不覆盖原手写实现的历史基线。
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -B -m tools.evaluate_retrieval `
  --cases 'F:/桌面/毕设/data/evaluation/hello-agents-v1/cases.jsonl' `
  --mode bm25 --top-k 5 10 `
  --output 'F:/桌面/毕设/docs/evaluation/bm25-rank-bm25-baseline.json'
```

测试使用真实合成 PDF、真实本地检索与隔离 SQLite；外部模型用 MockTransport，前端用 AppTest。20 题种子集只证明当前冻结样本上的检索、拒答和引用回归结果，不代替正式人工评测。实际部署需结合固定模型服务做连通性和回答质量验收。

Vue 前端另在 `F:/桌面/毕设/frontend` 执行 `npm test` 与 `npm run build`；上述 AppTest 保留验证旧 Streamlit 页面。

项目源码的说明性注释和文档字符串统一使用中文；技术标识符、协议字段、教材原文及测试样例保持原义。测试同时检查中文注释与知识正文过滤规则。

## 代码职责

- `F:/桌面/毕设/backend/api/routes.py`：HTTP 调度与响应契约。
- `F:/桌面/毕设/backend/services/corpus.py`：版本/哈希验证、目录与原文。
- `F:/桌面/毕设/backend/services/retrieval.py`：检索与可选融合。
- `F:/桌面/毕设/backend/services/generation.py`：摘录/模型回答及引用验证。
- `F:/桌面/毕设/backend/services/learning.py`：总结与练习。
- `F:/桌面/毕设/backend/storage/history.py`：SQLite 会话历史。
- `F:/桌面/毕设/frontend/api_client.py`：与 UI 分离的 HTTP 调用封装。
- `F:/桌面/毕设/tools/evaluate_retrieval.py`：冻结问题集的检索效果评测入口。

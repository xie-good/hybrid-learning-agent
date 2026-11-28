# Vue 前端接口接入文档

更新：2026-11-28。适用当前 Vue 3 双栏伴读工作台与 FastAPI `/api` 接口；描述以实际源码为准。

先读 [项目运行流程](F:/桌面/毕设/docs/project-runtime-flow.md) 建立全局认识，Vue 组件与样式结构见 [前端说明](F:/桌面/毕设/frontend/README.md)，完整后端字段见 [后端接口文档](F:/桌面/毕设/docs/api-reference.md)。

## 1. 运行方式与代理配置

浏览器运行 Vue 3 页面，通过原生 `fetch` 访问同源 `/api`，由 Vite 开发/预览代理转发至 FastAPI（默认 `http://127.0.0.1:8000`）。

| 配置 | 当前实现 |
|---|---|
| 后端代理地址 | 默认 `http://127.0.0.1:8000`；可通过 `BACKEND_URL` 或 `frontend/.env.local` 覆盖 |
| 浏览器请求路径 | 固定同源 `/api`；页面不硬编码后端主机 |
| 请求超时 | `request()` 默认 `90000` ms，可在调用处通过 `timeout` 覆盖（如出题请求为 `120000` ms） |
| 模型密钥 | 仅存于后端环境变量，不进入前端构建产物或浏览器 |

## 2. 核心文件与职责

| 文件 | 职责 |
|---|---|
| [main.js](F:/桌面/毕设/frontend/src/main.js) | 创建 Vue 应用并加载 `style.css` |
| [App.vue](F:/桌面/毕设/frontend/src/App.vue) | 公共布局、宽屏伴读容器、6 页装配、`KeepAlive` 缓存 |
| [useWorkspace.js](F:/桌面/毕设/frontend/src/composables/useWorkspace.js) | 知识库列表与切换、章/节范围、会话 UUID、历史快照与公共提示 |
| [api.js](F:/桌面/毕设/frontend/src/lib/api.js) | `fetch` 封装、超时、错误格式化、会话 UUID 与单选计分 |
| [OverviewView.vue](F:/桌面/毕设/frontend/src/views/OverviewView.vue) | 课程目录（侧栏置顶）：概览卡、统计、章节搜索与快捷跳转 |
| [QuestionView.vue](F:/桌面/毕设/frontend/src/views/QuestionView.vue) | 双栏伴读问答：左侧 PDF 按页纯白渲染/文本切片 + 可拖动分割条 + 右侧混合检索问答与随堂巩固 |
| [KnowledgeView.vue](F:/桌面/毕设/frontend/src/views/KnowledgeView.vue) | 多知识库管理、PDF/Word/Markdown 上传、原文档查看与文本块浏览 |
| [SummaryView.vue](F:/桌面/毕设/frontend/src/views/SummaryView.vue) | 章节总结：单行控制栏、要点、证据覆盖与闭环跳转 |
| [QuizView.vue](F:/桌面/毕设/frontend/src/views/QuizView.vue) | 练习自测：横排胶囊题型配置、作答、提交判分、自评与错题重练 |
| [HistoryView.vue](F:/桌面/毕设/frontend/src/views/HistoryView.vue) | 当前会话历史分页回看、单条删除与确认清空 |
| [SourceList.vue](F:/桌面/毕设/frontend/src/components/SourceList.vue) | 混合检索引用折叠卡（双路/BM25/向量/概览标签、分数明细、左侧原文定位） |
| [InlineQuizCard.vue](F:/桌面/毕设/frontend/src/components/InlineQuizCard.vue) | 问答页随堂出题巩固卡片 |

## 3. 接口调用映射

页面统一调用 `request(path, { method, body, timeout })`（`path` 不含 `/api` 前缀）；文档上传使用 `FormData` 直发 `/api/kbs/{kb_id}/documents`；PDF 页面预览直接将 `<img :src>` 指向 `/api/kbs/{kb_id}/documents/{doc_id}/page/{page_num}`。

| 调用路径 | 方法 | 用途 |
|---|---|---|
| `/health` | GET | 知识库、默认检索模式、生成配置与历史存储状态 |
| `/kbs`、`/kbs/{kb_id}` | GET / POST / DELETE | 查询、新建与删除自定义知识库 |
| `/kbs/{kb_id}/documents`、`/kbs/{kb_id}/documents/{doc_id}` | GET / POST / DELETE | 查看文档列表、上传 PDF/Word/MD、删除文档 |
| `/kbs/{kb_id}/documents/{doc_id}/source` | GET | 在新标签页打开原始文档 |
| `/kbs/{kb_id}/documents/{doc_id}/page/{page_num}` | GET | 按页获取 PDF 纯白底 PNG 图片，用于伴读区无黑边渲染 |
| `/kbs/{kb_id}/chunks` | GET | 分页浏览文本块（伴读区非 PDF 文档预览与知识库切片查看共用） |
| `/course`、`/chapters` | GET | 读取当前选中知识库的元信息与章/节目录（携带 `kb_id`） |
| `/qa` | POST | 混合检索问答并写入历史 |
| `/summary` | POST | 生成指定章/节总结 |
| `/quiz`、`/quiz/from-qa` | POST | 生成章节练习或基于问答原文的随堂巩固题 |
| `/history`、`/history/{record_id}` | GET / DELETE | 当前会话历史分页查询、单条删除与清空 |

## 4. 核心交互契约要点

- **问答（`POST /api/qa`）**：默认固定使用健康检查返回的 `default_retrieval_mode`（`hybrid`），不提供前端模式切换按钮；保留召回证据条数 `top_k`（1—10）调节。页面自动根据当前文档标题和真实章节动态生成 3 条推荐提问。
- **双栏伴读与原文定位**：点击 `SourceList` 中的「在左侧原文定位」时，PDF 文档自动跳转到 `source.page_start` 并渲染对应页面 PNG；Word/Markdown 文档自动滚动并高亮对应 `chunk_id` 卡片。
- **章节总结与练习自测**：`SummaryView` 将「生成总结」按钮内嵌在 `ScopeSelector` 右上角；`QuizView` 在提交前隐藏答案，提交后单选题自动客观计分、简答题对照参考答案自评，并支持仅重练答错和标记“待复习”的题目。
- **状态管理**：`App.vue` 通过 `provide/inject` 共享 `useWorkspace()`，配合 `<KeepAlive>` 缓存页面状态；浏览器刷新后复用 `sessionStorage` 中的 `session_id` 并重读问答历史。

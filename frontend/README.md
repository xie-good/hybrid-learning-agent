# 知序 · Vue 课程学习工作台

新界面使用 Vue 3 单文件组件、HTML 模板、原生 CSS 与 JavaScript，以 Vite 构建。不依赖 Streamlit；原有 Python 页面保持原样，供回退使用。

## 先看懂，再修改

### 组件结构与职责

```text
frontend/src/
├── App.vue                         # 根布局、页面装配、工作区生命周期
├── views/
│   ├── OverviewView.vue            # 工作台：目录搜索、展开和章节入口
│   ├── QuestionView.vue            # 问答：输入、检索选项、回答及引用
│   ├── SummaryView.vue             # 总结：生成、要点及证据覆盖
│   ├── QuizView.vue                # 自测：出题、作答、提交、评分与重做
│   └── HistoryView.vue             # 历史：刷新、分页、删除与清空确认
├── components/
│   ├── layout/
│   │   ├── AppSidebar.vue          # 侧栏导航、使用说明、手机抽屉
│   │   ├── AppTopbar.vue           # 面包屑、连接状态、手机菜单按钮
│   │   └── LearningLayout.vue      # 三个学习页共用的范围选择、提示与占位
│   ├── ScopeSelector.vue           # 公共章节/小节选择器
│   ├── AppIcon.vue                 # SVG 图标
│   └── SourceList.vue              # 教材原文及 PDF 页码
├── composables/useWorkspace.js     # 课程、学习范围、会话与历史等跨页状态
├── lib/
│   ├── api.js                      # HTTP、超时、错误、会话 UUID、单选计分
│   └── presentation.js             # 页面配置、生成方式文案及展示格式
├── main.js                         # 浏览器执行入口
├── style.css                       # 仅声明样式模块的加载顺序
└── styles/
    ├── base.css                    # 主题变量、标签默认值、公共按钮与焦点
    ├── layout.css                  # 侧栏、顶栏、主体与页面标题
    ├── footer.css                  # 公共页脚
    ├── components/learning.css     # 学习表单、提示、结果、教材引用与总结覆盖
    ├── views/
    │   ├── overview.css            # 工作台、课程目录与CSS书本插画
    │   ├── quiz.css                # 自测题型、选项和作答反馈
    │   └── history.css             # 历史记录、分页和清空确认
    ├── motion.css                  # 请求进度动画
    ├── responsive.css              # 屏幕断点与减少动态效果
    └── accessibility.css           # 最后加载的可读性与移动导航覆盖
```

上面的目录树相对于 `F:/桌面/毕设/frontend/src`。不是只把模板移到新文件：每个页面同时持有自己的业务状态与操作。例如题量、题型、作答、提交和重做都在 `QuizView.vue`，而不再留在根组件。

### 建议按这个顺序阅读

1. `F:/桌面/毕设/frontend/index.html` → `F:/桌面/毕设/frontend/src/main.js`：浏览器如何找到入口并挂载 Vue。
2. `F:/桌面/毕设/frontend/src/App.vue`：如何组装公共区域、提供共享工作区，并选择当前页面。
3. `F:/桌面/毕设/frontend/src/composables/useWorkspace.js`：哪些数据跨页面共享，如何初始化课程和历史。
4. 按需要阅读 `F:/桌面/毕设/frontend/src/views` 下的某个页面，跟随其表单事件查找同文件中的业务函数。
5. `F:/桌面/毕设/frontend/src/lib/api.js`：请求如何发出、超时和错误如何展示。
6. `F:/桌面/毕设/frontend/src/components/SourceList.vue` 与 `F:/桌面/毕设/frontend/src/style.css`：来源展示与样式布局。

`.vue` 文件的 `<script setup>` 管理本组件的逻辑，`<template>` 管理本组件的 HTML；样式按职责拆到 `styles`，由 `style.css` 统一加载。问答、总结、练习复用同一套学习表单、结果与引用样式，所以它们放在公共的 `components/learning.css`，不复制到各页面。

本次拆分保留全局作用域，不同时引入 `<style scoped>` 或页面懒加载；已有跨组件选择器仍能生效。入口中的导入顺序是原文件的规则顺序，`responsive.css` 在基础样式之后，`accessibility.css` 最后加载。不要因为相同断点重复出现就随意合并：末尾的手机导航可见性和文字大小规则有意覆盖前面的设置。

### 状态怎样在组件间流动

- `App.vue` 创建一次工作区并通过 `provide` 提供；公共区域和页面用 `useWorkspace()` 读取相同的课程、章/节范围、会话 UUID、历史快照及公共提示。共享范围不是把全部页面业务再搬进一个“大组件”。
- 各页面的输入和结果仍是本地 `ref`：问答页持有 `qa`，总结页持有 `summary`，自测页持有 `quiz` 和作答。页面之间不直接修改彼此的局部数据。
- 根组件用 `KeepAlive` 缓存已访问页面，所以切换页面不会丢掉目录搜索、输入内容或本轮作答；各学习页用 `watch` 监听共享章/节范围，范围变化时主动清掉旧结果。
- 历史页用 `onActivated` 在每次进入时刷新记录；清空历史后递增 `historyCleared`，问答页监听此通知后清掉旧回答。
- 继续使用地址中的 `#qa`、`#quiz` 等切换页面；不增加 Vue Router、Pinia 或新的运行时依赖。

三个常见的 Vue 概念：

- `ref`：会变化的数据，例如输入框中的问题、当前章节、接口返回的回答。
- `computed`：根据其他数据计算出来的结果，例如搜索后的目录、单选题得分。
- `watch`：数据变化后执行联动，例如切换章节后清除上一章的总结。

### 一次提问怎样走完前后端

1. 用户在输入框中提问，`v-model` 把内容同步到 `question`。
2. 点击发送触发 `QuestionView.vue` 内的 `ask()`，检查非空输入，并固定本次问题、章/节范围与会话 UUID。
3. 共享工作区的 `run()` 统一管理处理中状态；`request()` 将数据作为 JSON 发给 `/api/qa`。
4. 本地 Vite 将请求转给 8000 端口；`F:/桌面/毕设/backend/api/routes.py` 校验请求并调用检索、生成与历史存储服务。前端只调用接口，不执行检索算法。
5. 后端返回回答、引用、生成方式和耗时；问答页赋值给本地 `qa`，Vue 自动更新结果区域。
6. `SourceList` 展示教材原文；`loadHistory()` 重新获取后端保存的本次会话记录。

连接失败、超时、无效响应和后端业务错误，会经过请求层/页面层转换为中文提示；请求编号保留用于排查。

### 容易误解的几个状态

| 名称                        | 实际含义                                                                                  |
| --------------------------- | ----------------------------------------------------------------------------------------- |
| `session_id`                | 当前标签页复用的随机会话 UUID，用于查询对应历史；不是登录账号或身份鉴权                   |
| `chapter_id` / `section_id` | 学习范围；问答可不限章节，总结和练习必须选章节。前端的空字符串发送时会转换为 `null`       |
| `generation_mode`           | 后端实际使用的生成方式；`extractive` 是原文摘录，`llm` 是模型依据教材生成                 |
| `submitted`                 | 本轮练习是否已提交，控制参考答案/解析的展示；不是考试防作弊措施，参考答案本身已随接口返回 |
| `answers` / `reviews`       | 前者保存用户作答，后者保存简答题自评；只有单选题自动按选项键判分                          |
| `citations` / `coverage`    | 前者是教材证据，页码采用 PDF 实际页码；后者统计代表性片段覆盖，不表示全部知识点都已总结   |
| `historyOffset`             | 已跳过的历史条数，0、10、20 对应第 1、2、3 页，不是页码本身                               |

### 想改什么，应该找哪里

- 修改导航标题、页面介绍：看 `F:/桌面/毕设/frontend/src/lib/presentation.js` 的 `pages` 配置；不要只改某一处模板文字。
- 修改颜色：先看 `F:/桌面/毕设/frontend/src/styles/base.css` 的 `:root` 主题变量；修改布局、学习组件或某个页面时，按上面的职责找到相应样式文件。响应式与最终可读性覆盖分别位于 `responsive.css`、`accessibility.css`，各文件顶部保留中文说明。
- 修改请求参数：同时核对对应 View、`api.js` 和 `F:/桌面/毕设/backend/schemas/models.py`，前后端字段必须一致。
- 修改自测流程：先读 `QuizView.vue` 中的 `generateQuiz → submitQuiz → resetQuiz`，保留提交前隐藏反馈、单选客观判分和简答自评的区别。

注释说明职责、数据流和分支原因，不逐行复述语法。后续修改逻辑时也要同步更新对应说明，避免“代码变了，注释还停留在旧行为”。

## 本地启动

先在项目根目录启动原有 FastAPI 服务，再启动前端：

```powershell
Set-Location 'F:/桌面/毕设'
& './.venv/Scripts/python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# 另开终端；首次安装使用 npm ci
Set-Location 'F:/桌面/毕设/frontend'
npm ci
npm run dev
```

浏览器打开 http://127.0.0.1:5173。Node.js 20.19+ 或 22.12+（Vite 7 引擎要求）。页面直接访问同源 `/api`，Vite 将其代理到 `http://127.0.0.1:8000`，不需要改后端 CORS。后端地址不同时，在启动 Vite 的终端设置 `$env:BACKEND_URL='http://127.0.0.1:实际端口'`；也可在 `frontend/.env.local` 中仅配置这个地址。根目录原有 `.env` 不改动，任何模型密钥都不应放入前端配置。

## 验证与构建

```powershell
Set-Location 'F:/桌面/毕设/frontend'
npm test
npm run build
npm run preview
```

构建输出 `F:/桌面/毕设/frontend/dist`；本地构建预览地址 http://127.0.0.1:4173。部署时将该目录作为静态资源，并由 Web 服务把 `/api` 反向代理到 FastAPI；Vite 开发代理不是生产服务器。

## 保留的业务

- 工作台：真实章节目录、文本块统计、当前会话提问数、章节搜索。
- 问答：章/节筛选、可用检索方式、证据数、证据不足状态、可展开教材引用。
- 总结：关键要点、证据覆盖统计、教材来源。
- 自测：题量/题型/难度配置；全部完成后提交，答案与原文此前保持隐藏；单选客观计分，简答自评，支持全部重答或重做待复习题。
- 历史：按 UUID 隔离、每页 10 条、删除单条、确认后清空。UUID 存于 sessionStorage，当前标签页刷新后复用，关闭后结束。总结与练习不写入问答历史。
- 桌面双栏和手机抽屉导航、键盘焦点、加载/错误/空状态、减少动态效果设置。

## 后续修改提示词

```text
使用 karpathy-guidelines 修改 F:/桌面/毕设/frontend 的 Vue 前端。
先阅读 App.vue、composables/useWorkspace.js、相关 views 页面及后端 schemas/models.py。
保持页面业务在各自 View 内，公共区域在 components 内；不要把逻辑集中回根组件。
保留 FastAPI 契约、会话隔离、教材引用和提交前隐藏练习答案。
使用中文注释说明模块职责、关键状态、数据流和分支原因，不逐行堆砌语法说明。
只实现本次明确要求；不改后端业务、不覆盖现有未提交修改。
修改后执行 npm test、npm run build，并验证桌面及移动端主要交互。
```

参考：[Vue 单文件组件与项目搭建](https://vuejs.org/guide/quick-start.html)、[Vite 服务代理](https://vite.dev/config/server-options#server-proxy)。

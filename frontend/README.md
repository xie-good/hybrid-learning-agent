# 知序 · Vue 课程学习与文档伴读工作台

当前前端使用 Vue 3 单文件组件、HTML 模板、原生 CSS 与 JavaScript，以 Vite 构建，统一采用浅蓝白主题风格。说明按 **2026-11-28** 最新源码核对；系统整体数据流先看 [项目运行流程](F:/桌面/毕设/docs/project-runtime-flow.md)。

## 组件结构与职责

```text
frontend/src/
├── App.vue                         # 根布局、5 页装配、宽屏伴读容器、KeepAlive
├── views/
│   ├── OverviewView.vue            # 课程目录（侧栏置顶）：概览卡、统计、搜索、提问/总结快捷入口
│   ├── QuestionView.vue            # AI 问答：左 PDF 纯白按页预览/切片 + 可拖动分割条 + 右混合检索问答
│   ├── KnowledgeView.vue           # 知识库：多知识库切换、新建/删除、上传 PDF/MD、浏览切片
│   ├── SummaryView.vue             # 章节总结：顶部单行控制栏、要点、覆盖统计与闭环跳转
│   └── HistoryView.vue             # 问答历史：分页回看、单条删除与确认清空
├── components/
│   ├── layout/
│   │   ├── AppSidebar.vue          # 侧栏导航（主工作区 4 项 + 默认展开的学习工具 1 项）
│   │   ├── AppTopbar.vue           # 面包屑、当前知识库标签、连接状态与移动菜单按钮
│   │   └── LearningLayout.vue      # 总结的范围选择、操作插槽与空状态占位
│   ├── ScopeSelector.vue           # 公共章/节范围选择器（支持右上角 action 插槽）
│   ├── SourceList.vue              # 引用折叠卡（双路/BM25/向量/概览标签、分数明细、左侧原文定位）
│   └── AppIcon.vue                 # 统一 SVG 图标组件
├── composables/useWorkspace.js     # 跨页共享的知识库、目录、章/节范围、会话 UUID 与历史状态
├── lib/
│   ├── api.js                      # fetch、超时、中文错误转换、会话 UUID
│   └── presentation.js             # 侧栏顺序、展示文案与 Markdown 安全解析
├── main.js                         # 浏览器入口
├── style.css                       # 声明 CSS 模块的严格层叠顺序
└── styles/
    ├── base.css                    # 浅蓝白主题变量、基础排版与焦点环
    ├── layout.css                  # 侧栏、顶栏、主内容区与宽屏容器
    ├── footer.css                  # 公共页脚
    ├── components/learning.css     # 范围卡、引用标签与结果面板
    ├── views/
    │   ├── overview.css            # 课程目录概览卡、统计卡与章节网格
    │   ├── knowledge.css           # 多知识库管理、双栏伴读布局、可拖动分割条与 PDF 纯白预览
    │   └── history.css             # 历史列表、分页与清空确认
    ├── motion.css                  # 加载动画
    ├── responsive.css              # 响应式断点与减少动态效果
    └── accessibility.css           # 最后加载的可读性与移动导航覆盖
```

## 关键实现约定

- **导航顺序**：主工作区依次为 `课程目录 → AI 问答 → 知识库 → 问答历史`，「学习工具」默认展开，包含 `章节总结`。
- **双栏无黑边伴读**：`QuestionView.vue` 左侧对 PDF 文档不再使用自带黑边的 `<iframe>`，改为请求 `/api/kbs/{kb_id}/documents/{doc_id}/page/{page_num}` 渲染纯白高清 PNG，并提供页码输入直达、缩放（60%–180%）及中间可拖动分割条（左侧 28%–68%）。
- **固定混合检索**：问答页输入框底部不提供检索模式切换按钮，默认固定走服务端 `BM25 + 向量 · RRF 混合检索`，保留召回证据条数（1—10）调节。
- **状态与缓存**：`App.vue` 通过 `provide/inject` 提供共享 `useWorkspace()`，配合 `<KeepAlive>` 保留切页状态；浏览器刷新后复用 `sessionStorage` 中的 `session_id` 并重读问答历史。
- **样式层叠顺序**：`style.css` 的导入顺序受 `frontend/test/styles.test.js` 严格校验，新增或调整样式时保持原有层叠顺序，不要随意合并 `responsive.css` 和 `accessibility.css`。

## 本地启动与验证

先在项目根目录启动 FastAPI 后端（端口 8000），再启动 Vue 前端（端口 5173）：

```powershell
Set-Location 'F:/桌面/毕设/frontend'
npm ci
npm run dev
```

运行前端单元测试与生产构建：

```powershell
Set-Location 'F:/桌面/毕设/frontend'
npm test
npm run build
npm run preview
```

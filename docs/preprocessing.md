# 知识正文预处理与多格式文档入库

更新：2026-11-28。系统包含两套文档解析管线：一是针对预置教材 Hello-Agents 的离线清洗管线，二是针对用户在「知识库」页面上传个人资料的在线解析管线。

## 一、预置教材离线清洗规则（`pipeline/clean_pdf.py`）

- 课程范围当前为第 1—12 章（67 节、759 块），保留原 PDF 物理页码（第 10—560 页）。
- 收录概念、原理、知识小结以及知识讲解中的教学示例与代码。
- 自动排除独立的习题、练习、思考题、作业、参考文献及讨论交流板块；排除状态跨页延续，遇到后续知识小节自动恢复。
- 输出目录 `F:/桌面/毕设/data/processed/hello-agents/`：

| 文件 | 用途 |
|---|---|
| `cleaned.txt` | 供人工核对的知识正文 |
| `pages.jsonl` | 知识正文、字符偏移、原始提取文本与过滤审计信息 |
| `chapters.json` | 仅包含知识小节的课程目录与页码范围 |
| `chunks.jsonl` | 仅从知识正文生成的检索文本块 |
| `report.json` | 来源哈希、过滤规则、排除统计、数据版本与产物哈希 |

### 预置语料重建命令

```powershell
Set-Location 'F:/桌面/毕设'
# 1. 重新解析预置 PDF
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -B -m pipeline.run_preprocess --source 'F:/下载/Hello-Agents-V1.0.3-20260717.pdf' --output 'F:/桌面/毕设/data/processed/hello-agents' --force

# 2. 重建 BM25 与向量索引（数据版本变化后必须重建）
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -B -m pipeline.build_index --processed-dir 'F:/桌面/毕设/data/processed/hello-agents' --output 'F:/桌面/毕设/data/indexes/hello-agents' --mode all --force
```

重建完成后重启 FastAPI 即可加载新快照。

## 二、用户上传文档在线入库（`pipeline/ingest_doc.py`）

自定义知识库通过 `POST /api/kbs/{kb_id}/documents` 调用 `pipeline/ingest_doc.py` 完成在线解析与分块：

- **支持格式**：严格限制为 **PDF (`.pdf`)、Markdown (`.md`, `.markdown`)**，其余格式（含 `.docx`）在接口层与解析层均拒绝并返回 `422` 中文提示。
- **结构切分与精洗**：
  - PDF：逐页提取文本后转为带 `<!-- page:N -->` 物理页码锚点的 Markdown，优先依据书签或正文首章跳过封面与目录页，复用 `clean_pdf.py` 的规则剔除独立习题、参考文献及讨论交流板块；伴读预览时由后端 `pypdfium2` 按页实时渲染为纯白底 PNG。
  - Markdown (`.md`)：按 `# / ## / ###` 及中文章节标题拆分小节，保护代码块内部的 `#` 注释不被误判。
- **增量索引构建与回滚保护**：上传或删除文档后，`KnowledgeBaseManager` 复用内存中已有文档切片与旧 `vector.index.json` 缓存（仅对新增切片调用 Embedding，删文档 0 次调用 Embedding），且先完成向量化再落盘更新 `data/runtime/custom_kbs/{kb_id}/`，防止上游异常破坏原知识库。

## 三、验证命令

```powershell
Set-Location 'F:/桌面/毕设'
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -B -m unittest discover -s tests -p 'test_*.py'
```

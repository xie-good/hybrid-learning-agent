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

- **支持格式**：严格限制为 **PDF (`.pdf`)、Word (`.docx`)、Markdown (`.md`)**，其余格式在接口层与解析层均拒绝并返回中文提示。
- **结构切分**：
  - PDF：逐页提取文本并保留物理页码，伴读预览时由后端 `pypdfium2` 按页实时渲染为纯白底 PNG。
  - Word (`.docx`)：按标题样式与段落结构提取小节并切块。
  - Markdown (`.md`)：按 `# / ## / ###` 标题层级拆分小节并保留代码块上下文。
- **索引构建与落盘**：上传或删除文档后，`KnowledgeBaseManager` 会自动更新该知识库在 `data/runtime/custom_kbs/{kb_id}/` 下的 `chunks.jsonl`、BM25 索引及 Embedding 向量矩阵索引。

## 三、验证命令

```powershell
Set-Location 'F:/桌面/毕设'
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -B -m unittest discover -s tests -p 'test_*.py'
```

# 知识正文预处理

## 收录规则

- 课程范围仍为第 1—12 章，保留原 PDF 物理页码。
- 收录概念、原理、知识小结、知识讲解中的教学示例与代码。
- 排除独立的习题、练习、思考题、作业、参考文献及讨论交流板块。
- 根据书签与独立标题识别板块边界，不因为正文中出现“习题”“参考文献”等词就删除整段讲解。
- 同页的知识尾文与习题分别处理；排除状态跨页延续，遇到后续知识小节再恢复。
- 从章节中间指定起始页时，仍先确定所在板块，避免把无标题的习题续页当成正文。

这是结构化内容筛选，不是知识图谱抽取；知识讲解中的示例、代码和图注仍属于教材内容。

## 数据文件

`F:/桌面/毕设/data/processed/hello-agents/` 下：

| 文件 | 用途 |
|---|---|
| `cleaned.txt` | 供人工阅读的知识正文 |
| `pages.jsonl` | 知识正文、连续字符偏移、原始提取文本与过滤审计信息 |
| `chapters.json` | 仅包含知识小节的课程目录，保留原小节标识 |
| `chunks.jsonl` | 仅从知识正文生成的检索输入 |
| `report.json` | 来源哈希、过滤规则、排除统计、数据版本与产物哈希 |
| `README.md` | 本次产物说明 |

纯习题等非知识页保留页码审计记录，但不生成文本块。原始提取文本仅用于追溯，不作为检索输入；引用偏移对应过滤后的页面知识正文，原 PDF 不改写。

## 重建命令

```powershell
Set-Location 'F:/桌面/毕设'
# 重新解析原 PDF，仅替换固定的预处理产物。
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -B -m pipeline.run_preprocess --source 'F:/下载/Hello-Agents-V1.0.3-20260717.pdf' --output 'F:/桌面/毕设/data/processed/hello-agents' --force
# 数据版本变化后，旧的稀疏或向量索引不能混用。
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -B -m pipeline.build_index --processed-dir 'F:/桌面/毕设/data/processed/hello-agents' --output 'F:/桌面/毕设/data/indexes/hello-agents' --mode bm25 --force
```

重建后重启 FastAPI，使其加载新数据快照。向量索引需使用对应模型另行重建；上述默认流程不调用外部模型。

## 验证

```powershell
Set-Location 'F:/桌面/毕设'
& 'F:/桌面/毕设/.venv/Scripts/python.exe' -B -m unittest discover -s tests -v
```

测试覆盖板块边界、跨页续文、同页混合内容、知识小节恢复、局部页码范围、引用偏移与中文注释。教材检索相关性仍需要独立标注评测，过滤习题本身不代表所有查询的排序都已达标。

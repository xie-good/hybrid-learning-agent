# 第 1—6 章检索评测集 v1

- 语料版本：`caeb372d8f756b87`。
- 共 120 题，每章 20 题：17 题可答、3 题课程外拒答；合计 102 / 18。
- 每章 calibration / regression / validation 为 7 / 7 / 6；合计 42 / 42 / 36。
- `case_id` 采用 `cal|reg|val-chXX-NNN`，最后三位为章内序号。
  拒答题的章编号仅用于配额统计，不表示教材出处。
- 仅含评测器约定的六个字段，不设置 `chapter_id`、`section_id` 检索过滤；
  评测时仍在整部教材中检索，而非提前限定答案所在章节。
- 可答题来自正文小节，不采用 `section_id=null` 的块，也不靠小结、习题或参考文献出题。
  拒答题采用课程外日常问题，不将教材内技术问题标作拒答。
- 各 split 均为本次编制的公开题，不设盲测 holdout；题目先按原文复核、冻结，再评测，
  不依据检索得分修改题目、标注或门控阈值。

| 章节 | 总题数 | 可答 | 拒答 | 正文小节及可答题分布 |
|---|---:|---:|---:|---|
| ch01 | 20 | 17 | 3 | s001–s004：5 / 4 / 4 / 4 |
| ch02 | 20 | 17 | 3 | s001–s004：5 / 4 / 3 / 5 |
| ch03 | 20 | 17 | 3 | s001–s003：7 / 6 / 4 |
| ch04 | 20 | 17 | 3 | s001–s004：3 / 5 / 4 / 5 |
| ch05 | 20 | 17 | 3 | s001–s005：2 / 3 / 4 / 3 / 5 |
| ch06 | 20 | 17 | 3 | s001–s005：2 / 4 / 3 / 4 / 4 |
| 合计 | 120 | 102 | 18 | 25 个正文小节 |

## 自检

在仓库根目录运行：

```powershell
.venv/Scripts/python.exe data/evaluation/hello-agents-ch01-06-v1/validate_cases.py
```

脚本调用现有 `load_cases`，并检查精确行数、版本、题目及编号唯一性、每章数量、
可回答性、split 与编号前缀、目标小节归属，以及目标小节在目录和非空正文块中均存在。
语料本身通过 `CorpusRepository.require_ready()` 的完整性校验。

## 直接评测

```powershell
.venv/Scripts/python.exe -m tools.evaluate_retrieval `
  --cases data/evaluation/hello-agents-ch01-06-v1/cases.jsonl `
  --processed-dir data/processed/hello-agents `
  --index-dir data/indexes/hello-agents `
  --mode bm25 --top-k 5 10 `
  --output tmp/ch01-06-eval/bm25-rerun.json
```

若使用 hybrid，将 `--mode bm25` 改为 `--mode hybrid`，沿用本地已就绪的向量服务和同版本索引。
该评测不需要改动检索实现、默认模式或 `.env`。

## 本次运行的语料来源

主目录语料及索引文件在本次执行环境中读取时报 `PermissionError`。实际核题、自检和 BM25
评测使用工作区现存的同版本快照：

- processed：`tmp/ui-chinese-20261026/work/data/processed/hello-agents`
- index：`tmp/ui-chinese-20261026/work/data/indexes/hello-agents`
- chunks SHA256：`8f7335a65f1ed9c035af48eb3ecf393144302b168ef472a1adf759708d82a44b`
- report SHA256：`d17acff58d580dc5f4df8df4cee3555000a121e001c890d919a28a6ee17532e9`
- manifest SHA256：`a895482bbcbeb46c56d4c599b8067b7585f2253e121ce869489097c4c91ba63b`

快照中的版本、所有预处理文件哈希、BM25 索引哈希及其 chunks 哈希关联均已验证。
这不是对当前主目录文件字节内容的直接校验；主目录及其 indexes 均未被改写。
复现本次运行时，在上述命令中将对应路径换为这两个快照路径；自检也支持 `--processed-dir`。

## 本次验证与评测结果

冻结题集 SHA256：`93d49d534bd3474a9070d8a435fa5c204952cc3e529fba19fd43041afbd74381`。
实际运行命令（均退出 0）：

```powershell
.venv/Scripts/python.exe data/evaluation/hello-agents-ch01-06-v1/validate_cases.py --processed-dir tmp/ui-chinese-20261026/work/data/processed/hello-agents
.venv/Scripts/python.exe -m unittest discover -s tests -p test_retrieval_evaluation.py
.venv/Scripts/python.exe -m tools.evaluate_retrieval --cases data/evaluation/hello-agents-ch01-06-v1/cases.jsonl --processed-dir tmp/ui-chinese-20261026/work/data/processed/hello-agents --index-dir tmp/ui-chinese-20261026/work/data/indexes/hello-agents --mode bm25 --top-k 5 10 --output data/evaluation/hello-agents-ch01-06-v1/bm25-report.json
```

- 自检：PASS；120 行、版本一致、case_id / 问题唯一、102 / 18、所有目标小节真实存在、`load_cases` 通过。
- 原文依据复核：102 道可答题的支撑摘录均匹配同小节的真实 chunk；多子问另核查同节完整上下文。
- 自检脚本验证：1 个正常输入通过（退出 0）；12 个损坏输入均被拒绝（退出 1），
  覆盖题量、版本、编号、缺失或错章或 null 小节、可回答性、重复问题、范围过滤、split 前缀及章节配额。
- 现有 `test_retrieval_evaluation.py`：编制前、编制后均 7/7 通过。
- 原 20 题种子集未覆盖，SHA256 仍为 `e746deb529f88fa36a133a3f07ca319703db97300f264552d8b1c8e7cbf51b70`。

BM25 全量 120 题结果见 [`bm25-report.json`](bm25-report.json)，其中保留逐题结果、split 指标和复现哈希：

| 指标 | 结果 |
|---|---:|
| Recall@5（102 道可答题） | 0.323529 |
| Recall@10（102 道可答题） | 0.323529 |
| MRR@10（102 道可答题） | 0.323529 |
| 课程外拒答准确率 | 1.000000（18/18） |
| 引用字段有效率 | 1.000000（33/33 个有引用的样例） |
| 可答题被拒答数 | 69/102 |

按章可答题 Top-10 命中数依次为 3 / 5 / 8 / 4 / 5 / 8（各章分母均为 17）。
当前门控对 69 道可答题返回证据不足及空引用，已计入零召回，未绕过门控或调整题目标注。
课程外拒答准确率不是所有 120 题的可回答性判断准确率。本次未运行 hybrid，亦未用本结果调整检索实现。

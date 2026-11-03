# 检索记录

检索日期：2026-10-27。paper-search 作为主要检索工具；网页检索用于原始来源核对及中文期刊补充。

|结果文件|检索词|来源|退出状态|记录数|来源错误|
|---|---|---|---|---|---|
|arxiv_education.json|all:"retrieval augmented generation" AND (all:tutor OR all:course OR all:education)|arxiv|0|0|{"arxiv": "search for source 'arxiv' timed out after 35 seconds"}|
|chsr.json|CHSR-RRF curriculum-gated hybrid retrieval reciprocal rank fusion|openalex|0|1|{}|
|courseassist.json|CourseAssist Pedagogically Appropriate AI Tutor Computer Science Education|openalex|0|4|{}|
|dat.json|DAT Dynamic Alpha Tuning Hybrid Retrieval Retrieval-Augmented Generation|openalex|0|3|{}|
|education.json|retrieval augmented generation education tutoring course assistant|crossref,openalex|0|20|{}|
|eval.json|RAGAS Automated Evaluation Retrieval Augmented Generation|openalex|0|4|{}|
|foundations.json|BGE M3-Embedding Multi-Lingual Multi-Functionality Multi-Granularity|openalex|0|4|{}|
|fusion.json|Reciprocal rank fusion outperforms condorcet individual rank learning methods|crossref|0|3|{}|
|hybrid_education.json|"hybrid retrieval" education|crossref,openalex|0|16|{}|
|hybrid_rag.json|"hybrid retrieval" "retrieval augmented generation"|crossref,openalex|0|16|{}|
|rag_original.json|Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks|openalex|0|3|{}|
|short_courses.json|Improving AI assistants embedded short e-learning courses limited textual content|openalex|0|3|{}|

共 12 条 CLI 检索，返回 77 条记录（含重复和不相关结果）；筛选 12 篇。
arXiv CLI 查询达到 35 秒来源超时；相关预印本通过 OpenAlex 题录与 arXiv 原始页面核对。CLI 退出码 0 不等于所有来源均成功，应同时查看 errors 字段。

中文补充检索词：混合检索 课程 检索增强生成 论文；检索增强生成 学习助手 论文。
主要补充来源：情报工程官方期刊页面与现代信息科技期刊 CNKI 门户。

题录修正：
- KITE 优先引用 BEA 2026 正式论文 DOI 10.18653/v1/2026.bea-1.57，而非同题报告或视频 DOI。
- M3-Embedding 使用 ACL Findings 正式题名和作者拼写 Jianlyu Chen；作者 arXiv 版本题名略有不同。
- CourseAssist 保留 SIGCSE Virtual 2024 正式 DOI，并提供可公开读取的作者版本链接。
- CHSR-RRF 的页面月份与编号呈现差异，本清单只使用可核对的 2026 年，不断言具体首发月份。

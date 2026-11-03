# 国际文献定向核验记录

- 核验日期：2026-10-28。
- 课题：基于混合检索增强生成的课程学习助手设计与实现。
- 记录文件：`international_verified.json`，共10条，编号INT01—INT10。
- 检索方式：围绕BM25、RRF、DPR、RAG、长上下文、引用质量、RAG评测和教育应用进行题名与DOI定向检索；优先阅读出版社、会议官网、作者机构公开版本。本文献集是开题报告的主题性选集，不宣称穷尽式系统综述。
- 年份策略：保留2009年的方法奠基文献；其余选取2020—2025年正式发表且与项目核心设计直接相关的文献。预印本与正式版本重复时采用正式版。

## 采用的主要核验源

| 编号 | 文献定位 | 正式记录或第一方公开版本 | 核验及阅读层级 |
|---|---|---|---|
| INT01 | BM25概率相关性框架 | https://www.nowpublishers.com/article/Details/INR-019 ；https://www.nowpublishers.com/article/DownloadEBook/INR-019 | 出版社索引摘要、书目信息与作者机构清单；未标为全文阅读 |
| INT02 | Reciprocal rank fusion | https://dl.acm.org/doi/10.1145/1571941.1572114 ；https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf | 正式记录与作者公开两页全文 |
| INT03 | Dense Passage Retrieval | https://aclanthology.org/2020.emnlp-main.550/ | 正式记录与摘要 |
| INT04 | Retrieval-Augmented Generation | https://proceedings.neurips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html | 正式会议页与摘要；页码补核机构书目记录 |
| INT05 | M3-Embedding | https://aclanthology.org/2024.findings-acl.137/ | 正式记录与摘要 |
| INT06 | Lost in the Middle | https://aclanthology.org/2024.tacl-1.9/ | 正式记录与摘要 |
| INT07 | ALCE引用生成评测 | https://aclanthology.org/2023.emnlp-main.398/ | 正式记录与摘要 |
| INT08 | RAGAs | https://aclanthology.org/2024.eacl-demo.16/ | 正式记录；全文重点阅读指标与局限章节 |
| INT09 | Kasneci等教育机会与挑战 | https://www.sciencedirect.com/science/article/pii/S1041608023000195 ；https://opus.bibliothek.uni-augsburg.de/opus4/frontdoor/index/index/docId/109030 | 正式记录与机构作者稿；重点阅读教育用途及挑战 |
| INT10 | Bastani等高中数学实地实验 | https://www.pnas.org/doi/10.1073/pnas.2422633122 ；https://pubmed.ncbi.nlm.nih.gov/40560616/ | 正式记录、摘要及勘误记录 |

## 阅读与书目完整性

- 摘要层级：7篇（INT01、INT03—INT07、INT10）。
- 全文重点章节层级：2篇（INT08、INT09）。
- 全文层级：1篇（INT02，两页会议短文）。
- 9篇记录已核实的DOI；INT04保留正式会议URL，DOI字段为null，未把arXiv DOI充作会议DOI。
- JSON保存每篇准确题名、作者、正式年份、venue、卷期/页码或文章号、核验URL、阅读层级、中文概述和项目适用边界；不将未读全文的条目标作全文阅读。

## 正式版本与容易误写的地方

1. INT05正式发表题名为 **M3-Embedding: Multi-Linguality, Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge Distillation**，正式作者名使用ACL记录的Jianlyu Chen。不要将arXiv旧题名与正式会议信息混拼。
2. INT08引用2024年EACL System Demonstrations正式版，页码150—158，而非仅引用2023年预印本。
3. INT10引用2025年PNAS正式版122(26):e2422633122。2025年8月勘误更正作者单位，未改变本选集采用的摘要结论。
4. INT09是教育机会与挑战的讨论性论文，不能作为学习成绩提升的因果证据。INT10的实验结论有特定高中数学场景边界。

## 建议在本课题中的归纳方式

- **检索方法链**：BM25提供术语匹配基线；DPR解释稠密语义检索；M3提供多语向量模型候选；RRF在排名层融合多路结果。混合是否更好必须由同一冻结测试题集上的比较决定。
- **生成与证据链**：RAG解释基于外部资料生成的基本范式；长上下文研究支持控制分块、证据顺序与上下文规模；ALCE支持把引用存在、引用正确、引用覆盖分别检查。
- **评价链**：RAGAs类自动指标作为辅助；检索评价采用人工标注证据，生成评价保留中文教材场景的人工核查。避免将检索分数、答案正确性、引用忠实性混为一个指标。
- **教学边界**：围绕固定教材提供问答、总结、练习、引用核查；练习区分作答过程与答案展示。技术可靠性评测不等于已经证明学习效果提升。

## 使用限制

- 本记录未虚构下载成功或通读状态，也不复用未经核验的网络效果数字。
- 官方页面偶发403、验证码或未完整返回文本时，采用同一论文的官方索引摘要、作者机构公开版本等核验，并在JSON逐条注明。
- 国际文献侧重技术和教育设计依据；中文文献、教育RAG综述和项目现状由主任务合并，避免在这里重复计数。

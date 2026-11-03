"""合并、去重并保存开题使用的已核实书目。"""
from pathlib import Path
import csv
import json
import re

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / 'research'
international = json.loads((RESEARCH / 'international_verified.json').read_text(encoding='utf-8'))['papers']
chinese = json.loads((RESEARCH / 'chinese_verified.json').read_text(encoding='utf-8'))['papers']
records = {p['id']: p for p in international + chinese}
records['EDU01'] = {
    'id': 'EDU01',
    'title': 'Retrieval-augmented generation for educational application: A systematic survey',
    'authors': ['Zongxi Li', 'Zijian Wang', 'Weiming Wang', 'Kevin Hung', 'Haoran Xie', 'Fu Lee Wang'],
    'year': 2025, 'publication_date': '2025-06', 'online_first_date': '2025-05-14',
    'journal': 'Computers and Education: Artificial Intelligence',
    'volume': '8', 'issue': None, 'pages': '100417',
    'doi': '10.1016/j.caeai.2025.100417',
    'publisher_url': 'https://www.sciencedirect.com/science/article/pii/S2666920X25000578',
    'verification_urls': ['https://doi.org/10.1016/j.caeai.2025.100417'],
    'source': 'Crossref DOI精确查询及ScienceDirect出版方页面',
    'read_level': 'full_text_selected_sections',
    'access_note': '阅读公开摘要以及方法、应用分类、挑战与结论部分，未逐页核查全部表格。',
    'is_open_access': True,
    'topic': '教育RAG应用综述', 'method_family': '系统文献综述',
    'data_sources': '教育RAG研究文献', 'study_region': '不适用',
    'application_domain': '人工智能教育应用',
    'summary_cn': '研究梳理RAG在交互学习、教学内容生成与评价中的应用，并讨论知识完整性、幻觉、计算成本和多模态支持等挑战。',
    'limitations': '综述汇总异质场景与评价方法，不代表某一固定教材工具已获得同样收益。',
    'relevance_to_user': '用于组织问答、总结和练习的功能范围，并区分系统质量与学习成效。',
    'recommended_priority': 'A',
    'citation': 'LI Z, WANG Z, WANG W, et al. Retrieval-augmented generation for educational application: A systematic survey[J]. Computers and Education: Artificial Intelligence, 2025, 8: 100417. DOI: 10.1016/j.caeai.2025.100417.',
}
order = ['INT09', 'INT04', 'INT01', 'INT03', 'INT02', 'INT05', 'INT06', 'INT07', 'INT08', 'CN01', 'CN02', 'CN03', 'CN04', 'EDU01', 'INT10']
cn_levels = {'CN01': 'full_text_selected_sections', 'CN02': 'full_text_selected_sections', 'CN03': 'abstract_only', 'CN04': 'abstract_only'}
neutral_limits = {
    'INT03': '开放域问答结果不等同于中文教材表现，需要重新验证模型和问题分布迁移后的效果。',
    'INT08': '自动指标依赖评价模型及提示词，需以人工教材核查作为关键结论的参照。',
    'INT09': '该文是讨论性研究，不是本项目提高学习成绩的实验证据。',
    'INT10': '高中数学的特定实验环境与大学课程教材不同，外推应保持谨慎。',
    'CN01': '通用技术综述不替代固定教材的受控实验。',
    'CN02': '问答正确性与长期学习收益不同；额外重排和反思需计入延迟与资源消耗。',
    'CN03': '摘要主要讨论文本检索粒度，本次未据其推断最佳切分参数。',
    'CN04': '多模态文档研究用于界定图表处理边界，不作为当前纯文本系统效果的证据。',
}
papers = []
seen = set()
for number, identifier in enumerate(order, 1):
    p = dict(records[identifier])
    doi = (p.get('doi') or '').lower().replace('https://doi.org/', '').strip()
    key = 'doi:' + doi if doi else 'title:' + re.sub(r'\W+', '', p['title']).lower()
    if key in seen:
        raise ValueError(f'重复文献：{key}')
    seen.add(key)
    p['reference_number'] = number
    p['language'] = '中文' if identifier.startswith('CN') else '英文'
    p['doi'] = doi or None
    p['citation'] = p.get('citation') or p.get('citation_gbt7714')
    p['summary_cn'] = p.get('summary_cn') or p.get('abstract_summary_cn')
    p['read_level'] = p.get('read_level') or cn_levels.get(identifier)
    p['limitations'] = neutral_limits.get(identifier, p.get('limitations'))
    p['crossref_url'] = f'https://api.crossref.org/works/{doi}' if doi else None
    p['openalex_id'] = p.get('openalex_id')
    p['pdf_url'] = p.get('pdf_url')
    p['retrieved_on'] = '2026-10-28'
    papers.append(p)

payload = {
    'topic': '基于混合检索增强生成的课程学习助手设计与实现',
    'search_cutoff': '2026-10-28',
    'review_type': '主题性文献综述，非穷尽式系统评价',
    'deduplication': 'DOI优先，规范化题名其次；优先正式发表版本。',
    'included_count': len(papers),
    'reading_counts': {level: sum(p['read_level'] == level for p in papers)
                       for level in ('abstract_only', 'full_text_selected_sections', 'full_text')},
    'papers': papers,
}
(ROOT / '课题文献库.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
fields = ['reference_number', 'title', 'authors', 'year', 'journal', 'volume', 'issue', 'pages', 'doi', 'publisher_url', 'language', 'read_level', 'summary_cn', 'limitations', 'relevance_to_user']
with (ROOT / '课题文献明细.csv').open('w', encoding='utf-8-sig', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for p in papers:
        row = {key: p.get(key) for key in fields}
        if isinstance(row['authors'], list):
            row['authors'] = '; '.join(row['authors'])
        writer.writerow(row)
assert len(json.loads((ROOT / '课题文献库.json').read_text(encoding='utf-8'))['papers']) == 15
print(json.dumps({'included': len(papers), 'chinese': sum(p['language'] == '中文' for p in papers), 'reading_counts': payload['reading_counts']}, ensure_ascii=False))

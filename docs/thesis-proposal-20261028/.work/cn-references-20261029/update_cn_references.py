"""调整精简版开题报告的文献构成，仅替换引用及对应综述段落。"""
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile
import hashlib
import json
import re

from lxml import etree as E


WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
SOURCE = ROOT / '开题报告_精简版.docx'
OUTPUT = ROOT / '开题报告_精简版_中文文献版.docx'
NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def sha(data):
    return hashlib.sha256(data).hexdigest().upper()


def text_of(node):
    return ''.join(node.xpath('.//w:t/text()', namespaces=NS))


original_bytes = SOURCE.read_bytes()
original_hash = sha(original_bytes)
(WORK / '原精简版备份.docx').write_bytes(original_bytes)

# 保留原来已经核验过的基础论文，同时补充三篇中文正式发表论文。
library = json.loads((ROOT / '课题文献库.json').read_text(encoding='utf-8'))
old_papers = {p['reference_number']: p for p in library['papers']}
new_papers = [
    {
        'id': 'CN05',
        'title': '基于多模态与检索增强生成的数据库知识问答系统',
        'authors': ['梅忆寒', '王琳琳', '王鹏飞', '戴思龙', '岑黎彬', '蔡琰',
                    '倪伟聪', '王晓玲', '陈红', '杜小勇'],
        'year': 2024,
        'publication_date': '2024-12-10',
        'journal': '计算机教育',
        'volume': None,
        'issue': '12',
        'pages': '232-237',
        'doi': '10.16512/j.cnki.jsjjy.2024.12.023',
        'publisher_url': 'https://jyjs.cbpt.cnki.net/portal/journal/portal/client/paper/eefe975e09aaaf975387fa4178ff936f',
        'language': '中文',
        'source': '《计算机教育》期刊官方平台',
        'read_level': 'abstract_only',
        'summary_cn': '该文介绍数据库课程中结合多模态与检索增强生成的知识问答系统，以及系统开发、模块构建和功能展示。',
        'limitations': '目前依据官方摘要和书目信息归纳，未取得全文；不将功能展示等同于已验证的学习成绩提升。',
        'relevance_to_user': '为围绕固定课程材料开展知识问答提供中文应用研究参照；本课题不据此扩展多模态功能。',
        'citation': '梅忆寒, 王琳琳, 王鹏飞, 等. 基于多模态与检索增强生成的数据库知识问答系统[J]. 计算机教育, 2024(12): 232-237. DOI:10.16512/j.cnki.jsjjy.2024.12.023.',
        'retrieved_on': '2026-10-29',
    },
    {
        'id': 'CN06',
        'title': '检索增强生成赋能智能导学系统构建研究——基于本地大模型与私有知识库',
        'authors': ['杜修平', '王崟羽'],
        'year': 2025,
        'publication_date': '2025-05-10',
        'journal': '中国电化教育',
        'volume': None,
        'issue': '5',
        'pages': '117-127',
        'doi': None,
        'publisher_url': 'https://zdjy.cbpt.cnki.net/portal/journal/portal/client/paper/fbcf6d798a44005d4298a018c0268992',
        'language': '中文',
        'source': '《中国电化教育》期刊官方平台',
        'read_level': 'abstract_only',
        'summary_cn': '该文提出基于本地大模型与私有知识库的智能导学系统框架，讨论知识源处理、用户界面交互和人智协同导学模式。',
        'limitations': '目前依据官方摘要和书目信息归纳；期刊页面未给出DOI，因此不补造DOI。',
        'relevance_to_user': '为教材知识库、检索生成与学习者交互之间的组织方式提供中文研究参照，不将本课题宣称为完整智能导学平台。',
        'citation': '杜修平, 王崟羽. 检索增强生成赋能智能导学系统构建研究——基于本地大模型与私有知识库[J]. 中国电化教育, 2025(5): 117-127.',
        'retrieved_on': '2026-10-29',
    },
    {
        'id': 'CN07',
        'title': '大语言模型时代的信息检索综述',
        'authors': ['庞亮', '邓竞成', '顾佳', '沈华伟', '程学旗'],
        'year': 2024,
        'publication_date': '2024-07',
        'journal': '第二十三届中国计算语言学大会论文集（卷2：前沿综述）',
        'volume': None,
        'issue': None,
        'pages': '98-119',
        'doi': None,
        'publisher_url': 'https://aclanthology.org/2024.ccl-2.6/',
        'pdf_url': 'https://aclanthology.org/2024.ccl-2.6.pdf',
        'language': '中文',
        'source': 'ACL Anthology正式会议记录',
        'read_level': 'abstract_only',
        'summary_cn': '该综述从索引、检索和排序等环节讨论大语言模型对信息检索流程的影响，并分析新的信息获取方式。',
        'limitations': '本次归纳依据官方摘要与书目信息，不把综述性讨论表述为本项目的对照实验结果。',
        'relevance_to_user': '为比较关键词与语义检索、区分检索各环节的职责提供中文方法综述。',
        'citation': '庞亮, 邓竞成, 顾佳, 等. 大语言模型时代的信息检索综述[C]//第二十三届中国计算语言学大会论文集（卷2：前沿综述）. 太原: 中国中文信息学会, 2024: 98-119.',
        'retrieved_on': '2026-10-29',
    },
]
selected = new_papers + [deepcopy(old_papers[n]) for n in [10, 11, 12, 13, 2, 3, 5]]
for n, paper in enumerate(selected, 1):
    paper['reference_number'] = n
    paper['verification_urls'] = list(dict.fromkeys(
        [paper['publisher_url']] + paper.get('verification_urls', [])))

assert len(selected) == 10
assert sum(p['language'] == '中文' for p in selected) == 7
assert len({p['title'] for p in selected}) == 10
assert len({p['doi'].lower() for p in selected if p.get('doi')}) == sum(bool(p.get('doi')) for p in selected)

# 先保存可复核的文献记录，再生成与文献对应的正文。
selection = {
    'topic': library['topic'],
    'target_document': str(OUTPUT),
    'source_document': str(SOURCE),
    'source_sha256': original_hash,
    'selection_date': '2026-10-29',
    'before': {'total': 10, 'chinese': 3, 'english': 7, 'chinese_percent': 30},
    'after': {'total': 10, 'chinese': 7, 'english': 3, 'chinese_percent': 70},
    'selection_rule': '以课程问答、智能导学、检索流程、分块粒度及文档证据组织为主题筛选中文论文，保留RAG、BM25、RRF三篇英文原始方法论文。',
    'review_scope': '本次仅修订精简版开题报告，原完整版、独立文献综述及旧文献库不改写。',
    'papers': selected,
}
(WORK / '中文为主文献库.json').write_text(json.dumps(selection, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(WORK / 'artifact.md').write_text(
    '# 精简版开题报告中文文献修订\n\n'
    f'- 版式与内容基准：{SOURCE}\n'
    f'- 原件 SHA256：{original_hash}\n'
    '- 修改范围：研究目的中的引文、国内外研究现状两段、10条参考文献。\n'
    '- 文献构成：中文7篇、英文3篇，按正文首次出现顺序编号。\n'
    '- 保持原状：封面、个人信息、研究内容、实验方案、进度安排、预期目标、审批区、学校表格、样式、节与页码设置。\n'
    '- 原始文件不覆盖，另存中文文献版；输出前检查引用、Word打开和逐页PDF版式。\n', encoding='utf-8')

replacements = {
    '本课题面向固定课程教材，设计集问答、章节总结、练习和引用核查于一体的学习助手，帮助学习者查找知识、回顾章节并核对答案来源。教育检索增强生成研究为这类应用提供了方法参照[1]。':
    '本课题面向固定课程教材，设计集问答、章节总结、练习和引用核查于一体的学习助手，帮助学习者查找知识、回顾章节并核对答案来源。已有课程知识问答与智能导学研究为这类应用提供了实践参照[1][2]。',
    '国外研究已形成检索与生成结合的RAG框架[2]。BM25适合关键词匹配[3]，DPR等稠密检索方法支持语义匹配[4]，RRF通过合并排名融合多路结果[5]。这些方法为课程问答提供了技术基础，但实际效果仍需在指定教材上验证。':
    '国内研究从信息检索流程[3]、检索增强策略[4]、教育问答证据筛选[5]和检索粒度[6]等角度提出改进思路。多模态文档问答研究也关注证据可追溯性与评测问题[7]，本课题仅借鉴相关思路，研究范围仍以教材文本为主。',
    '国内研究关注RAG流程优化[6]、教育问答中的证据筛选[7]和检索粒度[8]。评价研究进一步区分引用是否存在与引用是否支持结论[9]，并提出自动化辅助评价方法[10]。因此，本课题将数据处理、检索效果和引用可靠性分别验证，避免仅凭回答流畅程度判断效果。':
    '国外研究提出将检索结果与语言模型结合的RAG框架[8]。BM25为关键词匹配提供基础[9]，RRF通过融合多路排名组织候选结果[10]。这些方法构成本课题的技术参照，实际检索效果和引用可靠性仍需在指定教材上验证。',
}

with ZipFile(SOURCE) as z:
    infos = z.infolist()
    parts = {info.filename: z.read(info.filename) for info in infos}
doc = E.fromstring(parts['word/document.xml'])
before = deepcopy(doc)
paragraphs = doc.xpath('//w:body//w:p', namespaces=NS)
reference_paragraphs = [p for p in paragraphs if re.match(r'^\[\d+\] ', text_of(p))]
assert len(reference_paragraphs) == 10
assert all(sum(text_of(p) == old for p in paragraphs) == 1 for old in replacements)
changes = []


def replace_text(paragraph, value):
    texts = paragraph.xpath('.//w:t', namespaces=NS)
    assert len(texts) == 1, '保持原段落格式，仅修改单个文字节点。'
    old = text_of(paragraph)
    texts[0].text = value
    changes.append({'before': old, 'after': value})


for p in paragraphs:
    old = text_of(p)
    if old in replacements:
        replace_text(p, replacements[old])

for number, (paragraph, paper) in enumerate(zip(reference_paragraphs, selected), 1):
    citation = paper['citation']
    if not paper.get('doi') and paper['publisher_url'] not in citation:
        # 会议论文附官方记录；中文期刊的完整卷期页码足以定位，长链接留在文献库。
        if paper['publisher_url'].startswith(('https://aclanthology.org/', 'https://proceedings.neurips.cc/')):
            citation += ' ' + paper['publisher_url']
    replace_text(paragraph, f'[{number}] {citation}')

assert len(changes) == 13
new_xml = E.tostring(doc, encoding='UTF-8', xml_declaration=True, standalone=True)
with ZipFile(OUTPUT, 'w') as z:
    for info in infos:
        z.writestr(info, new_xml if info.filename == 'word/document.xml' else parts[info.filename])

with ZipFile(OUTPUT) as z:
    assert z.testzip() is None
    changed_parts = [n for n, data in parts.items() if z.read(n) != data]
    assert changed_parts == ['word/document.xml']
    result = E.fromstring(z.read('word/document.xml'))

# 删除文本后应完全相同，确保全部段落属性、表格、封面、审批行和节设置未改动。
left, right = deepcopy(before), deepcopy(result)
for root in [left, right]:
    for t in root.xpath('//w:t', namespaces=NS):
        t.text = ''
assert E.tostring(left) == E.tostring(right)
after_ps = result.xpath('//w:body//w:p', namespaces=NS)
before_ps = before.xpath('//w:body//w:p', namespaces=NS)
assert len(after_ps) == len(before_ps)
refs = [text_of(p) for p in after_ps if re.match(r'^\[\d+\] ', text_of(p))]
assert [int(re.match(r'^\[(\d+)\]', t).group(1)) for t in refs] == list(range(1, 11))
body_text = '\n'.join(text_of(p) for p in after_ps if not re.match(r'^\[\d+\] ', text_of(p)))
citations = [int(n) for n in re.findall(r'\[(\d+)\]', body_text)]
assert list(dict.fromkeys(citations)) == list(range(1, 11))
assert all(p['title'] in refs[n] for n, p in enumerate(selected))
assert sha(SOURCE.read_bytes()) == original_hash
assert sha((WORK / '原精简版备份.docx').read_bytes()) == original_hash
assert 'None' not in text_of(result)

verification = {
    'source': str(SOURCE), 'output': str(OUTPUT),
    'source_sha256': original_hash, 'output_sha256': sha(OUTPUT.read_bytes()),
    'source_unchanged': True, 'backup_verified': True,
    'before': selection['before'], 'after': selection['after'],
    'changed_paragraph_count': len(changes), 'changed_parts': changed_parts,
    'all_nontext_xml_unchanged': True, 'all_references_cited_in_order': True,
    'zip_validation': 'OK', 'changes': changes,
}
(WORK / '文献替换核对.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(WORK / '修订正文.txt').write_text('\n\n'.join(text_of(p) for p in after_ps), encoding='utf-8')
print(json.dumps({k: v for k, v in verification.items() if k != 'changes'}, ensure_ascii=False, indent=2))

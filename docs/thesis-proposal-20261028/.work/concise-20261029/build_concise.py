"""在已完成报告的副本中精简正文，保留封面、样式及审批区。"""
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile
import hashlib
import json
import re

from lxml import etree as E
from concise_content import SECTIONS, REFERENCE_ORDER

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
SOURCE = ROOT / '开题报告_混合检索增强课程学习助手.docx'
OUTPUT = ROOT / '开题报告_精简版.docx'
REVIEW = ROOT / '中文文献综述_混合检索增强课程学习助手.docx'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def element(tag, **attrs):
    result = E.Element(f'{{{W}}}{tag}')
    for key, value in attrs.items():
        result.set(f'{{{W}}}{key}', str(value))
    return result


def text_of(node):
    return ''.join(node.xpath('.//w:t/text()', namespaces=NS))


def count_body(table):
    texts = [text_of(p) for row in table.findall('w:tr', NS)[1:-3]
             for p in row.findall('w:tc/w:p', NS)]
    text = ''.join(t for t in texts if not re.match(r'^\[\d+\]', t))
    return {'nonspace_characters': len(re.sub(r'\s', '', text)),
            'chinese_characters': len(re.findall(r'[\u3400-\u9fff]', text))}


source_sha, review_sha = sha(SOURCE), sha(REVIEW)
with ZipFile(SOURCE) as z:
    parts = {name: z.read(name) for name in z.namelist()}
doc = E.fromstring(parts['word/document.xml'])
body = doc.find('w:body', NS)
table = body.find('w:tbl', NS)
rows = table.findall('w:tr', NS)
before = count_body(table)
before_sections = [E.tostring(x) for x in doc.findall('.//w:sectPr', NS)]
before_cover = [E.tostring(x) for x in body.findall('w:p', NS)]
before_approval = [E.tostring(x) for x in rows[-3:]]
all_paragraphs = table.findall('.//w:p', NS)
heading_templates = [deepcopy(next(p for p in all_paragraphs if text_of(p).startswith(prefix)))
                     for prefix in ['一、', '二、', '三、', '四、', '五、']]
role_templates = {
    'h': deepcopy(next(p for p in all_paragraphs if text_of(p) == '1 研究目的与意义')),
    'p': deepcopy(next(p for p in all_paragraphs if text_of(p).startswith('课程学习中的概念查询'))),
    'ref': deepcopy(next(p for p in all_paragraphs if text_of(p).startswith('[1] '))),
}


def paragraph(text, role):
    p = deepcopy(role_templates[role])
    run_props = deepcopy(p.find('w:r/w:rPr', NS))
    for child in list(p):
        if child.tag != f'{{{W}}}pPr':
            p.remove(child)
    run = element('r')
    run.append(run_props)
    t = element('t')
    t.text = text
    run.append(t)
    p.append(run)
    return p


papers = json.loads((ROOT / '课题文献库.json').read_text(encoding='utf-8'))['papers']
by_number = {p['reference_number']: p for p in papers}
selected = [by_number[n] for n in REFERENCE_ORDER]
row_template = deepcopy(rows[1])
insert_at = table.index(rows[1])
for row in rows[1:-3]:
    table.remove(row)

for index, content in SECTIONS.items():
    paragraphs = [deepcopy(heading_templates[index - 1])]
    paragraphs.extend(paragraph(text, role) for role, text in content)
    if index == 1:
        for number, paper in enumerate(selected, 1):
            ref = f"[{number}] {paper['citation']}"
            if not paper.get('doi'):
                ref += ' ' + paper['publisher_url']
            paragraphs.append(paragraph(ref, 'ref'))
    for i, p in enumerate(paragraphs):
        row = deepcopy(row_template)
        cell = row.find('w:tc', NS)
        for child in list(cell):
            if child.tag != f'{{{W}}}tcPr':
                cell.remove(child)
        borders = cell.find('w:tcPr/w:tcBorders', NS)
        for edge, visible in [('top', i == 0), ('bottom', i == len(paragraphs) - 1)]:
            old = borders.find(f'w:{edge}', NS)
            if old is not None:
                borders.remove(old)
            borders.append(element(edge, val='single' if visible else 'nil', sz='4', color='000000'))
        cell.append(p)
        table.insert(insert_at, row)
        insert_at += 1

edited = dict(parts)
edited['word/document.xml'] = E.tostring(doc, encoding='UTF-8', xml_declaration=True, standalone=True)
with ZipFile(SOURCE) as src, ZipFile(OUTPUT, 'w') as out:
    for info in src.infolist():
        out.writestr(info, edited[info.filename])

with ZipFile(OUTPUT) as z:
    assert z.testzip() is None
    changed = [name for name in parts if z.read(name) != parts[name]]
    assert changed == ['word/document.xml']
    result = E.fromstring(z.read('word/document.xml'))
result_body = result.find('w:body', NS)
result_table = result_body.find('w:tbl', NS)
result_rows = result_table.findall('w:tr', NS)
assert [E.tostring(x) for x in result.findall('.//w:sectPr', NS)] == before_sections
assert [E.tostring(x) for x in result_body.findall('w:p', NS)] == before_cover
assert [E.tostring(x) for x in result_rows[-3:]] == before_approval
text = text_of(result_table)
references = [text_of(p) for p in result_table.findall('.//w:p', NS) if re.match(r'^\[\d+\] ', text_of(p))]
assert len(references) == 10
assert [int(re.match(r'^\[(\d+)\]', t).group(1)) for t in references] == list(range(1, 11))
body_citations = set()
for section in SECTIONS.values():
    for _, t in section:
        body_citations.update(int(n) for n in re.findall(r'\[(\d+)\]', t))
assert body_citations == set(range(1, 11))
assert all(t not in text for t in ['例如：本论文', '2024年X', 'None', 'cite'])
assert sha(SOURCE) == source_sha and sha(REVIEW) == review_sha
after = count_body(result_table)
qa = {'source': str(SOURCE), 'output': str(OUTPUT), 'source_sha256': source_sha,
      'output_sha256': sha(OUTPUT), 'source_unchanged': True, 'review_unchanged': True,
      'before': before, 'after': after,
      'body_reduction_percent': round(100 * (1 - after['nonspace_characters'] / before['nonspace_characters']), 1),
      'references_before': 15, 'references_after': 10, 'changed_parts': changed,
      'preserved': ['封面及个人信息栏', '全部审批行', '两节页边距与页码设置', '样式及校徽', '完整文献综述']}
(WORK / 'structure-verification.json').write_text(json.dumps(qa, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(WORK / '精简正文.txt').write_text('\n\n'.join(text_of(p) for p in result_table.findall('.//w:p', NS)), encoding='utf-8')
print(json.dumps(qa, ensure_ascii=False, indent=2))

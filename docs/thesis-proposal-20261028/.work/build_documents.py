"""使用原模板生成开题报告，并另存中文文献综述。"""
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile
import hashlib
import json
import re

from lxml import etree as E
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

from proposal_content import TITLE, SECTIONS, REVIEW

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.work'
SOURCE = WORK / '原始模板.docx'
PROPOSAL = ROOT / '开题报告_混合检索增强课程学习助手.docx'
REVIEW_PATH = ROOT / '中文文献综述_混合检索增强课程学习助手.docx'
PAPERS = json.loads((ROOT / '课题文献库.json').read_text(encoding='utf-8'))['papers']
EXPECTED = 'C413F2D50CB849D6C646FD75036A73735550B1347D8942B499AA373D82559A7B'
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest().upper() == EXPECTED
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}


def node(name, **attributes):
    element = E.Element(f'{{{W}}}{name}')
    for key, value in attributes.items():
        element.set(f'{{{W}}}{key}', str(value))
    return element


def paragraph(text, role='p'):
    p = node('p')
    props = node('pPr')
    props.append(node('pStyle', val='4'))
    props.append(node('spacing', before='80' if role == 'h' else '0', after='60' if role == 'h' else '40', line='320', lineRule='auto'))
    props.append(node('snapToGrid', val='0'))
    props.append(node('widowControl', val='1'))
    props.append(node('jc', val='left' if role in ('h', 'ref') else 'both'))
    props.append(node('ind', firstLine='480' if role == 'p' else '0'))
    if role == 'h':
        props.append(node('keepNext', val='1'))
        props.append(node('keepLines', val='1'))
    elif role == 'ref':
        props.append(node('keepLines', val='1'))
    p.append(props)
    run = node('r')
    rp = node('rPr')
    rp.append(node('rFonts', ascii='Times New Roman', hAnsi='Times New Roman', eastAsia='宋体', cs='Times New Roman'))
    rp.append(node('sz', val='22' if role == 'ref' else '24'))
    rp.append(node('szCs', val='22' if role == 'ref' else '24'))
    rp.append(node('color', val='000000'))
    if role == 'h':
        rp.append(node('b'))
    run.append(rp)
    t = node('t')
    t.text = text
    run.append(t)
    p.append(run)
    return p


def reference_text(paper):
    text = f"[{paper['reference_number']}] {paper['citation']}"
    if not paper.get('doi'):
        text += ' ' + paper['publisher_url']
    return text


def set_cover_line(p, text):
    for run in p.findall('w:r', NS):
        rp = run.find('w:rPr/w:u', NS)
        if rp is not None and rp.get(f'{{{W}}}val') == 'single':
            text_nodes = run.findall('w:t', NS)
            if text_nodes:
                text_nodes[0].text = text
                for extra in text_nodes[1:]:
                    extra.text = ''
                return
    raise ValueError('未找到封面题名下划线槽位')


with ZipFile(SOURCE) as z:
    original_parts = {name: z.read(name) for name in z.namelist()}
root = E.fromstring(original_parts['word/document.xml'])
body = root.find('w:body', NS)
cover = body.findall('w:p', NS)
set_cover_line(cover[7], '基于混合检索增强生成的')
set_cover_line(cover[8], '课程学习助手设计与实现')
table = body.find('w:tbl', NS)
rows = table.findall('w:tr', NS)
title_cell = rows[0].findall('w:tc', NS)[1]
for child in list(title_cell):
    if child.tag != f'{{{W}}}tcPr':
        title_cell.remove(child)
title_p = paragraph(TITLE, 'h')
title_p.find('w:pPr', NS).find('w:jc', NS).set(f'{{{W}}}val', 'center')
title_p.find('w:pPr/w:keepNext', NS).set(f'{{{W}}}val', '0')
title_cell.append(title_p)

for row_index, content in SECTIONS.items():
    # 正文栏随内容增长，不沿用空白表单的大段最小行高。
    row_props = rows[row_index].find('w:trPr', NS)
    height = row_props.find('w:trHeight', NS)
    if height is not None:
        height.set(f'{{{W}}}val', '1')
    row_props.append(node('cantSplit', val='0'))
    cell = rows[row_index].find('w:tc', NS)
    heading = deepcopy(cell.find('w:p', NS))
    heading_props = heading.find('w:pPr', NS)
    if heading_props is None:
        heading_props = node('pPr')
        heading.insert(0, heading_props)
    heading_props.append(node('keepNext', val='1'))
    for child in list(cell):
        if child.tag != f'{{{W}}}tcPr':
            cell.remove(child)
    cell.append(heading)
    for role, text in content:
        cell.append(paragraph(text, role))
    if row_index == 1:
        for paper in PAPERS:
            cell.append(paragraph(reference_text(paper), 'ref'))

    # 长表单栏拆为无内部横线的续行，使 Word 按段落分页，避免整栏移页。
    paragraphs = list(cell.findall('w:p', NS))
    insert_at = table.index(rows[row_index])
    for i, p in enumerate(paragraphs):
        continuation = deepcopy(rows[row_index])
        continuation_props = continuation.find('w:trPr', NS)
        continuation_props.find('w:cantSplit', NS).set(f'{{{W}}}val', '1')
        continuation_cell = continuation.find('w:tc', NS)
        for old in list(continuation_cell):
            if old.tag != f'{{{W}}}tcPr':
                continuation_cell.remove(old)
        cell_props = continuation_cell.find('w:tcPr', NS)
        borders = cell_props.find('w:tcBorders', NS)
        if borders is None:
            borders = node('tcBorders')
            cell_props.append(borders)
        for edge, visible in [('top', i == 0), ('bottom', i == len(paragraphs) - 1)]:
            old_edge = borders.find(f'w:{edge}', NS)
            if old_edge is not None:
                borders.remove(old_edge)
            borders.append(node(edge, val='single' if visible else 'nil', sz='4', color='000000'))
        continuation_cell.append(deepcopy(p))
        table.insert(insert_at + i, continuation)
    table.remove(rows[row_index])

# 审批栏沿用原始内容并从新页开始，避免把签名区挤到正文末尾。
approval = rows[6].find('w:tc/w:p/w:pPr', NS)
approval.append(node('pageBreakBefore', val='1'))
edited_parts = dict(original_parts)
edited_parts['word/document.xml'] = E.tostring(root, encoding='UTF-8', xml_declaration=True, standalone=True)
settings = E.fromstring(original_parts['word/settings.xml'])
update = settings.find('w:updateFields', NS)
if update is None:
    update = node('updateFields', val='true')
    settings.append(update)
else:
    update.set(f'{{{W}}}val', 'true')
edited_parts['word/settings.xml'] = E.tostring(settings, encoding='UTF-8', xml_declaration=True, standalone=True)
with ZipFile(SOURCE) as src, ZipFile(PROPOSAL, 'w') as out:
    for info in src.infolist():
        out.writestr(info, edited_parts[info.filename])

# 综述采用独立学术正文，不复制学校审批表。
doc = Document()
section = doc.sections[0]
section.page_width = Cm(21)
section.page_height = Cm(29.7)
section.top_margin = Cm(2.3)
section.bottom_margin = Cm(2.3)
section.left_margin = Cm(2.5)
section.right_margin = Cm(2.5)
section.footer_distance = Cm(1.2)
for style_name in ['Normal', 'Body Text', 'Title', 'Subtitle', 'Heading 1', 'Heading 2']:
    style = doc.styles[style_name]
    style.font.name = 'Times New Roman'
    style.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), '宋体')
    style.font.color.rgb = RGBColor(0, 0, 0)
    style.font.size = Pt(12)
    style.paragraph_format.space_after = Pt(5)
    style.paragraph_format.line_spacing = 1.35
doc.styles['Title'].font.size = Pt(20)
doc.styles['Title'].font.bold = True
doc.styles['Title'].paragraph_format.space_after = Pt(12)
# 移除默认模板自带的装饰线，学术综述只使用黑色文字层级。
for style in doc.styles:
    for border in list(style.element.findall('.//' + qn('w:pBdr'))):
        border.getparent().remove(border)
for name, size in [('Heading 1', 14), ('Heading 2', 12)]:
    doc.styles[name].font.size = Pt(size)
    doc.styles[name].font.bold = True
    doc.styles[name].paragraph_format.space_before = Pt(12)
    doc.styles[name].paragraph_format.space_after = Pt(6)
    doc.styles[name].paragraph_format.keep_with_next = True
doc.add_paragraph('混合检索增强课程学习助手\n中文文献综述', 'Title')
intro = doc.add_paragraph('对应课题  ' + TITLE)
intro.paragraph_format.space_after = Pt(5)
doc.add_paragraph('检索截至2026年10月28日  |  15篇代表性文献  |  中文4篇  英文11篇')
for role, text in REVIEW:
    if role == 'h1':
        doc.add_paragraph(text, 'Heading 1')
    else:
        p = doc.add_paragraph(text)
        p.paragraph_format.first_line_indent = Pt(24)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

levels = {'abstract_only': '摘要级阅读', 'full_text_selected_sections': '全文重点章节阅读', 'full_text': '全文阅读'}
for paper in PAPERS:
    n = paper['reference_number']
    doc.add_paragraph(f"[{n}] {paper['title']}", 'Heading 2')
    venue = paper.get('journal') or paper.get('conference_proceedings') or paper.get('venue')
    assert venue, f"文献{n}缺少刊会名"
    p = doc.add_paragraph(f"{paper['year']}年  {venue}  |  {levels[paper['read_level']]}  |  优先级\u00a0{paper['recommended_priority']}")
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = True
    p.runs[0].font.size = Pt(10.5)
    for label, value in [('研究要点', paper['summary_cn']), ('课题应用', paper['relevance_to_user']), ('适用边界', paper['limitations'])]:
        p = doc.add_paragraph()
        p.add_run(label + '：').bold = True
        p.add_run(value)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.keep_together = True
        if label == '适用边界':
            p.paragraph_format.keep_with_next = True
    p = doc.add_paragraph('原始来源：' + paper['publisher_url'])
    p.runs[0].font.size = Pt(10)
    p.paragraph_format.space_after = Pt(7)

doc.add_paragraph('八 建议阅读顺序', 'Heading 1')
doc.add_paragraph('建议按基础方法[2—5]、中文场景[10—12]、证据评价[7—9]、教育应用[1][14][15]的顺序阅读。[6]用于模型选型，[13]用于界定多模态扩展。')
doc.add_paragraph('参考文献', 'Heading 1')
for paper in PAPERS:
    p = doc.add_paragraph(reference_text(paper))
    p.paragraph_format.line_spacing = 1.2
    p.paragraph_format.keep_together = True
    p.paragraph_format.space_after = Pt(5)
    for run in p.runs:
        run.font.size = Pt(10.5)

footer = section.footer.paragraphs[0]
footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
field = OxmlElement('w:fldSimple')
field.set(qn('w:instr'), 'PAGE')
footer._p.append(field)
doc.core_properties.title = '混合检索增强课程学习助手中文文献综述'
doc.core_properties.subject = TITLE
doc.core_properties.author = ''
doc.save(REVIEW_PATH)

# 结构验证与保留部件核对。
with ZipFile(PROPOSAL) as z:
    assert z.testzip() is None
    changed = [name for name, data in original_parts.items() if z.read(name) != data]
    assert set(changed) <= {'word/document.xml', 'word/settings.xml'}, changed
    final_root = E.fromstring(z.read('word/document.xml'))
    assert len(final_root.findall('.//w:sectPr', NS)) == 2
    for before, after in zip(root.findall('.//w:sectPr', NS), final_root.findall('.//w:sectPr', NS)):
        assert E.tostring(before) == E.tostring(after)
    all_text = ''.join(final_root.xpath('.//w:t/text()', namespaces=NS))
    assert '例如：本论文' not in all_text and '2024年X' not in all_text
    for n in range(1, 16):
        assert f'[{n}]' in all_text
    assert '专业负责人签名' in all_text and '学生姓名' in all_text
    assert not any(t in all_text for t in ['turn23search', 'cite', '待生成'])
    (WORK / 'proposal-final-text.txt').write_text(all_text, encoding='utf-8')
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest().upper() == EXPECTED
with ZipFile(REVIEW_PATH) as z:
    assert z.testzip() is None
qa = {'source_sha256': EXPECTED, 'preserved_parts': len(original_parts) - len(changed), 'changed_parts': changed, 'references': len(PAPERS), 'proposal': str(PROPOSAL), 'review': str(REVIEW_PATH)}
(WORK / 'structure-verification.json').write_text(json.dumps(qa, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(qa, ensure_ascii=False))

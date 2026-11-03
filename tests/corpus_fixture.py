"""供 API 与服务集成测试共用的可移植真实 PDF 测试夹具。"""
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend.config import Settings
from pipeline.run_preprocess import preprocess


def make_corpus(root: Path, **settings_overrides) -> Settings:
    """创建小型真实 PDF，运行生产预处理流程，并返回隔离配置。

    内容包含 Agent、检索、BM25、向量、get_weather 和记忆。
    范围标识为 ch01-s001、ch01-s002 和 ch02-s001；全程不使用网络。
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    source = root / 'course.pdf'
    writer = PdfWriter()
    texts = [
        '1.1 Agent\nAn Agent perceives an environment and takes actions. '
        'A tool named get_weather provides weather observations. '
        'The planning module selects a sequence of actions. '
        'The memory module stores observations for later use.\n'
        'Sensors collect observations. Actuators execute actions. '
        'Goals guide decisions. Feedback improves later decisions.',
        '1.2 Retrieval\nBM25 ranks documents by term frequency and inverse document frequency. '
        'Retrieval returns source passages with page citations. '
        'Vector retrieval compares embedding similarity. '
        'RRF combines ranked result lists without adding new source text. '
        'The corpus contains chunks tied to chapter and section identifiers.',
        '2.1 Memory\nLong-term memory persists knowledge across interactions. '
        'Working memory holds temporary task information. '
        'Episodic memory stores past events. Semantic memory stores facts. '
        'A memory index helps retrieve relevant past observations. '
        'The application records each answer with its supporting citations.',
    ]
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
            NameObject('/F1'): writer._add_object(font)})})
        escaped = [line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
                   for line in text.splitlines()]
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 12 Tf 14 TL 50 740 Td '
                         + ' '.join(f'({line}) Tj T*' for line in escaped) + ' ET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    first = writer.add_outline_item('第一章 智能体基础', 0)
    writer.add_outline_item('1.1 Agent', 0, parent=first)
    writer.add_outline_item('1.2 Retrieval', 1, parent=first)
    second = writer.add_outline_item('第二章 记忆', 2)
    writer.add_outline_item('2.1 Memory', 2, parent=second)
    with source.open('wb') as output:
        writer.write(output)
    processed = root / 'processed'
    preprocess(source, processed, max_chars=300, overlap=30)
    options = {'processed_dir': processed, 'source_pdf': source,
               'database_path': root / 'history.sqlite3', 'index_dir': root / 'indexes',
               'generation_mode': 'extractive', 'llm_base_url': '', 'llm_model': '',
               'llm_api_key': '', 'embedding_base_url': '', 'embedding_model': '',
               'embedding_api_key': '', 'default_retrieval_mode': 'bm25'}
    options.update(settings_overrides)
    return Settings(**options)

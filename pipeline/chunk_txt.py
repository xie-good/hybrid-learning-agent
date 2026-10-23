"""从带页码的pages.jsonl分块；不跨物理页/章节/书签节，确保引用可核对。"""
import hashlib
import json
import re
from pathlib import Path

CHUNKING_VERSION = 'page-section-char-v1'


def split_spans(text: str, max_chars: int, overlap: int):
    """优先在换行或句末断开，保留精确字符偏移；重叠不会吞掉短尾段。"""
    start = 0
    while start < len(text):
        limit = min(start + max_chars, len(text))
        end, hard_split = limit, False
        if limit < len(text):
            lower = start + max(max_chars // 2, overlap + 1)
            newline = text.rfind('\n', lower, limit)
            if newline >= lower:
                end = newline + 1
            else:
                endings = list(re.finditer(r'[。！？；!?;]', text[lower:limit]))
                if endings:
                    end = lower + endings[-1].end()
                else:
                    hard_split = True
        yield start, end, hard_split
        if end == len(text):
            break
        start = end - overlap


def chunk_text(cleaned_file: Path, output_file: Path, *, max_chars: int = 1200,
               overlap: int = 150) -> dict:
    """字符而非token计长；保留短块，超长代码仍切分并标记，留待人工复核。"""
    cleaned_file, output_file = Path(cleaned_file), Path(output_file)
    if not cleaned_file.is_file():
        raise FileNotFoundError(cleaned_file)
    if max_chars < 100 or not 0 <= overlap < max_chars // 2:
        raise ValueError('max_chars至少100，overlap须在0至max_chars一半之间（不含）。')
    if cleaned_file.resolve() == output_file.resolve():
        raise ValueError('输入与输出文件必须不同。')
    records = [json.loads(line) for line in cleaned_file.read_text('utf-8').splitlines()
               if line.strip()]
    if not records:
        raise ValueError('输入没有页面记录。')
    # 先验证全部输入，再创建输出，避免混合不同教材或错误偏移污染检索数据。
    previous_page = 0
    for record in records:
        if (record['source_sha256'] != records[0]['source_sha256']
                or record['cleaning_version'] != records[0]['cleaning_version']
                or record['page'] <= previous_page):
            raise ValueError('页面来源/清洗版本不一致，或页码未严格递增。')
        previous_page = record['page']
        offset = 0
        for segment in record['segments']:
            if not offset == segment['char_start'] < segment['char_end'] <= len(record['text']):
                raise ValueError('节内字符范围无效。')
            offset = segment['char_end']
        if offset != len(record['text']):
            raise ValueError('节内字符范围未完整覆盖页面。')
    config = {'chunking_version': CHUNKING_VERSION, 'max_chars': max_chars, 'overlap': overlap}
    fingerprint = {'source': records[0]['source_sha256'],
                   'pages_sha256': hashlib.sha256(cleaned_file.read_bytes()).hexdigest(),
                   'cleaning': records[0]['cleaning_version'],
                   'page_start': records[0]['page'], 'page_end': records[-1]['page'], **config}
    dataset_version = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()[:16]
    output_file.parent.mkdir(parents=True, exist_ok=True)
    count, hard_splits = 0, 0
    with output_file.open('w', encoding='utf-8', newline='\n') as output:
        for page in records:
            for segment in page['segments']:
                base = segment['char_start']
                text = page['text'][base:segment['char_end']]
                for start, end, hard in split_spans(text, max_chars, overlap):
                    content = text[start:end]
                    if not content.strip():
                        continue
                    count += 1
                    hard_splits += int(hard)
                    chunk = {key: page[key] for key in ('source_file', 'source_sha256',
                             'chapter_id', 'chapter_title', 'cleaning_version', 'review_flags')}
                    chunk.update({
                        'chunk_id': f'{dataset_version}-p{page["page"]:04d}-{count:05d}',
                        'dataset_version': dataset_version,
                        'section_id': segment['section_id'], 'section_title': segment['section_title'],
                        'page_start': page['page'], 'page_end': page['page'],
                        'char_start': base + start, 'char_end': base + end,
                        'text': content, 'char_count': len(content), 'hard_split': hard,
                    })
                    output.write(json.dumps(chunk, ensure_ascii=False) + '\n')
    return {'dataset_version': dataset_version, 'chunk_count': count,
            'hard_split_count': hard_splits, 'chunk_config': config}


if __name__ == '__main__':
    print('请运行 python -m pipeline.run_preprocess --help 查看离线处理命令。')

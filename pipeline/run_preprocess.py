"""单一离线入口：校验参数→临时目录清洗/分块→验证→发布六个数据文件。"""
import argparse
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from pipeline.chunk_txt import chunk_text
from pipeline.clean_pdf import clean_pdf, write_json

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_NAMES = ('pages.jsonl', 'cleaned.txt', 'chapters.json', 'chunks.jsonl', 'report.json', 'README.md')


def preprocess(source: Path, output_dir: Path, *, start_page: int | None = None,
               end_page: int | None = None, max_chars: int = 1200,
               overlap: int = 150, force: bool = False) -> dict:
    """只覆盖六个已知产物；处理失败时不发布数据，不清空用户目录。"""
    source, output_dir = Path(source).resolve(), Path(output_dir).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.is_relative_to(output_dir):
        raise ValueError('输出目录必须与原始PDF分离。')
    if max_chars < 100 or not 0 <= overlap < max_chars // 2:
        raise ValueError('分块参数无效：max_chars>=100，0<=overlap<max_chars//2。')
    if not force and any((output_dir / name).exists() for name in OUTPUT_NAMES):
        raise FileExistsError('输出已存在；确认重建时添加 --force。')
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.preprocess-', dir=output_dir.parent) as temp:
        stage = Path(temp)
        report = clean_pdf(source, stage, start_page=start_page, end_page=end_page)
        report.update(chunk_text(stage / 'pages.jsonl', stage / 'chunks.jsonl',
                                 max_chars=max_chars, overlap=overlap))
        if not report['chunk_count']:
            raise ValueError('未提取到可分块正文；请检查是否为扫描PDF，本版不做OCR。')
        report['output_sha256'] = {name: hashlib.sha256((stage / name).read_bytes()).hexdigest()
                                   for name in OUTPUT_NAMES[:4]}
        write_json(stage / 'report.json', report)
        (stage / 'README.md').write_text(
            '# Hello-Agents 离线预处理产物\n\n'
            f"- 数据版本：`{report['dataset_version']}`\n"
            f"- 正文：PDF物理页{report['start_page']}—{report['end_page']}，"
            f"{report['chapter_count']}章，{report['chunk_count']}块。\n"
            '- 收录范围：课程理论、代码示例与实战知识；毕业设计整章排除。\n'
            '- `cleaned.txt`：人工抽查正文；保留代码换行和缩进，不保证代码可运行。\n'
            '- `pages.jsonl`：原始提取文本、清洗文本、页码、章节与节内字符范围。\n'
            '- `chapters.json`：书签章节目录和原始/本次包含的页码范围。\n'
            '- `chunks.jsonl`：后续检索输入，包含块ID、数据版本、章/节、页码与字符偏移。\n'
            '- `report.json`：来源哈希、参数、计数与待复核页。\n\n'
            '第一版按页/节切块，默认最多1200字符、重叠150字符；不跨页拼接。'
            '具体参数以report.json为准。图表只提取可读取的文字/图注，不做OCR。'
            'image_resource是保守资源提示，不代表图片已识别；hard_split表示无合适边界时硬切。'
            '未构建BM25或向量索引，知识库状态仍为未就绪。\n', 'utf-8')
        output_dir.mkdir(parents=True, exist_ok=True)
        # 每个文件同盘replace；六文件不是整体事务，发布后按report版本核验。
        for name in OUTPUT_NAMES:
            (stage / name).replace(output_dir / name)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description='课程PDF离线清洗与分块（不建索引、不调模型）')
    parser.add_argument('--source', type=Path, required=True, help='原PDF路径，不会改写')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/processed/hello-agents')
    parser.add_argument('--start-page', type=int, help='1起算物理页；默认首章书签页')
    parser.add_argument('--end-page', type=int, help='扫描范围终点，默认PDF末页；毕业设计章始终排除')
    parser.add_argument('--max-chars', type=int, default=1200)
    parser.add_argument('--overlap', type=int, default=150)
    parser.add_argument('--force', action='store_true', help='重建并替换六个已知产物')
    args = parser.parse_args()
    try:
        report = preprocess(args.source, args.output, start_page=args.start_page,
                            end_page=args.end_page, max_chars=args.max_chars,
                            overlap=args.overlap, force=args.force)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        parser.exit(2, f'预处理失败：{exc}\n')
    print(json.dumps({key: report[key] for key in ('included_pages', 'chapter_count',
                     'chunk_count', 'dataset_version')}, ensure_ascii=False))


if __name__ == '__main__':
    main()

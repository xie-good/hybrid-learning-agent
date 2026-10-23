"""文本切块入口占位；沿用现有chunk_txt.py文件名。"""
from pathlib import Path


def chunk_text(cleaned_file: Path, output_file: Path) -> None:
    """将来按章/节、完整段落和代码边界切块，输出带物理页码的JSONL。"""
    raise NotImplementedError('文本切块尚未实现。')


if __name__ == '__main__':
    print('骨架入口：文本切块尚未实现，本次未生成文本块。')

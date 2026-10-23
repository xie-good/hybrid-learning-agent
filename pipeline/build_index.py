"""索引构建入口占位；将来从同一份文本块建立两类索引。"""
from pathlib import Path


def build_indexes(chunks_file: Path, output_dir: Path) -> None:
    """将来构建BM25与向量索引，并核验块ID和数据集版本一致。"""
    raise NotImplementedError('索引构建尚未实现。')


if __name__ == '__main__':
    print('骨架入口：索引构建尚未实现，本次未创建任何索引。')

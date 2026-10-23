"""PDF清洗入口占位；后续保留原PDF，另存清洗正文和页码映射。"""
from pathlib import Path


def clean_pdf(source: Path, output_dir: Path) -> None:
    """将来提取正文、清理重复装饰并登记章节和异常。"""
    # 当前不读取或写入文件；不要在import时执行教材处理。
    raise NotImplementedError('PDF清洗尚未实现，原始文件保持不变。')


if __name__ == '__main__':
    print('骨架入口：PDF清洗尚未实现，本次未处理任何文件。')

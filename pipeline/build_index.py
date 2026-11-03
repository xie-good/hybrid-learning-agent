"""离线构建稀疏/稠密索引；默认BM25不发起外部请求。"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.config import Settings
from backend.errors import AppError
from backend.services.corpus import CorpusRepository
from backend.services.retrieval import (BM25Index, INDEX_FORMAT_VERSION, TOKENIZER_VERSION,
                                        embedding_fingerprint, fetch_embeddings)

INDEX_FILES = ('bm25.index.json', 'vector.index.json', 'manifest.json')


def build_indexes(chunks_file: Path, output_dir: Path, *, settings: Settings | None = None,
                  mode: str = 'bm25', batch_size: int = 32, force: bool = False) -> dict:
    """验证全部预处理文件，再发布带版本的索引产物。

    最后替换清单文件，使并发读取者拒绝混合索引快照，而非使用过期向量。
    修改语料、向量接口或模型之后须重新构建索引，并重启应用。
    """
    source, output = Path(chunks_file).resolve(), Path(output_dir).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.name != 'chunks.jsonl':
        raise ValueError('索引输入须为预处理目录中的 chunks.jsonl。')
    if (output == source.parent or output.is_relative_to(source.parent)
            or source.parent.is_relative_to(output)):
        raise ValueError('索引输出目录须与预处理目录分离。')
    if mode not in {'bm25', 'vector', 'hybrid'} or type(batch_size) is not int or not 1 <= batch_size <= 128:
        raise ValueError('mode 或 batch_size 参数无效。')
    if not force and any((output / name).exists() for name in INDEX_FILES):
        raise FileExistsError('索引已存在，确认重建时添加 --force。')
    config = settings if settings is not None else Settings.from_env()
    config = replace(config, processed_dir=source.parent, index_dir=output)
    repo = CorpusRepository(config)
    repo.require_ready()
    chunks = repo.scoped_chunks()
    sparse = BM25Index(chunks)
    payloads = {'bm25.index.json': sparse.payload(repo)}
    if mode in {'vector', 'hybrid'}:
        fingerprint = embedding_fingerprint(config)
        vectors = []
        dimension = None
        for offset in range(0, len(chunks), batch_size):
            batch = fetch_embeddings(config, [chunk['text'] for chunk in chunks[offset:offset + batch_size]])
            if dimension is None:
                dimension = len(batch[0])
            if any(len(vector) != dimension for vector in batch):
                raise AppError(502, 'embedding_dimension_mismatch', '向量服务批次维数不一致，索引尚未发布。')
            vectors.extend(batch)
        payloads['vector.index.json'] = {
            'format_version': INDEX_FORMAT_VERSION, 'dataset_version': repo.dataset_version,
            'chunks_sha256': repo.chunks_sha256, 'embedding_model': config.embedding_model,
            'embedding_fingerprint': fingerprint, 'dimension': dimension,
            'chunk_ids': sparse.ids, 'vectors': vectors,
        }

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.index-', dir=output.parent) as directory:
        stage = Path(directory)
        hashes = {}
        for name, payload in payloads.items():
            content = (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
            (stage / name).write_bytes(content)
            hashes[name] = hashlib.sha256(content).hexdigest()
        manifest = {'format_version': INDEX_FORMAT_VERSION, 'dataset_version': repo.dataset_version,
                    'chunks_sha256': repo.chunks_sha256, 'tokenizer_version': TOKENIZER_VERSION,
                    'chunk_count': len(chunks), 'files': hashes}
        (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        output.mkdir(parents=True, exist_ok=True)
        for name in (*payloads, 'manifest.json'):
            (stage / name).replace(output / name)
    return {'dataset_version': repo.dataset_version, 'chunk_count': len(chunks),
            'modes': ['bm25', 'vector', 'hybrid'] if 'vector.index.json' in payloads else ['bm25'],
            'files': list(payloads) + ['manifest.json']}


def main() -> None:
    config = Settings.from_env()
    parser = argparse.ArgumentParser(description='构建真实 BM25 索引；显式向量模式调用配置的 embedding 服务')
    parser.add_argument('--processed-dir', type=Path, default=config.processed_dir)
    parser.add_argument('--output', type=Path, default=config.index_dir)
    parser.add_argument('--mode', choices=('bm25', 'vector', 'hybrid'), default='bm25')
    parser.add_argument('--batch-size', type=int, default=32)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    try:
        result = build_indexes(args.processed_dir / 'chunks.jsonl', args.output, settings=config,
                               mode=args.mode, batch_size=args.batch_size, force=args.force)
    except AppError as exc:
        parser.exit(2, f'索引构建失败 [{exc.code}]：{exc.message}\n')
    except (OSError, ValueError) as exc:
        parser.exit(2, f'索引构建失败：{exc}\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()

"""在冻结问题集上评测检索，不把接口测试数量当作效果结论。"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Iterable

from backend.config import Settings
from backend.services.corpus import CorpusRepository
from backend.services.retrieval import (EVIDENCE_GATE_VERSION, EVIDENCE_MIN_CHUNK_COVERAGE,
                                        EVIDENCE_MIN_NORMALIZED_SCORE, RANKED_EVIDENCE_GATE_VERSION,
                                        RetrievalService)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_VERSION = 'retrieval-evaluator-v1'


"""`tools/evaluate_retrieval.py` 读题 → 调同一套 `RetrievalService.search` → 按规则算分 → 打出看到的 JSON"""

def _sha256(path: Path) -> str | None:
    """返回输入文件哈希；可选产物缺失时显式记录为空。"""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def load_cases(path: Path, dataset_version: str) -> list[dict]:
    """读取并严格校验 JSONL，避免用错语料版本或重复问题。"""
    records = []
    case_ids = set()
    for line_number, raw in enumerate(Path(path).read_text('utf-8').splitlines(), 1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(f'第 {line_number} 行不是有效 JSON。') from error
        if not isinstance(record, dict):
            raise ValueError(f'第 {line_number} 行必须是对象。')
        case_id = record.get('case_id')
        expected = record.get('expected_section_ids')
        if not isinstance(case_id, str) or not case_id.strip() or case_id in case_ids:
            raise ValueError(f'第 {line_number} 行的 case_id 缺失或重复。')
        if record.get('dataset_version') != dataset_version:
            raise ValueError(f'第 {line_number} 行的数据版本与当前语料不一致。')
        if record.get('split') not in {'calibration', 'regression', 'validation', 'holdout'}:
            raise ValueError(f'第 {line_number} 行的 split 不是受支持的评测划分。')
        if not isinstance(record.get('question'), str) or not record['question'].strip():
            raise ValueError(f'第 {line_number} 行缺少问题。')
        if type(record.get('answerable')) is not bool:
            raise ValueError(f'第 {line_number} 行的 answerable 必须是布尔值。')
        if (not isinstance(expected, list) or len(expected) != len(set(expected))
                or any(not isinstance(item, str) or not item for item in expected)):
            raise ValueError(f'第 {line_number} 行的 expected_section_ids 无效。')
        if record['answerable'] != bool(expected):
            raise ValueError(f'第 {line_number} 行的可回答性与预期小节不一致。')
        case_ids.add(case_id)
        records.append(record)
    if not records:
        raise ValueError('评测集不能为空。')
    return records


def _citation_is_valid(repo: CorpusRepository, citation: dict) -> bool:
    try:
        source = repo.evidence(citation['chunk_id'])
    except (KeyError, TypeError):
        return False
    fields = ('chapter_id', 'section_id', 'page_start', 'page_end', 'text')
    return (all(citation.get(field) == source.get(field) for field in fields)
            and type(citation.get('page_start')) is int
            and type(citation.get('page_end')) is int
            and 1 <= citation['page_start'] <= citation['page_end'])


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile + 0.999999)))
    return round(ordered[index], 3)


def _metrics(rows: list[dict], top_ks: tuple[int, ...]) -> dict:
    answerable = [row for row in rows if row['answerable']]
    unanswerable = [row for row in rows if not row['answerable']]
    with_citations = [row for row in rows if row['retrieved_chunk_ids']]
    metrics = {
        'case_count': len(rows),


        'answerable_count': len(answerable),
        'unanswerable_count': len(unanswerable),
        'abstained_count': sum(row['abstained'] for row in unanswerable),
        'citation_case_count': len(with_citations),
        'citation_valid_count': sum(row['citations_valid'] for row in with_citations),
    }
    for k in top_ks:
        metrics[f'recall_at_{k}'] = round(mean(row[f'recall_at_{k}'] for row in answerable), 6) if answerable else None
    maximum = max(top_ks)
    metrics[f'mrr_at_{maximum}'] = round(mean(row['reciprocal_rank'] for row in answerable), 6) if answerable else None
    metrics['abstention_accuracy'] = round(metrics['abstained_count'] / len(unanswerable), 6) if unanswerable else None
    metrics['citation_validity'] = round(metrics['citation_valid_count'] / len(with_citations), 6) if with_citations else None
    latencies = [row['latency_ms'] for row in rows]
    metrics['latency_p50_ms'] = _percentile(latencies, 0.50)
    metrics['latency_p95_ms'] = _percentile(latencies, 0.95)
    return metrics


def evaluate_cases(service: RetrievalService, repo: CorpusRepository, cases: Iterable[dict], *,
                   mode: str = 'bm25', top_ks: tuple[int, ...] = (5, 10)) -> dict:
    """计算逐例结果、分组指标和总指标；保留原始计数供人工复核。"""
    top_ks = tuple(sorted(set(top_ks)))
    if not top_ks or min(top_ks) < 1 or max(top_ks) > 20:
        raise ValueError('top_ks 必须位于 1—20。')
    rows = []
    for case in cases:
        started = perf_counter()
        found = service.search(case['question'], chapter_id=case.get('chapter_id'),
                               section_id=case.get('section_id'), top_k=max(top_ks),
                               mode=mode, debug=True)
        latency = round((perf_counter() - started) * 1000, 3)
        citations = found['citations']
        expected = set(case['expected_section_ids'])
        ranked_sections = [item.get('section_id') for item in citations]
        relevant_ranks = [index for index, section in enumerate(ranked_sections, 1) if section in expected]
        row = {
            'case_id': case['case_id'], 'split': case['split'], 'question': case['question'],
            'answerable': case['answerable'], 'expected_section_ids': case['expected_section_ids'],
            'retrieved_chunk_ids': [item['chunk_id'] for item in citations],
            'retrieved_section_ids': ranked_sections,
            'abstained': bool(found['insufficient_evidence']),
            'citations_valid': all(_citation_is_valid(repo, item) for item in citations),
            'reciprocal_rank': round(1 / relevant_ranks[0], 6) if relevant_ranks else 0.0,
            'latency_ms': latency,
            'evidence_gate': (found.get('debug') or {}).get('evidence_gate'),
        }
        for k in top_ks:
            found_sections = set(ranked_sections[:k])
            row[f'recall_at_{k}'] = round(len(expected & found_sections) / len(expected), 6) if expected else None
        rows.append(row)
    split_names = list(dict.fromkeys(row['split'] for row in rows))
    splits = {name: _metrics([row for row in rows if row['split'] == name], top_ks)
              for name in split_names}
    return {
        'dataset_version': repo.dataset_version, 'retrieval_mode': mode,
        'generated_at': datetime.now(timezone.utc).isoformat(), 'top_ks': list(top_ks),
        'case_count': len(rows), 'metrics': _metrics(rows, top_ks), 'splits': splits, 'cases': rows,
        'interpretation': '这是冻结小样本的项目基线，不代表总体失败率或泛化性能。',
    }


def main() -> int:
    config = Settings.from_env()
    parser = argparse.ArgumentParser(description='评测课程检索效果并输出可复核 JSON。')
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--processed-dir', type=Path, default=config.processed_dir)
    parser.add_argument('--index-dir', type=Path, default=config.index_dir)
    parser.add_argument('--mode', choices=('bm25', 'vector', 'hybrid'), default='bm25')
    parser.add_argument('--top-k', type=int, nargs='+', default=[5, 10])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    settings = replace(config, processed_dir=args.processed_dir, index_dir=args.index_dir)
    repo = CorpusRepository(settings)
    repo.require_ready()
    service = RetrievalService(repo, settings)
    if args.mode not in service.available_modes():
        raise SystemExit(f'检索模式 {args.mode} 未就绪；当前可用：{service.available_modes()}')
    cases = load_cases(args.cases, repo.dataset_version)
    report = evaluate_cases(service, repo, cases, mode=args.mode, top_ks=tuple(args.top_k))
    report['reproducibility'] = {
        'evaluator_version': EVALUATOR_VERSION,
        'evaluator_sha256': _sha256(Path(__file__)),
        'retrieval_source_sha256': _sha256(PROJECT_ROOT / 'backend/services/retrieval.py'),
        'cases_sha256': _sha256(args.cases),
        'processed_report_sha256': _sha256(args.processed_dir / 'report.json'),
        'index_manifest_sha256': _sha256(args.index_dir / 'manifest.json'),
        'evidence_gate_version': (EVIDENCE_GATE_VERSION if args.mode == 'bm25'
                                  else RANKED_EVIDENCE_GATE_VERSION),
        'evidence_min_chunk_coverage': EVIDENCE_MIN_CHUNK_COVERAGE,
        'evidence_min_normalized_score': EVIDENCE_MIN_NORMALIZED_SCORE,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = {'dataset_version': report['dataset_version'], 'mode': args.mode,
               'case_count': report['case_count'], **report['metrics']}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

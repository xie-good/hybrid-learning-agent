"""核对前六章冻结评测集的数量、版本、划分与真实小节引用。"""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import Settings
from backend.services.corpus import CorpusRepository
from tools.evaluate_retrieval import load_cases

DATASET_VERSION = 'caeb372d8f756b87'
FIELDS = {'case_id', 'dataset_version', 'split', 'question', 'answerable',
          'expected_section_ids'}
SPLIT_PREFIXES = {'cal': 'calibration', 'reg': 'regression', 'val': 'validation'}


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=Path(__file__).with_name('cases.jsonl'))
    parser.add_argument('--processed-dir', type=Path,
                        default=PROJECT_ROOT / 'data/processed/hello-agents')
    args = parser.parse_args()
    repo = CorpusRepository(Settings(processed_dir=args.processed_dir))
    repo.require_ready()
    check(repo.dataset_version == DATASET_VERSION, '语料版本不匹配。')
    cases = load_cases(args.cases, DATASET_VERSION)
    check(len(args.cases.read_text('utf-8').splitlines()) == len(cases) == 120,
          '必须恰好有 120 行，且每行是一道题。')
    catalog_sections = {section['section_id'] for chapter in repo.chapters()
                        for section in chapter['sections']}
    usable_sections = {chunk['section_id'] for chunk in repo.scoped_chunks()
                       if chunk['section_id'] is not None and chunk['text'].strip()}
    questions = set()
    chapters = {f'ch{number:02d}': [] for number in range(1, 7)}
    for case in cases:
        case_id = case['case_id']
        check(set(case) == FIELDS, f'{case_id}: 字段不匹配或附带了检索范围过滤。')
        match = re.fullmatch(r'(cal|reg|val)-(ch0[1-6])-([0-9]{3})', case_id)
        check(match is not None, f'{case_id}: 编号格式错误。')
        prefix, chapter_id, number = match.groups()
        check(SPLIT_PREFIXES[prefix] == case['split'], f'{case_id}: split 前缀不匹配。')
        check(1 <= int(number) <= 20, f'{case_id}: 章节内序号越界。')
        question = re.sub(r'\s+', '', case['question']).casefold()
        check(question not in questions, f'{case_id}: 问题重复。')
        questions.add(question)
        expected = set(case['expected_section_ids'])
        check(expected <= catalog_sections & usable_sections,
              f'{case_id}: 目标小节不存在或没有可用文本块。')
        check(all(section.startswith(chapter_id + '-') for section in expected),
              f'{case_id}: 目标小节属于其他章节。')
        chapters[chapter_id].append(case)
    summary = {}
    for chapter_id, rows in chapters.items():
        answerable = sum(row['answerable'] for row in rows)
        numbers = {int(row['case_id'].rsplit('-', 1)[1]) for row in rows}
        check(len(rows) == 20 and answerable == 17 and numbers == set(range(1, 21)),
              f'{chapter_id}: 应为 20 题，其中 17 题可答、3 题拒答，序号不重复。')
        sections = Counter(section for row in rows for section in row['expected_section_ids'])
        check(len(sections) >= 3, f'{chapter_id}: 至少应覆盖三个小节。')
        summary[chapter_id] = {'total': len(rows), 'answerable': answerable,
                               'unanswerable': len(rows) - answerable,
                               'splits': dict(Counter(row['split'] for row in rows)),
                               'section_counts': dict(sorted(sections.items()))}
    print(json.dumps({'result': 'PASS', 'dataset_version': DATASET_VERSION,
                      'case_count': len(cases), 'answerable_count': 102,
                      'unanswerable_count': 18, 'load_cases': 'PASS',
                      'cases_sha256': hashlib.sha256(args.cases.read_bytes()).hexdigest(),
                      'processed_dir': str(args.processed_dir.resolve()),
                      'chunks_sha256': repo.chunks_sha256, 'chapters': summary},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

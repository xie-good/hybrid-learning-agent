"""通过 rank_bm25 提供本地 Okapi BM25，以及显式配置的向量和 RRF 检索。

启动时不调用模型。稠密检索需要版本匹配的离线索引，以及兼容 OpenAI 的
嵌入服务端点；任意一项缺失时，均不使用合成向量或重排序器代替。
"""
from __future__ import annotations

from collections import Counter
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit

import httpx
from rank_bm25 import BM25Okapi

from backend.config import Settings, should_trust_env
from backend.errors import AppError
from backend.services.corpus import CorpusRepository

TOKENIZER_VERSION = 'nfkc-cjk-bigram-ident-v1'
INDEX_FORMAT_VERSION = 1
BM25_ALGORITHM = 'rank_bm25.BM25Okapi'
BM25_BACKEND_VERSION = version('rank-bm25')
EVIDENCE_GATE_VERSION = 'rank-bm25-cohesive-evidence-v2'
RANKED_EVIDENCE_GATE_VERSION = 'rank-bm25-returned-evidence-v1'
EVIDENCE_MIN_CHUNK_COVERAGE = 0.5
EVIDENCE_MIN_NORMALIZED_SCORE = 0.7
TOKEN_PATTERN = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?:[.:-][A-Za-z0-9_]+)*|\d+(?:\.\d+)*|[\u3400-\u9fff]+')
CAMEL_PATTERN = re.compile(r'[A-Z]+(?=[A-Z][a-z]|\b)|[A-Z]?[a-z]+|[0-9]+')
STOP_WORDS = frozenset({'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
                        'how', 'in', 'is', 'it', 'of', 'on', 'or', 'that', 'the', 'this',
                        'to', 'was', 'what', 'when', 'where', 'which', 'with',
                        '什么', '么是', '如何', '怎么', '为何', '哪些', '请问', '一下',
                        '介绍', '说明', '解释', '一个', '以及', '是否', '进行', '可以'})
QUESTION_PHRASES = re.compile(r'请问|请解释|请介绍|请说明|什么是|是什么|为什么|如何|怎么|怎样|哪些|是否')


def tokenize(text: str) -> list[str]:
    """确定性地生成中文双字词元，以及完整或拆分后的英文标识符。

    不需要外部词典，也不需要下载模型。保留完整代码标识符，
    可使 get_weather 和 HelloAgentsLLM 等名称精确匹配。
    """
    tokens: list[str] = []
    for match in TOKEN_PATTERN.finditer(unicodedata.normalize('NFKC', text)):
        word = match.group(0)
        if '\u3400' <= word[0] <= '\u9fff':
            parts = [word] if len(word) == 1 else [word[i:i + 2] for i in range(len(word) - 1)]
        else:
            parts = [word.casefold()]
            split = re.split(r'[_.:-]+', word)
            if len(split) > 1:
                parts.extend(piece.casefold() for piece in split if piece)
            camel = CAMEL_PATTERN.findall(word)
            if len(camel) > 1:
                parts.extend(piece.casefold() for piece in camel if piece)
            # 仅在每个标识符内部对拆分结果去重，不对整段文本去重。
            parts = list(dict.fromkeys(parts))
        tokens.extend(part for part in parts if part and part not in STOP_WORDS)
    return tokens


def evidence_query_tokens(question: str) -> set[str]:
    """移除问句套话，保留用于判断证据覆盖度的实义词元。"""
    return set(tokenize(QUESTION_PHRASES.sub(' ', question)))


class BM25Index:
    """封装库的默认 Okapi 评分；项目只负责分词、范围过滤和稳定排序。"""

    def __init__(self, chunks: list[dict], *, frequencies: list[dict] | None = None):
        self.ids = [chunk['chunk_id'] for chunk in chunks]
        self.frequencies = ([Counter(tokenize(chunk['text'])) for chunk in chunks]
                            if frequencies is None else [Counter(x) for x in frequencies])
        self.frequencies_by_id = dict(zip(self.ids, self.frequencies))
        self.lengths = [sum(freq.values()) for freq in self.frequencies]
        self.average_length = sum(self.lengths) / len(self.lengths) if self.lengths else 0.0
        self.document_frequency = Counter()
        for counts in self.frequencies:
            self.document_frequency.update(counts.keys())
        # 重建词元时不再次分词，避免把已拆分的标识符重复展开。
        documents = [list(counts.elements()) for counts in self.frequencies]
        self._engine = BM25Okapi(documents, k1=1.5, b=0.75, epsilon=0.25) if any(documents) else None
        self.idf = self._engine.idf if self._engine is not None else {}

    def rank(self, tokens: list[str], allowed_ids: set[str]) -> list[tuple[str, float]]:
        if not tokens or self._engine is None:
            return []
        terms = sorted(set(tokens))
        # 极小语料的库默认 IDF 可能为零或负值，用实际词元命中排除无关片段。
        positions = [i for i, (chunk_id, counts) in enumerate(zip(self.ids, self.frequencies))
                     if chunk_id in allowed_ids and any(counts[term] for term in terms)]
        if not positions:
            return []
        scores = self._engine.get_batch_scores(terms, positions)
        ranked = [(self.ids[i], float(score)) for i, score in zip(positions, scores)]
        return sorted(ranked, key=lambda pair: (-pair[1], pair[0]))

    def payload(self, repo: CorpusRepository) -> dict:
        return {'format_version': INDEX_FORMAT_VERSION, 'algorithm': BM25_ALGORITHM,
                'backend_version': BM25_BACKEND_VERSION,
                'tokenizer_version': TOKENIZER_VERSION, 'dataset_version': repo.dataset_version,
                'chunks_sha256': repo.chunks_sha256, 'chunk_ids': self.ids,
                'k1': 1.5, 'b': 0.75, 'epsilon': 0.25, 'term_frequencies': self.frequencies}


def embedding_endpoint(settings: Settings) -> str:
    base = settings.embedding_base_url.strip().rstrip('/')
    try:
        parsed = urlsplit(base)
        # 访问 .port 时也会检查端口语法错误或取值越界。
        port = parsed.port
        valid = (parsed.scheme in {'http', 'https'} and bool(parsed.hostname)
                 and not any(character.isspace() for character in parsed.netloc)
                 and not parsed.query and not parsed.fragment
                 and not parsed.username and not parsed.password
                 and (port is None or 0 < port <= 65535)
                 and bool(settings.embedding_model.strip()))
    except ValueError:
        valid = False
    if not valid:
        raise AppError(503, 'embedding_not_configured', '向量检索需要配置 EMBEDDING_BASE_URL 和 EMBEDDING_MODEL。')
    return base + '/embeddings'


def embedding_fingerprint(settings: Settings) -> str:
    identity = embedding_endpoint(settings) + '\n' + settings.embedding_model
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()


def normalized_vector(raw, *, expected_dimension: int | None = None) -> list[float]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 8192:
        raise ValueError('向量维数无效。')
    if expected_dimension is not None and len(raw) != expected_dimension:
        raise ValueError('向量维数不一致。')
    try:
        if not all(type(value) in (int, float) and math.isfinite(value) for value in raw):
            raise ValueError('向量元素必须是有限数值。')
        norm = math.hypot(*raw)
    except OverflowError:
        # Python 可接受任意大的 JSON 整数，而 IEEE 浮点数存在范围限制。
        raise ValueError('向量元素超出支持的数值范围。') from None
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError('向量范数为零或非有限数值。')
    return [value / norm for value in raw]


def fetch_embeddings(settings: Settings, texts: list[str]) -> list[list[float]]:
    """仅执行一次受限的嵌入请求；错误信息不包含凭证或上游响应正文。"""
    endpoint = embedding_endpoint(settings)
    headers = {'Content-Type': 'application/json'}
    if settings.embedding_api_key:
        headers['Authorization'] = f'Bearer {settings.embedding_api_key}'
    try:
        response = httpx.post(endpoint, headers=headers,
                              json={'model': settings.embedding_model, 'input': texts},
                              timeout=settings.model_timeout, follow_redirects=False,
                              trust_env=should_trust_env(endpoint))
        response.raise_for_status()
    except httpx.TimeoutException:
        raise AppError(504, 'embedding_timeout', '向量服务响应超时，请稍后重试。') from None
    except httpx.HTTPError:
        raise AppError(502, 'embedding_upstream_error', '向量服务调用失败，请检查服务配置或稍后重试。') from None
    try:
        payload = response.json()
        data = payload['data']
        if not isinstance(data, list) or len(data) != len(texts):
            raise ValueError('嵌入向量数量与输入文本数量不一致。')
        if not all(isinstance(item, dict) and type(item.get('index')) is int for item in data):
            raise ValueError('嵌入向量序号无效。')
        data = sorted(data, key=lambda item: item['index'])
        if [item['index'] for item in data] != list(range(len(texts))):
            raise ValueError('嵌入向量序号重复。')
        vectors = []
        for item in data:
            vectors.append(normalized_vector(item['embedding'],
                           expected_dimension=len(vectors[0]) if vectors else None))
        return vectors
    except (KeyError, TypeError, ValueError, AttributeError):
        raise AppError(502, 'embedding_invalid_response', '向量服务返回了无效的向量数据。') from None


def read_index_file(root: Path, manifest: dict, filename: str) -> dict:
    """仅读取已知文件名，并在 JSON 解码前校验文件字节。"""
    if filename not in {'bm25.index.json', 'vector.index.json'}:
        raise ValueError('索引文件名不在约定列表中。')
    content = (root / filename).read_bytes()
    if hashlib.sha256(content).hexdigest() != manifest['files'][filename]:
        raise ValueError('索引文件内容与哈希值不一致。')
    return json.loads(content.decode('utf-8'))


class RetrievalService:
    def __init__(self, repo: CorpusRepository, settings: Settings):
        self.repo, self.settings = repo, settings
        self._bm25: BM25Index | None = None
        self._vectors: dict[str, list[float]] = {}
        self._vector_dimension = 0
        self._vector_reason = '未找到与课程版本一致的向量索引，请运行离线索引构建。'
        if repo.status()['ready']:
            self._chunks = repo.scoped_chunks()
            self._bm25 = BM25Index(self._chunks)
            self._load_optional_indexes()

    def _load_optional_indexes(self) -> None:
        root = Path(self.settings.index_dir)
        try:
            manifest = json.loads((root / 'manifest.json').read_text('utf-8'))
            if (manifest['format_version'] != INDEX_FORMAT_VERSION
                    or manifest['dataset_version'] != self.repo.dataset_version
                    or manifest['chunks_sha256'] != self.repo.chunks_sha256):
                raise ValueError('索引版本与当前语料不一致。')
        except (OSError, KeyError, ValueError, TypeError):
            return
        # 可选稀疏索引文件损坏时，仍保留已校验的内存 BM25。
        try:
            sparse = read_index_file(root, manifest, 'bm25.index.json')
            expected = self._bm25.payload(self.repo)
            if any(sparse[key] != value for key, value in expected.items()):
                raise ValueError('稀疏索引校验失败。')
            self._bm25 = BM25Index(self._chunks, frequencies=sparse['term_frequencies'])
        except (OSError, KeyError, ValueError, TypeError):
            pass
        try:
            fingerprint = embedding_fingerprint(self.settings)
        except AppError:
            self._vector_reason = '向量检索需要配置 EMBEDDING_BASE_URL 和 EMBEDDING_MODEL。'
            return
        try:
            dense = read_index_file(root, manifest, 'vector.index.json')
            if (dense['format_version'] != INDEX_FORMAT_VERSION
                    or dense['dataset_version'] != self.repo.dataset_version
                    or dense['chunks_sha256'] != self.repo.chunks_sha256
                    or dense['embedding_fingerprint'] != fingerprint
                    or dense['embedding_model'] != self.settings.embedding_model
                    or dense['chunk_ids'] != self._bm25.ids
                    or type(dense['dimension']) is not int
                    or len(dense['vectors']) != len(self._bm25.ids)):
                raise ValueError('向量索引校验失败。')
            vectors = [normalized_vector(vector, expected_dimension=dense['dimension'])
                       for vector in dense['vectors']]
            self._vectors = dict(zip(self._bm25.ids, vectors))
            self._vector_dimension = dense['dimension']
        except (OSError, KeyError, ValueError, TypeError):
            self._vector_reason = '向量索引缺失、校验失败或与当前模型/语料版本不匹配，请重新构建索引。'

    def available_modes(self) -> list[str]:
        if self._bm25 is None:
            return []
        return ['bm25', 'vector', 'hybrid'] if self._vectors else ['bm25']

    def _evidence_gate(self, question: str, ranked: list[tuple[str, float]], mode: str,
                       top_k: int) -> dict:
        """BM25 保持原门控；稠密模式须在实际返回窗口内找到共同支撑片段。"""
        if mode == 'bm25':
            return self._bm25_evidence_gate(question, ranked, top_k)
        # RRF/余弦分数不能除以 BM25 IDF，未返回的 BM25 侧证据也不能放行。
        returned_ids = {chunk_id for chunk_id, _ in ranked[:top_k]}
        lexical_ranked = self._bm25.rank(tokenize(question), returned_ids)
        evidence_id = None
        for candidate in lexical_ranked:
            if self._bm25_evidence_gate(question, [candidate], 1)['passed']:
                evidence_id = candidate[0]
                # 只在门控内部选择见证，不改变引用的原始排序或分数。
                lexical_ranked = [candidate] + [item for item in lexical_ranked if item[0] != evidence_id]
                break
        gate = self._bm25_evidence_gate(question, lexical_ranked, top_k)
        gate.update(gate_version=RANKED_EVIDENCE_GATE_VERSION, evidence_chunk_id=evidence_id)
        return gate

    def _bm25_evidence_gate(self, question: str, ranked: list[tuple[str, float]],
                            top_k: int) -> dict:
        """拒绝关键词分散命中、但没有一段教材能共同支撑的问题。"""
        terms = evidence_query_tokens(question)
        candidate_ids = [chunk_id for chunk_id, _ in ranked[:max(5, top_k)]]
        supported = {term for term in terms if any(
            self._bm25.frequencies_by_id[chunk_id].get(term, 0) for chunk_id in candidate_ids)}
        coverage = len(supported) / len(terms) if terms else 0.0
        best_id = ranked[0][0] if ranked else None
        best_supported = ({term for term in terms
                           if self._bm25.frequencies_by_id[best_id].get(term, 0)}
                          if best_id else set())
        best_coverage = len(best_supported) / len(terms) if terms else 0.0
        # 分子与分母统一采用库的 IDF，不混用旧实现的正值平滑公式。
        query_weight = sum(self._bm25.idf.get(term, 0.0) for term in terms)
        normalized_score = ranked[0][1] / query_weight if ranked and query_weight else 0.0
        exact_single_term = len(terms) == 1 and len(best_supported) == 1
        cohesive_multi_term = (len(best_supported) >= 2
                               and best_coverage >= EVIDENCE_MIN_CHUNK_COVERAGE
                               and normalized_score >= EVIDENCE_MIN_NORMALIZED_SCORE)
        passed = bool(ranked) and (exact_single_term or cohesive_multi_term)
        return {'passed': passed,
                'reason': ('同一教材片段具备足够的关键词覆盖和相关性。' if passed
                           else '关键词只零散出现在教材中，尚不能形成可靠证据。'),
                'query_token_count': len(terms), 'supported_token_count': len(supported),
                'coverage': round(coverage, 6),
                'best_chunk_coverage': round(best_coverage, 6),
                'normalized_score': round(normalized_score, 6),
                'gate_version': EVIDENCE_GATE_VERSION}

    def _rank_vectors(self, question: str, allowed_ids: set[str]) -> list[tuple[str, float]]:
        if not self._vectors:
            raise AppError(503, 'vector_index_not_ready', self._vector_reason)
        if not allowed_ids:
            return []
        query_vector = fetch_embeddings(self.settings, [question])[0]
        if len(query_vector) != self._vector_dimension:
            raise AppError(502, 'embedding_dimension_mismatch', '查询向量维数与离线索引不一致，请重建索引。')
        vector_ranked = []
        for chunk_id in allowed_ids:
            #向量×块
            score = sum(query_value * chunk_value
                        for query_value, chunk_value in zip(query_vector, self._vectors[chunk_id]))
            if score > 0:
                vector_ranked.append((chunk_id, min(score, 1.0)))
        return sorted(vector_ranked, key=lambda pair: (-pair[1], pair[0]))

    @staticmethod
    def _fuse_rankings(bm25_ranked: list[tuple[str, float]],
                       vector_ranked: list[tuple[str, float]], top_k: int) -> list[tuple[str, float]]:
        fused_scores = Counter()
        candidate_limit = max(20, top_k * 4)
        for ranked_candidates in (bm25_ranked[:candidate_limit], vector_ranked[:candidate_limit]):
            for rank, (chunk_id, _) in enumerate(ranked_candidates, 1):
                fused_scores[chunk_id] += 1 / (60 + rank)
        return sorted(fused_scores.items(), key=lambda pair: (-pair[1], pair[0]))

    def search(self, question: str, chapter_id: str | None = None,
               section_id: str | None = None, top_k: int = 5,
               mode: str = 'bm25', debug: bool = False) -> dict:
        self.repo.require_ready()
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            raise AppError(422, 'invalid_question', '问题须为 1—2000 个字符的非空文本。')
        if mode not in {'bm25', 'vector', 'hybrid'} or type(top_k) is not int or not 1 <= top_k <= 20:
            raise AppError(422, 'invalid_retrieval_options', '检索模式或 top_k 参数无效。')
        scoped_chunks = self.repo.scoped_chunks(chapter_id, section_id)
        allowed_ids = {chunk['chunk_id'] for chunk in scoped_chunks}
        tokens = tokenize(question)
        bm25_ranked = self._bm25.rank(tokens, allowed_ids) if mode in {'bm25', 'hybrid'} else []
        vector_ranked = []
        if mode in {'vector', 'hybrid'}:
            vector_ranked = self._rank_vectors(question, allowed_ids)
        if mode == 'hybrid':
            ranked = self._fuse_rankings(bm25_ranked, vector_ranked, top_k)
        else:
            ranked = bm25_ranked if mode == 'bm25' else vector_ranked
        gate = self._evidence_gate(question, ranked, mode, top_k)
        if not gate['passed']:
            ranked = []
        citations = []
        for number, (chunk_id, score) in enumerate(ranked[:top_k], 1):
            citation = self.repo.evidence(chunk_id)
            citation.update(citation_id=number, score=round(score, 8))
            citations.append(citation)
        details = None
        if debug:
            details = {'algorithm': {'bm25': BM25_ALGORITHM, 'vector': 'cosine',
                                     'hybrid': 'rrf_k60'}[mode],
                       'tokenizer_version': TOKENIZER_VERSION, 'query_tokens': sorted(set(tokens)),
                       'scope_chunk_count': len(allowed_ids), 'bm25_candidates': len(bm25_ranked),
                       'vector_candidates': len(vector_ranked), 'reranker_applied': False,
                        'dataset_version': self.repo.dataset_version, 'evidence_gate': gate}
        return {'citations': citations, 'retrieval_mode': mode,
                'insufficient_evidence': not bool(citations), 'debug': details}

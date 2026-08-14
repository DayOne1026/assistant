"""06 RAG：检索——向量 + 图 + BM25 三路召回，RRF 融合（蓝图 06 retrieval 段，移植 zhao/rag/retrieval.py）。

向量通道改 pgvector（vector_fn 回调，返回 [(chunk_id, content, score)]）；
图通道改 05 get_related_entities（graph 回调）；BM25 纯 Python 原样搬。
所有业务通道按 user_id 过滤（03）。
"""

import math
import re
from collections import defaultdict

_rrf_k = 60


def _tokenize(text: str) -> list[str]:
    """中文按"字 + 二元组"，英文按空白。"""
    tokens = []
    for chunk in re.findall(r"[一-鿿]+|[a-zA-Z0-9]+", text.lower()):
        if re.match(r"[一-鿿]", chunk[0]):
            tokens.extend(chunk)
            tokens.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))
        else:
            tokens.append(chunk)
    return tokens


class BM25Retriever:
    """BM25 关键词检索，无外部依赖。中文按字+二元组分词。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: list[list[str]] = []
        self._doc_len: list[int] = []
        self._avgdl: float = 0.0
        self._df: dict[str, int] = defaultdict(int)
        self._tf: list[dict[str, int]] = []
        self._raw: list[str] = []

    def index(self, documents: list[str]):
        self._raw = list(documents)
        self._docs = [_tokenize(d) for d in documents]
        self._doc_len = [len(t) for t in self._docs]
        self._avgdl = sum(self._doc_len) / max(1, len(self._docs))
        self._tf.clear()
        self._df.clear()
        for tokens in self._docs:
            counts: dict[str, int] = defaultdict(int)
            for t in tokens:
                counts[t] += 1
            self._tf.append(dict(counts))
            for t in set(tokens):
                self._df[t] += 1

    def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        q_tokens = _tokenize(query)
        N = len(self._docs)
        scores = [(i, self._score(q_tokens, i)) for i in range(N)]
        scores = [(i, s) for i, s in scores if s > 0]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def _idf(self, term: str) -> float:
        n = self._df.get(term, 0)
        N = len(self._docs)
        return math.log((N - n + 0.5) / (n + 0.5) + 1)

    def _score(self, q_tokens: list[str], doc_idx: int) -> float:
        score = 0.0
        dl = self._doc_len[doc_idx]
        tf = self._tf[doc_idx]
        for t in q_tokens:
            if t not in tf:
                continue
            f = tf[t]
            num = f * (self.k1 + 1)
            den = f + self.k1 * (1 - self.b + self.b * dl / self._avgdl)
            score += self._idf(t) * num / den
        return score


async def search(query: str, user_id, top_k: int = 5,
                 vector_fn=None, graph=None, bm25=None,
                 rrf_k: int = 60) -> list[dict]:
    """多路召回 → RRF 融合。

    vector_fn: async (query, user_id, limit) -> [(chunk_id, content, score)]，必传
    graph:     async (user_id, query) -> [{"names": [...]}]，可选（05 get_related_entities）
    bm25:      BM25Retriever，可选
    """
    rrf: dict[int, float] = {}
    doc_map: dict[int, str] = {}

    if vector_fn is not None:
        for rank, (_, content, _score) in enumerate(await vector_fn(query, user_id, top_k * 2)):
            idx = hash((str(user_id), content))
            rrf[idx] = rrf.get(idx, 0) + 1 / (rrf_k + rank + 1)
            doc_map[idx] = content

    if graph is not None:
        for rank, p in enumerate(await graph(user_id, query)):
            idx = ~hash("|".join(p["names"]))
            rrf[idx] = rrf.get(idx, 0) + 1 / (rrf_k + rank + 1)
            doc_map[idx] = " → ".join(p["names"])

    if bm25 is not None:
        for rank, (doc_idx, _) in enumerate(bm25.search(query, top_k * 2)):
            key = ~doc_idx
            rrf[key] = rrf.get(key, 0) + 1 / (rrf_k + rank + 1)
            if key not in doc_map and doc_idx < len(bm25._raw):
                doc_map[key] = bm25._raw[doc_idx]

    ranked = sorted(rrf.items(), key=lambda x: x[1], reverse=True)[:top_k]
    results = [{"text": doc_map[idx], "score": s} for idx, s in ranked if idx in doc_map]
    # 跨通道内容去重（保 RRF 分高者）
    seen, deduped = set(), []
    for r in results:
        if r["text"] not in seen:
            seen.add(r["text"])
            deduped.append(r)
    return deduped

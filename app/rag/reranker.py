"""06 RAG：排序（蓝图 06 reranker 段，移植 zhao/rag/reranker.py）。

粗排：CrossEncoder（BGE-reranker-v2-m3，本地已缓存）；
精排：LLM 结构化输出逐条打分（三层兜底同 04/05），失败降级保留原序。
"""

import json as _json

from pydantic import BaseModel, Field

from app.core.llm import get_chat_model

RERANK_LLM = get_chat_model()


class CrossEncoderReranker:
    """BGE-reranker-v2-m3，query+doc 深度打分。"""

    def __init__(self, model: str = "BAAI/bge-reranker-v2-m3"):
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model)

    def score(self, query: str, documents: list[str],
              top_k: int | None = None) -> list[tuple[int, float]]:
        pairs = [(query, doc) for doc in documents]
        scores = self._model.predict(pairs, show_progress_bar=False)
        try:
            scores = scores.tolist()
        except AttributeError:
            pass
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        if top_k is not None:
            ranked = ranked[:top_k]
        return ranked


def coarse_rank(query: str, candidates: list[str],
                reranker: CrossEncoderReranker, top_k: int = 20) -> list[str]:
    """粗排——Cross-Encoder 对 (query, doc) 打分（top_k×2 → top_k）。"""
    if not candidates:
        return []
    return [candidates[i] for i, _ in reranker.score(query, candidates, top_k=top_k)]


class _RerankItem(BaseModel):
    i: int
    r: int = Field(ge=1, le=5)
    reason: str


class _RerankResult(BaseModel):
    """包装顶层 list——结构化输出稳定性（同 05 TripleExtraction）。"""

    items: list[_RerankItem]


_RANKING_PROMPT = """你是精排器。对文档逐一打分，只输出 JSON。

评分标准:
- 5: 直接完整回答了问题
- 4: 高度相关，部分回答
- 3: 相关，有参考价值
- 2: 弱相关
- 1: 无关

按 r 降序排列。"""


def _fallback(candidates: list[str], top_k: int) -> list[dict]:
    return [{"text": c, "relevance": 0, "reason": ""} for c in candidates[:top_k]]


async def rerank(query: str, candidates: list[str],
                 llm=None, top_k: int = 5) -> list[dict]:
    """精排——LLM 逐条打分。失败降级保留原序（三层兜底）。"""
    if not candidates:
        return []
    llm = llm or RERANK_LLM
    text = "\n\n".join(f"[{i}] {doc[:300]}" for i, doc in enumerate(candidates))
    prompt = _RANKING_PROMPT + f"\n问题: {query}\n\n文档:\n{text}"
    try:
        out = await llm.with_structured_output(_RerankResult).ainvoke(prompt)
        items = sorted(out.items, key=lambda x: x.r, reverse=True)
        results = []
        for it in items[:top_k]:
            if it.i < len(candidates):
                results.append(
                    {"text": candidates[it.i], "relevance": it.r, "reason": it.reason}
                )
        return results if results else _fallback(candidates, top_k)
    except Exception:
        return _fallback(candidates, top_k)

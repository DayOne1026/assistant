"""06 RAG：检索管线（蓝图 06 pipeline 段，移植 zhao/rag/pipeline.py build_context 骨架）。

build_context：改写 → 多路召回(RRF) → CrossEncoder 粗排 → LLM 精排 → 拼 "[参考文档]"。
无相关文档返回空串，agent 正常闲聊。
"""

from typing import Any

from app.core.llm import get_chat_model

from .query import rewrite
from .reranker import coarse_rank, rerank
from .retrieval import search

_reranker = None


def _get_reranker():
    global _reranker
    if _reranker is None:
        from .reranker import CrossEncoderReranker

        _reranker = CrossEncoderReranker()
    return _reranker


async def build_context(user_id, query: str, top_k: int = 5,
                        rewrite_query: bool = True,
                        vector_fn=None, bm25=None, graph=None,
                        llm: Any | None = None) -> str:
    """检索 → 粗排 → 精排 → 拼 "[参考文档]" prompt 片段；无相关文档返回空串。

    vector_fn: async (query, user_id, limit) -> [(chunk_id, content, score)]（必传，pgvector）
    bm25/graph: 可选召回通道
    """
    llm = llm or get_chat_model()
    q = await rewrite(query, llm) if rewrite_query else query

    candidates_raw = await search(
        q, user_id, top_k=top_k * 2, vector_fn=vector_fn, bm25=bm25, graph=graph
    )
    candidates = [c["text"] for c in candidates_raw]
    if not candidates:
        return ""

    coarse = coarse_rank(q, candidates, _get_reranker(), top_k=top_k)
    ranked = await rerank(q, coarse, llm, top_k=top_k)

    lines = ["[参考文档]"]
    for r in ranked:
        lines.append("---")
        lines.append(r["text"])
    return "\n".join(lines)

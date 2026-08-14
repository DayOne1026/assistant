"""06 RAG：EmbeddingService（蓝图 06 embedding 段）。

本地 BGE（bge-small-zh-v1.5，config.embedding_model），sentence-transformers。
模型懒加载单例，离线可用（用户本地已缓存）。normalize 后余弦 = 点积，配 pgvector cosine ops。
"""

import asyncio
from functools import lru_cache

from app.core.config import get_settings


@lru_cache
def _get_model(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


class EmbeddingService:
    def __init__(self, model: str | None = None, dim: int | None = None):
        s = get_settings()
        self._model_name = model or s.embedding_model
        self.dim = dim or s.embedding_dim

    def _model(self):
        return _get_model(self._model_name)

    async def embed(self, text: str) -> list[float]:
        vec = await asyncio.to_thread(
            self._model().encode, text, normalize_embeddings=True
        )
        return vec.tolist()

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        vecs = await asyncio.to_thread(
            self._model().encode, texts, normalize_embeddings=True
        )
        return [v.tolist() for v in vecs]

"""06 RAG：文档索引（蓝图 06 tasks/rag_tasks.py）。

index_document 为 async 核心（测试直调传 db）；index_document_task 是 Celery 同步包装
（worker 部署 12 生效）。upload 经 config.indexing_async 决定同步 or delay。
"""

import asyncio
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.core.config import get_settings
from app.db.session import async_session
from app.db.tenant import set_tenant_context
from app.rag import chunker, cleaner, loader
from app.rag.embedding import EmbeddingService


def pick_strategy(text: str) -> Callable:
    """有标题结构走 semantic，否则 token（蓝图 06 默认策略）。"""
    has_heading = any(line.strip().startswith("#") for line in text.split("\n")[:50])
    return chunker.chunk_by_semantic if has_heading else chunker.chunk_by_token


def _chunk_text(text: str, strategy: str) -> list[dict]:
    """strategy=parent_child 走父子块（flatten 后含 _embed/_id 标记），否则启发式 token/semantic。"""
    if strategy == "parent_child":
        return chunker.flatten_parent_child(chunker.chunk_parent_child(text))
    return pick_strategy(text)(text)


def _resolve_path(storage_path: str) -> str:
    """相对路径（storage 落盘用）解析到 storage_root；绝对路径直接用（测试/临时文件）。"""
    p = Path(storage_path)
    if p.is_absolute():
        return storage_path
    return str(Path(get_settings().storage_root) / p)


async def index_document(
    db: AsyncSession, document_id, storage_path: str, user_id,
    embedding: EmbeddingService | None = None, commit: bool = True,
    strategy: str = "auto",
) -> None:
    """load → clean → chunk（auto=token/semantic 启发式 / parent_child=父子块）→ dedupe → embed → 写 chunks。
    失败置 failed（不抛）。"""
    from app.repos.documents import chunk_repo, document_repo

    embedding = embedding or EmbeddingService()
    await set_tenant_context(db, user_id)  # RLS 上下文（独立调用/跨事务安全，03）
    try:
        raw = await asyncio.to_thread(loader.load, _resolve_path(storage_path))
        text = cleaner.clean(raw)
        if not text:
            await document_repo.update_status(db, document_id, "failed")
            if commit:
                await db.commit()
            return
        chunks = _chunk_text(text, strategy)
        # parent_child 的 children 非重叠且可能为 parent 子串，dedupe 会误删 → 跳过；
        # token/semantic 保留去重（避免 RRF 前重复命中）
        if strategy != "parent_child":
            chunks = cleaner.dedupe_chunks(chunks)
        # parent-child：仅 child 参与检索（parent 零向量占位，vector_search 过滤 parent）
        to_embed = [c["text"] for c in chunks if c.get("_embed", True)]
        vecs_full = await embedding.embed_many(to_embed) if to_embed else []
        it = iter(vecs_full)
        dim = get_settings().embedding_dim
        vecs = [next(it) if c.get("_embed", True) else [0.0] * dim for c in chunks]
        await chunk_repo.delete_by_document(db, document_id)  # 幂等重试：先清再写
        await chunk_repo.bulk_insert(
            db,
            [
                {
                    "id": c.get("_id"), "user_id": user_id, "document_id": document_id,
                    "chunk_index": i, "group_id": c.get("group_id"),
                    "seq_in_group": c.get("seq_in_group"), "parent_id": c.get("parent_id"),
                    "content": c["text"], "embedding": vecs[i],
                }
                for i, c in enumerate(chunks)
            ],
        )
        await document_repo.update_status(db, document_id, "ready", chunk_count=len(chunks))
        if commit:
            await db.commit()
    except Exception:
        await db.rollback()
        try:
            await set_tenant_context(db, user_id)
            await document_repo.update_status(db, document_id, "failed")
            if commit:
                await db.commit()
        except Exception:
            pass


@celery_app.task
def index_document_task(document_id: str, storage_path: str, user_id: str, strategy: str = "auto") -> None:
    """Celery 同步包装（config.indexing_async=True 时 upload delay 调用；worker 部署 12 生效）。
    测试直调 async 核心 index_document（传 db）。"""
    async def _run() -> None:
        async with async_session() as db:
            await index_document(
                db, uuid.UUID(document_id), storage_path, uuid.UUID(user_id), strategy=strategy
            )

    asyncio.run(_run())

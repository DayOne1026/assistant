"""06 RAG：文档索引（蓝图 06 tasks/rag_tasks.py）。

Celery worker 归 12 部署；本轮 upload 同步调用（ponytail: 12 部署时改 index_document.delay）。
"""

import asyncio
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.tenant import set_tenant_context
from app.rag import chunker, cleaner, loader
from app.rag.embedding import EmbeddingService


def pick_strategy(text: str) -> Callable:
    """有标题结构走 semantic，否则 token（蓝图 06 默认策略）。"""
    has_heading = any(line.strip().startswith("#") for line in text.split("\n")[:50])
    return chunker.chunk_by_semantic if has_heading else chunker.chunk_by_token


def _resolve_path(storage_path: str) -> str:
    """相对路径（storage 落盘用）解析到 storage_root；绝对路径直接用（测试/临时文件）。"""
    p = Path(storage_path)
    if p.is_absolute():
        return storage_path
    return str(Path(get_settings().storage_root) / p)


async def index_document(
    db: AsyncSession, document_id, storage_path: str, user_id,
    embedding: EmbeddingService | None = None, commit: bool = True,
) -> None:
    """load → clean → chunk → dedupe → embed → 写 chunks → status=ready；失败置 failed（不抛）。"""
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
        chunks = cleaner.dedupe_chunks(pick_strategy(text)(text))
        vecs = await embedding.embed_many([c["text"] for c in chunks])
        await chunk_repo.delete_by_document(db, document_id)  # 幂等重试：先清再写
        await chunk_repo.bulk_insert(
            db,
            [
                {
                    "user_id": user_id, "document_id": document_id,
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

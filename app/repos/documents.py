"""06 RAG：document_repo / chunk_repo。repo 只 flush，事务提交归 service。

所有方法必带 user_id 过滤（03 约定，RLS 兜底）。
from __future__ annotations：类体内方法名 list 遮蔽 builtin（同 repos/memory.py 坑）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.documents import Document, DocumentChunk


class DocumentRepo:
    async def create(
        self, db: AsyncSession, user_id: uuid.UUID, title: str, filename: str,
        content_type: str | None, storage_path: str,
    ) -> Document:
        doc = Document(
            user_id=user_id, title=title, filename=filename,
            content_type=content_type, storage_path=storage_path, status="processing",
        )
        db.add(doc)
        await db.flush()
        return doc

    async def get(
        self, db: AsyncSession, user_id: uuid.UUID, doc_id: uuid.UUID
    ) -> Document | None:
        """归属校验：user_id + id 双过滤，软删视为不存在（跨用户读返回 None）。"""
        return (
            await db.execute(
                select(Document).where(
                    Document.id == doc_id, Document.user_id == user_id,
                    Document.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    async def list(
        self, db: AsyncSession, user_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[Document], int]:
        where = [Document.user_id == user_id, Document.deleted_at.is_(None)]
        total = (
            await db.execute(
                select(func.count()).select_from(Document).where(*where)
            )
        ).scalar_one()
        rows = (
            await db.execute(
                select(Document)
                .where(*where)
                .order_by(Document.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), total

    async def soft_delete(
        self, db: AsyncSession, user_id: uuid.UUID, doc_id: uuid.UUID
    ) -> bool:
        """软删文档（deleted_at=now，07 通用二次确认后调用）。chunks 保留供恢复，检索侧排除。"""
        doc = await self.get(db, user_id, doc_id)
        if doc is None:
            return False
        doc.deleted_at = datetime.now().astimezone()
        await db.flush()
        return True

    async def update_status(
        self, db: AsyncSession, doc_id: uuid.UUID, status: str, chunk_count: int | None = None
    ) -> Document:
        """索引状态更新（幂等重试复用行）。RLS 兜底：当前上下文可见才改得到。"""
        doc = await db.get(Document, doc_id)
        if doc is None:
            raise ValueError(f"document {doc_id} 不存在")
        doc.status = status
        if chunk_count is not None:
            doc.chunk_count = chunk_count
        await db.flush()
        return doc


class ChunkRepo:
    async def delete_by_document(self, db: AsyncSession, document_id: uuid.UUID) -> None:
        """删某文档全部 chunks（索引幂等重试先清再写）。"""
        await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        await db.flush()

    async def bulk_insert(self, db: AsyncSession, rows: list[dict]) -> None:
        if rows:
            await db.execute(pg_insert(DocumentChunk), rows)
            await db.flush()

    async def vector_search(
        self, db: AsyncSession, user_id: uuid.UUID, query_vec: list[float], limit: int
    ) -> list[tuple]:
        """pgvector 余弦检索，WHERE user_id 强制过滤 + join 排除软删文档（03/07）。
        只搜叶子块（排除 parent 大块；token/semantic 的 group_id 为 0..n 自增，child 为 'child'），
        child 命中返回 parent 内容（coalesce，蓝图 06 parent-child）。
        返回 (id, document_id, chunk_index, content, score)。"""
        from sqlalchemy import or_

        parent_c = aliased(DocumentChunk)
        content_expr = func.coalesce(
            select(parent_c.content).where(parent_c.id == DocumentChunk.parent_id).scalar_subquery(),
            DocumentChunk.content,
        ).label("content")
        score = DocumentChunk.embedding.cosine_distance(query_vec).label("score")
        rows = (
            await db.execute(
                select(
                    DocumentChunk.id, DocumentChunk.document_id,
                    DocumentChunk.chunk_index, content_expr, score,
                )
                .join(Document, DocumentChunk.document_id == Document.id)
                .where(
                    DocumentChunk.user_id == user_id,
                    Document.deleted_at.is_(None),
                    or_(DocumentChunk.group_id.is_(None), DocumentChunk.group_id != "parent"),
                )
                .order_by(score)
                .limit(limit)
            )
        ).all()
        return [
            (r.id, r.document_id, r.chunk_index, r.content, r.score) for r in rows
        ]


document_repo = DocumentRepo()
chunk_repo = ChunkRepo()

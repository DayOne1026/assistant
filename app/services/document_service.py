"""06 RAG：文档服务（蓝图 06 document_service 段）。事务提交在此，repo 只 flush。"""

import asyncio
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ErrorCode
from app.core.pagination import Page, PageParams
from app.core.storage import Storage
from app.db.models.documents import Document
from app.rag.embedding import EmbeddingService
from app.repos.documents import chunk_repo, document_repo
from app.schemas.rag import ChunkResponse, DocumentResponse
from app.tasks.rag_tasks import index_document


async def upload(
    db: AsyncSession, storage: Storage, user_id: uuid.UUID, file, title: str | None = None
) -> Document:
    """存原始文件 → 建 documents(processing) → 同步索引（Celery 12 改 delay）。"""
    data = await file.read()
    ext = Path(file.filename or "").suffix.lower()
    path = f"documents/{user_id}/{uuid.uuid4()}{ext}"
    await asyncio.to_thread(storage.write, path, data)
    filename = file.filename or "未命名"
    doc = await document_repo.create(
        db, user_id, title or filename, filename, file.content_type, path
    )
    # RLS 上下文已由路由 set_tenant_context；index_document 内部再设（幂等），commit 归此
    await index_document(db, doc.id, path, user_id, commit=False)
    await db.commit()
    return doc


async def list_documents(db: AsyncSession, user_id: uuid.UUID, p: PageParams) -> Page:
    rows, total = await document_repo.list(db, user_id, (p.page - 1) * p.page_size, p.page_size)
    return Page(
        items=[DocumentResponse.model_validate(r) for r in rows],
        total=total, page=p.page, page_size=p.page_size,
    )


async def get_document(db: AsyncSession, user_id: uuid.UUID, doc_id: uuid.UUID) -> Document:
    doc = await document_repo.get(db, user_id, doc_id)
    if doc is None:
        raise AppException(ErrorCode.NOT_FOUND, "文档不存在", status_code=404)
    return doc


async def soft_delete(db: AsyncSession, storage: Storage, user_id: uuid.UUID, doc_id: uuid.UUID) -> None:
    """删除文档：删文件 + 记录（chunks FK CASCADE 级联）。二次确认归 07 通用模式。"""
    doc = await get_document(db, user_id, doc_id)
    await asyncio.to_thread(storage.delete, doc.storage_path)
    await document_repo.delete(db, user_id, doc_id)
    await db.commit()


async def search(
    db: AsyncSession, user_id: uuid.UUID, query: str, top_k: int = 5
) -> list[ChunkResponse]:
    """站内检索（POST /search）：embed 查询 → pgvector 余弦检索。"""
    vec = await EmbeddingService().embed(query)
    rows = await chunk_repo.vector_search(db, user_id, vec, top_k)
    return [
        ChunkResponse(id=r[0], document_id=r[1], chunk_index=r[2], content=r[3], score=r[4])
        for r in rows
    ]

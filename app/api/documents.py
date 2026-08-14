"""06 RAG：文档 API（蓝图 06 api/documents.py）。

POST /documents 上传即同步索引（Celery 12 改异步）；/search 站内检索。
DELETE 二次确认归 07 通用模式。
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_isolated, get_db, get_redis
from app.core.pagination import PageParams
from app.core.response import ok
from app.core.storage import Storage, get_storage
from app.db.models.users import User
from app.redis_client import RedisClient
from app.schemas.common import DeleteConfirmRequest
from app.schemas.rag import DocumentResponse, RetrievalQuery, RetrievalResponse
from app.services import delete_service, document_service

router = APIRouter(tags=["documents"])


@router.post("/documents")
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    chunk_strategy: str | None = Form(None),  # auto（token/semantic）/ parent_child（06 存储链路）
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
):
    doc = await document_service.upload(db, storage, user.id, file, title, chunk_strategy or "auto")
    return ok(DocumentResponse.model_validate(doc))


@router.get("/documents")
async def list_documents(
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    p = PageParams(page=page, page_size=page_size)
    return ok(await document_service.list_documents(db, user.id, p))


@router.get("/documents/{doc_id}")
async def get_document(
    doc_id: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_service.get_document(db, user.id, doc_id)
    return ok(DocumentResponse.model_validate(doc))


@router.delete("/documents/{doc_id}")
async def request_delete_document(
    doc_id: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    """二次确认第 1 步：校验归属并发 delete_token（07 通用模式）。"""
    result = await delete_service.request_delete(
        db, redis, user.id, "document", doc_id, document_service.get_document
    )
    return ok(result)


@router.post("/documents/{doc_id}/confirm")
async def confirm_delete_document(
    doc_id: uuid.UUID,
    data: DeleteConfirmRequest,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
    storage: Storage = Depends(get_storage),
):
    """二次确认第 2 步：token 校验通过，删物理文件 + 软删记录。"""
    await delete_service.confirm_delete(
        db, redis, user.id, "document", doc_id, data.delete_token,
        lambda db_, uid, did: document_service.do_soft_delete(db_, storage, uid, did),
    )
    return ok()


@router.post("/search")
async def search(
    data: RetrievalQuery,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    chunks = await document_service.search(db, user.id, data.query, data.top_k)
    return ok(RetrievalResponse(chunks=chunks))

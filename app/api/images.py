"""06 图片库：图片 API（蓝图 06 api/images.py）。

POST /images 上传、GET /images 列表、GET /images/{id}（短时 token 展示，<img> 无 header）、
GET /images/{id}/thumbnail、POST /images/search（multipart 图 或 query_text）、DELETE 二次确认。
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_isolated, get_db, get_redis
from app.core.pagination import PageParams
from app.core.response import ok
from app.core.security import verify_image_token
from app.core.storage import Storage, get_storage
from app.db.models.users import User
from app.db.tenant import set_tenant_context
from app.redis_client import RedisClient
from app.schemas.common import DeleteConfirmRequest
from app.services import delete_service
from app.rag import image_service

router = APIRouter(tags=["images"])


@router.post("/images")
async def upload_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
):
    img = await image_service.upload_image(db, storage, user.id, file)
    return ok(image_service._to_response(img, user.id))


@router.get("/images")
async def list_images(
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    return ok(await image_service.list_images(db, user.id, PageParams(page=page, page_size=page_size)))


def _require_uid(image_id: uuid.UUID, token: str) -> uuid.UUID:
    """图片展示端点鉴权：短时 query token（<img> 带不了 header，蓝图 06）。"""
    uid = verify_image_token(token, image_id)
    if uid is None:
        raise HTTPException(status_code=401, detail="token 无效或过期")
    return uid


@router.get("/images/{image_id}")
async def display_image(
    image_id: uuid.UUID,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    uid = _require_uid(image_id, token)
    await set_tenant_context(db, uid)  # RLS 上下文从 token 推导
    data, content_type = await image_service.get_image_bytes(db, uid, image_id, thumbnail=False)
    return Response(content=data, media_type=content_type)


@router.get("/images/{image_id}/thumbnail")
async def display_thumbnail(
    image_id: uuid.UUID,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    uid = _require_uid(image_id, token)
    await set_tenant_context(db, uid)
    data, content_type = await image_service.get_image_bytes(db, uid, image_id, thumbnail=True)
    return Response(content=data, media_type=content_type)


@router.post("/images/search")
async def search_images(
    file: UploadFile | None = File(None),
    query_text: str | None = Form(None),
    top_k: int = Form(10),
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    """multipart 传图（图查图）或 query_text（文字搜图），二选一。"""
    results = await image_service.search_images(
        db, user.id, query_image=file, query_text=query_text, top_k=top_k
    )
    return ok(results)


@router.delete("/images/{image_id}")
async def request_delete_image(
    image_id: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    """二次确认第 1 步（07 通用模式）。"""
    result = await delete_service.request_delete(
        db, redis, user.id, "image", image_id, image_service.get_image
    )
    return ok(result)


@router.post("/images/{image_id}/confirm")
async def confirm_delete_image(
    image_id: uuid.UUID,
    data: DeleteConfirmRequest,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    """二次确认第 2 步：删物理文件（原图+缩略图）+ 删记录。"""
    await delete_service.confirm_delete(
        db, redis, user.id, "image", image_id, data.delete_token, image_service.do_delete
    )
    return ok()

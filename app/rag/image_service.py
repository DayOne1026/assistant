"""06 图片库：图片服务（蓝图 06 image_service 段）。事务提交在此。

upload：落盘原图 + 缩略图 + CLIP 向量 + 写表；search：图查图 / 文字搜图（cosine 距离）。
emb 可注入（测试用假向量），默认全局 CLIP 单例。
"""

import asyncio
import io
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppException, ErrorCode
from app.core.pagination import Page, PageParams
from app.core.security import create_image_token
from app.core.storage import Storage
from app.db.models.images import Image
from app.rag.image_embedding import ImageEmbeddingService, get_image_embedding
from app.schemas.images import ImageResponse

_THUMB_MAX = 300


def _display_url(user_id: uuid.UUID, image_id: uuid.UUID, thumbnail: bool = False) -> str:
    """展示/缩略图端点（短时 token，<img> 直接渲染）。"""
    suffix = "/thumbnail" if thumbnail else ""
    return f"{get_settings().api_prefix}/images/{image_id}{suffix}?token={create_image_token(user_id, image_id)}"


def _to_response(img: Image, user_id: uuid.UUID) -> ImageResponse:
    return ImageResponse(
        id=img.id,
        url=_display_url(user_id, img.id),
        thumbnail_url=_display_url(user_id, img.id, thumbnail=True) if img.thumbnail_path else None,
        filename=img.filename,
        content_type=img.content_type,
        size=img.size,
        created_at=img.created_at,
    )


def _make_thumbnail(storage: Storage, user_id: uuid.UUID, data: bytes) -> str | None:
    """PIL 生成缩略图（300px）；pillow 未装则跳过（记 warning，功能不阻断）。"""
    try:
        from PIL import Image as PILImage
    except ImportError:
        from app.core.logging import get_logger

        get_logger(__name__).warning("pillow 未安装，跳过缩略图生成：pip install pillow")
        return None
    try:
        img = PILImage.open(io.BytesIO(data))
        img.thumbnail((_THUMB_MAX, _THUMB_MAX))
        buf = io.BytesIO()
        fmt = (img.format or "JPEG").upper()
        img.save(buf, format=fmt)
        thumb_path = f"media/{user_id}/{uuid.uuid4()}_thumb.{fmt.lower()}"
        storage.write(thumb_path, buf.getvalue())
        return thumb_path
    except Exception:
        return None


async def upload_image(
    db: AsyncSession, storage: Storage, user_id: uuid.UUID, file,
    emb: ImageEmbeddingService | None = None,
) -> Image:
    """存原图 + 缩略图 + CLIP 向量 + 写表。emb 注入便于测试（默认真实 CLIP 单例）。"""
    data = await file.read()
    ext = Path(file.filename or "").suffix.lower() or ".img"
    path = f"media/{user_id}/{uuid.uuid4()}{ext}"
    await asyncio.to_thread(storage.write, path, data)
    thumbnail_path = await asyncio.to_thread(_make_thumbnail, storage, user_id, data)
    emb = emb or get_image_embedding()
    vec = await asyncio.to_thread(emb.embed_image, data)
    img = Image(
        user_id=user_id,
        storage_path=path,
        thumbnail_path=thumbnail_path,
        filename=file.filename or "未命名",
        content_type=file.content_type or "application/octet-stream",
        size=len(data),
        image_embedding=vec,
        created_at=datetime.now(UTC),  # 显式设值，避免 commit 后 refresh 查 RLS 表（上下文已失效）
    )
    db.add(img)
    await db.commit()
    return img


async def list_images(db: AsyncSession, user_id: uuid.UUID, p: PageParams) -> Page:
    rows, total = await _list_page(db, user_id, (p.page - 1) * p.page_size, p.page_size)
    return Page(
        items=[_to_response(img, user_id) for img in rows],
        total=total, page=p.page, page_size=p.page_size,
    )


async def _list_page(db: AsyncSession, user_id: uuid.UUID, offset: int, limit: int):
    from sqlalchemy import func

    base = select(Image).where(Image.user_id == user_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (
        await db.execute(base.order_by(Image.created_at.desc()).offset(offset).limit(limit))
    ).scalars().all()
    return rows, total


async def get_image(db: AsyncSession, user_id: uuid.UUID, image_id: uuid.UUID) -> Image:
    img = (
        await db.execute(select(Image).where(Image.user_id == user_id, Image.id == image_id))
    ).scalar_one_or_none()
    if img is None:
        raise AppException(ErrorCode.NOT_FOUND, "图片不存在", status_code=404)
    return img


async def get_image_bytes(
    db: AsyncSession, user_id: uuid.UUID, image_id: uuid.UUID, thumbnail: bool = False
) -> tuple[bytes, str]:
    """读原图/缩略图字节 + content_type（展示端点）。"""
    img = await get_image(db, user_id, image_id)
    storage_path = img.thumbnail_path if thumbnail else img.storage_path
    if not storage_path:
        raise AppException(ErrorCode.NOT_FOUND, "无缩略图", status_code=404)
    from app.core.storage import get_storage

    data = await asyncio.to_thread(get_storage().read, storage_path)
    return data, img.content_type


async def search_images(
    db: AsyncSession, user_id: uuid.UUID,
    query_image=None, query_text: str | None = None, top_k: int = 10,
    emb: ImageEmbeddingService | None = None,
) -> list[ImageResponse]:
    """图查图（query_image 字节）或文字搜图（query_text）→ cosine 最近 top_k。"""
    if query_image is not None:
        data = await query_image.read()
        vec = await asyncio.to_thread((emb or get_image_embedding()).embed_image, data)
    elif query_text:
        vec = await asyncio.to_thread((emb or get_image_embedding()).embed_text, query_text)
    else:
        raise AppException(ErrorCode.VALIDATION_ERROR, "需提供 query_text 或查询图片")
    rows = (
        await db.execute(
            select(Image)
            .where(Image.user_id == user_id)
            .order_by(Image.image_embedding.cosine_distance(vec))
            .limit(top_k)
        )
    ).scalars().all()
    return [_to_response(img, user_id) for img in rows]


async def do_delete(db: AsyncSession, user_id: uuid.UUID, image_id: uuid.UUID) -> bool:
    """二次确认后执行：删物理文件（原图+缩略图）+ 删记录。"""
    img = (
        await db.execute(select(Image).where(Image.user_id == user_id, Image.id == image_id))
    ).scalar_one_or_none()
    if img is None:
        return False
    from app.core.storage import get_storage

    storage = get_storage()
    await asyncio.to_thread(storage.delete, img.storage_path)
    if img.thumbnail_path:
        await asyncio.to_thread(storage.delete, img.thumbnail_path)
    await db.delete(img)
    return True

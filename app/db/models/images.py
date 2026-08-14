"""06 图片库：images 表（CLIP 多模态向量，图文同一空间）。

完整落盘（storage media/{user_id}/{uuid}.{ext}）+ 元数据 + 向量检索（图查图/文字搜图）。
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UserScopedMixin


class Image(UserScopedMixin, Base):
    __tablename__ = "images"
    __table_args__ = (
        Index(
            "ix_images_embedding", "image_embedding",
            postgresql_using="hnsw", postgresql_ops={"image_embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)  # 原图
    thumbnail_path: Mapped[str | None] = mapped_column(String(500))  # 缩略图
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    phash: Mapped[int | None] = mapped_column(BigInteger)  # 感知哈希（可选去重）
    ocr_text: Mapped[str | None] = mapped_column(Text)  # 图内文字（增强文字搜图）
    description: Mapped[str | None] = mapped_column(Text)  # VLM 视觉描述
    image_embedding: Mapped[list[float]] = mapped_column(Vector(512), nullable=False)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # 文档插图来源
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

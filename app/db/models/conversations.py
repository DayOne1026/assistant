"""04 对话与意图：conversations / messages 两张表（蓝图 04 数据模型）。

messages.user_id 冗余存储（UserScopedMixin）便于隔离过滤，RLS 兜底。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UserScopedMixin


class Conversation(UserScopedMixin, TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(UserScopedMixin, Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(100))
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    wait_ms: Mapped[int | None] = mapped_column(Integer)  # 回复等待耗时（毫秒，13 前端计时落库）
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

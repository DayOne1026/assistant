"""08 通知：notifications / reminders 两张表（蓝图 08 数据模型）。

两表均带 user_id（UserScopedMixin），隔离走应用层过滤（repo 强制 user_id）——
不入 RLS（蓝图 03 迁移清单无此二表：系统任务 scan_due_reminders 需跨用户扫描）。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UserScopedMixin


class Notification(UserScopedMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # immediate/scheduled/triggered
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # ws/email
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Reminder(UserScopedMixin, TimestampMixin, Base):
    __tablename__ = "reminders"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    notify_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), default="ws")
    ref_type: Mapped[str | None] = mapped_column(String(50))
    ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/sent/cancelled

"""05 记忆与知识图谱：user_preferences / user_profiles 两张表（蓝图 05 数据模型）。

user_preferences 存用户偏好（value JSONB，key 同用户内唯一）；
user_profiles 是事实层之上的聚合画像快照，user_id 即主键（一人一份）。
"""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text, Uuid, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UserScopedMixin


class UserPreference(UserScopedMixin, TimestampMixin, Base):
    __tablename__ = "user_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_preferences_user_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="chat")
    # ponytail: 溯源引用（来源会话）；会话删除不级联，偏好独立于会话存续
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class UserProfile(Base, TimestampMixin):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    summary: Mapped[str | None] = mapped_column(Text)
    structured: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    facts_count: Mapped[int] = mapped_column(default=0, server_default="0")

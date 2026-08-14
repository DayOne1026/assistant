"""10 Skill 机制：skills 表（蓝图 10 数据模型）。

对话显式触发的多步技能，steps 存 SkillStep[]（JSONB）。无软删字段（蓝图未给），
DELETE 走 07 通用二次确认后物理删除。
"""

import uuid
from typing import Any

from sqlalchemy import Boolean, String, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UserScopedMixin


class Skill(UserScopedMixin, TimestampMixin, Base):
    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_skills_user_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

"""10 自定义 System Prompt：system_prompt_profiles 表（蓝图 10 数据模型）。

可多选 enabled（service 层 enable_profile 只 toggle 单条，对话时全部拼入系统提示）。
"""

import uuid

from sqlalchemy import Boolean, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UserScopedMixin


class SystemPromptProfile(UserScopedMixin, TimestampMixin, Base):
    __tablename__ = "system_prompt_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

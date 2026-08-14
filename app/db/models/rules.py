"""10 自动化规则：automation_rules 表（蓝图 10 数据模型）。

trigger_type=time（cron）/ event（事件名）；action_type=notify/tool。
last_run_at 供 cron 同分钟幂等去重。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UserScopedMixin


class AutomationRule(UserScopedMixin, TimestampMixin, Base):
    __tablename__ = "automation_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)  # time/event
    trigger_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)  # notify/tool
    action_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

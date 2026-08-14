"""11 审计：audit_logs / tool_call_logs 两张表（蓝图 11 数据模型）。

两表均带 user_id 但**不入 RLS**（蓝图 03 迁移清单无此二表），隔离靠 repo 强制 user_id 过滤。
tool_call_logs.call_id 关联确认流程定位（confirm/deny 时按 call_id 回写 decision/output）。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UserScopedMixin


class AuditLog(UserScopedMixin, Base):
    """业务写操作审计（删除/确认等）。"""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # create/update/delete/confirm
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ToolCallLog(UserScopedMixin, Base):
    """工具调用审计（四级权限 + 确认流程决策）。"""

    __tablename__ = "tool_call_logs"
    __table_args__ = (Index("ix_tool_call_logs_call_id", "call_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    call_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)  # read_only/create_modify/send_delete
    decision: Mapped[str] = mapped_column(String(20), nullable=False)  # pending/approved/denied
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

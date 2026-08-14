"""11 审计：audit_repo / tool_log_repo。repo 只 flush，事务提交归调用方。

两表不入 RLS（蓝图 03 清单无），隔离全靠应用层 user_id 过滤；list 必带 user_id。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit import AuditLog, ToolCallLog


class AuditRepo:
    async def create(
        self, db: AsyncSession, user_id: uuid.UUID, action: str, resource_type: str,
        resource_id: uuid.UUID | None = None, detail: dict | None = None,
        conversation_id: uuid.UUID | None = None,
        ip: str | None = None, user_agent: str | None = None,
    ) -> AuditLog:
        a = AuditLog(
            user_id=user_id, action=action, resource_type=resource_type,
            resource_id=resource_id, detail=detail, conversation_id=conversation_id,
            ip=ip, user_agent=user_agent,
        )
        db.add(a)
        await db.flush()
        return a

    async def list(
        self, db: AsyncSession, user_id: uuid.UUID, offset: int, limit: int,
        action: str | None = None, resource_type: str | None = None,
    ) -> tuple[list[AuditLog], int]:
        where = [AuditLog.user_id == user_id]
        if action:
            where.append(AuditLog.action == action)
        if resource_type:
            where.append(AuditLog.resource_type == resource_type)
        total = (
            await db.execute(select(func.count()).select_from(AuditLog).where(*where))
        ).scalar_one()
        rows = (
            await db.execute(
                select(AuditLog)
                .where(*where)
                .order_by(AuditLog.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), total


class ToolLogRepo:
    async def create(
        self, db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID | None,
        call_id: uuid.UUID, tool_name: str, level: str, decision: str,
        input_: dict[str, Any],
    ) -> ToolCallLog:
        t = ToolCallLog(
            user_id=user_id, conversation_id=conversation_id, call_id=call_id,
            tool_name=tool_name, level=level, decision=decision, input=input_,
        )
        db.add(t)
        await db.flush()
        return t

    async def list(
        self, db: AsyncSession, user_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[ToolCallLog], int]:
        where = [ToolCallLog.user_id == user_id]
        total = (
            await db.execute(select(func.count()).select_from(ToolCallLog).where(*where))
        ).scalar_one()
        rows = (
            await db.execute(
                select(ToolCallLog)
                .where(*where)
                .order_by(ToolCallLog.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), total

    async def complete(
        self, db: AsyncSession, call_id: uuid.UUID, decision: str, output: Any = None
    ) -> bool:
        """确认/拒绝后按 call_id 回写 decision/output（call_id 全局唯一）。"""
        r = await db.execute(
            update(ToolCallLog)
            .where(ToolCallLog.call_id == call_id)
            .values(decision=decision, output=output)
        )
        await db.flush()
        return r.rowcount > 0


audit_repo = AuditRepo()
tool_log_repo = ToolLogRepo()

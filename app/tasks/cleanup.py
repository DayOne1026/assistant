"""12 数据归档：软删物理清除 + 审计保留（蓝图 12 tasks 段）。

Celery worker 归 12 部署；测试直接调 async 核心（_purge_soft_deleted/_purge_audit_logs）。
软删表（conversations/documents/schedules/todos）有 RLS，逐活跃用户 set_tenant_context 删除；
audit_logs/tool_call_logs 无 RLS，直接删。
"""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.celery_app import celery_app
from app.db.models.audit import AuditLog, ToolCallLog
from app.db.models.conversations import Conversation
from app.db.models.documents import Document
from app.db.models.schedules import Schedule, Todo
from app.db.models.users import User
from app.db.session import async_session
from app.db.tenant import set_tenant_context

SOFT_DELETE_DAYS = 30  # 软删超 30 天物理清除
AUDIT_RETENTION_DAYS = 180  # 审计日志保留 180 天
SOFT_DELETE_MODELS = (Conversation, Document, Schedule, Todo)


async def _purge_soft_deleted(days: int = SOFT_DELETE_DAYS, db=None) -> int:
    """物理清除软删超 days 天的业务行（RLS 逐用户）。返回删除总数。
    db 为 None 自建连接（Celery 任务用）；测试可传 fixture db 走事务回滚。"""
    if db is None:
        async with async_session() as _db:
            return await _purge_soft_deleted_inner(_db, days)
    return await _purge_soft_deleted_inner(db, days)


async def _purge_soft_deleted_inner(db, days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    deleted = 0
    user_ids = (await db.execute(select(User.id).where(User.is_active))).scalars().all()
    for uid in user_ids:
        await set_tenant_context(db, uid)
        for model in SOFT_DELETE_MODELS:
            r = await db.execute(
                delete(model).where(model.deleted_at.is_not(None), model.deleted_at < cutoff)
            )
            deleted += r.rowcount
    await db.commit()
    return deleted


async def _purge_audit_logs(days: int = AUDIT_RETENTION_DAYS, db=None) -> int:
    """审计日志保留策略：超 days 天物理删除（无 RLS 直接删）。db 参数同 _purge_soft_deleted。"""
    if db is None:
        async with async_session() as _db:
            return await _purge_audit_logs_inner(_db, days)
    return await _purge_audit_logs_inner(db, days)


async def _purge_audit_logs_inner(db, days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    total = 0
    for model in (AuditLog, ToolCallLog):
        r = await db.execute(delete(model).where(model.created_at < cutoff))
        total += r.rowcount
    await db.commit()
    return total


@celery_app.task
def purge_soft_deleted(days: int = SOFT_DELETE_DAYS) -> int:
    return asyncio.run(_purge_soft_deleted(days))


@celery_app.task
def purge_audit_logs(days: int = AUDIT_RETENTION_DAYS) -> int:
    return asyncio.run(_purge_audit_logs(days))

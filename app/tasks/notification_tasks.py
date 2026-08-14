"""08 通知：定时任务（蓝图 08 tasks 段）。

Celery worker 归 12 部署；测试直接调 async 核心（_scan_due_reminders/_send_reminder）。
任务函数为同步 Celery 包装（独立进程无 event loop），内部 asyncio.run。
send_reminder 幂等：Redis setnx 锁（TTL 5min）+ status 置 sent，并发重复只发一次。
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.celery_app import celery_app
from app.db.models.notifications import Reminder
from app.db.models.users import User
from app.db.session import async_session
from app.db.tenant import set_tenant_context
from app.redis_client import get_redis, redis_key
from app.repos.notifications import reminder_repo
from app.services.notification_service import send_immediate

LOCK_TTL = 300  # 幂等锁 5 分钟


async def _send_reminder(reminder_id: str, db=None) -> None:
    """幂等发送：查 pending → setnx 锁 → 写 notification + WS 推送 → status=sent。

    db 为 None 自建连接（Celery 任务用）；测试可传 fixture db 走事务回滚。
    """
    if db is None:
        async with async_session() as _db:
            await _send_reminder_inner(_db, reminder_id)
    else:
        await _send_reminder_inner(db, reminder_id)


async def _send_reminder_inner(db, reminder_id: str) -> None:
    r = await reminder_repo.get_by_id(db, uuid.UUID(reminder_id))
    if r is None or r.status != "pending":
        return
    redis = await get_redis()
    if not await redis.setnx(
        redis_key("lock", r.user_id, f"reminder:{reminder_id}"), "1", ex=LOCK_TTL
    ):
        return  # 已有锁/正在处理
    await send_immediate(
        db, r.user_id, r.title, r.body or "",
        payload={
            "ref_type": r.ref_type,
            "ref_id": str(r.ref_id) if r.ref_id else None,
        },
        channel=r.channel,
    )
    await reminder_repo.mark_sent(db, uuid.UUID(reminder_id))
    await db.commit()


@celery_app.task
def send_reminder(self, reminder_id: str) -> None:
    """Celery 同步包装（bind 保留重试语义，worker 部署 12 生效）。"""
    return asyncio.run(_send_reminder(reminder_id))


async def _scan_due_reminders(limit: int = 100, db=None) -> int:
    """扫到期 pending 提醒 → 逐个发送（蓝图 beat 每 30s）。db 参数同 _send_reminder。"""
    if db is None:
        async with async_session() as _db:
            return await _scan_due_reminders_inner(_db, limit)
    return await _scan_due_reminders_inner(db, limit)


async def _scan_due_reminders_inner(db, limit: int) -> int:
    due = await reminder_repo.list_due(db, datetime.now(UTC), limit)
    for r in due:
        await _send_reminder(str(r.id), db)
    return len(due)


@celery_app.task
def scan_due_reminders(limit: int = 100) -> int:
    return asyncio.run(_scan_due_reminders(limit))


async def _scan_overdue_todos(limit: int = 100) -> int:
    """扫超期未完成任务 → 即时超期提醒（主动能力，蓝图每日 9 点）。

    todos 有 RLS 且无全局用户上下文，逐活跃用户设上下文查询。
    """
    from app.repos.todos import todo_repo  # 07 模块，惰性导入避免循环依赖

    sent = 0
    async with async_session() as db:
        user_ids = (
            await db.execute(select(User.id).where(User.is_active))
        ).scalars().all()
        for uid in user_ids:
            await set_tenant_context(db, uid)
            overdue = await todo_repo.list_overdue(db, uid, datetime.now(UTC), limit)
            for t in overdue:
                await send_immediate(
                    db, uid, "任务超期",
                    f"「{t.title}」已超过截止时间",
                    payload={"todo_id": str(t.id)},
                )
                sent += 1
    return sent


@celery_app.task
def scan_overdue_todos(limit: int = 100) -> int:
    return asyncio.run(_scan_overdue_todos(limit))


async def _purge_expired_reminders(days: int = 30) -> int:
    """清理过期 cancelled 记录（蓝图 12 归档）。reminders 无 RLS，可直接删。"""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    async with async_session() as db:
        r = await db.execute(
            delete(Reminder).where(
                Reminder.status == "cancelled", Reminder.created_at < cutoff
            )
        )
        await db.commit()
        return r.rowcount


@celery_app.task
def purge_expired_reminders(days: int = 30) -> int:
    return asyncio.run(_purge_expired_reminders(days))

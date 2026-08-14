"""08 通知：notification_repo / reminder_repo。repo 只 flush，事务提交归 service。

两表不入 RLS（蓝图 03 清单），隔离全靠应用层 user_id 过滤；
list_due/get_by_id/mark_sent 为系统任务专用（跨用户扫描，可信内部调用）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.notifications import Notification, Reminder


class NotificationRepo:
    async def create(
        self, db: AsyncSession, user_id: uuid.UUID, notif_type: str, channel: str,
        title: str, body: str, payload: dict | None = None,
    ) -> Notification:
        n = Notification(
            user_id=user_id, type=notif_type, channel=channel,
            title=title, body=body, payload=payload,
        )
        db.add(n)
        await db.flush()
        return n

    async def get(
        self, db: AsyncSession, user_id: uuid.UUID, nid: uuid.UUID
    ) -> Notification | None:
        """归属校验：user_id + id 双过滤，跨用户读返回 None。"""
        return (
            await db.execute(
                select(Notification).where(
                    Notification.id == nid, Notification.user_id == user_id
                )
            )
        ).scalar_one_or_none()

    async def list(
        self, db: AsyncSession, user_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[Notification], int]:
        """分页列表（未读在前，其余最新在前）。"""
        where = [Notification.user_id == user_id]
        total = (
            await db.execute(select(func.count()).select_from(Notification).where(*where))
        ).scalar_one()
        rows = (
            await db.execute(
                select(Notification)
                .where(*where)
                .order_by(Notification.read_at.is_(None).desc(), Notification.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), total

    async def mark_read(self, db: AsyncSession, user_id: uuid.UUID, nid: uuid.UUID) -> bool:
        r = await db.execute(
            update(Notification)
            .where(Notification.id == nid, Notification.user_id == user_id)
            .values(read_at=datetime.now().astimezone())
        )
        await db.flush()
        return r.rowcount > 0

    async def mark_all_read(self, db: AsyncSession, user_id: uuid.UUID) -> int:
        r = await db.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=datetime.now().astimezone())
        )
        await db.flush()
        return r.rowcount

    async def unread_count(self, db: AsyncSession, user_id: uuid.UUID) -> int:
        return (
            await db.execute(
                select(func.count()).select_from(Notification).where(
                    Notification.user_id == user_id, Notification.read_at.is_(None)
                )
            )
        ).scalar_one()


class ReminderRepo:
    async def create(
        self, db: AsyncSession, user_id: uuid.UUID, title: str, body: str | None,
        notify_at: datetime, channel: str, ref_type: str | None, ref_id: uuid.UUID | None,
    ) -> Reminder:
        r = Reminder(
            user_id=user_id, title=title, body=body, notify_at=notify_at,
            channel=channel, ref_type=ref_type, ref_id=ref_id,
        )
        db.add(r)
        await db.flush()
        return r

    async def get(
        self, db: AsyncSession, user_id: uuid.UUID, rid: uuid.UUID
    ) -> Reminder | None:
        return (
            await db.execute(
                select(Reminder).where(Reminder.id == rid, Reminder.user_id == user_id)
            )
        ).scalar_one_or_none()

    async def get_by_id(self, db: AsyncSession, rid: uuid.UUID) -> Reminder | None:
        """系统任务按 id 取（无 user_id 过滤，跨用户扫描用）。"""
        return (
            await db.execute(select(Reminder).where(Reminder.id == rid))
        ).scalar_one_or_none()

    async def list(
        self, db: AsyncSession, user_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[Reminder], int]:
        where = [Reminder.user_id == user_id]
        total = (
            await db.execute(select(func.count()).select_from(Reminder).where(*where))
        ).scalar_one()
        rows = (
            await db.execute(
                select(Reminder)
                .where(*where)
                .order_by(Reminder.notify_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), total

    async def cancel(self, db: AsyncSession, user_id: uuid.UUID, rid: uuid.UUID) -> bool:
        """置 cancelled（仅 pending 可取消），返回是否取消到。"""
        r = await db.execute(
            update(Reminder)
            .where(Reminder.id == rid, Reminder.user_id == user_id, Reminder.status == "pending")
            .values(status="cancelled")
        )
        await db.flush()
        return r.rowcount > 0

    async def cancel_by_ref(
        self, db: AsyncSession, user_id: uuid.UUID, ref_type: str, ref_id: uuid.UUID
    ) -> int:
        """取消某资源全部 pending 提醒（schedule update 时同步旧 reminder，07）。"""
        r = await db.execute(
            update(Reminder)
            .where(
                Reminder.user_id == user_id, Reminder.ref_type == ref_type,
                Reminder.ref_id == ref_id, Reminder.status == "pending",
            )
            .values(status="cancelled")
        )
        await db.flush()
        return r.rowcount

    async def list_due(
        self, db: AsyncSession, now: datetime, limit: int
    ) -> list[Reminder]:
        """到期待发提醒（跨用户，scan_due_reminders 用）。"""
        rows = (
            await db.execute(
                select(Reminder)
                .where(Reminder.status == "pending", Reminder.notify_at <= now)
                .order_by(Reminder.notify_at)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    async def mark_sent(self, db: AsyncSession, rid: uuid.UUID) -> None:
        await db.execute(
            update(Reminder).where(Reminder.id == rid).values(status="sent")
        )
        await db.flush()


notification_repo = NotificationRepo()
reminder_repo = ReminderRepo()

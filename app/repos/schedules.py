"""07 日程与任务：schedule_repo / todo_repo。repo 只 flush，事务提交归 service。

所有方法必带 user_id 过滤（03 约定，RLS 兜底）；软删行一律排除（deleted_at IS NULL）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.schedules import Schedule, Todo


def _now() -> datetime:
    return datetime.now().astimezone()


class ScheduleRepo:
    async def create(
        self, db: AsyncSession, user_id: uuid.UUID, title: str, description: str | None,
        start_at: datetime, end_at: datetime | None, reminder_at: datetime | None,
    ) -> Schedule:
        s = Schedule(
            user_id=user_id, title=title, description=description,
            start_at=start_at, end_at=end_at, reminder_at=reminder_at,
        )
        db.add(s)
        await db.flush()
        return s

    async def get(
        self, db: AsyncSession, user_id: uuid.UUID, sid: uuid.UUID
    ) -> Schedule | None:
        """归属校验：user_id + id 双过滤，软删视为不存在（跨用户读返回 None）。"""
        return (
            await db.execute(
                select(Schedule).where(
                    Schedule.id == sid, Schedule.user_id == user_id,
                    Schedule.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    async def list(
        self, db: AsyncSession, user_id: uuid.UUID, offset: int, limit: int,
        start_at: datetime | None = None, end_at: datetime | None = None,
    ) -> tuple[list[Schedule], int]:
        """分页列表（可选时间范围过滤，按开始时间升序，排除软删）。"""
        where = [Schedule.user_id == user_id, Schedule.deleted_at.is_(None)]
        if start_at:
            where.append(Schedule.start_at >= start_at)
        if end_at:
            where.append(Schedule.start_at <= end_at)
        total = (
            await db.execute(select(func.count()).select_from(Schedule).where(*where))
        ).scalar_one()
        rows = (
            await db.execute(
                select(Schedule)
                .where(*where)
                .order_by(Schedule.start_at)
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), total

    async def list_overlapping(
        self, db: AsyncSession, user_id: uuid.UUID, start_at: datetime, end_at: datetime | None
    ) -> list[Schedule]:
        """时间重叠检测：同用户 active 未软删，区间与 [start_at, end_at] 相交。
        end_at 为空按时间点处理（new_end = end_at or start_at，蓝图 07 重叠检测）。
        """
        new_end = end_at or start_at
        rows = (
            await db.execute(
                select(Schedule).where(
                    Schedule.user_id == user_id,
                    Schedule.deleted_at.is_(None),
                    Schedule.status == "active",
                    Schedule.start_at < new_end,
                    or_(Schedule.end_at.is_(None), Schedule.end_at > start_at),
                )
            )
        ).scalars().all()
        return list(rows)

    async def update(
        self, db: AsyncSession, user_id: uuid.UUID, sid: uuid.UUID, fields: dict
    ) -> Schedule | None:
        s = await self.get(db, user_id, sid)
        if s is None:
            return None
        for k, v in fields.items():
            setattr(s, k, v)  # 调用方 exclude_unset，显式 None 表示清空
        await db.flush()
        return s

    async def soft_delete(
        self, db: AsyncSession, user_id: uuid.UUID, sid: uuid.UUID
    ) -> bool:
        s = await self.get(db, user_id, sid)
        if s is None:
            return False
        s.deleted_at = _now()
        await db.flush()
        return True


class TodoRepo:
    async def create(
        self, db: AsyncSession, user_id: uuid.UUID, title: str, description: str | None,
        due_at: datetime | None,
    ) -> Todo:
        t = Todo(user_id=user_id, title=title, description=description, due_at=due_at)
        db.add(t)
        await db.flush()
        return t

    async def get(
        self, db: AsyncSession, user_id: uuid.UUID, tid: uuid.UUID
    ) -> Todo | None:
        return (
            await db.execute(
                select(Todo).where(
                    Todo.id == tid, Todo.user_id == user_id, Todo.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()

    async def list(
        self, db: AsyncSession, user_id: uuid.UUID, offset: int, limit: int,
        completed: bool | None = None,
    ) -> tuple[list[Todo], int]:
        """分页列表（可选 completed 过滤，排除软删）。"""
        where = [Todo.user_id == user_id, Todo.deleted_at.is_(None)]
        if completed is not None:
            where.append(Todo.completed.is_(completed))
        total = (
            await db.execute(select(func.count()).select_from(Todo).where(*where))
        ).scalar_one()
        rows = (
            await db.execute(
                select(Todo)
                .where(*where)
                .order_by(Todo.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), total

    async def update(
        self, db: AsyncSession, user_id: uuid.UUID, tid: uuid.UUID, fields: dict
    ) -> Todo | None:
        t = await self.get(db, user_id, tid)
        if t is None:
            return None
        for k, v in fields.items():
            setattr(t, k, v)  # 调用方 exclude_unset，显式 None 表示清空
        if "completed" in fields:
            t.completed_at = _now() if fields["completed"] else None
        await db.flush()
        return t

    async def set_completed(
        self, db: AsyncSession, user_id: uuid.UUID, tid: uuid.UUID, completed: bool
    ) -> Todo | None:
        t = await self.get(db, user_id, tid)
        if t is None:
            return None
        t.completed = completed
        t.completed_at = _now() if completed else None
        await db.flush()
        return t

    async def soft_delete(
        self, db: AsyncSession, user_id: uuid.UUID, tid: uuid.UUID
    ) -> bool:
        t = await self.get(db, user_id, tid)
        if t is None:
            return False
        t.deleted_at = _now()
        await db.flush()
        return True

    async def list_overdue(
        self, db: AsyncSession, user_id: uuid.UUID, now: datetime, limit: int
    ) -> list[Todo]:
        """超期未完成任务（08 scan_overdue_todos 用，RLS 上下文由调用方设置）。"""
        rows = (
            await db.execute(
                select(Todo)
                .where(
                    Todo.user_id == user_id,
                    Todo.deleted_at.is_(None),
                    Todo.completed.is_(False),
                    Todo.due_at.is_not(None),
                    Todo.due_at < now,
                )
                .order_by(Todo.due_at)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)


schedule_repo = ScheduleRepo()
todo_repo = TodoRepo()

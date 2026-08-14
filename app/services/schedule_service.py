"""07 日程服务（蓝图 07 service 段）。事务提交在此，repo 只 flush。

时间合法性（end≥start）→ 重叠检测（同用户 active 区间相交 → 08 冲突提醒，不阻止创建）
→ 建 → reminder 联动（reminder_at → 08 schedule_reminder）。
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ErrorCode
from app.core.pagination import Page, PageParams
from app.db.models.schedules import Schedule
from app.repos.notifications import reminder_repo
from app.repos.schedules import schedule_repo
from app.schemas.notification import ReminderCreate
from app.schemas.schedule import ScheduleCreate, ScheduleResponse, ScheduleUpdate
from app.services import automation_service, notification_service


def _validate_range(start_at, end_at) -> None:
    if end_at is not None and end_at < start_at:
        raise AppException(
            ErrorCode.VALIDATION_ERROR, "结束时间不能早于开始时间", status_code=400
        )


async def _sync_reminder(
    db: AsyncSession, user_id: uuid.UUID, schedule_id: uuid.UUID,
    reminder_at, title: str,
) -> None:
    """reminder_at → 建 08 reminder（ref 指向 schedule）。"""
    await notification_service.schedule_reminder(
        db, user_id,
        ReminderCreate(
            title=f"日程提醒：{title}", notify_at=reminder_at,
            ref_type="schedule", ref_id=schedule_id,
        ),
    )


async def create_schedule(
    db: AsyncSession, user_id: uuid.UUID, data: ScheduleCreate
) -> Schedule:
    _validate_range(data.start_at, data.end_at)
    conflicts = await schedule_repo.list_overlapping(db, user_id, data.start_at, data.end_at)
    s = await schedule_repo.create(
        db, user_id, data.title, data.description, data.start_at, data.end_at, data.reminder_at
    )
    if data.reminder_at:
        await _sync_reminder(db, user_id, s.id, data.reminder_at, data.title)
    await db.commit()
    if conflicts:
        # 08 冲突提醒：不阻止创建（蓝图「同用户 active 区间相交 → 08 冲突提醒」）
        await notification_service.send_immediate(
            db, user_id, "日程冲突提醒",
            f"「{data.title}」与已有日程时间重叠",
            payload={
                "schedule_id": str(s.id),
                "conflicts": [str(c.id) for c in conflicts],
            },
        )
    # 10 事件触发集成点：schedule.created（蓝图 10「07 建日程后 evaluate_event」）。
    # 规则执行失败不阻断建日程。
    try:
        await automation_service.evaluate_event(
            db, user_id, "schedule.created",
            {
                "schedule_id": str(s.id),
                "title": data.title,
                "start_at": data.start_at.isoformat(),
            },
        )
    except Exception:
        pass
    return s


async def list_schedules(
    db: AsyncSession, user_id: uuid.UUID, p: PageParams,
    start_at=None, end_at=None,
) -> Page:
    rows, total = await schedule_repo.list(
        db, user_id, (p.page - 1) * p.page_size, p.page_size, start_at, end_at
    )
    return Page(
        items=[ScheduleResponse.model_validate(r) for r in rows],
        total=total, page=p.page, page_size=p.page_size,
    )


async def get_schedule(
    db: AsyncSession, user_id: uuid.UUID, sid: uuid.UUID
) -> Schedule:
    s = await schedule_repo.get(db, user_id, sid)
    if s is None:
        raise AppException(ErrorCode.NOT_FOUND, "日程不存在", status_code=404)
    return s


async def update_schedule(
    db: AsyncSession, user_id: uuid.UUID, sid: uuid.UUID, data: ScheduleUpdate
) -> Schedule:
    cur = await get_schedule(db, user_id, sid)
    fields = data.model_dump(exclude_unset=True)
    _validate_range(fields.get("start_at", cur.start_at), fields.get("end_at", cur.end_at))
    s = await schedule_repo.update(db, user_id, sid, fields)
    if "reminder_at" in fields:
        # reminder 变更同步 08：取消旧 pending，新值非空则重建
        await reminder_repo.cancel_by_ref(db, user_id, "schedule", sid)
        if fields["reminder_at"] is not None:
            await _sync_reminder(db, user_id, sid, fields["reminder_at"], cur.title)
    await db.commit()
    return s

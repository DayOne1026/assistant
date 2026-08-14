"""07 日程 API（蓝图 07 API 层）。

DELETE 二次确认：第一次 DELETE /schedules/{id} 返回 delete_token；
POST /schedules/{id}/confirm body {delete_token} 才真删（软删）。
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_isolated, get_db, get_redis
from app.core.pagination import PageParams
from app.core.response import ok
from app.db.models.users import User
from app.redis_client import RedisClient
from app.repos.schedules import schedule_repo
from app.schemas.common import DeleteConfirmRequest
from app.schemas.schedule import ScheduleCreate, ScheduleResponse, ScheduleUpdate
from app.services import delete_service, schedule_service

router = APIRouter(tags=["schedules"])


@router.post("/schedules")
async def create_schedule(
    data: ScheduleCreate,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    s = await schedule_service.create_schedule(db, user.id, data)
    return ok(ScheduleResponse.model_validate(s))


@router.get("/schedules")
async def list_schedules(
    page: int = 1,
    page_size: int = 20,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    p = PageParams(page=page, page_size=page_size)
    return ok(await schedule_service.list_schedules(db, user.id, p, start_at, end_at))


@router.get("/schedules/{sid}")
async def get_schedule(
    sid: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    s = await schedule_service.get_schedule(db, user.id, sid)
    return ok(ScheduleResponse.model_validate(s))


@router.patch("/schedules/{sid}")
async def update_schedule(
    sid: uuid.UUID,
    data: ScheduleUpdate,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    s = await schedule_service.update_schedule(db, user.id, sid, data)
    return ok(ScheduleResponse.model_validate(s))


@router.delete("/schedules/{sid}")
async def request_delete_schedule(
    sid: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    result = await delete_service.request_delete(
        db, redis, user.id, "schedule", sid, schedule_service.get_schedule
    )
    return ok(result)


@router.post("/schedules/{sid}/confirm")
async def confirm_delete_schedule(
    sid: uuid.UUID,
    data: DeleteConfirmRequest,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    await delete_service.confirm_delete(
        db, redis, user.id, "schedule", sid, data.delete_token, schedule_repo.soft_delete
    )
    return ok()

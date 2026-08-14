"""10 Skill API（蓝图 10 API 层）。

DELETE 二次确认（07 通用模式）：DELETE /skills/{id} 发 delete_token，
POST /skills/{id}/confirm body {delete_token} 才物理删除。
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_isolated, get_db, get_redis
from app.core.pagination import PageParams
from app.core.response import ok
from app.db.models.users import User
from app.redis_client import RedisClient
from app.schemas.common import DeleteConfirmRequest
from app.schemas.skill import SkillCreate, SkillResponse, SkillRunRequest
from app.services import delete_service, skill_service

router = APIRouter(tags=["skills"])


@router.post("/skills")
async def create_skill(
    data: SkillCreate,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    s = await skill_service.create_skill(db, user.id, data)
    return ok(SkillResponse.model_validate(s))


@router.get("/skills")
async def list_skills(
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    p = PageParams(page=page, page_size=page_size)
    return ok(await skill_service.list_skills(db, user.id, p))


@router.get("/skills/{skill_id}")
async def get_skill(
    skill_id: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    s = await skill_service.get_skill(db, user.id, skill_id)
    return ok(SkillResponse.model_validate(s))


@router.post("/skills/{skill_id}/run")
async def run_skill(
    skill_id: uuid.UUID,
    data: SkillRunRequest,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    return ok(await skill_service.run_skill(db, user.id, skill_id, data.params))


@router.delete("/skills/{skill_id}")
async def request_delete_skill(
    skill_id: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    result = await delete_service.request_delete(
        db, redis, user.id, "skill", skill_id, skill_service.get_skill
    )
    return ok(result)


@router.post("/skills/{skill_id}/confirm")
async def confirm_delete_skill(
    skill_id: uuid.UUID,
    data: DeleteConfirmRequest,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    await delete_service.confirm_delete(
        db, redis, user.id, "skill", skill_id, data.delete_token, skill_service.delete_skill
    )
    return ok()

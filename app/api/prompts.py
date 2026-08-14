"""10 自定义 System Prompt API（蓝图 10 API 层，路径 /prompts）。

enable 切换互斥：POST /prompts/{id}/enable 先禁用其余再启用目标。
DELETE 二次确认（07 通用模式）：DELETE 发 delete_token，POST confirm 才物理删除。
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
from app.schemas.prompt import PromptCreate, PromptEnableRequest, PromptResponse
from app.services import delete_service
from app.services.prompt_assembler import (
    create_profile,
    delete_profile,
    enable_profile,
    get_profile,
    list_profiles,
)

router = APIRouter(tags=["prompts"])


@router.post("/prompts")
async def create_prompt(
    data: PromptCreate,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    p = await create_profile(db, user.id, data)
    return ok(PromptResponse.model_validate(p))


@router.get("/prompts")
async def list_prompts(
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    p = PageParams(page=page, page_size=page_size)
    return ok(await list_profiles(db, user.id, p))


@router.post("/prompts/{pid}/enable")
async def enable_prompt(
    pid: uuid.UUID,
    data: PromptEnableRequest,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    await enable_profile(db, user.id, pid, data.enabled)
    return ok()


@router.delete("/prompts/{pid}")
async def request_delete_prompt(
    pid: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    result = await delete_service.request_delete(
        db, redis, user.id, "prompt", pid, get_profile
    )
    return ok(result)


@router.post("/prompts/{pid}/confirm")
async def confirm_delete_prompt(
    pid: uuid.UUID,
    data: DeleteConfirmRequest,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    await delete_service.confirm_delete(
        db, redis, user.id, "prompt", pid, data.delete_token, delete_profile
    )
    return ok()

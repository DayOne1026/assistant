"""10 自动化规则 API（蓝图 10 API 层，路径 /automation/rules）。

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
from app.schemas.rule import RuleCreate, RuleResponse, RuleUpdate
from app.services import automation_service, delete_service

router = APIRouter(tags=["automation"])


@router.post("/automation/rules")
async def create_rule(
    data: RuleCreate,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    r = await automation_service.create_rule(db, user.id, data)
    return ok(RuleResponse.model_validate(r))


@router.get("/automation/rules")
async def list_rules(
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    p = PageParams(page=page, page_size=page_size)
    return ok(await automation_service.list_rules(db, user.id, p))


@router.get("/automation/rules/{rule_id}")
async def get_rule(
    rule_id: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    r = await automation_service.get_rule(db, user.id, rule_id)
    return ok(RuleResponse.model_validate(r))


@router.patch("/automation/rules/{rule_id}")
async def update_rule(
    rule_id: uuid.UUID,
    data: RuleUpdate,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    r = await automation_service.update_rule(db, user.id, rule_id, data)
    return ok(RuleResponse.model_validate(r))


@router.delete("/automation/rules/{rule_id}")
async def request_delete_rule(
    rule_id: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    result = await delete_service.request_delete(
        db, redis, user.id, "automation_rule", rule_id, automation_service.get_rule
    )
    return ok(result)


@router.post("/automation/rules/{rule_id}/confirm")
async def confirm_delete_rule(
    rule_id: uuid.UUID,
    data: DeleteConfirmRequest,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    await delete_service.confirm_delete(
        db, redis, user.id, "automation_rule", rule_id, data.delete_token,
        automation_service.delete_rule,
    )
    return ok()

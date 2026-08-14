"""09 集成：/integrations API（蓝图 09 api/integrations.py）。

POST /integrations/{provider}/auth-url（redirect_uri → AuthUrlResponse）；
POST /integrations/{provider}/callback（code+state → 加密落库）；
GET /integrations 列表；DELETE /integrations/{id} 撤销走 07 二次确认。
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_isolated, get_db, get_redis
from app.core.response import ok
from app.db.models.users import User
from app.redis_client import RedisClient
from app.schemas.common import DeleteConfirmRequest
from app.schemas.integration import OAuthCallbackRequest, OAuthStartRequest
from app.services import delete_service, integration_service
from app.services.integration_service import IntegrationService

router = APIRouter(tags=["integrations"])


@router.post("/integrations/{provider}/auth-url")
async def auth_url(
    provider: str,
    data: OAuthStartRequest,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    return ok(await IntegrationService(db, redis).start_oauth(user.id, provider, data.redirect_uri))


@router.post("/integrations/{provider}/callback")
async def callback(
    provider: str,
    data: OAuthCallbackRequest,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    return ok(await IntegrationService(db, redis).complete_oauth(user.id, provider, data))


@router.get("/integrations")
async def list_integrations(
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    return ok(await IntegrationService(db, redis).list(user.id))


@router.delete("/integrations/{integration_id}")
async def request_revoke(
    integration_id: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    """二次确认第 1 步（07 通用模式）。"""
    result = await delete_service.request_delete(
        db, redis, user.id, "integration", integration_id, integration_service.verify_integration
    )
    return ok(result)


@router.post("/integrations/{integration_id}/confirm")
async def confirm_revoke(
    integration_id: uuid.UUID,
    data: DeleteConfirmRequest,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    """二次确认第 2 步：外部 revoke + 置 revoked_at。"""
    await delete_service.confirm_delete(
        db, redis, user.id, "integration", integration_id, data.delete_token,
        integration_service.do_revoke,
    )
    return ok()

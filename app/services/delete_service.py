"""07 通用二次确认删除（蓝图 07 service 段，日程/任务/文档/会话共用）。

流程：request_delete 校验归属→发 delete_token（Redis 存 5min）；
confirm_delete 校验 token 匹配→软删（deleted_at=now）→写 audit（11 施工时补）。
"""

import secrets
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.audit_service import log_audit
from app.core.exceptions import AppException, ErrorCode
from app.redis_client import RedisClient, redis_key
from app.schemas.common import DeleteRequestResponse

CONFIRM_TTL = 300  # token 5 分钟有效


async def request_delete(
    db: AsyncSession, redis: RedisClient, user_id: uuid.UUID,
    resource_type: str, resource_id: uuid.UUID,
    verify: Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[None]],
) -> DeleteRequestResponse:
    """校验归属→生成 token→Redis app:confirm:{user_id}:{resource_type}:{id} 存 5min。"""
    await verify(db, user_id, resource_id)  # 归属校验，不存在抛 404
    token = secrets.token_urlsafe(32)
    await redis.set(
        redis_key("confirm", user_id, resource_type, str(resource_id)), token, ex=CONFIRM_TTL
    )
    return DeleteRequestResponse(
        resource_type=resource_type, resource_id=resource_id,
        delete_token=token, expires_in=CONFIRM_TTL,
    )


async def confirm_delete(
    db: AsyncSession, redis: RedisClient, user_id: uuid.UUID,
    resource_type: str, resource_id: uuid.UUID, token: str,
    do_delete: Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[bool]],
) -> None:
    """校验 token 匹配→软删→写 audit（11 注入）。失败抛 DELETE_NOT_CONFIRMED。"""
    key = redis_key("confirm", user_id, resource_type, str(resource_id))
    stored = await redis.get(key)
    if stored is None or stored != token:
        raise AppException(
            ErrorCode.DELETE_NOT_CONFIRMED, "删除未确认或已过期", status_code=400
        )
    await redis.delete(key)
    deleted = await do_delete(db, user_id, resource_id)
    if not deleted:
        raise AppException(ErrorCode.NOT_FOUND, "资源不存在", status_code=404)
    # 11：删除审计（audit_logs 无 RLS，repo 双过滤；log_audit 只 flush，随下方 commit 提交）
    await log_audit(db, user_id, "delete", resource_type, resource_id, detail={"deleted": True})
    await db.commit()

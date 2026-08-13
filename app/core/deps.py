"""依赖注入汇总。

get_current_user（02）、get_current_user_isolated（03）；get_tool_registry 依赖 11。
"""

import uuid

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppException, ErrorCode
from app.core.security import blacklist_key, decode_access_token, oauth2_scheme
from app.core.storage import get_storage
from app.db.models.users import User
from app.db.session import get_db
from app.db.tenant import set_tenant_context
from app.neo4j_client import get_neo4j
from app.redis_client import RedisClient, get_redis
from app.repos.users import user_repo


async def get_current_user(
    creds: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
) -> User:
    """Bearer 校验 + 黑名单检查（02 蓝图 deps 段）。"""
    payload = decode_access_token(creds)
    if await redis.get(blacklist_key(payload["jti"])):
        raise AppException(ErrorCode.TOKEN_EXPIRED, "token 已撤销", status_code=401)
    user = await user_repo.get_by_id(db, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise AppException(ErrorCode.INVALID_TOKEN, "用户不存在或已禁用", status_code=401)
    return user


async def get_current_user_isolated(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """03 隔离接入：解析出用户后设 RLS 上下文，再进业务查询。"""
    await set_tenant_context(db, user.id)
    return user


def get_tool_registry():
    """Agent 工具注册表（11）。"""
    raise NotImplementedError("11 审计与安全模块实现")

"""02 认证：/auth/{register,login,refresh,logout}（蓝图 02 API 表）。
统一响应：全部经 ApiResponse 包装（00 约定）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_redis
from app.core.response import ok
from app.core.security import oauth2_scheme
from app.redis_client import RedisClient
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
async def register(
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    """注册即登录？否，注册后前端调 login。"""
    user = await AuthService(db, redis).register_user(data)
    return ok(UserResponse.model_validate(user))


@router.post("/login")
async def login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    return ok(await AuthService(db, redis).login(data))


@router.post("/refresh")
async def refresh(
    data: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    return ok(await AuthService(db, redis).refresh(data.refresh_token))


@router.post("/logout")
async def logout(
    payload: LogoutRequest,
    creds: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    """access jti 入 Redis 黑名单；refresh 若给则 revoke。"""
    await AuthService(db, redis).logout(creds, payload.refresh_token)
    return ok()

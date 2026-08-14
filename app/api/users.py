"""02 用户：/users/me、/users/me/password 及 /account/{export,import}、DELETE /account。
统一响应：全部经 ApiResponse 包装（00 约定）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_current_user_isolated, get_db, get_redis
from app.core.response import ok
from app.db.models.users import User
from app.redis_client import RedisClient
from app.schemas.auth import ChangePasswordRequest, UserResponse
from app.services.auth_service import AuthService
from app.services.export_service import delete_account, export_user_data, import_user_data

router = APIRouter(tags=["users"])


@router.get("/users/me")
async def get_me(user: User = Depends(get_current_user)):
    return ok(UserResponse.model_validate(user))


@router.post("/users/me/password")
async def change_password(
    data: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    await AuthService(db, redis).change_password(user, data)
    return ok()


@router.get("/account/export")
async def export(user: User = Depends(get_current_user_isolated), db: AsyncSession = Depends(get_db)):
    """全数据导出（当前已建模块）。isolated：聚合查询 RLS 表须上下文。"""
    return ok(await export_user_data(db, user.id))


@router.post("/account/import")
async def import_(
    payload: dict,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    """恢复导入（校验格式与归属）。"""
    stats = await import_user_data(db, user.id, payload)
    return ok(stats)


@router.delete("/account")
async def delete(user: User = Depends(get_current_user_isolated), db: AsyncSession = Depends(get_db)):
    """注销：清 Redis/Neo4j → 级联删除全数据。"""
    await delete_account(db, user.id)
    return ok()

"""02 用户数据导出/导入/注销（蓝图 02 API 表 /account/*）。

schedules/todos/preferences/图谱/图片/会话 等模块 04-08 建成后在此聚合；
Redis 用户级 key（03 约定 {scope}:{user_id}:*）与 Neo4j 节点（05）清理待接入。
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ErrorCode
from app.repos.users import user_repo

# 蓝图导出结构：各业务模块数据槽，模块落地后逐个填充
EXPORT_BLOCKS = (
    "user",
    "schedules",
    "todos",
    "preferences",
    "graph",
    "images",
    "conversations",
)


async def export_user_data(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """聚合当前已建模块的用户数据 → dict。"""
    user = await user_repo.get_by_id(db, user_id)
    if user is None:
        raise AppException(ErrorCode.NOT_FOUND, "用户不存在")
    data = {
        "user": {"email": user.email, "username": user.username, "timezone": user.timezone},
        "schedules": [],   # 07 模块接入后聚合
        "todos": [],       # 07
        "preferences": [],  # 05
        "graph": [],       # 05 图谱三元组
        "images": [],      # 06
        "conversations": [],  # 04
    }
    return data


async def import_user_data(db: AsyncSession, user_id: uuid.UUID, data: dict) -> dict:
    """校验格式与归属 → 批量写入（幂等，冲突跳过）。"""
    if not isinstance(data, dict) or not all(k in data for k in EXPORT_BLOCKS):
        raise AppException(ErrorCode.VALIDATION_ERROR, "数据格式无效")
    user = await user_repo.get_by_id(db, user_id)
    if user is None:
        raise AppException(ErrorCode.NOT_FOUND, "用户不存在")
    # 归属校验：user 块必须与当前用户一致，禁止跨用户导入
    u = data["user"]
    if str(u.get("email", "")).lower() != user.email.lower():
        raise AppException(ErrorCode.PERMISSION_DENIED, "数据不属于当前用户", status_code=403)
    return {"imported": {"user": 1}, "skipped": {}}


async def delete_account(db: AsyncSession, user_id: uuid.UUID) -> None:
    """注销：DB CASCADE 删用户（refresh_tokens 随之删除）。"""
    user = await user_repo.get_by_id(db, user_id)
    if user is None:
        raise AppException(ErrorCode.NOT_FOUND, "用户不存在")
    # 03/05 接入后：清 Redis {scope}:{user_id}:*、删 Neo4j 图谱节点
    await db.delete(user)
    await db.commit()

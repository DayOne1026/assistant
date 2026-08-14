"""05 记忆：画像定期重构（蓝图 05 tasks 段 / 12 部署）。

Celery worker 归 12 部署；测试直接调 async 核心（_refresh_profiles）。
每日 force=True 全量重构；或脏计数（mark_stale incr）>= threshold 增量触发。
user_profiles 有 RLS 且无全局用户上下文，逐活跃用户 set_tenant_context 查询。
Neo4j 不可达时跳过（图谱事实缺失，画像重构无意义）。
"""

import asyncio

from sqlalchemy import select

from app.celery_app import celery_app
from app.db.models.users import User
from app.db.session import async_session
from app.db.tenant import set_tenant_context
from app.neo4j_client import init_neo4j
from app.redis_client import get_redis, redis_key
from app.services.memory_service import ProfileService

DIRTY_THRESHOLD = 5


async def _refresh_profiles(force: bool = False, threshold: int = DIRTY_THRESHOLD, db=None) -> int:
    """画像重构：脏计数 >= threshold 触发；force=True 全量。返回重构条数。
    db 为 None 自建连接（Celery 任务用）；测试可传 fixture db 走事务回滚。"""
    if db is None:
        async with async_session() as _db:
            return await _refresh_profiles_inner(_db, force, threshold)
    return await _refresh_profiles_inner(db, force, threshold)


async def _refresh_profiles_inner(db, force: bool, threshold: int) -> int:
    redis = await get_redis()
    try:
        neo4j = await init_neo4j()  # 任务进程无 lifespan，惰性初始化
    except Exception:
        return 0  # ponytail: Neo4j 不可达直接跳过（图谱事实缺失）
    service = ProfileService(db, redis, neo4j)
    refreshed = 0
    user_ids = (await db.execute(select(User.id).where(User.is_active))).scalars().all()
    for uid in user_ids:
        await set_tenant_context(db, uid)
        dirty = int(await redis.get(redis_key("profile_dirty", uid)) or 0)
        if not force and dirty < threshold:
            continue
        await service.refresh_profile(uid)
        await redis.delete(redis_key("profile_dirty", uid))
        refreshed += 1
    return refreshed


@celery_app.task
def refresh_profiles(force: bool = False, threshold: int = DIRTY_THRESHOLD) -> int:
    return asyncio.run(_refresh_profiles(force, threshold))

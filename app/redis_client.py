import secrets
import time
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings

_UNLOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class RedisClient:
    """redis-py async，decode_responses=True。"""

    def __init__(self, url: str):
        self._client = aioredis.from_url(url, decode_responses=True)
        self._locks: dict[str, str] = {}

    async def initialize(self) -> None:
        await self._client.ping()

    async def close(self) -> None:
        await self._client.aclose()

    # --- KV ---
    async def get(self, key: str) -> str | None:
        return await self._client.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> None:
        await self._client.set(key, value, ex=ex)

    async def setnx(self, key: str, value: Any, ex: int | None = None) -> bool:
        """SET NX EX 原子写（幂等/锁用）。"""
        return bool(await self._client.set(key, value, ex=ex, nx=True))

    async def delete(self, key: str) -> int:
        return await self._client.delete(key)

    async def expire(self, key: str, seconds: int) -> bool:
        return bool(await self._client.expire(key, seconds))

    async def incr(self, key: str) -> int:
        return await self._client.incr(key)

    # --- Hash ---
    async def hset(self, key: str, field: Any, value: Any) -> int:
        return await self._client.hset(key, field, value)

    async def hget(self, key: str, field: Any) -> str | None:
        return await self._client.hget(key, field)

    async def hgetall(self, key: str) -> dict:
        return await self._client.hgetall(key)

    async def hdel(self, key: str, *fields: Any) -> int:
        return await self._client.hdel(key, *fields)

    # --- List ---
    async def rpush(self, key: str, *values: Any) -> int:
        return await self._client.rpush(key, *values)

    async def lrange(self, key: str, start: int, stop: int) -> list:
        return await self._client.lrange(key, start, stop)

    async def lrem(self, key: str, count: int, value: Any) -> int:
        return await self._client.lrem(key, count, value)

    # --- ZSet ---
    async def zadd(self, key: str, mapping: dict, **kwargs) -> int:
        return await self._client.zadd(key, mapping, **kwargs)

    async def zrem(self, key: str, *members: Any) -> int:
        return await self._client.zrem(key, *members)

    async def zcard(self, key: str) -> int:
        return await self._client.zcard(key)

    # --- 分布式锁 ---
    async def acquire_lock(self, key: str, ttl: int = 10) -> bool:
        token = f"{time.time_ns()}-{secrets.token_hex(4)}"
        if await self.setnx(key, token, ex=ttl):
            self._locks[key] = token
            return True
        return False

    async def release_lock(self, key: str) -> None:
        token = self._locks.pop(key, None)
        if token is None:
            return
        await self._client.eval(_UNLOCK_SCRIPT, 1, key, token)

    # --- 滑动窗口限流 ---
    async def sliding_window_rate_limit(self, key: str, max_count: int, window: int) -> bool:
        """清窗口外 → 超 max 拒 → zadd 当前 → 续期 → True 放行。"""
        now = time.time()
        await self._client.zremrangebyscore(key, 0, now - window)
        if await self._client.zcard(key) >= max_count:
            return False
        await self._client.zadd(key, {secrets.token_hex(8): now})
        await self._client.expire(key, window)
        return True


_redis: RedisClient | None = None


async def init_redis() -> RedisClient:
    global _redis
    if _redis is None:
        _redis = RedisClient(get_settings().redis_url)
        await _redis.initialize()
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None


async def get_redis() -> RedisClient:
    """FastAPI 依赖：全局单例（startup 时 init）。"""
    if _redis is None:
        raise RuntimeError("Redis 未初始化，请先启动应用")
    return _redis

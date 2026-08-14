"""12 统一 HTTP 客户端（蓝图 12 core/http_client.py）。

外部服务调用统一封装：超时 + 重试（指数退避）+ 熔断 + 降级。
熔断：连续失败 5 次 → 60s 内直接走 fallback（Redis 计数，滑窗过期即恢复）。
"""

import asyncio
from typing import Any, Callable

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

_CIRCUIT_FAIL_LIMIT = 5
_CIRCUIT_WINDOW = 60


class HttpClient:
    """无状态单例使用；熔断状态存 Redis，多实例共享。"""

    async def request(
        self,
        method: str,
        url: str,
        *,
        timeout: float = 10,
        retries: int = 2,
        fallback: Callable[[], Any] | None = None,
        headers: dict | None = None,
        json: Any = None,
        data: Any = None,
    ) -> httpx.Response | None:
        """超时 10s；失败重试 2 次（退避 0.5/1s）；仍失败走 fallback 降级；
        熔断：连续失败 5 次 → 60s 内直接走 fallback（状态存 Redis）。
        json 传 JSON body，data 传表单编码（OAuth token 端点用，09）。"""
        host = url.split("/")[2]
        circuit_key = f"app:circuit:{host}"
        if await self._circuit_open(circuit_key):
            logger.warning("circuit open, fallback: %s", url)
            return self._call_fallback(fallback)
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.request(method, url, headers=headers, json=json, data=data)
                if response.status_code < 500:  # 4xx 客户端错误：不重试不计数
                    await self._reset_circuit(circuit_key)
                    return response
                last_error = RuntimeError(f"{url} status={response.status_code}")
            except httpx.HTTPError as exc:
                last_error = exc
            if attempt < retries:
                await asyncio.sleep(0.5 * (2**attempt))  # 退避 0.5/1s
        await self._record_failure(circuit_key)
        logger.warning("request failed after %s retries: %s | %s", retries, url, last_error)
        return self._call_fallback(fallback)

    # --- 熔断（Redis 计数，TTL 60s 滑窗） ---
    async def _circuit_open(self, key: str) -> bool:
        try:
            from app.redis_client import get_redis

            count = int(await (await get_redis()).get(key) or 0)
            return count >= _CIRCUIT_FAIL_LIMIT
        except Exception:
            return False  # ponytail: Redis 挂时 fail-open，熔断不挡业务

    async def _record_failure(self, key: str) -> None:
        try:
            from app.redis_client import get_redis

            redis = await get_redis()
            await redis.incr(key)
            await redis.expire(key, _CIRCUIT_WINDOW)
        except Exception:
            pass

    async def _reset_circuit(self, key: str) -> None:
        try:
            from app.redis_client import get_redis

            await (await get_redis()).delete(key)
        except Exception:
            pass

    @staticmethod
    def _call_fallback(fallback: Callable[[], Any] | None) -> Any:
        return fallback() if callable(fallback) else fallback

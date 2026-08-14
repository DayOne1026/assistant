"""12 幂等中间件（蓝图 12 middleware/idempotency.py）。

写请求带 Idempotency-Key header：Redis 存 `app:idem:{user}:{key}` 响应（TTL 1h），
重复提交返回缓存响应；并发同 key（setnx 锁被占）→ 2002 幂等冲突。
仅处理带 header 的写请求，其余透传，不影响既有调用。
"""

import json
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.exceptions import ErrorCode
from app.core.response import fail
from app.core.security import decode_access_token
from app.redis_client import get_redis

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_IDEMPOTENCY_TTL = 3600  # 缓存响应 1h（同时作并发锁 TTL）


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        idem_key = request.headers.get("idempotency-key")
        if request.method not in _WRITE_METHODS or not idem_key:
            return await call_next(request)

        cache_key = f"app:idem:{_user_id(request)}:{idem_key}"
        redis = await get_redis()

        cached = await redis.get(cache_key)
        if cached is not None and cached != "processing":
            return _response_from_cache(cached)

        # 并发同 key：首个请求持锁处理，重复并发请求直接 2002
        if not await redis.setnx(cache_key, "processing", ex=_IDEMPOTENCY_TTL):
            return JSONResponse(
                status_code=409,
                content=fail(ErrorCode.IDEMPOTENCY_CONFLICT, "并发重复请求，请稍后重试").model_dump(),
            )

        # BaseHTTPMiddleware 把下游响应包成 _StreamingResponse，需消费 body_iterator
        response = await call_next(request)
        body = b"".join([chunk async for chunk in response.body_iterator])
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        await redis.set(
            cache_key,
            json.dumps(
                {
                    "status_code": response.status_code,
                    "headers": headers,
                    "body": body.decode("utf-8", errors="replace"),
                },
                ensure_ascii=False,
            ),
            ex=_IDEMPOTENCY_TTL,
        )
        return Response(content=body, status_code=response.status_code, headers=headers)


def _user_id(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            return decode_access_token(auth[7:])["sub"]
        except Exception:
            pass  # 坏 token 交给认证依赖处理，按 IP 维度幂等
    return request.client.host if request.client else "anon"


def _response_from_cache(raw: str) -> JSONResponse:
    data: dict[str, Any] = json.loads(raw)
    return JSONResponse(
        status_code=data["status_code"],
        content=json.loads(data["body"]),
        headers=data["headers"],
    )

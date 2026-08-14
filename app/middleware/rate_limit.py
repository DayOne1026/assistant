"""11 限流中间件（蓝图 11 RateLimitMiddleware）。

Redis 滑动窗口（01 sliding_window_rate_limit，redis_client 已实现）；
key = 已认证 user_id 或 client IP + 路由路径；豁免 /health /docs /openapi.json；
settings.rate_limit_enabled 关则透传（测试环境关闭，防共享 IP 撞窗口）。
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.exceptions import ErrorCode
from app.core.response import fail
from app.core.security import decode_access_token
from app.redis_client import get_redis

settings = get_settings()

_EXEMPT_PATHS = ("/health", "/docs", "/openapi.json")


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.rate_limit_enabled or request.url.path in _EXEMPT_PATHS:
            return await call_next(request)
        key = request.client.host if request.client else "unknown"
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            try:
                key = decode_access_token(auth[7:])["sub"]  # 已认证按 user_id
            except Exception:
                pass  # 坏 token 交给认证依赖处理，按 IP 限流
        redis = await get_redis()
        allowed = await redis.sliding_window_rate_limit(
            f"app:ratelimit:{key}:{request.url.path}",
            settings.rate_limit_max, settings.rate_limit_window_seconds,
        )
        if not allowed:
            return JSONResponse(
                status_code=429,
                content=fail(ErrorCode.RATE_LIMITED, "请求过于频繁").model_dump(),
            )
        return await call_next(request)

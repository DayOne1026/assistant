from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.exceptions import AppException, app_exception_handler
from app.neo4j_client import close_neo4j, init_neo4j
from app.redis_client import close_redis, init_redis

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup：初始化 Redis/Neo4j 单例
    await init_redis()
    await init_neo4j()
    yield
    # shutdown
    await close_neo4j()
    await close_redis()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS 白名单（不用 *）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 业务异常 → ApiResponse
    app.add_exception_handler(AppException, app_exception_handler)

    # 路由（02）：认证与用户
    from app.api import auth, users

    app.include_router(auth.router, prefix=settings.api_prefix)
    app.include_router(users.router, prefix=settings.api_prefix)

    # 路由（04）：对话
    from app.api import chat

    app.include_router(chat.router, prefix=settings.api_prefix)

    # 中间件（11）：RateLimitMiddleware / HarmfulFilterMiddleware
    # 路由注册（03-11）：各模块 router，prefix=settings.api_prefix

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    # PyCharm 直接 Run 本文件即启动；传 app 对象避免 import 字符串路径问题
    uvicorn.run(app, host="0.0.0.0", port=8000)

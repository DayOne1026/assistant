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

    # 中间件（11）：限流 + 有害过滤
    from app.middleware.harmful import HarmfulFilterMiddleware
    from app.middleware.rate_limit import RateLimitMiddleware

    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(HarmfulFilterMiddleware)

    # 中间件（12）：幂等（写请求 Idempotency-Key）
    from app.middleware.idempotency import IdempotencyMiddleware

    app.add_middleware(IdempotencyMiddleware)

    # 可观测（12）：请求 span 中间件
    from app.core.telemetry import setup_telemetry

    setup_telemetry(app)

    # 业务异常 → ApiResponse
    app.add_exception_handler(AppException, app_exception_handler)

    # 路由（02）：认证与用户
    from app.api import auth, users

    app.include_router(auth.router, prefix=settings.api_prefix)
    app.include_router(users.router, prefix=settings.api_prefix)

    # 路由（04）：对话
    from app.api import chat

    app.include_router(chat.router, prefix=settings.api_prefix)

    # 路由（05）：记忆与知识图谱
    from app.api import memory

    app.include_router(memory.router, prefix=settings.api_prefix)

    # 路由（06）：文档 RAG
    from app.api import documents

    app.include_router(documents.router, prefix=settings.api_prefix)

    # 路由（06）：图片库
    from app.api import images

    app.include_router(images.router, prefix=settings.api_prefix)

    # 路由（08）：通知/提醒（含 WS /ws）
    from app.api import notifications

    app.include_router(notifications.router, prefix=settings.api_prefix)

    # 路由（07）：日程与任务
    from app.api import schedules, todos

    app.include_router(schedules.router, prefix=settings.api_prefix)
    app.include_router(todos.router, prefix=settings.api_prefix)

    # 路由（10）：Skill / 自动化规则 / System Prompt
    from app.api import prompts, rules, skills

    app.include_router(skills.router, prefix=settings.api_prefix)
    app.include_router(rules.router, prefix=settings.api_prefix)
    app.include_router(prompts.router, prefix=settings.api_prefix)

    # 路由（09）：外部服务集成
    from app.api import integrations

    app.include_router(integrations.router, prefix=settings.api_prefix)

    # 路由（11）：审计
    from app.api import audit

    app.include_router(audit.router, prefix=settings.api_prefix)

    # 健康检查（12）：依次 ping DB/Redis/Neo4j，compose healthcheck 复用
    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        from sqlalchemy import text

        from app.db.session import async_session
        from app.neo4j_client import get_neo4j
        from app.redis_client import get_redis

        checks: list[dict] = []
        ok = True
        try:
            async with async_session() as s:
                await s.execute(text("SELECT 1"))
            checks.append({"name": "database", "status": "up"})
        except Exception:
            ok = False
            checks.append({"name": "database", "status": "down"})
        try:
            await (await get_redis()).initialize()  # ping 复用
            checks.append({"name": "redis", "status": "up"})
        except Exception:
            ok = False
            checks.append({"name": "redis", "status": "down"})
        try:
            await (await get_neo4j()).run("RETURN 1")
            checks.append({"name": "neo4j", "status": "up"})
        except Exception:
            ok = False
            checks.append({"name": "neo4j", "status": "down"})
        return {"status": "ok" if ok else "degraded", "checks": checks}

    # 中间件（11）：RateLimitMiddleware / HarmfulFilterMiddleware
    # 路由注册（03-11）：各模块 router，prefix=settings.api_prefix

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    # PyCharm 直接 Run 本文件即启动；传 app 对象避免 import 字符串路径问题
    uvicorn.run(app, host="0.0.0.0", port=8000)

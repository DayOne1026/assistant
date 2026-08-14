import os

# 11：测试环境关闭限流（共享 testclient IP 会撞 60/min 窗口变 429）。
# 必须在 import app.main（触发 get_settings 缓存）之前设置。
os.environ["ASSISTANT_RATE_LIMIT_ENABLED"] = "false"

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.db.models  # noqa: F401  注册 Base.metadata（create_all 建 users/refresh_tokens）
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import async_session, get_db
from app.db.tenant_policy import BUSINESS_TABLES, enable_rls
from app.main import app
from app.neo4j_client import close_neo4j, get_neo4j, init_neo4j
from app.redis_client import close_redis, get_redis, init_redis
from app.repos.users import user_repo

import uuid

settings = get_settings()


@pytest.fixture(scope="session", autouse=True)
async def _redis():
    """session 级：初始化真实 Redis 单例（黑名单测试依赖），结束关闭。"""
    await init_redis()
    yield
    await close_redis()


@pytest.fixture(scope="session")
async def neo4j_client():
    """session 级：Neo4j 单例；连不上则 skip 隔离测试。"""
    await init_neo4j()
    client = await get_neo4j()
    try:
        await client.run("RETURN 1")
    except Exception:
        pytest.skip("Neo4j 不可达，跳过图谱隔离测试")
    yield client
    await close_neo4j()


@pytest.fixture(scope="session")
async def test_engine():
    """测试库引擎：连 ASSISTANT_DATABASE_URL，用例前建表 + 启用 RLS（03 遗留 4/5）。

    防呆：严禁直连 dev 库（drop_all 会清空业务数据）。须设
    ASSISTANT_DATABASE_URL=.../assistant_test。
    """
    url = make_url(settings.database_url)
    if url.database == "assistant":
        raise RuntimeError("测试严禁直连 dev 库：请设 ASSISTANT_DATABASE_URL=.../assistant_test")
    engine = create_async_engine(settings.database_url, echo=settings.pg_echo)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        # 03 遗留 5：每张已注册业务表建表后启用 RLS（表名来自可信常量，未建表跳过）
        existing = set(Base.metadata.tables.keys())
        for table in BUSINESS_TABLES:
            if table in existing:
                await enable_rls(conn, table)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(test_engine):
    """事务回滚 session：用例结束后 rollback，测试互不污染。"""
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await trans.rollback()
            await session.close()


@pytest.fixture
async def client(db):
    """httpx AsyncClient，依赖覆盖 get_db。"""
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


# user 夹具（预置测试用户，02）
@pytest.fixture
async def user(db):
    u = await user_repo.create(
        db,
        email="user@example.com",
        username="tester",
        hashed_password=hash_password("pass1234"),
        timezone="Asia/Shanghai",
    )
    await db.commit()
    return u


@pytest.fixture
async def real_user():
    """真实提交的用户（独立 session 落库）。

    audit 写 tool_call_logs 用独立 session（async_session），只能看到已提交的用户——
    db 级 user fixture 在回滚事务内，跨连接不可见，会触发 FK 违规。工具/审计测试用它。
    """
    async with async_session() as s:
        u = await user_repo.create(
            s,
            email=f"real-{uuid.uuid4()}@example.com",
            username=f"real{uuid.uuid4().hex[:8]}",
            hashed_password=hash_password("pass1234"),
            timezone="Asia/Shanghai",
        )
        await s.commit()
        return u

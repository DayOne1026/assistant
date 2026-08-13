import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app

settings = get_settings()


@pytest.fixture(scope="session")
async def test_engine():
    """测试库引擎：连 ASSISTANT_DATABASE_URL，用例前建表。"""
    engine = create_async_engine(settings.database_url, echo=settings.pg_echo)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
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


# user 夹具（预置测试用户）等 02 users 表就绪后补充

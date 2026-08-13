"""03 数据隔离测试（蓝图 03 隔离验证清单）。

RLS 生效验证用测试临时表（业务表 04-08 才建，机制等价）；
API 层 A/B 资源请求（清单第 2 条）待 schedules 等端点落地后补。
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.deps import get_current_user_isolated
from app.db.tenant import assert_rls_enabled, clear_tenant_context, set_tenant_context
from app.db.tenant_policy import BUSINESS_TABLES, enable_rls
from app.neo4j_client import neo4j_user_scope
from app.redis_client import redis_key

TEMP_TABLE = "test_rls_items"


async def _create_temp_table(db):
    await db.execute(
        text(f"CREATE TABLE IF NOT EXISTS {TEMP_TABLE} (id serial primary key, user_id uuid)")
    )
    await enable_rls(db, TEMP_TABLE)


async def _insert(db, uid):
    await set_tenant_context(db, uid)
    await db.execute(
        text(f"INSERT INTO {TEMP_TABLE} (user_id) VALUES (:uid)"), {"uid": str(uid)}
    )


# --- 蓝图清单 1：RLS SQL 层，A/B 数据互不可见 ---

async def test_rls_row_level_isolation(db):
    await _create_temp_table(db)
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    await _insert(db, user_a)
    await _insert(db, user_b)

    await set_tenant_context(db, user_a)
    rows_a = (await db.execute(text(f"SELECT user_id FROM {TEMP_TABLE}"))).scalars().all()
    assert len(rows_a) == 1
    assert str(rows_a[0]) == str(user_a)

    await set_tenant_context(db, user_b)
    rows_b = (await db.execute(text(f"SELECT user_id FROM {TEMP_TABLE}"))).scalars().all()
    assert len(rows_b) == 1
    assert str(rows_b[0]) == str(user_b)


async def test_rls_fail_closed_without_context(db):
    await _create_temp_table(db)
    user_a = uuid.uuid4()
    await _insert(db, user_a)
    await clear_tenant_context(db)
    # 上下文被清空后 current_setting 非 uuid → 查询抛错，任何数据不可见
    with pytest.raises(DBAPIError):
        (await db.execute(text(f"SELECT user_id FROM {TEMP_TABLE}"))).scalars().all()


# --- 蓝图清单 5：assert_rls_enabled 自检 ---

async def test_assert_rls_enabled(db):
    assert await assert_rls_enabled(db, TEMP_TABLE) is False  # 表不存在
    await _create_temp_table(db)
    assert await assert_rls_enabled(db, TEMP_TABLE) is True  # 已 enable_rls


# --- 蓝图清单 4：Redis key 前缀 ---

def test_redis_key_contains_user_scope():
    uid = uuid.uuid4()
    assert redis_key("session", uid) == f"app:session:{uid}"
    assert redis_key("session", uid, "conv-1") == f"app:session:{uid}:conv-1"
    assert redis_key("lock", uid, "schedule:1") == f"app:lock:{uid}:schedule:1"


async def test_redis_keys_isolated_by_user():
    a, b = uuid.uuid4(), uuid.uuid4()
    key_a = redis_key("session", a, "conv-1")
    key_b = redis_key("session", b, "conv-1")
    assert key_a != key_b
    assert str(a) in key_a and str(b) not in key_a


# --- 蓝图清单 3：Neo4j verify_user_scope 归属校验 ---

def test_neo4j_user_scope_param():
    uid = uuid.uuid4()
    assert neo4j_user_scope(uid) == {"user_id": str(uid)}


async def test_neo4j_verify_user_scope_isolated(neo4j_client):
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    node_id = uuid.uuid4()
    await neo4j_client.execute_write(
        "MERGE (n:Person {id: $id, user_id: $user_id})",
        {"id": str(node_id), "user_id": str(user_a)},
    )
    try:
        assert await neo4j_client.verify_user_scope(user_a, str(node_id), "Person") is True
        assert await neo4j_client.verify_user_scope(user_b, str(node_id), "Person") is False
    finally:
        await neo4j_client.execute_write(
            "MATCH (n:Person {id: $id}) DETACH DELETE n", {"id": str(node_id)}
        )


# --- 02→03 接入：get_current_user_isolated 设置 RLS 上下文 ---

async def test_get_current_user_isolated_sets_context(db, user):
    resolved = await get_current_user_isolated(user=user, db=db)
    assert resolved.id == user.id
    val = (
        await db.execute(text("SELECT current_setting('app.current_user_id', true)"))
    ).scalar()
    assert val == str(user.id)


# --- 蓝图迁移清单：10 张业务表均在清单内 ---

def test_business_tables_listed():
    assert len(BUSINESS_TABLES) == 10
    assert "schedules" in BUSINESS_TABLES
    assert "refresh_tokens" not in BUSINESS_TABLES  # 不适用 RLS

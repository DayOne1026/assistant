"""04 对话测试（蓝图 04 测试要点）：CRUD / 消息持久化 / 跨用户隔离 / RLS 落地。

POST messages（跑 AgentRunner）归 04b，持久化链路先用 repo 直写验证。
"""

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models.conversations import Message
from app.db.tenant import assert_rls_enabled, set_tenant_context
from app.repos.conversations import message_repo
from app.repos.users import user_repo

P = get_settings().api_prefix
CONVERSATIONS = f"{P}/conversations"

EMAIL_A = "alice@example.com"
EMAIL_B = "bob@example.com"
PASSWORD = "pass1234"
REG_A = {"email": EMAIL_A, "username": "alice", "password": PASSWORD, "timezone": "Asia/Shanghai"}
REG_B = {"email": EMAIL_B, "username": "bob", "password": PASSWORD, "timezone": "Asia/Shanghai"}


async def _register(client, data):
    return await client.post(f"{P}/auth/register", json=data)


async def _login(client, email):
    return await client.post(f"{P}/auth/login", json={"email": email, "password": PASSWORD})


async def _headers(client, email):
    d = (await _login(client, email)).json()["data"]
    return {"Authorization": f"Bearer {d['access_token']}"}


async def _new_conv(client, headers, title=None):
    r = await client.post(CONVERSATIONS, json={"title": title} if title else {}, headers=headers)
    assert r.status_code == 200
    return r.json()["data"]["id"]


# --- CRUD ---


async def test_create_conversation_default_title(client):
    await _register(client, REG_A)
    h = await _headers(client, EMAIL_A)
    r = await client.post(CONVERSATIONS, json={}, headers=h)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["title"] == "新对话"
    assert data["id"]


async def test_create_conversation_with_title(client):
    await _register(client, REG_A)
    h = await _headers(client, EMAIL_A)
    r = await client.post(CONVERSATIONS, json={"title": "周末计划"}, headers=h)
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "周末计划"


async def test_list_conversations_paginated(client):
    await _register(client, REG_A)
    h = await _headers(client, EMAIL_A)
    for _ in range(3):
        await _new_conv(client, h)
    r = await client.get(CONVERSATIONS, params={"page": 1, "page_size": 2}, headers=h)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 3
    assert len(data["items"]) == 2


async def test_delete_conversation(client, db):
    await _register(client, REG_A)
    h = await _headers(client, EMAIL_A)
    conv_id = await _new_conv(client, h)
    r = await client.delete(f"{CONVERSATIONS}/{conv_id}", headers=h)
    assert r.status_code == 200
    # 删除后归属校验 404
    assert (await client.get(f"{CONVERSATIONS}/{conv_id}/messages", headers=h)).status_code == 404
    # FK CASCADE：messages 级联清空（RLS 上下文 = alice，可见自己表内行）
    assert (await db.execute(select(func.count()).select_from(Message))).scalar_one() == 0


# --- 消息持久化（04b 前用 repo 直写模拟 turn）---


async def test_messages_persisted_and_readable(client, db):
    await _register(client, REG_A)
    h = await _headers(client, EMAIL_A)
    conv_id = await _new_conv(client, h)
    # 模拟一轮 turn：user + assistant 两行落库
    alice = await user_repo.get_by_email(db, EMAIL_A)
    await set_tenant_context(db, alice.id)
    await message_repo.create(db, conv_id, alice.id, "user", "明早9点开会")
    await message_repo.create(db, conv_id, alice.id, "assistant", "已记下")
    await db.commit()
    r = await client.get(f"{CONVERSATIONS}/{conv_id}/messages", headers=h)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 2
    assert [m["role"] for m in data["items"]] == ["user", "assistant"]
    assert data["items"][1]["content"] == "已记下"
    assert data["items"][1]["attachments"] == []  # 04a 无图片引用，06 才补 URL


async def test_messages_search_q(client, db):
    await _register(client, REG_A)
    h = await _headers(client, EMAIL_A)
    conv_id = await _new_conv(client, h)
    alice = await user_repo.get_by_email(db, EMAIL_A)
    await set_tenant_context(db, alice.id)
    await message_repo.create(db, conv_id, alice.id, "user", "记一下买牛奶")
    await message_repo.create(db, conv_id, alice.id, "user", "今天天气不错")
    await db.commit()
    r = await client.get(
        f"{CONVERSATIONS}/{conv_id}/messages", params={"q": "牛奶"}, headers=h
    )
    data = r.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["content"] == "记一下买牛奶"


# --- 跨用户隔离（蓝图 04 测试要点：A 无法读 B 的会话）---


async def test_isolation_cross_user(client):
    await _register(client, REG_A)
    await _register(client, REG_B)
    ha = await _headers(client, EMAIL_A)
    hb = await _headers(client, EMAIL_B)
    conv_a = await _new_conv(client, ha)
    # B 读 A 的会话消息 → 404 NOT_FOUND（归属校验 + RLS 兜底）
    r = await client.get(f"{CONVERSATIONS}/{conv_a}/messages", headers=hb)
    assert r.status_code == 404
    assert r.json()["code"] == "4001"
    # B 删 A 的会话 → 404
    r = await client.delete(f"{CONVERSATIONS}/{conv_a}", headers=hb)
    assert r.status_code == 404
    # B 列表看不到 A 的会话
    assert (await client.get(CONVERSATIONS, headers=hb)).json()["data"]["total"] == 0
    # A 的会话仍在
    assert (await client.get(CONVERSATIONS, headers=ha)).json()["data"]["total"] == 1


# --- 03 遗留 5 落地：业务表 RLS 已启用 ---


async def test_rls_enabled_on_business_tables(db):
    assert await assert_rls_enabled(db, "conversations") is True
    assert await assert_rls_enabled(db, "messages") is True

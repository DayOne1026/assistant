"""04 Agent 测试（蓝图 04 测试要点）：意图路由 / 消息持久化 / 多轮 checkpointer / 隔离。

意图识别为真实 LLM（deepseek-v4-pro，.env），断言宽松防 flaky。
POST messages 依赖 RedisSaver checkpointer（redis-stack/RediSearch）。
"""

import uuid

from sqlalchemy import func, select

from app.agent.intent import (
    INTENT_BRANCH,
    route_by_intent,
    validate_intent_params,
)
from app.agent.runner import classify_confirm_input, get_runner
from app.core.config import get_settings
from app.db.models.conversations import Message
from app.db.tenant import set_tenant_context
from app.repos.users import user_repo
from app.schemas.chat import IntentResult

P = get_settings().api_prefix
CONVERSATIONS = f"{P}/conversations"
EMAIL = "alice@example.com"
EMAIL_B = "bob@example.com"
PASSWORD = "pass1234"
REG = {"email": EMAIL, "username": "alice", "password": PASSWORD, "timezone": "Asia/Shanghai"}
REG_B = {"email": EMAIL_B, "username": "bob", "password": PASSWORD, "timezone": "Asia/Shanghai"}

KNOWN_INTENTS = set(INTENT_BRANCH) | {"default_chat", "confirm"}


async def _register(client, data):
    await client.post(f"{P}/auth/register", json=data)


async def _headers(client, email=EMAIL):
    d = (await client.post(f"{P}/auth/login", json={"email": email, "password": PASSWORD})).json()["data"]
    return {"Authorization": f"Bearer {d['access_token']}"}


async def _new_conv(client, headers):
    r = await client.post(CONVERSATIONS, json={}, headers=headers)
    assert r.status_code == 200
    return r.json()["data"]["id"]


async def _post(client, headers, conv_id, content):
    return await client.post(
        f"{CONVERSATIONS}/{conv_id}/messages",
        json={"conversation_id": conv_id, "content": content},
        headers=headers,
    )


# --- 纯函数：路由映射（无 LLM）---


def test_route_by_intent_mapping():
    assert route_by_intent({"intent": {"intent_name": "create_schedule"}}) == "tool"
    assert route_by_intent({"intent": {"intent_name": "query_memory"}}) == "memory"
    assert route_by_intent({"intent": {"intent_name": "remember_fact"}}) == "memory_write"
    assert route_by_intent({"intent": {"intent_name": "search_docs"}}) == "rag"
    assert route_by_intent({"intent": {"intent_name": "trigger_skill"}}) == "skill"
    assert route_by_intent({"intent": {"intent_name": "default_chat"}}) == "chat"
    assert route_by_intent({}) == "chat"


def test_classify_confirm_input():
    assert classify_confirm_input("确认") == "confirm"
    assert classify_confirm_input("可以") == "confirm"
    assert classify_confirm_input("取消") == "deny"
    assert classify_confirm_input("不要了") == "deny"
    assert classify_confirm_input("明早9点开会") is None


def test_validate_intent_params_no_schema_lenient():
    """未注册参数 schema 的意图（query_* 等）宽松放行不降级。"""
    r = IntentResult(intent_name="query_schedule", parameters={"start_at": "2026-09-01"}, confidence=0.9)
    out = validate_intent_params(r)
    assert out.parameters == {"start_at": "2026-09-01"}
    assert out.confidence == 0.9


def test_validate_intent_params_schema_strict():
    """07 注册 create_schedule 后：缺必填参数 → 清空降级；参数完整 → 通过。"""
    r = IntentResult(intent_name="create_schedule", parameters={"title": "开会"}, confidence=0.9)
    out = validate_intent_params(r)
    assert out.parameters == {}
    assert out.confidence == 0.0
    r2 = IntentResult(
        intent_name="create_schedule",
        parameters={"title": "开会", "start_at": "2026-09-01T10:00:00+08:00"},
        confidence=0.9,
    )
    assert validate_intent_params(r2).parameters == r2.parameters


# --- 集成：POST messages 全链路（真实 LLM + checkpointer）---


async def test_post_message_persists_and_replies(client, db):
    await _register(client, REG)
    h = await _headers(client)
    conv_id = await _new_conv(client, h)
    r = await _post(client, h, conv_id, "明早9点开会")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["reply"]  # 有回复
    assert data["intent"]["intent_name"] in KNOWN_INTENTS
    # messages 表 user+assistant 两行（RLS 上下文 alice）
    alice = await user_repo.get_by_email(db, EMAIL)
    await set_tenant_context(db, alice.id)
    total = (await db.execute(select(func.count()).select_from(Message))).scalar_one()
    assert total == 2


async def test_multi_turn_checkpointer(client, db):
    """Redis checkpointer 保留上轮（蓝图 04 测试要点）。"""
    await _register(client, REG)
    h = await _headers(client)
    conv_id = await _new_conv(client, h)
    for content in ("我叫小明", "我住在杭州"):
        r = await _post(client, h, conv_id, content)
        assert r.status_code == 200
        assert r.json()["data"]["reply"]
    # thread state 有历史（checkpointer 生效，Redis 会话隔离）
    alice = await user_repo.get_by_email(db, EMAIL)
    runner = get_runner()
    thread = runner._thread(alice.id, uuid.UUID(conv_id))
    snapshot = runner._graph.get_state(thread)
    assert snapshot is not None
    assert snapshot.values.get("messages")  # 保留上轮消息


async def test_runner_confirm_branch_no_pending(client):
    """确认分支不走意图路由；无可确认动作 → 提示。"""
    await _register(client, REG)
    h = await _headers(client)
    conv_id = await _new_conv(client, h)
    r = await _post(client, h, conv_id, "确认")
    data = r.json()["data"]
    assert data["intent"]["intent_name"] == "confirm"
    assert "无可确认" in data["reply"]


async def test_post_message_isolation(client):
    """B 无法向 A 的会话发消息（归属校验 404）。"""
    await _register(client, REG)
    await _register(client, REG_B)
    ha = await _headers(client)
    hb = await _headers(client, EMAIL_B)
    conv_a = await _new_conv(client, ha)
    r = await _post(client, hb, conv_a, "偷偷发一条")
    assert r.status_code == 404

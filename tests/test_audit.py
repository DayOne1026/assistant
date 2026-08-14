"""11 审计与安全测试（蓝图 11 测试要点 + 00 落位）。

四级权限 / 确认流程（含过期/伪造）/ jsonschema 参数校验 / 工具调用审计落库 /
删除审计 / 限流原语 / 有害过滤 / 审计隔离。工具测试用 fake registry + 真实 redis。
audit 写库用独立 session 真实落库，fixture db（Read Committed）可读到。
"""

import uuid
from datetime import datetime

import pytest

from app.agent.tools import ToolDef, ToolLevel, ToolRegistry
from app.audit.audit_service import log_audit
from app.core.config import get_settings
from app.core.exceptions import AppException, ErrorCode
from app.db.tenant import set_tenant_context
from app.redis_client import get_redis, redis_key
from app.repos.audit import audit_repo, tool_log_repo
from app.repos.schedules import schedule_repo
from app.schemas.schedule import ScheduleCreate
from app.services import delete_service, schedule_service

P = get_settings().api_prefix


async def _reg() -> ToolRegistry:
    return ToolRegistry(await get_redis())


def _tool(name: str, level: ToolLevel, handler, schema: dict | None = None) -> ToolDef:
    return ToolDef(
        name=name, description=name, parameters_schema=schema or {}, level=level, handler=handler
    )


# --- 四级权限 ---


async def test_high_risk_register_rejected():
    async def h(uid, params):
        return {}

    reg = await _reg()
    with pytest.raises(AppException) as ei:
        reg.register(_tool("fake_hr", ToolLevel.HIGH_RISK, h))
    assert ei.value.code is ErrorCode.TOOL_LEVEL_DENIED


async def test_read_only_direct_execution(real_user):
    calls = []

    async def h(uid, params):
        calls.append(1)
        return {"ok": True}

    reg = await _reg()
    reg.register(_tool("fake_ro", ToolLevel.READ_ONLY, h))
    res = await reg.call(real_user.id, "fake_ro", {}, None)
    assert res.status == "done"
    assert calls == [1]  # READ_ONLY 直接执行


async def test_create_modify_pending(real_user):
    async def h(uid, params):
        raise AssertionError("写工具未确认不应执行")

    reg = await _reg()
    reg.register(_tool("fake_cm", ToolLevel.CREATE_MODIFY, h))
    res = await reg.call(real_user.id, "fake_cm", {}, None)
    assert res.status == "pending_confirmation"  # 写工具挂起待确认


async def test_invalid_params_rejected(real_user):
    async def h(uid, params):
        return {"ok": True}

    reg = await _reg()
    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    reg.register(_tool("fake_v", ToolLevel.READ_ONLY, h, schema))
    with pytest.raises(AppException) as ei:
        await reg.call(real_user.id, "fake_v", {}, None)
    assert ei.value.code is ErrorCode.VALIDATION_ERROR  # jsonschema 校验失败
    # 合法参数通过
    res = await reg.call(real_user.id, "fake_v", {"x": "v"}, None)
    assert res.status == "done"


# --- 确认流程 + 工具审计落库 ---


async def test_confirm_flow_and_audit(db, real_user):
    calls = []

    async def h(uid, params):
        calls.append(1)
        return {"done": True}

    reg = await _reg()
    reg.register(_tool("fake_cm", ToolLevel.CREATE_MODIFY, h))
    uid = real_user.id
    res = await reg.call(uid, "fake_cm", {}, None)
    assert res.status == "pending_confirmation"
    assert calls == []
    rows, _ = await tool_log_repo.list(db, uid, 0, 10)
    assert rows[0].decision == "pending"  # 挂起时审计预录
    # 确认 → handler 执行 → 审计 approved（audit 走独立 session 提交，fixture db 需 expire 重读）
    res2 = await reg.confirm(uid, res.call_id)
    assert res2.status == "done"
    assert calls == [1]
    db.expire_all()
    rows, _ = await tool_log_repo.list(db, uid, 0, 10)
    assert rows[0].decision == "approved"


async def test_deny_marks_audit(db, real_user):
    async def h(uid, params):
        raise AssertionError()

    reg = await _reg()
    reg.register(_tool("fake_cm", ToolLevel.CREATE_MODIFY, h))
    uid = real_user.id
    res = await reg.call(uid, "fake_cm", {}, None)
    await reg.deny(uid, res.call_id)
    rows, _ = await tool_log_repo.list(db, uid, 0, 10)
    assert rows[0].decision == "denied"


async def test_confirm_expired_or_forged(real_user):
    async def h(uid, params):
        raise AssertionError()

    reg = await _reg()
    reg.register(_tool("fake_cm", ToolLevel.CREATE_MODIFY, h))
    uid = real_user.id
    res = await reg.call(uid, "fake_cm", {}, None)
    # 手动删 redis 模拟过期
    redis = await get_redis()
    await redis.delete(redis_key("confirm-tool", uid, str(res.call_id)))
    assert (await reg.confirm(uid, res.call_id)).status == "denied"
    # 伪造 call_id 拒绝
    assert (await reg.confirm(uid, uuid.uuid4())).status == "denied"


async def test_read_only_tool_logged(db, real_user):
    async def h(uid, params):
        return {"ok": True}

    reg = await _reg()
    reg.register(_tool("fake_ro", ToolLevel.READ_ONLY, h))
    uid = real_user.id
    res = await reg.call(uid, "fake_ro", {}, None)
    assert res.status == "done"
    rows, total = await tool_log_repo.list(db, uid, 0, 10)
    assert total == 1
    assert rows[0].tool_name == "fake_ro"
    assert rows[0].decision == "approved"  # 读工具直接完成即 approved
    assert rows[0].level == "read_only"


# --- 删除审计（delete_service 二次确认）---


async def test_delete_service_writes_audit(client, db, user):
    await set_tenant_context(db, user.id)
    s = await schedule_service.create_schedule(
        db, user.id, ScheduleCreate(title="审计用日程", start_at=datetime.now().astimezone())
    )
    redis = await get_redis()
    req = await delete_service.request_delete(
        db, redis, user.id, "schedule", s.id, schedule_service.get_schedule
    )
    await delete_service.confirm_delete(
        db, redis, user.id, "schedule", s.id, req.delete_token, schedule_repo.soft_delete
    )
    rows, total = await audit_repo.list(db, user.id, 0, 10)
    assert total >= 1
    assert rows[0].action == "delete"
    assert rows[0].resource_type == "schedule"
    assert rows[0].resource_id == s.id


# --- 限流（redis 滑动窗口原语）---


async def test_rate_limit_sliding_window():
    redis = await get_redis()
    key = f"test:ratelimit:{uuid.uuid4()}"
    for _ in range(3):
        assert await redis.sliding_window_rate_limit(key, 3, 60)
    assert not await redis.sliding_window_rate_limit(key, 3, 60)  # 超阈值拒绝


# --- 有害内容过滤 ---


async def test_harmful_filter_blocks_sensitive_input(client, db):
    # 中间件先于认证拦截，无需 token；含敏感词 body → 400
    r = await client.post(f"{P}/conversations", json={"title": "自杀"})
    assert r.status_code == 400


async def test_harmful_filter_passes_normal_input(client, db):
    r = await client.post(f"{P}/auth/register", json={
        "email": f"normal-{uuid.uuid4()}@example.com", "username": f"n{uuid.uuid4().hex[:6]}",
        "password": "pass1234", "timezone": "Asia/Shanghai",
    })
    assert r.status_code == 200  # 正常内容不被误伤


# --- 审计隔离（A 查不到 B）---


async def test_audit_isolated_cross_user(db, real_user):
    async def h(uid, params):
        return {"ok": True}

    reg = await _reg()
    reg.register(_tool("fake_iso", ToolLevel.READ_ONLY, h))
    uid_a = real_user.id
    await reg.call(uid_a, "fake_iso", {}, None)
    # B（不存在的 user_id）查 A 的 tool_log → 空
    rows, total = await tool_log_repo.list(db, uuid.uuid4(), 0, 10)
    assert total == 0
    # A 能查到自己的
    _, total_a = await tool_log_repo.list(db, uid_a, 0, 10)
    assert total_a == 1


# --- audit API ---


async def test_audit_logs_api(client, db, user):
    await set_tenant_context(db, user.id)
    await log_audit(db, user.id, "delete", "schedule", None, {"deleted": True})
    await db.commit()
    r = await client.post(f"{P}/auth/login", json={"email": "user@example.com", "password": "pass1234"})
    h = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    r2 = await client.get(f"{P}/audit-logs", headers=h)
    assert r2.status_code == 200
    data = r2.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["action"] == "delete"

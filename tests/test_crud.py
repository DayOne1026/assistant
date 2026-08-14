"""07 日程与任务测试（蓝图 07 测试要点）：CRUD 隔离 / 时间校验 / 二次确认 / 软删 / 重叠提醒。

二次确认 token 过期：直接删 Redis key 模拟（token 本身 TTL 300s 不等待）。
"""

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models.notifications import Notification
from app.redis_client import get_redis, redis_key
from app.repos.users import user_repo

P = get_settings().api_prefix
SCHEDULES = f"{P}/schedules"
TODOS = f"{P}/todos"

EMAIL_A = "crud-a@example.com"
EMAIL_B = "crud-b@example.com"
PASSWORD = "pass1234"
REG_A = {"email": EMAIL_A, "username": "cruda", "password": PASSWORD, "timezone": "Asia/Shanghai"}
REG_B = {"email": EMAIL_B, "username": "crudb", "password": PASSWORD, "timezone": "Asia/Shanghai"}


async def _register(client, data):
    return await client.post(f"{P}/auth/register", json=data)


async def _login(client, email):
    return await client.post(f"{P}/auth/login", json={"email": email, "password": PASSWORD})


async def _headers(client, email):
    d = (await _login(client, email)).json()["data"]
    return {"Authorization": f"Bearer {d['access_token']}"}


async def _new_schedule(client, h, title="周会", start="2026-09-01T10:00:00+08:00", end="2026-09-01T11:00:00+08:00"):
    r = await client.post(
        f"{SCHEDULES}",
        json={"title": title, "start_at": start, "end_at": end},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _new_todo(client, h, title="买牛奶"):
    r = await client.post(f"{TODOS}", json={"title": title}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_schedule_crud_flow(client):
    await _register(client, REG_A)
    h = await _headers(client, EMAIL_A)
    s = await _new_schedule(client, h)
    assert (await client.get(f"{SCHEDULES}/{s['id']}", headers=h)).json()["data"]["title"] == "周会"
    assert (await client.get(f"{SCHEDULES}", headers=h)).json()["data"]["total"] == 1
    r = await client.patch(f"{SCHEDULES}/{s['id']}", json={"title": "季度会"}, headers=h)
    assert r.json()["data"]["title"] == "季度会"


async def test_schedule_time_validation(client):
    await _register(client, REG_A)
    h = await _headers(client, EMAIL_A)
    r = await client.post(
        f"{SCHEDULES}",
        json={"title": "非法", "start_at": "2026-09-01T10:00:00+08:00", "end_at": "2026-09-01T09:00:00+08:00"},
        headers=h,
    )
    assert r.json()["code"] == "2001"


async def test_schedule_isolation_cross_user(client):
    await _register(client, REG_A)
    await _register(client, REG_B)
    ha = await _headers(client, EMAIL_A)
    hb = await _headers(client, EMAIL_B)
    s = await _new_schedule(client, ha)
    # B 访问 A 的日程 → 404（读/改/删，不得泄漏存在）
    assert (await client.get(f"{SCHEDULES}/{s['id']}", headers=hb)).status_code == 404
    assert (await client.patch(f"{SCHEDULES}/{s['id']}", json={"title": "x"}, headers=hb)).status_code == 404
    assert (await client.delete(f"{SCHEDULES}/{s['id']}", headers=hb)).status_code == 404


async def test_schedule_delete_two_step(client, db):
    await _register(client, REG_A)
    h = await _headers(client, EMAIL_A)
    s = await _new_schedule(client, h)
    # 第 1 步 DELETE：发 token 不真删
    r = await client.delete(f"{SCHEDULES}/{s['id']}", headers=h)
    token = r.json()["data"]["delete_token"]
    assert (await client.get(f"{SCHEDULES}/{s['id']}", headers=h)).status_code == 200
    # 错误 token 拒
    r = await client.post(f"{SCHEDULES}/{s['id']}/confirm", json={"delete_token": "bad"}, headers=h)
    assert r.json()["code"] == "4003"
    # token 过期拒（模拟删 key）
    u = await user_repo.get_by_email(db, EMAIL_A)
    redis = await get_redis()
    await redis.delete(redis_key("confirm", u.id, "schedule", str(s["id"])))
    r = await client.post(f"{SCHEDULES}/{s['id']}/confirm", json={"delete_token": token}, headers=h)
    assert r.json()["code"] == "4003"
    # 重新请求 token 后正确确认 → 软删
    r = await client.delete(f"{SCHEDULES}/{s['id']}", headers=h)
    token2 = r.json()["data"]["delete_token"]
    r = await client.post(f"{SCHEDULES}/{s['id']}/confirm", json={"delete_token": token2}, headers=h)
    assert r.status_code == 200
    # 软删后：详情 404、列表排除
    assert (await client.get(f"{SCHEDULES}/{s['id']}", headers=h)).status_code == 404
    assert (await client.get(f"{SCHEDULES}", headers=h)).json()["data"]["total"] == 0


async def test_todo_crud_and_toggle(client):
    await _register(client, REG_A)
    h = await _headers(client, EMAIL_A)
    t = await _new_todo(client, h)
    r = await client.post(f"{TODOS}/{t['id']}/toggle?completed=true", headers=h)
    assert r.json()["data"]["completed"] is True
    assert r.json()["data"]["completed_at"] is not None
    assert (await client.get(f"{TODOS}?completed=true", headers=h)).json()["data"]["total"] == 1
    assert (await client.get(f"{TODOS}?completed=false", headers=h)).json()["data"]["total"] == 0


async def test_todo_delete_two_step(client):
    await _register(client, REG_A)
    h = await _headers(client, EMAIL_A)
    t = await _new_todo(client, h)
    r = await client.delete(f"{TODOS}/{t['id']}", headers=h)
    token = r.json()["data"]["delete_token"]
    r = await client.post(f"{TODOS}/{t['id']}/confirm", json={"delete_token": token}, headers=h)
    assert r.status_code == 200
    assert (await client.get(f"{TODOS}/{t['id']}", headers=h)).status_code == 404


async def test_schedule_overlap_notifies(client, db):
    await _register(client, REG_A)
    h = await _headers(client, EMAIL_A)
    await _new_schedule(client, h, "早会", "2026-09-01T10:00:00+08:00", "2026-09-01T11:00:00+08:00")
    # 重叠日程：不阻止创建，发 08 冲突提醒
    r = await client.post(
        f"{SCHEDULES}",
        json={"title": "评审", "start_at": "2026-09-01T10:30:00+08:00", "end_at": "2026-09-01T12:00:00+08:00"},
        headers=h,
    )
    assert r.status_code == 200
    n = (await db.execute(select(func.count()).select_from(Notification))).scalar_one()
    assert n == 1

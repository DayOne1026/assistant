"""08 通知/提醒测试（蓝图 08 测试要点）：扫描幂等 / 取消不发送 / 已读流程 / ConnectionManager / WS 鉴权。

定时任务测 async 核心（_scan_due_reminders/_send_reminder），传 fixture db 走事务回滚；
email 渠道 send_email 归 12，本次不测。
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models.notifications import Notification
from app.main import app
from app.repos.notifications import reminder_repo
from app.repos.users import user_repo
from app.services import notification_service
from app.tasks.notification_tasks import _scan_due_reminders

P = get_settings().api_prefix
REMINDERS = f"{P}/reminders"
NOTIFICATIONS = f"{P}/notifications"

EMAIL_A = "notif@example.com"
EMAIL_B = "notif-b@example.com"
PASSWORD = "pass1234"
REG_A = {"email": EMAIL_A, "username": "notifuser", "password": PASSWORD, "timezone": "Asia/Shanghai"}
REG_B = {"email": EMAIL_B, "username": "notifuserb", "password": PASSWORD, "timezone": "Asia/Shanghai"}
PAST = "2026-08-01T08:00:00+08:00"  # 早于今天的到期时间


async def _register(client, data=None):
    return await client.post(f"{P}/auth/register", json=data or REG_A)


async def _headers(client, email=EMAIL_A):
    r = await client.post(f"{P}/auth/login", json={"email": email, "password": PASSWORD})
    d = r.json()["data"]
    return {"Authorization": f"Bearer {d['access_token']}"}


async def test_scan_due_reminders_sends_once(client, db):
    await _register(client)
    h = await _headers(client)
    r = await client.post(
        f"{REMINDERS}", json={"title": "吃药", "notify_at": PAST, "channel": "ws"}, headers=h
    )
    assert r.status_code == 200
    rid = r.json()["data"]["id"]
    assert r.json()["data"]["status"] == "pending"
    # 扫描到期提醒 → 发送（notification 落库）
    assert await _scan_due_reminders(db=db) >= 1
    count = (await db.execute(select(func.count()).select_from(Notification))).scalar_one()
    assert count == 1
    # 幂等：再扫不重复发
    await _scan_due_reminders(db=db)
    count2 = (await db.execute(select(func.count()).select_from(Notification))).scalar_one()
    assert count2 == 1
    # reminder 置 sent
    r = await reminder_repo.get_by_id(db, uuid.UUID(rid))
    assert r.status == "sent"


async def test_cancelled_reminder_not_sent(client, db):
    await _register(client)
    h = await _headers(client)
    r = await client.post(f"{REMINDERS}", json={"title": "取消的", "notify_at": PAST}, headers=h)
    rid = r.json()["data"]["id"]
    # 取消（仅 pending 可取消）
    assert (await client.delete(f"{REMINDERS}/{rid}", headers=h)).status_code == 200
    await _scan_due_reminders(db=db)
    count = (await db.execute(select(func.count()).select_from(Notification))).scalar_one()
    assert count == 0


async def test_notification_read_flow(client, db):
    await _register(client)
    h = await _headers(client)
    u = await user_repo.get_by_email(db, EMAIL_A)
    # 即时通知（service 直调，模拟冲突/自动化触发）
    await notification_service.send_immediate(db, u.id, "日程冲突", "与已有日程重叠")
    assert (await client.get(f"{NOTIFICATIONS}", headers=h)).json()["data"]["total"] == 1
    assert (await client.get(f"{NOTIFICATIONS}/unread-count", headers=h)).json()["data"]["count"] == 1
    # 单条已读
    nid = (await client.get(f"{NOTIFICATIONS}", headers=h)).json()["data"]["items"][0]["id"]
    assert (await client.post(f"{NOTIFICATIONS}/{nid}/read", headers=h)).status_code == 200
    assert (await client.get(f"{NOTIFICATIONS}/unread-count", headers=h)).json()["data"]["count"] == 0
    # 再造一条未读 → 全部已读
    await notification_service.send_immediate(db, u.id, "任务超期", "任务已超期")
    assert (await client.post(f"{NOTIFICATIONS}/read-all", headers=h)).status_code == 200
    assert (await client.get(f"{NOTIFICATIONS}/unread-count", headers=h)).json()["data"]["count"] == 0


async def test_connection_manager_push():
    class FakeWS:
        def __init__(self):
            self.sent = []

        async def accept(self):
            pass

        async def send_json(self, payload):
            self.sent.append(payload)

    from app.services.notification_service import ConnectionManager

    m = ConnectionManager()
    uid = uuid.uuid4()
    ws = FakeWS()
    await m.connect(uid, ws)
    assert await m.send_to_user(uid, {"type": "test"}) == 1
    assert ws.sent == [{"type": "test"}]
    assert await m.send_to_user(uuid.uuid4(), {"type": "x"}) == 0  # 离线用户 0
    await m.disconnect(uid, ws)
    assert await m.send_to_user(uid, {"type": "x"}) == 0


def test_ws_rejects_bad_token():
    """WS 鉴权：坏 token 握手即 close(1008)（蓝图 08）。TestClient 非 with，避免 lifespan 关全局 redis。"""
    tc = TestClient(app)
    with pytest.raises(Exception):
        with tc.websocket_connect(f"{P}/ws?token=bad-token"):
            pass
    tc.close()


async def test_notifications_isolated_cross_user(client, db):
    """03 隔离清单第 2 条：A 的 token 看/动不了 B 的通知与提醒（应用层 user_id 过滤）。

    notifications/reminders 不入 RLS（蓝图 03 清单），隔离全靠 repo 双过滤。
    """
    await _register(client, REG_A)
    await _register(client, REG_B)
    ha = await _headers(client, EMAIL_A)
    hb = await _headers(client, EMAIL_B)
    ub = await user_repo.get_by_email(db, EMAIL_B)
    # B 建提醒 + 即时通知
    r = await client.post(f"{REMINDERS}", json={"title": "B的提醒", "notify_at": PAST}, headers=hb)
    rid = r.json()["data"]["id"]
    await notification_service.send_immediate(db, ub.id, "B的通知", "body")
    nid = (await client.get(f"{NOTIFICATIONS}", headers=hb)).json()["data"]["items"][0]["id"]
    # A 取消 B 的提醒 / 已读 B 的通知 → 404（不泄漏存在）
    assert (await client.delete(f"{REMINDERS}/{rid}", headers=ha)).status_code == 404
    assert (await client.post(f"{NOTIFICATIONS}/{nid}/read", headers=ha)).status_code == 404
    # A 的列表不含 B 的数据
    assert (await client.get(f"{NOTIFICATIONS}", headers=ha)).json()["data"]["total"] == 0
    assert (await client.get(f"{REMINDERS}", headers=ha)).json()["data"]["total"] == 0

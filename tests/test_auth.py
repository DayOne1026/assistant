"""02 认证测试（蓝图 02 测试要点）：策略/锁定/轮换/黑名单/重复冲突。"""

from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.repos.users import user_repo

P = get_settings().api_prefix

REGISTER = f"{P}/auth/register"
LOGIN = f"{P}/auth/login"
REFRESH = f"{P}/auth/refresh"
LOGOUT = f"{P}/auth/logout"
ME = f"{P}/users/me"
CHANGE_PASSWORD = f"{P}/users/me/password"

EMAIL = "a@example.com"
PASSWORD = "pass1234"
REG_DATA = {"email": EMAIL, "username": "alice", "password": PASSWORD, "timezone": "Asia/Shanghai"}


async def _register(client, **overrides):
    return await client.post(REGISTER, json={**REG_DATA, **overrides})


async def _login(client, password: str = PASSWORD):
    return await client.post(LOGIN, json={"email": EMAIL, "password": password})


async def test_register_ok(client):
    r = await _register(client)
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == "0"
    assert body["data"]["email"] == EMAIL
    assert body["data"]["username"] == "alice"
    assert "hashed_password" not in body["data"]  # 不泄露散列


async def test_register_weak_password_rejected(client):
    r = await _register(client, password="aaaaaaaa")  # 无数字
    assert r.status_code == 400
    assert r.json()["code"] == "1005"  # PASSWORD_POLICY
    r = await _register(client, password="12345678")  # 无字母
    assert r.status_code == 400
    assert r.json()["code"] == "1005"


async def test_register_duplicate_conflict(client):
    await _register(client)
    r = await _register(client, username="bob")  # 重复 email
    assert r.status_code == 409
    r = await _register(client, email="b@example.com")  # 重复 username
    assert r.status_code == 409


async def test_login_ok(client):
    await _register(client)
    r = await _login(client)
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().access_token_expire_minutes * 60
    assert "access_token" in body and "refresh_token" in body


async def test_login_lockout_after_5_failures(client):
    await _register(client)
    for _ in range(5):
        r = await _login(client, password="wrongpass1")
        assert r.status_code == 401
    # 锁定后即使密码正确也拒绝
    r = await _login(client)
    assert r.status_code == 423
    assert r.json()["code"] == "1004"  # ACCOUNT_LOCKED


async def test_lockout_expiry_unlocks(client, db):
    await _register(client)
    user = await user_repo.get_by_email(db, EMAIL)
    user.is_locked = True
    user.locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)  # 已到期
    user.failed_login_count = 5
    await db.commit()
    r = await _login(client)
    assert r.status_code == 200  # 到期解锁，正确密码登录成功并复位


async def test_refresh_rotation_invalidates_old(client):
    await _register(client)
    r = await _login(client)
    old_access = r.json()["data"]["access_token"]
    old_refresh = r.json()["data"]["refresh_token"]
    r2 = await client.post(REFRESH, json={"refresh_token": old_refresh})
    assert r2.status_code == 200
    assert r2.json()["data"]["access_token"] != old_access
    # 旧 refresh 已轮换失效
    r3 = await client.post(REFRESH, json={"refresh_token": old_refresh})
    assert r3.status_code == 401
    assert r3.json()["code"] == "1001"  # INVALID_TOKEN


async def test_logout_blacklists_access(client):
    await _register(client)
    d = (await _login(client)).json()["data"]
    headers = {"Authorization": f"Bearer {d['access_token']}"}
    assert (await client.get(ME, headers=headers)).status_code == 200
    r = await client.post(LOGOUT, json={"refresh_token": d["refresh_token"]}, headers=headers)
    assert r.status_code == 200
    # access 已进黑名单，再访问被拒
    r2 = await client.get(ME, headers=headers)
    assert r2.status_code == 401
    assert r2.json()["code"] == "1002"  # TOKEN_EXPIRED


async def test_change_password(client):
    await _register(client)
    headers = {"Authorization": f"Bearer {(await _login(client)).json()['data']['access_token']}"}
    r = await client.post(
        CHANGE_PASSWORD,
        json={"old_password": PASSWORD, "new_password": "newpass567"},
        headers=headers,
    )
    assert r.status_code == 200
    assert (await _login(client)).status_code == 401  # 旧密码失效
    assert (await _login(client, password="newpass567")).status_code == 200  # 新密码可登


async def test_me_requires_valid_token(client):
    r = await client.get(ME)  # 无 token
    assert r.status_code in (401, 403)

"""09 集成测试：OAuth 全流程（state 防 CSRF / 加密落库 / 过期刷新 / 撤销拒绝 / 隔离）。

FakeProvider 替换真实 OAuth（monkeypatch integration_service.get_provider）；
依赖 cryptography（Fernet 加密，pip install cryptography）。
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.exceptions import AppException, ErrorCode
from app.db.tenant import set_tenant_context
from app.integrations.crypto import decrypt_token
from app.integrations.oauth import TokenData
from app.repos.integrations import integration_repo
from app.schemas.integration import OAuthCallbackRequest
from app.services import integration_service
from app.services.integration_service import IntegrationService

PROVIDER = "google"


class FakeProvider:
    """假 OAuth provider：记录调用，返回固定 token。"""

    def __init__(self):
        self.revoked = False

    def build_auth_url(self, state, redirect_uri):
        return f"https://fake/auth?state={state}"

    async def fetch_token(self, code, redirect_uri):
        return TokenData(
            access_token="at123", refresh_token="rt123", expires_in=3600,
            account_identifier="acct@example.com",
        )

    async def refresh(self, refresh_token):
        return TokenData(
            access_token="at_new", refresh_token=None, expires_in=3600,
            account_identifier="acct@example.com",
        )

    async def revoke(self, token):
        self.revoked = True


@pytest.fixture
def fake_provider(monkeypatch):
    fp = FakeProvider()
    monkeypatch.setattr(integration_service, "get_provider", lambda name: fp)
    return fp


async def _scoped(db, uid):
    await set_tenant_context(db, uid)
    return uid


async def _start_complete(db, uid, state_override=None):
    """start → complete 返回 integration 行。"""
    svc = IntegrationService(db, await _redis())
    r = await svc.start_oauth(uid, PROVIDER, "https://app/callback")
    await _scoped(db, uid)  # start_oauth 无 commit，安全起见重设
    resp = await svc.complete_oauth(
        uid, PROVIDER, OAuthCallbackRequest(code="code1", state=state_override or r.state)
    )
    return resp


async def _redis():
    from app.redis_client import get_redis

    return await get_redis()


async def test_start_oauth_returns_url_and_state(db, user, fake_provider):
    uid = await _scoped(db, user.id)
    r = await IntegrationService(db, await _redis()).start_oauth(uid, PROVIDER, "https://app/cb")
    assert r.auth_url.startswith("https://fake/auth") and r.state


async def test_complete_oauth_wrong_state_rejected(db, user, fake_provider):
    uid = await _scoped(db, user.id)
    svc = IntegrationService(db, await _redis())
    await svc.start_oauth(uid, PROVIDER, "https://app/cb")
    with pytest.raises(AppException) as e:
        await svc.complete_oauth(uid, PROVIDER, OAuthCallbackRequest(code="c", state="wrong-state"))
    assert e.value.code == ErrorCode.INTEGRATION_INVALID


async def test_token_encrypted_at_rest(db, user, fake_provider):
    uid = await _scoped(db, user.id)
    resp = await _start_complete(db, uid)
    assert resp.provider == PROVIDER and resp.account_identifier == "acct@example.com"
    row = await integration_repo.get(db, uid, resp.id)
    assert row.access_token_enc != "at123"  # 明文绝不落库
    assert decrypt_token(row.access_token_enc) == "at123"
    assert decrypt_token(row.refresh_token_enc) == "rt123"


async def test_get_access_token_refreshes_when_expired(db, user, fake_provider):
    uid = await _scoped(db, user.id)
    resp = await _start_complete(db, uid)
    await _scoped(db, uid)  # complete commit 后上下文失效
    # 手动把 expires_at 改成已过期
    row = await integration_repo.get(db, uid, resp.id)
    row.expires_at = datetime.now(UTC) - timedelta(minutes=5)
    await db.flush()
    token = await IntegrationService(db, await _redis()).get_access_token(uid, resp.id)
    assert token == "at_new"  # 过期自动刷新
    await _scoped(db, uid)
    row2 = await integration_repo.get(db, uid, resp.id)
    assert decrypt_token(row2.access_token_enc) == "at_new"
    assert row2.expires_at > datetime.now(UTC)


async def test_revoked_integration_rejected(db, user, fake_provider):
    uid = await _scoped(db, user.id)
    resp = await _start_complete(db, uid)
    await _scoped(db, uid)
    assert await integration_service.do_revoke(db, uid, resp.id)
    assert fake_provider.revoked
    with pytest.raises(AppException) as e:
        await IntegrationService(db, await _redis()).get_access_token(uid, resp.id)
    assert e.value.code == ErrorCode.INTEGRATION_INVALID


async def test_isolation_across_users(db, user, fake_provider):
    a = await _scoped(db, user.id)
    resp = await _start_complete(db, a)
    b = uuid.uuid4()
    await _scoped(db, b)
    # B 访问 A 的 integration：不存在（repo user_id 过滤 + RLS）
    with pytest.raises(AppException) as e:
        await IntegrationService(db, await _redis()).get_access_token(b, resp.id)
    assert e.value.code == ErrorCode.NOT_FOUND

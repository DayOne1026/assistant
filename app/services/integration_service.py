"""09 集成：IntegrationService（蓝图 09 service 段）。

start_oauth 发 state（Redis TTL 10min）；complete_oauth 校验 state → 换 token → 加密落库；
get_access_token 过期自动刷新；revoke 外部撤销 + 标记。token 明文绝不落库。
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ErrorCode
from app.integrations.crypto import decrypt_token, encrypt_token
from app.integrations.oauth import get_provider
from app.redis_client import RedisClient, redis_key
from app.repos.integrations import integration_repo
from app.schemas.integration import AuthUrlResponse, IntegrationResponse, OAuthCallbackRequest

STATE_TTL = 600  # state 10 分钟有效


class IntegrationService:
    def __init__(self, db: AsyncSession, redis: RedisClient):
        self._db = db
        self._redis = redis

    async def start_oauth(self, user_id: uuid.UUID, provider: str, redirect_uri: str) -> AuthUrlResponse:
        """生成 state → Redis 存 `app:oauth:{user_id}:{state}`（provider|redirect_uri）→ 返回授权 URL。"""
        state = secrets.token_urlsafe(32)
        await self._redis.set(
            redis_key("oauth", user_id, state), f"{provider}|{redirect_uri}", ex=STATE_TTL
        )
        auth_url = get_provider(provider).build_auth_url(state, redirect_uri)
        return AuthUrlResponse(auth_url=auth_url, state=state)

    async def complete_oauth(
        self, user_id: uuid.UUID, provider: str, data: OAuthCallbackRequest
    ) -> IntegrationResponse:
        """校验 state（防 CSRF）→ 换 token → 加密 upsert → 删 state。"""
        stored = await self._redis.get(redis_key("oauth", user_id, data.state))
        if not stored:
            raise AppException(ErrorCode.INTEGRATION_INVALID, "state 无效或已过期")
        stored_provider, redirect_uri = stored.split("|", 1)
        if stored_provider != provider:
            raise AppException(ErrorCode.INTEGRATION_INVALID, "state 与 provider 不匹配")
        tok = await get_provider(provider).fetch_token(data.code, redirect_uri)
        row = await integration_repo.upsert(
            self._db, user_id, provider, tok.account_identifier,
            access_token_enc=encrypt_token(tok.access_token),
            refresh_token_enc=encrypt_token(tok.refresh_token) if tok.refresh_token else None,
            token_type="Bearer",
            scope=tok.scope,
            expires_at=datetime.now(UTC) + timedelta(seconds=tok.expires_in),
        )
        await self._redis.delete(redis_key("oauth", user_id, data.state))
        await self._db.commit()
        return IntegrationResponse.model_validate(row)

    async def list(self, user_id: uuid.UUID) -> list[IntegrationResponse]:
        rows = await integration_repo.list(self._db, user_id)
        return [IntegrationResponse.model_validate(r) for r in rows]

    async def get_access_token(self, user_id: uuid.UUID, integration_id: uuid.UUID) -> str:
        """解密；过期自动刷新并回写。撤销/无 refresh/刷新失败抛 INTEGRATION_INVALID。"""
        row = await integration_repo.get(self._db, user_id, integration_id)
        if row is None:
            raise AppException(ErrorCode.NOT_FOUND, "集成不存在", status_code=404)
        if row.revoked_at:
            raise AppException(ErrorCode.INTEGRATION_INVALID, "集成已撤销")
        if row.expires_at and row.expires_at < datetime.now(UTC) + timedelta(seconds=60):
            if not row.refresh_token_enc:
                raise AppException(ErrorCode.INTEGRATION_INVALID, "无 refresh token，请重新授权")
            new = await get_provider(row.provider).refresh(decrypt_token(row.refresh_token_enc))
            await integration_repo.update_tokens(
                self._db, user_id, integration_id,
                access_token_enc=encrypt_token(new.access_token),
                expires_at=datetime.now(UTC) + timedelta(seconds=new.expires_in),
                refresh_token_enc=encrypt_token(new.refresh_token) if new.refresh_token else None,
            )
            await self._db.commit()
            return new.access_token
        return decrypt_token(row.access_token_enc)


async def verify_integration(db: AsyncSession, user_id: uuid.UUID, integration_id: uuid.UUID) -> None:
    """07 二次确认 verify：归属校验，不存在抛 404。"""
    row = await integration_repo.get(db, user_id, integration_id)
    if row is None:
        raise AppException(ErrorCode.NOT_FOUND, "集成不存在", status_code=404)


async def do_revoke(db: AsyncSession, user_id: uuid.UUID, integration_id: uuid.UUID) -> bool:
    """07 二次确认 do_delete：外部 revoke（尽力）+ 置 revoked_at。"""
    row = await integration_repo.get(db, user_id, integration_id)
    if row is None:
        return False
    try:
        await get_provider(row.provider).revoke(decrypt_token(row.access_token_enc))
    except AppException:
        pass  # 外部撤销失败不阻断本地标记
    return await integration_repo.revoke(db, user_id, integration_id)

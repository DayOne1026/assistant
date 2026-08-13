"""02 认证：AuthService——注册/登录/刷新/登出/改密（蓝图 02 services 段）。"""

import uuid
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppException, ErrorCode
from app.core.security import (
    blacklist_key,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    validate_password_policy,
    verify_password,
)
from app.db.models.users import User
from app.redis_client import RedisClient
from app.repos.users import refresh_token_repo, user_repo
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RegisterRequest, TokenResponse

settings = get_settings()

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuthService:
    def __init__(self, db: AsyncSession, redis: RedisClient):
        self.db = db
        self.redis = redis

    async def register_user(self, data: RegisterRequest) -> User:
        """唯一性校验(email/username) → 密码策略 → hash → 建用户。"""
        if await user_repo.get_by_email(self.db, data.email):
            raise AppException(ErrorCode.CONFLICT, "邮箱已被注册", status_code=409)
        if await user_repo.get_by_username(self.db, data.username):
            raise AppException(ErrorCode.CONFLICT, "用户名已被占用", status_code=409)
        validate_password_policy(data.password)
        user = await user_repo.create(
            self.db,
            email=data.email,
            username=data.username,
            hashed_password=hash_password(data.password),
            timezone=data.timezone,
        )
        await self.db.commit()
        return user

    async def login(self, data: LoginRequest) -> TokenResponse:
        """认证 + 锁定检查 + 失败计数 + 签发双 token。"""
        user = await user_repo.get_by_email(self.db, data.email)
        if user is None:
            raise AppException(ErrorCode.BAD_CREDENTIALS, "账号或密码错误", status_code=401)
        if user.is_locked and user.locked_until and user.locked_until > _now():
            raise AppException(ErrorCode.ACCOUNT_LOCKED, "账户已锁定，请稍后再试", status_code=423)
        if not verify_password(data.password, user.hashed_password):
            user.failed_login_count += 1
            if user.failed_login_count >= MAX_FAILED_LOGINS:
                user.is_locked = True
                user.locked_until = _now() + timedelta(minutes=LOCKOUT_MINUTES)
            await self.db.commit()
            raise AppException(ErrorCode.BAD_CREDENTIALS, "账号或密码错误", status_code=401)
        # 成功：复位计数，签发
        user.failed_login_count = 0
        user.is_locked = False
        user.locked_until = None
        await self.db.commit()
        return await self._issue_tokens(user.id)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        """校验 refresh → 轮换（旧 revoke、发新双 token）。"""
        h = sha256(refresh_token.encode()).hexdigest()
        row = await refresh_token_repo.get_by_hash(self.db, h)
        if row is None or row.revoked_at is not None or row.expires_at < _now():
            raise AppException(ErrorCode.INVALID_TOKEN, "refresh token 无效", status_code=401)
        row.revoked_at = _now()
        await self.db.commit()
        return await self._issue_tokens(row.user_id)

    async def logout(self, access_token: str, refresh_token: str | None) -> None:
        """access jti 入 Redis 黑名单(TTL=exp)；refresh 若给则 revoke。"""
        payload = decode_access_token(access_token)
        expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        ttl = max(0, int((expires_at - _now()).total_seconds()))
        await self.redis.set(blacklist_key(payload["jti"]), "1", ex=ttl)
        if refresh_token:
            h = sha256(refresh_token.encode()).hexdigest()
            row = await refresh_token_repo.get_by_hash(self.db, h)
            if row is not None and row.revoked_at is None:
                row.revoked_at = _now()
                await self.db.commit()

    async def change_password(self, user: User, data: ChangePasswordRequest) -> None:
        """旧密码校验 → 策略校验 → 改 hash → 全量 revoke 该用户 refresh。"""
        if not verify_password(data.old_password, user.hashed_password):
            raise AppException(ErrorCode.BAD_CREDENTIALS, "旧密码错误", status_code=401)
        validate_password_policy(data.new_password)
        user.hashed_password = hash_password(data.new_password)
        await refresh_token_repo.revoke_all_for_user(self.db, user.id)
        await self.db.commit()

    async def _issue_tokens(self, user_id: uuid.UUID) -> TokenResponse:
        access, jti, exp = create_access_token(user_id)
        raw, h, rt_jti = create_refresh_token()
        await refresh_token_repo.create(
            self.db,
            user_id=user_id,
            token_hash=h,
            jti=rt_jti,
            expires_at=_now() + timedelta(days=settings.refresh_token_expire_days),
        )
        await self.db.commit()
        return TokenResponse(
            access_token=access,
            refresh_token=raw,
            expires_in=settings.access_token_expire_minutes * 60,
        )

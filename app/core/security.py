"""02 认证：密码策略/散列、JWT 签发校验、不透明 refresh token、黑名单 key。"""

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWTError

from app.core.config import get_settings
from app.core.exceptions import AppException, ErrorCode

settings = get_settings()

_ALGORITHM = "HS256"

# 蓝图：≥8位，含字母+数字
PASSWORD_POLICY_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,64}$")

# Bearer 依赖（login 走 JSON body，tokenUrl 仅供 OpenAPI 文档）
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_prefix}/auth/login")


def validate_password_policy(password: str) -> None:
    """不满足(≥8位，含字母+数字)抛 PASSWORD_POLICY。"""
    if not PASSWORD_POLICY_RE.match(password):
        raise AppException(ErrorCode.PASSWORD_POLICY, "密码须≥8位且含字母和数字")


def hash_password(password: str) -> str:
    """bcrypt 散列。"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """校验密码。"""
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(user_id: uuid.UUID) -> tuple[str, uuid.UUID, datetime]:
    """签发 access token，返回 (token, jti, expires_at)。payload: sub=user_id, jti, exp。"""
    jti = uuid.uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": str(user_id), "jti": str(jti), "exp": expires_at}
    token = jwt.encode(payload, settings.secret_key, algorithm=_ALGORITHM)
    return token, jti, expires_at


def create_refresh_token() -> tuple[str, str, uuid.UUID]:
    """生成不透明 refresh token，返回 (raw_token, sha256_hex, jti)。"""
    raw = secrets.token_urlsafe(48)
    h = hashlib.sha256(raw.encode()).hexdigest()
    return raw, h, uuid.uuid4()


def decode_access_token(token: str) -> dict:
    """校验签名/过期，返回 payload；无效抛 TOKEN_EXPIRED/INVALID_TOKEN。"""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise AppException(ErrorCode.TOKEN_EXPIRED, "token 已过期", status_code=401)
    except PyJWTError:
        raise AppException(ErrorCode.INVALID_TOKEN, "token 无效", status_code=401)


def blacklist_key(jti: str) -> str:
    """03 规范收编 02 的裸 key：jwt 黑名单无 user_id 维度，用固定前缀。"""
    return f"app:jwt:blacklist:{jti}"


# --- 图片展示短时 token（06 图片库：<img> 带不了 header，query token 方案） ---
_IMAGE_TOKEN_TTL = 300  # 5 分钟


def create_image_token(user_id: uuid.UUID, image_id: uuid.UUID) -> str:
    """签发短时图片展示 token（scope=image + user_id + image_id + exp）。"""
    return jwt.encode(
        {
            "scope": "image",
            "sub": str(user_id),
            "img": str(image_id),
            "exp": datetime.now(timezone.utc) + timedelta(seconds=_IMAGE_TOKEN_TTL),
        },
        settings.secret_key,
        algorithm=_ALGORITHM,
    )


def verify_image_token(token: str, image_id: uuid.UUID) -> uuid.UUID | None:
    """校验图片 token，返回 user_id；无效/过期/不匹配返回 None。"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[_ALGORITHM])
    except PyJWTError:
        return None
    if payload.get("scope") != "image" or payload.get("img") != str(image_id):
        return None
    return uuid.UUID(payload["sub"])

"""09 集成：token 加密/解密（蓝图 09 crypto 段）。

Fernet 对称加密（settings.oauth_token_encryption_key 派生 32 字节 key）。
依赖 cryptography（pip install cryptography）；未装时调用抛清晰错误。
"""

import base64
import hashlib

from app.core.config import get_settings
from app.core.exceptions import AppException, ErrorCode


def _fernet():
    from cryptography.fernet import Fernet

    raw = get_settings().oauth_token_encryption_key.encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(key)


def encrypt_token(plain: str) -> str:
    """Fernet 加密（access/refresh token 落库前调用）。"""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_token(enc: str) -> str:
    """解密。key 轮换/损坏时抛 EXTERNAL_SERVICE_ERROR 提示重新授权（蓝图 09）。"""
    try:
        return _fernet().decrypt(enc.encode()).decode()
    except Exception:
        raise AppException(ErrorCode.EXTERNAL_SERVICE_ERROR, "token 解密失败，请重新授权", status_code=502)

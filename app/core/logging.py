"""12 日志脱敏 + 结构化 logger（蓝图 12 core/logging.py）。

红线：input/output/detail 落库前先 redact；password/token 字段永不打印。
"""

import json
import logging
import re
from typing import Any

from app.core.config import get_settings

_SENSITIVE_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<email>"),  # email
    (re.compile(r"\b1[3-9]\d{9}\b"), "<phone>"),  # 手机号
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "<jwt>"),  # JWT
]

# 敏感字段名：键命中即整体遮蔽
_SENSITIVE_KEYS = {"password", "token", "secret", "api_key", "authorization", "refresh_token"}


def redact(value: Any) -> Any:
    """递归脱敏：str 匹配敏感模式替换；dict/list 递归；敏感键整体遮蔽。"""
    if isinstance(value, str):
        for pattern, repl in _SENSITIVE_PATTERNS:
            value = pattern.sub(repl, value)
        return value
    if isinstance(value, dict):
        return {k: (f"<{k}>" if k.lower() in _SENSITIVE_KEYS else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    """结构化输出：{"ts","level","logger","msg"}，message 经 redact。"""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "msg": redact(record.getMessage()),
            },
            ensure_ascii=False,
        )


def get_logger(name: str) -> logging.Logger:
    """结构化 logger：生产仅 WARNING+，开发 DEBUG+。"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING if get_settings().env == "prod" else logging.DEBUG)
        logger.propagate = False
    return logger

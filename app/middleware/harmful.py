"""11 有害内容过滤中间件（蓝图 11 HarmfulFilterMiddleware）。

规则为主（蓝图 11）：敏感词 / URL 黑名单 / 异常字符；命中输入→400 拒绝，
命中输出→application/json 非流式响应脱敏替换（SSE/流式跳过，无法简单替换）。
可选 LLM 分类（慢）默认关。settings.harmful_filter_enabled 开关。
"""

import re

from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.exceptions import ErrorCode
from app.core.response import fail

settings = get_settings()

# 敏感词黑名单（示例清单，可扩展；须避免误伤正常业务词）
SENSITIVE_WORDS = ("自杀", "血腥", "赌博网站", "外挂")
# URL 黑名单模式（示例）
BAD_URL_RE = re.compile(r"https?://[a-z0-9.-]*(evil|malware|phishing)[a-z0-9.-]*", re.I)
# 异常控制字符
BAD_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# 输出脱敏映射
SANITIZE_MAP = {"自杀": "**", "血腥": "**", "赌博网站": "***", "外挂": "**"}


def _is_harmful(text: str) -> bool:
    return (
        any(w in text for w in SENSITIVE_WORDS)
        or bool(BAD_URL_RE.search(text))
        or bool(BAD_CHARS_RE.search(text))
    )


def _sanitize(text: str) -> str:
    for w, rep in SANITIZE_MAP.items():
        text = text.replace(w, rep)
    return text


class HarmfulFilterMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.harmful_filter_enabled:
            return await call_next(request)
        body = await request.body()  # Starlette body() 缓存，下游复用同一 Request 仍可读
        if body and _is_harmful(body.decode("utf-8", errors="ignore")):
            return JSONResponse(
                status_code=400,
                content=fail(ErrorCode.VALIDATION_ERROR, "内容包含敏感信息").model_dump(),
            )
        response = await call_next(request)
        return await self._sanitize_response(response)

    async def _sanitize_response(self, response):
        # 仅 JSON 非流式响应脱敏；SSE/流式跳过（对话流无法简单替换）。
        # body_iterator 一旦读取即耗尽，必须总是构造新 Response 返回。
        if "application/json" not in response.headers.get("content-type", ""):
            return response
        if isinstance(response, StreamingResponse):
            return response
        chunks = [chunk async for chunk in response.body_iterator]
        text = b"".join(chunks).decode("utf-8", errors="ignore")
        new_text = _sanitize(text)
        headers = dict(response.headers)
        headers.pop("content-length", None)  # body 长度可能变化
        return Response(
            content=new_text.encode("utf-8"),
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )

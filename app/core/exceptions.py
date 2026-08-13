from enum import Enum

from fastapi import Request
from fastapi.responses import JSONResponse


class ErrorCode(str, Enum):
    """全平台错误码枚举，完整对照表见 12。
    分段：1xxx 认证 / 2xxx 参数 / 3xxx 权限 / 4xxx 资源 / 5xxx 服务。
    """

    SUCCESS = "0"
    INVALID_TOKEN = "1001"
    TOKEN_EXPIRED = "1002"
    BAD_CREDENTIALS = "1003"
    ACCOUNT_LOCKED = "1004"
    PASSWORD_POLICY = "1005"
    VALIDATION_ERROR = "2001"
    IDEMPOTENCY_CONFLICT = "2002"
    PERMISSION_DENIED = "3001"
    ISOLATION_VIOLATION = "3002"
    TOOL_LEVEL_DENIED = "3003"
    NOT_FOUND = "4001"
    CONFLICT = "4002"
    DELETE_NOT_CONFIRMED = "4003"
    INTEGRATION_INVALID = "4004"
    LLM_ERROR = "5001"
    EXTERNAL_SERVICE_ERROR = "5002"
    RATE_LIMITED = "5003"


class AppException(Exception):
    """业务异常，Service/Repo 统一抛它。
    构造参数 (code, message, status_code, detail)。
    全局 handler 将其转为 ApiResponse(code, None, message)。
    """

    def __init__(self, code: ErrorCode, message: str, status_code: int = 400, detail: str | None = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    from app.core.response import ApiResponse  # ponytail: 延迟导入避免 core 内循环依赖

    return JSONResponse(
        status_code=exc.status_code,
        content=ApiResponse(code=exc.code.value, data=None, message=exc.message).model_dump(),
    )

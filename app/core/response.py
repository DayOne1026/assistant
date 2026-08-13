from typing import Any

from pydantic import BaseModel

from app.core.exceptions import ErrorCode


class ApiResponse(BaseModel):
    """统一响应体：成功 {"code":"0","data":...,"message":"ok"}。"""

    code: str = "0"
    data: Any = None
    message: str = "ok"


def ok(data: Any = None, message: str = "ok") -> ApiResponse:
    return ApiResponse(code="0", data=data, message=message)


def fail(code: ErrorCode, message: str) -> ApiResponse:
    return ApiResponse(code=code.value, data=None, message=message)

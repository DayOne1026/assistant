"""11 审计 API（蓝图 11 API 层）。

GET /audit-logs、GET /tool-logs（用户只能看自己的，repo 双过滤）；
POST /agent/tools/confirm：call_id 精确确认 或 confirm_latest 确认会话最近动作。
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_service
from app.core.deps import get_current_user_isolated, get_db, get_tool_registry
from app.core.exceptions import AppException, ErrorCode
from app.core.pagination import PageParams
from app.core.response import ok
from app.db.models.users import User
from app.schemas.audit import ToolConfirmRequest

router = APIRouter(tags=["audit"])


@router.get("/audit-logs")
async def list_audit_logs(
    page: int = 1,
    page_size: int = 20,
    action: str | None = None,
    resource_type: str | None = None,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    p = PageParams(page=page, page_size=page_size)
    return ok(await audit_service.list_audit_logs(db, user.id, action, resource_type, p))


@router.get("/tool-logs")
async def list_tool_logs(
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    p = PageParams(page=page, page_size=page_size)
    return ok(await audit_service.list_tool_logs(db, user.id, p))


@router.post("/agent/tools/deny")
async def deny_tool(
    data: ToolConfirmRequest,
    user: User = Depends(get_current_user_isolated),
    registry=Depends(get_tool_registry),
):
    """精确拒绝（call_id）或拒绝会话最近动作（confirm_latest 语义复用，11 确认流程）。"""
    if data.call_id:
        result = await registry.deny(user.id, data.call_id, data.conversation_id)
    elif data.confirm_latest:
        if not data.conversation_id:
            raise AppException(
                ErrorCode.VALIDATION_ERROR, "deny_latest 需带 conversation_id", status_code=400
            )
        result = await registry.deny_latest(user.id, data.conversation_id)
    else:
        raise AppException(
            ErrorCode.VALIDATION_ERROR, "call_id 或 confirm_latest 必填一个", status_code=400
        )
    return ok(result)


@router.post("/agent/tools/confirm")
async def confirm_tool(
    data: ToolConfirmRequest,
    user: User = Depends(get_current_user_isolated),
    registry=Depends(get_tool_registry),
):
    """精确确认（call_id）或确认会话最近动作（confirm_latest）。"""
    if data.call_id:
        result = await registry.confirm(user.id, data.call_id, data.conversation_id)
    elif data.confirm_latest:
        if not data.conversation_id:
            raise AppException(
                ErrorCode.VALIDATION_ERROR, "confirm_latest 需带 conversation_id", status_code=400
            )
        result = await registry.confirm_latest(user.id, data.conversation_id)
    else:
        raise AppException(
            ErrorCode.VALIDATION_ERROR, "call_id 或 confirm_latest 必填一个", status_code=400
        )
    return ok(result)

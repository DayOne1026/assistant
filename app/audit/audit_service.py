"""11 审计服务（蓝图 11 audit 段）。

log_audit / log_tool_call / complete_tool_call 只 flush（事务归调用方：
delete_service 与 tools.py 自建 session 各自 commit）；list_* 带 user_id 过滤（隔离）。
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, PageParams
from app.repos.audit import audit_repo, tool_log_repo
from app.schemas.audit import AuditLogResponse, ToolLogResponse


async def log_audit(
    db: AsyncSession, user_id: uuid.UUID, action: str, resource_type: str,
    resource_id: uuid.UUID | None = None, detail: dict | None = None,
    request=None, conversation_id: uuid.UUID | None = None,
) -> None:
    """业务操作审计（07/10 调用点：delete_service 二次确认删除）。request 提取 ip/user_agent。"""
    ip = user_agent = None
    if request is not None:
        ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
    await audit_repo.create(
        db, user_id, action, resource_type, resource_id, detail, conversation_id, ip, user_agent
    )


async def log_tool_call(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID | None,
    name: str, params: dict, level: str, decision: str, call_id: uuid.UUID,
) -> None:
    """工具调用审计（tools.py call 里 pending 预录）。"""
    await tool_log_repo.create(
        db, user_id, conversation_id, call_id, name, level, decision, params
    )


async def complete_tool_call(
    db: AsyncSession, call_id: uuid.UUID, output=None, decision: str = "approved",
) -> None:
    """确认/拒绝后回写 decision/output。"""
    await tool_log_repo.complete(db, call_id, decision, output)


async def list_audit_logs(
    db: AsyncSession, user_id: uuid.UUID, action: str | None, resource_type: str | None,
    p: PageParams,
) -> Page:
    rows, total = await audit_repo.list(
        db, user_id, (p.page - 1) * p.page_size, p.page_size, action, resource_type
    )
    return Page(
        items=[AuditLogResponse.model_validate(r) for r in rows],
        total=total, page=p.page, page_size=p.page_size,
    )


async def list_tool_logs(
    db: AsyncSession, user_id: uuid.UUID, p: PageParams
) -> Page:
    rows, total = await tool_log_repo.list(db, user_id, (p.page - 1) * p.page_size, p.page_size)
    return Page(
        items=[ToolLogResponse.model_validate(r) for r in rows],
        total=total, page=p.page, page_size=p.page_size,
    )

"""11 审计：出参 + 工具确认入参（蓝图 11 Pydantic Schema）。"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: str
    resource_type: str
    resource_id: uuid.UUID | None
    detail: dict[str, Any] | None
    created_at: datetime


class ToolLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tool_name: str
    level: str
    decision: str
    created_at: datetime


class ToolConfirmRequest(BaseModel):
    """POST /agent/tools/confirm：call_id 精确确认 或 confirm_latest 确认最近动作。"""

    call_id: uuid.UUID | None = None
    confirm_latest: bool = False
    conversation_id: uuid.UUID | None = None

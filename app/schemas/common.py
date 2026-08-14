"""通用二次确认删除（蓝图 07 common.py，日程/任务/文档/会话共用）。"""

import uuid

from pydantic import BaseModel, Field


class DeleteRequestResponse(BaseModel):
    resource_type: str
    resource_id: uuid.UUID
    delete_token: str
    expires_in: int = 300
    message: str = "再次提交以确认删除"


class DeleteConfirmRequest(BaseModel):
    delete_token: str = Field(min_length=1)

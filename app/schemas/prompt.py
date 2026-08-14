"""10 自定义 System Prompt：入参/出参（蓝图 10 Pydantic Schema）。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PromptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1)


class PromptEnableRequest(BaseModel):
    enabled: bool


class PromptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prompt: str
    enabled: bool
    created_at: datetime
    updated_at: datetime

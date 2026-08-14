"""07 任务：入参/出参（蓝图 07 Schema 段）。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TodoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    due_at: datetime | None = None


class TodoUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    due_at: datetime | None = None
    completed: bool | None = None


class TodoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    due_at: datetime | None
    completed: bool
    completed_at: datetime | None
    created_at: datetime

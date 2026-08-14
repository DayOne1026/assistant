"""07 日程：入参/出参（蓝图 07 Schema 段）。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ScheduleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    start_at: datetime
    end_at: datetime | None = None
    reminder_at: datetime | None = None


class ScheduleUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    reminder_at: datetime | None = None
    status: Literal["active", "cancelled"] | None = None


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    start_at: datetime
    end_at: datetime | None
    reminder_at: datetime | None
    status: str
    created_at: datetime

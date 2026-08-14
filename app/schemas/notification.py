"""08 通知：入参/出参（蓝图 08 Schema 段）。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReminderCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str | None = None
    notify_at: datetime
    channel: Literal["ws", "email"] = "ws"
    ref_type: str | None = None
    ref_id: uuid.UUID | None = None


class ReminderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    body: str | None
    notify_at: datetime
    channel: str
    status: str
    created_at: datetime


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    channel: str
    title: str
    body: str
    read_at: datetime | None
    created_at: datetime

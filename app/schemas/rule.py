"""10 自动化规则：入参/出参（蓝图 10 Pydantic Schema）。

trigger_config 示例：
  time:  {"cron": "0 9 * * *"}
  event: {"event": "schedule.created", "delay_seconds": 0}
action_config 示例：
  notify: {"title": "早安", "body": "今天有 {n} 个日程", "channel": "ws"}
  tool:   {"name": "create_todo", "params": {"title": "..."}}
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    trigger_type: Literal["time", "event"]
    trigger_config: dict[str, Any]
    action_type: Literal["notify", "tool"]
    action_config: dict[str, Any]
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    trigger_type: Literal["time", "event"] | None = None
    trigger_config: dict[str, Any] | None = None
    action_type: Literal["notify", "tool"] | None = None
    action_config: dict[str, Any] | None = None
    enabled: bool | None = None


class RuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    trigger_type: str
    trigger_config: dict[str, Any]
    action_type: str
    action_config: dict[str, Any]
    enabled: bool
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime

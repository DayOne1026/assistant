"""10 Skill：入参/出参（蓝图 10 Pydantic Schema）。

SkillStep.params 支持 {{key}} 模板占位，运行时按 SkillRunRequest.params 渲染。
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SkillStep(BaseModel):
    tool: str  # 工具名（11 注册表）或 "llm"
    params: dict[str, Any] = {}  # 固定参数或 {name: "{{param}}"} 模板
    prompt: str | None = None  # tool=llm 时的指令


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    description: str = Field(min_length=1, max_length=500)
    steps: list[SkillStep] = Field(min_length=1, max_length=20)


class SkillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    steps: list[SkillStep]
    enabled: bool
    created_at: datetime


class SkillRunRequest(BaseModel):
    params: dict[str, Any] = {}

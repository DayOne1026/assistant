"""04 对话与意图：Pydantic 入参/出参（蓝图 04 Schema 段）。"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    title: str | None = None


class ConversationUpdate(BaseModel):
    """对话改名。"""
    title: str = Field(min_length=1, max_length=200)


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    image_id: uuid.UUID | None = None  # 附带图片（图片库引用，图片理解）


class Attachment(BaseModel):
    """问答/消息里的图片或文件引用。url 已带短期展示 token，前端直接 <img>。"""

    type: Literal["image", "file"] = "image"
    image_id: uuid.UUID | None = None
    url: str | None = None
    thumbnail_url: str | None = None
    filename: str | None = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    tool_name: str | None
    attachments: list[Attachment] = []  # 历史图片引用（读取时后端补短期 URL，06）
    wait_ms: int | None = None  # 回复等待耗时（毫秒，13 前端计时落库）
    created_at: datetime


class IntentResult(BaseModel):
    """意图识别结构化输出。"""

    intent_name: str  # 见 INTENTS 表
    parameters: dict[str, Any] = Field(default_factory=dict)  # 实体/参数；路由后按意图 schema 二次校验
    confidence: float = Field(default=0.8, ge=0, le=1)


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID
    content: str


class ChatResponse(BaseModel):
    reply: str
    intent: IntentResult
    tool_calls: list[str] = []  # 本次调用的工具名
    attachments: list[Attachment] = []  # 图片/文件引用（图库检索/工具结果）
    wait_ms: int | None = None  # 回显本次等待耗时

"""05 记忆与知识图谱：Pydantic 入参/出参（蓝图 05 Schema 段）。"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# 图谱实体类型（蓝图 05：节点标签）
EntityType = Literal["Person", "Place", "Organization", "Topic", "Event", "Document"]


class ExtractedTriple(BaseModel):
    """从文本提取的三元组。"""

    subject: str
    predicate: str
    object: str
    subject_type: EntityType
    object_type: EntityType
    confidence: float = Field(ge=0, le=1)


class TripleExtraction(BaseModel):
    """包装顶层 list——多数 SDK 对顶层 list 结构化输出支持不稳，外包一层更稳。"""

    triples: list[ExtractedTriple]


class TripleResponse(BaseModel):
    subject: str
    predicate: str
    object: str
    confidence: float


class MemoryQueryRequest(BaseModel):
    question: str = Field(min_length=1)


class MemoryResponse(BaseModel):
    answer: str
    sources: list[str]  # 命中偏好 key / 图路径描述


class MemoryItem(BaseModel):
    key: str
    value: Any


class ProfileStruct(BaseModel):
    """画像结构化输出（三层兜底同 04）。"""

    location: str | None = None
    profession: str | None = None
    age_group: str | None = None
    interests: list[str] = []
    traits: list[str] = []
    summary: str  # 一段自然语言画像


class Profile(BaseModel):
    """用户画像读取模型（user_profiles 表）。ProfileService.get_profile 返回它。"""

    summary: str
    structured: dict | None = None
    facts_count: int = 0
    updated_at: datetime

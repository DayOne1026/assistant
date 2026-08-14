"""06 RAG：文档检索入参/出参（蓝图 06 Schema 段）。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentUpload(BaseModel):
    title: str | None = None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    filename: str
    status: str
    chunk_count: int
    created_at: datetime


class ChunkResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    content: str
    score: float | None = None


class RetrievalQuery(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(5, ge=1, le=20)


class RetrievalResponse(BaseModel):
    chunks: list[ChunkResponse]

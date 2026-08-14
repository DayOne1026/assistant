"""06 图片库：ImageResponse（蓝图 06 schema 段）。"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class ImageResponse(BaseModel):
    """图片展示信息（url 为短时 token 展示端点，前端直接 <img>）。"""

    id: uuid.UUID
    url: str
    thumbnail_url: str | None = None
    filename: str
    content_type: str
    size: int
    created_at: datetime


class ImageSearchRequest(BaseModel):
    """文字搜图入参（multipart 图片搜图走 File）。"""

    query_text: str
    top_k: int = 10

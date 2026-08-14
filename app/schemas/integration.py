"""09 集成：Schema（蓝图 09 schema 段）。绝不回显 token。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuthUrlResponse(BaseModel):
    auth_url: str
    state: str


class OAuthStartRequest(BaseModel):
    redirect_uri: str


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str


class IntegrationResponse(BaseModel):
    """绝不回显 token。from_attributes：model_validate(ORM 行)。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    account_identifier: str
    scope: str | None = None
    expires_at: datetime | None = None
    created_at: datetime

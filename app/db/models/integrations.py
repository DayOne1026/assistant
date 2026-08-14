"""09 集成：user_integrations 表（蓝图 09 数据模型）。

外部服务授权（Google/Outlook...）token 加密落库（Fernet，access_token_enc/refresh_token_enc）；
UNIQUE(provider, account_identifier, user_id) 防重复绑定。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UserScopedMixin


class UserIntegration(UserScopedMixin, TimestampMixin, Base):
    __tablename__ = "user_integrations"
    __table_args__ = (
        UniqueConstraint(
            "provider", "account_identifier", "user_id", name="uq_integration_provider_account"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # google / outlook / todoist...
    account_identifier: Mapped[str] = mapped_column(String(255), nullable=False)  # 外部账号标识
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)  # Fernet 加密
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)  # Fernet 加密
    token_type: Mapped[str] = mapped_column(String(20), default="Bearer")
    scope: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 撤销标记

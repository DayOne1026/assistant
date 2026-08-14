"""09 集成：integration_repo（蓝图 09）。repo 只 flush，事务提交归 service。

所有方法必带 user_id 过滤（03 约定，RLS 兜底）。
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.integrations import UserIntegration


class IntegrationRepo:
    async def upsert(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        provider: str,
        account_identifier: str,
        *,
        access_token_enc: str,
        refresh_token_enc: str | None,
        token_type: str,
        scope: str | None,
        expires_at: datetime | None,
    ) -> UserIntegration:
        """按 (provider, account_identifier, user_id) 唯一键 upsert，返回行。"""
        values = dict(
            user_id=user_id, provider=provider, account_identifier=account_identifier,
            access_token_enc=access_token_enc, refresh_token_enc=refresh_token_enc,
            token_type=token_type, scope=scope, expires_at=expires_at,
        )
        stmt = (
            pg_insert(UserIntegration)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["provider", "account_identifier", "user_id"],
                set_={
                    "access_token_enc": access_token_enc,
                    "refresh_token_enc": refresh_token_enc,
                    "scope": scope,
                    "expires_at": expires_at,
                    "revoked_at": None,  # 重新授权清除撤销标记
                },
            )
            .returning(UserIntegration)
        )
        return (await db.execute(stmt)).scalar_one()

    async def get(
        self, db: AsyncSession, user_id: uuid.UUID, integration_id: uuid.UUID
    ) -> UserIntegration | None:
        return (
            await db.execute(
                select(UserIntegration).where(
                    UserIntegration.user_id == user_id, UserIntegration.id == integration_id
                )
            )
        ).scalar_one_or_none()

    async def list(self, db: AsyncSession, user_id: uuid.UUID) -> list[UserIntegration]:
        return (
            await db.execute(
                select(UserIntegration)
                .where(UserIntegration.user_id == user_id)
                .order_by(UserIntegration.created_at.desc())
            )
        ).scalars().all()

    async def revoke(
        self, db: AsyncSession, user_id: uuid.UUID, integration_id: uuid.UUID
    ) -> bool:
        """置 revoked_at；不存在返回 False。"""
        row = await self.get(db, user_id, integration_id)
        if row is None:
            return False
        row.revoked_at = datetime.now()
        await db.flush()
        return True

    async def update_tokens(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        integration_id: uuid.UUID,
        *,
        access_token_enc: str,
        expires_at: datetime,
        refresh_token_enc: str | None = None,
    ) -> bool:
        """刷新后回写；不存在返回 False。"""
        row = await self.get(db, user_id, integration_id)
        if row is None:
            return False
        row.access_token_enc = access_token_enc
        row.expires_at = expires_at
        if refresh_token_enc:
            row.refresh_token_enc = refresh_token_enc
        await db.flush()
        return True


integration_repo = IntegrationRepo()

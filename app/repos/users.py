"""02 认证：user_repo / refresh_token_repo。repo 只 flush，事务提交归 service。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.users import RefreshToken, User


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UserRepo:
    async def get_by_email(self, db: AsyncSession, email: str) -> User | None:
        return (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()

    async def get_by_username(self, db: AsyncSession, username: str) -> User | None:
        return (
            await db.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()

    async def get_by_id(self, db: AsyncSession, user_id: uuid.UUID) -> User | None:
        return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()

    async def create(self, db: AsyncSession, **kwargs) -> User:
        user = User(**kwargs)
        db.add(user)
        await db.flush()
        return user


class RefreshTokenRepo:
    async def create(self, db: AsyncSession, **kwargs) -> RefreshToken:
        row = RefreshToken(**kwargs)
        db.add(row)
        await db.flush()
        return row

    async def get_by_hash(self, db: AsyncSession, token_hash: str) -> RefreshToken | None:
        return (
            await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        ).scalar_one_or_none()

    async def revoke_all_for_user(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        """改密码/注销时全量吊销该用户未过期的 refresh token。"""
        rows = (
            await db.execute(
                select(RefreshToken).where(
                    RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
                )
            )
        ).scalars().all()
        now = _now()
        for row in rows:
            row.revoked_at = now
        await db.flush()


user_repo = UserRepo()
refresh_token_repo = RefreshTokenRepo()

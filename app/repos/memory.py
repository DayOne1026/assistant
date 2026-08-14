"""05 记忆：preference_repo / profile_repo。repo 只 flush，事务提交归 service。

所有方法必带 user_id 过滤（03 约定，RLS 兜底）。
from __future__ annotations：类体内方法名 list 会遮蔽 builtin（类作用域注解求值），
字符串化注解规避。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.memory import UserPreference, UserProfile


class PreferenceRepo:
    async def upsert(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        key: str,
        value: Any,
        source: str = "chat",
        source_conversation_id: uuid.UUID | None = None,
    ) -> UserPreference:
        """同用户同 key 存在则更新，否则插入（PG 复合唯一 (user_id, key) on_conflict）。"""
        stmt = (
            pg_insert(UserPreference)
            .values(
                user_id=user_id,
                key=key,
                value=value,
                source=source,
                source_conversation_id=source_conversation_id,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "key"],
                set_={
                    "value": value,
                    "source": source,
                    "source_conversation_id": source_conversation_id,
                },
            )
            .returning(UserPreference)
        )
        return (await db.execute(stmt)).scalar_one()

    async def get_by_key(
        self, db: AsyncSession, user_id: uuid.UUID, key: str
    ) -> UserPreference | None:
        return (
            await db.execute(
                select(UserPreference).where(
                    UserPreference.user_id == user_id, UserPreference.key == key
                )
            )
        ).scalar_one_or_none()

    async def list(self, db: AsyncSession, user_id: uuid.UUID) -> list[UserPreference]:
        return (
            await db.execute(
                select(UserPreference)
                .where(UserPreference.user_id == user_id)
                .order_by(UserPreference.updated_at.desc())
            )
        ).scalars().all()

    async def search(
        self, db: AsyncSession, user_id: uuid.UUID, question: str
    ) -> list[UserPreference]:
        """模糊匹配偏好 key：question 按词切分，任一词 ilike key。"""
        terms = [t for t in question.replace("，", " ").replace(",", " ").split() if t]
        if not terms:
            return []
        cond = or_(*(UserPreference.key.ilike(f"%{t}%") for t in terms))
        return (
            await db.execute(
                select(UserPreference).where(UserPreference.user_id == user_id, cond)
            )
        ).scalars().all()


class ProfileRepo:
    async def get(self, db: AsyncSession, user_id: uuid.UUID) -> UserProfile | None:
        return (
            await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        ).scalar_one_or_none()

    async def upsert(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        summary: str | None,
        structured: dict | None,
        facts_count: int,
    ) -> UserProfile:
        """一人一份：存在更新，否则插入（user_id 主键 on_conflict）。"""
        stmt = (
            pg_insert(UserProfile)
            .values(
                user_id=user_id,
                summary=summary,
                structured=structured,
                facts_count=facts_count,
            )
            .on_conflict_do_update(
                index_elements=[UserProfile.user_id],
                set_={
                    "summary": summary,
                    "structured": structured,
                    "facts_count": facts_count,
                },
            )
            .returning(UserProfile)
        )
        return (await db.execute(stmt)).scalar_one()


preference_repo = PreferenceRepo()
profile_repo = ProfileRepo()

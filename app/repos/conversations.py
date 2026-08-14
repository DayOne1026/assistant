"""04 对话：conversation_repo / message_repo。repo 只 flush，事务提交归 service。

所有方法必带 user_id 过滤（03 约定，RLS 兜底）。
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversations import Conversation, Message


class ConversationRepo:
    async def create(self, db: AsyncSession, user_id: uuid.UUID, title: str) -> Conversation:
        conv = Conversation(user_id=user_id, title=title)
        db.add(conv)
        await db.flush()
        return conv

    async def update_title(
        self, db: AsyncSession, user_id: uuid.UUID, conv_id: uuid.UUID, title: str
    ) -> Conversation | None:
        """改名（归属校验）；不存在返回 None。返回对象供 commit 后直接返回（避免回查 RLS 表）。"""
        conv = await self.get(db, user_id, conv_id)
        if conv is None:
            return None
        conv.title = title
        await db.flush()
        return conv

    async def get(
        self, db: AsyncSession, user_id: uuid.UUID, conv_id: uuid.UUID
    ) -> Conversation | None:
        """归属校验：user_id + id 双过滤，软删视为不存在（跨用户读返回 None）。"""
        return (
            await db.execute(
                select(Conversation).where(
                    Conversation.id == conv_id, Conversation.user_id == user_id,
                    Conversation.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    async def list(
        self, db: AsyncSession, user_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[Conversation], int]:
        """分页列表（最新在前，排除软删），返回 (items, total)。"""
        where = [Conversation.user_id == user_id, Conversation.deleted_at.is_(None)]
        total = (
            await db.execute(
                select(func.count()).select_from(Conversation).where(*where)
            )
        ).scalar_one()
        rows = (
            await db.execute(
                select(Conversation)
                .where(*where)
                .order_by(Conversation.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), total

    async def soft_delete(
        self, db: AsyncSession, user_id: uuid.UUID, conv_id: uuid.UUID
    ) -> bool:
        """软删会话（deleted_at=now，07 通用二次确认后调用）。返回是否删到。"""
        conv = await self.get(db, user_id, conv_id)
        if conv is None:
            return False
        conv.deleted_at = datetime.now().astimezone()
        await db.flush()
        return True


class MessageRepo:
    async def create(
        self,
        db: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str,
        content: str,
        tool_name: str | None = None,
        meta: dict | None = None,
        wait_ms: int | None = None,
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            user_id=user_id,
            role=role,
            content=content,
            tool_name=tool_name,
            meta=meta,
            wait_ms=wait_ms,
        )
        db.add(msg)
        await db.flush()
        return msg

    async def list_by_conversation(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        conv_id: uuid.UUID,
        offset: int,
        limit: int,
        q: str | None = None,
    ) -> tuple[list[Message], int]:
        """按会话分页读历史（时间正序），q=内容搜索。"""
        where = [Message.conversation_id == conv_id, Message.user_id == user_id]
        if q:
            where.append(Message.content.ilike(f"%{q}%"))
        total = (
            await db.execute(select(func.count()).select_from(Message).where(*where))
        ).scalar_one()
        rows = (
            await db.execute(
                select(Message)
                .where(*where)
                .order_by(Message.created_at)
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), total


conversation_repo = ConversationRepo()
message_repo = MessageRepo()

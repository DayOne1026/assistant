"""04 对话：会话 CRUD service（蓝图 04 对话存储）。事务提交在此，repo 只 flush。"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ErrorCode
from app.core.pagination import Page, PageParams
from app.db.models.conversations import Conversation
from app.repos.conversations import conversation_repo
from app.schemas.chat import ConversationResponse


async def create_conversation(
    db: AsyncSession, user_id: uuid.UUID, title: str | None
) -> Conversation:
    conv = await conversation_repo.create(db, user_id, title or "新对话")
    await db.commit()
    return conv


async def update_conversation_title(
    db: AsyncSession, user_id: uuid.UUID, conv_id: uuid.UUID, title: str
) -> Conversation:
    """改名（归属校验）；不存在抛 404。
    commit 后直接返回 repo 对象（expire_on_commit=False 字段仍在），避免回查 RLS 表上下文失效。"""
    conv = await conversation_repo.update_title(db, user_id, conv_id, title)
    if conv is None:
        raise AppException(ErrorCode.NOT_FOUND, "会话不存在", status_code=404)
    await db.commit()
    return conv


async def list_conversations(
    db: AsyncSession, user_id: uuid.UUID, p: PageParams
) -> Page[ConversationResponse]:
    rows, total = await conversation_repo.list(
        db, user_id, (p.page - 1) * p.page_size, p.page_size
    )
    return Page(
        items=[ConversationResponse.model_validate(r) for r in rows],
        total=total,
        page=p.page,
        page_size=p.page_size,
    )


async def get_conversation(
    db: AsyncSession, user_id: uuid.UUID, conv_id: uuid.UUID
) -> Conversation:
    conv = await conversation_repo.get(db, user_id, conv_id)
    if conv is None:
        raise AppException(ErrorCode.NOT_FOUND, "会话不存在", status_code=404)
    return conv


async def soft_delete(
    db: AsyncSession, user_id: uuid.UUID, conv_id: uuid.UUID
) -> bool:
    """软删会话（delete_service.confirm_delete 的 do_delete 回调，07 通用二次确认）。"""
    return await conversation_repo.soft_delete(db, user_id, conv_id)

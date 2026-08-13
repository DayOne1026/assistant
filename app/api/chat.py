"""04 对话：/conversations CRUD + 历史消息（蓝图 04 API 层）。

POST /conversations/{id}/messages（跑 AgentRunner）归 04b。统一响应经 ApiResponse（00 约定）。
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_isolated, get_db
from app.core.pagination import Page, PageParams
from app.core.response import ok
from app.db.models.users import User
from app.repos.conversations import message_repo
from app.schemas.chat import ConversationCreate, ConversationResponse, MessageResponse
from app.services import conversation_service

router = APIRouter(tags=["chat"])


@router.post("/conversations")
async def create_conversation(
    data: ConversationCreate,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    conv = await conversation_service.create_conversation(db, user.id, data.title)
    return ok(ConversationResponse.model_validate(conv))


@router.get("/conversations")
async def list_conversations(
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    p = PageParams(page=page, page_size=page_size)
    return ok(await conversation_service.list_conversations(db, user.id, p))


@router.get("/conversations/{conv_id}/messages")
async def list_messages(
    conv_id: uuid.UUID,
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    await conversation_service.get_conversation(db, user.id, conv_id)  # 归属校验，跨用户 404
    rows, total = await message_repo.list_by_conversation(
        db, user.id, conv_id, (page - 1) * page_size, page_size, q
    )
    return ok(
        Page(
            items=[MessageResponse.model_validate(m) for m in rows],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.delete("/conversations/{conv_id}")
async def delete_conversation(
    conv_id: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    await conversation_service.delete_conversation(db, user.id, conv_id)
    return ok()

"""04 对话：/conversations CRUD + 历史消息（蓝图 04 API 层）。

POST /conversations/{id}/messages（跑 AgentRunner）归 04b。统一响应经 ApiResponse（00 约定）。
"""

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import get_runner
from app.core.deps import get_current_user_isolated, get_db, get_redis
from app.core.pagination import Page, PageParams
from app.core.response import ok
from app.db.models.users import User
from app.redis_client import RedisClient
from app.repos.conversations import message_repo
from app.schemas.chat import (
    ChatRequest,
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
    MessageResponse,
)
from app.schemas.common import DeleteConfirmRequest
from app.services import conversation_service, delete_service

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


@router.patch("/conversations/{conv_id}")
async def update_conversation_title(
    conv_id: uuid.UUID,
    data: ConversationUpdate,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    """对话改名（13 前端对话名称自定义）。"""
    conv = await conversation_service.update_conversation_title(db, user.id, conv_id, data.title)
    return ok(ConversationResponse.model_validate(conv))


@router.post("/conversations/{conv_id}/messages")
async def post_message(
    conv_id: uuid.UUID,
    data: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    """发消息跑 AgentRunner；Accept: text/event-stream 时 SSE 流式（04b）。"""
    await conversation_service.get_conversation(db, user.id, conv_id)  # 归属校验
    runner = get_runner()
    if "text/event-stream" in request.headers.get("accept", ""):
        return StreamingResponse(
            runner.stream(db, user.id, conv_id, data.content),
            media_type="text/event-stream",
        )
    return ok(await runner.run(db, user.id, conv_id, data.content))


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
async def request_delete_conversation(
    conv_id: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    """二次确认第 1 步：校验归属并发 delete_token（07 通用模式）。"""
    result = await delete_service.request_delete(
        db, redis, user.id, "conversation", conv_id, conversation_service.get_conversation
    )
    return ok(result)


@router.post("/conversations/{conv_id}/confirm")
async def confirm_delete_conversation(
    conv_id: uuid.UUID,
    data: DeleteConfirmRequest,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    """二次确认第 2 步：token 校验通过才软删。"""
    await delete_service.confirm_delete(
        db, redis, user.id, "conversation", conv_id, data.delete_token,
        conversation_service.soft_delete,
    )
    return ok()

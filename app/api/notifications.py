"""08 通知：/notifications、/reminders、WS /ws（蓝图 08 API 层）。

WS 鉴权：/ws?token=<access_token>，握手前校验失败 close(1008)。
"""

import uuid

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_isolated, get_db
from app.core.pagination import PageParams
from app.core.response import ok
from app.core.security import decode_access_token
from app.db.models.users import User
from app.schemas.notification import NotificationResponse, ReminderCreate, ReminderResponse
from app.services import notification_service

router = APIRouter(tags=["notifications"])


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str = Query(...)):
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except Exception:
        await websocket.close(code=1008)
        return
    manager = notification_service.manager
    await manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(user_id, websocket)


@router.get("/notifications")
async def list_notifications(
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    p = PageParams(page=page, page_size=page_size)
    return ok(await notification_service.list_notifications(db, user.id, p))


@router.post("/notifications/read-all")
async def mark_all_read(
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    await notification_service.mark_all_read(db, user.id)
    return ok()


@router.get("/notifications/unread-count")
async def unread_count(
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    return ok({"count": await notification_service.unread_count(db, user.id)})


@router.post("/notifications/{nid}/read")
async def mark_read(
    nid: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    await notification_service.mark_read(db, user.id, nid)
    return ok()


@router.post("/reminders")
async def create_reminder(
    data: ReminderCreate,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    r = await notification_service.schedule_reminder(db, user.id, data)
    return ok(ReminderResponse.model_validate(r))


@router.get("/reminders")
async def list_reminders(
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    p = PageParams(page=page, page_size=page_size)
    return ok(await notification_service.list_reminders(db, user.id, p))


@router.delete("/reminders/{rid}")
async def cancel_reminder(
    rid: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    await notification_service.cancel_reminder(db, user.id, rid)
    return ok()

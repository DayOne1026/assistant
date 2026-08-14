"""08 通知：NotificationService + ConnectionManager（蓝图 08 service 段）。

send_immediate 写表 + 推送（ws 走 ConnectionManager，email 走 send_email smtp 封装）；
schedule_reminder 供 07 日程联动调用。
manager 为全局单例：WS 连接按 user_id 分组，api/tasks/service 共用。
"""

import asyncio
import smtplib
import uuid
from email.message import EmailMessage

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppException, ErrorCode
from app.core.logging import get_logger
from app.core.pagination import Page, PageParams
from app.db.models.notifications import Notification, Reminder
from app.db.models.users import User
from app.repos.notifications import notification_repo, reminder_repo
from app.schemas.notification import NotificationResponse, ReminderCreate, ReminderResponse

logger = get_logger(__name__)


class ConnectionManager:
    """按 user_id 管理在线 WebSocket 连接，广播即时通知（蓝图 08）。"""

    def __init__(self) -> None:
        self._conns: dict[uuid.UUID, set[WebSocket]] = {}

    async def connect(self, user_id: uuid.UUID, ws: WebSocket) -> None:
        await ws.accept()
        self._conns.setdefault(user_id, set()).add(ws)

    async def disconnect(self, user_id: uuid.UUID, ws: WebSocket) -> None:
        conns = self._conns.get(user_id)
        if conns:
            conns.discard(ws)

    async def send_to_user(self, user_id: uuid.UUID, payload: dict) -> int:
        """推给该用户所有连接，返回推送数（在线才推，离线走轮询拉取）。"""
        sent = 0
        for ws in list(self._conns.get(user_id, set())):
            try:
                await ws.send_json(payload)
                sent += 1
            except Exception:
                # 连接已断开：清理，不阻断其他连接
                self._conns.get(user_id, set()).discard(ws)
        return sent


# 全局单例：WS 路由 connect/disconnect、send_immediate、Celery 任务共用
manager = ConnectionManager()


async def send_immediate(
    db: AsyncSession, user_id: uuid.UUID, title: str, body: str,
    payload: dict | None = None, channel: str = "ws",
) -> Notification:
    """即时通知：写表 + commit + 按渠道推送（ws 推送 / email 发送）。"""
    n = await notification_repo.create(db, user_id, "immediate", channel, title, body, payload)
    await db.commit()
    if channel == "email":
        await send_email(db, user_id, title, body)  # 失败内部降级，不阻断
    else:
        await manager.send_to_user(
            user_id, {"type": "notification", "id": str(n.id), "title": title, "body": body}
        )
    return n


async def send_email(db: AsyncSession, user_id: uuid.UUID, title: str, body: str) -> None:
    """email 渠道（蓝图 08）：查用户邮箱 → smtp 发送（asyncio.to_thread 包装阻塞 smtplib）。
    smtp 未配置/发送失败 → 记 warning 降级，不抛错（通知已落库，失败重试由上层调度控制）。"""
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_user:
        logger.warning("smtp 未配置，跳过邮件发送: %s", title)
        return
    email = (await db.execute(select(User.email).where(User.id == user_id))).scalar()
    if not email:
        return
    try:
        await asyncio.to_thread(_send_smtp_sync, settings, email, title, body)
    except Exception:
        logger.warning("邮件发送失败: %s -> %s", title, email)


def _send_smtp_sync(settings, to_addr: str, title: str, body: str) -> None:
    """阻塞 smtplib 发送（在 to_thread 内执行）。"""
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to_addr
    msg["Subject"] = title
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


async def schedule_reminder(
    db: AsyncSession, user_id: uuid.UUID, data: ReminderCreate
) -> Reminder:
    """建定时提醒（供 07 日程 reminder_at 联动调用）。"""
    r = await reminder_repo.create(
        db, user_id, data.title, data.body, data.notify_at, data.channel,
        data.ref_type, data.ref_id,
    )
    await db.commit()
    return r


async def cancel_reminder(db: AsyncSession, user_id: uuid.UUID, rid: uuid.UUID) -> None:
    if not await reminder_repo.cancel(db, user_id, rid):
        raise AppException(ErrorCode.NOT_FOUND, "提醒不存在或已发送", status_code=404)
    await db.commit()


async def list_reminders(db: AsyncSession, user_id: uuid.UUID, p: PageParams) -> Page:
    rows, total = await reminder_repo.list(db, user_id, (p.page - 1) * p.page_size, p.page_size)
    return Page(
        items=[ReminderResponse.model_validate(r) for r in rows],
        total=total, page=p.page, page_size=p.page_size,
    )


async def list_notifications(db: AsyncSession, user_id: uuid.UUID, p: PageParams) -> Page:
    rows, total = await notification_repo.list(
        db, user_id, (p.page - 1) * p.page_size, p.page_size
    )
    return Page(
        items=[NotificationResponse.model_validate(r) for r in rows],
        total=total, page=p.page, page_size=p.page_size,
    )


async def mark_read(db: AsyncSession, user_id: uuid.UUID, nid: uuid.UUID) -> None:
    if not await notification_repo.mark_read(db, user_id, nid):
        raise AppException(ErrorCode.NOT_FOUND, "通知不存在", status_code=404)
    await db.commit()


async def mark_all_read(db: AsyncSession, user_id: uuid.UUID) -> None:
    await notification_repo.mark_all_read(db, user_id)
    await db.commit()


async def unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    return await notification_repo.unread_count(db, user_id)

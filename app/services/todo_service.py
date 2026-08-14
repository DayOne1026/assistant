"""07 任务服务（蓝图 07 service 段）。事务提交在此，repo 只 flush。"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ErrorCode
from app.core.pagination import Page, PageParams
from app.db.models.schedules import Todo
from app.repos.schedules import todo_repo
from app.schemas.todo import TodoCreate, TodoResponse, TodoUpdate


async def create_todo(db: AsyncSession, user_id: uuid.UUID, data: TodoCreate) -> Todo:
    t = await todo_repo.create(db, user_id, data.title, data.description, data.due_at)
    await db.commit()
    return t


async def list_todos(
    db: AsyncSession, user_id: uuid.UUID, p: PageParams, completed: bool | None = None
) -> Page:
    rows, total = await todo_repo.list(
        db, user_id, (p.page - 1) * p.page_size, p.page_size, completed
    )
    return Page(
        items=[TodoResponse.model_validate(r) for r in rows],
        total=total, page=p.page, page_size=p.page_size,
    )


async def get_todo(db: AsyncSession, user_id: uuid.UUID, tid: uuid.UUID) -> Todo:
    t = await todo_repo.get(db, user_id, tid)
    if t is None:
        raise AppException(ErrorCode.NOT_FOUND, "任务不存在", status_code=404)
    return t


async def update_todo(
    db: AsyncSession, user_id: uuid.UUID, tid: uuid.UUID, data: TodoUpdate
) -> Todo:
    await get_todo(db, user_id, tid)
    t = await todo_repo.update(db, user_id, tid, data.model_dump(exclude_unset=True))
    await db.commit()
    return t


async def toggle_complete(
    db: AsyncSession, user_id: uuid.UUID, tid: uuid.UUID, completed: bool
) -> Todo:
    """快捷完成/取消（工具与 /todos/{id}/toggle 用）。"""
    await get_todo(db, user_id, tid)
    t = await todo_repo.set_completed(db, user_id, tid, completed)
    await db.commit()
    return t

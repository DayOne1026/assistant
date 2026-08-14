"""07 任务 API（蓝图 07 API 层，与 /schedules 同构 + /todos/{id}/toggle）。

DELETE 二次确认：第一次 DELETE 返回 delete_token，POST /todos/{id}/confirm 才真删。
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_isolated, get_db, get_redis
from app.core.pagination import PageParams
from app.core.response import ok
from app.db.models.users import User
from app.redis_client import RedisClient
from app.repos.schedules import todo_repo
from app.schemas.common import DeleteConfirmRequest
from app.schemas.todo import TodoCreate, TodoResponse, TodoUpdate
from app.services import delete_service, todo_service

router = APIRouter(tags=["todos"])


@router.post("/todos")
async def create_todo(
    data: TodoCreate,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    t = await todo_service.create_todo(db, user.id, data)
    return ok(TodoResponse.model_validate(t))


@router.get("/todos")
async def list_todos(
    page: int = 1,
    page_size: int = 20,
    completed: bool | None = None,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    p = PageParams(page=page, page_size=page_size)
    return ok(await todo_service.list_todos(db, user.id, p, completed))


@router.get("/todos/{tid}")
async def get_todo(
    tid: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    t = await todo_service.get_todo(db, user.id, tid)
    return ok(TodoResponse.model_validate(t))


@router.patch("/todos/{tid}")
async def update_todo(
    tid: uuid.UUID,
    data: TodoUpdate,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    t = await todo_service.update_todo(db, user.id, tid, data)
    return ok(TodoResponse.model_validate(t))


@router.post("/todos/{tid}/toggle")
async def toggle_todo(
    tid: uuid.UUID,
    completed: bool = True,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    t = await todo_service.toggle_complete(db, user.id, tid, completed)
    return ok(TodoResponse.model_validate(t))


@router.delete("/todos/{tid}")
async def request_delete_todo(
    tid: uuid.UUID,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    result = await delete_service.request_delete(
        db, redis, user.id, "todo", tid, todo_service.get_todo
    )
    return ok(result)


@router.post("/todos/{tid}/confirm")
async def confirm_delete_todo(
    tid: uuid.UUID,
    data: DeleteConfirmRequest,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
):
    await delete_service.confirm_delete(
        db, redis, user.id, "todo", tid, data.delete_token, todo_repo.soft_delete
    )
    return ok()

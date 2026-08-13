from typing import Generic, TypeVar

from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


class PageParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


def get_page_params(page: int, page_size: int) -> PageParams:
    """FastAPI 依赖：解析分页入参。"""
    return PageParams(page=page, page_size=page_size)


async def paginate(db: AsyncSession, stmt: Select, p: PageParams) -> Page:
    """count 子查询算 total，再 limit/offset 取当前页。"""
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await db.execute(stmt.limit(p.page_size).offset((p.page - 1) * p.page_size))
    ).scalars().all()
    return Page(items=list(rows), total=total, page=p.page, page_size=p.page_size)

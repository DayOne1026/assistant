"""03 数据隔离：PG RLS 请求级上下文（蓝图 03）。

fail-closed：未显式设置 app.current_user_id 时，RLS policy 查不到任何行。
set_config 第二参 is_local=true 即 SET LOCAL，事务结束自动失效，杜绝连接池串号。
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_tenant_context(session: AsyncSession, user_id: uuid.UUID) -> None:
    """在事务内设置 RLS 用户上下文。必须在任何业务查询前调用一次。"""
    await session.execute(
        text("SELECT set_config('app.current_user_id', :uid, true)"),
        {"uid": str(user_id)},
    )


async def clear_tenant_context(session: AsyncSession) -> None:
    """事务结束后清理，防连接复用串号（SET LOCAL 自动清，兜底显式清）。"""
    await session.execute(text("SELECT set_config('app.current_user_id', '', true)"))


async def assert_rls_enabled(session: AsyncSession, table: str) -> bool:
    """确认该表 RLS + {table}_user_isolation policy 已启用，用于启动自检/测试。"""
    row = (
        await session.execute(
            text(
                """
                SELECT c.relrowsecurity AS rls,
                       EXISTS (
                           SELECT 1 FROM pg_policy p
                           WHERE p.polrelid = c.oid
                             AND p.polname = :policy
                       ) AS policy
                FROM pg_class c
                WHERE c.relname = :table
                """
            ),
            {"table": table, "policy": f"{table}_user_isolation"},
        )
    ).mappings().first()
    if row is None:
        return False
    return bool(row["rls"] and row["policy"])

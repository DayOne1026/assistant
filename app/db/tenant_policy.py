"""03 数据隔离：业务表 RLS policy 迁移 helper（蓝图 03 迁移段）。

每张带 user_id 的业务表建表后调用 enable_rls() 启用行级隔离。
alembic 完整基建归 12 部署，届时迁移内直接调用本函数。
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 蓝图 03 迁移清单：需 ENABLE ROW LEVEL SECURITY 的业务表
# （refresh_tokens 不适用 RLS，走应用层过滤；users 为认证表不加）
BUSINESS_TABLES = (
    "schedules",
    "todos",
    "conversations",
    "messages",
    "user_preferences",
    "documents",
    "document_chunks",
    "skills",
    "automation_rules",
    "user_integrations",
)


async def enable_rls(session: AsyncSession, table: str) -> None:
    """为单张业务表启用 RLS + {table}_user_isolation policy。

    USING 管 SELECT/UPDATE/DELETE，WITH CHECK 管 INSERT/UPDATE；
    未设置 app.current_user_id 时 current_setting 抛错 → 查不到（fail-closed）。
    FORCE 强制表 owner 也受 RLS 约束（否则 owner 绕过，见 03 修复说明）。
    table 名必须来自可信常量（BUSINESS_TABLES），不接受用户输入。
    """
    await session.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    await session.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
    await session.execute(
        text(
            f"""
            CREATE POLICY {table}_user_isolation ON {table}
            USING (user_id = current_setting('app.current_user_id')::uuid)
            WITH CHECK (user_id = current_setting('app.current_user_id')::uuid)
            """
        )
    )

"""0001 基线：建全部表 + 业务表 RLS policy（03/12）。

upgrade：Base.metadata.create_all（checkfirst 幂等）建当前模型全部表；
对 BUSINESS_TABLES 中已建模的业务表启用 RLS（DROP POLICY IF EXISTS 再建，幂等）。
未建模的 user_integrations（归 09）自动跳过。
downgrade：drop_all。
"""

import app.db.models  # noqa: F401  注册全部模型到 metadata
from alembic import op
from sqlalchemy import text

from app.db.base import Base
from app.db.tenant_policy import BUSINESS_TABLES

revision = "0001"
down_revision = None


def upgrade() -> None:
    bind = op.get_bind()
    # pgvector 扩展：superuser 预建（init/10-vector.sql）；应用角色无权限建则跳过
    try:
        bind.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception:
        pass  # 非 superuser 无权限建扩展，假定 init 已预建

    Base.metadata.create_all(bind=bind)  # checkfirst=True：已存在表跳过

    for table in BUSINESS_TABLES:
        if table not in Base.metadata.tables:
            continue  # 未建模（user_integrations 归 09）不建
        bind.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        bind.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        bind.execute(text(f"DROP POLICY IF EXISTS {table}_user_isolation ON {table}"))
        bind.execute(
            text(
                f"CREATE POLICY {table}_user_isolation ON {table} "
                "USING (user_id = current_setting('app.current_user_id')::uuid) "
                "WITH CHECK (user_id = current_setting('app.current_user_id')::uuid)"
            )
        )


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())

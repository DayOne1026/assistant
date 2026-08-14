"""0003 集成：user_integrations 表 + RLS（蓝图 09）。

模型已注册进 metadata；幂等：表/RLS policy 已存在则跳过（新库 0001 create_all 即含）。
"""

import app.db.models  # noqa: F401  注册全部模型（含 UserIntegration）
from alembic import op
from sqlalchemy import inspect, text

from app.db.base import Base

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    bind = op.get_bind()
    if "user_integrations" not in inspect(bind).get_table_names():
        Base.metadata.tables["user_integrations"].create(bind, checkfirst=True)
    # RLS（幂等：DROP POLICY IF EXISTS 再建）
    bind.execute(text("ALTER TABLE user_integrations ENABLE ROW LEVEL SECURITY"))
    bind.execute(text("ALTER TABLE user_integrations FORCE ROW LEVEL SECURITY"))
    bind.execute(text("DROP POLICY IF EXISTS user_integrations_user_isolation ON user_integrations"))
    bind.execute(
        text(
            "CREATE POLICY user_integrations_user_isolation ON user_integrations "
            "USING (user_id = current_setting('app.current_user_id')::uuid) "
            "WITH CHECK (user_id = current_setting('app.current_user_id')::uuid)"
        )
    )


def downgrade() -> None:
    Base.metadata.tables["user_integrations"].drop(bind=op.get_bind(), checkfirst=True)

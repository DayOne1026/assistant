"""0004 对话：messages 加 wait_ms 列（13 回复等待耗时落库）。

wait_ms 记录前端实测的回复等待耗时（毫秒），随 assistant 消息持久化，
重新登录后历史消息仍能显示。
"""

import app.db.models  # noqa: F401
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("messages")}
    if "wait_ms" not in cols:
        op.add_column("messages", sa.Column("wait_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "wait_ms")

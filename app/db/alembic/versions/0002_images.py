"""0002 图片库：images 表 + RLS（蓝图 06）。

images 模型已注册进 metadata；0001 用 create_all 建表（新库 0001 即含 images），
本迁移幂等：表/RLS policy 已存在则跳过（增量升级用）。
"""

import app.db.models  # noqa: F401  注册全部模型（含 Image）
from alembic import op
from sqlalchemy import inspect, text

from app.db.base import Base

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    bind = op.get_bind()
    if "images" not in inspect(bind).get_table_names():
        Base.metadata.tables["images"].create(bind, checkfirst=True)
    # RLS（幂等：DROP POLICY IF EXISTS 再建）
    bind.execute(text("ALTER TABLE images ENABLE ROW LEVEL SECURITY"))
    bind.execute(text("ALTER TABLE images FORCE ROW LEVEL SECURITY"))
    bind.execute(text("DROP POLICY IF EXISTS images_user_isolation ON images"))
    bind.execute(
        text(
            "CREATE POLICY images_user_isolation ON images "
            "USING (user_id = current_setting('app.current_user_id')::uuid) "
            "WITH CHECK (user_id = current_setting('app.current_user_id')::uuid)"
        )
    )


def downgrade() -> None:
    Base.metadata.tables["images"].drop(bind=op.get_bind(), checkfirst=True)

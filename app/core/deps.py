"""依赖注入汇总。

get_current_user / get_tool_registry 依赖 02/11，本文件只留签名+职责（01 约定）。
"""

from app.core.config import get_settings
from app.core.storage import get_storage
from app.db.session import get_db
from app.neo4j_client import get_neo4j
from app.redis_client import get_redis


async def get_current_user():
    """Bearer 校验 + 黑名单检查（02）。"""
    raise NotImplementedError("02 认证模块实现")


def get_tool_registry():
    """Agent 工具注册表（11）。"""
    raise NotImplementedError("11 审计与安全模块实现")

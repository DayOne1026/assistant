"""11 工具权限框架（04b 先建骨架，07-10 注册工具、11 补审计）。

ToolLevel 四级权限 + Redis 挂起/确认/拒绝流程（蓝图 11 伪代码）。
audit 回调留占位（11 审计模块施工时注入）。全局单例，FastAPI 经 get_tool_registry 取。
"""

from __future__ import annotations  # 惰性求值注解：方法名 list 不 shadow 内置 list

import json
import uuid
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.exceptions import AppException, ErrorCode
from app.redis_client import RedisClient, redis_key

CONFIRM_TTL = 300  # 挂起动作 5 分钟有效期


class ToolLevel(str, Enum):
    READ_ONLY = "read_only"  # 直接执行
    CREATE_MODIFY = "create_modify"  # 用户确认后执行
    SEND_DELETE = "send_delete"  # 二次确认
    HIGH_RISK = "high_risk"  # 禁止注册


class ToolResult(BaseModel):
    status: Literal["done", "pending_confirmation", "denied"]
    call_id: uuid.UUID | None = None
    data: Any = None
    message: str = ""


class ToolDef(BaseModel):
    name: str
    description: str
    parameters_schema: dict  # JSON Schema，供 LLM 生成参数 + 服务端校验
    level: ToolLevel
    handler: Callable[[uuid.UUID, dict], Awaitable[Any]] = Field(exclude=True)


class ToolRegistry:
    """注册/查找/调用（权限+确认）。audit 归 11，工具注册归 07-10。"""

    def __init__(self, redis: RedisClient):
        self._redis = redis
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        if tool.level is ToolLevel.HIGH_RISK:
            raise AppException(ErrorCode.TOOL_LEVEL_DENIED, f"{tool.name} 属高危工具，禁止注册")
        if tool.name in self._tools:
            raise AppException(ErrorCode.CONFLICT, f"工具已存在: {tool.name}", status_code=409)
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def list(self) -> list[ToolDef]:
        return list(self._tools.values())

    async def call(
        self, user_id: uuid.UUID, name: str, params: dict,
        conversation_id: uuid.UUID | None = None,
    ) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            raise AppException(ErrorCode.NOT_FOUND, f"工具不存在: {name}", status_code=404)
        if tool.level is ToolLevel.HIGH_RISK:
            return ToolResult(status="denied", message="高危工具禁止调用")
        if not isinstance(params, dict):
            raise AppException(ErrorCode.VALIDATION_ERROR, "工具参数必须为对象")
        # ponytail: JSON Schema 参数校验留 11（07-10 工具注册后再加 jsonschema）
        call_id = uuid.uuid4()
        # ponytail: audit.log_tool_call(...) 占位，11 注入
        if tool.level is ToolLevel.READ_ONLY:
            data = await tool.handler(user_id, params)
            return ToolResult(status="done", call_id=call_id, data=data)
        detail = json.dumps(
            {
                "name": name,
                "params": params,
                "conversation_id": str(conversation_id) if conversation_id else None,
            }
        )
        await self._redis.set(
            redis_key("confirm-tool", user_id, str(call_id)), detail, ex=CONFIRM_TTL
        )
        if conversation_id:
            await self._redis.rpush(
                redis_key("confirm-pending", user_id, str(conversation_id)), str(call_id)
            )
        return ToolResult(status="pending_confirmation", call_id=call_id, message="该操作需你确认")

    async def confirm(
        self, user_id: uuid.UUID, call_id: uuid.UUID,
        conversation_id: uuid.UUID | None = None,
    ) -> ToolResult:
        raw = await self._redis.get(redis_key("confirm-tool", user_id, str(call_id)))
        if raw is None:
            return ToolResult(status="denied", message="确认已过期或无效")
        detail = json.loads(raw)
        name, params = detail["name"], detail["params"]
        if conversation_id and detail.get("conversation_id") != str(conversation_id):
            return ToolResult(status="denied", message="该动作不属于此会话")
        tool = self.get(name)
        data = await tool.handler(user_id, params)
        await self._redis.delete(redis_key("confirm-tool", user_id, str(call_id)))
        if conversation_id:
            await self._redis.lrem(
                redis_key("confirm-pending", user_id, str(conversation_id)), 0, str(call_id)
            )
        return ToolResult(status="done", call_id=call_id, data=data)

    async def get_pending(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> list[ToolResult]:
        ids = await self._redis.lrange(
            redis_key("confirm-pending", user_id, str(conversation_id)), 0, -1
        )
        result = []
        for cid in ids:
            raw = await self._redis.get(redis_key("confirm-tool", user_id, cid))
            if raw is None:
                continue
            d = json.loads(raw)
            result.append(
                ToolResult(
                    status="pending_confirmation",
                    call_id=uuid.UUID(cid),
                    message=f"待确认：{d['name']} {d['params']}",
                )
            )
        return result

    async def confirm_latest(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> ToolResult:
        ids = await self._redis.lrange(
            redis_key("confirm-pending", user_id, str(conversation_id)), -1, -1
        )
        if not ids:
            return ToolResult(status="denied", message="无可确认动作")
        return await self.confirm(user_id, uuid.UUID(ids[0]), conversation_id)

    async def deny(
        self, user_id: uuid.UUID, call_id: uuid.UUID,
        conversation_id: uuid.UUID | None = None,
    ) -> ToolResult:
        await self._redis.delete(redis_key("confirm-tool", user_id, str(call_id)))
        if conversation_id:
            await self._redis.lrem(
                redis_key("confirm-pending", user_id, str(conversation_id)), 0, str(call_id)
            )
        return ToolResult(status="denied", message="已取消")

    async def deny_latest(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> ToolResult:
        ids = await self._redis.lrange(
            redis_key("confirm-pending", user_id, str(conversation_id)), -1, -1
        )
        if not ids:
            return ToolResult(status="denied", message="无可取消动作")
        return await self.deny(user_id, uuid.UUID(ids[0]), conversation_id)


_registry: ToolRegistry | None = None


def get_registry(redis: RedisClient) -> ToolRegistry:
    """全局单例（首参 redis 首次生效，之后复用）。"""
    global _registry
    if _registry is None:
        _registry = ToolRegistry(redis)
    return _registry

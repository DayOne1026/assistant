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

from app.audit.audit_service import complete_tool_call, log_tool_call
from app.core.exceptions import AppException, ErrorCode
from app.db.session import async_session
from app.db.tenant import set_tenant_context
from app.redis_client import RedisClient, redis_key
from app.repos.schedules import schedule_repo, todo_repo
from app.schemas.schedule import ScheduleCreate, ScheduleUpdate
from app.schemas.todo import TodoCreate, TodoUpdate
from app.services import schedule_service, todo_service
from datetime import datetime

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
            call_id = uuid.uuid4()
            await self._write_tool_log(
                user_id, conversation_id, name, params, tool.level.value, "denied", call_id
            )
            return ToolResult(status="denied", message="高危工具禁止调用")
        if not isinstance(params, dict):
            raise AppException(ErrorCode.VALIDATION_ERROR, "工具参数必须为对象")
        # 11：JSON Schema 服务端校验（LLM 生成参数 → 失败 VALIDATION_ERROR）
        _validate_params(params, tool.parameters_schema)
        call_id = uuid.uuid4()
        await self._write_tool_log(
            user_id, conversation_id, name, params, tool.level.value, "pending", call_id
        )
        if tool.level is ToolLevel.READ_ONLY:
            data = await tool.handler(user_id, params)
            await self._complete_tool_log(call_id, data)
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
        await self._complete_tool_log(call_id, data)  # 11：decision → approved
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
        await self._complete_tool_log(call_id, None, decision="denied")  # 11：decision → denied
        await self._redis.delete(redis_key("confirm-tool", user_id, str(call_id)))
        if conversation_id:
            await self._redis.lrem(
                redis_key("confirm-pending", user_id, str(conversation_id)), 0, str(call_id)
            )
        return ToolResult(status="denied", message="已取消")

    async def _write_tool_log(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID | None,
        name: str, params: dict, level: str, decision: str, call_id: uuid.UUID,
    ) -> None:
        """审计写库：独立 session（tool_call_logs 无 RLS，不需 set_tenant_context）。"""
        async with async_session() as db:
            await log_tool_call(
                db, user_id, conversation_id, name, params, level, decision, call_id
            )
            await db.commit()

    async def _complete_tool_log(
        self, call_id: uuid.UUID, output=None, decision: str = "approved"
    ) -> None:
        async with async_session() as db:
            await complete_tool_call(db, call_id, output, decision)
            await db.commit()

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


def _validate_params(params: dict, schema: dict) -> None:
    """JSON Schema 服务端校验（11）。空 schema 放行；失败抛 VALIDATION_ERROR。
    惰性 import jsonschema（pyproject 追加依赖后 pip install）。"""
    if not schema:
        return
    from jsonschema import ValidationError, validate

    try:
        validate(params, schema)
    except ValidationError as e:
        raise AppException(
            ErrorCode.VALIDATION_ERROR, f"工具参数校验失败: {e.message}", status_code=400
        ) from e


def get_registry(redis: RedisClient) -> ToolRegistry:
    """全局单例（首参 redis 首次生效，之后复用）。"""
    global _registry
    if _registry is None:
        _registry = ToolRegistry(redis)
        register_06_tools(_registry)
        register_07_tools(_registry)
    return _registry


# --- 07 工具 handler（蓝图 07 Agent 工具表；审计/jsonschema 校验归 11）---
# handler 在独立事务内显式设 RLS 上下文（03），再调 service/repo。


async def _in_scope(user_id, fn):
    async with async_session() as db:
        await set_tenant_context(db, user_id)
        return await fn(db, user_id)


def _parse_dt(v):
    if v is None or isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v))


async def _handle_create_schedule(user_id, params):
    data = ScheduleCreate.model_validate(params)

    async def _fn(db, uid):
        s = await schedule_service.create_schedule(db, uid, data)
        return {"id": str(s.id), "title": s.title, "start_at": s.start_at.isoformat()}

    return await _in_scope(user_id, _fn)


async def _handle_list_schedules(user_id, params):
    start_at, end_at = _parse_dt(params.get("start_at")), _parse_dt(params.get("end_at"))

    async def _fn(db, uid):
        rows, total = await schedule_repo.list(db, uid, 0, 50, start_at, end_at)
        return {
            "total": total,
            "items": [
                {"id": str(r.id), "title": r.title, "start_at": r.start_at.isoformat(), "status": r.status}
                for r in rows
            ],
        }

    return await _in_scope(user_id, _fn)


async def _handle_get_schedule(user_id, params):
    sid = uuid.UUID(params["schedule_id"])

    async def _fn(db, uid):
        s = await schedule_service.get_schedule(db, uid, sid)
        return {"id": str(s.id), "title": s.title, "start_at": s.start_at.isoformat(), "status": s.status}

    return await _in_scope(user_id, _fn)


async def _handle_update_schedule(user_id, params):
    sid = uuid.UUID(params["schedule_id"])
    data = ScheduleUpdate.model_validate(params)

    async def _fn(db, uid):
        s = await schedule_service.update_schedule(db, uid, sid, data)
        return {"id": str(s.id), "title": s.title, "status": s.status}

    return await _in_scope(user_id, _fn)


async def _handle_delete_schedule(user_id, params):
    sid = uuid.UUID(params["schedule_id"])

    async def _fn(db, uid):
        await schedule_service.get_schedule(db, uid, sid)  # 归属校验
        await schedule_repo.soft_delete(db, uid, sid)
        await db.commit()
        return {"deleted": True, "id": str(sid)}

    return await _in_scope(user_id, _fn)


async def _handle_create_todo(user_id, params):
    data = TodoCreate.model_validate(params)

    async def _fn(db, uid):
        t = await todo_service.create_todo(db, uid, data)
        return {"id": str(t.id), "title": t.title, "completed": t.completed}

    return await _in_scope(user_id, _fn)


async def _handle_list_todos(user_id, params):
    completed = params.get("completed")
    if isinstance(completed, str):
        completed = completed.lower() == "true"

    async def _fn(db, uid):
        rows, total = await todo_repo.list(db, uid, 0, 50, completed)
        return {
            "total": total,
            "items": [
                {"id": str(r.id), "title": r.title, "completed": r.completed, "due_at": r.due_at.isoformat() if r.due_at else None}
                for r in rows
            ],
        }

    return await _in_scope(user_id, _fn)


async def _handle_update_todo(user_id, params):
    tid = uuid.UUID(params["todo_id"])
    data = TodoUpdate.model_validate(params)

    async def _fn(db, uid):
        t = await todo_service.update_todo(db, uid, tid, data)
        return {"id": str(t.id), "title": t.title, "completed": t.completed}

    return await _in_scope(user_id, _fn)


async def _handle_toggle_todo(user_id, params):
    tid = uuid.UUID(params["todo_id"])
    completed = bool(params.get("completed", True))

    async def _fn(db, uid):
        t = await todo_service.toggle_complete(db, uid, tid, completed)
        return {"id": str(t.id), "completed": t.completed}

    return await _in_scope(user_id, _fn)


async def _handle_delete_todo(user_id, params):
    tid = uuid.UUID(params["todo_id"])

    async def _fn(db, uid):
        await todo_service.get_todo(db, uid, tid)  # 归属校验
        await todo_repo.soft_delete(db, uid, tid)
        await db.commit()
        return {"deleted": True, "id": str(tid)}

    return await _in_scope(user_id, _fn)


def _id_only_schema() -> dict:
    return {
        "type": "object",
        "properties": {"schedule_id": {"type": "string", "format": "uuid"}},
        "required": ["schedule_id"],
    }


def _todo_id_schema() -> dict:
    return {
        "type": "object",
        "properties": {"todo_id": {"type": "string", "format": "uuid"}},
        "required": ["todo_id"],
    }


async def _handle_web_search(user_id, params):
    """联网搜索（06 Tavily）：query 搜索 → 答案 + 结果列表。key 走 config，无 key 降级。"""
    query = params.get("query")
    if not query:
        return {"message": "缺少查询词 query", "results": []}
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.tavily_api_key:
        return {"message": "联网搜索未配置（tavily_api_key 为空）", "results": []}
    from app.core.http_client import HttpClient

    resp = await HttpClient().request(
        "POST", "https://api.tavily.com/search",
        json={"query": query, "max_results": 5, "include_answer": True},
        headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
        timeout=15, retries=1, fallback=lambda: None,
    )
    if resp is None:
        return {"message": "联网搜索服务不可用", "results": []}
    data = resp.json()
    return {
        "answer": data.get("answer", ""),
        "results": [
            {"title": r.get("title"), "url": r.get("url"), "content": r.get("content")}
            for r in data.get("results", [])[:5]
        ],
    }


def register_06_tools(registry: ToolRegistry) -> None:
    """注册 06 联网搜索工具（蓝图 06 工具表）。"""
    registry.register(ToolDef(
        name="web_search", description="联网搜索（查天气、新闻、实时信息）",
        parameters_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "搜索查询词"}},
            "required": ["query"],
        },
        level=ToolLevel.READ_ONLY, handler=_handle_web_search,
    ))


def register_07_tools(registry: ToolRegistry) -> None:
    """注册 07 日程/任务工具（蓝图 07 Agent 工具表）。"""
    registry.register(ToolDef(
        name="create_schedule", description="创建日程",
        parameters_schema=ScheduleCreate.model_json_schema(),
        level=ToolLevel.CREATE_MODIFY, handler=_handle_create_schedule,
    ))
    registry.register(ToolDef(
        name="list_schedules", description="查询日程",
        parameters_schema={
            "type": "object",
            "properties": {
                "start_at": {"type": "string", "format": "date-time"},
                "end_at": {"type": "string", "format": "date-time"},
            },
        },
        level=ToolLevel.READ_ONLY, handler=_handle_list_schedules,
    ))
    registry.register(ToolDef(
        name="get_schedule", description="日程详情",
        parameters_schema=_id_only_schema(),
        level=ToolLevel.READ_ONLY, handler=_handle_get_schedule,
    ))
    registry.register(ToolDef(
        name="update_schedule", description="更新日程",
        parameters_schema={
            "type": "object",
            "properties": {"schedule_id": {"type": "string", "format": "uuid"}, **ScheduleUpdate.model_json_schema()["properties"]},
            "required": ["schedule_id"],
        },
        level=ToolLevel.CREATE_MODIFY, handler=_handle_update_schedule,
    ))
    registry.register(ToolDef(
        name="delete_schedule", description="删除日程（需用户确认）",
        parameters_schema=_id_only_schema(),
        level=ToolLevel.SEND_DELETE, handler=_handle_delete_schedule,
    ))
    registry.register(ToolDef(
        name="create_todo", description="创建任务",
        parameters_schema=TodoCreate.model_json_schema(),
        level=ToolLevel.CREATE_MODIFY, handler=_handle_create_todo,
    ))
    registry.register(ToolDef(
        name="list_todos", description="查询任务",
        parameters_schema={
            "type": "object",
            "properties": {"completed": {"type": "boolean"}},
        },
        level=ToolLevel.READ_ONLY, handler=_handle_list_todos,
    ))
    registry.register(ToolDef(
        name="update_todo", description="更新任务",
        parameters_schema={
            "type": "object",
            "properties": {"todo_id": {"type": "string", "format": "uuid"}, **TodoUpdate.model_json_schema()["properties"]},
            "required": ["todo_id"],
        },
        level=ToolLevel.CREATE_MODIFY, handler=_handle_update_todo,
    ))
    registry.register(ToolDef(
        name="toggle_todo", description="切换任务完成状态",
        parameters_schema={
            "type": "object",
            "properties": {"todo_id": {"type": "string", "format": "uuid"}, "completed": {"type": "boolean"}},
            "required": ["todo_id"],
        },
        level=ToolLevel.CREATE_MODIFY, handler=_handle_toggle_todo,
    ))
    registry.register(ToolDef(
        name="delete_todo", description="删除任务（需用户确认）",
        parameters_schema=_todo_id_schema(),
        level=ToolLevel.SEND_DELETE, handler=_handle_delete_todo,
    ))

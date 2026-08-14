"""10 自动化规则服务（蓝图 10 service 段）。事务提交在此，repo 只 flush。

evaluate_event：业务代码调用点（07 建日程后）检查 event 规则 → Redis 去重 → 执行。
run_rule：notify→08 send_immediate；tool→直接调 handler（规则=用户显式配置=预授权，
跳过 registry.call 的确认挂起——后台规则无法等用户确认）。
get_registry 一律函数内惰性 import（tools 顶层 import schedule_service，而 schedule_service
顶层 import 本模块，顶层 import 会成环）。
"""

import hashlib
import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ErrorCode
from app.core.pagination import Page, PageParams
from app.db.models.rules import AutomationRule
from app.redis_client import get_redis, redis_key
from app.repos.skills import rule_repo
from app.schemas.rule import RuleCreate, RuleResponse, RuleUpdate
from app.services import notification_service

EVENT_DEDUP_TTL = 60  # 同规则同 payload 事件去重窗口（秒）


async def create_rule(db: AsyncSession, user_id: uuid.UUID, data: RuleCreate) -> AutomationRule:
    r = await rule_repo.create(
        db, user_id, data.name, data.trigger_type, data.trigger_config,
        data.action_type, data.action_config, data.enabled,
    )
    await db.commit()
    return r


async def list_rules(db: AsyncSession, user_id: uuid.UUID, p: PageParams) -> Page:
    rows, total = await rule_repo.list(db, user_id, (p.page - 1) * p.page_size, p.page_size)
    return Page(
        items=[RuleResponse.model_validate(r) for r in rows],
        total=total, page=p.page, page_size=p.page_size,
    )


async def get_rule(db: AsyncSession, user_id: uuid.UUID, rule_id: uuid.UUID) -> AutomationRule:
    r = await rule_repo.get(db, user_id, rule_id)
    if r is None:
        raise AppException(ErrorCode.NOT_FOUND, "规则不存在", status_code=404)
    return r


async def update_rule(db: AsyncSession, user_id: uuid.UUID, rule_id: uuid.UUID, data: RuleUpdate) -> AutomationRule:
    await get_rule(db, user_id, rule_id)  # 归属校验
    r = await rule_repo.update(db, user_id, rule_id, data.model_dump(exclude_unset=True))
    await db.commit()
    return r


async def delete_rule(db: AsyncSession, user_id: uuid.UUID, rule_id: uuid.UUID) -> bool:
    """物理删除（供 delete_service 二次确认 do_delete）。"""
    return await rule_repo.delete(db, user_id, rule_id)


def _payload_hash(payload: dict | None) -> str:
    """payload 稳定摘要（去重 key 用）。"""
    return hashlib.sha256(json.dumps(payload or {}, sort_keys=True).encode()).hexdigest()[:16]


def _render(cfg: dict, payload: dict | None) -> dict:
    """递归渲染 action_config 中字符串的 {key} 占位（含嵌套 notify/tool 结构）；缺 key 捕获降级。"""
    payload = payload or {}
    out = {}
    for k, v in cfg.items():
        if isinstance(v, str):
            try:
                out[k] = v.format(**payload)
            except (KeyError, IndexError):
                out[k] = v
        elif isinstance(v, dict):
            out[k] = _render(v, payload)
        else:
            out[k] = v
    return out


async def _run_rule_core(db: AsyncSession, user_id: uuid.UUID, rule: AutomationRule, payload=None) -> None:
    """执行单条规则 action。notify→send_immediate；tool→直接调 handler（预授权）。"""
    cfg = _render(rule.action_config, payload)
    if rule.action_type == "notify":
        n = cfg.get("notify") or {}
        await notification_service.send_immediate(
            db, user_id,
            str(n.get("title") or rule.name),
            str(n.get("body") or ""),
            channel=str(n.get("channel") or "ws"),
        )
    elif rule.action_type == "tool":
        t = cfg.get("tool") or {}
        name, params = t.get("name"), t.get("params") or {}
        if not name:
            raise AppException(ErrorCode.VALIDATION_ERROR, "tool 规则缺少工具名", status_code=400)
        # 惰性 import 避免顶层环（tools → schedule_service → automation_service）
        from app.agent.tools import get_registry

        from app.core.config import get_settings
        from app.redis_client import RedisClient

        tool = get_registry(RedisClient(get_settings().redis_url)).get(name)
        if tool is None:
            raise AppException(ErrorCode.NOT_FOUND, f"工具不存在: {name}", status_code=404)
        await tool.handler(user_id, params)  # 预授权直接执行，不走确认挂起


async def run_rule(db: AsyncSession, user_id: uuid.UUID, rule_id: uuid.UUID, payload=None) -> None:
    """执行单条规则（Celery run_rule / 测试直调）。"""
    await _run_rule_core(db, user_id, await get_rule(db, user_id, rule_id), payload)


async def evaluate_event(
    db: AsyncSession, user_id: uuid.UUID, event: str, payload: dict | None = None
) -> int:
    """业务代码调用点（07 建日程后）：匹配 event 规则 → Redis 去重 → 执行，返回执行条数。

    去重：同一规则 + 同一 event + 同一 payload 在 EVENT_DEDUP_TTL 内只执行一次。
    """
    rules = await rule_repo.list_by_event(db, user_id, event)
    if not rules:
        return 0
    redis = await get_redis()
    executed = 0
    for r in rules:
        key = redis_key("event", user_id, event, str(r.id), _payload_hash(payload))
        if not await redis.setnx(key, "1", ex=EVENT_DEDUP_TTL):
            continue  # 短时间已触发过
        await _run_rule_core(db, user_id, r, payload)
        executed += 1
    return executed

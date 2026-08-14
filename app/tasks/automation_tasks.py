"""10 自动化规则：定时任务（蓝图 10 tasks 段）。

Celery worker 归 12 部署；测试直接调 async 核心（_scan_automation_rules/_run_rule）。
任务函数为同步 Celery 包装（独立进程无 event loop），内部 asyncio.run。
time 规则 cron 命中 + last_run_at 同分钟幂等；event 规则走 evaluate_event（业务调用点，Redis 去重）。
automation_rules 有 RLS 且无全局用户上下文，扫描逐活跃用户 set_tenant_context 查询。
"""

import asyncio
import uuid
from datetime import datetime

from sqlalchemy import select

from app.celery_app import celery_app
from app.db.models.users import User
from app.db.session import async_session
from app.db.tenant import set_tenant_context
from app.repos.skills import rule_repo


def _field_match(expr: str, val: int) -> bool:
    """单字段匹配：支持 *、数字、a-b、*/n、逗号组合。"""
    for part in expr.split(","):
        part = part.strip()
        if part in ("*", "?"):
            return True
        if "/" in part:
            base, step = part.split("/", 1)
            step = int(step)
            if base in ("", "*"):
                if val % step == 0:
                    return True
            elif "-" in base:
                lo, hi = map(int, base.split("-"))
                if lo <= val <= hi and (val - lo) % step == 0:
                    return True
            elif int(base) == val:
                return True
        elif "-" in part:
            lo, hi = map(int, part.split("-"))
            if lo <= val <= hi:
                return True
        elif part.isdigit() and int(part) == val:
            return True
    return False


def _cron_matches(cron: str, dt) -> bool:
    """5 字段 cron（分 时 日 月 周）命中判断。
    ponytail: minimal stdlib 实现（覆盖蓝图 cron 示例），复杂表达式升级 croniter。
    """
    fields = cron.split()
    if len(fields) != 5:
        return False
    values = [dt.minute, dt.hour, dt.day, dt.month, dt.isoweekday()]
    return all(_field_match(f, v) for f, v in zip(fields, values))


async def _run_rule(user_id, rule_id, payload=None, db=None) -> None:
    """执行单条规则（Celery run_rule 用；测试直调 async 核心）。
    db 为 None 自建连接；测试传 fixture db 走事务回滚。"""
    if db is None:
        async with async_session() as _db:
            await _run_rule_inner(_db, user_id, rule_id, payload)
    else:
        await _run_rule_inner(db, user_id, rule_id, payload)


async def _run_rule_inner(db, user_id, rule_id, payload=None) -> None:
    from app.services.automation_service import _run_rule_core  # 惰性，避免顶层环

    await set_tenant_context(db, user_id)
    rule = await rule_repo.get(db, user_id, uuid.UUID(rule_id))
    if rule is None:
        return
    await _run_rule_core(db, user_id, rule, payload)


@celery_app.task(bind=True, max_retries=2)
def run_rule(self, user_id, rule_id, payload=None) -> None:
    """Celery 同步包装（bind 保留重试语义，worker 部署 12 生效）。"""
    uid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    return asyncio.run(_run_rule(uid, rule_id, payload))


async def _scan_automation_rules(limit: int = 200, db=None) -> int:
    """Beat 每分钟：扫 time 规则 cron 命中 → 执行，返回执行条数。db 参数同 _run_rule。"""
    if db is None:
        async with async_session() as _db:
            return await _scan_automation_rules_inner(_db, limit)
    return await _scan_automation_rules_inner(db, limit)


async def _scan_automation_rules_inner(db, limit: int) -> int:
    now = datetime.now().astimezone()
    minute_start = now.replace(second=0, microsecond=0)
    ran = 0
    user_ids = (await db.execute(select(User.id).where(User.is_active))).scalars().all()
    for uid in user_ids:
        await set_tenant_context(db, uid)
        rules = await rule_repo.list_enabled_time(db, uid)
        for r in rules:
            cron = (r.trigger_config or {}).get("cron")
            if not cron or not _cron_matches(cron, now):
                continue
            if r.last_run_at is not None and r.last_run_at >= minute_start:
                continue  # 同分钟幂等：本分钟内已跑过
            await rule_repo.touch_last_run(db, r.id, now)
            await db.commit()
            from app.services.automation_service import _run_rule_core  # 惰性，避免顶层环

            await _run_rule_core(db, uid, r, {})
            ran += 1
    return ran


@celery_app.task
def scan_automation_rules(limit: int = 200) -> int:
    return asyncio.run(_scan_automation_rules(limit))

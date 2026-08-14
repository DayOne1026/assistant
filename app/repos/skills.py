"""10 Skill/自动化规则/System Prompt：skill_repo / rule_repo / prompt_repo。

repo 只 flush，事务提交归 service（07/08 约定）。所有方法必带 user_id 过滤（03，RLS 兜底）。
三张表无软删字段（蓝图未给），delete 为物理删。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.prompts import SystemPromptProfile
from app.db.models.rules import AutomationRule
from app.db.models.skills import Skill


class SkillRepo:
    async def create(
        self, db: AsyncSession, user_id: uuid.UUID, name: str,
        description: str, steps: list[dict[str, Any]],
    ) -> Skill:
        s = Skill(user_id=user_id, name=name, description=description, steps=steps)
        db.add(s)
        await db.flush()
        return s

    async def get(
        self, db: AsyncSession, user_id: uuid.UUID, skill_id: uuid.UUID
    ) -> Skill | None:
        """归属校验：user_id + id 双过滤，跨用户读返回 None。"""
        return (
            await db.execute(
                select(Skill).where(Skill.id == skill_id, Skill.user_id == user_id)
            )
        ).scalar_one_or_none()

    async def list(
        self, db: AsyncSession, user_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[Skill], int]:
        where = [Skill.user_id == user_id]
        total = (
            await db.execute(select(func.count()).select_from(Skill).where(*where))
        ).scalar_one()
        rows = (
            await db.execute(
                select(Skill)
                .where(*where)
                .order_by(Skill.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), total

    async def delete(self, db: AsyncSession, user_id: uuid.UUID, skill_id: uuid.UUID) -> bool:
        r = await db.execute(
            delete(Skill).where(Skill.id == skill_id, Skill.user_id == user_id)
        )
        await db.flush()
        return r.rowcount > 0


class RuleRepo:
    async def create(
        self, db: AsyncSession, user_id: uuid.UUID, name: str, trigger_type: str,
        trigger_config: dict, action_type: str, action_config: dict, enabled: bool = True,
    ) -> AutomationRule:
        r = AutomationRule(
            user_id=user_id, name=name, trigger_type=trigger_type,
            trigger_config=trigger_config, action_type=action_type,
            action_config=action_config, enabled=enabled,
        )
        db.add(r)
        await db.flush()
        return r

    async def get(
        self, db: AsyncSession, user_id: uuid.UUID, rule_id: uuid.UUID
    ) -> AutomationRule | None:
        return (
            await db.execute(
                select(AutomationRule).where(
                    AutomationRule.id == rule_id, AutomationRule.user_id == user_id
                )
            )
        ).scalar_one_or_none()

    async def list(
        self, db: AsyncSession, user_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[AutomationRule], int]:
        where = [AutomationRule.user_id == user_id]
        total = (
            await db.execute(select(func.count()).select_from(AutomationRule).where(*where))
        ).scalar_one()
        rows = (
            await db.execute(
                select(AutomationRule)
                .where(*where)
                .order_by(AutomationRule.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), total

    async def list_enabled_time(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> list[AutomationRule]:
        """enabled 的 time 规则（scan_automation_rules 用）。"""
        rows = (
            await db.execute(
                select(AutomationRule).where(
                    AutomationRule.user_id == user_id,
                    AutomationRule.enabled.is_(True),
                    AutomationRule.trigger_type == "time",
                )
            )
        ).scalars().all()
        return list(rows)

    async def list_by_event(
        self, db: AsyncSession, user_id: uuid.UUID, event: str
    ) -> list[AutomationRule]:
        """enabled 的 event 规则（evaluate_event 用，trigger_config.event 精确匹配）。"""
        rows = (
            await db.execute(
                select(AutomationRule).where(
                    AutomationRule.user_id == user_id,
                    AutomationRule.enabled.is_(True),
                    AutomationRule.trigger_type == "event",
                )
            )
        ).scalars().all()
        return [r for r in rows if (r.trigger_config or {}).get("event") == event]

    async def update(
        self, db: AsyncSession, user_id: uuid.UUID, rule_id: uuid.UUID, fields: dict
    ) -> AutomationRule | None:
        r = await self.get(db, user_id, rule_id)
        if r is None:
            return None
        for k, v in fields.items():
            setattr(r, k, v)  # 调用方 exclude_unset，显式 None 表示清空
        await db.flush()
        return r

    async def delete(self, db: AsyncSession, user_id: uuid.UUID, rule_id: uuid.UUID) -> bool:
        r = await db.execute(
            delete(AutomationRule).where(
                AutomationRule.id == rule_id, AutomationRule.user_id == user_id
            )
        )
        await db.flush()
        return r.rowcount > 0

    async def touch_last_run(
        self, db: AsyncSession, rule_id: uuid.UUID, last_run_at
    ) -> None:
        """scan 命中后写 last_run_at（同分钟幂等；跨用户扫描无 RLS 上下文问题，规则已定位）。"""
        await db.execute(
            update(AutomationRule).where(AutomationRule.id == rule_id).values(last_run_at=last_run_at)
        )
        await db.flush()


class PromptRepo:
    async def create(
        self, db: AsyncSession, user_id: uuid.UUID, name: str, prompt: str
    ) -> SystemPromptProfile:
        p = SystemPromptProfile(user_id=user_id, name=name, prompt=prompt)
        db.add(p)
        await db.flush()
        return p

    async def get(
        self, db: AsyncSession, user_id: uuid.UUID, pid: uuid.UUID
    ) -> SystemPromptProfile | None:
        return (
            await db.execute(
                select(SystemPromptProfile).where(
                    SystemPromptProfile.id == pid, SystemPromptProfile.user_id == user_id
                )
            )
        ).scalar_one_or_none()

    async def list_enabled(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> list[SystemPromptProfile]:
        """当前启用的人设（可多选，对话时全部拼入系统提示）。"""
        rows = (
            await db.execute(
                select(SystemPromptProfile)
                .where(
                    SystemPromptProfile.user_id == user_id,
                    SystemPromptProfile.enabled.is_(True),
                )
                .order_by(SystemPromptProfile.created_at)
            )
        ).scalars().all()
        return list(rows)

    async def list(
        self, db: AsyncSession, user_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[SystemPromptProfile], int]:
        where = [SystemPromptProfile.user_id == user_id]
        total = (
            await db.execute(select(func.count()).select_from(SystemPromptProfile).where(*where))
        ).scalar_one()
        rows = (
            await db.execute(
                select(SystemPromptProfile)
                .where(*where)
                .order_by(SystemPromptProfile.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), total

    async def delete(self, db: AsyncSession, user_id: uuid.UUID, pid: uuid.UUID) -> bool:
        r = await db.execute(
            delete(SystemPromptProfile).where(
                SystemPromptProfile.id == pid, SystemPromptProfile.user_id == user_id
            )
        )
        await db.flush()
        return r.rowcount > 0

    async def set_enabled(
        self, db: AsyncSession, user_id: uuid.UUID, pid: uuid.UUID, enabled: bool
    ) -> bool:
        r = await db.execute(
            update(SystemPromptProfile)
            .where(SystemPromptProfile.id == pid, SystemPromptProfile.user_id == user_id)
            .values(enabled=enabled)
        )
        await db.flush()
        return r.rowcount > 0


skill_repo = SkillRepo()
rule_repo = RuleRepo()
prompt_repo = PromptRepo()

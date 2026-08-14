"""10 Skill 服务（蓝图 10 service 段）。事务提交在此，repo 只 flush。

create_skill 校验 steps 工具名存在（tool=="llm" 或注册表有）；run_skill 调 SkillRunner。
registry 默认取全局单例，测试可注入 fake registry（不连真实库）。
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ErrorCode
from app.core.pagination import Page, PageParams
from app.db.models.skills import Skill
from app.repos.skills import skill_repo
from app.schemas.skill import SkillCreate, SkillResponse


def _get_registry(registry):
    """None → 全局单例（生产）；否则直接用传入的（测试 fake）。"""
    if registry is not None:
        return registry
    # 惰性：tools 顶层 import schedule_service，而 schedule_service import 本模块相关，避免顶层环
    from app.agent.tools import get_registry

    from app.core.config import get_settings
    from app.redis_client import RedisClient

    return get_registry(RedisClient(get_settings().redis_url))


def _validate_steps(registry, steps) -> None:
    """校验每个 step 的工具名：llm 合法；其余须在注册表。非法工具名拒绝（蓝图 10 测试要点）。"""
    for step in steps:
        if step.tool == "llm":
            continue
        if registry.get(step.tool) is None:
            raise AppException(
                ErrorCode.VALIDATION_ERROR, f"工具不存在: {step.tool}", status_code=400
            )


async def create_skill(db: AsyncSession, user_id: uuid.UUID, data: SkillCreate, registry=None) -> Skill:
    _validate_steps(_get_registry(registry), data.steps)
    s = await skill_repo.create(
        db, user_id, data.name, data.description, [st.model_dump() for st in data.steps]
    )
    await db.commit()
    return s


async def list_skills(db: AsyncSession, user_id: uuid.UUID, p: PageParams) -> Page:
    rows, total = await skill_repo.list(db, user_id, (p.page - 1) * p.page_size, p.page_size)
    return Page(
        items=[SkillResponse.model_validate(r) for r in rows],
        total=total, page=p.page, page_size=p.page_size,
    )


async def get_skill(db: AsyncSession, user_id: uuid.UUID, skill_id: uuid.UUID) -> Skill:
    s = await skill_repo.get(db, user_id, skill_id)
    if s is None:
        raise AppException(ErrorCode.NOT_FOUND, "技能不存在", status_code=404)
    return s


async def delete_skill(db: AsyncSession, user_id: uuid.UUID, skill_id: uuid.UUID) -> bool:
    """物理删除（供 delete_service 二次确认 do_delete）。"""
    return await skill_repo.delete(db, user_id, skill_id)


async def run_skill(
    db: AsyncSession, user_id: uuid.UUID, skill_id: uuid.UUID, params: dict, registry=None,
) -> dict:
    """取技能 → SkillRunner 按 steps 跑子图 → 返回 step 结果。"""
    from app.agent.skill_graph import SkillRunner  # 惰性：skill_graph 顶层不依赖本模块

    skill = await get_skill(db, user_id, skill_id)
    return await SkillRunner(_get_registry(registry)).run(user_id, None, skill, params)


async def find_skill_by_intent(
    db: AsyncSession, user_id: uuid.UUID, description: str
) -> Skill | None:
    """意图命中匹配：enabled 技能里 name 与描述互相子串包含。
    ponytail: 简单匹配；语义命中升级 LLM 打分（蓝图未给规格）。
    """
    rows, _ = await skill_repo.list(db, user_id, 0, 100)
    for s in rows:
        if s.enabled and (s.name in description or description in s.name):
            return s
    return None

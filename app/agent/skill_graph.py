"""10 Skill 机制：SkillRunner + skill_entry（蓝图 00 落位：skill_graph.py）。

SkillRunner 按 skill.steps 动态构建 LangGraph 子图（step_i 顺序节点 → END），
每步校验权限（registry.call）或跑 LLM，step_results 串成结果。
skill_entry 是主图（graph.py）的 skill 分支节点：按描述匹配技能 → 跑子图 → 注入 reply。
"""

import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent.state import AgentState
from app.agent.tools import ToolRegistry
from app.schemas.skill import SkillStep


class SkillState(TypedDict, total=False):
    user_id: uuid.UUID
    conversation_id: uuid.UUID | None
    params: dict[str, Any]
    step_results: list[dict]


def fmt(template: str, params: dict) -> str:
    """替换 {{key}} 占位为 params[key]；无占位符原样返回（蓝图 10 fmt）。"""
    out = template
    for k, v in params.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


class SkillRunner:
    """按 steps 动态构建 LangGraph 子图并执行。llm 供 step.tool=="llm" 分支。"""

    def __init__(self, registry: ToolRegistry, llm=None):
        self._registry = registry
        # 惰性实例化：蓝图默认 get_chat_model()，测试可注入 fake llm（None 兜底避免 import 时建连接）
        self._llm = llm

    async def run(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID | None,
        skill, params: dict,
    ) -> dict:
        """构建子图：step_i 节点按序执行工具或 LLM，返回最终 SkillState。"""
        steps = [SkillStep.model_validate(s) for s in skill.steps]  # JSONB 存 dict，转模型
        g = StateGraph(SkillState)
        for i, step in enumerate(steps):
            g.add_node(f"step_{i}", self._make_step_executor(step))
            if i > 0:
                g.add_edge(f"step_{i-1}", f"step_{i}")
        g.add_edge(f"step_{len(steps) - 1}", END)
        g.add_edge(START, "step_0")
        graph = g.compile()
        return await graph.ainvoke(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "params": params,
                "step_results": [],
            }
        )

    def _make_step_executor(self, step):
        async def executor(state: SkillState) -> dict:
            resolved = {
                k: (fmt(v, state["params"]) if isinstance(v, str) else v)
                for k, v in step.params.items()
            }
            if step.tool == "llm":
                llm = self._llm or get_chat_model()
                out = await llm.ainvoke((step.prompt or "").format(**state["params"]))
                result = {"content": getattr(out, "content", str(out))}
            else:
                # 11：权限 + 审计 + 会话确认（registry.call 对写工具挂起待确认）
                result = await self._registry.call(
                    state["user_id"], step.tool, resolved, state.get("conversation_id")
                )
                if hasattr(result, "model_dump"):
                    result = result.model_dump()
            return {
                "step_results": [
                    *state.get("step_results", []),
                    {"step": step.tool, "result": result},
                ]
            }

        return executor


async def skill_entry(state: AgentState, registry: ToolRegistry) -> dict:
    """10 定义：intent=trigger_skill，按描述匹配技能，跑子图，结果注入 reply。失败降级。"""
    description = state["messages"][-1]["content"]
    user_id = state["user_id"]
    # 惰性 import：skill_service 顶层 import SkillRunner（本模块），顶层 import 会成环
    from app.db.session import async_session
    from app.db.tenant import set_tenant_context
    from app.services.skill_service import find_skill_by_intent

    try:
        async with async_session() as db:
            await set_tenant_context(db, user_id)
            skill = await find_skill_by_intent(db, user_id, description)
            if skill is None:
                return {"reply": "未找到匹配的技能，可先创建或换个说法试试"}
            params = ((state.get("intent") or {}).get("parameters") or {}).get("params", {})
            result = await SkillRunner(registry).run(
                user_id, state.get("conversation_id"), skill, params
            )
            return {"reply": _format_skill_result(skill.name, result.get("step_results", []))}
    except Exception as e:
        return {"reply": f"技能执行失败：{getattr(e, 'message', str(e))}"}


def _format_skill_result(name: str, step_results: list[dict]) -> str:
    lines = [f"技能「{name}」执行完成："]
    for r in step_results:
        step, result = r.get("step"), r.get("result") or {}
        if isinstance(result, dict):
            if result.get("status") == "pending_confirmation":
                lines.append(f"- {step}: {result.get('message') or '待确认'}")
            else:
                data = result.get("data")
                lines.append(f"- {step}: {result.get('message') or (str(data) if data is not None else '完成')}")
        else:
            lines.append(f"- {step}: {result}")
    return "\n".join(lines)


def get_chat_model():
    """惰性取 LLM（避免 import 时实例化连接）。"""
    from app.core.llm import get_chat_model as _get

    return _get()

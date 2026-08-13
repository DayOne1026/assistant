"""04 PlanExecute 子图（蓝图 04 loops/plan_execute.py）：plan → execute ↔ replan 循环。"""

import uuid
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.agent.intent import INTENT_LLM
from app.agent.tools import ToolRegistry


class PlanStep(BaseModel):
    step: str  # 做什么
    tool: str | None = None  # 用哪个工具（空=LLM 直接做）
    params: dict = {}


class PlanExecuteState(TypedDict, total=False):
    task: str
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    plan: list[PlanStep]
    idx: int
    results: list[dict]
    final: str
    reply: str


class ReplanOutput(BaseModel):
    adjust: bool
    revised_plan: list[PlanStep] | None = None


def _task(state: PlanExecuteState) -> str:
    return state.get("task") or (
        state["messages"][-1]["content"] if state.get("messages") else ""
    )


def _summarize(state: PlanExecuteState) -> str:
    steps = [r.get("step") for r in state.get("results", [])]
    return f"已按计划完成 {len(steps)} 步：{' → '.join(steps) or '（无）'}"


def _build_plan(registry: ToolRegistry):
    async def plan(state: PlanExecuteState) -> dict:
        task = _task(state)
        tools = ", ".join(t.name for t in registry.list()) or "无可用工具"
        prompt = (
            f"任务：{task}\n可用工具：{tools}\n"
            '输出 JSON 数组，3-6 步：[{"step": "做什么", "tool": "工具名或null", "params": {}}]'
        )
        plan_list = await INTENT_LLM.with_structured_output(list[PlanStep]).ainvoke(prompt)
        return {"plan": plan_list, "idx": 0}

    return plan


def _build_execute(registry: ToolRegistry):
    async def execute(state: PlanExecuteState) -> dict:
        idx = state.get("idx", 0)
        p = state["plan"][idx]
        if p.tool:
            result = await registry.call(
                state["user_id"], p.tool, p.params, state.get("conversation_id")
            )
            obs = result.model_dump() if result else {"status": "error"}
        else:
            reply = await INTENT_LLM.ainvoke(f"子任务：{p.step}\n直接输出结果")
            obs = {"answer": reply.content}
        return {"results": [*state.get("results", []), {"step": p.step, **obs}]}

    return execute


async def replan(state: PlanExecuteState) -> dict:
    """判断是否偏离/需调整：是 → 重生成 plan 复位 idx；否则 idx+1；结束 → 汇总。"""
    idx = state.get("idx", 0)
    n = len(state.get("plan", []))
    if idx + 1 >= n:
        summary = _summarize(state)
        return {"final": summary, "reply": summary}
    next_idx = idx + 1
    last = (state.get("results") or [{}])[-1]
    prompt = (
        f"任务：{_task(state)}\n剩余计划：{[p.step for p in state['plan'][next_idx:]]}\n"
        f"刚完成：{last}\n下一步：{state['plan'][next_idx].step}\n"
        '输出 JSON：{"adjust": false} 或 {"adjust": true, "revised_plan": [剩余步骤数组]}'
    )
    try:
        out = await INTENT_LLM.with_structured_output(ReplanOutput).ainvoke(prompt)
    except Exception:
        out = ReplanOutput(adjust=False)
    if out.adjust and out.revised_plan:
        return {"plan": out.revised_plan, "idx": 0}
    return {"idx": next_idx}


def _route(state: PlanExecuteState) -> str:
    return "end" if state.get("final") else "execute"


def build_plan_subgraph(registry: ToolRegistry):
    builder = StateGraph(PlanExecuteState)
    builder.add_node("planning", _build_plan(registry))
    builder.add_node("execute", _build_execute(registry))
    builder.add_node("replan", replan)
    builder.add_edge(START, "planning")
    builder.add_edge("planning", "execute")
    builder.add_edge("execute", "replan")
    builder.add_conditional_edges("replan", _route, {"execute": "execute", "end": END})
    return builder.compile()

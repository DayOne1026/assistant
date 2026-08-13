"""04 ReAct 子图（蓝图 04 loops/react.py）：thought → (act ↔ think 循环) → 答案。最大 8 轮防死循环。"""

import uuid
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.agent.intent import INTENT_LLM
from app.agent.tools import ToolRegistry

MAX_STEPS = 16  # 8 轮（thought+observation 各占一条）


class ReActState(TypedDict, total=False):
    task: str
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    steps: list[dict]  # [{thought, action, observation}, ...]
    final: str
    reply: str  # 子图出口映射主图 reply


class ReActAction(BaseModel):
    tool: str | None = None
    params: dict = {}
    answer: str | None = None


class ReActThink(BaseModel):
    thought: str
    action: ReActAction


def _task(state: ReActState) -> str:
    return state.get("task") or (
        state["messages"][-1]["content"] if state.get("messages") else ""
    )


def _build_think(registry: ToolRegistry):
    async def think(state: ReActState) -> dict:
        task = _task(state)
        steps = state.get("steps", [])
        if len(steps) >= MAX_STEPS:
            return {"final": "已达最大轮数，稍后再试", "reply": "已达最大轮数，稍后再试"}
        tools = ", ".join(t.name for t in registry.list()) or "无可用工具"
        prompt = (
            f"任务：{task}\n可用工具：{tools}\n历史步骤：{steps}\n"
            '只能输出 JSON：{"thought": "思考", "action": {"tool": "工具名", "params": {}}}'
            ' 或 {"thought": "思考", "action": {"answer": "最终答案"}}。能回答就 answer 直接收尾。'
        )
        out = await INTENT_LLM.with_structured_output(ReActThink).ainvoke(prompt)
        if out.action.answer is not None:
            return {"final": out.action.answer, "reply": out.action.answer}
        return {"steps": [*steps, {"thought": out.thought, "action": out.action.model_dump()}]}

    return think


def _build_act(registry: ToolRegistry):
    async def act(state: ReActState) -> dict:
        last = state["steps"][-1]
        tool, params = last["action"]["tool"], last["action"].get("params", {})
        result = await registry.call(
            state["user_id"], tool, params, state.get("conversation_id")
        )
        obs = result.model_dump() if result else {"status": "error", "message": "工具调用失败"}
        return {"steps": [*state["steps"], {"observation": obs}]}

    return act


def _route(state: ReActState) -> str:
    return "end" if state.get("final") else "act"


def build_react_subgraph(registry: ToolRegistry):
    builder = StateGraph(ReActState)
    builder.add_node("think", _build_think(registry))
    builder.add_node("act", _build_act(registry))
    builder.add_edge(START, "think")
    builder.add_conditional_edges("think", _route, {"act": "act", "end": END})
    builder.add_edge("act", "think")
    return builder.compile()

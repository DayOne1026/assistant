"""04 Reflection 子图（蓝图 04 loops/reflection.py）：generate → critique ↔ revise，通过(score≥8)或满 3 轮结束。"""

import uuid
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.agent.intent import INTENT_LLM

MAX_ITERATIONS = 3
PASS_SCORE = 8


class ReflectionState(TypedDict, total=False):
    task: str
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    draft: str
    iterations: int
    issues: list[str]
    final: str
    reply: str


class CritiqueOutput(BaseModel):
    score: int = Field(ge=0, le=10)
    issues: list[str] = []


def _task(state: ReflectionState) -> str:
    return state.get("task") or (
        state["messages"][-1]["content"] if state.get("messages") else ""
    )


async def generate(state: ReflectionState) -> dict:
    reply = await INTENT_LLM.ainvoke(f"写作任务：{_task(state)}\n直接给出初稿")
    return {"draft": reply.content, "iterations": 0}


async def critique(state: ReflectionState) -> dict:
    draft = state["draft"]
    iterations = state.get("iterations", 0)
    if iterations >= MAX_ITERATIONS:
        return {"final": draft, "reply": draft}
    prompt = (
        f"任务：{_task(state)}\n草稿：{draft}\n"
        '输出 JSON：{"score": 0-10, "issues": ["问题"]}。score>=8 视为通过。'
    )
    out = await INTENT_LLM.with_structured_output(CritiqueOutput).ainvoke(prompt)
    if out.score >= PASS_SCORE:
        return {"final": draft, "reply": draft}
    return {"issues": out.issues, "iterations": iterations + 1}


async def revise(state: ReflectionState) -> dict:
    reply = await INTENT_LLM.ainvoke(
        f"任务：{_task(state)}\n按意见修订：{state.get('issues', [])}\n草稿：{state['draft']}\n给出修订版"
    )
    return {"draft": reply.content}


def _route(state: ReflectionState) -> str:
    return "end" if state.get("final") else "revise"


def build_reflection_subgraph(llm):
    builder = StateGraph(ReflectionState)
    builder.add_node("generate", generate)
    builder.add_node("critique", critique)
    builder.add_node("revise", revise)
    builder.add_edge(START, "generate")
    builder.add_edge("generate", "critique")
    builder.add_conditional_edges("critique", _route, {"revise": "revise", "end": END})
    builder.add_edge("revise", "critique")
    return builder.compile()

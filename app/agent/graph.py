"""04 对话：主对话图（蓝图 04 graph.py）。

intent_route → (工具执行 / 记忆 / RAG / Agent 子图) → finalize。
checkpointer 用 RedisSaver（依赖 RediSearch，redis-stack）。
"""

import uuid

from langgraph.checkpoint.redis import RedisSaver
from langgraph.graph import END, START, StateGraph

from app.agent.intent import INTENT_LLM, intent_route, route_by_intent
from app.agent.memory.graph_extractor import extract_triples
from app.agent.memory.graph_writer import GraphWriter
from app.agent.state import AgentState
from app.agent.tools import ToolRegistry
from app.db.session import async_session
from app.db.tenant import set_tenant_context
from app.neo4j_client import get_neo4j
from app.rag.embedding import EmbeddingService
from app.rag.pipeline import build_context
from app.repos.documents import chunk_repo
from app.services.memory_service import MemoryService

# ponytail: langgraph-checkpoint-redis 0.1.3 只实现 sync 方法，graph.ainvoke 走 async 版需适配
class _AsyncRedisSaver(RedisSaver):
    async def aget_tuple(self, config):
        return self.get_tuple(config)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        return self.list(config, filter=filter, before=before, limit=limit)

    async def aput(self, config, checkpoint, metadata, new_versions):
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        return self.put_writes(config, writes, task_id, task_path)


_checkpointer = None


def _get_checkpointer():
    global _checkpointer
    if _checkpointer is None:
        import redis as sync_redis

        from app.core.config import get_settings

        _checkpointer = _AsyncRedisSaver(
            redis_client=sync_redis.Redis.from_url(get_settings().redis_url)
        )
        _checkpointer.setup()
    return _checkpointer


# --- 外部节点占位（蓝图标注归属 11/05/06/10，对应模块施工时原位替换）---


async def tool_executor(state: AgentState, registry: ToolRegistry) -> dict:
    """11 定义。04b 阶段 registry 无工具（07-10 未注册），调 registry 得 NOT_FOUND → 降级提示。"""
    intent_name = (state.get("intent") or {}).get("intent_name", "default_chat")
    params = (state.get("intent") or {}).get("parameters", {})
    try:
        result = await registry.call(
            state["user_id"], intent_name, params, state.get("conversation_id")
        )
    except Exception as e:  # AppException 等
        return {"reply": f"该功能暂不可用（{getattr(e, 'message', str(e))}）", "tool_results": []}
    if result.status == "pending_confirmation":
        return {"reply": f"有一项待确认：{result.message}，回复『确认』执行", "tool_results": []}
    return {"reply": result.message or "完成", "tool_results": []}


async def memory_write(state: AgentState) -> dict:
    """05 定义：提取本次对话三元组写图谱。失败静默，不阻断。"""
    text = "".join(m["content"] for m in state["messages"] if m["role"] == "user")
    user_id = state["user_id"]
    try:
        triples = await extract_triples(text)
        written = await GraphWriter(await get_neo4j()).write_triples(
            user_id, triples, state.get("conversation_id")
        )
        # ponytail: 蓝图"同时抽取偏好写 PG"未给抽取规格，偏好走手动 PUT + query_memory 检索
        return {"memory_context": f"wrote {written} triples"}
    except Exception:
        return {}


async def memory_query(state: AgentState) -> dict:
    """05 定义：问题→偏好+图谱→组装 memory_context 注入 finalize。失败降级。"""
    last = state["messages"][-1]["content"]
    user_id = state["user_id"]
    try:
        neo4j = await get_neo4j()
        async with async_session() as s:
            # 节点内独立会话：显式设 RLS 上下文（03），否则偏好查询 fail-closed
            await set_tenant_context(s, user_id)
            resp = await MemoryService(s, neo4j).query_memory(user_id, last)
            return {"memory_context": resp.answer}
    except Exception:
        return {"memory_context": ""}


async def rag_retrieve(state: AgentState) -> dict:
    """06 定义：按用户问题 build_context，注入 rag_context 供 finalize。失败降级。"""
    try:
        user_id = state["user_id"]
        last = state["messages"][-1]["content"]
        async with async_session() as s:
            await set_tenant_context(s, user_id)

            async def vector_fn(query, uid, limit):
                vec = await EmbeddingService().embed(query)
                return await chunk_repo.vector_search(s, uid, vec, limit)

            ctx = await build_context(user_id, last, vector_fn=vector_fn)
            return {"rag_context": ctx}
    except Exception:
        return {"rag_context": ""}


async def skill_entry(state: AgentState) -> dict:
    """10 定义。占位：未开放。"""
    return {"reply": "Skill 功能未开放（模块 10 施工后可用）"}


def agent_selector(state: AgentState) -> dict:
    """04 节点：路由决策点，本身无状态更新。"""
    return {}


def select_agent(state: AgentState) -> str:
    """条件路由：按意图名 + 关键词规则选子图（蓝图 04 agent_selector 表格）。"""
    intent_name = (state.get("intent") or {}).get("intent_name", "default_chat")
    if intent_name in ("create_schedule", "query_schedule", "create_todo", "query_todo", "web_search"):
        return "tool"
    content = state["messages"][-1]["content"] if state.get("messages") else ""
    if any(k in content for k in ("规划", "研究", "分析", "整理", "计划", "安排", "多步", "依次")):
        return "plan"
    if any(k in content for k in ("写", "报告", "邮件", "总结", "文章", "文案")):
        return "reflection"
    return "chat"


async def finalize(state: AgentState) -> dict:
    """组装 memory/rag 上下文 + LLM 生成回复；已有 reply（工具/子图产出）则透传。"""
    if state.get("reply"):
        return {"reply": state["reply"]}
    last = state["messages"][-1]["content"]
    ctx = []
    if state.get("memory_context"):
        ctx.append(f"记忆：{state['memory_context']}")
    if state.get("rag_context"):
        ctx.append(f"参考文档：{state['rag_context']}")
    prompt = "你是 AI 私人助理。\n" + "\n".join(ctx) + f"\n用户：{last}"
    reply = await INTENT_LLM.ainvoke(prompt)
    return {"reply": reply.content}


def build_main_graph(registry: ToolRegistry):
    from app.agent.loops.plan_execute import build_plan_subgraph
    from app.agent.loops.react import build_react_subgraph
    from app.agent.loops.reflection import build_reflection_subgraph

    g = StateGraph(AgentState)
    g.add_node("intent_route", intent_route)
    g.add_node("tool_executor", lambda s: tool_executor(s, registry))
    g.add_node("memory_write", memory_write)
    g.add_node("memory_query", memory_query)
    g.add_node("rag_retrieve", rag_retrieve)
    g.add_node("skill_entry", skill_entry)
    g.add_node("agent_selector", agent_selector)
    g.add_node("react_loop", build_react_subgraph(registry))
    g.add_node("plan_loop", build_plan_subgraph(registry))
    g.add_node("reflection_loop", build_reflection_subgraph(INTENT_LLM))
    g.add_node("finalize", finalize)

    g.add_edge(START, "intent_route")
    # ponytail: 蓝图 04 图代码写 chat→finalize；为让规划/写作子图可达（agent_selector 表格），
    # chat 也经 agent_selector 决策（纯闲聊才落 finalize）。
    g.add_conditional_edges(
        "intent_route", route_by_intent,
        {
            "tool": "agent_selector", "memory": "memory_query",
            "memory_write": "memory_write", "rag": "rag_retrieve",
            "skill": "skill_entry", "chat": "agent_selector",
        },
    )
    g.add_conditional_edges(
        "agent_selector", select_agent,
        {
            "tool": "tool_executor", "react": "react_loop",
            "plan": "plan_loop", "reflection": "reflection_loop",
            "chat": "finalize",
        },
    )
    g.add_edge("tool_executor", "memory_write")
    g.add_edge("skill_entry", "memory_write")
    g.add_edge("react_loop", "memory_write")
    g.add_edge("plan_loop", "memory_write")
    g.add_edge("reflection_loop", "memory_write")
    g.add_edge("memory_write", "finalize")
    g.add_edge("memory_query", "finalize")
    g.add_edge("rag_retrieve", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=_get_checkpointer())

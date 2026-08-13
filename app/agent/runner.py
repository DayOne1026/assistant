"""04 对话：AgentRunner（蓝图 04 runner.py）。全局单例。"""

import uuid
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools import ToolRegistry, get_registry
from app.redis_client import redis_key
from app.repos.conversations import message_repo
from app.schemas.chat import ChatResponse, IntentResult

CONFIRM_WORDS = ("确认", "可以", "好的", "执行", "同意")
DENY_WORDS = ("取消", "不要", "算了", "拒绝", "不行")


def classify_confirm_input(content: str) -> str | None:
    """判定确认/取消；否则 None（蓝图 04 补充说明）。"""
    for w in DENY_WORDS:
        if w in content:
            return "deny"
    for w in CONFIRM_WORDS:
        if w in content:
            return "confirm"
    return None


def format_pending_result(result) -> str:
    if result.status == "done":
        return "已完成。"
    if result.status == "denied":
        return result.message or "已取消。"
    return result.message or "该操作需你确认"


class AgentRunner:
    """对话入口：跑图 + 持久化消息。全局单例（get_runner）。"""

    def __init__(self, graph, registry: ToolRegistry):
        self._graph = graph
        self._registry = registry

    def _thread(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> dict:
        """Redis checkpointer thread：redis_key 会话隔离（03）。"""
        return {
            "configurable": {"thread_id": redis_key("session", user_id, str(conversation_id))}
        }

    async def run(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
        image_id: uuid.UUID | None = None,
    ) -> ChatResponse:
        """调图 → 持久化 user/assistant 消息 → 返回 ChatResponse。
        image_id：图片理解（VLM 描述注入）归 06，先忽略。
        """
        # 0. 本轮是"确认/取消"？直接处理挂起动作，不走意图路由
        action = classify_confirm_input(content)
        if action is not None:
            result = (
                await self._registry.confirm_latest(user_id, conversation_id)
                if action == "confirm"
                else await self._registry.deny_latest(user_id, conversation_id)
            )
            reply = format_pending_result(result)
            await message_repo.create(db, conversation_id, user_id, "user", content)
            await message_repo.create(db, conversation_id, user_id, "assistant", reply)
            await db.commit()
            return ChatResponse(
                reply=reply,
                intent=IntentResult(intent_name="confirm", parameters={}, confidence=1.0),
            )
        # 1. 持久化用户消息
        await message_repo.create(db, conversation_id, user_id, "user", content)
        # 2. 跑图
        inputs = {
            "messages": [{"role": "user", "content": content}],
            "user_id": user_id,
            "conversation_id": conversation_id,
        }
        result = await self._graph.ainvoke(inputs, config=self._thread(user_id, conversation_id))
        reply = result.get("reply") or "抱歉，我没有理解你的意思。"
        # 3. 持久化 assistant 回复
        await message_repo.create(db, conversation_id, user_id, "assistant", reply)
        await db.commit()
        intent_data = result.get("intent") or {
            "intent_name": "default_chat", "parameters": {}, "confidence": 0.0
        }
        tool_calls = [
            r.get("name") for r in result.get("tool_results", []) if isinstance(r, dict) and r.get("name")
        ]
        return ChatResponse(reply=reply, intent=IntentResult(**intent_data), tool_calls=tool_calls)

    async def get_history(
        self, db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> list:
        """从 messages 表读持久历史（业务数据，非 checkpointer）。"""
        rows, _ = await message_repo.list_by_conversation(db, user_id, conversation_id, 0, 100)
        return rows

    async def stream(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
        image_id: uuid.UUID | None = None,
    ) -> AsyncIterator[str]:
        """同 run，但走 astream，SSE chunk 流式返回（打字机效果见 12 优化）。"""
        inputs = {
            "messages": [{"role": "user", "content": content}],
            "user_id": user_id,
            "conversation_id": conversation_id,
        }
        async for chunk in self._graph.astream(
            inputs, config=self._thread(user_id, conversation_id), stream_mode="updates"
        ):
            yield f"data: {chunk}\n\n"


_runner: AgentRunner | None = None


def get_runner() -> AgentRunner:
    """全局单例：首次调用构建主图（含 RedisSaver checkpointer）。"""
    global _runner
    if _runner is None:
        from app.agent.graph import build_main_graph
        from app.core.config import get_settings
        from app.redis_client import RedisClient

        registry = get_registry(RedisClient(get_settings().redis_url))
        _runner = AgentRunner(build_main_graph(registry), registry)
    return _runner

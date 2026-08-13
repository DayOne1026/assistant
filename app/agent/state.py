"""04 对话：AgentState（蓝图 04）。

messages 用 operator.add 合并（每次追加本轮消息）。
intent 存 dict（蓝图标注 IntentResult；checkpointer 序列化兼容用 dict，API 层转回模型）。
"""

import uuid
from operator import add
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict, total=False):
    messages: Annotated[list[dict], add]  # 本次 turn 消息流
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    intent: dict | None  # IntentResult.model_dump()
    tool_results: list[dict]
    memory_context: str
    rag_context: str
    reply: str

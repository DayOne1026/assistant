from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from app.core.config import get_settings


@lru_cache
def get_chat_model() -> BaseChatModel:
    """按 settings.llm_provider 返回单例模型：
    deepseek → ChatOpenAI 指向 DeepSeek API（兼容端点）
    qwen     → langchain_community.chat_models.ChatTongyi（DashScope）
    结构化输出：两家 with_structured_output 走 function calling / JSON mode 降级，
    无 OpenAI 级约束解码，必须服务端 Pydantic 校验 + 重试兜底（见 04/05）。
    """
    settings = get_settings()
    if settings.llm_provider == "qwen":
        from langchain_community.chat_models import ChatTongyi

        return ChatTongyi(model=settings.llm_model, dashscope_api_key=settings.llm_api_key)

    # ponytail: 锁定的 langchain-community 0.2.19 无原生 ChatDeepSeek，走 OpenAI 兼容端点；
    # 升级 langchain-community>=0.3 后换回 ChatDeepSeek(model=..., api_key=..., base_url=...)
    from langchain_community.chat_models import ChatOpenAI

    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )


def get_embedding_model():
    """Embedding 单例（06 rag/embedding.EmbeddingService）。"""
    raise NotImplementedError("06 RAG 模块实现")


def _strip_json_fence(text: str) -> str:
    """去掉模型 JSON 输出周围的 markdown 围栏（```json ... ```）。"""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


async def ainvoke_json(llm, prompt):
    """直接调 LLM 输出 JSON 文本 → 解析为 python 对象。

    绕开 with_structured_output：langchain-community 0.2.19 的 ChatOpenAI
    bind_tools 未实现（NotImplementedError），结构化输出全挂；
    改走模型原生 JSON 输出 + 手工解析，调用方再 model_validate 到各自 schema。
    失败抛 json 解析异常，由调用方降级兜底。
    """
    import json

    raw = (await llm.ainvoke(prompt)).content
    return json.loads(_strip_json_fence(raw))

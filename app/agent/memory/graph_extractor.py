"""05 记忆与知识图谱：三元组提取（蓝图 05 GraphExtractor）。

LLM 结构化输出，失败降级空列表（不阻断对话）。
三层兜底同 04（intent.py）：with_structured_output → Pydantic 校验（模型自带）→ 异常兜底。
"""

from langchain_core.language_models import BaseChatModel

from app.core.llm import ainvoke_json, get_chat_model
from app.schemas.memory import ExtractedTriple

EXTRACTOR_LLM: BaseChatModel = get_chat_model()

_PROMPT = (
    "从文本提取事实三元组(主-谓-宾)，只输出 JSON。"
    "类型限 Person/Place/Organization/Topic/Event/Document。忽略虚指与否定歧义。\n"
    "第一人称（我/我们）作主语时也提取，主语统一记作\"我\"，类型 Person。\n"
    "文本：{text}"
)


async def extract_triples(text: str) -> list[ExtractedTriple]:
    """LLM JSON 输出三元组；失败返回空列表（不阻断对话）。"""
    if not text or not text.strip():
        return []
    try:
        data = await ainvoke_json(EXTRACTOR_LLM, _PROMPT.format(text=text))
        if isinstance(data, dict):  # 模型输出 {"triples": [...]} 包装
            data = data.get("triples", [])
        return [ExtractedTriple.model_validate(t) for t in data]
    except Exception:
        return []

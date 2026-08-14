"""06 RAG：查询预处理（蓝图 06 query 段，复用 zhao/rag/query.py，LLM 换 get_chat_model）。

rewrite 改写扩写 / hyde 假设答案 / step_back 后退提问。全部 async（langchain）。
"""

from typing import Any

from app.core.llm import get_chat_model

QUERY_LLM = get_chat_model()

_REWRITE_PROMPT = """你是查询改写助手。把用户问题改写成更精确、完整的检索查询。

规则:
- 补充同义词和相关关键词（中英文都加）
- 保留原始语义，不要添加用户没问的信息
- 去除口语化表达，用书面语
- 只输出改写后的查询，不加任何解释"""

_HYDE_PROMPT = """假设你是一本百科全书。根据用户问题，写一段100-200字的假设回答。

规则:
- 不需要准确，要的是语言风格和用词接近真实文档
- 使用专业术语，信息密度高
- 只输出假设回答，不加"根据我的知识"之类的前缀"""

_STEPBACK_PROMPT = """你是一个逆向思考助手。用户问了一个具体问题，请退一步思考：

这个具体问题涉及哪些基础概念或原理？生成一个更通用、更基础的背景问题。

规则:
- 不要直接回答用户问题
- 后退到原理/概念层面，而不是细节
- 背景问题应该比原始问题覆盖面更广
- 只输出后退后的问题，一行"""


async def rewrite(query: str, llm: Any | None = None) -> str:
    llm = llm or QUERY_LLM
    resp = await llm.ainvoke(_REWRITE_PROMPT + f"\n\n问题: {query}")
    return (resp.content or query).strip()


async def hyde(query: str, llm: Any | None = None) -> str:
    llm = llm or QUERY_LLM
    resp = await llm.ainvoke(_HYDE_PROMPT + f"\n\n问题: {query}")
    return (resp.content or query).strip()


async def step_back(query: str, llm: Any | None = None) -> str:
    llm = llm or QUERY_LLM
    resp = await llm.ainvoke(_STEPBACK_PROMPT + f"\n\n问题: {query}")
    return (resp.content or query).strip()


async def preprocess(query: str, llm: Any | None = None,
                     strategies: list[str] | None = None) -> list[str]:
    """批量执行多种策略，返回变体查询（默认 ['rewrite']）。"""
    strategies = strategies or ["rewrite"]
    fns = {"rewrite": rewrite, "hyde": hyde, "step_back": step_back}
    return [await fns[s](query, llm) for s in strategies if s in fns]

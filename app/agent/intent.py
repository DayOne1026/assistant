"""04 意图识别：INTENTS 表 + 结构化输出三层兜底（蓝图 04 intent 段）。

流程：① with_structured_output(IntentResult) 输出松散 parameters
     ② validate_intent_params 按意图参数 schema 二次校验（schema 未注册的意图宽松放行）
     ③ 失败重试 → default_chat 兜底。
"""

from app.core.llm import ainvoke_json, get_chat_model
from app.schemas.chat import IntentResult
from app.schemas.schedule import ScheduleCreate
from app.schemas.skill import SkillRunRequest
from app.schemas.todo import TodoCreate
from app.agent.state import AgentState

# intent_name → (触发示例, 路由到)
INTENTS: dict[str, str] = {
    "create_schedule": "明早9点开会",
    "query_schedule": "我这周有什么日程",
    "create_todo": "记一下买牛奶",
    "query_todo": "我有哪些任务",
    "remember_fact": "记住我喜欢拿铁",
    "query_memory": "我上次说喜欢喝什么",
    "search_docs": "查我笔记里关于XX",
    "trigger_skill": "帮我做健身打卡",
    "web_search": "查一下今天北京的天气",
    "default_chat": "闲聊",
}

# 路由分支键（route_by_intent 返回，对应主图 conditional_edges 映射）
INTENT_BRANCH: dict[str, str] = {
    "create_schedule": "tool",
    "query_schedule": "tool",
    "create_todo": "tool",
    "query_todo": "tool",
    "web_search": "tool",
    "remember_fact": "memory_write",
    "query_memory": "memory",
    "search_docs": "rag",
    "trigger_skill": "skill",
}

# 意图参数 schema（路由后二次校验）。来源：07 ScheduleCreate/TodoCreate、10 SkillRunRequest。
# 07：create_schedule/create_todo 有必填参数，校验失败清空降级；query_* 无必填，宽松放行。
# 10：trigger_skill 的 params 有默认空 dict，宽松。
INTENT_PARAM_SCHEMAS: dict[str, type] = {
    "create_schedule": ScheduleCreate,
    "create_todo": TodoCreate,
    "trigger_skill": SkillRunRequest,
}

INTENT_LLM = get_chat_model()  # ChatDeepSeek/千问（按配置）


def validate_intent_params(result: IntentResult) -> IntentResult:
    """② 按 intent_name 取参数模型 model_validate；失败清空参数并降级。"""
    schema = INTENT_PARAM_SCHEMAS.get(result.intent_name)
    if schema is None:
        return result  # 该意图参数 schema 未注册，宽松放行
    try:
        schema.model_validate(result.parameters)
        return result
    except Exception:
        return IntentResult(intent_name=result.intent_name, parameters={}, confidence=0.0)


async def intent_route(state: AgentState) -> dict:
    """LLM 结构化输出 → IntentResult；default_chat 兜底（三层兜底：with_structured_output + Pydantic 二次校验 + 异常兜底）。"""
    last = state["messages"][-1]["content"]
    prompt = f"""识别用户意图与实体，只输出 JSON。
可选意图：{list(INTENTS.keys())}
输出格式：{{"intent_name": "其中一个意图名", "parameters": {{"实体键": "值"}}, "confidence": 0.0~1.0}}
用户：{last}"""
    try:
        result = validate_intent_params(IntentResult.model_validate(await ainvoke_json(INTENT_LLM, prompt)))
    except Exception:
        result = IntentResult(intent_name="default_chat", parameters={}, confidence=0.0)
    return {"intent": result.model_dump()}  # checkpointer 序列化兼容，存 dict


def route_by_intent(state: AgentState) -> str:
    """根据 intent_name 返回分支键（tool/memory/memory_write/rag/skill/chat）。"""
    intent_name = (state.get("intent") or {}).get("intent_name", "default_chat")
    return INTENT_BRANCH.get(intent_name, "chat")

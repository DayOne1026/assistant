# 10 Skill 机制、自动化规则引擎、自定义 System Prompt

## Skill 机制

对话中显式触发的多步技能，LangGraph 子图动态构建。

### 数据模型（PG）

#### skills
| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK users.id CASCADE, index | |
| name | VARCHAR(100) | UNIQUE(user_id, name) | 触发名 |
| description | VARCHAR(500) | NOT NULL | 触发描述 |
| steps | JSONB | NOT NULL | SkillStep[] |
| enabled | BOOL | default true | |
| created_at / updated_at | TIMESTAMPTZ | TimestampMixin | |

### Pydantic Schema

```python
class SkillStep(BaseModel):
    tool: str                    # 工具名（11 注册表）或 "llm"
    params: dict[str, Any] = {}  # 固定参数或 {name: "{{param}}"} 模板
    prompt: str | None = None    # tool=llm 时的指令

class SkillCreate(BaseModel):
    name: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    description: str
    steps: list[SkillStep] = Field(min_length=1, max_length=20)

class SkillResponse(BaseModel):
    id: UUID
    name: str
    description: str
    steps: list[SkillStep]
    enabled: bool
    created_at: datetime

class SkillRunRequest(BaseModel):
    params: dict[str, Any] = {}
```

### SkillRunner（agent/skill_graph.py）

```python
class SkillRunner:
    """按 steps 动态构建 LangGraph 子图并执行。"""
    def __init__(self, registry: ToolRegistry, llm=get_chat_model()):
        self._registry = registry; self._llm = llm   # llm 供 step.tool=="llm" 分支

    async def run(self, user_id: UUID, conversation_id: UUID | None,
                  skill: Skill, params: dict) -> dict:
        """构建子图：step_i 节点按序执行工具或 LLM，返回最终结果。
        conversation_id 供工具确认（11）挂会话队列。"""
```

`run` 伪代码：
```
g = StateGraph(SkillState)     # SkillState: {user_id, conversation_id, step_results, params}
for i, step in enumerate(skill.steps):
    g.add_node(f"step_{i}", make_step_executor(step))   # 校验权限→执行→记录
    if i > 0: g.add_edge(f"step_{i-1}", f"step_{i}")
g.add_edge(f"step_{len(skill.steps)-1}", END)
graph = g.compile()
return await graph.ainvoke({"user_id": user_id, "conversation_id": conversation_id,
                            "params": params, "step_results": []})
```

`make_step_executor` 伪代码：
```
async def executor(state):
    resolved = {k: (fmt(v, state["params"]) if isinstance(v,str) else v)
                for k,v in step.params.items()}
    if step.tool == "llm":
        result = await self._llm.ainvoke(step.prompt.format(**state["params"]))
    else:
        result = await self._registry.call(user_id, state["conversation_id"],
                                           step.tool, resolved)   # 11：权限+审计+会话确认
    return {"step_results": [*state["step_results"], {"step": step.tool, "result": result}]}
```

`fmt(template, params)`：替换模板中 `{{key}}` 占位符为 params[key]；无占位符则原样返回。

### Service（services/skill_service.py）

| 函数 | 职责 |
|---|---|
| `create_skill / list_skills / get_skill / delete_skill` | CRUD（校验 steps 工具名存在） |
| `run_skill(user_id, skill_id, params) -> dict` | 调 SkillRunner |
| `find_skill_by_intent(user_id, description) -> Skill | None` | 意图命中匹配 |

### Agent 集成（04）

```python
async def skill_entry(state: AgentState) -> dict:
    """intent=trigger_skill：按参数/描述匹配技能，跑子图，结果注入 reply。"""
```

## 自动化规则引擎

时间/事件触发，后台自动执行（Celery）。

### 数据模型（PG）

#### automation_rules
| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK users.id CASCADE, index | |
| name | VARCHAR(200) | NOT NULL | |
| trigger_type | VARCHAR(20) | NOT NULL | time / event |
| trigger_config | JSONB | NOT NULL | 见下 |
| action_type | VARCHAR(20) | NOT NULL | notify / tool |
| action_config | JSONB | NOT NULL | 见下 |
| enabled | BOOL | default true | |
| last_run_at | TIMESTAMPTZ | NULL | 幂等/去重 |
| created_at / updated_at | TIMESTAMPTZ | TimestampMixin | |

trigger_config 示例：
```json
// time: 每天
{"cron": "0 9 * * *"}
// event: 日程创建后
{"event": "schedule.created", "delay_seconds": 0}
```
action_config 示例：
```json
{"notify": {"title": "早安", "body": "今天有 {n} 个日程", "channel": "ws"}}
{"tool": {"name": "create_todo", "params": {"title": "..."}}}
```

内置规则（预置示例，用户可启用）：
```json
{"name": "每日简报", "trigger_type": "time", "trigger_config": {"cron": "0 8 * * *"},
 "action_type": "notify",
 "action_config": {"title": "今日简报", "body": "今日 {n} 个日程，{m} 个待办，天气 {w}", "channel": "ws"}}
```
（主动能力：早晨自动推送日程/待办/天气汇总。）

### Service（services/automation_service.py）

| 函数 | 职责 |
|---|---|
| `create_rule / list_rules / get_rule / update_rule / delete_rule` | CRUD |
| `evaluate_event(user_id, event: str, payload: dict)` | 事件触发检查（业务代码调用点） |
| `run_rule(user_id, rule_id, payload)` | 执行 action |

### Celery（tasks/automation_tasks.py）

```python
@app.task
def scan_automation_rules(limit: int = 200) -> int:
    """Beat 周期（每分钟）：扫 time 规则 cron 命中→run_rule.delay。"""

@app.task(bind=True, max_retries=2)
def run_rule(self, user_id, rule_id, payload=None):
    """执行 action：notify→08 send_immediate；tool→registry.call（11）。"""
```

事件触发集成点：07 建日程后 `evaluate_event(user_id, "schedule.created", {...})`。

## 自定义 System Prompt

### 数据模型（PG）

#### system_prompt_profiles
| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK users.id CASCADE, index | |
| name | VARCHAR(100) | NOT NULL | 如"管家模式" |
| prompt | TEXT | NOT NULL | 用户写的语气/人设 |
| enabled | BOOL | default false | 同一用户至多一个启用 |
| created_at / updated_at | TIMESTAMPTZ | TimestampMixin | |

### PromptAssembler（services/prompt_assembler.py）

```python
USER_CONTENT_SEP = "\n<user_memory_scope>\n"

def build_system_prompt(user: User, enabled_profile: PromptProfile | None,
                        user_profile: Profile | None = None,
                        dynamic: dict | None = None) -> str:
    """拼接顺序：安全层 → 用户信息+画像 → 用户自定义层 → 动态上下文。安全层不可覆盖。"""
```

`build_system_prompt` 伪代码：
```
parts = [
  SAFETY_LAYER,                 # 固定安全指令（角色边界、禁泄露、工具权限），硬编码，不可被用户改写
  "当前用户：{username}，时区：{timezone}",
]
if user_profile:
    parts.append(f"{USER_CONTENT_SEP}用户画像：{user_profile.summary}")   # 人物快照，会话开头注入
if enabled_profile:
    parts.append(USER_CONTENT_SEP + enabled_profile.prompt)   # 只追加，不上移
if dynamic:                                                   # 记忆/RAG 注入
    parts.append(USER_CONTENT_SEP + "动态上下文：" + json.dumps(dynamic))
return "\n\n".join(parts)
```

防注入要点：
- 用户 prompt 只能出现在安全层之后（追加），不能覆盖安全指令
- 用户消息与 system prompt 之间用 `USER_CONTENT_SEP` 分隔
- 用户 prompt 内容一律视为不可信数据，不做指令合并

### Service + API（api/prompts.py）

| 函数/接口 | 职责 |
|---|---|
| `create_profile / list_profiles / delete_profile` | CRUD |
| `enable_profile(user_id, id)` | 启用（先禁用其余） |
| POST /prompts, GET /prompts, DELETE /prompts/{id}, POST /prompts/{id}/enable | |

## 测试要点

- Skill：steps 顺序执行；参数模板渲染；工具权限/审计生效；非法工具名拒绝
- 规则：cron 命中判断；事件触发去重（同 payload 短时间不重复）；action 幂等
- Prompt：安全层永在首位；启用切换互斥；注入文本不改变安全层

## 模块边界

- Skill 与自动化规则：Skill=对话显式触发、多步推理；规则=时间/事件自动触发、固定动作
- 工具执行与审计：11
- 通知发送：08

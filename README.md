# Assistant — 多用户 AI 私人助理平台

一个多租户的 AI 私人助理平台，具备 Agent 引擎、RAG 文档检索、记忆与知识图谱、自动化与定时任务等能力。后端 FastAPI，前端 Vue 3。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python · FastAPI · SQLAlchemy · Alembic · Celery |
| 存储 | PostgreSQL（含向量检索） · Redis |
| Agent | LangGraph（ReAct / Plan-Execute / Reflection 三种循环） |
| 前端 | Vue 3 · TypeScript · Vite · Pinia · WebSocket |
| 部署 | Docker · Docker Compose |

## 核心功能

- **Agent 引擎**：意图识别、工具调用、多循环策略（ReAct / Plan-Execute / Reflection）
- **RAG 文档检索**：文档切分、重排序、向量检索
- **记忆与知识图谱**：会话记忆 + 实体关系知识图谱
- **多租户**：基于 PostgreSQL RLS 的行级数据隔离
- **自动化与定时任务**：规则触发、Cron 调度、通知推送
- **技能系统**：可扩展技能注册与执行
- **其他**：待办、审计日志、图片管理、MCP/Webhook 集成、图像理解

## 快速开始

```bash
# 1. 复制环境变量
cp .env.example .env

# 2. 启动基础设施（PostgreSQL + Redis）
docker compose up -d

# 3. 初始化数据库
alembic upgrade head

# 4. 启动后端
uvicorn app.main:app --reload --port 8000

# 5. 启动前端
cd frontend && npm install && npm run dev
```

后端 API 默认在 `http://localhost:8000`，前端开发服务器在 `http://localhost:3000`。

## 目录结构

```
app/
├── agent/        # Agent 引擎（意图/主图/子循环/工具/记忆提取）
├── api/          # REST API 路由
├── core/         # 配置、LLM 客户端、安全、日志
├── db/           # 数据模型、Alembic 迁移、租户策略
├── rag/          # 文档切分、向量检索、重排序、图像服务
├── services/     # 业务逻辑层
├── tasks/        # Celery 异步任务
├── integrations/ # MCP / OAuth / 加密等集成
└── middleware/   # 限流、幂等、内容安全
frontend/
├── src/
│   ├── views/    # 页面（聊天、记忆、图片、日程、待办、设置）
│   ├── components/
│   ├── api/      # 接口封装
│   └── stores/   # Pinia 状态
```

## 测试

```bash
pytest
```

## 版本

- v0.1 — 初始版本

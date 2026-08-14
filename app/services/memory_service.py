"""05 记忆与知识图谱：MemoryService / ProfileService（蓝图 05 services 段）。

偏好 + 图谱 + 画像。偏好走 PG（RLS 兜底），图谱走 Neo4j（user_id 强制过滤），
画像缓存走 Redis（redis_key 规范）。LLM 失败一律优雅降级，不抛业务异常。
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.memory.graph_extractor import extract_triples
from app.agent.memory.graph_writer import GraphWriter
from app.core.llm import ainvoke_json, get_chat_model
from app.neo4j_client import Neo4jClient
from app.redis_client import RedisClient, redis_key
from app.repos.memory import preference_repo, profile_repo
from app.schemas.memory import MemoryResponse, Profile, ProfileStruct

PROFILE_CACHE_TTL = 3600


class MemoryService:
    """偏好检索 + 图谱多跳 → LLM 组装记忆回答。"""

    def __init__(
        self,
        db: AsyncSession,
        neo4j: Neo4jClient,
        llm: Any | None = None,
    ):
        self._db = db
        self._neo4j = neo4j
        self._llm = llm or get_chat_model()
        self._writer = GraphWriter(neo4j)

    # --- 写入 ---

    async def remember(
        self,
        user_id: uuid.UUID,
        key: str,
        value: Any,
        source: str = "chat",
        conversation_id: uuid.UUID | None = None,
    ) -> None:
        """upsert user_preferences。conversation_id 记录来源会话（溯源）。"""
        await preference_repo.upsert(
            self._db, user_id, key, value, source, conversation_id
        )
        await self._db.commit()

    async def get_memory(self, user_id: uuid.UUID, key: str) -> Any | None:
        pref = await preference_repo.get_by_key(self._db, user_id, key)
        return pref.value if pref else None

    async def write_triples(
        self,
        user_id: uuid.UUID,
        text: str,
        conversation_id: uuid.UUID | None = None,
    ) -> int:
        """提取三元组写图谱。失败静默返回 0（不阻断对话）。"""
        try:
            triples = await extract_triples(text)
            return await self._writer.write_triples(user_id, triples, conversation_id)
        except Exception:
            return 0

    # --- 查询 ---

    async def query_memory(self, user_id: uuid.UUID, question: str) -> MemoryResponse:
        """偏好匹配 + 图多跳 → LLM 组装回答；无记忆时优雅降级。"""
        prefs = await preference_repo.search(self._db, user_id, question)
        paths = []
        for e in await self._match_entity_names(user_id, question):
            paths += await self.get_related_entities(user_id, e)
        if not prefs and not paths:
            return MemoryResponse(
                answer=f"关于『{question}』，我还没有相关记忆。", sources=[]
            )
        ctx = {
            "preferences": [{"key": p.key, "value": p.value} for p in prefs],
            "graph_paths": [
                " → ".join(p["names"]) + f" (conf={p['confidences']})" for p in paths
            ],
        }
        answer = await self._llm.ainvoke(f"基于记忆回答：{question}\n记忆：{ctx}")
        sources = [f"preference:{p.key}" for p in prefs]
        sources += [f"graph:{' → '.join(p['names'])}" for p in paths]
        return MemoryResponse(answer=answer.content, sources=sources)

    async def get_related_entities(
        self, user_id: uuid.UUID, entity_name: str, max_depth: int = 2
    ) -> list[dict]:
        """多跳查询。Cypher 带 user_id 强制过滤（03），禁止裸 MATCH。"""
        records = await self._neo4j.run(
            """
            MATCH (start {{name: $entity, user_id: $user_id}})
            MATCH path = (start)-[:RELATED_TO*1..{depth}]-(related)
            WHERE related.user_id = $user_id
            RETURN [n IN nodes(path) | n.name] AS names,
                   [r IN relationships(path) | r.predicate] AS predicates,
                   [r IN relationships(path) | r.confidence] AS confidences
            LIMIT 50
            """.format(depth=int(max_depth)),
            {"entity": entity_name, "user_id": str(user_id)},
        )
        return [r.data() for r in records]

    async def _match_entity_names(
        self, user_id: uuid.UUID, question: str
    ) -> list[str]:
        """问题中出现的既有图谱实体名（零额外 LLM，比 LLM 提取更准）。"""
        records = await self._neo4j.run(
            "MATCH (n {user_id: $user_id}) RETURN n.name AS name",
            {"user_id": str(user_id)},
        )
        return [r["name"] for r in records if r["name"] and r["name"] in question]


class ProfileService:
    """用户画像快照：事实层之上的聚合，Redis 缓存 + PG 落盘。"""

    def __init__(
        self,
        db: AsyncSession,
        redis: RedisClient,
        neo4j: Neo4jClient,
        llm: Any | None = None,
    ):
        self._db = db
        self._redis = redis
        self._neo4j = neo4j
        self._llm = llm or get_chat_model()

    def _cache_key(self, user_id: uuid.UUID) -> str:
        return redis_key("profile", user_id)

    async def get_profile(self, user_id: uuid.UUID) -> Profile | None:
        """读 Redis 缓存 app:profile:{user_id}，未命中读 PG 并回填。"""
        raw = await self._redis.get(self._cache_key(user_id))
        if raw:
            return Profile.model_validate_json(raw)
        row = await profile_repo.get(self._db, user_id)
        if row is None:
            return None
        obj = Profile(
            summary=row.summary or "",
            structured=row.structured,
            facts_count=row.facts_count,
            updated_at=row.updated_at,
        )
        await self._redis.set(self._cache_key(user_id), obj.model_dump_json(), ex=PROFILE_CACHE_TTL)
        return obj

    async def mark_stale(self, user_id: uuid.UUID) -> None:
        """新事实写入后调用：失效缓存 + 脏计数 incr。"""
        await self._redis.delete(self._cache_key(user_id))
        await self._redis.incr(redis_key("profile_dirty", user_id))

    async def refresh_profile(self, user_id: uuid.UUID) -> Profile:
        """取近期事实 → LLM 合并生成 → upsert。无事实返回空画像不报错。"""
        facts = await self._collect_facts(user_id)
        if facts:
            try:
                out = ProfileStruct.model_validate(
                    await ainvoke_json(self._llm, f"根据以下用户记忆生成画像：\n" + "\n".join(facts))
                )
                summary, structured = out.summary, out.model_dump(exclude={"summary"})
            except Exception:
                summary, structured = "暂无足够记忆生成画像", None
        else:
            summary, structured = "暂无足够记忆生成画像", None
        await profile_repo.upsert(self._db, user_id, summary, structured, len(facts))
        await self._db.commit()
        # ponytail: commit 后 SET LOCAL 上下文失效，不再回查 RLS 表；
        # 直接用刚落盘的数据回填缓存并返回（避免 app/Celery 进程 RLS fail-closed）
        obj = Profile(summary=summary, structured=structured, facts_count=len(facts), updated_at=datetime.now(UTC))
        await self._redis.set(self._cache_key(user_id), obj.model_dump_json(), ex=PROFILE_CACHE_TTL)
        return obj

    async def invalidate_cache(self, user_id: uuid.UUID) -> None:
        await self._redis.delete(self._cache_key(user_id))

    async def _collect_facts(self, user_id: uuid.UUID) -> list[str]:
        """近 30 天偏好 + 图谱实体采样（蓝图 refresh_profile 伪代码）。"""
        prefs = await preference_repo.list(self._db, user_id)
        facts = [f"{p.key}: {p.value}" for p in prefs]
        records = await self._neo4j.run(
            """
            MATCH (n {user_id: $user_id})
            RETURN n.name AS name, n.confidence AS confidence
            LIMIT 30
            """,
            {"user_id": str(user_id)},
        )
        facts += [f"实体: {r['name']} (conf={r['confidence']})" for r in records]
        return facts

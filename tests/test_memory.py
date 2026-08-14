"""05 记忆与知识图谱测试（蓝图 05 测试要点）。

图谱写入/多跳/隔离用真 Neo4j（conftest neo4j_client 夹具，不可达 skip）；
LLM 相关（提取/画像/组装回答）用 monkeypatch mock，防 flaky。
偏好/画像落 PG（RLS 兜底），画像缓存走真 Redis。
"""

import uuid

from app.agent.memory.graph_extractor import extract_triples
from app.agent.memory.graph_writer import GraphWriter, stable_id
from app.core.config import get_settings
from app.db.tenant import set_tenant_context
from app.neo4j_client import neo4j_user_scope
from app.repos.memory import preference_repo
from app.schemas.memory import ExtractedTriple, TripleExtraction
from app.services.memory_service import MemoryService, ProfileService

P = get_settings().api_prefix


# --- 夹具辅助 ---


def _uid():
    return uuid.uuid4()


async def _scoped(db, uid):
    """RLS 上下文：直连 db 的业务查询必须设（03 fail-closed，未设查不到）。"""
    await set_tenant_context(db, uid)
    return uid


def _triple(subj, pred, obj, s_type="Person", o_type="Topic", conf=0.9):
    return ExtractedTriple(
        subject=subj, predicate=pred, object=obj,
        subject_type=s_type, object_type=o_type, confidence=conf,
    )


class _FakeExtractor:
    """with_structured_output → ainvoke 返回固定三元组。"""

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, prompt):
        return TripleExtraction(triples=[
            _triple("小明", "喜欢", "咖啡"),
            _triple("小明", "在", "上海", o_type="Place"),
        ])


class _FakeLLM:
    """MemoryService / ProfileService 注入。"""

    async def ainvoke(self, prompt):
        return type("R", (), {"content": "基于记忆的固定回答"})()

    def with_structured_output(self, schema):
        return self


class _FakeProfileOut:
    summary = "上海的一名工程师"

    def model_dump(self, **kw):
        return {"location": "上海", "profession": "工程师",
                "age_group": None, "interests": [], "traits": []}


class _FakeProfileLLM:
    """ProfileService 注入：with_structured_output → ainvoke 返回画像结构。"""

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, prompt):
        return _FakeProfileOut()


async def _cleanup_neo4j(neo4j_client, *uids):
    for uid in uids:
        await neo4j_client.execute_write(
            "MATCH (n {user_id: $uid}) DETACH DELETE n", {"uid": str(uid)}
        )


# --- 提取：结构与类型合法 ---


async def test_extract_triples_structure(monkeypatch):
    monkeypatch.setattr("app.agent.memory.graph_extractor.EXTRACTOR_LLM", _FakeExtractor())
    triples = await extract_triples("小明喜欢咖啡")
    assert len(triples) == 2
    assert triples[0].subject == "小明"
    assert triples[0].object_type in ("Person", "Place", "Organization", "Topic", "Event", "Document")
    assert 0 <= triples[0].confidence <= 1


async def test_extract_triples_empty_on_error(monkeypatch):
    class _Bad:
        def with_structured_output(self, schema):
            return self

        async def ainvoke(self, prompt):
            raise RuntimeError("llm down")

    monkeypatch.setattr("app.agent.memory.graph_extractor.EXTRACTOR_LLM", _Bad())
    assert await extract_triples("任何文本") == []
    assert await extract_triples("  ") == []  # 空文本直接短路


async def test_stable_id_deterministic():
    uid = _uid()
    assert stable_id(uid, "小明") == stable_id(uid, "小明")
    assert stable_id(uid, "小明") != stable_id(uid, "小刚")
    assert neo4j_user_scope(uid) == {"user_id": str(uid)}


# --- MERGE 幂等 + 复合唯一 + 隔离（真 Neo4j）---


async def test_write_merge_idempotent(neo4j_client):
    uid = _uid()
    writer = GraphWriter(neo4j_client)
    try:
        assert await writer.write_triples(uid, [_triple("小明", "喜欢", "咖啡")]) == 1
        assert await writer.write_triples(uid, [_triple("小明", "喜欢", "咖啡")]) == 1  # 写两次
        rows = await neo4j_client.run(
            "MATCH (n {user_id: $uid}) RETURN count(n) AS c", {"uid": str(uid)}
        )
        assert rows[0]["c"] == 2  # 小明 + 咖啡，无重复节点
    finally:
        await _cleanup_neo4j(neo4j_client, uid)


async def test_cross_user_same_name_not_conflict(neo4j_client):
    a, b = _uid(), _uid()
    writer = GraphWriter(neo4j_client)
    try:
        await writer.write_triples(a, [_triple("小明", "喜欢", "咖啡")])
        await writer.write_triples(b, [_triple("小明", "喜欢", "咖啡")])
        # 同用户内实体去重
        rows = await neo4j_client.run(
            "MATCH (n:Person {user_id: $uid}) RETURN count(n) AS c", {"uid": str(a)}
        )
        assert rows[0]["c"] == 1
        # 跨用户同名实体不冲突：id 不同（user_id 参与唯一）
        rows = await neo4j_client.run(
            "MATCH (n:Person {user_id: $a, name: '小明'}) "
            "MATCH (m:Person {user_id: $b, name: '小明'}) RETURN n.id AS id1, m.id AS id2",
            {"a": str(a), "b": str(b)},
        )
        assert rows[0]["id1"] != rows[0]["id2"]
    finally:
        await _cleanup_neo4j(neo4j_client, a, b)


async def test_isolation_verify_user_scope(neo4j_client):
    a, b = _uid(), _uid()
    writer = GraphWriter(neo4j_client)
    try:
        await writer.write_triples(a, [_triple("小明", "喜欢", "咖啡")])
        # B 的 user_id 查不到 A 的实体
        rows = await neo4j_client.run(
            "MATCH (n {name: '小明', user_id: $uid}) RETURN n", {"uid": str(b)}
        )
        assert len(rows) == 0
        # verify_user_scope：A 属主 True，B 越权 False
        sid = stable_id(a, "小明")
        assert await neo4j_client.verify_user_scope(a, sid, "Person") is True
        assert await neo4j_client.verify_user_scope(b, sid, "Person") is False
    finally:
        await _cleanup_neo4j(neo4j_client, a)


async def test_get_related_entities_multi_hop(neo4j_client):
    uid = _uid()
    writer = GraphWriter(neo4j_client)
    try:
        await writer.write_triples(uid, [_triple("小明", "喜欢", "咖啡"), _triple("小明", "在", "上海", o_type="Place")])
        svc = MemoryService(None, neo4j_client, llm=_FakeLLM())  # 只查图，不需 db
        paths = await svc.get_related_entities(uid, "小明", max_depth=1)
        names = [n for p in paths for n in p["names"]]
        assert "咖啡" in names and "上海" in names
    finally:
        await _cleanup_neo4j(neo4j_client, uid)


# --- query_memory 优雅降级 / 有记忆组装（llm mock）---


async def test_query_memory_no_memory_degrades(db, neo4j_client):
    uid = await _scoped(db, _uid())
    svc = MemoryService(db, neo4j_client, llm=_FakeLLM())
    resp = await svc.query_memory(uid, "你好呀")
    assert resp.sources == []
    assert "还没有相关记忆" in resp.answer


async def test_query_memory_with_preference_and_graph(db, neo4j_client, user):
    uid = await _scoped(db, user.id)
    try:
        await preference_repo.upsert(db, uid, "favorite_drink", "咖啡", "chat")
        await db.commit()
        await GraphWriter(neo4j_client).write_triples(uid, [_triple("小明", "喜欢", "咖啡")])
        svc = MemoryService(db, neo4j_client, llm=_FakeLLM())
        # question 同时含偏好 key 与图谱实体名：LIKE 命中 key + 实体名命中图
        resp = await svc.query_memory(uid, "小明 喜欢 favorite_drink 吗")
        assert resp.answer == "基于记忆的固定回答"
        assert any(s.startswith("preference:") for s in resp.sources)
        assert any(s.startswith("graph:") for s in resp.sources)
    finally:
        await _cleanup_neo4j(neo4j_client, uid)


# --- ProfileService：refresh / 缓存 / 无事实 / 隔离 ---


async def test_profile_refresh_and_cache(db, neo4j_client, monkeypatch, user):
    from app.redis_client import get_redis, redis_key

    redis = await get_redis()
    uid = await _scoped(db, user.id)
    await preference_repo.upsert(db, uid, "location", "上海")
    await db.commit()
    monkeypatch.setattr("app.services.memory_service.get_chat_model", lambda: _FakeProfileLLM())
    svc = ProfileService(db, redis, neo4j_client, llm=_FakeProfileLLM())
    profile = await svc.refresh_profile(uid)
    assert profile.summary == "上海的一名工程师"
    assert profile.facts_count >= 1
    # 缓存回填 → 命中
    cached = await svc.get_profile(uid)
    assert cached is not None and cached.summary == "上海的一名工程师"
    assert await redis.get(redis_key("profile", uid)) is not None
    # mark_stale：缓存失效
    await svc.mark_stale(uid)
    assert await redis.get(redis_key("profile", uid)) is None


async def test_profile_no_facts(db, neo4j_client, user):
    from app.redis_client import get_redis

    redis = await get_redis()
    uid = await _scoped(db, user.id)
    svc = ProfileService(db, redis, neo4j_client, llm=_FakeLLM())
    profile = await svc.refresh_profile(uid)  # 无事实不报错
    assert profile.summary == "暂无足够记忆生成画像"
    assert profile.facts_count == 0


async def test_profile_isolation(db, neo4j_client, user):
    from app.redis_client import get_redis

    redis = await get_redis()
    a = await _scoped(db, user.id)
    b = _uid()
    await preference_repo.upsert(db, a, "location", "上海")
    await db.commit()
    svc = ProfileService(db, redis, neo4j_client, llm=_FakeLLM())
    await svc.refresh_profile(a)
    assert await svc.get_profile(b) is None  # B 查不到 A 的画像


# --- API 层（偏好 CRUD / query 降级）---


async def _register_and_headers(client, email, username):
    await client.post(
        f"{P}/auth/register",
        json={"email": email, "username": username, "password": "pass1234", "timezone": "Asia/Shanghai"},
    )
    d = (await client.post(
        f"{P}/auth/login", json={"email": email, "password": "pass1234"}
    )).json()["data"]
    return {"Authorization": f"Bearer {d['access_token']}"}


async def test_api_preferences_flow(client):
    headers = await _register_and_headers(client, "mem@example.com", "memuser")
    r = await client.put(f"{P}/memory/preferences/favorite_drink", json={"value": "咖啡"}, headers=headers)
    assert r.status_code == 200
    r = await client.get(f"{P}/memory/preferences", headers=headers)
    items = r.json()["data"]
    assert any(i["key"] == "favorite_drink" and i["value"] == "咖啡" for i in items)


async def test_api_query_memory_degrades(client):
    headers = await _register_and_headers(client, "mem2@example.com", "memuser2")
    r = await client.post(f"{P}/memory/query", json={"question": "你好"}, headers=headers)
    assert r.status_code == 200
    assert "还没有相关记忆" in r.json()["data"]["answer"]

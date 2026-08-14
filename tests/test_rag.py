"""06 RAG 测试（蓝图 06 测试要点）。

纯逻辑（cleaner/chunker/BM25/RRF/精排降级）不依赖模型；
索引/检索/API 依赖真实 embedding（本地 BGE）与 CrossEncoder，装包后跑。
"""

import uuid

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models.documents import DocumentChunk
from app.db.tenant import set_tenant_context
from app.rag import chunker, cleaner
from app.rag.loader import load
from app.rag.reranker import coarse_rank, rerank
from app.rag.retrieval import BM25Retriever, search
from app.repos.documents import chunk_repo, document_repo
from app.services import document_service
from app.tasks.rag_tasks import index_document

P = get_settings().api_prefix


async def _scoped(db, uid):
    """RLS 上下文：直连 db 业务查询必须设（03 fail-closed）。"""
    await set_tenant_context(db, uid)
    return uid


async def _emb(text: str):
    from app.rag.embedding import EmbeddingService

    return await EmbeddingService().embed(text)


async def _chunk_count(db, doc_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == doc_id)
        )
    ).scalar_one()


# --- cleaner（蓝图新增）---


def test_clean_removes_noise():
    src = "﻿导航\n\n[链接](https://a.com)\nhttps://b.com\n\n正文内容  有空格\n\n\n\n结尾\n\nCopyright 2026"
    out = cleaner.clean(src)
    assert "https://" not in out
    assert "Copyright" not in out
    assert "正文内容 有空格" in out
    assert "\n\n\n" not in out


def test_dedupe_chunks():
    chunks = [
        {"text": "完全相同", "tokens": 1},
        {"text": "完全相同", "tokens": 1},
        {"text": "包含完全相同这个子串的更长的内容", "tokens": 5},
    ]
    assert len(cleaner.dedupe_chunks(chunks)) == 2


# --- chunker（含 seq_in_group / 文档内组号）---


def test_chunk_by_token_structure():
    chunks = chunker.chunk_by_token("这是第一段内容。" * 60, size=200)
    assert chunks
    assert all({"text", "tokens", "group_id", "seq_in_group"} <= set(c) for c in chunks)
    assert chunks[0]["group_id"] == "0"  # 文档内自增 0 起


def test_chunk_seq_in_group_increments():
    chunks = chunker.chunk_by_token("这是一个非常长的段落，包含很多句子。" * 200, size=100, overlap=0)
    gid = chunks[0]["group_id"]
    seqs = [c["seq_in_group"] for c in chunks if c["group_id"] == gid]
    assert len(seqs) >= 2
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def test_chunk_protect_code_block():
    text = "```python\ndef foo():\n    return 1\ndef bar():\n    return 2\n```\n\n后面正文"
    chunks = chunker.chunk_by_token(text, size=200)
    joined = "".join(c["text"] for c in chunks)
    assert "def foo" in joined and "def bar" in joined


def test_chunk_by_semantic():
    chunks = chunker.chunk_by_semantic("# 标题一\n内容一\n\n# 标题二\n内容二", size=200)
    joined = "".join(c["text"] for c in chunks)
    assert "标题一" in joined and "标题二" in joined


# --- loader（mock 外部依赖）---


def test_load_txt(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("你好", encoding="utf-8")
    assert load(str(p)) == "你好"


def test_load_url_mocked(monkeypatch):
    class _Resp:
        text = "网页 markdown"

        def raise_for_status(self):
            pass

    def _fake_get(url, timeout, headers):
        assert "r.jina.ai" in url
        return _Resp()

    monkeypatch.setattr("app.rag.loader.requests.get", _fake_get)
    assert load("https://example.com/x") == "网页 markdown"


# --- BM25 / RRF ---


def test_bm25_chinese():
    bm = BM25Retriever()
    bm.index(["我爱北京天安门", "今天天气很好", "咖啡提神"])
    hits = bm.search("北京", top_k=2)
    assert hits and hits[0][0] == 0  # 中文"字+二元组"命中


async def test_search_rrf_vector_and_bm25():
    async def vector_fn(q, uid, limit):
        return [(uuid.uuid4(), "语义相似的文档内容", 0.2)]

    bm = BM25Retriever()
    bm.index(["语义相似的文档内容", "无关内容"])
    results = await search("查询", uuid.uuid4(), top_k=5, vector_fn=vector_fn, bm25=bm)
    assert any("语义相似" in r["text"] for r in results)


# --- 排序：粗排缩减 + 精排失败降级 ---


def test_coarse_rank_reduces():
    class _FakeReranker:
        def score(self, query, docs, top_k=None):
            ranked = sorted(enumerate(docs), key=lambda x: len(x[1]), reverse=True)
            return ranked[:top_k] if top_k else ranked

    out = coarse_rank("q", ["短", "这是一个较长的文档"], _FakeReranker(), top_k=1)
    assert out == ["这是一个较长的文档"]


async def test_rerank_fallback_on_error():
    class _Bad:
        def with_structured_output(self, schema):
            return self

        async def ainvoke(self, prompt):
            raise RuntimeError("llm down")

    out = await rerank("问题", ["文档A", "文档B"], llm=_Bad(), top_k=2)
    assert len(out) == 2
    assert out[0]["relevance"] == 0  # 失败降级保留原序


# --- 索引：status/维度/幂等；检索隔离（真实 embedding）---


async def test_index_and_retrieve(db, user, tmp_path):
    uid = await _scoped(db, user.id)
    p = tmp_path / "doc.txt"
    p.write_text("机器学习是人工智能的一个重要分支。" * 5, encoding="utf-8")
    doc = await document_repo.create(db, uid, "测试文档", "doc.txt", "text/plain", str(p))
    await index_document(db, doc.id, str(p), uid, commit=False)
    await db.commit()
    assert doc.status == "ready"
    assert doc.chunk_count > 0
    chunk = (
        await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    ).scalars().first()
    assert len(chunk.embedding) == 512  # bge-small-zh 维度
    # 检索命中相关文档
    hits = await chunk_repo.vector_search(db, uid, await _emb("机器学习"), 3)
    assert hits and "机器学习" in hits[0][3]


async def test_index_idempotent(db, user, tmp_path):
    uid = await _scoped(db, user.id)
    p = tmp_path / "doc.txt"
    p.write_text("幂等测试内容。" * 30, encoding="utf-8")
    doc = await document_repo.create(db, uid, "t", "doc.txt", "text/plain", str(p))
    await index_document(db, doc.id, str(p), uid, commit=False)
    await db.commit()
    c1 = await _chunk_count(db, doc.id)
    await index_document(db, doc.id, str(p), uid, commit=False)  # 重跑
    await db.commit()
    c2 = await _chunk_count(db, doc.id)
    assert c1 == c2  # 先清再写，幂等


async def test_retrieve_isolation(db, user, tmp_path):
    a = await _scoped(db, user.id)
    b = uuid.uuid4()
    p = tmp_path / "doc.txt"
    p.write_text("只属于用户A的私密内容。" * 5, encoding="utf-8")
    doc = await document_repo.create(db, a, "A的文档", "doc.txt", "text/plain", str(p))
    await index_document(db, doc.id, str(p), a, commit=False)
    await db.commit()
    hits = await chunk_repo.vector_search(db, b, await _emb("私密内容"), 3)
    assert hits == []  # A 的 chunk 对 B 不可见（user_id 过滤）


# --- API 层：上传/列表/详情/搜索/删除 ---


async def _register_and_headers(client, email, username):
    await client.post(
        f"{P}/auth/register",
        json={"email": email, "username": username, "password": "pass1234", "timezone": "Asia/Shanghai"},
    )
    d = (await client.post(
        f"{P}/auth/login", json={"email": email, "password": "pass1234"}
    )).json()["data"]
    return {"Authorization": f"Bearer {d['access_token']}"}


async def test_api_documents_flow(client):
    headers = await _register_and_headers(client, "rag@example.com", "raguser")
    files = {"file": ("doc.txt", "机器学习是人工智能的分支。".encode(), "text/plain")}
    r = await client.post(f"{P}/documents", files=files, headers=headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "ready"
    assert data["chunk_count"] > 0

    r = await client.get(f"{P}/documents", headers=headers)
    assert r.json()["data"]["total"] >= 1

    r = await client.get(f"{P}/documents/{data['id']}", headers=headers)
    assert r.status_code == 200

    r = await client.post(f"{P}/search", json={"query": "机器学习", "top_k": 3}, headers=headers)
    assert r.status_code == 200
    assert r.json()["data"]["chunks"]

    r = await client.delete(f"{P}/documents/{data['id']}", headers=headers)
    assert r.status_code == 200

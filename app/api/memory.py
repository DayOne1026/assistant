"""05 记忆与知识图谱：/memory /graph 路由（蓝图 05 API 层）。"""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_isolated, get_db
from app.core.response import ok
from app.db.models.users import User
from app.neo4j_client import Neo4jClient, get_neo4j
from app.repos.memory import preference_repo
from app.schemas.memory import (
    MemoryItem,
    MemoryQueryRequest,
    MemoryResponse,
    TripleResponse,
)
from app.services.memory_service import MemoryService

router = APIRouter(tags=["memory"])


class PreferenceUpdate(BaseModel):
    value: Any  # 任意结构化值


def _service(db: AsyncSession, neo4j: Neo4jClient) -> MemoryService:
    return MemoryService(db, neo4j)


@router.get("/memory/preferences")
async def list_preferences(
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
):
    prefs = await preference_repo.list(db, user.id)
    return ok([MemoryItem(key=p.key, value=p.value) for p in prefs])


@router.put("/memory/preferences/{key}")
async def upsert_preference(
    key: str,
    data: PreferenceUpdate,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    neo4j: Neo4jClient = Depends(get_neo4j),
):
    """手动写入偏好（source=manual）。"""
    await _service(db, neo4j).remember(user.id, key, data.value, source="manual")
    return ok()


@router.post("/memory/query")
async def query_memory(
    data: MemoryQueryRequest,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    neo4j: Neo4jClient = Depends(get_neo4j),
):
    """记忆问答（图谱+偏好）。"""
    resp: MemoryResponse = await _service(db, neo4j).query_memory(user.id, data.question)
    return ok(resp)


@router.get("/graph/entities/{name}")
async def graph_entities(
    name: str,
    user: User = Depends(get_current_user_isolated),
    db: AsyncSession = Depends(get_db),
    neo4j: Neo4jClient = Depends(get_neo4j),
):
    """指定实体的多跳路径，展开为相邻关系三元组。"""
    paths = await _service(db, neo4j).get_related_entities(user.id, name)
    triples: list[TripleResponse] = []
    for p in paths:
        names, preds, confs = p["names"], p["predicates"], p["confidences"]
        for i in range(len(names) - 1):
            triples.append(
                TripleResponse(
                    subject=names[i],
                    predicate=preds[i] or "RELATED_TO",
                    object=names[i + 1],
                    confidence=confs[i] or 1.0,
                )
            )
    return ok(triples)

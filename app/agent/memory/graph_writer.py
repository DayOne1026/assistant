"""05 记忆与知识图谱：图谱写入（蓝图 05 GraphWriter）。

MERGE 幂等 + user_id 强制属性（03 复合唯一 (id, user_id)）。
节点/关系标签仅来自受限常量（EntityType），防 Cypher 注入。
"""

import hashlib
import uuid

from app.neo4j_client import Neo4jClient
from app.schemas.memory import EntityType, ExtractedTriple

_ENTITY_LABELS: frozenset[str] = frozenset(EntityType.__args__)

_MERGE_TEMPLATE = """
MERGE (s:`{s_type}` {{id: $sid, user_id: $user_id}})
SET s.name = $subject, s.confidence = $confidence,
    s.source_conversation_id = $conversation_id
MERGE (o:`{o_type}` {{id: $oid, user_id: $user_id}})
SET o.name = $object, o.confidence = $confidence,
    o.source_conversation_id = $conversation_id
MERGE (s)-[r:RELATED_TO {{predicate: $predicate, user_id: $user_id}}]->(o)
SET r.confidence = $confidence, r.source_conversation_id = $conversation_id
"""


def stable_id(user_id: uuid.UUID, name: str) -> str:
    """同用户同名实体稳定 id：sha256(user_id|name) 前 32 位。"""
    return hashlib.sha256(f"{user_id}|{name}".encode()).hexdigest()[:32]


class GraphWriter:
    def __init__(self, neo4j: Neo4jClient):
        self._neo4j = neo4j

    async def write_triples(
        self,
        user_id: uuid.UUID,
        triples: list[ExtractedTriple],
        conversation_id: uuid.UUID | None = None,
    ) -> int:
        """MERGE 写入三元组，返回写入条数。节点/关系带 user_id + source_conversation_id。"""
        for t in triples:
            # ponytail: 标签插值前强制白名单校验（可信常量），不接受任意字符串
            if t.subject_type not in _ENTITY_LABELS or t.object_type not in _ENTITY_LABELS:
                continue
            await self._neo4j.execute_write(
                _MERGE_TEMPLATE.format(
                    s_type=t.subject_type,
                    o_type=t.object_type,
                ),
                {
                    "user_id": str(user_id),
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "sid": stable_id(user_id, t.subject),
                    "oid": stable_id(user_id, t.object),
                    "subject": t.subject,
                    "object": t.object,
                    "predicate": t.predicate,
                    "confidence": t.confidence,
                },
            )
        return len(triples)

import uuid

import neo4j
from neo4j import AsyncGraphDatabase

from app.core.config import get_settings


def neo4j_user_scope(user_id: uuid.UUID) -> dict:
    """业务 Cypher 必须用该参数做首条过滤（03）：WHERE n.user_id = $user_id。
    code review 必查项：禁止裸 MATCH。
    """
    return {"user_id": str(user_id)}


class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str, database: str):
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        self._database = database

    async def run(self, query: str, params: dict | None = None) -> list:
        """只读查询；业务查询必须带 user_id 参数（03）。"""
        async with self._driver.session(
            database=self._database, default_access_mode=neo4j.READ_ACCESS
        ) as session:
            result = await session.run(query, params or {})
            return [record async for record in result]

    async def execute_write(self, query: str, params: dict | None = None) -> list:
        """写查询，内部开 WRITE session。"""
        async with self._driver.session(
            database=self._database, default_access_mode=neo4j.WRITE_ACCESS
        ) as session:
            result = await session.run(query, params or {})
            return [record async for record in result]

    async def verify_user_scope(self, user_id: str, node_id: str, label: str) -> bool:
        """节点归属校验：业务节点必须带 user_id 属性且等于当前用户（03 Cypher）。"""
        query = (
            f"MATCH (n:`{label}`) WHERE n.id = $node_id AND n.user_id = $user_id "
            "RETURN count(n) AS c"
        )
        # ponytail: label 来自可信代码常量（EntityType），非用户输入
        records = await self.run(query, {"node_id": node_id, "user_id": str(user_id)})
        return bool(records) and records[0]["c"] > 0

    async def close(self) -> None:
        await self._driver.close()


_neo4j: Neo4jClient | None = None


async def init_neo4j() -> Neo4jClient:
    global _neo4j
    if _neo4j is None:
        s = get_settings()
        _neo4j = Neo4jClient(s.neo4j_uri, s.neo4j_user, s.neo4j_password, s.neo4j_database)
    return _neo4j


async def close_neo4j() -> None:
    global _neo4j
    if _neo4j is not None:
        await _neo4j.close()
        _neo4j = None


async def get_neo4j() -> Neo4jClient:
    """FastAPI 依赖：全局单例（startup 时 init）。"""
    if _neo4j is None:
        raise RuntimeError("Neo4j 未初始化，请先启动应用")
    return _neo4j

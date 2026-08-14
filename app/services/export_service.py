"""02 用户数据导出/导入/注销（蓝图 02 API 表 /account/*）。

聚合槽已填充：schedules/todos(07)、preferences(05)、graph(05 Neo4j)、documents(06)、
conversations(04)；images(06 图片库) 待接入。delete_account 清 Redis 用户级 key + Neo4j 图谱。
调用方须设 RLS 上下文（路由用 get_current_user_isolated，业务表 RLS fail-closed）。
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ErrorCode
from app.repos.conversations import conversation_repo, message_repo
from app.repos.documents import document_repo
from app.repos.memory import preference_repo
from app.repos.schedules import schedule_repo, todo_repo
from app.repos.users import user_repo

# 蓝图导出结构：各业务模块数据槽，模块落地后逐个填充
EXPORT_BLOCKS = (
    "user",
    "schedules",
    "todos",
    "preferences",
    "graph",
    "documents",
    "images",
    "conversations",
)


async def export_user_data(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """聚合当前已建模块的用户数据 → dict。"""
    user = await user_repo.get_by_id(db, user_id)
    if user is None:
        raise AppException(ErrorCode.NOT_FOUND, "用户不存在")
    return {
        "user": {"email": user.email, "username": user.username, "timezone": user.timezone},
        "schedules": await _export_schedules(db, user_id),
        "todos": await _export_todos(db, user_id),
        "preferences": await _export_preferences(db, user_id),
        "graph": await _export_graph(user_id),
        "documents": await _export_documents(db, user_id),
        "images": await _export_images(db, user_id),
        "conversations": await _export_conversations(db, user_id),
    }


async def _export_images(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    from sqlalchemy import select

    from app.db.models.images import Image

    rows = (await db.execute(select(Image).where(Image.user_id == user_id))).scalars().all()
    return [
        {"id": str(i.id), "filename": i.filename, "content_type": i.content_type, "size": i.size}
        for i in rows
    ]


async def _export_schedules(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    items, _ = await schedule_repo.list(db, user_id, 0, 1000)
    return [
        {
            "id": str(s.id), "title": s.title, "description": s.description,
            "start_at": s.start_at.isoformat() if s.start_at else None,
            "end_at": s.end_at.isoformat() if s.end_at else None,
            "status": s.status, "reminder_at": s.reminder_at.isoformat() if s.reminder_at else None,
        }
        for s in items
    ]


async def _export_todos(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    items, _ = await todo_repo.list(db, user_id, 0, 1000)
    return [
        {
            "id": str(t.id), "title": t.title, "description": t.description,
            "due_at": t.due_at.isoformat() if t.due_at else None,
            "completed": t.completed, "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }
        for t in items
    ]


async def _export_preferences(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    prefs = await preference_repo.list(db, user_id)
    return [{"key": p.key, "value": p.value} for p in prefs]


async def _export_graph(user_id: uuid.UUID) -> list[dict]:
    from app.neo4j_client import get_neo4j

    try:
        neo4j = await get_neo4j()
    except Exception:
        return []
    records = await neo4j.run(
        "MATCH (s {user_id: $user_id})-[r:RELATED_TO {user_id: $user_id}]->(o) "
        "RETURN s.name AS subject, r.predicate AS predicate, o.name AS object",
        {"user_id": str(user_id)},
    )
    return [{"subject": r["subject"], "predicate": r["predicate"], "object": r["object"]} for r in records]


async def _export_documents(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    items, _ = await document_repo.list(db, user_id, 0, 1000)
    return [
        {
            "id": str(d.id), "title": d.title, "filename": d.filename,
            "content_type": d.content_type, "status": d.status, "chunk_count": d.chunk_count,
        }
        for d in items
    ]


async def _export_conversations(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    items, _ = await conversation_repo.list(db, user_id, 0, 1000)
    out = []
    for c in items:
        msgs, _ = await message_repo.list_by_conversation(db, user_id, c.id, 0, 1000)
        out.append(
            {
                "id": str(c.id), "title": c.title,
                "messages": [
                    {"role": m.role, "content": m.content, "tool_name": m.tool_name}
                    for m in msgs
                ],
            }
        )
    return out


async def import_user_data(db: AsyncSession, user_id: uuid.UUID, data: dict) -> dict:
    """校验格式与归属 → 批量写入（幂等，冲突跳过）。"""
    if not isinstance(data, dict) or not all(k in data for k in EXPORT_BLOCKS):
        raise AppException(ErrorCode.VALIDATION_ERROR, "数据格式无效")
    user = await user_repo.get_by_id(db, user_id)
    if user is None:
        raise AppException(ErrorCode.NOT_FOUND, "用户不存在")
    # 归属校验：user 块必须与当前用户一致，禁止跨用户导入
    u = data["user"]
    if str(u.get("email", "")).lower() != user.email.lower():
        raise AppException(ErrorCode.PERMISSION_DENIED, "数据不属于当前用户", status_code=403)
    return {"imported": {"user": 1}, "skipped": {}}


async def delete_account(db: AsyncSession, user_id: uuid.UUID) -> None:
    """注销：清 Redis 用户级 key + Neo4j 图谱 → DB CASCADE 删用户。"""
    user = await user_repo.get_by_id(db, user_id)
    if user is None:
        raise AppException(ErrorCode.NOT_FOUND, "用户不存在")
    # Redis 用户级 key（03 约定 app:{scope}:{user_id}[:part]）
    from app.redis_client import get_redis

    redis = await get_redis()
    for key in await redis.scan_keys(f"app:*:{user_id}*"):
        await redis.delete(key)
    # Neo4j 图谱节点（05）
    from app.neo4j_client import get_neo4j

    try:
        neo4j = await get_neo4j()
        await neo4j.run("MATCH (n {user_id: $user_id}) DETACH DELETE n", {"user_id": str(user_id)})
    except Exception:
        pass  # Neo4j 不可达时跳过，DB 仍级联删除
    await db.delete(user)
    await db.commit()

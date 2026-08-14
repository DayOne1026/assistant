-- 12/06：pgvector 扩展（hnsw 向量索引必需）。
-- docker-entrypoint-initdb.d 以 superuser 执行；应用角色 assistant_app 无权限建扩展，
-- 故 alembic 基线迁移里也假定本扩展已存在（CREATE EXTENSION 失败仅静默跳过）。
CREATE EXTENSION IF NOT EXISTS vector;

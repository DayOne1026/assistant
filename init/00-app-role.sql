-- 03 RLS 前置：bootstrap superuser（assistant）绕过 RLS 且不可降级，
-- 应用改用独立非 superuser 角色 assistant_app 连接。
-- 由 postgres 镜像 docker-entrypoint-initdb.d 首次初始化时以 superuser 执行。
CREATE ROLE assistant_app LOGIN PASSWORD 'assistant' NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT ALL PRIVILEGES ON DATABASE assistant TO assistant_app;
-- PG15+ public schema 默认无 PUBLIC CREATE，显式授予
GRANT ALL ON SCHEMA public TO assistant_app;
GRANT CREATE ON SCHEMA public TO assistant_app;

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全平台配置。env 前缀 ASSISTANT_，读 .env（见 .env.example）。
    蓝图标注「必填」的 secret 类字段给了 dev 默认值，生产必须用环境变量覆盖。
    """

    model_config = SettingsConfigDict(env_prefix="ASSISTANT_", env_file=".env", extra="ignore")

    app_name: str = "assistant"
    env: str = "dev"
    api_prefix: str = "/api/v1"

    # JWT（02）；dev 默认 ≥32 字节，生产必须 env 覆盖
    secret_key: str = "dev-secret-change-me-to-32-bytes-plus"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    timezone: str = "Asia/Shanghai"

    # PostgreSQL（pgvector）；应用用非 superuser 角色（03，RLS 对 superuser 无效）
    database_url: str = "postgresql+asyncpg://assistant_app:assistant@localhost:5432/assistant"
    pg_echo: bool = False
    pool_size: int = 10
    max_overflow: int = 20

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "dev-password-change-me"
    neo4j_database: str = "neo4j"

    # LLM（01）
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_api_key: str = "change-me"
    llm_base_url: str = "https://api.deepseek.com"
    vision_model: str = "qwen-vl-max"

    # Embedding（06）：本地 BGE（bge-small-zh-v1.5，512 维；本地已缓存，离线可用）
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dim: int = 512

    # Celery（08/10/12）
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # CORS 白名单（不用 *）
    cors_origins: list[str] = ["http://localhost:3000"]

    # 限流（11）
    rate_limit_max: int = 60
    rate_limit_window_seconds: int = 60
    rate_limit_enabled: bool = True  # 测试环境关闭（conftest 设 ASSISTANT_RATE_LIMIT_ENABLED=false）
    harmful_filter_enabled: bool = True  # 有害内容过滤开关

    # SMTP（08 email 渠道）；未配置时 send_email 跳过
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "assistant@localhost"

    # OAuth（09）
    oauth_token_encryption_key: str = "dev-key-change-me"
    oauth_redirect_base: str = "http://localhost:8000/api/v1/integrations"
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    outlook_oauth_client_id: str = ""
    outlook_oauth_client_secret: str = ""
    jwt_blacklist_enabled: bool = True

    # 图片库（06，CLIP 本地向量）
    image_embedding_model: str = "clip-ViT-B-32"
    image_embedding_dim: int = 512

    # 文件存储（06）
    storage_root: str = "storage"

    # RAG 索引（06/12）：True 走 Celery 异步索引（worker 部署后），False 同步（测试/无 worker）
    indexing_async: bool = False

    # 联网搜索（06 web_search）
    tavily_api_key: str = ""

    # OTel（12）
    otel_enabled: bool = False
    otel_service_name: str = "assistant"


@lru_cache
def get_settings() -> Settings:
    """单例返回 Settings。"""
    return Settings()

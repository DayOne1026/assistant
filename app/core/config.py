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

    # JWT（02）
    secret_key: str = "dev-secret-change-me"
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

    # Embedding（06）
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    # Celery（08/10/12）
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # CORS 白名单（不用 *）
    cors_origins: list[str] = ["http://localhost:3000"]

    # 限流（11）
    rate_limit_max: int = 60
    rate_limit_window_seconds: int = 60

    # OAuth（09）
    oauth_token_encryption_key: str = "dev-key-change-me"
    jwt_blacklist_enabled: bool = True

    # 图片库（06，CLIP 本地向量）
    image_embedding_model: str = "clip-ViT-B-32"
    image_embedding_dim: int = 512

    # 文件存储（06）
    storage_root: str = "storage"

    # 联网搜索（06 web_search）
    tavily_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    """单例返回 Settings。"""
    return Settings()

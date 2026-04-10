"""Centralized application settings."""

from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseModel):
    name: str = "mirror-main-agent"
    env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"


class PostgresConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 5432
    db: str = "mirror"
    user: str = "mirror"
    password: str = "mirror"
    dsn: str = "postgresql://mirror:mirror@127.0.0.1:5432/mirror"


class RedisConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 6379
    db: int = 0
    password: str = ""
    url: str = "redis://127.0.0.1:6379/0"


class Neo4jConfig(BaseModel):
    uri: str = "bolt://127.0.0.1:7687"
    user: str = "neo4j"
    password: str = "mirrorneo4j"
    database: str = "neo4j"


class QdrantConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 6333
    grpc_port: int = 6334
    url: str = "http://127.0.0.1:6333"
    api_key: str = ""


class OpenCodeConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 4096
    base_url: str = "http://127.0.0.1:4096"
    image: str = "ghcr.io/sst/opencode:latest"


class ModelRouteConfig(BaseModel):
    provider_type: str
    vendor: str
    model: str
    base_url: str
    api_key: str = ""


class ModelRoutingConfig(BaseModel):
    reasoning_main: ModelRouteConfig
    lite_extraction: ModelRouteConfig
    retrieval_embedding: ModelRouteConfig
    retrieval_reranker: ModelRouteConfig


class Settings(BaseSettings):
    """Single entry point for environment-backed settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "mirror-main-agent"
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_LOG_LEVEL: str = "INFO"

    POSTGRES_HOST: str = "127.0.0.1"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "mirror"
    POSTGRES_USER: str = "mirror"
    POSTGRES_PASSWORD: str = "mirror"
    POSTGRES_DSN: str = "postgresql://mirror:mirror@127.0.0.1:5432/mirror"

    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""
    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    NEO4J_URI: str = "bolt://127.0.0.1:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "mirrorneo4j"
    NEO4J_DATABASE: str = "neo4j"

    QDRANT_HOST: str = "127.0.0.1"
    QDRANT_PORT: int = 6333
    QDRANT_GRPC_PORT: int = 6334
    QDRANT_URL: str = "http://127.0.0.1:6333"
    QDRANT_API_KEY: str = ""

    OPENCODE_HOST: str = "127.0.0.1"
    OPENCODE_PORT: int = 4096
    OPENCODE_BASE_URL: str = "http://127.0.0.1:4096"
    OPENCODE_IMAGE: str = "ghcr.io/sst/opencode:latest"

    MODEL_REASONING_MAIN_PROVIDER_TYPE: str = "openai_compatible"
    MODEL_REASONING_MAIN_VENDOR: str = "openai"
    MODEL_REASONING_MAIN_MODEL: str = "gpt-4.1"
    MODEL_REASONING_MAIN_BASE_URL: str = "https://api.openai.com/v1"
    MODEL_REASONING_MAIN_API_KEY: str = ""

    MODEL_LITE_EXTRACTION_PROVIDER_TYPE: str = "openai_compatible"
    MODEL_LITE_EXTRACTION_VENDOR: str = "openai"
    MODEL_LITE_EXTRACTION_MODEL: str = "gpt-4.1-mini"
    MODEL_LITE_EXTRACTION_BASE_URL: str = "https://api.openai.com/v1"
    MODEL_LITE_EXTRACTION_API_KEY: str = ""

    MODEL_RETRIEVAL_EMBEDDING_PROVIDER_TYPE: str = "openai_compatible"
    MODEL_RETRIEVAL_EMBEDDING_VENDOR: str = "openai"
    MODEL_RETRIEVAL_EMBEDDING_MODEL: str = "text-embedding-3-large"
    MODEL_RETRIEVAL_EMBEDDING_BASE_URL: str = "https://api.openai.com/v1"
    MODEL_RETRIEVAL_EMBEDDING_API_KEY: str = ""

    MODEL_RETRIEVAL_RERANKER_PROVIDER_TYPE: str = "openai_compatible"
    MODEL_RETRIEVAL_RERANKER_VENDOR: str = "local"
    MODEL_RETRIEVAL_RERANKER_MODEL: str = "reranker-v1"
    MODEL_RETRIEVAL_RERANKER_BASE_URL: str = "http://127.0.0.1:8081"
    MODEL_RETRIEVAL_RERANKER_API_KEY: str = ""

    @property
    def app(self) -> AppConfig:
        return AppConfig(
            name=self.APP_NAME,
            env=self.APP_ENV,
            host=self.APP_HOST,
            port=self.APP_PORT,
            log_level=self.APP_LOG_LEVEL,
        )

    @property
    def postgres(self) -> PostgresConfig:
        return PostgresConfig(
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            db=self.POSTGRES_DB,
            user=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            dsn=self.POSTGRES_DSN,
        )

    @property
    def redis(self) -> RedisConfig:
        return RedisConfig(
            host=self.REDIS_HOST,
            port=self.REDIS_PORT,
            db=self.REDIS_DB,
            password=self.REDIS_PASSWORD,
            url=self.REDIS_URL,
        )

    @property
    def neo4j(self) -> Neo4jConfig:
        return Neo4jConfig(
            uri=self.NEO4J_URI,
            user=self.NEO4J_USER,
            password=self.NEO4J_PASSWORD,
            database=self.NEO4J_DATABASE,
        )

    @property
    def qdrant(self) -> QdrantConfig:
        return QdrantConfig(
            host=self.QDRANT_HOST,
            port=self.QDRANT_PORT,
            grpc_port=self.QDRANT_GRPC_PORT,
            url=self.QDRANT_URL,
            api_key=self.QDRANT_API_KEY,
        )

    @property
    def opencode(self) -> OpenCodeConfig:
        return OpenCodeConfig(
            host=self.OPENCODE_HOST,
            port=self.OPENCODE_PORT,
            base_url=self.OPENCODE_BASE_URL,
            image=self.OPENCODE_IMAGE,
        )

    @property
    def model_routing(self) -> ModelRoutingConfig:
        return ModelRoutingConfig(
            reasoning_main=ModelRouteConfig(
                provider_type=self.MODEL_REASONING_MAIN_PROVIDER_TYPE,
                vendor=self.MODEL_REASONING_MAIN_VENDOR,
                model=self.MODEL_REASONING_MAIN_MODEL,
                base_url=self.MODEL_REASONING_MAIN_BASE_URL,
                api_key=self.MODEL_REASONING_MAIN_API_KEY,
            ),
            lite_extraction=ModelRouteConfig(
                provider_type=self.MODEL_LITE_EXTRACTION_PROVIDER_TYPE,
                vendor=self.MODEL_LITE_EXTRACTION_VENDOR,
                model=self.MODEL_LITE_EXTRACTION_MODEL,
                base_url=self.MODEL_LITE_EXTRACTION_BASE_URL,
                api_key=self.MODEL_LITE_EXTRACTION_API_KEY,
            ),
            retrieval_embedding=ModelRouteConfig(
                provider_type=self.MODEL_RETRIEVAL_EMBEDDING_PROVIDER_TYPE,
                vendor=self.MODEL_RETRIEVAL_EMBEDDING_VENDOR,
                model=self.MODEL_RETRIEVAL_EMBEDDING_MODEL,
                base_url=self.MODEL_RETRIEVAL_EMBEDDING_BASE_URL,
                api_key=self.MODEL_RETRIEVAL_EMBEDDING_API_KEY,
            ),
            retrieval_reranker=ModelRouteConfig(
                provider_type=self.MODEL_RETRIEVAL_RERANKER_PROVIDER_TYPE,
                vendor=self.MODEL_RETRIEVAL_RERANKER_VENDOR,
                model=self.MODEL_RETRIEVAL_RERANKER_MODEL,
                base_url=self.MODEL_RETRIEVAL_RERANKER_BASE_URL,
                api_key=self.MODEL_RETRIEVAL_RERANKER_API_KEY,
            ),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

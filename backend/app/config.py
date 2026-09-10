from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "yaoke"

    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    rerank_model: str = "BAAI/bge-reranker-base"
    enable_rerank: bool = False

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "ornith-1.5:9b"

    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"

    # Controlled web search backend. Agent mode decides whether the tool is exposed to Ornith.
    web_search_enabled: bool = True
    web_search_backend: str = "auto"
    web_search_region: str = "cn-zh"
    web_search_max_results: int = 5
    web_search_timeout_seconds: int = 8

    # P1.4 Ornith Agent. Three rounds is a hard product/safety ceiling, not only a default.
    agent_mode_default: str = "auto"
    agent_max_tool_rounds: int = Field(default=3, ge=1, le=3)
    agent_llm_timeout_seconds: int = 120

    chunk_size: int = 800
    chunk_overlap: int = 120
    vector_weight: float = 0.70
    top_k: int = 5
    max_file_size_mb: int = 20
    bm25_cache_ttl_seconds: int = Field(default=300, ge=0, le=3600)
    retrieval_parallel_hybrid: bool = True

    jwt_secret: str = "change-me-before-production-yaoke-demo-secret"
    jwt_expire_hours: int = 8

    # Local backend cwd is normally ./backend, so ../demo-data points to repo demo data.
    # Docker overrides this to /app/demo-data via docker-compose.
    demo_data_dir: str = "../demo-data"


settings = Settings()

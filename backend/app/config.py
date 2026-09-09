from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "nexuskb"

    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    rerank_model: str = "BAAI/bge-reranker-base"
    enable_rerank: bool = False

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"

    chunk_size: int = 800
    chunk_overlap: int = 120
    vector_weight: float = 0.70
    top_k: int = 5
    max_file_size_mb: int = 20

    jwt_secret: str = "change-me-before-production-nexuskb-demo-secret"
    jwt_expire_hours: int = 8

    # Local backend cwd is normally ./backend, so ../demo-data points to repo demo data.
    # Docker overrides this to /app/demo-data via docker-compose.
    demo_data_dir: str = "../demo-data"


settings = Settings()

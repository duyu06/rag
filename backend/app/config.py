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
    # Keep the local model resident between requests to avoid repeated load latency.
    ollama_keep_alive: str = "30m"

    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"

    # Controlled web search backend. Agent mode decides whether the tool is exposed to Ornith.
    web_search_enabled: bool = True
    web_search_backend: str = "auto"
    web_search_region: str = "cn-zh"
    web_search_max_results: int = 5
    web_search_timeout_seconds: int = 8

    # Ornith Agent.
    agent_mode_default: str = "auto"
    agent_max_tool_rounds: int = Field(default=3, ge=1, le=3)
    agent_llm_timeout_seconds: int = 120
    # Tool-routing turns may reason; evidence-only synthesis should be fast and bounded.
    agent_think_tool_routing: bool = True
    agent_think_synthesis: bool = False
    agent_num_predict_tool_routing: int = Field(default=768, ge=64, le=4096)
    agent_num_predict_synthesis: int = Field(default=512, ge=64, le=4096)
    # Only the most recent completed conversation messages are sent back to the model.
    agent_history_max_messages: int = Field(default=8, ge=0, le=20)
    # Local mode is an explicit enterprise-only mode, so it can safely skip the
    # first model tool-decision round and execute authorized enterprise_search directly.
    agent_local_fast_path: bool = True

    chunk_size: int = 800
    chunk_overlap: int = 120
    vector_weight: float = 0.70  # retained for config compatibility; P1.6 Hybrid uses RRF.
    top_k: int = 5
    max_file_size_mb: int = 20
    bm25_cache_ttl_seconds: int = Field(default=300, ge=0, le=3600)
    retrieval_parallel_hybrid: bool = True
    # P1.6 metadata-aware index generation. Demo data is automatically reindexed
    # when the payload schema version changes.
    retrieval_schema_version: str = "p16-metadata-rrf-v1"
    retrieval_vector_candidates: int = Field(default=30, ge=5, le=100)
    retrieval_bm25_candidates: int = Field(default=30, ge=5, le=100)
    retrieval_rrf_k: int = Field(default=60, ge=1, le=200)
    retrieval_rerank_candidates: int = Field(default=12, ge=5, le=50)
    # BGE's short-query retrieval instruction improves pure dense Top-3 recall on
    # the real-BGE gate. Hybrid keeps the raw query because it measured better with RRF.
    retrieval_vector_query_instruction: str = "为这个句子生成表示以用于检索相关文章："
    # Prefer diverse documents in the final evidence set while still allowing a
    # document to contribute multiple sections. Deferred chunks fill any shortage.
    retrieval_max_chunks_per_document: int = Field(default=2, ge=1, le=10)
    retrieval_query_context_max_chars: int = Field(default=320, ge=80, le=1000)

    jwt_secret: str = "change-me-before-production-yaoke-demo-secret"
    jwt_expire_hours: int = 8

    # Local backend cwd is normally ./backend, so ../demo-data points to repo demo data.
    # Docker overrides this to /app/demo-data via docker-compose.
    demo_data_dir: str = "../demo-data"


settings = Settings()

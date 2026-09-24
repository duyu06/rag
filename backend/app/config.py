from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "yaoke"

    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    rerank_model: str = "BAAI/bge-reranker-base"
    enable_rerank: bool = False
    rerank_provider: Literal["local", "typesafe"] = "local"

    # TypeSafe is an optional, server-side-only judgment layer. With the defaults
    # below it performs no network calls and the existing local reranker remains
    # authoritative.
    typesafe_enabled: bool = False
    # 五档：off 从不调用；shadow 恒调用只观测；selective 仅 should_judge() 触发才调用并应用；
    # active 高置信单一事实外都调用并应用；strict 恒调用并应用（=V1 active，验收用）。
    typesafe_mode: Literal["off", "shadow", "selective", "active", "strict"] = "shadow"
    typesafe_api_key: SecretStr = SecretStr("")
    typesafe_base_url: str = "https://api.typesafe.ai"
    typesafe_model: str = "jev-latest"
    typesafe_timeout_seconds: float = Field(default=8.0, ge=0.5, le=120.0)
    typesafe_max_concurrency: int = Field(default=6, ge=1, le=16)
    typesafe_candidates: int = Field(default=6, ge=1, le=20)
    # 动态 TopK 的 compound 档；V1 该键默认 12，V2 按设计 §4/§8 收紧为 8（键名保持不变）。
    typesafe_compound_candidates: int = Field(default=8, ge=2, le=30)
    typesafe_max_passage_chars: int = Field(default=2400, ge=200, le=8000)
    typesafe_injection_max: float = Field(default=0.70, ge=0.0, le=1.0)
    typesafe_contradicts_min: float = Field(default=0.70, ge=0.0, le=1.0)
    typesafe_relevant_min: float = Field(default=0.45, ge=0.0, le=1.0)
    typesafe_evidence_min: float = Field(default=0.55, ge=0.0, le=1.0)
    typesafe_input_price_per_million_usd: float = Field(default=0.042, ge=0.0)
    # V2 判定段超时预算：软线只记 slow 计数，硬线取消未完成批次并退本地序。
    # 硬线终值 3000 = Task 8 §8/§9 预留的标定动作（段A：1800 压在本 API 单请求 P95 1835ms
    # 之下；段B：批次墙钟在 6-8 条逐判定请求下尾部落 3.0-4.9s，1800/2400 均低于现网）。
    # 语义对象是**一个判定批次**（spec §5），不是单请求、也不跨批次累计。
    typesafe_soft_timeout_ms: int = Field(default=1200, ge=500, le=30000)
    typesafe_hard_timeout_ms: int = Field(default=3000, ge=1000, le=60000)
    # 动态 TopK（替代 V1 固定 6/12）：判定前池尺寸按 margin / confidence_floor 分档。
    typesafe_min_candidates: int = Field(default=3, ge=1, le=12)
    typesafe_max_candidates: int = Field(default=6, ge=1, le=20)
    typesafe_low_confidence_candidates: int = Field(default=12, ge=2, le=40)
    # CE 分差与置信度门槛；默认值在首轮 59 题 strict 对照中标定。
    typesafe_high_margin: float = Field(default=0.25, ge=0.0, le=1.0)
    typesafe_medium_margin: float = Field(default=0.10, ge=0.0, le=1.0)
    typesafe_confidence_floor: float = Field(default=0.20, ge=0.0, le=1.0)
    # 语义去重：cosine 达阈值即合并并保留高分块。
    typesafe_dedup_cosine: float = Field(default=0.97, ge=0.0, le=1.0)
    # 进程内判定缓存（单 worker 部署足够，不做持久化）；文档重建后内容 hash 自然失效。
    typesafe_cache_enabled: bool = True
    typesafe_cache_ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    typesafe_cache_max_entries: int = Field(default=2048, ge=128, le=65536)
    # 熔断：窗口下限 8 与 app/resilience.CircuitBreaker 的构造约束同轨，坏配置在启动期即拒。
    typesafe_breaker_enabled: bool = True
    typesafe_breaker_window: int = Field(default=20, ge=8, le=200)
    typesafe_breaker_failure_ratio: float = Field(default=0.30, ge=0.0, le=1.0)
    typesafe_breaker_open_seconds: int = Field(default=60, ge=1, le=3600)
    typesafe_breaker_half_open_probes: int = Field(default=3, ge=1, le=10)

    @property
    def effective_typesafe_mode(self) -> str:
        """判定层唯一入口口径：typesafe_enabled=false 恒等价 off，mode 不得反向打开。"""
        if not self.typesafe_enabled:
            return "off"
        return self.typesafe_mode

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "ornith-1.5:9b"
    # Keep the local model resident between requests to avoid repeated load latency.
    ollama_keep_alive: str = "30m"

    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"

    # Model Router V2.3（设计 §3/§12）。默认开启：三条链路走统一 router；
    # false = 三链 legacy 原行为（仅限本版紧急回退，下一稳定版删除该分支）。
    llm_router_enabled: bool = True
    # 声明式注册表（零 secret：凭据只从 env 来，D1）。相对路径以 WORKDIR(backend/)
    # 为基准，容器镜像已 COPY config，与 FEISHU_RULES_FILE 同一口径。
    llm_registry_file: str = "config/llm_registry.json"
    # **总预算制**：三 attempt 共享这 30s（禁按模型相加）；每 attempt 再取
    # min(llm_model_timeout_seconds, budget.remaining())（spec §6）。
    llm_total_budget_ms: int = Field(default=30000, ge=5000, le=120000)
    llm_model_timeout_seconds: int = Field(default=20, ge=1, le=300)
    # 当前模型的重试次数（仅 retryable 类；model_unavailable 不重试当前——换模型更快，spec §6 冻结）。
    llm_retry_per_model: int = Field(default=1, ge=0, le=2)
    # 逐 provider 熔断（D4：`CircuitBreaker(name=provider)`）。window 下限 8 与
    # app/resilience.MIN_WINDOW 同轨，坏配置在启动期即拒，不会悄悄永不熔断。
    llm_breaker_enabled: bool = True
    llm_breaker_window: int = Field(default=20, ge=8, le=200)
    llm_breaker_failure_ratio: float = Field(default=0.30, ge=0.0, le=1.0)
    llm_breaker_open_seconds: int = Field(default=60, ge=1, le=3600)
    llm_breaker_half_open_probes: int = Field(default=3, ge=1, le=10)
    # 云厂商占位（PENDING_EXTERNAL）：key 只允许写入 backend/.env 或生产 Secret Store；
    # 无 key 时注册表解析层把对应 external 条目收成 enabled=False（不删条目、不改 JSON）。
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    qwen_api_key: SecretStr = SecretStr("")
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

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
    retrieval_schema_version: str = "p16-metadata-rrf-v2"
    retrieval_vector_candidates: int = Field(default=30, ge=5, le=100)
    retrieval_bm25_candidates: int = Field(default=30, ge=5, le=100)
    retrieval_rrf_k: int = Field(default=60, ge=1, le=200)
    # Six candidates preserve the 30-question quality baseline while halving
    # warm CPU rerank latency versus the previous pool of twelve.
    retrieval_rerank_candidates: int = Field(default=6, ge=5, le=50)
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

    # Feishu permission bridge (see docs/FEISHU_PERMISSION_BRIDGE_DESIGN.md).
    # Disabled by default: every behaviour stays exactly like the demo accounts.
    feishu_permissions_enabled: bool = False
    feishu_app_id: str = ""
    feishu_app_secret: SecretStr = SecretStr("")
    feishu_base_url: str = "https://open.feishu.cn"
    feishu_timeout_seconds: float = Field(default=3.0, ge=0.5, le=30.0)
    feishu_cache_ttl_seconds: int = Field(default=900, ge=30, le=86400)
    feishu_cache_stale_seconds: int = Field(default=86400, ge=60, le=604800)
    feishu_rules_file: str = "config/feishu_permissions.json"


settings = Settings()

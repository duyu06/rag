
**Files:** Create `app/llm/errors.py`、`normalize.py`、`provider.py`、`health.py`；测试类②（MockTransport）。

**Interfaces:**
- `errors.py`：`class LLMError(Exception): kind: Literal["retryable","config","hard","model_unavailable"]; status_code:int|None`；`classify(status:int, body_text:str) -> LLMError|None`（408/429/500/502/503/504→retryable；body 含 `alloc|failed to load|model not found|no such model`→model_unavailable(亦走 retryable 路径但 kind 独立)；401/403→config；400/404/422→hard_retryable_no(=non-retryable 可 fallback)；`payload_too_large|invalid tool schema|unsupported`→hard_terminal NO_FALLBACK）；`from_exception(exc)`（ConnectTimeout/ReadTimeout/ConnectionError→retryable；HTTPStatusError→classify(status)）。
- `normalize.py`：`openai_payload(req, model)` / `parse_openai_response(data, model, provider, latency)` / `parse_openai_tool_calls` / `ollama_payload(req, model)`（think/keep_alive/options 按 `agent.py:47-78` 现有形状平移）/ `parse_ollama_response`（message+tool_calls+prompt_eval_count）/ `openai_stream_lines(resp)->Iterator[LLMChunk]`（data: [DONE] 终止、delta.content、最后 usage 块）/ `ollama_stream_lines(resp)`（逐行 JSON、`message.content`、done+eval_count）。
- `health.py`：probe 收编（D6）——`probe_ollama/probe_llm` 从 rag.py 迁入（签名不变），`knowledge_os.py` 改 import；`provider_health_view(registry) -> Mapping[provider, {"healthy":bool}]`（60s 缓存）供 router 与 status 聚合消费。
- `provider.py`：`complete(model: ModelDefinition, req: LLMRequest, timeout: float) -> LLMResponse`、`stream(model, req, timeout) -> Iterator[LLMChunk]`（内部按 `model.provider` 选适配器 dict `PROVIDERS`）；未知 provider→hard_terminal；httpx 客户端**仅此处构造**（health.py 的 probe 亦经此层统一发请求）；`native_stream.py` 本任务**不动**（Task 7 迁移后其调用方消失，再于 Task 7 删除文件）。

Steps：错误分类表逐码参数化测试、Ollama/OpenAI complete/stream 报文级 Mock 测试（含 tool_calls 字符串参数→dict、usage 缺失记 0+estimated 旗标、`[DONE]`、中文 UTF-8 行拆包）、probe 迁移引用点全改 + `test_runtime_metadata_contract` 等既有钉不降强度 → 绿。


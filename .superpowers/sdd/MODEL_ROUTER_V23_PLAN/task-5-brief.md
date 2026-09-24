
**Files:** Create `app/llm/usage.py`；Modify `app/knowledge_os.py`（status 增 `"llm"` 块 + warmup 挂 lifespan 与 identity.warmup 并排）、`app/security.py`（`llm` 块字段白名单常量）、`app/agent_trace.py`/`conversation_agent.py`/`agent.py` 的 trace 组装点注入 `model_route`（additive）；测试类⑤。

**Interfaces:** `init_usage_db()`（CREATE TABLE IF NOT EXISTS，字段=spec §8 冻结 19 列）；`log_usage(UsageRecord)`（try/except fail-open + `logging.warning`）；`aggregate_status(window_s=300)`→`{requests_5m, success_rate, fallback_rate, p95_latency_ms, providers:{name:{healthy}}}`（healthy 来自 provider probes 缓存 60s）；trace `model_route` 结构按 spec §6 示例（机器码）。禁存项反测试：插入含中文 prompt 的请求后 `SELECT * FROM llm_request_logs` 全列扫 prompt 片段 0 命中；status 响应形状等式测试（未知键不外泄）。

## Task 2 评审移交项

- **M-7（不修，记本任务）：`error_type` 只存机器码，不存 `str(LLMError)`。** Task 2 的 `LLMError.message` 刻意带「状态码 + provider 回显的 body 摘要」（截断 200 字符、已压平换行），那是给人读的诊断面，不是可入库的结构化字段：里面可能有上游任意文本，且会随 `classify` 的文案调整而漂移。落库口径固定为
  `error_type = error.kind`（四值：`retryable` / `config` / `hard` / `model_unavailable`，必要时加 `no_fallback` 后缀如 `hard:no_fallback`）+ `status_code = error.status_code`（已有列，int/None）。
  反测试建议直接沿用 §8 的禁存项扫法：造一条 body 含唯一 canary 的失败响应，断言 `llm_request_logs` 全列 0 命中该 canary（能同时挡住把 `str(exc)`、traceback 或 prompt 顺手塞进 `error_type` 的实现）。
- 顺带一句同源事实：`LLMError.retryable` / `fallback_allowed` / `is_config` 三个派生属性已经把「重试当前 / 换候选 / 跳 provider」的判定做完了，Task 5 只归因、不再判策略（策略在 Task 4）。



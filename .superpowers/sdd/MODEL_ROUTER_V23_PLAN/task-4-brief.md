
**Files:** Create `app/llm/fallback.py`；`__init__.py` 填公共 `complete()/stream()`（含 `router_enabled()`、classifier→plan→execute→usage.log 编排与 mode 参数）；测试类④。

**Interfaces:** `run_complete(profile, req, *, trace_id, request_id) -> FallbackResult(response: LLMResponse, attempts: tuple[Attempt,...], selected_index:int, budget_ms:float)`；`run_stream(...) -> StreamSession`：`session.chunks()` 首 chunk 前异常→内部换下一候选重开请求（对用户无感），yield 出第一个 chunk 即 `committed=True`；此后异常→上抛 `StreamInterrupted(partial_text)`，**不再切模型**；`session.finish()` 汇总 usage/ttft。Attempt(model,provider,result:success|failed|skipped_circuit,error_type,latency_ms)。重试=`llm_retry_per_model` 次当前模型（retryable kind；model_unavailable 不重试当前——换模型更快，冻结）；401/403→该 provider 其余候选本次跳过 + `PROVIDER_CONFIG_FAILED`；hard terminal→立即上抛。breaker：`allow()` False→Attempt(skipped_circuit)+reason，不 record；每 attempt 后 `record(ok)`。预算：`TimeoutBudget(soft_ms=budget*0.7, hard_ms=llm_total_budget_ms)`；每 attempt `timeout=min(llm_model_timeout_seconds, remaining/1000)`；exhausted→停止并上抛聚合错误（业务层兜底文案不变）。

Mock 矩阵测试：spec §10 表 #3–#8、#10、#11（pre-commit 切换/post-commit 不切）+ legacy flag off。


## Task 3 评审移交（硬义务）
1. execute 前置上下文收口：对 RoutePlan 候选按 `sum(len(str(m)) for m in req.messages)/2 > context_tokens` 二次过滤，收口后为空抛 `NoCapableModelError(stage="context")`。
2. `_Stage` 需含 "context"；`NoCapableModelError` 入口校验 reason_codes ⊆ 冻结枚举（Task 3 修复轮负责，T4 直接依赖）。
3. 出厂注册表下 agent 必然 NoCapable → fast-path 是常驻主干分支；T8 需核对 ornith 真实 tools 能力（现 app/agent.py 无条件发 tools，与 §3 tools=false 冲突）。
4. trace.model_route 带 stage+被剔计数（勿造新 reason 码）；PRIMARY_UNHEALTHY 描述被剔 provider，文案注意。

# Model Router V2.3 — Enterprise LLM Routing & Resilience Layer 设计

日期：2026-09-23 · 状态：已冻结（用户方案九段 + D1–D6 裁决 + 发布约束全部批准）
原则（冻结）：**spec 中 D1–D6、19+1 验收矩阵、P0 failover 用例与 DoD 的优先级高于实现便利性；实现与 spec 冲突时改实现，不反向放宽 spec。**
前置：`TYPESAFE_V2_PRODUCTION_DESIGN.md`（判定层已交付）、`app/resilience.py`（本设计复用其熔断/预算件）。

## 1. 目标与范围

把三条生成链路（`rag.py` 非流式、`conversation_agent.py` SSE、`agent.py` 工具回路）收编进统一 LLM Router：能力注册表、规则路由、failover、逐 provider 熔断、全局超时预算、token/成本记账与可解释 trace。

**本单不做（明确排除）**：隐私路由（KB data_classification，V2.5）、模型控制台 UI（V2.6）、动态性能路由/学习类路由（V2.7）、预算强制（budget enforcement 只记账不拦截）。`LLM_ROUTER_ENABLED=false` 的 legacy 路径仅限 V2.3 紧急回退，**下一稳定版必须删除**。

## 2. 架构边界（冻结）

```
RAG ─┐
SSE ─┼─> LLMRouter ─> RequestProfile ─> ModelRegistry ─> Candidate Selection ─> RoutePlan(primary+fallbacks+reason)
Agent┘                                                                    │
                                                              FallbackExecutor（CircuitBreaker×provider + TimeoutBudget 全局）
                                                          │
                                                       Provider（唯一出口）
                                              ┌───────────┴───────────┐
                                        OllamaNative             OpenAICompat
```

- **Single Egress**：除 `backend/app/llm/provider.py` 外，全 `backend/app/` 禁止出现 `/api/chat`、`/v1/chat/completions`、`OLLAMA_BASE_URL`、`_API_KEY` 直连、以及任何指向 LLM endpoint 的 httpx 调用——以契约测试静态扫描强制执行（D6）。业务层禁止 `if provider == ...` 形态。
- 目录（冻结）：`backend/app/llm/{__init__,models,registry,classifier,router,provider,fallback,usage,errors,normalize}.py`。

## 3. Registry（声明式，零 secret）

`backend/config/llm_registry.json`（`LLM_REGISTRY_FILE` 可覆盖），schema 按用户方案第一段原样冻结：`version`、每模型 `{id, provider, model, enabled, external, capabilities{chat,rag,tools,stream,reasoning}, priority{chat,rag,tools}, limits{context_tokens,max_output_tokens}, pricing{input_per_1m,output_per_1m,currency}}`。运行逻辑不入 JSON。

- **D1 凭据解析**：provider → env 约定 `{PROVIDER大写}_API_KEY / _BASE_URL / _MODEL_OVERRIDE`；`ollama` 读现有 `OLLAMA_BASE_URL/OLLAMA_MODEL`；内置 `openai` 条目复用现有 `OPENAI_*`（不产生第二套配置）。注册表**永不**含 key/base url。
- 默认注册表内置：`ollama-ornith`（ornith-1.5:9b-text，tools=false，priority 100/100/0）、`ollama-phi3`（phi3:mini，tools=false，80/80/0）、`openai`（gpt-4.1-mini，enabled=true 仅当 key 非空，tools=true）、`deepseek-chat`/`qwen-plus`（enabled=false 占位，tools=true）。能力旗标按各模型真实能力，注册表校验失败（结构/重复 id/非法 priority）= `LLM_ROUTER_ENABLED=true` 时启动 fail-fast（沿用 identity.warmup 模式）。
- `models.py` 数据对象（冻结清单，不过度抽象）：`ModelCapabilities / ModelPricing / ModelLimits / ModelDefinition / RequestProfile / RouteCandidate / RoutePlan / LLMRequest / LLMResponse / LLMChunk / ToolCall / UsageRecord`。`RequestProfile` 为 frozen dataclass：`mode: chat|rag|agent`、`complexity: low|medium|high`、`needs_tools`、`needs_stream`、`needs_reasoning=false`——Router 唯一合法输入。

## 4. Classifier（规则，禁 LLM 判路由）

`classify(query, call_site_mode, has_tool_schema, wants_stream) -> RequestProfile`：complexity 规则=长度+对比/推理/多条件/方案/风险词表（复用 `typesafe_router` 的词表风格，独立实现不成环）；mode 由调用点声明（RAG=rag、SSE=rag+stream、Agent=agent+needs_tools 当轮有工具意图）；**不引入任何模型调用**。

## 5. Router（纯函数，不执行请求）

`plan(profile, registry, health_view) -> RoutePlan`，过滤顺序（冻结）：`enabled → 必需 capability → external policy（本版本仅记录，不拦截）→ health/熔断态 → limits（形式校验：上限必须为正；**上下文粗估在 Task 4 execute 前置**——`plan()` 冻结签名无请求体，2026-09-23 评审修订；收口后无候选抛 `NoCapableModelError(stage="context")`）→ priority → cost`。**capability > preference**：priority=100 不得覆盖能力不符。评分=profile.mode 的 priority 降序，同分 cost 低优先；输出 `RoutePlan(primary, fallbacks[], reason_codes[])`。

- reason codes（机器可读，冻结枚举）：`LOCAL_PREFERRED / CAPABILITY_MATCH / HIGHER_PRIORITY / LOWER_COST / PRIMARY_UNHEALTHY / CIRCUIT_OPEN / FALLBACK_AFTER_TIMEOUT / PROVIDER_CONFIG_FAILED / NO_CAPABLE_MODEL`。
- **D2 零候选**：抛 `NoCapableModelError`；Agent 调用方捕获并降级 `agent_local_fast_path`（无工具直执行企业检索），**不得 500**；RAG/chat 链（needs_tools=false）理论永不触发，仍设兜底=显式 503 业务错误文案。
- 验收线：`plan()` 纯内存 P95 ≤ 10ms（本地 benchmark 直测）。

## 6. Provider 层（normalize + probe）

`provider.py` 两实现 + `health.py` 语义的 probe 收编（D6：`probe_ollama/probe_llm` 迁入，`/api/system/status`、SystemView 消费形状不变）：

- 统一动词：`complete(LLMRequest) -> LLMResponse`、`stream(LLMRequest) -> Iterator[LLMChunk]`；`OpenAICompat`（`/chat/completions`）与 `OllamaNative`（`/api/chat`）差异全部在此层吸收。
- **Tools 标准化**（第五段冻结）：两侧 tool_calls → `ToolCall(id,name,arguments dict)`；`LLMResponse(content, tool_calls, finish_reason, usage)`；Agent 只认内部模型。
- usage 提取：OpenAI `usage.{prompt_tokens,completion_tokens}`；Ollama `prompt_eval_count/eval_count`（缺失记 0 并标 estimated）。
- **错误三分类**（`errors.py`，冻结映射）：
  - retryable：408/429/500/502/503/504、ConnectTimeout/ReadTimeout/ConnectionError、Ollama 模型加载失败（`model_unavailable`，含 500+"alloc/failed to load"形态）→ 当前模型重试 1 次（retry budget），预算内仍败 → fallback；
  - non-retryable：400/404/422 → 不换当前 provider 重试，**允许**fallback 下一候选；401/403 → 标 `PROVIDER_CONFIG_FAILED`，本次请求内跳过该 provider 其余候选（不同 provider 且凭据独立者仍可用）；
  - hard terminal：请求体超限/工具 schema 非法/策略拒绝/能力不支持 → `NO_FALLBACK`，直接返回业务错误。
- 每 attempt 超时 = `min(model_timeout(默认 20s), budget.remaining())`；全局预算 `LLM_TOTAL_BUDGET_MS` 默认 30000（**总预算制**：三 attempt 共享 30s，不做每模型相加）。

## 7. FallbackExecutor + 熔断 + 流式 commit

- 执行链：`for candidate in [primary]+fallbacks`：breaker `allow()` 预检（**D4**：`CircuitBreaker(name=provider)`，半开名额与陈旧回执沿用 `resilience.py` 既有文档化语义；OPEN 时计 `CIRCUIT_OPEN` reason 并直接下一候选）→ attempt → `record(ok)`；成功返回 `RouteAttemptResult(selected, fallback_index, attempts[])`。
- **流式 commit 边界（第四段冻结）**：首个有效内容 token 发出前失败 = 可安全 fallback（用户无感）；此后失败 = **禁止换模型**，输出现行 SSE 事件词汇 `error` + `done`（D5：payload 仅增量字段 `stream_committed:true`、`error_type`；不新增事件类型）。该矩阵（pre-commit fail→切换 / post-commit fail→不切换）必须有自动化测试。
- `LLM_ROUTER_ENABLED`（默认 true）：false=三链路走原 legacy 分支（仅 V2.3 应急；契约测试双路绿）。

## 8. Usage 记账与观测（D3）

表 `llm_request_logs` 建在现有 `data/conversations.db`（`usage.py` 自建表与写连接；**记账失败 fail-open**：吞异常入 warning 日志，绝不影响生成）。字段（冻结）：`id, trace_id, request_id, route_mode, route_reason(码数组 JSON), provider, model, fallback_index, input_tokens, output_tokens, total_tokens, ttft_ms, latency_ms, estimated_cost, currency, success, error_type, status_code, created_at`。**永不存储**：prompt、完整 context、reasoning/CoT、API key、Authorization。prompt 采样如需，另立 debug/audit 策略，禁止入本表。

观测出口（白名单、聚合 only）：`/api/system/status` 增 `llm: {requests_5m, success_rate, fallback_rate, p95_latency_ms, providers:{name:{healthy}}}`（`fallback_rate` 从 usage 表聚合，不另建计数器，D4；禁泄 key/base url/prompt/异常栈/用户问题）；trace 增 `model_route` 对象（mode/requirements/primary/fallbacks/selected_reason codes/attempts[{model,result,error_type}] + stage/selected_index/context_dropped）——前端 TraceView 以 detail 文本消费即可，控制台 UI 留 V2.6。

### 8.1 §8 回写（2026-09-24，Task 5 评审 I-4 与裁定 C；precedent = §5 limits 的 Task 3 修订）

上面两段的口径有四处不完整，按本小节执行。19 列的字段清单与「永不存储」清单**不动**。

1. **`error_type` 的值域**：§8 不枚举取值，Task 2 移交项冻的是「provider 归类如何落库」= `error.kind`（`retryable`/`config`/`hard`/`model_unavailable`，必要时 `:no_fallback` / `:状态码` 后缀）。该口径不覆盖**没有 provider 归类**的行，故账本侧另立两枚哨兵：`client_aborted`（见第 2 条）与 `unknown`（不合任何形状即整值替换成它，绝不留原文）。两者都**不许**掺 provider 的 body 摘要或 `str(exc)`。
2. **`client_aborted` 判据（收窄后）**：`success is False` ∧ `error_type` 缺失 ∧ **有交付事实**（`fallback_index >= 0` ∧ `input+output tokens > 0`）⇒ `client_aborted`；其余 `success=False ∧ error_type` 缺失 ⇒ `unknown`。理由：消费方在 commit 之后离开是真实等待而非模型故障；而「生产者漏填归类」绝不能从**缺席**被反推成关页，否则一次全链失败会在 status 页读成「1.0 的关页 + 零失败样本」。这道闸**对两个来源一视同仁**：链上显式写进来的 `client_aborted` 若没有交付事实，同样退回 `unknown`；`success=True` 的行也不许携带这枚哨兵（`scored_rows` 按 `error_type` 剔行，一枚贴在成功行上的 `client_aborted` 会把一次真实成功从分子与分母一起请走）。两枚哨兵是**账本的产物**，三条链只允许写 provider 的 `kind`（或 `kind:status`）。
3. **`llm` 块的 additive 键**：除上述五键外允许 `aborted_rate` 与 `breaker:{name:{state}}`。`success_rate` 的分子与分母**同时**剔除 `client_aborted`（`p95_latency_ms` 不剔除：它量的是用户等了多久），关页率因此只能从 `aborted_rate` 读，不许被折进成功率。`breaker` 与 `providers.*.healthy` 必须物理分离——`healthy` 唯一数据源是 probe + 60s 缓存（D4），熔断态不得渗透进去。两枚键同样逐枚过白名单，禁前缀放行。
4. **`model_route` 的 `stage`/`selected_index`/`context_dropped`**：原六键清单与 §5（trace 需「带 stage + 被剔计数」）互相矛盾，而 19 列里没有这三枚事实的位置；丢弃执行面事实比给 trace 对象补三枚键更坏，故按上划线后的九键执行。**唯一生产者**仍是 `app.llm.usage.model_route_trace()`，**唯一挂载点**仍是 `app.agent_trace.attach_model_route()`；同一份事实不许在第二处构造（评审 C 裁定，据此删除 Task 5 一度新增的 `app.llm.model_route_payload()`）。

## 9. 三条链路迁移

`rag.py::generate_answer` → profile(mode=rag) → `router.complete`；`conversation_agent.py` → mode=rag+stream，chunk 映射现行 SSE 事件 + commit 跟踪；`agent.py` → mode=agent，工具轮用 `LLMResponse.tool_calls`，`NoCapableModelError` 走 D2 降级；`current_model_name()` 改由 router 解析（响应 model 字段来自实际选中模型）；既有响应结构对外不变（additive only）。

### 9.1 §9 回写（2026-09-24，Task 7 独立评审 I-3 裁定；precedent = §8.1 的 Task 5 修订）

对话链的两条腿在 `LLM_ROUTER_ENABLED=false` 下**不对称**：非流式腿（`token_sink is None`）保留原调用 `agent._ollama_chat(messages, [])`；**流式腿没有 legacy 形态可留**——它的原实现 `app/native_stream.py` 已由 Task 7 退役，把 `/api/chat` + `httpx.stream` 内联回业务文件即违反 D6 与矩阵 #19。因此这一腿的 #18 对照面从「旗标关掉走旧代码」改为「**报文与退役模块逐字等价**」（`stream=True` / `tools=[]` / `think` / `keep_alive` / `options{temperature=0.2, num_predict}`），且关掉旗标时该腿**仍走路由**（`timings["native_stream"]` 仍为 `true`）。后果写清：`LLM_ROUTER_ENABLED=false` 只是**非流式路径**的应急回退，**不覆盖对话链流式腿与 agent 链的工具轮**；V2.3 验收文档必须点名这一缩小，运维不得把它当作「SSE 侧模型故障的止血开关」。

同一处口径修正：对话链**两条腿的现网采样温度都是 0.2**（`native_stream.py` 的 `options.temperature` 与 `agent._ollama_chat`），0.1 只属于 `app/rag.py` 那条链的 `RAG_LEGACY_TEMPERATURE`；给对话链套 0.1 属于未声明的行为变更，本链一律用自己的命名常量（Task 7 评审第 5 项验收口径）。

**Task 8 补正（2026-09-24）**：上面那句「不覆盖……agent 链的工具轮」不准确——**agent 链两条腿都有 legacy 形态**（同一段 httpx 报文，含 `tools` 键）。正确表述是：agent 链的 #18 对照面完整存在，但关掉旗标会退回到「无条件把 `tools` 发给不支持工具的本地模型」这一**现网行为**；也就是说应急含义是「回到未路由的世界」，**不是**「让工具轮可用」。

### 9.2 SSE `done.model_used` 契约（2026-09-25，Task 11 修复 I-11-2 的响应面闭环；用户裁定）

I-11-2 要求三事实一致（响应面 / 账本 / trace 的**实际**模型名）。流式腿此前响应面**没有**任何模型字段
⇒ 若不挂键，`route_out` 盒子在这条腿上就不可从外部验证。因此本版唯一一处 additive 键集合变化锁在
`/api/query/stream` 的 `done` 事件：`model_used?: "<actual model>"`。契约六条，逐条必须是行为断言而非注释：

1. **只记实际模型**：`model_used = LLMResponse.model`（生效模型名，M2 口径），**绝不**取 `RoutePlan.primary`。
2. **只在实际模型已知时出现**：零候选（`NoCapableModelError`）、fast-path、provider 回显空串 ⇒
   **键不存在**。不许 `null`、不许 `""`、更不许拿计划面名字补位。
3. **pre-commit fallback**（`planned=ornith` 失败、`phi3` 成功）⇒ `done.model_used = phi3:mini`。
4. **不扩散**：`token` / `error` 事件**不加** `model_used`（`token` 只带 `{"text": ...}`）。本版键集合变化只有 `done` 这一处。
5. **legacy 兼容**：`LLM_ROUTER_ENABLED=false` 的有 key / 无 key 两形，响应面与迁移前**逐字相等**；
   不得为统一字段而改 legacy payload。

**作用域限定（避免被误读成 D5）**：`/api/query/stream` 这条腿是**缓冲生成**——`generate_answer` 整段生成完
再按 14 字符切片回放成 `token` 事件，**没有 commit 边界**。所以「post-commit 失败时 `done.model_used` 保持
已 commit 的模型」这条**不落在本端点**；它约束的是对话链 `conversation_stream_routes.py` 那条真流式腿，
而那一腿本版**不引入** `model_used` 键（它的模型经会话响应面的 `model_used` 暴露，形状由 Task 7 钉死）。

事实链的期望形状（fallback 场景）：`RoutePlan.primary = ornith-1.5:9b-text`（计划事实）／
`trace.success_attempt.model = phi3:mini`（执行事实）／`llm_request_logs.model = phi3:mini`（账本事实）／
`done.model_used = phi3:mini`（响应事实）。四者各记各的，**不互相覆盖**。

## 10. 验收矩阵（19+1，全 P0 除非注明）

| # | 用例 | 方法 | 预期 |
| --- | --- | --- | --- |
| 1 | OpenAI-compat 成功 | httpx MockTransport | PASS |
| 2 | Ollama 成功 | 同上 | PASS |
| 3 | 429→retry | 同上 | 重试后成功 |
| 4 | 500→fallback | 同上 | 第二候选成功，fallback_index=1 |
| 5 | timeout→fallback | 同上 | 同上且 reason 含 FALLBACK_AFTER_TIMEOUT |
| 6 | 400 | 同上 | 不重试当前；允许 fallback |
| 7 | 401 | 同上 | 不重试当前 provider；标 PROVIDER_CONFIG_FAILED |
| 8 | malformed JSON | 同上 | 归类正确（非 retryable 崩溃） |
| 9 | stream 成功 | 同上 | SSE 序完整 |
| 10 | pre-token 流失败 | 同上 | 静默换模型，用户无感 |
| 11 | post-token 流失败 | 同上 | 不切模型，error+done+stream_committed |
| 12 | tool call OpenAI | 同上 | ToolCall 标准化 |
| 13 | tool call Ollama | 同上 | ToolCall 标准化 |
| 14 | Router 延迟 | 本地 benchmark | P95≤10ms |
| 15 | usage 落库 | SQLite 断言 | 字段全、无禁存项 |
| 16 | status 聚合 | API 测试 | llm 块形状 |
| 17 | trace route 解释 | 集成 | model_route 完整 |
| 18 | legacy 回退 | flag=false | 三链原行为；**对话链仅非流式腿有 legacy 形态，流式腿以「报文与退役模块逐字等价」为准（见 §9.1）** |
| 19 | 单一出口静态扫描 | 契约测试 | provider.py 外零命中 |
| **P0** | **REAL-LLM-FAILOVER-001**：primary=ornith-1.5:9b-text（真实加载失败）→fallback=phi3:mini 真实成功 | 本机 Ollama | 10 断言：primary 真被调用/失败归类 model_unavailable/fallback 被调/phi3 有效回答/fallback_index=1/trace_id 全链一致/model_route 两 attempt/usage 落库/零 prompt 入库/API 200 |

云厂商（DeepSeek/Qwen/OpenAI 实连）= `PENDING_EXTERNAL`，不计 PASS/FAIL；key 到位后仅需新增 LIVE-CLOUD-* 用例不改架构。回归基线：当前 407 passed 只增不减；前端 build PASS；密钥扫描 0。

**DoD（逐项绿才可判 V2.3 通过）**：Registry / Capability Routing / Router P95 / 两适配器 / 非流式 / 流式 / Tool Calls / Retry / Fallback / Circuit Breaker / Timeout Budget / Usage Accounting / Trace Explainability / Status Observability / 三链路迁移 / Mock 协议组 / 真实 failover / Prompt·Reasoning 存储=0 / P0 回归=0。

## 11. 实施顺序（冻结链）

models/registry → provider+normalize+probe → classifier/router → fallback+resilience → usage/观测 → RAG 迁移 → SSE 迁移 → Agent 迁移 → mock 协议契约 → REAL-LLM-FAILOVER-001 → 全量回归 + Enterprise Quality Gate 记录。

## 12. 配置键（Settings + .env.example）

`llm_router_enabled=true`、`llm_registry_file=config/llm_registry.json`、`llm_total_budget_ms=30000(5000..120000)`、`llm_model_timeout_seconds=20`、`llm_retry_per_model=1`、`llm_breaker_enabled=true`（+window/ratio/open/probes 四键与 typesafe 同构默认）、`{DEEPSEEK,QWEN}_API_KEY/_BASE_URL` 占位空值。

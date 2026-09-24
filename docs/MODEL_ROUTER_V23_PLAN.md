# Model Router V2.3 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development — 每任务新实现代理 + 独立评审 + 修复轮 + 定点复审。步骤 checkbox 跟踪。**本工作流不执行 git 写操作**（rag 仓库 HEAD 陈旧、84+ 文件未提交属用户决定）；每任务收尾 = 定向测试绿 + 全套件 ≥407 passed / 0 failed 只增不减。

**Goal:** 三条生成链路（RAG 非流式 / SSE 流式 / Agent 工具回路）+ `native_stream.py` 全部收编进统一 `backend/app/llm/` Router：注册表、规则路由、failover、逐 provider 熔断、30s 总预算、usage 记账、可解释 trace。

**Architecture:** 冻结调用链 `业务 → llm.complete/stream → classifier → router.plan → fallback.execute → provider(唯一出口)`；spec 为权威（`docs/MODEL_ROUTER_V23_DESIGN.md`，其九段 + D1–D6 + 19+1 矩阵 + DoD 优先于实现便利）。

**Tech Stack:** FastAPI + pydantic v2 + httpx（MockTransport 协议级测试）+ SQLite(conversations.db) + 复用 `app/resilience.py`；无新依赖。

**Spec:** `E:\xiangmu\rag\docs\MODEL_ROUTER_V23_DESIGN.md`（执行时两文档都读）

## Global Constraints

- D1：凭据 env 约定 `{PROVIDER大写}_API_KEY/_BASE_URL/_MODEL_OVERRIDE`；ollama 用 `OLLAMA_BASE_URL/OLLAMA_MODEL`；内置 `openai` 条目复用 `OPENAI_*`；registry JSON **零 secret**（出现 key/base_url 字段即评审红线）。
- D2：零候选 `NoCapableModelError`；Agent 捕获→`agent_local_fast_path`；任何链不得因此 500/503 给用户裸错。
- D3：`llm_request_logs` 入 `data/conversations.db`；写失败 fail-open（warning 日志）；**永不存** prompt/context/reasoning/key/Authorization（反测试钉）。
- D4：熔断按 provider（`CircuitBreaker(name=provider)`）；OPEN 时 reason 记 `CIRCUIT_OPEN`、不标 degraded；`fallback_rate` 从 usage 表聚合。
- D5：SSE 事件词汇不变；commit 前可换模型，commit 后 `error+done` + payload 增量 `stream_committed:true/error_type`。
- D6：单一出口静态契约——`app/llm/provider.py` 之外禁止出现 `/api/chat`、`/v1/chat/completions`、`OLLAMA_BASE_URL`、`_API_KEY` 直连、指向 LLM 的 httpx；probe 迁入 provider，SystemView/status 消费形状不变。
- `LLM_ROUTER_ENABLED=false` = 三链 legacy 原行为（双路契约测试绿；legacy 下一稳定版删除，本版保留）。（**Task 7 评审修订**：对话链流式腿因 `native_stream.py` 退役而无 legacy 形态，口径见 DESIGN §9.1。）
- 过滤顺序与 capability>preference 冻结（spec §5）；总预算 `min(model_timeout, budget.remaining())`，三 attempt 共享 30000ms，禁相加。
- reason codes 枚举冻结：`LOCAL_PREFERRED/CAPABILITY_MATCH/HIGHER_PRIORITY/LOWER_COST/PRIMARY_UNHEALTHY/CIRCUIT_OPEN/FALLBACK_AFTER_TIMEOUT/PROVIDER_CONFIG_FAILED/NO_CAPABLE_MODEL`（机器码入 usage.route_reason 与 trace）。
- 云厂商无 key：验收记 `PENDING_EXTERNAL`（非 PASS 非 FAIL）；对外响应结构 additive-only；前端文案遵循 `docs/UI_COPY_GLOSSARY.md`。
- 测试在 `E:\xiangmu\rag\backend`：`python -m pytest tests -q`。

## 文件结构

见 spec §2/§3。测试新建：`tests/test_model_router_v23_contract.py`（注册表/路由/fallback/mock 矩阵）、`tests/test_llm_usage_contract.py`（记账/禁存项/聚合）、`tests/test_llm_egress_guard.py`（单一出口扫描）、迁移各带既有文件适配。

---

### Task 1: models + registry + 配置键（TDD）

**Files:** Create `app/llm/__init__.py`(暂仅 re-export 占位函数)、`app/llm/models.py`、`app/llm/registry.py`、`backend/config/llm_registry.json`、测试类①；Modify `app/config.py`（§12 键：`llm_router_enabled=True`、`llm_registry_file="config/llm_registry.json"`、`llm_total_budget_ms=30000(ge5000 le120000)`、`llm_model_timeout_seconds=20`、`llm_retry_per_model=1(ge0 le2)`、`llm_breaker_enabled=True`、`llm_breaker_window=20(ge8)`、`llm_breaker_failure_ratio=0.30`、`llm_breaker_open_seconds=60`、`llm_breaker_half_open_probes=3`、`deepseek_api_key/qwen_api_key: SecretStr=""`、`deepseek_base_url="https://api.deepseek.com/v1"`、`qwen_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"`）、`backend/.env.example`。

**Interfaces（冻结）:**
- `ModelCapabilities(chat,rag,tools,stream,reasoning: bool)`；`ModelPricing(input_per_1m, output_per_1m: float, currency="USD")`；`ModelLimits(context_tokens=8192, max_output_tokens=2048)`；`ModelDefinition(id,provider,model,enabled,external,capabilities,priority: dict[str,int],limits,pricing)`（pydantic）。
- `@dataclass(frozen=True) RequestProfile(mode: Literal["chat","rag","agent"], complexity: Literal["low","medium","high"], needs_tools: bool, needs_stream: bool, needs_reasoning: bool=False)`；`RouteCandidate(model: ModelDefinition, score: int, reason_codes: tuple[str,...])`；`RoutePlan(primary: RouteCandidate, fallbacks: tuple[RouteCandidate,...], reason_codes: tuple[str,...])`。
- `LLMRequest(messages: list[dict], temperature: float=0.2, tools: list[dict]=[], num_predict: int|None=None, think: bool|None=None, keep_alive: str|None=None)`；`ToolCall(id,name,arguments: dict)`；`LLMResponse(content:str, tool_calls: tuple[ToolCall,...], finish_reason:str, model:str, provider:str, input_tokens:int, output_tokens:int, latency_ms:float)`；`LLMChunk(text:str, finish: bool=False, usage: dict|None=None)`；`UsageRecord`（§8 字段镜像，dataclass）。
- `load_registry(path: str) -> Registry`（`Registry(models: tuple[ModelDefinition,...])` + `get(id)`）；校验：重复 id、priority 键 ⊆ {chat,rag,tools}、capabilities 至少一项 true、未知顶层键 forbid → 违规 `RegistryError(ValueError)`；`provider_credentials(model) -> ProviderCredentials(base_url: str, api_key: str)` 按 D1 env 解析（ollama→base=OLLAMA_BASE_URL、key=""；openai→OPENAI_*；其余大写前缀）；`get_registry()/reset_registry()`；`warmup()`（enabled 时加载一次，异常上抛）。默认 JSON：spec §3 列出的 5 条目（ornith priority 100/100/0、phi3 80/80/0、openai/deepseek/qwen tools=true，enabled：openai=`bool(OPENAI_API_KEY)` 在代码里动态判定，deepseek/qwen=false）。

Steps：红测试（加载/校验/凭据解析/warmup fail-fast 四组 ≥10 例，`Registry(_env_file=None)+mock.patch.dict(os.environ)` 隔离法沿用 TypeSafeV2 Task2）→ 实现 → 绿 → 全套件 ≥417。

### Task 2: errors + normalize + provider（唯一出口成型）

**Files:** Create `app/llm/errors.py`、`normalize.py`、`provider.py`、`health.py`；测试类②（MockTransport）。

**Interfaces:**
- `errors.py`：`class LLMError(Exception): kind: Literal["retryable","config","hard","model_unavailable"]; status_code:int|None`；`classify(status:int, body_text:str) -> LLMError|None`（408/429/500/502/503/504→retryable；body 含 `alloc|failed to load|model not found|no such model`→model_unavailable(亦走 retryable 路径但 kind 独立)；401/403→config；400/404/422→hard_retryable_no(=non-retryable 可 fallback)；`payload_too_large|invalid tool schema|unsupported`→hard_terminal NO_FALLBACK）；`from_exception(exc)`（ConnectTimeout/ReadTimeout/ConnectionError→retryable；HTTPStatusError→classify(status)）。
- `normalize.py`：`openai_payload(req, model)` / `parse_openai_response(data, model, provider, latency)` / `parse_openai_tool_calls` / `ollama_payload(req, model)`（think/keep_alive/options 按 `agent.py:47-78` 现有形状平移）/ `parse_ollama_response`（message+tool_calls+prompt_eval_count）/ `openai_stream_lines(resp)->Iterator[LLMChunk]`（data: [DONE] 终止、delta.content、最后 usage 块）/ `ollama_stream_lines(resp)`（逐行 JSON、`message.content`、done+eval_count）。
- `health.py`：probe 收编（D6）——`probe_ollama/probe_llm` 从 rag.py 迁入（签名不变），`knowledge_os.py` 改 import；`provider_health_view(registry) -> Mapping[provider, {"healthy":bool}]`（60s 缓存）供 router 与 status 聚合消费。
- `provider.py`：`complete(model: ModelDefinition, req: LLMRequest, timeout: float) -> LLMResponse`、`stream(model, req, timeout) -> Iterator[LLMChunk]`（内部按 `model.provider` 选适配器 dict `PROVIDERS`）；未知 provider→hard_terminal；httpx 客户端**仅此处构造**（health.py 的 probe 亦经此层统一发请求）；`native_stream.py` 本任务**不动**（Task 7 迁移后其调用方消失，再于 Task 7 删除文件）。

Steps：错误分类表逐码参数化测试、Ollama/OpenAI complete/stream 报文级 Mock 测试（含 tool_calls 字符串参数→dict、usage 缺失记 0+estimated 旗标、`[DONE]`、中文 UTF-8 行拆包）、probe 迁移引用点全改 + `test_runtime_metadata_contract` 等既有钉不降强度 → 绿。

### Task 3: classifier + router（纯函数）

**Files:** Create `app/llm/classifier.py`、`router.py`；测试类③。

**Interfaces:** `classify(query:str, *, mode, needs_tools=False, needs_stream=False) -> RequestProfile`（complexity：len≥60 或 对比/为什么/方案/风险/多条件词→high；有连接的多约束→medium；else low——词表模块常量+注释）；`plan(profile, registry, health_view: Mapping[str, dict]) -> RoutePlan`：过滤顺序 enabled→caps（chat 恒需；mode 对应 caps；needs_tools→tools；needs_stream→stream）→ external policy（V2.3 仅透传旗标）→ health（provider healthy ∧ not circuit_open，全灭时降级为"忽略 health 但记 PRIMARY_UNHEALTHY/CIRCUIT_OPEN"还是抛 NoCapable？**冻结：健康全灭→仍抛 NoCapableModelError，由 fallback 的 legacy 分支或业务降级承接**——评审确认与 D2 一致）→ limits（context 粗估 len(messages) 字符/2，超限候选剔除）→ priority[mode] 降序 → 同分 pricing 低优；reason codes 全程记录；`profile.mode` 在 priority 缺失键=0 分剔除（tools priority 0 → agent 模式剔除，与 capability 双保险）。P95≤10ms：60 候选×200 次循环计时测试。

### Task 4: fallback executor（重试/熔断/预算/流式 commit）

**Files:** Create `app/llm/fallback.py`；`__init__.py` 填公共 `complete()/stream()`（含 `router_enabled()`、classifier→plan→execute→usage.log 编排与 mode 参数）；测试类④。

**Interfaces:** `run_complete(profile, req, *, trace_id, request_id) -> FallbackResult(response: LLMResponse, attempts: tuple[Attempt,...], selected_index:int, budget_ms:float)`；`run_stream(...) -> StreamSession`：`session.chunks()` 首 chunk 前异常→内部换下一候选重开请求（对用户无感），yield 出第一个 chunk 即 `committed=True`；此后异常→上抛 `StreamInterrupted(partial_text)`，**不再切模型**；`session.finish()` 汇总 usage/ttft。Attempt(model,provider,result:success|failed|skipped_circuit,error_type,latency_ms)。重试=`llm_retry_per_model` 次当前模型（retryable kind；model_unavailable 不重试当前——换模型更快，冻结）；401/403→该 provider 其余候选本次跳过 + `PROVIDER_CONFIG_FAILED`；hard terminal→立即上抛。breaker：`allow()` False→Attempt(skipped_circuit)+reason，不 record；每 attempt 后 `record(ok)`。预算：`TimeoutBudget(soft_ms=budget*0.7, hard_ms=llm_total_budget_ms)`；每 attempt `timeout=min(llm_model_timeout_seconds, remaining/1000)`；exhausted→停止并上抛聚合错误（业务层兜底文案不变）。

Mock 矩阵测试：spec §10 表 #3–#8、#10、#11（pre-commit 切换/post-commit 不切）+ legacy flag off。

### Task 5: usage + 观测（表/聚合/status/trace）

**Files:** Create `app/llm/usage.py`；Modify `app/knowledge_os.py`（status 增 `"llm"` 块 + warmup 挂 lifespan 与 identity.warmup 并排）、`app/security.py`（`llm` 块字段白名单常量）、`app/agent_trace.py`/`conversation_agent.py`/`agent.py` 的 trace 组装点注入 `model_route`（additive）；测试类⑤。

**Interfaces:** `init_usage_db()`（CREATE TABLE IF NOT EXISTS，字段=spec §8 冻结 19 列）；`log_usage(UsageRecord)`（try/except fail-open + `logging.warning`）；`aggregate_status(window_s=300)`→`{requests_5m, success_rate, fallback_rate, p95_latency_ms, providers:{name:{healthy}}}`（healthy 来自 provider probes 缓存 60s）；trace `model_route` 结构按 spec §6 示例（机器码）。禁存项反测试：插入含中文 prompt 的请求后 `SELECT * FROM llm_request_logs` 全列扫 prompt 片段 0 命中；status 响应形状等式测试（未知键不外泄）。

> **接口口径以 DESIGN §8.1（2026-09-24 回写）为准**（Task 5 评审 I-4 / 裁定 C 的产物）：上面那行的五键清单已扩为**七键**（另加 `aborted_rate`、`breaker:{name:{state}}`，逐枚过白名单）；`error_type` 值域在 provider 的 `kind`（+`:status`/`:no_fallback`）之外含两枚**账本侧哨兵** `client_aborted`/`unknown`，且交付闸对「推断」与「链上自写」两个来源同样生效；trace `model_route` 是**九键**（六键 + `stage`/`selected_index`/`context_dropped`），**唯一生产者** `usage.model_route_trace()`、**唯一挂载点** `agent_trace.attach_model_route()`。`unknown` 不设新的观测键（与 `success_rate` 完全共线），归因走 `error_type='unknown'` 的库查询 → T9/T11 验收清单。

### Task 6: RAG 迁移

Modify `app/rag.py`：`generate_answer` 的 143–176 双分支 → `llm.complete(profile(mode="rag"), LLMRequest(...), trace_id=None)`；`except LLMError/NoCapableModelError` 沿用现"LLM 不可用回退原文"文案（行为不变）；`current_model_name()` 改经 router 默认候选解析（无 key 时 ollama 模型名不变）；`LLM_ROUTER_ENABLED=false` 保留旧分支原样（if 包裹）；probe 引用改 provider。测试：既有 `test_branding/test_p16/test_typesafe_*` 全绿 + 新用例断言响应 model 字段=RoutePlan primary。

### Task 7: SSE 迁移 + native_stream 退役

Modify `app/conversation_agent.py`：`token_sink is None` 分支→`llm.complete(mode="rag")`；流式分支→`run_stream`（ttft 记录点=首 chunk；`redact_text` 逐 chunk 保留；commit 由 StreamSession 提供；`StreamInterrupted`→现 error/done 事件 + payload `stream_committed:true`）；删除 `from app.native_stream import ollama_chat_stream` 并删除 `app/native_stream.py`（先 grep 全仓零其余引用）；`llm_ms/llm_calls/model_used` 语义不变（model 来自 selected）；legacy flag 分支保留原调用。测试：既有 SSE/stream 契约（`test_p17_streaming_contract` 等）不降强度 + commit 前/后两用例。

### Task 8: Agent 迁移

Modify `app/agent.py`：`_ollama_chat` → 内部改 `llm.complete(mode="agent", needs_tools=bool(tools))`（think/num_predict/keep_alive 经 LLMRequest 透传；返回形状转现行 `message dict` 以最小化循环体 diff）；tool_calls 用 `LLMResponse.tool_calls` 标准化替换 `message.get("tool_calls")` 手写路径（`_tool_arguments` 保留兼容或删除——grep 使用后定）；`NoCapableModelError`→捕获→走 `_local_fast_path` 等价降级（现 local 模式分支复用），trace 记 `NO_CAPABLE_MODEL→fast_path` 注记；legacy flag 分支保留。测试：`test_agent_contracts/test_agent_routing_contracts` 17 例适配不降强度（评审逐条）+ 新 D2 降级用例。

### Task 9: 19+1 矩阵补全 + 单一出口守卫

Create `tests/test_llm_egress_guard.py`（D6 扫描：`rg` 模式集 `/api/chat|/v1/chat/completions|OLLAMA_BASE_URL|_API_KEY|httpx.(post|stream)` 于 `app/`，豁免 provider.py+usage/probes 无调用例外清单以等式钉）；对照 spec §10 表逐项映射到已有测试，缺项补（预计：#9 完整 SSE、#16 providers healthy 形状、#17 trace 断言）。全套件绿。

### Task 10: REAL-LLM-FAILOVER-001（P0 真实验收）

起宿主后端（backend/，env：LLM_ROUTER_ENABLED=true、registry 默认、qdrant 容器在、Ollama 在且 ornith-9b-text 保持未加载态）；跑 1 次真实 `/api/query/stream`：断言 spec §10 P0 十字（primary 404/500 真实发生、kind=model_unavailable、phi3 真实生成中文答案、fallback_index=1、usage 行、API 200、trace model_route attempts=2、prompt 零入库）；数字与日志证据存 task-10 报告段。若 ornith 意外可加载：`docker stop ollama`? 不允许——改用 registry 临时条目 model 改为不存在的 `ornith-1.5:9b-missing`（等效加载失败）并在报告注明等价性。

### Task 11: 全量回归 + 验收记录

`python -m pytest tests -q` 终态、`npm run build`、`docker compose build backend && up -d`（含新 config COPY 已有）、健康冒烟（登录/问答/SSE/status llm 块/TraceView model_route 浏览器走查）、密钥扫描；写 `docs/MODEL_ROUTER_V23_ACCEPTANCE_2026-09-23.md`（DoD 19 项逐项 + 矩阵 20 行 + PENDING_EXTERNAL 三行 + 与 TypeSafe V2 交接的复用件清单）。终审包+台账收口。

---

## 验收线（冻结，摘自 spec）

DoD 19 项全 PASS；矩阵 19 mock/单测 + REAL-LLM-FAILOVER-001 PASS；`P0 Regression=0`；Prompt/Reasoning 存储=0；Router P95≤10ms；407→只增。云条目 `PENDING_EXTERNAL`。

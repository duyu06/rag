# Task 4 报告 — fallback executor（重试/熔断/预算/流式 commit）+ 包级公共 API

状态：**DONE / 绿**。定向 `tests/test_model_router_v23_contract.py` **240 passed / 0 failed**，
345 subtests（本任务前 176 → **+64 例**，全部为测试类④）；全套件 `python -m pytest tests -q`
**647 passed / 0 failed / 839 subtests**（基线 583 → 只增不减，+64 全为本任务用例）。
变异自查 **8/8 killed**（见下表，含任务书点名的 5 发）。

## 交付文件

| 文件 | 行数 | 内容 |
| --- | --- | --- |
| `backend/app/llm/fallback.py` | 900（新建） | `run_complete` / `run_stream` / `StreamSession`、`Attempt` / `FallbackResult` / `StreamSummary`、`AllCandidatesFailedError` / `StreamInterrupted`、逐 provider 熔断单例表 `BREAKERS` + `circuit_breaker()` / `circuit_is_open()` / `reset_circuit_breakers()`、`routing_health_view()`（T3 移交的 `{healthy, circuit_open}` 合成）、上下文收口 `estimate_prompt_tokens()` / `fit_chain_to_context()`、共享状态机 `_Runner`（gate 三段预检 / 预算 / 回执 / 理由码 / attempts） |
| `backend/app/llm/__init__.py` | 387（+~260） | `router_enabled()`、`complete(...)`、`stream(...)`、`log_stream_usage(...)`、usage 接缝 `set_usage_sink()` / `usage_sink()` / `_log_usage()`（fail-open）、内部件 `_request` / `_query_of` / `_plan` / `_usage_from_result` / `_usage_from_failure`；再导出执行器面（`run_complete`/`run_stream`/`FallbackResult`/`Attempt`/`StreamSession`/`StreamSummary`/`StreamInterrupted`/`AllCandidatesFailedError`/`reset_circuit_breakers`），**不**再导出 `provider.complete/stream` |
| `backend/tests/test_model_router_v23_contract.py` | 2636 → 3870（+1234） | 测试类④：`FallbackContractTests`(6) / `ContextGateTests`(5) / `FallbackTransportMatrixTests`(12) / `RetryBudgetTests`(4) / `CircuitBreakerIntegrationTests`(8) / `StreamCommitTests`(16) / `PackageEntryPointTests`(12) / `ModelOverrideEndToEndTests`(1) = **64 例**；新增 `_FallbackFixture`（熔断复位 + 假钟 + stub provider）与 `fb_*` / `s_*` 构造器 |

`native_stream.py`、`rag.py`、`agent.py`、`conversation_agent.py`、`app/resilience.py`、
`app/config.py`、`app/llm/{models,registry,errors,normalize,provider,health,classifier,router}.py`
本任务**零触碰**（改动面严格限于任务书给的三处）。未做任何 git 写操作。

## 红 → 绿证据

1. **红（无实现）**：`ModuleNotFoundError: No module named 'app.llm.fallback'` → 契约文件
   collection error（1 error，0 test 可跑）。测试先写、先红，再落实现。
2. **红（首轮实现后）11 例**，两类根因，都按语义修正而不是放宽断言：
   - `StreamSession` 把 `reason_codes` 定义成 property，`finish()`/`_interrupted()` 里按方法
     调用 ⇒ `TypeError: 'tuple' object is not callable`（实现 bug，改调用点 2 处）；
   - 测试自身口径错：`fb_request()` 忘了传 `messages`（边界用例实际测的是短请求）、
     `selected_index` 按「收口后链」的下标算错两处（config 跳过链里是 2 不是 1）、
     `int(estimate)` 代替 `ceil`（115 上限 vs 114.5 粗估的反向边界）。
3. **上下文边界的取整方向**在报告里落成文字：判据是 `estimated <= context_tokens`
   （**等于上限算装得下**），`estimate` 是 float，所以「恰好装得下」的用例必须用
   `math.ceil(estimated)` 造上限——`int()` 会造出一个必然被剔的假边界。已由
   `test_boundary_is_inclusive_at_the_context_limit` 钉住。

## 测试构成（64 例）

- **FallbackContractTests 6**：`run_complete` / `run_stream` 参数名与 keyword-only、
  `FallbackResult` 前四字段逐字（冻结五字段 + 可加的 `context_dropped`）、`Attempt` 五字段；
  首参双形态（`RoutePlan` 走纯执行、`RequestProfile` 由执行器自行 plan）+ 越界类型 `TypeError`；
  `StreamInterrupted` **不是** `LLMError` 子类且三件套齐、异常消息不含交付文本（D3）；
  `AllCandidatesFailedError` 是 `LLMError` 子类、`kind` 沿用最后一个真实失败、无失败时 `hard`；
  **AST 钉**：`app/llm/__init__.py` 里 `llm_router_enabled` 只出现 1 次且必须在
  `router_enabled()` 函数体内（legacy 旗标不进 llm 包）。
- **ContextGateTests 5**：公式逐字（`sum(len(str(m)))/2`、`CONTEXT_CHARS_PER_TOKEN=2`、空列表 0）；
  边界含等号两向；超长请求先收口再外呼（小上下文候选零次调用）+ `context_dropped=1`；
  收口后为空 ⇒ `stage="context"` 且 `reason_codes == ("NO_CAPABLE_MODEL",)`（**不造新码**）、
  异常文本带被剔计数、零外呼；`run_stream` 同样在**开流时**收口（不消费 chunks 也抛）。
- **FallbackTransportMatrixTests 12**（#3–#8 用真 `MockTransport`，归类来自真实状态码/body）：
  #3 429→同模型重试后成功（2 次 HTTP、`attempts=[failed,success]`、selected_index=0）；
  #4 500+"failed to load"→`model_unavailable`→第二候选（断言两次请求体 `model` 字段，
  fallback_index=1）；#5 客户端超时→换候选 + `FALLBACK_AFTER_TIMEOUT`，并核
  「计划码在前、执行期码在后」的合并序；#6 400（给了 retry=1 也不许用）→不重试当前、可换候选；
  #7 401（stub 版三候选跨 provider：同 provider 候选**零外呼**、`PROVIDER_CONFIG_FAILED`、
  被跳过的候选不产 Attempt）+ 401 的 transport 版（聚合错误 `kind=config`）；
  #8 200+畸形 JSON → `hard`（不崩、不重试当前）→ 换候选成功；
  硬终态 `no_fallback` → **原异常对象** `assertIs` 上抛且下一候选未被调用；
  预算收缩（假钟每次外呼 +11s ⇒ timeout 逐次 20.0/19.0/8.0，第 4 次不发生，
  `budget_exhausted=True` + 3 条 attempts + 消息含「预算耗尽」）；
  timeout 封顶两向（预算富余=20.0；`llm_total_budget_ms=5000` ⇒ 5.0）；
  全链皆败聚合（attempts 附带、kind/`status_code` 归因、消息不含请求内容）；
  `FALLBACK_AFTER_TIMEOUT` 判据的 5 形态单测（真超时/408 算，连接失败/500/400 不算）。
- **RetryBudgetTests 4**：`llm_retry_per_model` 0/1/2 ⇒ 同模型真实调用数 1/2/3（逐值 subTest）；
  `model_unavailable` 给了 2 次额度也只调用一次就换；`config`/`hard` 同样不重试当前（逐 kind）；
  重试**共享**预算（三次 attempt 的 timeout 20.0/18.0/6.0 逐次收缩）。
- **CircuitBreakerIntegrationTests 8**：每 provider 单例（同对象、按 provider 命名、异 provider 异实例）；
  OPEN ⇒ `Attempt(skipped_circuit, error_type=None, latency=0.0)` + `CIRCUIT_OPEN` + 零外呼；
  被跳过的候选不写进 breaker（迟到回执按 `resilience.py` 的要求丢弃，state 仍 open）；
  D4 两面：`routing_health_view` 的 `{healthy:True, circuit_open:True}`（OPEN **不**标 degraded）
  与探针 unhealthy 并存时两键独立；`llm_breaker_enabled=false` 旁路（OPEN 也外呼、
  `circuit_breaker()` 返回 None、`circuit_is_open()` 返回 False、无 `CIRCUIT_OPEN`）；
  **回执表逐 kind**（注入记录型 breaker）：retryable/model_unavailable/config ⇒ False、
  `hard`+状态码 ⇒ True、无状态码的 hard（`from_exception(ValueError)`）⇒ False、成功 ⇒ True；
  半开名额归还：`half_open_probes=1` 的 OPEN→HALF_OPEN（用 `CircuitBreaker(clock=假钟)` 公开参数）
  ⇒ hard+400 后第二个候选仍被放行（若 hard 不回执，名额泄漏 ⇒ 自己把自己闸掉）；
  `test_success_records_a_positive_receipt`。
- **StreamCommitTests 16**（全部生成器 fake，零真网络）：happy path（内容块序、committed、
  ttft=首个内容块时刻、`finish()` 全字段、model_id/provider_name）；空文本块不提交且被扣住
  （ttft 随空块推进 1500ms）；**#10 pre-commit 静默换模型**（含「开流即抛」与「迭代中抛」两种、
  attempts 逐次留痕、用户只见第二个模型的字）；流式 config 跳同 provider；
  **#11 post-commit 不换模型**（retry=2 也只 1 次调用、第二候选零调用、`partial_text`/
  `selected_index`/`error_type`/`model_id` 齐、committed True）+ post-commit config 同样终止；
  usage 只取成功者（失败轮的 999/999 被丢弃）；usage 缺失 ⇒ 全 0 + `estimated=True`；
  全候选 pre-commit 皆败 ⇒ 聚合异常且 `finish()` 仍可调用（response_text None、committed False、
  completed False、selected_index -1、error_type 有值）；干净空流是**成功**不是失败（不二次外呼）；
  流式侧 breaker OPEN 跳过 + `skipped_circuit` attempt；流式预算收缩；
  会话单次消费（`chunks()` 二次 ⇒ RuntimeError、未消费就 `finish()` ⇒ RuntimeError）；
  `chunks`/`finish` 签名与只读观测面（budget_ms/context_dropped/partial_text/selected_candidate）。
- **PackageEntryPointTests 12**：`router_enabled()` 真假两态且是函数；`complete()` 端到端编排
  （classify→plan→run，理由码合并序）；六个请求旋钮逐个落进 `LLMRequest` +
  `_query_of` 只看最后一条消息；给 profile 时**不**调 classify（mode 仍取调用点声明）；
  `stream()` 默认 `needs_stream=True`（高分但不会流的条目不入选）而 `complete()` 放宽该要求
  （同一条目反居 primary）；**D2 透传**：出厂注册表无 key 的 agent 模式 ⇒
  `NoCapableModelError(stage="capability")`、零外呼、零记账（fast-path 常驻主干）；
  usage 行字段逐项（成功行：trace/request/mode/provider/model/fallback_index/total_tokens/
  latency=全链之和）；失败行（`success=False`、`error_type=kind`、`status_code`、
  `fallback_index=-1`）且异常原样上抛；sink 抛异常 ⇒ fail-open 不影响生成；
  T5 接缝两面（无 sink 时惰性解析 `app.llm.usage.log_usage`，模块不存在时静默跳过）；
  `log_stream_usage()` 折叠 `StreamSummary`；包面再导出的**同一对象**等式。
- **ModelOverrideEndToEndTests 1**：`OPENAI_MODEL_OVERRIDE` 经 `run_complete` 真
  MockTransport 端到端——请求体 `model` 用别名、`response.model` 指向别名、attribution 到
  provider（Task 1 移交项在整条链上的落点）。

## 变异自查（8 发，全部被杀；逐发还原后 `diff` 确认零残留 + 240 例全绿）

| # | 变异 | 结果 | 被哪条杀死 |
| --- | --- | --- | --- |
| M1 | commit 后也换模型（删 `if self.committed: raise _interrupted`） | **2 failed** | `test_matrix_11_post_commit_failure_never_switches_model`、`test_post_commit_config_failure_also_stops_the_chain` |
| M2 | 熔断旁路失效（`llm_breaker_enabled=false` 仍建/用 breaker） | **1 failed** | `test_breaker_disabled_bypasses_gate_entirely` |
| M3 | config 跳过跨 provider 泄漏（`if self.config_failed:` 而非按 provider） | **2 failed** | `test_matrix_7_401_...`、`test_config_failure_in_stream_skips_the_rest_of_that_provider` |
| M4 | 重试计数下限变 1（`max(1, retry)`） | **1 failed**（subTest retry=0） | `test_retry_count_follows_the_setting_exactly` |
| M5 | 预算不收缩（timeout 恒为 `llm_model_timeout_seconds`） | **4 failed** | 非流式/流式预算收缩、重试共享预算、封顶两向 四条全红 |
| M6 | 去掉上下文收口（候选链直接放行） | **4 failed** | 边界两向、被剔候选零外呼、`stage="context"` 抛点、流式开流收口 |
| M7 | 空文本块也算「内容」并提前提交 | **3 failed** | `test_leading_non_content_chunks_...`、#10、usage 去重 |
| M8 | `stream()` 的 `needs_stream` 默认改 False（放宽能力要求） | **1 failed** | `test_stream_requires_stream_capability_by_default` |

任务书点名的 5 项（commit 后换模型 / 熔断旁路 / config 跨 provider / 重试计数 / 预算不收缩）
= M1–M5 全覆盖，另加 3 发覆盖收口、提交点语义与入口默认值。

## 偏离与自裁决（brief 之外，均已在代码注释里落文）

1. **`run_complete`/`run_stream` 首参支持两形态**（`RoutePlan` 或 `RequestProfile`）。
   brief 把首参写成 `profile`，同时把候选链冻结成 `RoutePlan.primary+fallbacks`：只给一种
   就会要么丢画像、要么让执行器自己去 plan。现实现：**生产路径（`llm.complete/stream`）
   恒传 `RoutePlan`**（计划可复现、trace 可对照），传 `RequestProfile` 是便利入口（执行器
   自行 plan，默认进程注册表 + `routing_health_view()`，会打探针）。越界类型 ⇒ `TypeError`。
2. **可加字段（全部带默认值，不动冻结五字段的顺序与语义）**：
   `FallbackResult.context_dropped`（T3 移交④要的「被剔计数」，trace 的 `model_route` 要用）；
   `StreamSummary` 在冻结六字段之后加 `committed` / `completed` / `error_type` /
   `model_id` / `provider_name` / `budget_ms` / `context_dropped`。
   理由：§8 的 `success` / `error_type` / `provider` / `model` 四列**只有** finish() 的输出能
   喂，而「走完 / commit 后中断 / pre-commit 全败」三种终态只看 `committed` 分不开。
   流式没有 `LLMResponse`，所以 `model_id` 取注册表条目 id（非 effective model 名）。
3. **`hard` 的熔断回执按「有没有真实往返」分岔**（任务书写的是「视情况」）：
   带 HTTP 状态码 ⇒ `record(True)`（对方活着并回了话，坏在我们的请求；记 False 会让一条
   写坏的请求把整个 provider 闸 60 秒），不带状态码 ⇒ `record(False)`（外呼没发生）。
   半开名额**必须归还**是这条分岔的硬约束：`CircuitBreaker` 的 HALF_OPEN 槽位没有租约回收
   （`app/resilience.py` 模块文档自陈），放行后不回执＝慢性饿死该 provider 的探测通道。
   已由 `test_hard_with_http_status_is_not_a_provider_failure_and_returns_the_probe_slot`
   （`half_open_probes=1`：若不回执，第二个候选会被自己的熔断器闸掉）钉住。
4. **被 config 跳过的候选不产 `Attempt`**（`skipped_circuit` 却产）：判据是 D4 的
   「每真实调用回执」——熔断跳过有独立 reason 且 `resilience.py` 要求丢弃该期回执，
   而 config 跳过既无自己的错误事实、也已被 `PROVIDER_CONFIG_FAILED` 描述；
   多一条同名 Attempt 只会把 §8 的 `fallback_rate` 聚合口径弄糊。
5. **空文本 chunk 不算内容**：未提交时扣住不吐（`finish`/`usage` 块），提交后照原序透传。
   否则「已交付给用户看到东西」与 `committed` 会分家，pre-commit 换模型就成了改口。
6. **干净结束的空流算成功**（不判失败、不换模型）：provider 答了「空」是答案，不是故障；
   判失败会让一个合法的短回答吃掉整条链的预算。此时 `committed=False`、`completed=True`、
   `selected_index=0`。
7. **`AllCandidatesFailedError.kind` 沿用最后一个真实失败的归类**（无失败可沿用 ⇒ `hard`），
   `no_fallback` 保持 False：聚合错误的终止性由**类本身**表达，不借 §6 的「请求不合法」语义。
   刻意是 `LLMError` 子类（三条链今天就在 `except LLMError` 里落兜底文案，D2 不许新增 catch）；
   而 `StreamInterrupted` 刻意**不是**（见 `fallback.py` 的类文档：否则调用方的
   `except LLMError` 会把已交付内容的会话当成可整体重发的错误，用户看到两段不同模型的答案）。
8. **`timeout_or_none()` 返回 `None` 表示预算耗尽**，`_STOP` 走 `gate()` 而不是抛：
   于是「停止外呼」与「换候选」共用同一个三段预检（config → 预算 → `allow()`），顺序被
   注释冻结——预算排在 `allow()` 之前，因为 `allow()` 一放行就欠一条回执。
9. **重试前重新 `allow()`**（`runner.allow_retry`）：一次候选可能对应多次真实调用，
   HALF_OPEN 名额必须逐个借还；顺带覆盖「熔断在重试前打开 ⇒ 不再外呼、也不留回执」。
10. **`FALLBACK_AFTER_TIMEOUT` 的判据**是归类事实（`kind=retryable` ∧（消息前缀「超时」∨
    408）），不是「没有状态码就是超时」——连接失败同样没有状态码，冒领超时会让 trace 说谎。
11. **`_query_of` 只看最后一条消息的 content**：拼全文会把 rag 的检索上下文算进复杂度，
    于是「上下文长」被误判成「问题难」。`complexity` 今天不参与打分（T3 偏离 3），
    所以这个口径只影响 trace 可读性。
12. **`llm.complete()` 的 usage 落点在包级、`stream()` 的不落**：非流式的账在 `run_complete`
    返回时已完整；流式的 ttft/commit/usage 只在 `finish()` 之后存在，包级写不了，
    所以提供 `log_stream_usage(summary, ...)` 让调用点（T7）显式记账，
    两种终态（成功 / `AllCandidatesFailedError` 后）用同一个调用式。
13. **`estimated_cost` 不在 T4 算**：单价属于注册表条目、这里是执行面；谁拥有账本谁算成本。
    失败行的 `provider` 在无 attempts 时取 `LLMError.provider`（可能为空串）。
14. **latency 口径**：usage 的 `latency_ms` = 全链 attempts 实测之和（预算消费口径），
    与 `LLMResponse.latency_ms`（最后一次成功往返）不同；两者都在结果对象里，T5 不必猜。

## 移交下一任务（handoff）

- **→ T5（头号）**：记账接线只剩一行——`llm.set_usage_sink(log_usage)`，或直接建
  `app/llm/usage.py` 暴露 `log_usage(UsageRecord)`（本包的 `usage_sink()` 会**惰性解析**它，
  无需回改 T4）。已备好的字段：`route_mode`、`route_reason`（计划码在前、执行期码在后，
  已去重）、`provider`、`model`、`fallback_index`、`input/output/total_tokens`、`ttft_ms`
  （流式）、`latency_ms`（全链之和）、`success`、`error_type`、`status_code`、`trace_id`、
  `request_id`。T5 只需补 `id`/`created_at`/`estimated_cost`/`currency`。
  `log_stream_usage()` 里 `fallback_index=-1` 与 `error_type` 是「未选中」哨兵，
  落库前请判 `summary.completed`。
- **→ T5**：trace 的 `model_route` 需要 **stage + 被剔计数**（T3 移交④）：
  成功路径读 `FallbackResult.context_dropped` / `StreamSummary.context_dropped`；
  零候选路径读 `NoCapableModelError.stage` 与异常文本里的「被剔 N 条」
  （要结构化数字就调公开函数 `fit_chain_to_context(plan, req)` 重算，纯函数零副作用）。
  `PRIMARY_UNHEALTHY` 仍只描述被 health 步剔掉的 provider（T3 口径未动）。
- **→ T7（SSE）**：`StreamSession` 给出 D5 需要的一切——`committed`（→ payload
  `stream_committed:true`）、`StreamInterrupted.error_type`（→ payload `error_type`）、
  `partial_text`（**不得重复推送**）、`attempts`/`selected_index`/`reason_codes`。
  事件词汇零新增；`except LLMError`（聚合失败/硬终态）与 `except StreamInterrupted`
  **必须两支分开写**，后者才写 `stream_committed`。会话被客户端断开时 `chunks()` 因
  `GeneratorExit` 退出、不产任何回执，`finish()` 仍可调（`completed=False`、无 `error_type`）。
- **→ T6/T8**：`complete()` 不吞 `NoCapableModelError`（已用出厂注册表 agent 模式钉住零外呼），
  两支的既有兜底文案可直接接。T8 仍需核对 ornith 真实 tools 能力（现 `app/agent.py` 无条件
  发 tools，与 §3 `tools=false` 冲突——`complete(needs_tools=bool(tools))` 已把裁决权交给
  调用点，改不改由 T8 定）。rag 链务必带 `temperature=RAG_LEGACY_TEMPERATURE`（T2 移交）。
- **→ T9**：`app/llm/fallback.py` 与 `__init__.py` 对 D6 全文扫描永久零命中（无 httpx import、
  无端点/凭据字面量、无 base_url 属性读），无需豁免清单；`SingleEgressStructureTests` 的
  目录 glob 已自动覆盖到新文件。若 T9 加「业务不得直接调 provider」的守卫，
  `llm.__init__` 的再导出面（`run_complete`/`run_stream`）应算合法路径，
  `provider.complete/stream` 仍是违例。
- **→ T10（真实 failover）**：执行序已按 spec §7 落地，REAL-LLM-FAILOVER-001 需要的
  「primary 真被调用并失败 / `kind=model_unavailable` / fallback_index=1 / attempts 两条」
  全在 `run_complete` 的路径上，无需改架构；预算默认 30000ms、模型超时默认 20s
  （真机 ornith 加载失败约 1–2s，phi3 生成 <20s，余量充足）。

## 需上层确认（不阻断，按 spec 字面实现）

1. 偏离 3 的 `hard`+状态码 ⇒ `record(True)`：spec §6 只写「每真实调用回执」，未定义 hard
   的记账值。我按「provider 是否活着」建模（400 是活的证据），代价是「一条坏请求不会
   闸掉 provider」——如果评审认为任何非成功都应计入失败率，改动面只有
   `_breaker_receipt_is_ok()` 一行 + 两条测试（半开名额用例需同时改成断言名额泄漏被容忍）。
2. 偏离 4 的「config 跳过不产 Attempt」：若 T5 的 trace 希望看到「链上每一个候选的下场」，
   可改成产 `Attempt(result="failed", error_type="config", latency_ms=0.0)` 的同 provider
   跳过条目；我选了「没有真实调用就没有回执」这一侧，因为它与 D4 的熔断口径同源。
3. 偏离 7 的 `StreamInterrupted` 异常族归属：现在是独立 `Exception`。若评审更担心
   「调用方漏 catch 导致 500」而不是「误重发」，可改成 `LLMError` 子类（T7 的
   `except LLMError` 就天然接住），但那会弱化「禁止整体重发」这条 D5 边界的结构性保障。
4. `complete()` 的 `profile` 关键字参数是任务书「若调用方没给 profile」这句的落地方式；
   若希望签名里不出现它，等价替代是调用方直接 `run_complete(plan, req)`（已再导出）。

## Fix round 1

评审 Spec ✅，唯一 Important（I1）+ 一条被 ratify 的文档级论据。基线 647 passed/0 failed
起算；改动只落在 `app/llm/__init__.py`、`app/llm/fallback.py`（**仅 docstring，行为零改动**）、
`tests/test_model_router_v23_contract.py`。

### I1 流式 usage 行的 latency 口径（原 `__init__.py:300` → 现 `:309`）

原状：`latency_ms=summary.budget_ms`。`budget_ms` 是配置常数（`llm_total_budget_ms`，默认
30000），把它写进 §8 的 `latency_ms` 列 = 把 `p95_latency_ms` 钉死在预算天花板上：一条
300ms 就答完的流式链也算成 30 秒，快链与慢链在观测面上不可区分——而流式是三条链里唯一
对外承诺「首字延迟」的那条出口。非流式侧（`_usage_from_result` / `_usage_from_failure`）
一直是 `_chain_latency_ms(attempts)`，所以这处不是口径选择分歧，是同一个包里的两出口
分家。

修法：`latency_ms=_chain_latency_ms(summary.attempts)`，与非流式同一函数、同一口径。
`StreamSummary.attempts` 本就带逐跳实测延迟（`fallback.py` 的 `note_success` /
`note_failure` 写入），**无需**为「暴露实测链延迟」动 `fallback.py` 的任何逻辑。

`budget_ms` 的去向（按 §8 冻结列处理，**不新增列**）：§8 的 19 列里没有 budget 列
（`test_usage_record_mirrors_section_eight_columns` 逐字镜像那 19 个名字，本已钉住
`UsageRecord` 长不出 `budget_ms`），于是「这次给了多少预算」留在汇总面
（`StreamSummary.budget_ms` / `StreamSession.budget_ms`，trace 与 T7 payload 从那里读）。
`log_stream_usage` 的 docstring 把这条写死在函数上；测试侧独立断言三件事：
`summary.budget_ms == 30000.0 == settings.llm_total_budget_ms`（原义未丢）、
`record.latency_ms != summary.budget_ms`、`not hasattr(record, "budget_ms")`。

### 测试（`PackageEntryPointTests` 12 → 13 例）

1. `test_log_stream_usage_folds_a_summary_into_a_row`（改造）：`stream_step` 0.2 → 0.45
   （2 个 chunk ⇒ 全链 attempts 之和 = 900ms、ttft 随之 = 450ms），新增「和=900 ⇒
   `record.latency_ms == 900.0` 且 `!= summary.budget_ms`」+ 上面那组 budget_ms 独立断言。
2. `test_log_stream_usage_latency_is_the_sum_of_every_hop_not_the_last_one`（新增）：
   两跳链（fb-a pre-commit 失败 200ms → fb-b 成功 400ms，即矩阵 #10 的形状）⇒ 行里必须是
   600ms。单跳用例证不了「之和」这一维，所以这条不是重复劳动：它同时钉
   `fallback_index=1`、`success=True`、`error_type is None`（成功收尾不冒领会话级错误）。

### 变异自查（2 发，逐发还原后复跑全绿）

| # | 变异 | 结果 | 被哪条杀死 |
| --- | --- | --- | --- |
| F1 | 恢复 `latency_ms=summary.budget_ms`（I1 原状） | **2 failed**（`600.0 != 30000.0`、`900.0 != 30000.0`） | 本轮新增的两处断言（单跳 + 两跳） |
| F2 | `_chain_latency_ms()` 改成「只取最后一跳」 | **1 failed**（`600.0 != 400.0`） | 新增的两跳链用例（F2 恰好证明单跳用例分不开这两种实现） |

### 文档级（评审 ratify；上表原「需上层确认 1」的论据改，结论不变）

`fallback.py:25-37`（模块 docstring 第 5 条）与 `:512` `_breaker_receipt_is_ok()` 的
`hard` 回执论据换成 **HALF_OPEN 的判活规则**：该状态下只有 `record(True)` 算探测通过、
任一 `record(False)` 立即 `_trip()` 回 OPEN（见 `app/resilience.py` 的状态机段）。于是一条
**永久坏**的自己人请求（400/404/422，报文是我们写错的）若记 False，会在每个冷却窗口把
healthy 的 provider 重新闸 `open_seconds` 秒，锁死在 OPEN → HALF_OPEN → OPEN 的循环里谁也
过不去；带状态码即「对方在线」，记 True 才把它留在服务面上。原「写坏的请求会把整个
provider 闸 60 秒」是 CLOSED 滑窗视角，撑不住这条偏序；「探测名额无租约回收」降级为
「回执**必须给**」的附注（那说的是要不要回执，不是回执取值）。函数体两行未动，行为零改动。

### 门槛复跑

- 定向：`python -m pytest tests/test_model_router_v23_contract.py -q` ⇒
  **241 passed / 0 failed**（+345 subtests），门槛 ≥241/0 ✅
- 全套件：`python -m pytest -q` ⇒ **648 passed / 0 failed**（+839 subtests；13 warnings 均为
  既有 `InsecureKeyLengthWarning`），基线 647 + 本轮新增 1 例，门槛 ≥648/0 ✅
- 本文件上方「测试构成（64 例）」与「移交下一任务」的 T5 段据此读作 65 例；
  `latency_ms`（全链之和）那条移交口径现在**流式与非流式同函数**，T5 不必再分出口。
- git 零写操作（仅 `git diff --stat` 只读）；未派子代理。

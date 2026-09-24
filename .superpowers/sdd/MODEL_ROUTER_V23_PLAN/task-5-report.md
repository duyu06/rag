# Task 5 报告 — usage 记账（§8 冻结 19 列）+ 观测出口（status 聚合 / trace `model_route`）

## 状态

**DONE（修复轮 1 已落地）**。本段描述的是**整个 Task 5 任务窗口**（起点 = Task 4 末快照
00:01:14）的交付物，不是某一次的接续轮。轮次构成：round 1（被会话截断的那一轮：账本 /
聚合 / warmup / 白名单四件已在树里）→ round 2（两个红转绿 + trace 接缝 + 16 发变异自查）
→ **修复轮 1**（评审 5 条 Important + 6 条点名的 Minor，见文末「修复轮 1」）。

- 定向（修复轮 1 后）：`python -m pytest tests/test_llm_usage_contract.py -q` ⇒
  **100 passed / 0 failed / 30 subtests**（第 5 轮 98 例 − 删除的 7 例 payload + 新增 9 例）。
  同一文件从仓库根跑也是 **100 passed / 0 failed / 30 subtests**（评审 I-5 的 cwd 耦合已消除）。
- 全套件（修复轮 1 后）：`cd backend && python -m pytest tests -q` ⇒
  **748 passed / 0 failed / 873 subtests in 78.0s**（T4 末基线 648 → 第 5 轮 746 → 本轮 748；
  0 failed 是硬门）。
- 约束核对：零 git 写、零真实 LLM/Ollama 外呼、零新增依赖、零新增 §8 的 19 列之外的列、
  未动 `rag.py` / `agent.py` / `conversation_agent.py` / `config.py` / `fallback.py`。
- **改动面（Task 5 全窗口 = 8 个文件）**：

| 文件 | 何时 | 本任务对它做了什么 |
| --- | --- | --- |
| `backend/app/llm/usage.py` | 新建 | 账本 + 聚合 + warmup + `model_route_trace`（§8.1 九键）；修复轮 1 后 1056 行（wc -l；round 2 结束时 932） |
| `backend/tests/test_llm_usage_contract.py` | 新建 | 测试类⑤；修复轮 1 后 100 例 / 14 组 |
| `backend/app/agent_trace.py` | 01:35（round 2） | `MODEL_ROUTE_KEY` + `attach_model_route`（additive + fail-open）；**修复轮 1 未再改动** |
| `backend/app/llm/__init__.py` | 00:31（round 1）→ 02:35（修复轮 1） | round 1 加过 `model_route_payload` / `_route_stage` / `_route_error_code` / `_effective_model_name` + 导出 + docstring 段；**修复轮 1 把 payload 那一族三枚函数删除**，`_effective_model_name` 的解析并成包级公共件 `effective_model_name_for_entry` |
| `backend/app/knowledge_os.py` | 00:16 | `llm` 块 = legacy 六键 + `aggregate_status()` → 整块过 `public_llm_status` |
| `backend/app/main.py` | 00:16 | lifespan 增 `warmup_llm_router()`（与 `warmup_identity_permissions()` 并排） |
| `backend/app/security.py` | 01:28 → 02:38（修复轮 1） | `PUBLIC_LLM_STATUS_KEYS` / `public_llm_status` 的白名单段是 Task 5 早段（00:16 之前）落的（`knowledge_os.py:28,34,657` 从 00:16 起 import 它）。01:28 那次写入是 **round 2 的变异注入并原样还原**（M3 打在 `public_llm_status` 的遍历上，mtime 变化、内容净零改动）；修复轮 1 才有**真实**内容改动：`_LLM_PROVIDER_NAME_PATTERN` 收紧到 `^[a-z0-9_]{1,64}$`（Minor 1）。**「本轮对它做过变异注入并原样还原」= mtime 变化、内容净零改动**，这是标准措辞，不再写成「零改动」 |
| `backend/tests/test_model_router_v23_contract.py` | 00:22（round 1，此前漏报） | `:3786-3812` 的 `test_usage_sink_falls_back_to_late_bound_app_llm_usage` 从「两面」重写成「三面」——详见下面「T4 那一例的强度核对」 |

**T4 那一例的强度核对（旧钉为何失效 / 新钉降不降强度）**：旧版第二枚断言是
`self.assertIsNone(llm.usage_sink())  # 今天的真实状态：没有 usage 模块`，它成立的前提
是 `app/llm/usage.py` **还不存在**；T5 把它建出来了，这句话就从「事实」变成了「假的」，
留着就是一枚会自己腐烂的钉（不是被放宽，是被现实作废）。三面版逐面核对：
- 面 1（显式 sink 优先）：旧版没有这一枚 ⇒ **新增**。
- 面 2（惰性解析到 `usage.log_usage`）：旧版用 `patch.dict(sys.modules, {"app.llm.usage": 假模块})`
  证明「能解析到同名函数」，新版解析到**真** `log_usage` ⇒ 同一件事、更真的对象。
- 面 3（取不到 ⇒ `usage_sink()` 为 None 且 `complete()` 照常交付）：对应旧版的
  「无 sink ⇒ 不炸」⇒ 等价保留（打的是包属性 `llm.usage`，因为真模块一旦被 import 过，
  只换 `sys.modules` 换不掉父包上的属性——第一版就是这么红的）。
- 返回值语义（`set_usage_sink` 返回前一个 sink）：旧版没有 ⇒ **新增**。
- **旧版少掉的一枚**：`assertEqual(1, len(rows))` + `assertEqual("chat", rows[0].route_mode)`
  ——旧版在假模块上下文里真的跑了一次 `complete()`，证明「账**交付**给了惰性解析到的 sink」；
  三面版只断言解析结果本身，这一步在它里面就没有主人了。**修复轮 1 已在 T5 自己的契约文件里
  把这枚断言补回来**（`WarmupWiringTests::test_the_late_bound_sink_writes_a_real_row_for_llm_complete`：
  真 `log_usage` + 真临时库 + 真 `llm.complete()` ⇒ 一行、`route_mode="chat"`、
  `model` 走 M2 口径），并额外钉了 `trace_id` 与 `success`。净结论：T4 那一例本身**不降强度**
  （新增两枚、等价保留两枚、作废一枚因由可查），少掉的那一枚已在改动面内的文件里补回。

## 交付文件

（下表按 Task 5 全窗口写；「round 2」= 评审前的最后一轮，「修复轮 1」= 本轮。逐文件面
另见上面「改动面」表。）

| 文件 | 行数 | round 2 内容 |
| --- | --- | --- |
| `backend/app/llm/usage.py` | 736 → 932（+196） | **新增** trace `model_route` 的公共构造函数 `model_route_trace()`（当时按 §8 的六键）及其零件 `_trace_mode` / `_trace_requirements` / `_candidate_view` / `_attempt_view` / `_trace_result` / `_trace_error_code` / `_entry_by_id`；**改** `_cost_for` 为三分支口径（新增 `_caller_cost`）；**新增** `model` 列口径归一（`_match_entry` + `_stored_model_name` + `_entry_effective_name`）；`_prepare_record` 收口重排（注册表只查一次、token 先收口再折价）；`_metrics_of` 改为关页那一刀**只筛一次**；常量 `_COST_PRECISION` / `TRACE_LIST_MAX_ITEMS` / `_ATTEMPT_RESULTS` / `TRACE_UNKNOWN`；模块 docstring 增第 4 条口径 |
| `backend/app/agent_trace.py` | 56 → 92（+36） | **新增** `MODEL_ROUTE_KEY = "model_route"` 常量 + `attach_model_route(trace, plan, result, *, profile=None)`：T6/7/8 的一行接缝，additive（只多一个键）+ fail-open（构造失败只 warning）。既有 `new_trace_id` / `public_args` / `save_trace` / `get_trace` 一字未改（**文本层与字节层都未改**：本轮对它零写入；上一轮曾把 19 行的行尾从 mixed 规整为全 CRLF，见评审 Minor 8，属既有卫生问题） |
| `backend/tests/test_llm_usage_contract.py` | 1168 → 1740（+572） | 测试类⑤扩到 14 组 / 98 例（上一轮 69 例 ⇒ +29）：新增 `ModelRouteTraceShapeTests`(13)、`AgentTraceModelRouteSeamTests`(3)、`ModelRoutePayloadTests`(7，**修复轮 1 已随被删实现一并删除**)；`CostTests` 3 → 10；`ModelColumnCaliberTests` 5 → 8；`ProviderHealthBudgetTests` 9 → 10；`UsageSchemaTests` 5 → 6；`ClientAbortTests` 3 → 4；修正 1 例的取样方式（详见「红→绿」） |

`app/security.py` 的 `llm` 白名单段（`PUBLIC_LLM_STATUS_KEYS` 13 枚 + `public_llm_status` +
三个私有零件）是 Task 5 早段（00:16 前）落的，被 `knowledge_os.py:28,34,657` import；
round 2 只对它做过**变异注入并原样还原**（M3，mtime 变化、内容净零改动）。
`app/knowledge_os.py` 的 `llm` 块（legacy 六键 + 聚合块 → 整块过白名单）与 `app/main.py` 的
`warmup_llm_router()`（与 `warmup_identity_permissions()` 并排）都在 00:16 写入，属本任务改动面。

## 红 → 绿证据

两个红**归因在不同侧**，各自按根因修，没有任何断言被放宽。

### 红 1：`UsageSchemaTests::test_a_record_round_trips_through_every_column` — **实现 bug，改 `usage.py`**

- 现象：调用方递 `estimated_cost=0.004, currency="USD"`，库里落 `(0.0, "")`。
- 根因：旧 `_cost_for()` 只有「按注册表牌价折算」一条路，注册表匹不到条目就 `return 0.0, ""`，把调用方**已经算好的**成本静默清零。§8 冻结的 `estimated_cost` / `currency` 两列是账本里唯一的成本数据位，清零 = 丢数据。
- 修法（裁定=三分支，已写进 `_cost_for` docstring）：
  1. **注册表匹到条目**（`provider` + `entry.model` 或 `entry.id`，`model` 优先于 `id`）⇒ **牌价是权威**，用它折算，币种取 `pricing.currency`；调用方自带的成本不认（一张表里两套价格来源，聚合总额就会取决于「哪条链先写」）。
  2. **匹不到但调用方算过**（`estimated_cost` 有限且 **> 0**）⇒ 持久化调用方的值 + 它的 `currency`（过 `_CURRENCY_PATTERN` 三字母白名单并大写，不合形状即空串）。
  3. **调用方也没给** ⇒ `(0.0, "")`；**空币种仍是「不知道牌价」的唯一标记**。
- 「算过」的判据取 **> 0** 而不是「非 None」：`UsageRecord.estimated_cost` 是 `float` 字段、默认值就是 `0.0`，库里 `0.0` 分不开「算过了，这一路免费」与「压根没算」；若把前者也带上币种，就会出现「USD 且 0 成本」的行，而这一形状在 §8 口径里同时是「免费的云端模型」的写法 ⇒ 两义。代价进「遗留 minor 1」（免费路的币种丢失）。
- 顺带修的两处同源缺陷（都有新测试钉）：
  - 折价吃的是**收口前**的原始 token：`input_tokens="n/a"` 会让账本自己 `TypeError`，被 `log_usage` 的 fail-open 吞掉 ⇒ **丢整行账**（观测面自己成了故障源）。现在先 `_non_negative_int` 收口再折价（`test_bad_token_values_are_clamped_before_the_price_is_applied`）。
  - 匹配不看 `provider` ⇒ 两个 provider 挂同名模型（`qwen-plus` 经 DashScope 与经网关）时套错牌价，本地免费路会把云端账单折成 0（`test_the_provider_narrows_the_price_lookup_when_two_sides_share_a_name`，M15 就是它杀的）。

### 红 2：`ModelColumnCaliberTests::test_the_sink_still_sanitizes_an_unsafe_name` — **测试自身取样口径错，改测试**

- 现象：`rows[1]["model"]` 期望 `""`，实到 `"fb-a-model"`。
- 查证（不是净化逻辑坏）：该组 `setUp` 里 `llm.set_usage_sink(None)` ⇒ `log_stream_usage()` **自己就会经 sink 落一行**（惰性解析到真 `log_usage`）；测试又把这个返回值显式 `log_usage()` 了一次 ⇒ 库里是「同一条流式账的两行 + canary 那一行」共 **3 行**，按下标取 `rows[1]` 取到的正是那条重复的流式账。`_model_name` 的白名单 `[A-Za-z0-9_.:/+\-]{1,128}` 对 20 个中文字符必然返回 `""`——净化没坏。
- 修法：断言改为**按 `trace_id` 定位行**，并显式钉住「实际落了几行、每行是谁」：`assertEqual(2, len(rows))` + `assertEqual({"t-stream","t-canary"}, {trace_id})`；顺手加了两条 `M1`（流式行 `status_code` 恒 NULL）与「其余列照常落」的断言。为避免那 1 行重复写，去掉了测试自己补的那一次 `log_usage`（sink 已经写过）。
- **中文 canary ⇒ `model` 列空串**这条断言原样保留（一个字未松），并由 M1 变异（白名单改透传）证明它还活着。

## 测试构成（修复轮 1 后 100 例 / 14 组）

| 组 | 例 | 钉什么 |
| --- | --- | --- |
| `UsageSchemaTests` | 7 | §8 的 19 列**列名+顺序**三方等式（DDL ↔ 常量 ↔ `UsageRecord`）+ 禁存列名；`init_usage_db` 幂等与建父目录；全列往返；路径与 `ConversationStore` 同源；**§5 冻结枚举闭合**；**`_clean_codes` 的去重 + 上限**（上限 = 枚举基数、截断那一支是活代码。修复轮 1 +1，杀评审 Minor 2 的存活变异） |
| `ForbiddenContentTests` | 7 | 中文 prompt 掺进**每一个**字符串列 ⇒ `SELECT *` 全列扫 0 命中；`error_type` 只收机器码 + 长度上限；`str(LLMError)` 的 body canary 全列 0 命中（T2 移交 M-7）；**`kind:<状态码>` 后缀与 `status_code` 列同一个定义域**（修复轮 1 +1，Minor 3）；越界数字收口 / 坏标识符整值丢弃；币种双向 |
| `ClientAbortTests` | 5 | 有交付事实的关页 ⇒ `client_aborted`（既有列的合法值，不是新列）；**没有交付事实的失败行 ⇒ `unknown` 且进 `success_rate` 分母、`aborted_rate` 不受它影响**（修复轮 1 +1，§8.1 第 2 条 / 评审 I-4）；provider 失败保留 kind；零候选不产行 ⇒ 不进 `requests_5m` 分母 |
| `AggregateMathTests` | 8 | 10 行窗口的四个率 + 最近秩 p95；关页两头剔除的反证；分母 0 ⇒ `None`；窗口边界压线；单样本 p95；延迟面不剔关页；旗标关掉零外呼 |
| `ProviderHealthBudgetTests` | 10 | `providers.healthy` 只来自 probe；1.5s 整轮预算 / 在飞去重 / 退缓存 / TTL 后宁缺毋滥；breaker 只读不建；**熔断态不渗透进 `healthy`**（D4）；两例 breaker 用例补 `no_probes()`（修复轮 1，Minor 12：以前靠 `ollama.test` 解析失败侥幸） |
| `FailOpenTests` | 6 | 写库任何异常不上抛且**照旧交付内容**；读库失败 ⇒ 空块；聚合自身炸 ⇒ 空形状不外抛；表缺失 ⇒ 空窗口且**不顺手建表**；注册表坏只影响名字面 |
| `CostTests` | 10 | 三分支逐支（①牌价权威 / ②承载调用方成本 / ③空币种）+ 坏成本收口 + 币种白名单 + 注册表不可用仍有账 + 同名跨 provider + 坏 token 不丢行 |
| `LlmStatusWhitelistTests` | 7 | `public_llm_status` deny-by-default：邻近键 / 凭据形状 / 前缀放行不是规则 / 标量 retype / **provider 名字符集与注册表同源**（`api.openai.com`、`127.0.0.1:11434`、`Ollama` 都不许过——修复轮 1 把 Minor 1 的宽字符集钉死）/ 非 mapping 塌空 / 熔断词表 |
| `SystemStatusLlmBlockTests` | 4 | `/api/system/status` 的 `llm` 块键集 = 白名单；legacy 六键不动；**未知键不外泄**（canary 不进响应体）；其他块不受影响 |
| `ModelRouteTraceShapeTests` | 16 | **§8.1 的九键**逐字（四层键序 + 末三枚执行面事实的位序）；`stage` / `selected_index` / `context_dropped` 的四值语义与 D2 缺省（修复轮 1 +2）；mode+requirements 只来自画像五字段、**`needs_*` 显式真值判定**（`"false"` 不是 True，修复轮 1 +1，Minor 4）；候选解释只含名字与打分（无 `pricing` / `limits`）；理由码过滤；attempts 按 M2 归一 + 越界值兜底；JSON 往返；**画像挂 `query`/`prompt`/`messages` canary ⇒ 0 命中**；两张列表封顶 16；两枚类型闸门；`AllCandidatesFailedError` 可用；注册表不可用仍出完整对象；**router 真产出的 `PRIMARY_UNHEALTHY` 原样进 trace**（T3 移交同源口径） |
| `AgentTraceModelRouteSeamTests` | 3 | `attach_model_route` 只多 `model_route` 一个键（其余字段逐字节不变）、fail-open、落盘 JSONL 读回来形状完整且无 prompt |
| `ModelRouteProducerUniquenessTests` | 2 | **防回潮（评审 C / §8.1 第 4 条）**：`llm.model_route_payload` 的属性与导出面都不许复活、`app.llm` 里 `model_route*` 命名的可调用只剩 `usage.model_route_trace` 一枚、`MODEL_ROUTE_KEY` 的值只由它产出；再加**源码级扫描**：全 `app/` 里说这个键名的文件只许挂载点那一处、把执行面三键成对写成字面量的文件只许生产者那一处（修复轮 1 新增组） |
| `ModelColumnCaliberTests` | 8 | 生效名口径（流式 / 非流式 / **三条出口落同一个词** / 别名同理 / 匹不到不猜 / sink 白名单） |
| `WarmupWiringTests` | 7 | warmup 链（门闸→sink→建表）、fresh 部署建表、旗标关掉全链 no-op、坏表能起坏注册表不能起、lifespan 两处并排、接缝惰性自接线、**惰性 sink 真的为 `llm.complete()` 落一行**（修复轮 1 +1：补回 T4 那例改三面时掉的那枚断言） |

第 5 轮的 `ModelRoutePayloadTests` 7 例随 `llm.model_route_payload()` 一并删除——被删的是零业务
消费者的死码，那 7 例只是它自己的测试；它独有的 `stage` / `selected_index` / `context_dropped`
三枚事实改由 `ModelRouteTraceShapeTests` 在**九键**清单里钉（覆盖面净增不减）。


## 变异自查（16 发，全部被杀；逐发还原后复跑零残留）

（本节是 **round 2** 的自查记录，保留原文。修复轮 1 另跑 8 发 M-R1..M-R8，见文末「修复轮 1」
第 2 小节；其中 M2 那一发的语义在 §8.1 收窄后仍成立——种子行的关页 shape 带着交付事实。）

| # | 变异 | 结果 | 被哪条杀死 |
| --- | --- | --- | --- |
| M1 | **`_model_name` 白名单改成直接透传**（只截断） | **2 failed** | `test_long_chinese_prompt_never_survives_any_column`、`test_the_sink_still_sanitizes_an_unsafe_name` |
| M2 | **`client_aborted` 计入 `success_rate` 分母**（`scored_rows` 返回全部行） | **3 failed**（0.7143 → 0.5556、`None` → `0.0`） | `test_window_rates_and_p95_on_ten_seeded_rows`、`test_aborted_rows_would_otherwise_poison_the_success_rate`、`test_all_aborted_window_has_no_success_samples_at_all` |
| M3 | **未知键绕过 `public_llm_status`**（遍历 `白名单 ∪ source` 键） | **4 failed** | `test_field_set_is_exactly_the_whitelist`、`test_prefix_admission_is_not_a_rule`、`test_llm_block_is_the_legacy_probe_face_plus_the_aggregate`、`test_unknown_aggregate_keys_never_reach_the_response` |
| M4 | `_stored_model_name` → 直接透传（不查注册表） | **failed** | `test_all_three_producer_paths_land_on_one_model_string`、`test_the_model_override_alias_is_the_stored_value_on_every_path` |
| M5 | 砍掉成本第 ② 支（匹不到一律 `(0.0,"")`） | **4 failed** | 红 1 那例 + `test_an_unmatched_entry_still_persists_the_callers_own_cost` 等 |
| M6 | `_trace_requirements` 改成 `dict(vars(profile))`（属性遍历） | **failed** | `test_a_profile_carrying_a_query_leaves_not_a_single_byte_in_the_object` |
| M7 | 去掉 `model_route_trace` 的两枚类型闸门 | **3 failed** | `test_both_argument_gates_are_type_errors`（subTest 两侧） |
| M8 | `_clean_codes` 不再过滤 §5 枚举 | **3 failed** | 禁存项那例 + `test_selected_reason_codes_are_filtered_to_the_frozen_enum` + 候选解释那例 |
| M9 | `_caller_cost` 把 `0.0` 也当「算过价」 | **3 failed** | `test_branch_three_keeps_empty_currency_...`、`test_unknown_model_costs_zero_...`、`test_currency_follows_the_registry_...` |
| M10 | 去掉 trace 两张列表的 16 上限 | **failed** | `test_both_lists_are_capped` |
| M11 | `error_type` 词表闸改成透传 | **2 failed** | `test_error_type_rejects_human_text_and_is_length_capped`、禁存项那例（M-7 反测试） |
| M12 | `log_usage` 不再 fail-open（吞异常改成 `raise`） | **2 failed** | `test_a_locked_database_cannot_break_the_generation_chain`、`test_log_usage_swallows_every_database_error` |
| M13 | trace 接缝不再 fail-open（`TypeError` 上抛） | **1 failed** | `test_the_seam_is_fail_open` |
| M14 | 折价吃**收口前**的原始 token | **1 failed** | `test_bad_token_values_are_clamped_before_the_price_is_applied` |
| M15 | `_match_entry` 忽略 `provider` 维度 | **1 failed** | `test_the_provider_narrows_the_price_lookup_when_two_sides_share_a_name` |
| M16 | 接缝写成常量假对象（不调 `model_route_trace`） | **2 failed** | `test_attaching_writes_exactly_one_new_key`、`test_the_seam_is_fail_open` |

诚实说明：M2 第一版**存活**过——当时 `_metrics_of` 里分母是 `total - len(aborted)`、分子用 `scored_rows(rows)`，两处平行实现导致「改 `scored_rows`」成了等价变异。我把分子分母合并成**只筛一次**（`scored = scored_rows(rows)`）后重跑才杀掉。这是变异自查顺手发现的真实设计缺陷，不是测试技巧。

## 裁定与口径

### 1. M2（`model` 列劈叉）实测结论与最终口径

实测三条出口在 `UsageRecord.model` 上写的是**两种**东西：

| 出口 | 写什么 | 出处 |
| --- | --- | --- |
| 非流式**成功** | provider 回显的**生效模型名**（回显缺失时 provider 层已按 `effective_model_name` 兜底） | `app/llm/__init__.py::_usage_from_result` |
| 非流式**失败** | **注册表条目 id**（`Attempt.model_id`，T4 移交 M4） | `_usage_from_failure` |
| 流式 | 生效模型名（T4 修复轮 I1 起，`log_stream_usage` 自己回查注册表并套 D1 别名） | `log_stream_usage` + `_effective_model_name` |

**最终口径：`model` 列恒为「生效模型名」（含 `{PROVIDER}_MODEL_OVERRIDE` 别名），归一发生在落库前。**
实现 = `_match_entry`（`provider` 相符 + `model` 优先于 `id` 命中）→ `_stored_model_name`：匹到就换成该条目的生效名（匹到 `model` 时幂等，匹到 `id` 时完成换名，override 生效时两侧都落到别名）；匹不到（条目被删 / provider 名不合法 / 注册表不可用）就**原样留**那个可解释的名字，**不拿 provider 去猜**；`name` 为空（被字符集白名单挡掉的回显）仍为空——那里没有信息可以恢复。
为什么不改生产者侧：`_usage_from_failure` 不在本任务改动面（且失败行只有条目 id 可用，回查注册表是账本更该负责的事——账本本来就要查一次注册表拿牌价）。**残留的生产者侧不对称**见「遗留 minor 3」。
跨路一致性测试：`test_all_three_producer_paths_land_on_one_model_string`（先断言内存里确实**仍是两种**词，再断言库里只剩一种）+ `test_the_model_override_alias_is_the_stored_value_on_every_path`（别名场景）。trace 的 `model_route` 用**同一个** `_stored_model_name`，所以 trace 与账本对同一个模型的写法也一致。

### 2. 关页 / 零候选（M3）语义（**判据已按 §8.1 第 2 条收窄，修复轮 1**）

- 关页：`success=False ∧ error_type 缺失 ∧` **有交付事实**（`fallback_index >= 0 ∧ (input+output) tokens > 0`）⇒ 落 `client_aborted`（既有列的取值，**不是新列**）；聚合从 `success_rate` 的**分子与分母同时**剔除，单列 `aborted_rate`；`p95_latency_ms` **不**剔除（关页前的等待是真实等待）；`fallback_rate` / `aborted_rate` 的分母是窗口全部行。**没有交付事实**的同类形状落 `unknown` 并**留在分母里**（它是一次失败）——旧判据「只看 error_type 缺失」是从**缺席**反推「用户关页」，会把生产者漏填归类的全链失败读成「1.0 的关页 + 零失败样本」。钉：`test_aborted_row_is_written_as_client_aborted`（有交付那一支）+ `test_a_failure_row_without_error_type_is_not_silently_called_an_abort`（三种无交付形状 + 反证）。
- 零候选：`NoCapableModelError` 在任何外呼之前抛出 ⇒ 没有 attempt、**没有行**、不进 `requests_5m` 分母（`test_no_capable_model_writes_no_row_and_stays_out_of_the_denominator`）。两支的区别写在测试 docstring 里：关页有「真实执行过」的事实要留，零候选连一行都不该存在。

### 3. D4：`providers.healthy` 与熔断态分离

`providers:{name:{healthy}}` 的唯一数据源是 `health.provider_health_view()`（probe + 60s 缓存，**不掺** `circuit_open`）；熔断态另开 `breaker:{name:{state}}`。新增 `test_an_open_breaker_never_leaks_into_the_healthy_face`：同一个 provider 探针 True + 熔断 OPEN ⇒ `healthy` 仍为 `True`，两键值域互不交叉（`healthy ∈ {bool,"unknown"}`、`state ∈ {closed,half_open,open,unknown}`）。router 侧要 `{healthy, circuit_open}` 合成视图是 `fallback.routing_health_view()` 的职责，与观测面**刻意不同源**，两侧各有测试。

### 4. `reason` 码与 `context_dropped` 与 router 同源（T3 移交）

`_REASON_CODES = frozenset(REASON_CODES)` **从 `app.llm.router` import**，本文件不重述词表（含 `PRIMARY_UNHEALTHY` 的措辞）；`test_every_router_reason_code_survives_the_sink` 钉枚举闭合，`test_the_routers_own_vocabulary_survives_into_the_trace_object` 用**真的 `plan()`**（health_view 把 ollama 标不健康）产出计划 → 回执 → trace 对象，断言 `PRIMARY_UNHEALTHY` 原样出现且 primary 指到 openai 条目。
`ROUTE_REASON_MAX_ITEMS` 修复轮 1 起 = `len(REASON_CODES)`（曾经是硬编码 12 vs 枚举 9 枚 ⇒ 上限永不生效的死码，且去重/上限两件事零测试；评审 Minor 2）。

`context_dropped` / `stage` / `selected_index` 这三枚**执行面**事实的落点：第 5 轮的报告写的是
「§8 六键里没有它们的位置，目前由 T4 的 `llm.model_route_payload()` 承载」——那句话当时就是
**假的**（那枚函数是 Task 5 round 1 新加的零消费者死码，见评审 I-2/I-3），而 §8 的六键清单与
§5（trace 要「带 stage + 被剔计数」）本来就互相矛盾。**处置（主 agent 已回写 §8.1 第 4 条）**：
按九键执行，三枚事实**并进** `usage.model_route_trace()`，`model_route_payload()` 删除。
本轮据此落地：唯一生产者 = `usage.model_route_trace`，唯一挂载点 = `agent_trace.attach_model_route`，
防回潮由 `ModelRouteProducerUniquenessTests` 两例钉住（属性 / `__all__` / 命名扫描 / 源码级字面量扫描）。

### 5. `llm` 块里 §8 未列出的 additive 键——逐项辩护（**已获 §8.1 第 3 条回写授权**）

白名单常量 `PUBLIC_LLM_STATUS_KEYS` 共 13 枚，其中 §8 正文明列的只有 5 枚（`requests_5m` /
`success_rate` / `fallback_rate` / `p95_latency_ms` / `providers`）。下表后两枚
（`aborted_rate` / `breaker`）**已由 §8.1 第 3 条回写授权**（评审 I-4 的书面裁定，主 agent
2026-09-24 写入 spec；终审时向用户复述确认），不再是「待批」状态；其余 6 枚是 V2.3 之前的既有面。

| 键 | 为什么不算越界 |
| --- | --- |
| `status` / `model` / `provider` / `p50_ms` / `p95_ms` / `ttft_ms` | **V2.3 之前就存在**的探针面（前端 `SystemView` 在消费）。§9 冻结「既有响应结构对外不变（additive only）」——把它们删掉或改名才是违例。它们也不是 Router 造的键，本轮只是把 Router 的聚合块**并进同一个 dict** |
| `p95_latency_ms` vs `p95_ms` | 两者量不同东西：前者是 usage 面的**全链耗时**（各 attempt 之和），后者是 trace 面的生成耗时。**故意不同名**，各自说清自己量的是什么，不是重复上报 |
| `aborted_rate`（§8 之外） | M3 的**必需出口**：关页行被两头剔除后，`success_rate=1.0` 就不再区分「全部成功」与「用户中途关页」。没有一个显式出口，运维会读到假的健康。值域 `[0,1]`、纯聚合、无行级信息、不点名是哪个请求；分母与 `requests_5m` 同源 |
| `breaker`（§8 之外） | 同上性质：`providers.healthy` 被 D4 限定为「只说 probe」，于是「链上为什么没有这个 provider」需要另一个词来回答，否则运维只能猜。形状是 `{provider: {"state": 四枚封闭词}}`——**只有**注册表侧已校验过的 provider 名（`public_llm_status` 再过一次字符集闸，URL 形状直接丢）+ 状态词；不含失败计数、窗口阈值、半开名额、任何 URL / key / 上游文本。`llm_breaker_enabled=false` 时恒报 `closed`，观测不到也不会泄露配置 |

两条共同的反外泄保证：整块再过一次 `public_llm_status`（deny-by-default，未知键 / 邻近前缀键 / 把行吐出去的诱惑键都进不来，`test_unknown_aggregate_keys_never_reach_the_response` 用 `apikey_DDD…` + 中文 prompt canary 钉死）；`aggregate_status` 自身只 SELECT 四个聚合列，任何失败收成空形状。

## 移交下一任务（T6 / T7 / T8 的硬义务）

**本轮只建接缝 + 钉契约**：今天业务代码里没有任何路径真的走 `llm.complete/stream`，所以 `attach_model_route` **零业务调用点**（`grep -rn "attach_model_route" backend/app/` 只会命中定义处）。矩阵 #17 的「集成」半段目前由 `AgentTraceModelRouteSeamTests::test_the_persisted_line_carries_model_route_and_no_prompt`（真 `save_trace` → 真 JSONL → 真 `get_trace`）覆盖到**可覆盖的极限**，剩下的那一步必须在迁移里做。

义务（三条链各自一行，写在收尾处、trace 落盘之前）：

```python
from app.agent_trace import attach_model_route           # 或 import agent_trace

attach_model_route(trace, result.plan, result, profile=profile)   # 调用形状（§6 第 4 条）
#   trace   : dict —— 该链正在组装的那条 trace（本函数只写 trace["model_route"]）
#   plan    : app.llm.models.RoutePlan —— 由 T6 加到结果对象末位的可加字段 `plan`
#   result  : FallbackResult（T6/T8 非流式）| StreamSummary（T7，`session.finish()` 的产物）
#             | AllCandidatesFailedError（D2 降级路径，尤其要能解释）
#   profile : RequestProfile（classify 的返回值）—— 只有它知道 mode/requirements；不传则两键为空
# 键名常量：agent_trace.MODEL_ROUTE_KEY == "model_route"
# 底层纯函数：app.llm.usage.model_route_trace(plan, result, *, profile=None, registry=None)
```

- **T7（SSE）**：`stream_committed` / `error_type` 属 D5 的 **SSE payload 增量字段**，不进 trace 的 route 解释（本函数刻意不读 `StreamSummary.committed`）；commit 事实仍走事件体。
- **T6/T7/T8 共同的接口缺口——修复轮 1 已有裁定（评审包 §6 第 4 条，不再由你们三选一）**：`llm.complete()` 只返回 `FallbackResult`、不把 `RoutePlan` 递出来，而 `model_route_trace` 的计划面必需它。裁定取「(c) 的变体」：**由 T6 给 `app/llm/fallback.py` 的 `FallbackResult` 与 `StreamSummary` 各加一个末位可加字段 `plan: RoutePlan | None = None`**（frozen dataclass 末位默认值 ⇒ 既有构造与 T4 的 12 处断言不破），`run_complete` 与 `StreamSession.finish()` 负责填；`AllCandidatesFailedError` 同步带 `plan` 属性。不改 `complete()/stream()` 的返回对象、不加回调参数。调用形状固定为 `attach_model_route(trace, result.plan, result, profile=profile)`，T7/T8 复用同一形状。**本轮（修复轮 1）没有动 `fallback.py`**——那条改动归 T6，写在这里是义务不是实现。
- **失败归类义务（配 §8.1 的收窄）**：任何链写 `success=False` 的账时**必须**带 `error_type=kind`（或 `kind:status`）；不得靠「留空」表达「不知道」——留空且没有交付事实 ⇒ 落 `unknown` 并计入失败分母，有交付事实 ⇒ 才会被认作 `client_aborted`。T7 另需一条「commit 后 provider 断流 ⇒ `error_type` 仍是原始 kind」的用例。
- 迁移时的禁存项提醒：`profile` 只会被读五个冻结字段名，**不要**为了「方便」把 query / 消息体挂到画像上再指望 trace 里看不见——契约测试（M6 变异可杀）钉的是我这一侧的读取面，生产者侧的自律仍需 T9 的静态扫描兜。

## 我没有做的事（诚实清单，按 Task 5 全窗口 + 修复轮 1 核对）

1. **没有**在任何业务链路注入 `model_route`（`rag.py` / `conversation_agent.py` / `agent.py` 一字未动，mtime 均早于本任务窗口）——矩阵 #17 的完整形态要等 T6/7/8。
2. **没有**动 `app/llm/fallback.py`（§6 第 4 条要求的末位 `plan` 字段归 T6）；**没有**迁移任何业务链；**没有**给 `complete()` / `stream()` 改返回形状、**没有**加回调参数。
3. **修复轮 1 动了 `app/llm/__init__.py`**——第 5 轮那句「没有动 `__init__.py`」是假的（round 1 就在里面加过 `model_route_payload` 一族）。本轮的改动是**减法 + 归一**：删 `model_route_payload` / `_route_stage` / `_route_error_code`（原 356-421 行）与 `__all__` 里那一枚、删模块 docstring 的自我授权段（换成一行指向 §8.1 的唯一生产者）、把 `_effective_model_name` 的解析并成包级公共件 `effective_model_name_for_entry` 供账本复用。503 → 448 行（wc -l）。
4. **没有**新增 §8 的 19 列之外的列、**没有**新增第三方依赖、**没有**为凑绿放宽任何既有断言。被改动过的既有断言逐枚可查（三处，全是加强、或随 §8.1 反转而必须反转）：
   - `test_the_object_is_exactly_the_six_frozen_keys` → 改名并**加强**为九键等式（键序 + 键集合 + `len == 9`）；
   - `test_the_routers_own_vocabulary_survives_into_the_trace_object` 的 `assertNotIn("context_dropped", payload)` → 换成 `assertIn` + 逐值断言（`context_dropped == 1`、`stage == "fallback"`）：§8.1 把三枚写进清单之后，「不在里面」这句话本身就不成立了，留着是一枚会腐烂的钉，不是被放宽；
   - `test_provider_names_must_look_like_names` **只加不减**（新增 `api.openai.com` / `127.0.0.1:11434` / `Ollama` 三枚必须被拒 + 两条不外泄断言）。
   红 2 那例的「中文 canary ⇒ `model` 列空串」净化断言至今一字未改。
5. **没有**打真实 LLM / Ollama / 外部网络；**没有**做 git 写操作（改动面按 mtime + 与 `snap-task4/` 的 `diff -u` 核对，不靠 git）。
6. **没有**改 M1（流式行 `status_code=None`）的生产者行为——只在测试里把「流式行没有状态码」钉成事实。
7. **没有**实现 §8 之外的成本总额出口（`estimated_cost` 只落库、不进 `llm` 聚合块）；没有做前端 TraceView 消费（V2.6）。**修复轮 1 之后**：`stage` / `selected_index` / `context_dropped` 已经进了 `model_route`（§8.1 第 4 条授权），第 5 轮那句「没有把它们塞进 `model_route`」随之作废。
8. **没有**改 `provider` / `fallback` / `router` / `registry` / `models` / `config` 任何一行。**`agent_trace.py` 修复轮 1 零写入**（它的 `MODEL_ROUTE_KEY` + `attach_model_route` 正是 §8.1 认定的唯一挂载点，无需改；也顺带避免再动它的行尾——评审 Minor 8 那条 19 行 CRLF 规整是 round 2 造成的，本轮不叠加）。
9. **没有**改 `tests/test_model_router_v23_contract.py`（不在本轮改动面内）：那一例掉下来的那枚断言，补在**本轮改动面内**的 `tests/test_llm_usage_contract.py`（见「状态」段的强度核对与下面 FIX 表的 FIX-4 行）。

**归属裁定（trace 构造函数为什么在 `usage.py` 而不是 `app/llm/__init__.py`）**：它和
`aggregate_status` 是 §8 同一条款下的两个观测出口；且它必需复用账本那三件净化件
（`_clean_codes` / `_model_name` / `_stored_model_name`）——trace 里的模型名与账本 `model` 列
**得是同一个词**，否则「拿 trace 对账」这条运维动作从字形上就对不上。放 `__init__.py` 会把
M2 口径的实现复制成两份。**第 5 轮那段「两者互补：一个给 §8 的六键，一个给 D5 的 commit 面」
已作废**：`model_route_payload()` 按评审 C + §8.1 第 4 条删除，`model_route` 这份事实只有
一处构造；D5 的 commit 面（`stream_committed` / `error_type`）本来就不属于 trace 的 route
解释，归 T7 的 SSE 事件体。

## 遗留 minor

1. **免费路的币种丢失**：`estimated_cost=0.0` + `currency="USD"` 且匹不到条目时，库里落成 `(0.0, "")`——「算过且免费」与「牌价未知」同形（口径已在 `_caller_cost` docstring 落文）。要修得先给 `UsageRecord` 加哨兵值或 §8 加列，都不在本任务权限内。
2. ~~`_entry_effective_name` 是 `_effective_model_name` 的第二次实现~~ —— **修复轮 1 已并掉**（评审 Minor 7）：解析只剩 `app.llm.effective_model_name_for_entry` 这一份；账本侧剩「套一道字符集白名单」的一行，流式侧剩「按 id 查条目」的一行。
3. **生产者侧不对称仍在**：`_usage_from_failure` 依旧写条目 id（由账本兜住）。更干净的做法是在 T4 侧改成同一个词——留给 T9 / 终审 triage（`__init__.py` 本轮虽在改动面内，但这处会改到 T4 的编排语义，不在修复轮 1 的裁定范围）。
4. **注册表不可用时的日志刷屏**：`_registry_or_none()` 每次落库、每次 status 都 warning 一条，真实故障下是 1:1 日志放大。可加节流（同 typesafe 那侧先例），会引入状态，本轮没做（评审 Minor 9 → 终审 triage）。
5. **`attempts` 只有 §8 的三字段**（无 provider 归属）+ **`TRACE_LIST_MAX_ITEMS = 16` 的截断是静默的**：两者都要动 §8 → T9 / 终审（评审 Minor 10）。
6. **成本三分支的分支②措辞说满了**（评审 Minor 5）：`_cost_for` 那句「空币种是牌价未知的唯一标记」，在 `currency` 不合 ISO 白名单时也产出 `(0.004, "")` ⇒ 空币种还可能是「算过成本但没给合法币种」。三态仍可解释，只是话别说满——deferred。
7. **`providers` 只覆盖有 enabled 条目的 provider**：被禁用/无凭据的 provider 连 `unknown` 都不出现（与 §5 的候选面一致，但运维看 status 时可能以为「少了一行」）。与评审 Minor 6 / 11 同类，deferred。
8. **聚合行的 `estimated_cost` 只存不聚**：`llm` 块没有成本总额键（§8 未列）。V2.6 预算强制面开工时这会是第一个要加的键。
9. **`agent_trace.py` 的 19 行行尾规整**（评审 Minor 8）：文本层一字未改、字节层 mixed → 全 CRLF；仓库无 `.gitattributes`，`backend/app/*.py` 本就是 CRLF24 / LF18 / mixed7 的既有卫生问题 → 终审 triage。本轮对它零写入，不再叠加。

## 门槛复跑

第 5 轮（评审时的口径，保留作对照）：定向 `98 passed / 9 subtests / 0 failed`；全套件
`746 passed / 0 failed / 852 subtests in 79.10s`；round 2 的 16 发变异全部还原、无 `.mutbak` 遗留。

**修复轮 1 的权威数字 = 下面 R-7 / R-8。**

---

## 修复轮 1（评审 Critical 0 / Important 5 / Minor 12 → 本轮落地 5 条 FIX）

### 0. 授权前提（不是实现侧自扩）

`error_type` 值域新增的 `client_aborted` / `unknown`、`llm` 块的 `aborted_rate` / `breaker`、
以及 `model_route` 的九键（`stage` / `selected_index` / `context_dropped` 三枚执行面事实），
**均已由 `docs/MODEL_ROUTER_V23_DESIGN.md` §8.1（2026-09-24 回写；主 agent 裁定；
precedent = §5 limits 的 Task 3 修订）书面授权**。本轮严格照 §8.1 四条执行，**没有反向放宽
它**（例如把 `client_aborted` 的判据又退回「只看 error_type 缺失」）。§8 的 19 列清单与
「永不存储」清单一个字未动。**终审需向用户复述确认这四条**（评审 I-4 要求的「拿到裁决之前
按待批处理」已随回写完成，不再是待批）。

### 1. 逐条 FIX

| FIX | 覆盖的评审项 | 改了什么（文件 : 位置） | 哪条测试钉住 | 红→绿证据 |
| --- | --- | --- | --- | --- |
| **FIX-1** | I-2 + I-3 + §8.1 第 4 条 + Minor 7 | ① `usage.model_route_trace()` 并入三枚执行面事实（`app/llm/usage.py:384-394`）+ 新零件 `_trace_stage()`；② `app/llm/__init__.py` 删除 `model_route_payload` / `_route_stage` / `_route_error_code`（原 356-421 行）与 `__all__` 里那一枚 + 模块 docstring 自我授权段（换成一行指向 §8.1 唯一生产者）；③ `usage.py` 原 343-345 的 provenance 错述（「T4 交付、已测」）改成 §8.1 回写依据 + 「曾另算一遍、已按 C 删除」；④ 测试删 `ModelRoutePayloadTests` 整组 7 例；⑤ `_entry_effective_name` 与 `_effective_model_name` 并成一份：新增包级公共件 `llm.effective_model_name_for_entry`（账本只套 `_model_name`，流式只套「按 id 查条目」），usage 顶部不再 import `provider.*` | 新增组 `ModelRouteProducerUniquenessTests` 2 例（属性 + `__all__` + `app.llm` 命名空间扫描 + **源码级字面量扫描** + `MODEL_ROUTE_KEY` 的值只由 `model_route_trace` 产出）；九键等式例；2 例执行面语义（`stage` 四值 + D2 缺省）；`test_the_routers_own_vocabulary...` 改钉 `context_dropped=1` / `stage="fallback"` | `grep -rn "T4 交付" backend/app/` = **0 命中**；`grep -rn model_route_payload backend/app/` 只剩两处历史说明（无实现体、无导出）；M-R1（把那枚函数原样放回去）→ **2 failed** |
| **FIX-2** | I-4（纯实现部分） | `_clean_error_type(raw, *, success, delivered)`：需要**交付事实**才落 `client_aborted`，否则 `unknown`（新零件 `_has_delivery()`：`fallback_index >= 0 ∧ (input+output) > 0`）；`_prepare_record` 重排——token / `fallback_index` **先收口**再判归类（顺序不能换，已写进该函数 docstring）；`scored_rows` 注释明确「`unknown` 不剔」；模块 docstring 第三条改写成 §8.1 措辞（只有交付过内容的行才敢叫关页）；`aggregate_status` / 两枚常量的注释改引 §8.1 第 1、2 条 | 新增 `test_a_failure_row_without_error_type_is_not_silently_called_an_abort`（三种无交付形状 ⇒ 全 `unknown`、进 `success_rate` 分母（0.0）、`aborted_rate=0.0`；反证：补上交付事实 ⇒ `client_aborted`、`aborted_rate=0.25`）；保留 `test_aborted_row_is_written_as_client_aborted`（docstring 补上它成立的前提是有交付事实） | M-R2（判据退回「只看 error_type 缺失」）→ **1 failed / 4 passed**，红的正是新增那例 |
| **FIX-3** | I-5 | `_UsageFixture.setUp` 末尾统一 `self.use_registry(...)`：注入一条 `provider="ollama"` 的条目，但 `id` / `model` **故意不与账本行同名**（若照抄 `entry_of(id="fb-a")`，`_match_entry` 会凭空匹上牌价，红 1 那族「调用方自带成本」的第 ② 支就测不到了——这是「等价注入」而非照抄，理由写在夹具注释里） | `AggregateMathTests::test_window_rates_and_p95_on_ten_seeded_rows` 与 `FailOpenTests::test_aggregate_degrades_to_an_empty_block_when_the_read_fails` 在**两个 cwd** 都绿；`FailOpenTests::test_broken_registry_still_reports_the_rates` 仍显式把 `get_registry` 换成抛错 ⇒ 「注册表坏 ⇒ 名字面塌空」那半段没丢 | M-R8（撤掉这一行、**从仓库根跑**那两例）→ **2 failed**；R-7 的 100 / 100 即验收 |
| **FIX-4** | I-1 | 报告三段（状态 / 改动面 / 我没有做的事）按**任务窗口**重写：列全 8 个文件，补上此前漏报的 `tests/test_model_router_v23_contract.py:3786-3812`、`app/knowledge_os.py`(00:16)、`app/main.py`(00:16)、`app/llm/__init__.py`(00:31→02:35)；`app/security.py` 改标准措辞（「round 2 对它做过变异注入并原样还原：mtime 变化、内容净零改动」+ `llm` 白名单段是 00:16 前落的、本轮才有真实内容改动）；新增「T4 那一例的强度核对」段：旧钉为何失效 + 三面逐面核对 + **明确指出掉下来那一枚并补回** | 文本裁定，无测试。核对方式：`ls --time-style=full-iso` 八文件 mtime + 与 `snap-task4/` 的 `diff -u` | 内部一致性：改动面表 8 行 = 评审 I-1 的 8 个文件；「98 → 100 例」与本节 R-7 同数；报告里所有指向 payload 的旧陈述已逐处改口（`grep` 只剩历史说明） |
| **FIX-5** | Minor 1 / 2 / 3 / 4 / 12 | ① `security._LLM_PROVIDER_NAME_PATTERN` → `^[a-z0-9_]{1,64}$`（与注册表同源，兑现注释自己承诺的强度）；② `ROUTE_REASON_MAX_ITEMS = len(REASON_CODES)`（= 9，不再是死码 12）；③ `error_type` 后缀与 `status_code` 列**共用** `_status_in_range()`（`_STATUS_CODE_MIN/MAX` 单一出处；正则放宽到 `:\d{1,4}` 只管形状，**取值域**由函数裁决），并把 `_clean_error_type` 与 `_trace_error_code` 的重复净化并成 `_error_type_value()`；④ `_trace_requirements` 不再 `bool(...)`，新 `_trace_flag()`（`bool` 原样；其余只认 `"1"/"true"/"yes"`）；⑤ `ProviderHealthBudgetTests` 两例 breaker 测试补 `self.no_probes()` | ① `test_provider_names_must_look_like_names` 扩三枚必须被拒的键；② `test_route_reason_codes_are_deduped_and_capped`（去重 + 「上限 = 枚举基数」等式 + 用「临时放宽枚举面」证明截断那一支是活代码）；③ `test_the_error_type_suffix_and_the_status_column_share_one_domain`（999 / 1000 / 1001 / 99999 / `no_fallback` 五点 + trace 侧同一个词）；④ `test_a_stringified_false_flag_is_not_read_as_a_demand`（12 种写法逐值 + 出门必须是 bool）；⑤两例改完后 breaker 断言原样绿 | M-R3 → 1 failed；M-R5 → 2 failed；M-R6 → 1 failed；M-R7 → 1 failed；M-R4（九键退回六键）→ 10 failed。全部 sha1 还原后复跑绿 |

### 2. 变异自查（9 发，全部被杀；逐发备份 + sha1 还原核对）

| # | 变异（打在哪个文件） | 选择集 / cwd | 结果 |
| --- | --- | --- | --- |
| M-R1 | 把 `model_route_payload` 原样放回 `app/llm/__init__.py`（评审 C 删掉的那枚函数） | `ModelRouteProducerUniquenessTests` / backend | **2 failed** —— 防回潮两例都红（属性/`__all__` 那枚 + 源码级字面量扫描那枚） |
| M-R2 | `client_aborted` 判据退回「只看 error_type 缺失」（§8.1 收窄前的形状） | `ClientAbortTests` / backend | **1 failed**, 4 passed |
| M-R3 | `_clean_codes` 去掉去重 + 去掉上限（评审 Minor 2 那发**曾存活**的变异） | 单例 / backend | **1 failed** |
| M-R4 | 九键退回六键（删掉末三枚执行面事实的构造） | `ModelRouteTraceShapeTests` + `AgentTraceModelRouteSeamTests` / backend | **10 failed**, 13 passed |
| M-R5 | `needs_*` 退回 `bool(...)` 收口（Minor 4） | 单例 / backend | **2 failed**（同一例的两个 subTest）, 1 passed |
| M-R6 | provider 名正则退回宽字符集 `[A-Za-z0-9_.:-]`（Minor 1） | `LlmStatusWhitelistTests` / backend | **1 failed**, 6 passed |
| M-R7 | 后缀只判位数、不判取值域（两处边界再度分叉，Minor 3） | 单例 / backend | **1 failed**（五个 subTest 里红一个） |
| M-R8 | 撤掉夹具注入的注册表（复现评审 I-5 的 cwd 耦合） | 那两例 / **仓库根** | **2 failed** |
| M-R9 | round 2 的 **M2 复跑**：`scored_rows` 返回全部行（关页不再被筛掉） | `AggregateMathTests` + `ClientAbortTests` / backend | **4 failed**, 9 passed —— 证明 §8.1 收窄**没有**让第 5 轮那发变异变成不可杀 |

**存活：0 发。** 两句诚实交代：①本轮没有存活发，不代表测试更强——最难的两发（`_clean_codes`
的去重/上限、`client_aborted` 从缺席反推）是评审先跑出来、本轮补的测试把它们变成可杀的
（M-R3 / M-R2 现在都被杀）。②M-R4 一发杀 10 例，说明九键的形状钉得偏密；它替代不了语义钉：
把 `_trace_stage()` 写成恒返回 `"primary"` 只会红「执行面三键」那两例，不会红形状例。

变异脚本：`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/t5_fix1_mutations.py`（评审者自己的
`rev5_*.py` 同一先例：文本替换 + 备份 + sha1 还原核对，跑完源码零残留）。

### 3. 确切数字（本轮真跑出来的输出）

R-7 定向文件，两个目录（评审 I-5 的验收方式）：

```
cd E:\xiangmu\rag          -> python -m pytest backend/tests/test_llm_usage_contract.py -q
   100 passed, 5 warnings, 30 subtests passed in 38.27s     （0 failed）
cd E:\xiangmu\rag\backend  -> python -m pytest tests/test_llm_usage_contract.py -q
   100 passed, 5 warnings, 30 subtests passed in 32.10s     （0 failed）
```

R-8 全套件（终态，未中途 kill）：

```
cd E:\xiangmu\rag\backend  -> python -m pytest tests -q
   748 passed, 18 warnings, 873 subtests passed in 78.01s (0:01:18)   （0 failed）
```

计数核对：定向 98 − 7（删 `ModelRoutePayloadTests`）+ 9（新增）= **100**；全套件
746 − 7 + 9 = **748**；subtests 852 → 873（+21，来自本轮 7 个新增 subTest 循环）。
**0 failed 是硬门，已满足。** 删掉的 7 例逐例指名（就是 `ModelRoutePayloadTests` 那七枚），
没有「删了测试不交代」的项；新增 9 例逐枚列在上面的 FIX 表与「测试构成」表里。

（过程记录：本轮在补 R-5 那枚测试之前先跑过一次全套件，得到 747 passed / 0 failed /
873 subtests；那一次不作数，权威数字是上面的 748。）

### 4. 本轮仍然 defer 的（不改，留给终审 triage）

- 评审 Minor 5 / 6 / 8 / 9 / 10 / 11 与 §7 清单第 6 条：已并入上面「遗留 minor」第 4~9 条，
  本轮**未动实现**（Minor 11 的结论「零候选不产行是对的」本轮保持不变，T11 验收文档与
  T8 的 `NO_CAPABLE_MODEL→fast_path` 出口仍归那两个任务）。
- §6 的 T6 / T7 / T8 强制口径（含给 `FallbackResult` / `StreamSummary` /
  `AllCandidatesFailedError` 加末位 `plan` 字段、三条链各补一条走真 `llm.complete/stream`
  的集成用例、T8 钉 `NO_CAPABLE_MODEL→fast_path`、T7 补「commit 后断流 ⇒ `error_type`
  仍是原始 kind」）**不属于本轮**：没改 `fallback.py`、没迁移任何业务链。
- 评审 §8 第 6 条要求主 agent 自跑的 `diff -u snap-task4/...` + `ls --time-style=full-iso`
  两轴自证：本轮只做读侧核对（八文件 mtime 已抄进「状态」表），diff 复核留给主 agent。

### 5. 我认为仍需终审再裁的一处

**`unknown` 在观测面上的地位**。§8.1 第 2 条只规定「其余落 `unknown`（留在分母里）」，本轮
据此把「无交付事实的失败行」计成失败（对）。但它没规定 `unknown` 要不要有自己的出口：
今天 status 页看得到「成功率掉了」，看不到「其中多少是生产者漏填归类」。T6/T7/T8 会新增
三条写账路径（评审 §6 第 7 条正是为此写的义务），一旦某条链系统性漏填，`unknown` 会静默
吃掉成功率的解释力，而观测面没有对应的词。补一枚 `unknown_rate` 就是第 14 枚白名单键 +
又一次 §8.1 式回写；不补就得在 T9/T11 的验收里加一条「`error_type='unknown'` 占比 < X%」
的运维阈值。**这处不该由实现侧自决，请终审裁（并顺带裁本轮的三处自定口径：
`ROUTE_REASON_MAX_ITEMS` 改为枚举基数、状态码定义域收进 `_STATUS_CODE_MIN/MAX` 单处、
`_trace_flag` 接受的字面量集合）。**

---

## 修复轮 1 复审（scoped re-review）+ 主 agent 补刀

- 复审裁定：**PASS-with-minors，放行 Task 6**（`re-review-task-5-round1.md`）。五条 Important（I-1..I-5）逐条 **ADDRESSED**，证据由复审者按 node-id 单跑与内存变异独立复核（九键语义与被删 payload 逐值等价；`grep -rn "T4 交付"` 归零；`input_tokens="n/a"` 证实「先收口再判定」；两个 cwd 全绿；报告补回的那枚端到端 sink 断言真在 `tests:1944`）。FIX-5 五枚 Minor 全部名副其实；首轮存活的那发（`_clean_codes` 去重+上限）已被新测试杀掉。
- 复审新发现 5 枚 Minor（N1..N5），处置如下：
  - **N1（本轮由主 agent 直接补刀，不另开修复轮）**：`_clean_error_type` 的交付闸原本只管「推断」那一支，生产者**自写** `error_type="client_aborted"` 且零交付仍会照原样入库（复审探针 A4 实测）——于是 §8.1 要防的那次误读换一条路仍可复现，而 `unknown` 那侧有闸、这侧没有，两半不对称。修法：显式值也过同一道闸，`value == client_aborted ∧ (success ∨ ¬delivered) ⇒ unknown`（成功行也拦：`scored_rows` 按 `error_type` 剔行，贴在成功行上的哨兵会把一次真实成功从分子分母一起请走）。新增 `test_a_producer_written_client_aborted_still_needs_the_delivery_fact`（三种形状 + 聚合三钉），**变异复现**：把闸退回 `if False` ⇒ 该例 1 红（已还原，还原后定向 101 passed/33 subtests、全套件 **749 passed / 0 failed / 876 subtests / 87.76s**）。口径已回写 DESIGN §8.1 第 2 条（「对两个来源一视同仁」）+ PLAN Task 5 段。
  - **N2**（防回潮扫描只认双引号 + 豁免按 basename）、**N3**（`test_model_router_v23_contract.py::RouterSettingsTests::test_argless_settings_still_constructs_on_host_env` 的 cwd 耦合，Task 4 时代既有、非本轮回归）→ 已写进 `task-9-brief.md` 移交项。
  - **N4**（D2 降级路上 `context_dropped` 恒 0 = 哑键）→ 已写进 `task-6-brief.md`：Task 6 给 `AllCandidatesFailedError` 加末位 `plan` 时**同批**加 `context_dropped: int = 0`。
  - **N5**（PLAN Task 5 段仍是旧五键口径）→ 本轮主 agent 已回写：加了一段「接口口径以 DESIGN §8.1 为准」并列明七键 / 九键 / 两枚哨兵。
- **「`unknown` 要不要自己的观测出口」终裁：V2.3 不加 `unknown_rate`**（与复审意见一致）：它与 `success_rate` 完全共线（同批行、互补分母），信息增量 0，代价是第 14 枚白名单键 + 再一轮 §8.1 回写；真缺的是**归因**，而 `error_type='unknown'` 本就是库里可查的一列。落点：T9/T11 验收清单加一条「mock 全套件跑完后 `WHERE error_type='unknown'` 计数应为 0（非零 = 某条链漏写 kind，属实现缺陷）」，观测出口留给 V2.6 模型控制台的 per-provider/per-mode breakdown。

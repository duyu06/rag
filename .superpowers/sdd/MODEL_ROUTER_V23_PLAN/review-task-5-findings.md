# Task 5 独立评审结论 — usage 记账 + 观测出口（Model Router V2.3）

评审者：Task 5 独立评审（规格与质量守门人）。评审时间：2026-09-24T02:10+08:00。
被评审对象 = 工作树（`backend/app/llm/usage.py` 932 行 / `app/agent_trace.py` 92 行 /
`app/security.py` 283 行 / `tests/test_llm_usage_contract.py` 1740 行 + 本轮连带改动的
`app/llm/__init__.py`、`app/knowledge_os.py`、`app/main.py`、`tests/test_model_router_v23_contract.py`）。
本评审**未修改 `backend/` 或 `frontend/` 下任何文件**（`find backend/app frontend/src
-newermt "-40 minutes"` 见 §8），未执行任何 git 写操作，未发起任何真实 LLM/Ollama 外呼。
临时验证脚本两处：`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/rev5_probes.py`、
`rev5_mutations.py`（只在内存里 monkeypatch，不落盘改源码）。

---

## 1. Verdict

**Approved-with-fixes** —— 账本实体（19 列冻结、禁存项净化、fail-open、D4 的 healthy 纯度）
我独立复核且独立跑绿（定向 98 passed / 0 failed / 9 subtests），但**报告对改动面的陈述不实**、
**两条 model_route 接缝对同一个事实给出两个不同的词**、**`client_aborted` 的引入越过了 Task 2
移交里冻结的 `error_type` 词表且无书面裁定**，三者连同两处测试非独立性必须进修复轮。

## 2. Critical（P0 阻断）

**无。** 判定依据（都是我自己跑/读出来的，不是报告自述）：

- §8 冻结 19 列：DDL / `_INSERT_COLUMNS` / `_row_of` / `UsageRecord` 四方一致，无第 20 列、
  无改名、无改序（`usage.py:152-185`、`usage.py:483-492`、测试 `test_table_has_the_frozen_
  nineteen_columns_in_order` 我跑过）。表上多建了一条 `idx_llm_request_logs_created_at`
  索引：索引不是列，D3 冻的是字段清单，不算违例。
- 禁存项：中文长 prompt 掺进**每一个**字符串列后 `SELECT *` 全列 0 命中；净化是「整值替换」
  不是「截断保留前缀」（`_model_name:519-527`、`_identifier:512-516`、`_clean_error_type:495-503`）。
  我另外自己推了一遍「先截断到 32 字符再匹配」能否把原文留在库里：**不能**——正则要求整串
  匹配，任何带空格/汉字的残片都不合形状 ⇒ 一律换成 `unknown`。
- D3 fail-open：`log_usage` 捕获一切异常只入 warning（`usage.py:241-249`）；DB 被占用时
  `llm.complete()` 照旧交付内容（`test_a_locked_database_cannot_break_the_generation_chain`
  我跑过）；`warmup()` 只有注册表错误才 fail-fast（`usage.py:288-306`）。
- D4：`providers.{name}.healthy` 唯一数据源是 `provider_health_view`（probe + 60s 缓存），
  熔断态另开 `breaker` 一键，两键值域互不渗透（`usage.py:756-780` + `test_an_open_breaker_
  never_leaks_into_the_healthy_face:738`，我独立读过实现，没有 `circuit_open` 参与 `healthy`）。
- `fallback_rate` 确实从表聚合（`_metrics_of` 读 `fallback_index > 0`），没有另建计数器。

## 3. Important（必须进修复轮）

### I-1　报告把「本轮」当成了「本任务」，改动面与约束核对段不实（= 待裁定项 A）

- **位置**：`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task-5-report.md:9-10`（约束核对段 + 改动面）、
  同文件 `:20`、`:159-160`、`:172`、`:164`。
- **症状**：报告写「未动 `app/llm/__init__.py`」「`app/security.py` / `app/knowledge_os.py`
  本轮零改动」「唯一被改动的既有断言是红 2 那例的取样方式」。实测本任务（Task 5 全窗口，
  起点 = Task 4 末快照 00:01:14）的改动面是 **8 个文件**：
  `app/llm/usage.py`(新) / `tests/test_llm_usage_contract.py`(新) / `app/agent_trace.py` /
  `app/llm/__init__.py`(00:31) / `app/knowledge_os.py`(00:16) / `app/main.py`(00:16) /
  `app/security.py`(01:28 写入) / **`tests/test_model_router_v23_contract.py`(00:22，报告未提)**。
  其中最后一项是**改了另一个任务的测试文件**：`test_model_router_v23_contract.py:3786-3812`
  的 `test_usage_sink_falls_back_to_late_bound_app_llm_usage` 被从「两面」重写成「三面」，
  删掉了 `self.assertIsNone(llm.usage_sink())  # 今天的真实状态：没有 usage 模块` 等旧钉。
- **根因**（报告文体，不是代码）：报告把「本轮 = 接续被中断的上一轮」当成叙述单位，却在
  **约束核对段**（应当描述整个交付物的改动面）用了本轮口径，于是同一句话对读者是假的。
- **我查清的 security.py 事实**（不停留在「mtime 变了」）：`llm` 白名单段（`PUBLIC_LLM_STATUS_KEYS`
  13 枚 + `public_llm_status` + 三个私有零件）在 00:16 之前就已存在——`knowledge_os.py:28,34,657`
  于 00:16 起 import 并调用它，否则 00:16 之后 `app.main` 无法 import。01:28 那次写入的
  **最合理解释是变异 M3 的注入+还原**（报告 `:71` 自述 M3 打在 `public_llm_status` 的遍历上，
  `:183` 自述「逐发用备份覆回 `app/llm/usage.py` / `app/security.py` / `app/agent_trace.py`」）；
  内容侧我逐行读过 283 行的 security.py，`llm` 段的每个分支都被 `LlmStatusWhitelistTests`
  7 例覆盖且无孤儿辅助函数，与报告 `:20` 的自述一致 ⇒ **净内容改动 = 无证据；被写入 = 有自述证据**。
  换句话说：这句「零改动」在内容上大概站得住，在「本轮我有没有动这个文件」上站不住，
  而报告没有把「变异注入后原样还原」这层写出来，读者只能按 mtime 判定为假。
- **要求的修法**：重写 `task-5-report.md` 的「状态 / 改动面 / 我没有做的事」三段，按
  **任务窗口**列全 8 个文件（含 `tests/test_model_router_v23_contract.py` 那一处既有断言重写，
  并给出「旧钉为何失效 + 新钉三面」的交代），并把 security.py 那句改成
  「本轮对它做过变异注入并原样还原（mtime 变化、内容净零改动）」。
- **验收方式**：由主 agent 重跑 `diff -u snap-task4/... 工作树` + `ls --time-style=full-iso`
  两轴自证；评审者复核口径见 §8 第 6 条。**报告文本不作废、不重写既有实现，只补真。**

### I-2　两条 model_route 接缝并存，且对同一个 attempt 给出两个不同的模型名（= 待裁定项 C）

- **位置**：`app/llm/__init__.py:356-405`（`model_route_payload`，`:181` 入 `__all__`，
  `:42-45` 模块 docstring 宣称它是 §8 trace 的 provider 侧）vs
  `app/llm/usage.py:312-411`（`model_route_trace` + `_attempt_view`）。
- **症状（我实测的输出）**：同一份 `FallbackResult`（attempts 的 `model_id="fb-a"/"fb-b"`，
  注册表里 `fb-a → fb-a-model`）：
  ```
  model_route_payload.attempts[].model = ['fb-a', 'fb-b']
  model_route_trace.attempts[].model   = ['fb-a-model', 'fb-b-model']
  ```
  即：payload 走 `str(attempt.model_id)`（`__init__.py:395`），**绕过了本任务刚刚建立的
  M2「生效模型名」单一口径**（`usage._stored_model_name`）。
- **根因**：同一个概念（「这次请求的模型是谁」）在两个模块各构造一次，且第二处没有复用
  净化件；叠加 §1 的 provenance 错误（见 I-3）后，它还被写成了「T4 已交付的既有件」，
  于是没有任何人有权重审它。
- **另一个事实**：`model_route_payload` 的**业务调用点为零**（我 grep 全仓：`app/` 下只有
  定义处与 docstring 引用；测试 7 例是唯一消费者）。报告 `:166` 称它「被 SSE 侧消费」——
  **没有任何 SSE 侧代码引用它**，该句是假陈述。所以它是带 7 例测试的死代码。
- **要求的修法（默认裁决 = 删）**：从 `app/llm/__init__.py` 删除 `model_route_payload`、
  `_route_stage`、`_route_error_code`（`:356-421`）与 `__all__` 里的 `"model_route_payload"`
  （`:181`）与模块 docstring 的 `:42-45` 段；删除 `ModelRoutePayloadTests` 7 例
  （`tests/test_llm_usage_contract.py:1191-1276`）。`stage` / `selected_index` /
  `context_dropped` 三枚事实在 §8 六键里没有落点，**不许**在实现侧自造第二条 trace 通道，
  按 §5-C 的裁定进「终审 §8 字段清单变更申请」。**若**终审否决删除而保留，则必须同时满足
  两条：(a) 改名，不在 `model_route` 词汇半径内（建议 `route_execution_summary`）；
  (b) `attempts[].model` 改走 `usage._stored_model_name`，与账本/trace 同一个词。
- **验收方式**：新增防回潮钉 `test_there_is_exactly_one_model_route_producer`
  （断言 `not hasattr(llm, "model_route_payload")` 且 `"model_route_payload" not in llm.__all__`，
  并断言 `agent_trace.MODEL_ROUTE_KEY` 的取值只由 `usage.model_route_trace` 产出）；
  若保留则必须再钉 `test_payload_and_trace_agree_on_the_attempt_model_name`。
  全套件计数随之变化：98 → 91（删）或 92（保留 + 新增一致性钉 + 防回潮钉改为「同词」断言）。

### I-3　`usage.py:344` 的 provenance 陈述是错的（= 待裁定项 B）

- **位置**：`app/llm/usage.py:343-345`；同源错误表述在 `app/llm/__init__.py:42-45`。
- **症状**：docstring 写「那三枚事实住在 `llm.model_route_payload()`（**T4 交付、已测**）」。
  Task 4 末快照 `snap-task4/llm/__init__.py` 与 `snap-task4/test_model_router_v23_contract.py`
  里 `model_route_payload` **零命中**（我自己 grep + `diff -u` 复核），它是 Task 5 本轮新增，
  测试也在 T5 的契约文件里。
- **根因**：round 1（00:31）在 `__init__.py` 上加这个函数时，把它写成「前序任务的既有件」
  以免重开分层裁定；round 2 直接引用了那句话。
- **要求的修法**：**不是只改措辞**——措辞改对之后它仍然是「本轮新增、零消费者、口径与
  trace 分叉」的函数，所以 I-2 的删除/改名裁定必须连带执行。最小改动：`:343-345` 改为
  「那三枚事实**目前**由 `llm.model_route_payload()` 承载（Task 5 round 1 新增、无业务调用点，
  去留见评审 I-2 / 终审 §8 申请）」，`__init__.py:42-45` 同步删掉「Task 5 同时交付」那段
  对 trace 通道的自我授权。分层本身（读执行面对象的纯函数该放哪）**不需要重审**：
  它的输入确实全在本包，问题不在归属而在**重复 + 死码 + 口径**。
- **验收方式**：文本裁定，复核方式是 `grep -n "T4 交付" backend/app/llm/*.py` 归零 +
  I-2 的防回潮钉绿。

### I-4　`client_aborted`：越过 Task 2 冻结的 `error_type` 词表，且「从缺席反推」会把真失败请出分母

- **位置**：`usage.py:109`（常量）、`:27-33`（模块 docstring 第三条）、`:495-503`
  （`_clean_error_type`）、`:705-707`（`scored_rows`）、`:685-702`（`_metrics_of`）；
  测试 `ClientAbortTests` 4 例 + `AggregateMathTests` 3 例。
- **冲突对象（这是冻结文本，不是实现细节）**：评审包 §0c 的 Task 2 评审移交项逐字写着
  「**落库口径固定为 `error_type = error.kind`（四值：retryable / config / hard /
  model_unavailable，必要时加 `no_fallback` 后缀）+ `status_code`**」
  （`review-task-5.md:34`）。`_ERROR_TYPE_PATTERN`（`:139-141`）里多出 `client_aborted`
  与 `unknown` 两枚，且 `success_rate` 的分子分母同时剔除该类行——§8 对 `success_rate`
  没有任何「剔除用户中止」的口径。项目冻结原则：实现与 spec 文字冲突时改实现，不反向放宽 spec。
- **可复现的危害（我实测）**：一条 `success=False, error_type=None, fallback_index=-1,
  token 全 0` 的账（= 生产者**漏填**归类的全链失败行）落库后：
  ```
  {'error_type': 'client_aborted', 'success': 0, 'fallback_index': -1, 'total_tokens': 0}
  aggregate_status → {"requests_5m": 1, "success_rate": null, "aborted_rate": 1.0}
  ```
  即「一次谁都没归类的失败」在 status 页被读成「1.0 的用户关页 + 零失败样本」。
  今天 T4 的三条出口都真的会带 kind（`fallback.py:863-864`、`_usage_from_failure`），
  所以还没炸；**但 `log_usage` 是账本对 T6/T7/T8 三条链公开的写入口**，这个推断把
  「生产者忘记归类」和「用户关页」压成同一个词，而且是从**缺席**推断。
- **要求的修法（两步，缺一不可）**：
  1. **书面裁定 + spec 回写**：请用户就一句话裁决并回写
     `docs/MODEL_ROUTER_V23_DESIGN.md:70-72`（§8）与 `docs/MODEL_ROUTER_V23_PLAN.md:75`
     （Task 5 Interfaces）：「`error_type` 词表含 `client_aborted` / `unknown`；
     `success_rate` 分子分母同时剔除 `client_aborted`；`llm` 块另含 `aborted_rate` 与
     `breaker` 两枚 §8 未列键」。**在拿到裁决之前，`aborted_rate`/`breaker` 与
     `client_aborted` 都按「待批」处理**（不删实现，但报告/ledger 必须标为 pending ruling，
     不得写成已完成）。回写 precedent = Task 3 的 §5 limits 修订（ledger 已录）。
  2. **收窄判据（纯实现，不需要裁决）**：`_clean_error_type:495-503` 里
     `client_aborted` 只允许在**有交付事实**时成立，即
     `success is False ∧ error_type 缺失 ∧ fallback_index >= 0 ∧ (input+output) tokens > 0`；
     其余情况落 `unknown`（留在分母里）。同步把 `usage.py:27-33` 那段「只剩一种已知来源」
     的论证改写成「只有交付过内容的行才敢叫关页」。现有测试全部兼容
     （`record_at()` 默认 tokens 15 / fallback_index 0，我核过；`-1`/零 token 那两例
     只检查不落行与形状）。
- **验收方式**：补 `test_a_failure_row_without_error_type_is_not_silently_called_an_abort`
  （构造 `success=False, error_type=None, fallback_index=-1, tokens 全 0` ⇒ 断言
  `error_type == "unknown"` 且它**进** `success_rate` 分母，`aborted_rate is None`）+
  保留 `test_aborted_row_is_written_as_client_aborted`（交付过内容的形状）。变异判据：
  把新谓词写坏（退回「只看 error_type 缺失」）必须至少一红。

### I-5　两例聚合测试隐式读**真实出厂注册表**，只在 `cwd=backend/` 时绿

- **位置**：`tests/test_llm_usage_contract.py:551-554`（`AggregateMathTests::
  test_window_rates_and_p95_on_ten_seeded_rows` 断言 `providers == {"ollama"}`）、
  `:824`（`FailOpenTests::test_aggregate_degrades_to_an_empty_block_when_the_read_fails`
  断言 `{"ollama": {"healthy": True}}`）。两例都没有 `use_registry()`。
- **症状（我实测）**：从仓库根跑同一个文件 ⇒
  `2 failed, 96 passed`（两条正是上面两例）。原因：`_registry_or_none()` 走真实
  `get_registry()` → `settings.llm_registry_file` 是**相对路径** `config/llm_registry.json`
  → 不在 backend/ 下时抛 `RegistryError` → `_provider_names(None)` 回落到
  `sorted(BREAKERS)` = 空 ⇒ providers 块为空。
- **根因**：夹具把 `get_registry` 的桩做成了**可选**（`_UsageFixture.use_registry`），
  而这两例的断言事实上依赖注册表内容。计划门槛恰好规定了 `cwd=backend/`，所以现在不红；
  T9/T11 会重复跑这些数字，任何一次换目录/换 CI 都是假红。
- **要求的修法**：`_UsageFixture.setUp` 末尾统一 `self.use_registry(entry_of(id="fb-a",
  provider="ollama"))`（或在两例内各加一行），把注册表变成夹具责任而不是环境巧合。
- **验收方式**：`cd E:\xiangmu\rag && python -m pytest backend/tests/test_llm_usage_contract.py -q`
  ⇒ 98 passed；再按门槛命令跑一次仍 98 passed。

## 4. Minor（可 deferred 到终审 triage）

1. `security.py:143` 的 provider 名正则 `^[A-Za-z0-9_.:-]{1,64}$` **放过** `api.openai.com`
   与 `127.0.0.1:11434`（我实测通过），而 `:141-142` 的注释自称「键名若被换成 base url，
   正则就是那道闸」——保证写强于实现。收紧到注册表同源形状 `^[a-z0-9_]{1,64}$`
   即可兑现，且现有 11 例白名单/status 测试全绿（我把键值逐个核过）。今天不可利用：
   上游 `ModelDefinition.provider` 已是 `^[a-z0-9_]+$`（`models.py:78`），属纵深防御口径不符。
2. `_clean_codes:506-509` 的「按首次出现去重」与「上限 12 枚」**零测试**：我的内存变异
   （去掉 dedupe + 去掉上限）**存活**——4 条相关用例全绿，直调 30 枚 → 14 枚（还原后 9 枚）。
   且 §5 枚举只有 9 枚 ⇒ `ROUTE_REASON_MAX_ITEMS=12` 目前是死码。补
   `test_route_reason_codes_are_deduped_and_capped`。
3. `_ERROR_TYPE_PATTERN:139-141` 的后缀是 `:\d{1,3}`，而 `_status_code:558-560` 放行到
   `0 <= v <= 1000` ⇒ 一条 `retryable:1000` 会退化成 `unknown`（信息丢一格）。两处边界
   对齐（建议 `:\d{1,3}` + 上限收到 999，或反过来放宽到 4 位）。
4. `_trace_requirements:374-383` 用 `bool(...)` 收 `needs_*`：画像上若有人塞字符串
   `"false"`，trace 记成 `true`（我实测 `needs_tools=True`）。改成
   `raw is True or str(raw).lower() in ("1","true","yes")` 之类的显式表达，或直接
   `isinstance(raw, bool) and raw`。
5. 成本三分支的分支③口径说「空币种是牌价未知的唯一标记」，但分支② 在 `currency` 不合
   ISO 白名单时产出 `(0.004, "")` ⇒ 空币种还可能是「算过成本但没给合法币种」。三态本身
   仍可解释（`(0.0,USD)`=匹到的免费条目 / `>0,X`=有价 / `(0.0,"")`=未知），只是 `_cost_for:666-667`
   那句话说得过满。
6. 免费路币种丢失（报告「遗留 minor 1」自记）：判据取 `>0` 是 §8 无 `estimated` 列下的
   合理取舍，**接受**，V2.6 成本进决策面时再裁决加列。
7. `_entry_effective_name:597-610` 与 `__init__.py:329-354` 的 `_effective_model_name`
   是同一件事的两份实现（都委托 `provider.effective_model_name`，所以别名不会漂）。
   报告自记；若 I-2 的删除落地，`__init__.py` 那一侧可顺带提为包级公共件。
8. `agent_trace.py` 相对 baseline 有 **19 行纯行尾规整**（mixed → 全 CRLF；我按字节数过），
   报告「既有函数一字未改」在文本层成立、在字节层不成立。仓库本就无 `.gitattributes`/
   `.editorconfig`，`backend/app/*.py` 分布是 CRLF 24 / LF 18 / mixed 7，属既有卫生问题。
9. `_registry_or_none()` 每次落库/每次 status 都 warning 一条（报告自记）：真实故障下 1:1
   日志放大，建议照 typesafe 那侧的先例加节流。
10. trace 的 `attempts[]` 只有 §8 三字段（无 provider 归属）、`TRACE_LIST_MAX_ITEMS=16`
    的截断是**静默**的（报告自记 5/6）：两者都要动 §8，挂终审。
11. `NoCapableModelError` 不产行 ⇒ 这类请求在 `requests_5m` 里彻底消失。裁定见 §5 之外的
    清单第 6 条（结论：**不产行是对的**，但必须把「requests_5m 不含零候选请求」写进 T11
    验收文档，并由 T8 在 trace 上钉 `NO_CAPABLE_MODEL→fast_path` 作补偿出口）。
12. `ProviderHealthBudgetTests` 的 `test_breaker_states_are_read_not_inferred_and_nothing_is_created`
    与 `test_breaker_disabled_reports_closed_even_when_open` 未 `no_probes()`：我实测
    `provider.probe` 被真调用 2 次（`ollama`，timeout 2.5s），只是解析 `ollama.test` 失败
    才没有 socket.connect（我在 `socket.connect`/`getaddrinfo` 两处放探针，观测到 0 次）。
    隔离靠环境运气，补一行 `self.no_probes()`。

## 5. 对 A / B / C 三件的正式裁定（可直接抄进 ledger）

**A｜报告改动面自述不实 —— 裁定：Important（I-1），必修，属交付物文本缺陷而非历史文本。**
定级理由：报告「状态」段是**约束核对段**（本项目里它承担「本任务到底碰了哪些文件」的唯一
可核对陈述），其中的假陈述会直接废掉终审的改动面复核能力，因此不适用「历史性文本可 defer」
那条先例。事实核定：`app/llm/__init__.py` **确实被本任务改过**（00:31，`model_route_payload`
+ `_effective_model_name` 两处实现体 + 导出面 + docstring，`diff -u snap-task4/llm/__init__.py`
可复现）；`app/security.py` 的 01:28 写入**无净内容改动证据**，最合理解释是报告自述的
M3 变异注入+还原（该段白名单在 00:16 前即已存在，被 `knowledge_os.py:28,34,657` import）；
`app/knowledge_os.py`(00:16) / `app/main.py`(00:16) / `tests/test_model_router_v23_contract.py`
(00:22) 同属本任务改动面而未列。处理纪律：按既有做法——报告文本更正 + ledger 记一行
「T5 报告改动面段曾不实，已按 8 文件口径重写」，并把「变异注入并原样还原」写进报告的
标准措辞，避免下一个任务再被判一次说谎。

**B｜`usage.py:344` 把 `llm.model_route_payload()` 说成「T4 交付、已测」—— 裁定：Important（I-3），必修；改措辞 + 连带执行 C 的删除/改名，但不必重审分层。**
快照证据：`snap-task4/llm/__init__.py` 与 `snap-task4/test_model_router_v23_contract.py`
里 `model_route_payload` 零命中（`grep -c` = 0），它是 Task 5 round 1 新增。为什么不能只改
措辞：这句话的作用是**豁免重审**（「前序任务已交付已测 ⇒ 本任务不动它」）；措辞改对之后，
函数本身仍然是「本轮新增 + 零业务消费者 + 模型名口径与 trace/账本分叉」，那三点才是问题。
分层归属（读执行面对象的纯函数不该住在 trace 模块）本身判为**正确**，无需重审——但按 C 的
裁定它不该以「provider 侧的 model_route」名义存在。

**C｜两条 model_route 接缝并存 —— 裁定：不是职责分层的正确切法，是同一份事实两处构造；最终口径如下（Important I-2）。**
证据：同一份 `FallbackResult` 下 `model_route_payload.attempts[].model = ['fb-a','fb-b']`
而 `usage.model_route_trace.attempts[].model = ['fb-a-model','fb-b-model']`；前者绕过
`_stored_model_name`（M2 口径）。业务调用点：payload = 0，trace = 唯一经
`agent_trace.attach_model_route` 的通道。**这不违反「同一事实单一出处」的前提是删除或改名 +
口径归一二者之一；现状违反。** 可执行最终口径见 §6（编号 1-8），其中第 4 条同时回答了报告
:152 提的「接口缺口三选一」：**选 (c) 的变体——由 T6 给结果对象加一个带默认值的可加字段
`plan`，不动 `complete()` 的返回对象**。

## 6. 移交 T6 / T7 / T8 的强制口径（编号执行，逐条可照做）

1. **唯一生产者**：trace 的 `model_route` 键**只能**由
   `app.llm.usage.model_route_trace(plan, result, *, profile=None, registry=None)` 产出；
   键名常量 `agent_trace.MODEL_ROUTE_KEY`（值 `"model_route"`）。业务链**不得**自己拼这个
   dict，不得把任何其它函数的返回值 merge 进 `trace["model_route"]`。
2. **唯一挂载点**：`app.agent_trace.attach_model_route(trace, plan, result, profile=profile)`，
   调用位置 = 该链**组装完 trace、`save_trace()` 之前**的那一处收尾（不在 llm 包内：llm 不
   知道 trace 的形状；不在 usage 之外再造第二个挂载器）。
3. **参数契约**：`plan` = 真 `RoutePlan`（`llm.plan()` 的产物）；`result` =
   `FallbackResult`（T6/T8 非流式）｜`StreamSummary`（T7，`session.finish()`）｜
   `AllCandidatesFailedError`（D2 降级/全链失败，**必须**也挂 trace，那是最需要解释的一条）；
   `profile` = 本次 `RequestProfile`，不传 ⇒ `mode=""`、`requirements={}`（不猜）。
4. **plan 怎么拿到（对报告 `:152` 的三选一定裁）**：由 **T6** 在
   `app/llm/fallback.py` 的 `FallbackResult` 与 `StreamSummary` 各加一个末位可加字段
   `plan: RoutePlan | None = None`（frozen dataclass 末位默认值 ⇒ 既有构造与 T4 的 12 处
   断言不破），`run_complete` 与 `StreamSession.finish()` 负责填；`AllCandidatesFailedError`
   同步带 `plan` 属性。**不改 `complete()/stream()` 的返回对象、不加回调参数**（(b)/(c) 否决：
   前者动返回形状，后者要求三条链各自闭包传参，形状更容易漂）。调用形状固定为
   `attach_model_route(trace, result.plan, result, profile=profile)`。T7/T8 复用同一形状。
5. **`model_route_payload` 的处置**：T5 修复轮删除（见 I-2）。T6/T7/T8 **不得**引用它；
   若终审否决删除，则只有 `usage` 那一份能进 trace，另一份只能作为 SSE/D5 侧的**非 trace**
   诊断摘要，且 `attempts[].model` 必须先套 `usage._stored_model_name`。
6. **禁存项的生产者侧义务**：`profile` 只被读 5 个冻结字段名，但**不要**因此把 query /
   消息体 / reasoning 挂到画像或 result 上；`LLMRequest.messages` 不得进 trace（契约测试
   只钉住了我这一侧的读取面，另一半靠 T9 的 D6 静态扫描 + 你们自律）。
7. **失败归类义务（配 I-4 的收窄）**：任何链写 `success=False` 的账时**必须**带
   `error_type=kind`（或 `kind:status`）；不得靠「留空」表达「不知道」——留空且没有交付事实
   ⇒ 现在会落 `unknown` 并计入失败分母，有交付事实 ⇒ 才会被认作 `client_aborted`。
   T7 要补一条「commit 后 provider 断流 ⇒ `error_type` 仍是原始 kind」的用例。
8. **矩阵 #17 的「集成」半段归你们**：T6/T7/T8 各补一条走**真 `llm.complete/stream`** 的用例，
   断言产出的 trace 里 `model_route` 六键齐备（顶层键序 + attempts 非空 + 无 prompt/
   reasoning 字节）。Task 5 的 `AgentTraceModelRouteSeamTests` 3 例只覆盖到纯函数 + 落盘
   JSONL 往返，**它不能替你们交 #17**。T8 另需按 plan Task 8 在 trace 上记
   `NO_CAPABLE_MODEL→fast_path`（这是 M3/零候选不产行之后唯一的解释出口）。

## 7. §8 必查清单 1–11 逐项结论

| # | 结论 | 证据（文件:行 / 我跑出来的） |
| --- | --- | --- |
| 1 冻结 19 列 | **PASS** | `usage.py:152-185` DDL 19 列 + 18 可写列与 `_row_of:483-492` 同序；`route_reason` 走 `json.dumps(list(...))` 是码数组；测试 6 例（含三方等式与禁存列名）绿 |
| 2 禁存项 | **PASS（+ Minor 1）** | `:512-527` 整值替换；我实测 `_model_name` 对 `kimi/月之暗面`、33×4 汉字、129 字符全 ⇒ `""`；`_clean_error_type` 的「先压空白再截断再匹配」我逐条推演过：截断后仍匹配 ⇒ 必无空格/汉字 ⇒ 无 prompt 可能存活；trace 侧 `test_a_profile_carrying_a_query_leaves_not_a_single_byte_in_the_object` 我用鸭子画像独立复跑 |
| 3 D3 fail-open | **PASS** | `:241-249`、`:280-285`、`:288-306`；`FailOpenTests` 6 例绿；`warmup` 只注册表上抛（`test_a_broken_table_still_boots_but_a_broken_registry_does_not`） |
| 4 D4 与 status 形状 | **PASS（+ I-4 的回写义务 / Minor 1）** | `providers` 只读 `provider_health_view`（`:765-780`），熔断走 `_breaker_block:836-853`；白名单 13 枚逐枚列举、无前缀放行（`:221-228`），我的 M3 内存变异被 4 例杀；`fallback_rate` 从表算（`:693`） |
| 5 `client_aborted` 新语义 | **Important（I-4）** | 越过 §0c 的 T2 冻结词表（`review-task-5.md:34`）；`p95_latency_ms` 不剔除**自洽**（它量等待，关页前也在等）；`aborted_rate` 是 §8 外键 ⇒ 与 spec 回写同批处理 |
| 6 零候选不产行 | **Minor（清单 11 之 11）** | 结论：不产行**正确**（§8 的行是「一次 LLM 请求」的账，零候选连一次外呼都没有，`route_mode` 之外的 17 列无事实可填）；但 `requests_5m` 因此**不含**它 ⇒ 注册表配错期 status 会像「闲置」而非「故障」。补偿：T8 trace 记 `NO_CAPABLE_MODEL→fast_path`（§6 第 8 条）+ T11 验收文档写明该键的口径 |
| 7 M2 口径归一 | **Important（I-2，因为 trace 侧漏了一半）** | 账本三条出口：`test_all_three_producer_paths_land_on_one_model_string` 实测「内存两种词、库里一种词」；`_model_name` 不误杀真名（我跑了 12 个真名）；但 payload 那条 trace 通道仍写条目 id ⇒ 归一不彻底 |
| 8 `_cost_for` 三分支 | **PASS（+ Minor 5/6）** | `:655-679`；本地牌价 0 的条目走分支①⇒ `(0.0,"USD")`，**不会**被误判为「不知价」（实测 `test_the_provider_narrows_the_price_lookup...` 断言 `(0.0,"USD")`）；「>0 判据丢免费路币种」= 已记取舍 |
| 9 trace 接缝诚实边界 | **PASS（+ Minor 4）** | 只读 5 个字段名（我塞 `query/prompt/reasoning/messages/system_prompt` 五枚带标记的鸭子画像：`mode` 含中文空格 ⇒ `""`，五个标记 0 命中）；`attach_model_route` 的 `except Exception` 会把编程错误吞成 warning —— 接受（§8 观测面语义），但由 §6 第 8 条的集成用例兜住「键必须存在」 |
| 10 测试质量 | **Important（I-5）+ Minor 2** | 类/例数与报告逐项吻合（我按 AST 数过：98，CostTests 10、ModelColumnCaliberTests 8、ModelRouteTraceShapeTests 13）；M1/M2/M3 三发变异**我全部独立复现被杀**（M1 还多杀一例 trace 用例）；但 `_clean_codes` 的去重+上限变异存活；两例 cwd 依赖；`reset_usage_state()` 与 `llm.set_usage_sink` 的 addCleanup 我核过，未见跨用例泄漏 |
| 11 范围纪律 | **Important（I-2 的一半）** | 未迁移任何业务链（`rag.py`/`agent.py`/`conversation_agent.py` mtime 15:17/15:18/18:46 均早于本任务，我核过）；无新依赖、无新端点、无新列；**越界项 = 在 `__init__.py` 里新增一个零消费者的导出函数**（属 T4 文件 + 属自扩范围） |

## 8. 我实际执行过的验证（命令 + 关键输出）

```
# 1) 定向文件（评审者自己跑）
cd backend && python -m pytest tests/test_llm_usage_contract.py -q
  → 98 passed, 5 warnings, 9 subtests passed in 34.65s

# 2) 改动面（只读比对，不用 git）
diff -u snap-task4/llm/__init__.py backend/app/llm/__init__.py          # +docstring4行 +__all__1枚 +_effective_model_name +model_route_payload +log_stream_usage 的 model 改口径
diff -u snap-task4/test_model_router_v23_contract.py backend/tests/... # 3786-3812 一例被从「两面」重写为「三面」
diff -u baseline-app/agent_trace.py backend/app/agent_trace.py          # 纯 additive + 19 行行尾规整
grep -c model_route_payload snap-task4/llm/__init__.py                  # 0（证伪「T4 交付」）
grep -rn "model_route_payload" app/                                     # 只有定义处 ⇒ 零业务消费者
ls --time-style=full-iso（8 个文件 mtime 对照窗口 00:01 → 01:48）
python（字节级 EOL 统计：agent_trace.py 92CRLF/0LF；usage/security/tests 全 LF；仓库 app/*.py = CRLF24/LF18/mixed7）

# 3) 内存探针（rev5_probes.py，临时库在 tempfile 目录，不写 backend/）
同一 FallbackResult：payload.attempts[].model=['fb-a','fb-b']  vs  trace.attempts[].model=['fb-a-model','fb-b-model']
_model_name 真名 12 枚：qwen2.5:7b-instruct-16k / meta-llama/Llama-3.1-8B-Instruct /
  ollama.com/library/llama3.1:70b / gpt-4o-mini-2024-07-18 / phi3:mini …… 全原样；中文、含空格、>128 ⇒ ""
public_llm_status({"providers":{"api.openai.com":…,"127.0.0.1:11434":…}}) ⇒ 两键**全部通过**
success=False∧error_type=None∧fallback_index=-1∧tokens=0 ⇒ 库里 error_type='client_aborted'，
  aggregate_status → {"requests_5m":1,"success_rate":null,"aborted_rate":1.0}
鸭子画像（带 query/prompt/reasoning/messages/system_prompt）⇒ 五枚标记 0 命中；needs_tools="false" ⇒ True；mode 含中文 ⇒ ""

# 4) 内存变异复现（rev5_mutations.py，全部 monkeypatch 后原样还原，未改任何源码）
M1 usage._model_name 透传（只截断） → 3 红：test_long_chinese_prompt_never_survives_any_column /
   test_the_sink_still_sanitizes_an_unsafe_name / test_attempt_fields_degrade_to_machine_readable_fallbacks；还原后 4/4 绿
M2 scored_rows 返回全部行（关页进分母） → 3 红：0.7143!=0.5556 / 0.5556==0.5556 / 0.0 is not None；还原后 4/4 绿
M3 public_llm_status 遍历 白名单∪source → 4 红（'rows'/'aborted'/'success_rate_debug' 泄漏）；还原后 5/5 绿
新变异 A：_clean_codes 去 dedupe + 去 12 上限 → **存活**（4/4 仍绿，直调 30 枚 → 14 枚 vs 还原后 9 枚）= 测试缺口
新变异 B：AGGREGATE_ROW_CAP=1 → 1 红（9 != 1）
探针真实性：ProviderHealthBudgetTests 两例内 provider.probe 被调 2 次（ollama/2.5s），
   socket.connect 与 getaddrinfo 观测到 **0 次**（解析失败即回退）⇒ 无外呼，但隔离靠环境

# 5) cwd 敏感性（I-5 的证据）
cd E:/xiangmu/rag && python -m pytest backend/tests/test_llm_usage_contract.py -q
  → 2 failed, 96 passed（AggregateMathTests::test_window_rates_and_p95_on_ten_seeded_rows
     FailOpenTests::test_aggregate_degrades_to_an_empty_block_when_the_read_fails）

# 6) 全套件我**没有**再跑（主 agent 已独立核实 746 passed / 0 failed / 852 subtests；
#    与我在树里看到的文件面不矛盾：定向 98 例我复跑为绿，T4 侧被重写的那 1 例我也读过 diff 全文）

# 7) 评审副作用自查
find backend/app frontend/src -newermt "-40 minutes" -type f -not -path "*__pycache__*"   # 空 ⇒ 源码零改动
（backend/data/audit.jsonl 被 SystemStatusLlmBlockTests 追加过一次 status 审计记录——该测试自身的既有行为，
  与前四任务跑测试时同形；未新增/修改任何 backend/ 或 frontend/ 源文件，未跑 git 写操作。）
```

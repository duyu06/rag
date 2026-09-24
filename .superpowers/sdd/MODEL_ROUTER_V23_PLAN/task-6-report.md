# Task 6 报告 — RAG 生成链迁入 `app.llm`（§9 第一条）+ T5 移交的执行面 `plan` + 温度等价门闸

## 状态

**DONE**。三条交付都落地并全绿：

1. **A 迁移**：`app/rag.py::generate_answer` 的默认路改成 `llm.complete(messages, mode="rag",
   temperature=RAG_LEGACY_TEMPERATURE, trace_id=None)`；`LLM_ROUTER_ENABLED=false` 的两条
   `httpx.post` 分支**原样保留**（矩阵 #18 的对照组）；`current_model_name()` 改经 `plan()`
   解析 rag 模式默认候选的生效模型名；`web_search` / `build_context` / `SYSTEM_PROMPT` /
   TypeSafe 逻辑一字未动。
2. **B T5 移交**：`app/llm/fallback.py` 的 `FallbackResult`、`StreamSummary`、
   `AllCandidatesFailedError` 各加**末位带默认值**的 `plan: RoutePlan | None = None`，
   `AllCandidatesFailedError` **同批**加 `context_dropped: int = 0`；三个填值点（`run_complete`
   成功路径、`_Runner.all_failed()`、`StreamSession.finish()`）全部填上。
   没改 `complete()/stream()` 的返回对象、没加回调参数（评审 C 否决的那两条）。
3. **C 温度门闸**：两条 provider 腿 × 双路全部覆盖，OpenAI 腿钉**逐字相等**，Ollama 腿钉
   **显式值 + 键集合差恰好 `{"options","tools"}`**（偏差被枚举，见下面「C 组裁定」）。

- 定向（交付口径 1）：
  `python -m pytest tests/test_llm_usage_contract.py tests/test_model_router_v23_contract.py
  tests/test_web_search_contracts.py tests/test_runtime_metadata_contract.py
  tests/test_typesafe_api_runtime.py tests/test_typesafe_security_contract.py -q`
  ⇒ **408 passed / 0 failed / 381 subtests in 39.01s**
- 全套件（交付口径 2）：`cd backend && python -m pytest tests -q`
  ⇒ **788 passed / 0 failed / 878 subtests in 81.53s**
  （基线 749 / 876 ⇒ **+39 例 / +2 subtests**，只增不减成立）
- 变异自查（交付口径 3）：**11 发，全部被杀（RED），存活 0 发**；逐发 sha1 还原一致。
- 约束核对：零 git 写、零真实外呼（router 腿 `httpx.MockTransport`、legacy 腿 `httpx.post`
  替身，健康视图整轮 stub）、零新增依赖、零新增 §8 的列、未动 `native_stream.py` /
  `agent.py` / `conversation_agent.py` / `app/security.py` / `app/llm/__init__.py`。
- 改动面（**3 个文件**，按 mtime + 与 `snap-task5/` 的 `diff -u` 核对）：

| 文件 | 行数变化 | 本任务做了什么 |
| --- | --- | --- |
| `backend/app/rag.py` | 144 → 280 | 生成面迁 router + `_answer_via_router` + `_llm_unavailable`；`current_model_name` 拆成 router 路 / `_legacy_model_name`；文件头 D6 豁免段（含逐枚命中数）|
| `backend/app/llm/fallback.py` | 908 → 943 | 三对象加 `plan`（异常另加 `context_dropped`）+ `_Runner` 携带 plan + 三个填值点 + 四处 docstring |
| `backend/tests/test_model_router_v23_contract.py` | 3921 → 4731 | 新增 Task 6 段：**+810 行、删除 0 行**（`diff` 的 `<` 计数为 0，见「既有断言」段）|
| `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/t6_mutations.py` | 新建 | 变异脚本（字节安全版；先例 `t5_fix1_mutations.py`）|

## 红 → 绿证据

**先说清姿势**：本任务是「实现 → 测试 → 变异自查」的顺序落盘，**没有跑 TDD 的先红**，
所以真正的「红→绿」证据由两处提供，任何一处都不该被读成「测试写完就顺手绿了」。

### 1. 开发过程中真实红过一次的那两发（红在测试侧，改的是测试）

- `test_flag_off_never_calls_the_router` / `test_both_paths_deliver_the_same_answer…`
  首跑 **2 failed**：legacy 腿的替身返回 `httpx.Response(200, json=body)`，而
  rag 的 legacy 分支调 `response.raise_for_status()` —— httpx **0.28.1** 在没有 request 的
  Response 上直接 `RuntimeError("Cannot call raise_for_status as the request instance has
  not been set on this response.")`，于是被测代码正确地走了兜底文案，红的是替身。
  实测核验：`httpx.Response(200, json=…)` + `raise_for_status()` ⇒ RuntimeError。
  修法 = 替身自己挂一个 `request=httpx.Request("POST", url)`（真客户端由 transport 挂），
  **没有**放宽任何断言、**没有**把 legacy 分支改成不 `raise_for_status`。
- 另有一次 `2 failed` 来自我自己的选择集写法（`-k "A or B"` 被 `split()` 拆成多个 argv ⇒
  `no tests ran`），变异脚本第一版因此白跑了一轮，顺带暴露出第二个更严重的问题：
  **第一版脚本用 `read_text`/`write_text` 做替换，把纯 LF 的 `fallback.py` 写成了纯 CRLF**
  （sha1 还原核对当场报不一致）。已按 `snap-task5` 的行尾风格还原成纯 LF，脚本改成
  全程 `read_bytes`/`write_bytes`（事故与修法都写进脚本 docstring）。
  内容零损伤：还原后 `diff -u snap-task5/app/llm/fallback.py backend/app/llm/fallback.py`
  只剩本任务的 6 处语义改动。**这是本任务唯一一次对既有文件造成非语义字节变化，如实报。**

### 2. 11 发变异的 RED 记录（这才是「断言真的挡得住」的证据）

见下面「变异自查」表：M1（去温度）⇒ 2 红、M2（legacy if 写反）⇒ 5 红、
M3/M11（`plan` 不填 / 填成 None）⇒ 各 3 红，**三条点名的必做发全部被杀**。

### 3. 一次「红不出来」的自我修正（新增两例）

第一版变异表跑完后我发现 **catch-all 那一发（M8）没有对应的钉**：
如果只保留窄化的 `except (LLMError, …)` 而删掉 `except Exception`，
「坏响应体 → 兜底文案」这条现网行为就没有测试守着了（legacy 腿的 `KeyError` 会变 500）。
于是补了两例：`test_a_malformed_legacy_body_still_degrades_instead_of_raising`
（钉 `模型连接错误：KeyError`）与
`test_a_legacy_connection_error_keeps_the_exception_class_name`（钉 `ConnectError`），
M8 从「可能存活」变成 **RED（2 failed）**。这一发是自查过程真正抓出来的缺口，不是装饰。

## 测试构成（Task 6 新增 39 例 / 7 组，全在 `tests/test_model_router_v23_contract.py`）

| 组 | 例 | 钉什么 |
| --- | --- | --- |
| `RagRouterMigrationTests` | 6 | router 路**恰好一次**真实外呼（MockTransport 计数 + URL）；两条消息形状与 `SYSTEM_PROMPT` 逐字；`[1]` 引用与证据块措辞；`联网来源：` 尾块的编号偏移与末行逐字；`注：本次联网检索部分失败…` 那一注的**位置**（正文之后、无尾块时结尾）；无证据时零外呼；`result.plan` 在真链上可用（`isinstance RoutePlan` + primary 与响应模型名同源）|
| `RagTemperatureEquivalenceTests` | 6 | OpenAI 腿 `temperature` 逐字相等 `== RAG_LEGACY_TEMPERATURE`；Ollama 腿 `options.temperature` 显式 0.1 + 键集合差恰好 `{"options","tools"}` + `messages/model/stream` 逐字；flag on/off 各自禁用另一条出口（`llm.complete` 上闸 / `httpx.post` 上闸）；两腿同一响应体 ⇒ 对外文本逐字相同；legacy 的 URL 与 `timeout=120` 原样 |
| `RagFailureFaceTests` | 9 | `NoCapableModelError`（真注册表面孔 + 全 provider 不健康的 health_view）→ 现文案、零外呼、不抛；异常**类名**进文案（`NoCapableModelError` / `AllCandidatesFailedError` 两种）；兜底文案仍带联网尾块；上下文收口剔空 ⇒ 同一句；全链失败 ⇒ **一行 `success=0` 且 `error_type="model_unavailable"`（非空 kind）**；零候选 ⇒ 0 行且「`success=0` 行必带 error_type」等式；legacy 坏响应体 / 连接失败仍降级；`/api/query` 真 HTTP 面 200 + `model_used` |
| `RagLedgerTests` | 2 | 一次问答一行 `route_mode="rag"` 成功账（provider/model/token 三元组/`fallback_index`/`trace_id is None`/`ttft_ms is None`）+ **禁存项**：中文问题、证据正文、`SYSTEM_PROMPT[:24]`、`请依据以下证据回答问题` 在整行序列化里 0 命中；fallback 命中时 `model` 与 `fallback_index` 指向真答的那一条 + 理由码去重 |
| `RagDisplayedModelNameTests` | 8 | 无 key ⇒ `== settings.ollama_model`（真出厂注册表文件）；展示面**不打网络**（探针上闸 + MockTransport 零请求）；坏注册表 / 零候选 ⇒ 退回 legacy 名字而不抛；**反证**：注册表 primary 与 `ollama_model` 分叉时以注册表为准（证明上一枚不是恒等式）；有 key ⇒ 云端 primary；flag off 两分支逐字；`OLLAMA_MODEL_OVERRIDE` 别名到展示面 |
| `PlanCarrierTests` | 7 | 三个填值点（`run_complete` / `finish()` / `all_failed()`）都带**同一个** plan 对象（`assertIs`）；`context_dropped` 到异常；末位默认值 ⇒ 既有位置参构造照旧（`plan is None`）；字段序/参数序等式（`plan` 是 dataclass 末位、异常签末两枚）；`llm.complete()` 透传不改对象 |
| `RagLegacyEgressInventoryTests` | 1 | D6 豁免清单的**事实源**：`rag.py` 的 httpx 代码命中恰好 3（1 import + 2 `httpx.post`）、端点字面量恰好 2、`httpx.get`/`httpx.Client` 恰好 0。**钉等式而不是 `<=`**（`<=` 会让「顺手加第三条出口」静默通过）|

夹具：`_RagMigrationFixture(_EgressFixture)`（真 provider + MockTransport + 临时
`conversations.db` + `llm.set_usage_sink(None)` ⇒ 惰性接真 `log_usage`）。
它相对 `_EgressFixture` 只多做四件事：settings 多打三处（`llm`/`fallback`/`usage`）、
注册表按用例注入（`llm` 与 `usage` 同一份）、`provider_health_view` 换成 stub（**不打探针**）、
临时账本。既有夹具与既有用例**一处未改**。

## 变异自查（11 发，全部 RED 被杀，存活 0 发）

选择集 = Task 6 的 6 个组（`-k "RagRouter or RagTemperature or RagFailure or RagLedger or
RagDisplayed or PlanCarrier"`，M4/M5/M7 用更小的子集以定位）。脚本：
`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/t6_mutations.py`（锚点命中数必须恰好 1，否则 SKIP）。

| # | 变异（文件 : 打在什么上） | 结果 | 被哪条杀死 |
| --- | --- | --- | --- |
| **M1** | `rag.py`：**去掉 `temperature=RAG_LEGACY_TEMPERATURE`**（T2 移交 I-4 的硬义务） | **RED 2 failed** | `test_openai_leg_temperature_is_byte_equal…`（0.2 ≠ 0.1）+ `test_ollama_leg_pins_the_explicit_temperature…` |
| **M2** | `rag.py`：**legacy 分支的 `if` 条件写反**（`elif not settings.openai_api_key`） | **RED 5 failed** | 两条腿的温度例 + `test_legacy_endpoint_urls_and_timeout_are_unchanged` + `flag_off/flag_on` 两道闸 |
| **M3** | `fallback.py`：**成功路径不填 `plan`** | **RED 3 failed** | `test_fallback_result_carries_the_exact_plan_it_executed` + `test_the_plan_travels_with_the_result_the_rag_chain_gets` + `test_complete_passes_the_result_object_through_untouched` |
| M4 | `fallback.py`：`StreamSession.finish()` 不填 plan | **RED 1 failed** | `test_stream_summary_carries_the_plan` |
| M5 | `fallback.py`：聚合异常的 `context_dropped` 恒 0（N4 的哑键退回） | **RED 1 failed** | `test_the_context_drop_count_reaches_the_aggregate_error` |
| M6 | `rag.py`：展示面退回 legacy 的「看有没有 key」猜法（等于没迁移） | **RED 2 failed** | `test_the_name_follows_the_registry_primary_not_the_ollama_setting` + `test_the_cloud_primary_is_reported_when_a_key_arrives` |
| M7 | `rag.py`：展示面不再兜住坏注册表（`except` 换成永不发生的类） | **RED 2 failed** | `test_a_broken_registry_degrades_to_the_legacy_name_instead_of_raising` + `test_zero_candidates_degrade_instead_of_raising` |
| M8 | `rag.py`：删掉 legacy 腿保留的 catch-all | **RED 2 failed** | `test_a_malformed_legacy_body_still_degrades_instead_of_raising`（第一轮**没有**这枚钉 ⇒ 为此新增两例，见「红→绿」第 3 段）|
| M9 | `rag.py`：生成面 `mode="chat"` | **RED 2 failed** | `test_one_success_row_with_route_mode_rag_and_no_prompt_bytes` + `test_the_ledger_follows_the_candidate_that_actually_answered` |
| M10 | `rag.py`：`_append_web_sources(answer, 0, …)`（丢掉企业条数） | **RED 1 failed** | `test_web_sources_tail_block_keeps_position_and_wording`（`- [2]` 变 `- [1]`）|
| **M11** | `fallback.py`：`plan=None` 但字段还在（防「只查有没有这个键」的假测试） | **RED 3 failed** | 与 M3 同三例（`assertIs(plan, result.plan)` 而非 `hasattr`）|

诚实说明两点：①**M1 与 M2 各杀 2/5 例而不是更多**，是因为温度等价这一族故意只钉在
「报文面」的 6 例里——它们是门闸而不是行为面；反过来 `5 failed` 的 M2 说明双路互斥闸
（`guard_router_off` / `guard_legacy_egress_off`）确实在挡事。
②有一发我**故意没跑**：把 `except (LLMError, AllCandidatesFailedError, NoCapableModelError)`
单独删掉（保留 catch-all）——那发**必然存活**，因为 catch-all 在集合上覆盖了它，这条窄化
clause 的价值是「源码可读 + 将来收窄 catch-all 时不丢 D2 出口」。写在这里而不是假装它可杀。

## 裁定与移交

### 1. C 组：Ollama 腿的温度偏差是**行为变更**，显式声明如下

**事实（已核实，不是推测）**：`normalize.ollama_payload` **恒发** `options.temperature`
（以及恒发 `tools: []`），而 `rag.py` 的 legacy Ollama 分支两个键都没有 ⇒ 它吃的是
**Ollama 服务端默认**。所以任务书里「与 legacy 报文逐字相等」这一条在 Ollama 这一腿上
**按构造不可能成立**。我没有伪造等价（没有把 `options` 变成可选键——那会改掉 `agent.py`
平移过来的现网形状，也归 T8 管），也没有放宽门闸（没有把断言写成「温度大致相同」），
而是按裁定执行：

1. **OpenAI 兼容腿 = 真等价**：`legacy["temperature"] == routed["temperature"] ==
   RAG_LEGACY_TEMPERATURE == 0.1` 逐字钉住，外加 `model`/`messages` 逐字相等 +
   `headers` 只有 `Authorization` 一枚 + 键集合差恰好 `{"stream"}`。
2. **Ollama 腿 = 偏差被枚举**：`routed["options"]["temperature"] == 0.1`（显式值，
   不看 legacy）+ `assertNotIn("options"/"tools", legacy)` +
   `set(routed) - set(legacy) == {"options","tools"}`（**恰好**两枚，多一枚少一枚都红）+
   `messages`/`model`/`stream` 逐字相等 + `set(legacy) - set(routed) == set()`。
   另钉 `set(routed["options"]) == {"temperature"}`：偏差只有温度这一件事，
   `num_predict`/`think`/`keep_alive` 都没有偷渡进来。
3. **双路 × 两腿**都跑过（`llm_router_enabled` true/false 各一次，各自禁掉另一条出口）。

**这条偏差的实际内容**：`LLM_ROUTER_ENABLED=true` 且候选落在 Ollama 上时，RAG 生成的
采样温度从「Ollama 服务端默认」变成**显式 0.1**。请写进 DESIGN §9 的修订说明与 T11 验收文档。

**我的技术判断：为什么「与 OpenAI 腿同为 0.1」比「复刻服务端默认」更配得上 RAG 的
grounded/引用硬约束**——四条论据，按决定性排序：

1. **RAG 的三条硬约束全是「忠实度/格式」类，不是「多样性」类**。`SYSTEM_PROMPT` 第 2/3/6/7
   条是：不得编造、关键事实标 `[1] [2]`、最终答案简体中文、证据不足时用**中文固定话术**拒答。
   温度抬高会同时增加三类失败：(a) 引用编号与证据块**错位**（把 [2] 的内容标成 [1]，
   前端 Evidence Inspector 就指向错文档）；(b) 「证据不足」漂移成「合理推测」；
   (c) 固定拒答话术被改写成同义句——而 `REFUSAL_PHRASE` 是 TypeSafe 收尾时钉过的
   **下游「无答案」判据的中文标记白名单**（`tests/test_agent_contracts.py:89,126` +
   `eval_dataset_complex.json` 的 `no_answer_cases`），措辞一漂，评测就判不出「无答案」。
   这三类都是**不可观测的静默劣化**，比「答案不够有创意」贵得多。
2. **同一条链不允许有两个采样温度**。legacy 的形状是「有云 key ⇒ 0.1；没 key ⇒ 服务端默认」，
   于是同一个问题在云端腿保守、本地腿发散。这条链今天还有 usage 落库与 status 聚合，
   跨 provider 比较 `success_rate` / 延迟时，混杂变量不该包含「这次走的是哪条腿的解码策略」。
   §9 的迁移语义（三条链收编进同一个 Router、fallback 可跨腿）更直接要求这一点：
   矩阵 #4/#5 的 fallback 用例测的是「换了模型仍然是同一次生成」，若换腿顺带换温度，
   那条用例的对照组就不成立。
3. **把路由开关当解码策略开关用是错的**：`LLM_ROUTER_ENABLED` 的语义是「走不走 Router」，
   它一拨就同时改了解码温度，那是把两个正交维度绑死在一个键上，应急回退时反而引入新变量。
   迁移后两条腿的温度**都是** 0.1，旗标只切执行面。
4. **可复现性方向不对称**：服务端默认会随 Ollama 版本与模型 GGUF 元数据漂移
   （Ollama 的 `temperature` 默认值是 0.8，而带 `general.alignment` 元数据的模型会覆盖
   Modelfile/请求里的温度）。显式发 0.1 至少让「我们这一侧要什么」写死在报文里；
   复刻「不发」等于把一个我们既不拥有也不观测的量当成契约。
   风险的不对称也支持这一侧：0.1 更保守（重复率略升、偶有过度简短），
   而 0.8 那一侧的代价是上面三类静默劣化——**保守侧错了看得见，发散侧错了看不见**。

**需要终审向用户复述的一点**：Ollama 腿的默认温度到底是多少、以及是否有个别模型用元数据
强制覆盖（那是 Ollama 侧的事实，我**没有**在本任务里实测，也不该实测——零真实外呼），
不影响本门的结论：现在两侧都是**显式 0.1**，而 legacy 是**未指定**。
T10 的真实 failover 会第一次在真 Ollama 上跑这条链，届时若观测到 0.1 引起质量退化，
改的是**常量**（`RAG_LEGACY_TEMPERATURE` 的单一出处在 `app/llm/__init__.py`），
不是把某一腿退回「不发」。

### 2. 与 T5 已评审裁定冲突的一处：`NoCapableModelError` 要不要一行失败账

任务书 D-3 要求：「`NoCapableModelError` ⇒ ……并且**这条失败账带 `error_type` 的 kind
（不许留空，§8.1 第 2 条）**」。**这一条与 Task 5 已经评审 + 回写过 §8.1 的裁定正面冲突，
我按 T5 的裁定执行，并把它可执行的部分钉满**：

- 冲突面：`tests/test_llm_usage_contract.py:666`
  `test_no_capable_model_writes_no_row_and_stays_out_of_the_denominator` 明确断言
  `llm.complete()` 抛 `NoCapableModelError` 时 **库里 0 行**、`requests_5m=0`，理由是
  「把『路由没找到模型』算成『模型失败』，`success_rate` 就会为一条根本没发出的请求记账，
  而 D2 的降级（Agent fast-path / RAG 兜底文案）是**设计内**的出口，不是故障」
  （T5 报告 §2 第二条 + 复审 PASS 放行 T6）。
- 更硬的一层：**`NoCapableModelError` 没有 `.kind` 这个属性**（它刻意不是 `LLMError` 的子类，
  §4/fallback 的冻结区分）。于是「带 error_type 的 kind」这一要求在数学上就只能靠
  造一个词来满足；而 `usage` 那侧的字符集闸会把任何自造词收成 `unknown` ⇒ 这行会
  作为一次**失败**进 `success_rate` 分母 —— 正是 T5 那道裁定要防的读法。
- 我做的（三件，都在改动面内）：
  1. RAG 的 `NoCapableModelError` 出口 = **现文案 + 不抛 + 零外呼**，并用真 HTTP 面
     (`/api/query` 200) 钉住「不炸」。
  2. 把「失败账不许留空 kind」钉在**它真正管得着的那一支**上：
     `test_a_full_chain_failure_writes_one_row_with_a_provider_kind` ⇒ 全链失败
     （`AllCandidatesFailedError`，有真实 attempt）落一行
     `success=0, error_type="model_unavailable", status_code=500`，kind 非空。
  3. 再钉一条**等式**：`test_the_zero_candidate_exit_writes_no_row_at_all` ⇒ 零候选那一支
     0 行，且「库里不存在 `success=0` 而 `error_type` 为空的行」以全表扫描的形式成立。
- **要请终审裁的**：若坚持「零候选也要一行」，需要（a）§8.1 式回写 + （b）反转 T5 那例
  （那是**降强度**方向的反转，不是补强）+ （c）给 `NoCapableModelError` 造一个 kind
  或给 `error_type` 词表加第三枚哨兵（例如 `no_capable_model`，但那是新值域、要过白名单）。
  三步都超出 T6 的授权，我没有动。**结论：本任务不新增写账路径。**

### 3. 矩阵 #17 的「集成」半段：按你的口径归 T7/T8

brief 里 T5 移交第三条把 #17 的集成半段派给了本任务，但同一份任务书明确
「`app/rag.py` 这条链**没有 trace**，本任务不要为了接 `attach_model_route` 去给 rag 造 trace」。
我按任务书执行：**没有**给 RAG 造 trace（`trace_id=None`，账本的 `trace_id` 列因此是 NULL，
已钉），改为交付 #17 的**前置事实**：`result.plan` 在真 `llm.complete()` 上确实可用且与响应
模型名同源（`RagRouterMigrationTests::test_the_plan_travels_with_the_result_the_rag_chain_gets`
+ `PlanCarrierTests` 7 例），T7 只要写
`attach_model_route(trace, summary.plan, summary, profile=profile)` 一行就有料可接。
#17 的完整形态（九键落盘 trace）因此**仍归 T7/T8**，请主 agent 在矩阵台账上把这一行改挂。

### 4. `current_model_name()` 新解析路径的失败面（任务书点名要交代）

新实现 = `plan(RAG_PROFILE, registry, routing_health_view(registry, include_probes=False))`
→ `effective_model_name_for_entry(plan.primary.model)`。与 legacy 那两句 `if` 相比：

- **多出来的失败面**（legacy 永不失败，所以每一条都必须有收口）：
  - `RegistryError`（文件缺失 / 结构坏 / 重复 id / provider 未登记）→ 退回 `_legacy_model_name()`
    + 一条 `logging.warning`。M7 变异证明这层 catch 是活的。
  - `NoCapableModelError`（enabled 全灭 / rag capability 全 false / rag priority 全 0 /
    健康视图把所有 provider 闸掉）→ 同上。注意这**可能**发生：legacy 只看「有没有 key」，
    注册表还要看能力旗标，有人把 `ollama-ornith` 的 `capabilities.rag` 写成 false 就零候选。
  - 我没有加宽到 `except Exception`：`plan()` 是纯函数、`effective_model_name_for_entry`
    内部已经吞掉凭据解析失败（`RegistryError/TypeError/ValueError`），剩下的都是配置事故，
    要响的是 `warmup()` 那道启动门闸而不是这里。
- **展示面与生成面可能劈叉的两个窗口**（都是刻意取舍，写在 docstring 里）：
  1. **探针**：生成路 `_plan()` 带 `provider_health_view()`（真探针 + 60s 缓存），
     展示路 `include_probes=False` ⇒ 只有「provider 恰好不健康且缓存刚过期」这段时间
     两边候选会不同。换来的是 `/api/health` 与前端 30s 轮询的 status 页**不把 Ollama 打个来回**
     （任务书「不许在展示面上打网络」）。测试侧用两道闸钉死：`fail_on_any_probe()`
     （探针一被调用就 `AssertionError`）+ `self.requests == []`（MockTransport 零请求）。
  2. **熔断态**：`include_probes=False` **仍然并 `circuit_open`**，所以本地 provider 被熔断时
     展示面会报 fallback 条目的名字。这是「现在谁会服务这一行」的诚实答案，
     代价是它随请求序列抖（不是常量）。若产品口径要「展示面只报注册表默认值」，
     那要换成 `plan(..., None)`，请终审一句话裁。
  3. **上下文收口不在这里**：`plan()` 没有请求体 ⇒ 报的是「计划面 primary」，
     而 §5 的 context 粗估在 Task 4 的 execute 前置做 ⇒ 超大上下文的请求真会用到更靠后的候选。
- **等式与反证都在**：无 key 时 `== settings.ollama_model` 成立，是因为出厂注册表本地主条目
  （`ollama-ornith` = `ornith-1.5:9b-text`）与部署的 `OLLAMA_MODEL` 同名（`backend/.env` 实测）；
  `test_the_name_follows_the_registry_primary_not_the_ollama_setting` 故意把两者分开，
  证明读的是注册表而不是 setting。也就是说：**如果哪天 `OLLAMA_MODEL` 与注册表条目改名而不同步，
  `model_used` 会跟着注册表走**（§9「响应 model 字段来自实际选中模型」优先于「等于 OLLAMA_MODEL」），
  这是 §9 的语义而不是回归。这一点值得进 T11 的验收说明。
- `complexity="low"` 只是占位（§5 打分今天不看它，T3 报告「偏离 3」）。若将来复杂度参与裁决，
  展示面要先决定「没有问题文本时的默认档位」，我在 `_RAG_PROFILE` 的注释里留了这句话。

### 5. 迁移后 `app/rag.py` 的 D6 命中面（拿这个数字更新 T9 的豁免清单）

> **本段在修复轮 1 被整段重写**（评审 §4 Minor 5 + §6 第 4/6 条）。首轮这张表把
> `settings.openai_api_key` 记成「5 处代码命中」，其中 **L92 / L109 其实是 docstring 散文**
> （`current_model_name` 的 docstring 与「失败面」段各提了一次），真实**代码读法只有 3 处
> = L142 / L202 / L206**。T9 以下面这张「代码 / 散文」分列的表为准，逐枚按**文件 + 行**列进
> 豁免，禁前缀放行。核对方式：代码侧按「非注释行」逐枚数（`RagLegacyEgressInventoryTests`
> 钉的是等式），散文侧按行号读原文。文件共 **280 行**。

| 模式 | 代码命中 | 代码行号 | 散文/注释命中 | 散文行号 | 给 T9 的口径 |
| --- | --- | --- | --- | --- | --- |
| `httpx` | **3** | 27（`import httpx`）、204（openai 腿 `httpx.post(`）、220（ollama 腿 `httpx.post(`） | 7 | 9、10、13、18、20、22、246 | 3 处全是 legacy 出口，随 legacy 删除而消失 |
| `httpx.post(` | 2 | 204、220 | — | — | 上面那 3 枚里的两枚 |
| `import httpx` | 1 | 27 | — | — | |
| `httpx.get` / `httpx.Client` | **0** | — | — | — | 展示面零出口；本轮起由 `RagDisplayedModelNameTests` 的**三道 httpx 闸**（`get`/`post`/`Client`）+ 探针上闸 + MockTransport 零请求共同钉住，不再靠读代码证 |
| `"/chat/completions"` | 1 | 203 | 1 | 11 | ⚠ **无 `/v1` 前缀** ⇒ `task-9-brief.md` 的模式集（`/v1/chat/completions`）对这条腿**不可见**，必须把字面量 `/chat/completions` 加进扫描集（`SingleEgressStructureTests.FORBIDDEN_LITERALS` 早已含它，两份口径本来就对齐） |
| `"/api/chat"` | 1 | 221 | 1 | 11 | |
| `settings.openai_base_url` | 1 | 203 | 0 | — | 端点拼接（唯一一处） |
| `settings.ollama_base_url` | 1 | 221 | 0 | — | 端点拼接（唯一一处） |
| `settings.openai_api_key`（**代码读法**） | **3** | 142、202、206 | **2** | 92、109（docstring 散文） | L142 = `_legacy_model_name()` 读 bool、L202 = legacy 分支 `elif` 读 bool ⇒ **两处不发请求**；只有 **L206** 进 `Authorization` header，是唯一那枚凭据出口 |
| `OLLAMA_BASE_URL` / `*_API_KEY`（大写 env 字面量） | **0** | — | — | — | 本文件不读裸 env，全部经 `settings` |
| `timeout=120` | 2 | 215、230 | — | — | legacy 原样（评审 M7 变异钉着） |
| `"temperature": 0.1` | 1 | 209 | — | — | legacy 分支原样；router 腿走 `RAG_LEGACY_TEMPERATURE` 单一出处 ⇒ 全文件代码里的 `0.1` 字面量**只剩这一枚** |
| `settings.ollama_model` / `openai_model` | 3 / 2 | 99、144、223 / 143、208 | 0 | — | 模型名默认值，不是出口 |

- 文件头部有一段 D6 豁免说明（**逐枚点名 3 + 2**、指向 DESIGN §1/§7、矩阵 **#18**、
  以及「下一稳定版必须删除 legacy」这条义务），Task 9 的守卫测试可以直接引这段。
- 这组数字**已被测试钉成等式**：`RagLegacyEgressInventoryTests`
  （3 处 httpx 代码命中 / 2 处端点字面量 / `httpx.get`+`httpx.Client` 必须为 0）。
  删 legacy 的那一次改动会让它变红——那是**故意的**：届时它应被改成「全零」而不是被删。
- `settings.openai_api_key` 的 3 处代码读法里 **L142 与 L202 是「读 bool」不是出口**
  （D6 禁的是指向 LLM endpoint 的出口，不是读配置）：T9 若按 `_API_KEY`（大小写不敏感）扫，
  要把 L142 / L202 / L206 按**文件 + 行**分别列进豁免并标出各自语义（前两枚读配置、
  第三枚才是 header），另加 `health.py` 里 T2 落的同类读法。


### 6. 被改动的既有断言逐条清单

**条数：0。** `diff` 核验：
`snap-task5/tests/test_model_router_v23_contract.py` → 工作树 = **删除 0 行、新增 810 行**
（`grep -c '^<'` = 0）；其余 5 个被点名会牵动的文件（`test_llm_usage_contract.py` /
`test_web_search_contracts.py` / `test_runtime_metadata_contract.py` /
`test_typesafe_api_runtime.py` / `test_typesafe_security_contract.py` /
`test_agent_contracts.py`）**mtime 均早于本任务窗口、零写入**，749 例基线全部原样绿。

需要交代的两处「差点需要改既有断言」：
1. `FallbackContractTests::test_run_complete_signature_is_frozen` 与
   `test_run_stream_signature_and_session_surface` 用 `fields_[:5]` / `[:6]` 切片断言字段序
   ⇒ **切片而不是全等**，所以末位加 `plan` 不破它们（这正是裁定 C 选「末位默认值」的理由）。
   我没有为它们做任何适配。
2. `ModelRouteTraceShapeTests` 里两处直接 `AllCandidatesFailedError(attempts, reason_codes=…)`
   的构造断言 `payload["context_dropped"] == 0`：新参数带默认值 ⇒ 仍然成立（我复核过这两例，
   并把「不填也是 0」另钉进 `PlanCarrierTests::test_plan_defaults_to_none_for_legacy_constructions`）。

一处**顺带产生的实现文档漂移**（不在我的改动面，交给主 agent 决定是否回写）：
`app/llm/usage.py:369-371` 那句「`AllCandidatesFailedError` 没有 `selected_index` /
`context_dropped` 两枚字段 ⇒ 那三枚按『没有事实』落」。T6 之后它只剩一半为真
（`context_dropped` 现在有了，`selected_index` 仍没有）。**行为**上没有破坏任何 T5 断言
（那两例的异常是测试自己构造的，未传 `context_dropped` ⇒ 仍是 0），只是那句话该改。

### 7. 移交 T7 / T8 / T9 的硬事实

- **T7/T8**：`attach_model_route(trace, result.plan, result, profile=profile)` 的形状
  现在**有数据可走**（三个填值点 + 7 例钉住）。`AllCandidatesFailedError` 同时带
  `plan` 与 `context_dropped`，D2 那一条降级路不再解释不了。
  两个残留缺口：①`NoCapableModelError` **仍然不带** `plan`/`context_dropped`（任务书没派，
  我没加）⇒ T8 若在 fast-path 里要挂 trace，得自己把 `plan` 传下去；
  ②`_usage_from_failure` 写的是条目 id（T5 遗留 minor 3 的同一处）。
- **T9**：D6 豁免清单按上面第 5 段那行表格抄；`RagLegacyEgressInventoryTests` 已经替 T9
  钉了等式，T9 只需把 `app/rag.py` 放进 legacy 豁免名单并核对**数字一致**。
- **T11**：§9 修订说明要收的两条行为变更 = 上面「C 组裁定」的温度偏差 +
  「§4」里 `model_used` 改为注册表 authoritative（与 `OLLAMA_MODEL` 解耦）。
  另外矩阵 #18 的「三链原行为」目前 **RAG 那一腿有报文级证明**（温度组 6 例），
  SSE/Agent 两腿等 T7/T8 补同样形状的门闸。

## 我没有做的事（诚实清单）

1. **没有**改 `app/llm/__init__.py`（任务书允许「仅当 `plan` 透传需要」；实测 `complete()`
   原样返回 `run_complete` 的对象 ⇒ 零改动，`test_complete_passes_the_result_object_through_untouched`
   用 `assertIs` 钉的就是这件事）。
2. **没有**动 `native_stream.py` / `agent.py` / `conversation_agent.py` / `app/security.py` /
   `config.py` / `provider.py` / `normalize.py` / `router.py` / `registry.py` / `usage.py` /
   `health.py` / `classifier.py` / `models.py`，也没动 `config/llm_registry.json`。
3. **没有**改或删除任何既有测试断言（0 条；证据见上面第 6 段）。
4. **没有**打真实外呼：全程 MockTransport / `httpx.post` 替身 / stub 健康视图；
   也**没有**跑真实双模型 failover（矩阵 #4/#5 那种两候选链只在 ledger 组里以
   `serve_sequence` 的形状出现过一次，用于证 `model` 列跟着真候选走；真实 Ollama 归 T10）。
5. **没有**给 RAG 造 trace、**没有**接 `attach_model_route`（按任务书）。
6. **没有**为 `NoCapableModelError` 新增写账路径（冲突已如实报，见第 2 段）。
7. **没有**做 git 写操作（改动面按 mtime + 与 `snap-task5/` 的 `diff -u` 核对）。
8. **没有**动 `SYSTEM_PROMPT` 的两条中文硬约束、`build_context`、`web_search` 调用面、
   TypeSafe 相关逻辑（`test_web_search_contracts` / `test_agent_contracts` 的源码扫描原样绿）。
9. **没有**把 legacy 的 `except Exception` catch-all 收窄、**没有**把
   `模型连接错误：{type(exc).__name__}` 里的类名换成字面量（全仓 grep 过：`模型连接错误`
   在 `tests/`、`frontend/`、`docs/` 里 **0 命中**，只有 3 份历史快照的 `rag.py` 副本 ⇒
   没有任何断言依赖这句话，所以「保住类名语义」这件事由我新加的两例负责，而不是由
   「有没有测试读它」决定）。

## 遗留 minor

1. **`usage.py:369-371` 那句话现在只有一半为真**（`AllCandidatesFailedError` 已有
   `context_dropped`）；纯文档漂移，行为不变。不在我的改动面，留给主 agent 或 T9。
2. **展示面读熔断态、生成路读探针 + 熔断**：两处的候选在「provider 恰好坏了」的窗口里会
   劈叉（有界在 60s 探针缓存内）。要消掉只能给 `health.py` 加「只读缓存、不触发探测」的公共口
   （现在是私有 dict），会新引入一个观测面 API ⇒ 不在本任务裁。
3. **`_RAG_PROFILE.complexity="low"` 是占位**：今天不参与打分（T3 偏离 3）。若 T9/T11 之后
   有人让复杂度参与裁决，展示面会需要一个「没有问题文本时」的显式策略。
4. **legacy 腿的 catch-all 宽度**仍在（矩阵 #18 要求），代价是 RAG 路上非 Router 家族的
   异常（例如未来某处 `TypeError`）也会被同一句文案吞掉。修法只有两个：删 legacy，
   或给 router 路单独一套 try——后者会让两条腿形状分叉、#18 的对照失去意义。留 legacy 删除时收口。
5. **`_legacy_model_name` 与 `probe_llm` 的「看 key」判断是两处独立读法**（`health.py` 里那份
   是 T2 落的）。两处都随 legacy 一起消失，现在不是 bug，但 T9 的扫描要认得它们。
6. **温度门闸是「一次问答、一条候选」形状的等价证明**：链走到 fallback 之后温度仍是 0.1
   （同一个 `LLMRequest` 复用），但本任务没有为「fallback 后温度不变」单独钉一例，
   那属 T10 真实 failover 的十字断言范围。
7. 本任务**未跑前端 build / docker**（无前端改动；T11 统一跑）。

## 门槛复跑

```
cd E:\xiangmu\rag\backend
python -m pytest tests/test_llm_usage_contract.py tests/test_model_router_v23_contract.py \
  tests/test_web_search_contracts.py tests/test_runtime_metadata_contract.py \
  tests/test_typesafe_api_runtime.py tests/test_typesafe_security_contract.py -q
  → 408 passed, 14 warnings, 381 subtests passed in 39.01s          （0 failed）

python -m pytest tests -q        # 终态，未中途 kill
  → 788 passed, 20 warnings, 878 subtests passed in 81.53s (0:01:21) （0 failed）
```

计数核对：基线 749 → 788 = **+39**（Task 6 新增 7 组 39 例：
`RagRouterMigrationTests` 6 + `RagTemperatureEquivalenceTests` 6 + `RagFailureFaceTests` 9 +
`RagLedgerTests` 2 + `RagDisplayedModelNameTests` 8 + `PlanCarrierTests` 7 +
`RagLegacyEgressInventoryTests` 1 = 39，`--collect-only` 实测 39/280；
其中失败面那组 9 例含开发中补的 2 例，见「红→绿」第 3 段）。
subtests 876 → 878 = +2（`test_the_new_fields_are_last_and_defaulted` 的两枚 subTest）。
变异脚本 11 发跑完后 `sha1` 还原核对全部一致，源码零残留。

---

# 修复轮 1（2026-09-24）

被修复对象 = 首轮独立评审 **Approved-with-fixes**（Critical 0 / Important 2 / Minor 8）。
本轮只做评审派下的 FIX-1..4，**没有**改 `app/rag.py` 与 `app/llm/fallback.py`
（评审判定它们 PASS；跑完全套件后两者 sha1 仍是 `a5a6387169…` / `008d8213bc…`，
与评审 §7 的 RESTORE 行逐字相同 ⇒ 除临时变异-还原外零残留）。

## 0. 本轮改动面（4 个文件，其中 2 个是新建）

| 文件 | 变化 | 做了什么 |
| --- | --- | --- |
| `backend/tests/test_model_router_v23_contract.py` | 4731 → **5019** 行（对 `snap-task5/` 仍是 **删除 0 行 / 新增 1098 行**） | FIX-1 新增 `ModelRouteIntegrationTests`（2 例）+ FIX-2 新增 `_FallbackFixture._isolate_usage_ledger`、`_RagMigrationFixture` 的 env 兜底、`LedgerIsolationGuardTests`（3 例）+ FIX-3 改造 2 枚既有断言（只增不减）+ 3 枚 import |
| `backend/tests/conftest.py` | **新建 166 行** | 会话级护栏：env 默认值 + `usage.database_path` 改道闸 + 逐例归责 + 终端 summary |
| `backend/app/llm/usage.py` | 369-371 → 369-373（**纯 docstring**） | FIX-4：修 `AllCandidatesFailedError` 的字段口径，代码零改动 |
| `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/t6fix1_mutations.py` | 新建 | 本轮 6 发变异脚本（字节安全版，先例 `t6_mutations.py`） |

**「既有断言改动」条数**：本轮动了 2 枚**首轮自己新增**的测试体（`test_the_zero_candidate_exit_writes_no_row_at_all`、
`test_the_display_face_never_touches_the_network`），两枚都是**加闸**不是放宽；对 Task 1-5 的
既有断言依旧 **0 条**（`diff snap-task5 → 工作树` 的 `<` 计数 = 0，本轮复测）。

**开工前的真实库状态**（只读 SQL 实测，主 agent 清理后）：`llm_request_logs` **0 行**、
`conversations` 7、`messages` 10。跑完全套件后**再测一次**：0 / 7 / 10，
`data/conversations.db` 的 sha1 全程 `39bca2c404e2…` 未变、mtime 全程停在 `Sep 24 04:47`
（本轮从没打开过它的写连接）。

> **给下一轮评审的范围核对提示（如实报）**：本轮**不要再用 mtime 判范围**。
> `find app tests -newermt` 会把 `app/rag.py` 与 `app/llm/fallback.py` 一起列出来，
> 那是变异脚本 R2/R6「临时改 → 立即还原」留下的时间戳，**内容一字未动**：
> `sha1(app/rag.py) = a5a6387169…`、`sha1(app/llm/fallback.py) = 008d8213bc…`，
> 与评审 §7 的 RESTORE 行逐字相同；`usage.py` 对 `snap-task5/` 的差异只有第 4 段那处 docstring。
> 判范围请用 `diff snap-task5/… + sha1`，或 `git status --porcelain`（本轮零 git 写，
> 工作树的 M 集合与首轮一致）。


## 1. FIX-1（评审 I-1）：矩阵 #17 的「真调用」半段 — **已交**

评审者给的骨架逐条落地，全部在 `tests/test_model_router_v23_contract.py` 内，`app/rag.py` 一行未改。

新增 `ModelRouteIntegrationTests(_RagMigrationFixture)`（2 例）+ `MODEL_ROUTE_NINE_KEYS` 常量：

- `spy_the_real_chain()`：给 `llm.complete` 与 `llm.classify` 各挂一枚 spy，抓的是**这条链
  真正用过的那份 `profile`**（不是测试另造的画像）与真 `result`/真异常对象。链路是
  真 `generate_answer → llm.complete → classify → plan → run_complete → provider(MockTransport)`。
- `test_a_real_llm_complete_lands_a_nine_key_model_route`（成功路）钉：
  ① `set(trace["model_route"]) == 九键` + `len(route) == 9`（多一枚少一枚都红）+
  `set(trace) == {"trace_id","events","model_route"}`（additive，已有字段没被挤掉）；
  ② `route["attempts"]` **非空**、`route["primary"]["model"] == result.response.model`（M2 同源）、
  `route["attempts"][0]["model"] == result.response.model`、`stage=="primary"`、
  `selected_index == result.selected_index`、`requirements` / `primary` 的子键集合等式；
  ③ 整份 trace `json.dumps` 后 `RAG_PROMPT_CANARY` / `SYSTEM_PROMPT[:24]` /
  「请依据以下证据回答问题」/ 证据正文 **0 命中**；
  ④ **真写 JSONL 再读回**：`TRACE_PATH` 指到临时文件 → `save_trace` → 单行 →
  `json.loads(line)["model_route"] == route` → 再过 `get_trace("t6-integration")` 等式
  （内存对象不算交付，评审点名的那句）。
- `test_the_aggregate_failure_branch_lands_stage_none_with_the_drop_count`（降级路，
  §8.1 第 4 条点名「降级路最需要解释」）：真链跑出 `AllCandidatesFailedError`
  （候选 A 的 `limits.context_tokens=10` 被上下文收口剔掉 ⇒ `exc.context_dropped == 1`；
  候选 B 真外呼吃 500），`attach_model_route(trace, exc.plan, exc, profile=profile)` 后钉
  `stage=="none"`、`selected_index == -1`、`context_dropped == exc.context_dropped == 1`、
  `attempts` 长度 1（被剔的那条不许出现在 attempt 里）、`attempts[0]["result"]=="failed"`
  且 `error_type=="model_unavailable"`、用户侧仍是 D2 现文案，另钉
  `route["attempts"][0]["model"] == 真账本行的 model`（trace 与账本同一个词）。
- 未越界：没给 RAG 造 trace（`/api/query` 今天没有 trace 对象），没接 SSE/工具轮。

**验收**：`python -m pytest tests/test_model_router_v23_contract.py -k ModelRouteIntegration -q`
⇒ **2 passed / 283 deselected in 31.90s**（要求是 ≥1，评审给的门槛是 ≥2，实际 2）。
**红→绿**：这两例在首轮是**不存在**的（`attach_model_route` 在 T6 的测试里出现 0 次）；
本轮先落地即绿，其「真的挡得住」由 R1/R2/R5 三发变异证明（见第 5 段）。

## 2. FIX-2（评审 I-2）：测试写真实库 — 做成**系统级护栏**，不只是一次补漏

**(a) 补漏（本任务新增 39 例的自查 + 同族扩面）**
`_FallbackFixture.setUp` 新增 `_isolate_usage_ledger()`：① 显式内存 sink
（`llm.set_usage_sink(self.ledger_rows.append)` + `addCleanup` 还原，照 `PackageEntryPointTests`
现成姿势）；② `CONVERSATION_DB_PATH` 指到本例临时目录。隔离做在**基类**而不是
`PlanCarrierTests` 一处——同族 7 个类（含未来新增的子类）一起被罩住。
`_RagMigrationFixture` 补第三道 env 兜底（它原本只有 `init_usage_db` 的覆盖值，
覆盖值一旦被删就直通真库）。

**(b) 护栏（新建 `backend/tests/conftest.py`）**
1. 会话级：`CONVERSATION_DB_PATH` 未被调用方显式设置时指到会话临时目录（设过的一律不动）。
2. **路径层 = 真正的护栏**：包住 `app.llm.usage.database_path`，凡解析到仓库 `data/` 底下的
   生效路径一律改道到会话临时库并记一笔。为什么必须有这一层：`_EgressFixture` 用
   `mock.patch.dict(os.environ, {}, clear=True)`（Task 1 就在用的手法，不该为护栏去改它），
   它会把第 1 层设的 env 一并清掉 ⇒ 光靠 env 拦不住。
3. 逐例归责：autouse function fixture 在本例收尾时，只要记过一笔就让**这一例**红。
4. `pytest_terminal_summary` 把改道计数打在终端上 ⇒ 跑一次全套件就是一份同类漏洞清单。

**(c) 防回潮钉 `LedgerIsolationGuardTests`（3 例）**
① `guard_is_active()` 且**生效路径**不在仓库 `data/` 下、不等于真库；
② 本会话 `ledger_redirects() == []`；③ 真库 `llm_request_logs` **仍是 0 行**（只读 URI）。
口径取舍（要主 agent 知道）：③ 用的是评审给的**首选**口径「跑完后真库必须仍是 0 行」。
它的代价是**在开发机上跑过真实应用、账本里已有真样本的人会让这枚红**（那时 ①② 仍然成立，
护栏也确实保护了那份数据）。若 T11 判定「开发机可能有真账」不可接受，最小改法是把 ③ 换成
「会话开始时的行数快照 == 结束时行数」的等式（护栏只保证不新增，不承诺历史为 0）。
本轮按评审原文交付，没有擅自换成弱口径。

**(d) 同类隔离漏洞自查结论（逐条，实测不是推断）**
- 全仓写账只有一条路：`app/llm/__init__.py:_log_usage → usage_sink()`（惰性解析到真
  `log_usage`）；发起点只有 `llm.complete()` 与 `llm.log_stream_usage()`
  （`run_complete`/`run_stream` 本身不写，`grep _log_usage app/llm/fallback.py` = 0 命中）。
- 会走 `llm.complete()` 的夹具逐个过：`PackageEntryPointTests` 12 处（T4 自带 sink，
  评审实测干净）、`_RagMigrationFixture` 系（临时库 + `set_usage_sink(None)`，干净）、
  `PlanCarrierTests`（**唯一真漏洞**，就是评审数到的那 22 行）、
  `test_llm_usage_contract.py` 全族 `_UsageFixture`（`init_usage_db(tmp)` + 显式 sink，干净）。
- **结论：本轮实际找到并修掉的同类洞 = 1 处（`_FallbackFixture` 族）；另补 1 处防御缺口
  （`_RagMigrationFixture` 缺 env 兜底）。** 护栏装完后**全套件 793 例的 `[ledger-guard]`
  计数 = 0**（两次终态跑都是 0）⇒ 除上述两处，全仓再无第二个「测试写真实账本」的漏点。
- **与既有期望的冲突清单**（grep `data/conversations.db` 与 `database_path(`）：只有
  `test_database_path_shares_the_conversation_store_source`（`tests/test_llm_usage_contract.py:363`）
  与 `test_warmup_creates_a_table_a_fresh_deployment_does_not_have`（同文件 :1930）两枚读
  `database_path()`。两枚都把 env **显式**设成临时目录、目标不在仓库 `data/` 下 ⇒
  护栏的改道分支不触发、原样返回 ⇒ 期望逐字不变（双文件 386 例里两枚均绿）。
  **没有静默改掉任何一枚的期望**，也没有新增依赖默认路径的用例。

**(e) 顺带掉评审 I-2 那枚「同源但可容忍」**
`RagFailureFaceTests::test_the_http_face_still_returns_200_when_no_candidate_is_capable`
现在把 `app.audit.AUDIT_PATH` 指到临时文件 ⇒ 本轮全套件跑完后 `data/audit.jsonl` 里
canary 问题文本的命中数**没有增长**（21 → 21，实测）。**未**做全局 audit 改道，两条理由：
`app/knowledge_os.py` 是 `from app.audit import AUDIT_PATH`（import 期绑定），会话级 patch
会让「写」与「读」劈叉；且 §8 的「永不存储」约束的是账本，audit 记 query 是既有设计。
其他任务的文件仍会往 `data/audit.jsonl` 追加（本轮实测 +1830 B，均为非 T6 用例的文本）
⇒ 留给 T9/T11 统一裁，见「仍存 minor」第 6 条。

## 3. FIX-3（Minor 1 / 2）

- **Minor 1**：`test_the_zero_candidate_exit_writes_no_row_at_all` 的第二枚断言原先在
  `rows == []` 上是同义反复。现在先落**一行合法成功账**作对照组，再跑零候选那一支，
  断言变成三枚：库里恰好 1 行（= 对照组那行，**行数不增长**）、那一行 `success=1`、
  以及**非空表上**「不存在 `success=0` 且 `error_type` 为空的行」。原强度只增不减。
- **Minor 2**：`test_the_display_face_never_touches_the_network` 补
  `mock.patch.object(rag_module.httpx, "get"/"post"/"Client", forbidden)` 三道闸，
  与 `fail_on_any_probe()`（setUp）+ `self.requests == []` 并列为**三道**；
  「展示面零网络」从此由测试保证而不是代码读证。反证 = 变异 R6。

## 4. FIX-4（Minor 4）：`app/llm/usage.py` 的文档漂移

**只改 docstring**（369-371 → 369-373），代码零改动；`diff snap-task5/app/llm/usage.py` 实测
**只有这一处**：

```
369,371c369,373
<       fast-path、RAG 兜底文案）**尤其**需要一条能解释的 route。它没有 `selected_index` /
<       `context_dropped` 两枚字段 ⇒ 那三枚按「没有事实」落：`stage="none"`、
<       `selected_index=-1`、`context_dropped=0`（不猜）。
---
>       fast-path、RAG 兜底文案）**尤其**需要一条能解释的 route。它**没有** `selected_index`
>       这一枚事实（一条候选都没跑通，也就没有「选中第几条」）⇒ 该枚连同由它推出来的
>       `stage` 按「没有事实」落：`selected_index=-1`、`stage="none"`（不猜）。
>       `context_dropped` 则**自 Task 6 起是它带的字段**（§8.1 第 4 条：降级路最需要解释的
>       恰好是「有几条候选根本没被允许尝试」）⇒ 这里读异常里的那个真数，不再恒 0。
```

## 5. 变异（修复轮 1：6 发，全部 RED 被杀，存活 0）

脚本 `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/t6fix1_mutations.py`（受管 5 个文件，
锚点命中数必须恰好 1 否则 SKIP，逐发还原后核对 sha1，收尾再全量核对；实测「全部一致」）。

| # | 变异 | 结果 | 被哪枚钉杀死 |
| --- | --- | --- | --- |
| **R1** | 把集成例里的 `attach_model_route(trace, result.plan, result, profile=profile)` 整行换成 `_ = (trace, result, profile)`（**评审点名的必做发**） | **RED** | `test_a_real_llm_complete_lands_a_nine_key_model_route`（`assertIn(MODEL_ROUTE_KEY, trace)`） |
| **R2** | `fallback.py`：聚合异常不填 `context_dropped`（恒 0）（**必做发**） | **RED** | `test_the_aggregate_failure_branch_lands_stage_none_with_the_drop_count`（`context_dropped == 1`） |
| **R3** | 拆掉 `_FallbackFixture` 的账本隔离（sink 交回惰性解析 + 撤掉 env 兜底）=「新测试忘关 sink」那一类事故（**必做发**） | **RED** | 归责准确：`ERROR PlanCarrierTests::test_complete_passes_the_result_object_through_untouched`（护栏的逐例闸）+ `FAILED LedgerIsolationGuardTests::test_no_test_in_this_session_tried_to_write_the_real_ledger`（防回潮钉）+ 终端 `[ledger-guard] data\conversations.db ⇒ <会话临时目录>/conversations.db` |
| R4 | `usage.model_route_trace` 少交一枚 `context_dropped` 键（九键变八键） | **RED** | 两枚集成例的键集合等式（+ T5 的 `ModelRouteTraceShape` 族，跨两个文件同时红） |
| R5 | `usage._trace_stage` 不再认 `selected_index < 0`（降级路谎报 primary） | **RED** | 降级那枚集成例（`stage == "none"`） |
| R6 | `rag.py::current_model_name()` 里偷偷塞一枚 `httpx.get(...)`（Minor 2 的靶子） | **RED** | `RagDisplayedModelNameTests`（三道 httpx 闸；`--tb=line` 显示的是闸自己的 `AssertionError`） |

诚实标注：R4 与 R5 打的是 `app/llm/usage.py`（T5 的文件、本轮只允许改 docstring）——
**临时改、跑完立即还原、sha1 逐发核对一致**，最终树里 `usage.py` 的差异只有第 4 段那处 docstring。

## 6. 终态数字（本轮亲跑，未中途 kill）

```
cd E:\xiangmu\rag\backend
python -m pytest tests/test_model_router_v23_contract.py -k ModelRouteIntegration -q
  → 2 passed, 283 deselected in 31.90s                        （FIX-1 的验收口径）

python -m pytest tests/test_model_router_v23_contract.py tests/test_llm_usage_contract.py -q
  → 386 passed, 7 warnings, 381 subtests passed in 45.89s      （0 failed，双文件交付口径）

python -m pytest tests/test_llm_usage_contract.py tests/test_model_router_v23_contract.py \
  tests/test_web_search_contracts.py tests/test_runtime_metadata_contract.py \
  tests/test_typesafe_api_runtime.py tests/test_typesafe_security_contract.py -q
  → 413 passed, 14 warnings, 381 subtests passed in 42.70s     （0 failed；首轮 408 + 本轮 5）

python -m pytest tests -q                                       # 终态，一次跑完
  → 793 passed, 20 warnings, 878 subtests passed in 108.31s (0:01:48)   （0 failed）
```

- 计数解释（一次讲清，不留歧义）：**788 → 793 = +5 例 / subtests 878 不变**
  = `ModelRouteIntegrationTests` 2（FIX-1）+ `LedgerIsolationGuardTests` 3（FIX-2 护栏钉）。
  评审 §6 第 12 条建议把哨兵塞进既有 subTest「避免又一次计数解释」——我**没有**那么做：
  这五枚各有一发变异打红，塞进别人的 subTest 会丢掉归责（R3 的证据链正是靠独立归责）。
- **清理后真实库仍为 0 行的实测证明**（跑完全套件之后，只读 SQL）：
  `llm_request_logs` **0 行** ｜ `conversations` 7 ｜ `messages` 10 ｜
  `data/conversations.db` sha1 `39bca2c404e2…` 与开工前逐字相同、mtime 停在 `Sep 24 04:47`；
  同轮 `[ledger-guard]` 计数 **0**。`data/agent_traces.jsonl` mtime 停在 `Sep 23 15:58`
  （新增的 JSONL 往返例只在临时目录里落盘）。
- 约束核对：零 git 写；零真实外呼（新增两枚例的出口仍只有 `httpx.MockTransport`，
  本机 Ollama 的 `phi3:mini` 没被打扰）；零新增依赖；`app/rag.py` / `app/llm/fallback.py`
  sha1 未变；`tests/` 里除本轮 4 处新增/改造外无其他改动。

## 7. 修复轮 1 之后仍存的 minor（如实报，未偷偷做）

1. **Minor 3（同源自比）原样保留**：`effective_model_name_for_entry(result.plan.primary.model)
   == result.response.model` 仍是左侧=右侧的算法。本轮新增的集成例把
   「trace 的 `attempts[0].model` 与账本 `model` 列是同一个词」也钉上，同源自比的比重被
   稀释而不是加重；真正的反证仍在 `RAG_LOCAL_MODEL` 字面量 + `RagDisplayedModelNameTests`
   的注册表分叉反证那两枚上。
2. **Minor 6 / 7 未动**：`_RAG_PROFILE.complexity="low"` 的展示面画像口径归 T11 文档；
   `StreamInterrupted` 不带 `plan`/`context_dropped`（`fallback.py:873-879`）归 T7 ——
   两者都不在本轮改动面。T7 请照本轮 R2/R5 的形状给「流式中断那支」也补一枚集成钉。
3. **护栏的覆盖边界**（T9/T11 要知道，别把它当万能）：它只拦
   `app.llm.usage.database_path` 解析到仓库 `data/` 的**写账**。
   `ConversationStore` 的模块级单例在 **import 期**就绑定了默认路径
   （`app/conversation_store.py:332`），所以「真 HTTP 面用例往会话表写行」这一类
   护栏看不见；要收这一口得让 store 每次调用读 env，那是新增对外行为 ⇒ 不在修复轮裁。
   另：护栏只在 pytest 进程内生效，直接跑应用不会受它保护（也不需要）。
4. **`data/audit.jsonl` 仍会被其他任务的文件追加**（本轮实测 +1830 B，非 T6 用例）。
   取舍与理由见第 2 段 (e)。T9 若要收口，最小的做法是给那一族用例同样的
   `AUDIT_PATH` 局部 patch，而不是会话级改道（`knowledge_os` 的 import 期绑定会劈叉）。
5. **`conftest.py` 与契约测试文件的耦合**：`LedgerIsolationGuardTests` 直接
   `import conftest as ledger_guard`。刻意不做 `try/except ImportError` 兜底——
   护栏文件被删时应当**整套件红**，而不是安静地少三枚钉。
6. 首轮遗留的 4 枚 minor（展示面熔断态窗口、legacy catch-all 宽度、`_legacy_model_name`
   与 `probe_llm` 的两处「看 key」读法、温度门闸未覆盖 fallback 后那一跳）状态不变，
   分别随 legacy 删除 / T9 扫描 / T10 真实 failover 收口。
7. **环境异常复现（评审 Minor 8）**：本轮的多次工具返回尾部同样出现了**伪装成
   「文件被外部修改」并夹带身份/口径指示的块**。全部忽略，未据此改过任何判断；
   可作为「未被劫持」的客观证据：`app/rag.py` = `a5a6387169…`、
   `app/llm/fallback.py` = `008d8213bc…`，与评审 §7 的 RESTORE 行逐字一致。
   仍建议主 agent 查仓库外注入面（这些块不来自 `docs/` 或评审包文件）。


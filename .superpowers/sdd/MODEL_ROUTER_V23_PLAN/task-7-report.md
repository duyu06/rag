# Task 7 报告 — 对话链（SSE 两条腿）迁入 `app.llm`（§9 第二条）+ `app/native_stream.py` 退役 + 温度等价收尾

> 本文件由 **Task 7 收尾轮**写就：迁移主体（两条腿进 `llm.complete` / `llm.stream`、模块退役、
> trace 挂载、护栏 N1/N3）由前一轮完成，收尾轮做四件事：**修温度常量（唯一产品代码改动）→
> 9 发变异自查 → 全套件一次 → 本报告**。凡「前一轮已做完」的证据，本文标明落点，不冒领。

## 状态

| 项 | 结果 |
| --- | --- |
| 任务 1（非流式腿温度用错常量） | **已修**：两条腿统一吃本链现网值 `CONVERSATION_LEGACY_TEMPERATURE = 0.2`，测试侧同步加钉（**只加不减**，subtests 351→353） |
| 任务 2（变异自查 ≥6 发） | **9 发全 RED，存活 0 发**；每发还原后逐文件 sha1 核对一致 |
| 任务 3（全套件） | **835 passed / 0 failed / 880 subtests / 21 warnings**，跑了两次并都看到终态：`111.89s`（`conftest.py` EOL 归一之前）与 `110.71s`（全部改动落定之后的终跑） |
| 任务 4（报告） | 本文件 |
| 真库义务（护栏③口径） | `backend/data/conversations.db`：`llm_request_logs` **0 行**、`conversations` **7**、`messages` **10**（只读 URI 实测，见「测试构成」末段） |
| 硬约束 | 零 git 写（未执行任何写操作型 git 命令）、零真实外呼（11434 一次都没打，全程 `httpx.MockTransport`）、零新增依赖、`app/rag.py`/`app/agent.py`/`app/llm/{router,classifier,registry,usage}.py` 与 `fallback.py` **字节未动**（下表有 sha1 证据） |

## 交付文件（改动面 = **本任务窗口**，起点 `snap-task6/`，09-24 05:10 前后）

窗口内的文件级事实全部由「`snap-task6/` ↔ 工作树逐字节比对」+「mtime > 05:00」两把尺子取来，
不是凭记忆列。**19 个快照文件里 17 个逐字节 SAME**，只有下表这些动了。

### A. 产品代码

| 文件 | 窗口起点 | 现在 | 本窗口做了什么 |
| --- | --- | --- | --- |
| `backend/app/native_stream.py` | 63 行（`baseline-app/`） | **已删除** | 退役：NDJSON 行解析逐字节复刻进 `app/llm/normalize.py`，HTTP 出口收进 `app/llm/provider.py`。全仓零残留引用由 AST 扫描 + `importlib` 的 `ModuleNotFoundError` 双钉（`SseNativeStreamFieldFaceTests::test_the_module_is_gone_and_nothing_imports_it`） |
| `backend/app/conversation_agent.py` | 458 行（`baseline-app/`，即迁移前形态） | **595 行**（CRLF 原生，`sha1=c65937c0a841`） | 前一轮：两条腿迁 `llm.complete` / `llm.stream`、legacy 分支按 `router_enabled()` 保留、`session.finish()` 收执行面事实、`attach_model_route` 挂 trace、账本行取 `llm.log_stream_usage` 返回值。**收尾轮**：常量 `SSE_STREAM_TEMPERATURE` → **`CONVERSATION_LEGACY_TEMPERATURE`（覆盖两条腿）**、非流式腿从 `RAG_LEGACY_TEMPERATURE`（0.1）改回本链现值 0.2、删掉那枚不再使用的 `from app.llm import RAG_LEGACY_TEMPERATURE`、常量与两处调用点的注释重写 |
| `backend/app/conversation_stream_routes.py` | 250 行 | **284 行** | 前一轮：D5 的 SSE 出口——`StreamInterrupted` 用**现行事件词汇** `error` + `done` 落 payload 增量 `stream_committed` / `error_type`（不新增事件类型，`SseRoutePayloadTests.KNOWN_SSE_EVENTS` 钉着集合不许变大） |

**明说不许被误读的一条**：`app/llm/fallback.py` 与 `app/rag.py` 在本窗口**没有被改动**。
`fallback.py` 现在 943 行 / 0 CRLF / `sha1=008d8213bc05`，与 `snap-task6/app/llm/fallback.py`
**逐字节相同**（`app/rag.py` 同理，`sha1=a5a638716947` SAME）——这两枚是「非内容写入后已复原」
的结论，不是「我没查」。

### B. 测试

| 文件 | 窗口起点 | 现在 | 本窗口做了什么 |
| --- | --- | --- | --- |
| `backend/tests/conftest.py` | 166 行（LF） | **372 行**（LF，`sha1=4b1defdd5a21`） | 前一轮：护栏 N1（读/写分开归类，写才判红）+ N3（相对默认路径的**三候选**解析，从任何 cwd 都落进保护集）。**收尾轮**：一笔**非内容写入**——该文件被前一轮的文本模式读写翻成了 372/372 CRLF，收尾轮按字节还原为纯 LF（`replace(b"\r\n", b"\n")`；还原前后**去掉 CR 的 sha1 完全相同** = `4b1defdd5a21…`，即内容一字节未改）。不还原的后果正是主 agent 在 `fallback.py` 上点名的那种：与 `snap-task6` 的逐行比对会显示 372 行假差异 |
| `backend/tests/test_model_router_v23_contract.py` | 5019 行 | **6119 行**（LF，`sha1=df1717c548fc`） | 前一轮 +949 行（Task 7 段：6 个 `Sse*` 类 35 例 + `_SseMigrationFixture` 底座 + `business_file_has_no_second_llm_egress` + 护栏类改写）。**收尾轮 +68 行**：温度三处（详见「被改动的既有断言」段），删除 0 行测试例 |
| `backend/tests/test_p17_streaming_contract.py` | 60 行 | **132 行**（CRLF 原生，`sha1=808adcae4bea`） | 前一轮：`test_ollama_synthesis_uses_native_streaming` 换落成 `test_native_stream_module_is_retired_and_its_semantics_live_in_llm` 等（8 例）。收尾轮**未动**此文件 |

### C. 计划目录工件（不进产品树）

`t7_temperature_fix.py`（任务 1 的字节安全落盘器）、`t7_temperature_test_fix.py`（测试侧同步）、
`t7fix1_mutations.py`（9 发变异，字节安全）、`t7fix1_mutation_lab.log` + `t7fix1_mutation_lab_T1-T5.log`。
先例：`t6fix1_mutations.py`。三份脚本共同规矩：读 `bytes`、`bytes.replace`、写 `bytes`、锚点命中数
必须恰好 1 否则整份不落盘、还原后 sha1 比对并打印；`fallback.py` / `rag.py` 放进**禁改名单**
并在脚本收尾二次核对（输出「禁改 全部未动」）。

## 红 → 绿证据

### 1. 任务 1 本身的红（不是变异，是「改之前那版为什么错」）

事实链（全部读快照，不读记忆）：

* `baseline-app/conversation_agent.py:297-299` —— 非流式腿调 `agent_module._ollama_chat(messages, [])`；
  `app/agent.py:65` 的 `options` 现值 = **`"temperature": 0.2`**（Task 8 之前那支本任务没碰）。
* `baseline-app/native_stream.py:27-28` —— 流式腿硬编码 **`"temperature": 0.2`**。
* ⇒ 本链两条腿历史上**都是 0.2**。`RAG_LEGACY_TEMPERATURE`（0.1，`app/llm/__init__.py:98`）
  是 `app/rag.py` 那条链的现值，**不属于本链**。

变异 **T7** 就是「把常量搬回 0.1」这一次动作的复现（也等于修复前的现场）：

```
T7 → RED ['4 failed, 330 passed, …']
     红例 = SseStreamContractTests::test_the_legacy_ndjson_streaming_payload_is_reproduced_on_the_wire
            SseBufferedAndLegacyTests::test_the_buffered_leg_carries_the_conversation_temperature_and_the_legacy_option_keys …
```

改回 0.2 后：`tests/test_p17_streaming_contract.py + tests/test_model_router_v23_contract.py`
= **332 passed / 0 failed / 353 subtests**（改前 351，收尾轮净增 2 枚 subTest，例数不变：
改名 1 枚 + 替换 1 枚，**没有删除任何既有覆盖面**）。

### 2. 9 发变异的 RED 记录（断言真的挡得住的证据）

每发的还原都做了 sha1 核对：`变异态 sha1={…}` → `还原后逐文件 sha1 全部一致`；
脚本退出前再核一次全量（`收尾 sha1 核对：受管 全部一致 | 禁改 全部未动`）。

| # | 变异（打在什么上） | 结果 | 被哪条杀死 |
| --- | --- | --- | --- |
| **T1** | 任务书点名 #1：去掉**非流式腿**的 `temperature=` 参数 | **RED 1 failed** | `SseBufferedAndLegacyTests::test_the_buffered_leg_carries_the_conversation_temperature_and_the_legacy_option_keys`（**调用面 spy**：`seen[0]` 的 kwargs 里没有 `temperature` ⇒ 红）。**如实标注**：只钉报文值挡不住这一发——`LLMRequest.temperature` 字段默认恰好也是 0.2，删参之后线上字节一模一样。收尾轮加 spy 之前，这一发是**必然存活**的 |
| **T2** | 任务书点名 #2：post-commit 异常改成「再切一次出口重试」 | **RED 2 failed** | `SseCommitMatrixTests::test_matrix_11_post_commit_failure_never_switches_model`（`requested_models()` 变两条）+ `SseRoutePayloadTests::test_a_real_truncated_upstream_lands_error_plus_done_on_the_wire` |
| **T3** | 任务书点名 #3：逐 chunk 的 `redact_text` 摘掉（= 挪到收尾之后洗） | **RED 2 failed** | `P17StreamingContractsTest::test_redaction_happens_per_chunk_before_the_token_is_forwarded` + `SseStreamContractTests::test_redaction_happens_per_chunk_before_the_client_sees_it` |
| **T4** | 任务书点名 #4：删掉 `attach_model_route(...)` 那行 | **RED 3 failed** | `SseTraceIntegrationTests` 三例（成功流 / buffered / **commit 后中断**）——#17 集成半段全体红 |
| **T5** | 任务书点名 #5：`router_enabled()` 分支写反 | **RED 6 failed** | `test_matrix_18_the_legacy_branch_still_calls_agent_ollama_chat` + 温度两枚 + messages 等式 + `guard_legacy_chat_off` 那道闸 |
| **T6** | 任务书点名 #6：`native_stream` 取值改反（流式返回 False） | **RED 4 failed** | `SseStreamContractTests::test_the_stream_leg_forwards_every_content_chunk_in_order` / `…empty_answer…` + `SseNativeStreamFieldFaceTests::test_the_field_appears_exactly_at_the_three_pre_migration_sites` |
| **T7** | 温度常量改回 0.1（= 搬进 `app/rag.py` 那条链的值） | **RED 4 failed** | 两条腿的报文例各红一次（上表已列） |
| **T8** | `session.finish()` 从 `finally` 挪到正常收尾（`finally:` → `else:`） | **RED 6 failed** | `SseCommitMatrixTests` 三枚（pre-commit 全败 / 真实 kind / 矩阵 #11）+ `SseTraceIntegrationTests::test_the_interrupted_stream_also_lands_a_model_route` + `SseRoutePayloadTests` + p17 |
| **T9** | ttft 的「首个内容 chunk」记录点删掉 | **RED 1 failed** | `SseStreamContractTests::test_ttft_is_recorded_at_the_first_content_chunk` |

**存活：0 发。** 唯一需要交代的是 T1 的成因（见该格备注）：它不是「本轮侥幸杀掉」，
而是**上一轮的钉法本来会漏**——「漏参 = 吃字段默认」在这个链上恰好同值，所以必须钉调用面。

### 3. 一处诚实的口径修正（不是变异）

`app/conversation_agent.py` 的注释在 T7 期间把偏差挂在「已声明的行为变更」上，
并把不存在的类名 `SseTemperatureFaceTests` 写进了注释（实际类是 `SseBufferedAndLegacyTests`）。
收尾轮一并改成：**两条腿均与 legacy 逐字等价** + 真实类名。

## 测试构成（本窗口 = Task 7 全段）

| 组 | 例 | 钉什么 |
| --- | --- | --- |
| `SseStreamContractTests` | 10 | 流式序逐 chunk 不乱不合并；**退役模块当年的报文逐键复现**（`stream=True` / `tools=[]` / `think` / `keep_alive` / `options{temperature=0.2, num_predict}`）；ttft 记录点 = 首内容 chunk（且账本那枚同源不同轴）；逐 chunk 脱敏在 `token_sink` 之前；`done` 空 chunk 不推；`llm_ms`/`llm_calls`/`model_used` 语义；D1 别名；空答案文案；`timings` **键集合等式**；三条「没走到生成」的路零外呼零账无 route |
| `SseCommitMatrixTests` | 6 | 矩阵 #10（pre-commit 静默换候选、用户无感、`llm_calls` 仍 1）、#11（**post-commit 绝不换模型** = D5 主证据）、真实 kind 活过 commit、pre-commit 全败恰好一行 `success=0`/`fallback_index=-1`/`ttft_ms is None`、链上不自写账本哨兵（源码面）、零候选 0 行 |
| `SseTraceIntegrationTests` | 5 | #17 集成半段：`model_route` 九键 + 三张子视图键集封口 + **真 JSONL 往返** + 禁存项 0 命中 + 中断路也挂 + `llm` 包不碰 trace 形状 |
| `SseBufferedAndLegacyTests` | 6 | 任务书 A + D：buffered 腿走 `llm.complete(mode="rag")`、**温度枚（收尾轮重写）**、**两腿互等枚（收尾轮新增）**、矩阵 #18 的 legacy 原调用、两腿 `messages` 逐字相等、流式腿无 legacy 形态（不对称，见「裁定」段） |
| `SseNativeStreamFieldFaceTests` | 4 | 任务书 C 的关键区分（下表） |
| `SseRoutePayloadTests` | 4 | D5 的对外事件面：事件名只有 `error` + `done`，payload 增量两枚键；成功序 9 帧逐位不变；pre-commit 失败的既有 error payload **一字节不变** |
| `LedgerIsolationGuardTests` / `LedgerGuardClassificationTests` | 4 + 3 | 护栏 N1/N3：三候选路径、读不判红、写逐例判红、两份真库逐张点数 |
| `tests/test_p17_streaming_contract.py` | 8 | 模块退役后语义住在 `llm/`（`ollama_payload` / `ollama_stream_lines` 的**行为断言**，不是 grep）；未收 `done` 不算成功；逐字转发不切片；检索面不因迁移改动；逐 chunk 脱敏；SSE 只落一条 assistant 消息 |

**两枚考卷合计 332 例 / 353 subtests；全套件 835 例 / 880 subtests / 0 failed。**
基线口径：Task 6 末 793 passed / 878 subtests ⇒ 本窗口净增 **42 例 / 2 枚 subtests**。

真库实测（只读 URI：`sqlite3.connect(path.as_uri() + "?mode=ro")`，**不是**默认读写打开）：

```
E:\xiangmu\rag\backend\data\conversations.db   llm_request_logs=0  conversations=7  messages=10
E:\xiangmu\rag\data\conversations.db           llm_request_logs=<no such table>  conversations=0  messages=0
```

## `native_stream` **字段** ≠ `app/native_stream` **模块**（任务书 C 的区分证据）

| 面 | 迁移前 | 迁移后 | 谁钉 |
| --- | --- | --- | --- |
| 源码里 `"native_stream":` 出现次数 | 3（`events[final]` / `timings` / 非快路径字面 `False`） | **3**（逐枚对齐） | `SseNativeStreamFieldFaceTests::test_the_field_appears_exactly_at_the_three_pre_migration_sites`（`assertEqual(3, …)` + `native_stream = True` 恰 1 + `native_stream = False` 恰 1） |
| 取值集合 | `{True, False}`（bool，无字符串形态） | `{True, False}` | 同上 + `assertNotIn('"native_stream": "', SOURCE)` |
| 行为面取值 | 流式腿 True / buffered 腿 False / 非快路径 False / 三条无生成文案路 False | **同** | `SseStreamContractTests`（True ×2）、`SseBufferedAndLegacyTests`（False ×2）、`test_the_three_no_generation_paths_never_touch_the_llm`（False） |
| 白名单 | `PUBLIC_TIMING_KEYS` 含它 | 含它（`security.py` 本窗口未动） | `test_the_field_is_still_whitelisted_and_still_reaches_the_response`（`public_timings` 正反两向 + `evil` 键被丢） |
| **模块** | `app/native_stream.py` 63 行，被 `from app.native_stream import ollama_chat_stream` 引用 | **文件不存在、零 import**（`ollama_chat_stream` 在业务文件里出现次数 2 → **0**） | `test_the_module_is_gone_and_nothing_imports_it`：`ast` 全仓扫 `Import`/`ImportFrom` + `importlib.import_module` 必须抛 `ModuleNotFoundError` |

**口径要点（终审会问到）**：D6 的字符串黑名单**刻意不含** `"native_stream"` 这个键名——
`business_file_has_no_second_llm_egress()` 只把 `httpx` import、`from native_stream`、
`/api/chat`、`/chat/completions`、`ollama_base_url` 当出口痕迹，因为「留字段、退役模块」
正是本任务的区分点；把字段名当字符串扫进去会让合规代码自己变红。

## 裁定与移交

### 1. 温度：本链**没有**行为变更，请终审按此回写 DESIGN §9

* **结论**：`app/conversation_agent.py` 的两条腿迁移后发出的 `options.temperature`
  **与 legacy 逐字等价（都是 0.2）**，`num_predict` / `think` / `keep_alive` / `tools` / `messages`
  同源等价，两腿之间**唯一允许不同的键恰好是 `stream`**（等式钉，不是 `<=`）。
* **回写点**：DESIGN §9 里若把「SSE buffered 腿 0.2 → 0.1」记成已声明偏差，**请删掉那一条**——
  它来自本任务任务书的一处笔误（把 `RAG_LEGACY_TEMPERATURE` 当成了本链常量），代码已纠正。
* **边界要说清**：`RAG_LEGACY_TEMPERATURE`（0.1）**归 `app/rag.py` 那条链**，本链不用它；
  T6 报告 C 组与 `app/llm/__init__.py` 的 docstring 说的就是那一处，**没有被推翻**。
  矩阵 #18 的口径由「一腿声明偏差」变为「两腿逐字等价」。
* **为什么显式传参而不是让默认值兜**：`LLMRequest.temperature` 的字段默认恰好也是 0.2，
  漏参在**报文面不可见**（= 变异 T1 的成因）。所以本链显式传常量 + 断言等式 +
  断言 `llm.complete` 的 kwargs 里有 `temperature`。这条「巧合同值」值得 T8 注意：
  `app/agent.py::_ollama_chat` 迁进 `llm.complete` 时，**chat 腿的温度也要显式传**，
  否则会静默继承一个「谁都没决定过」的默认。

### 2. 流式腿没有 legacy 形态可留（不对称，请写进 §9 修订说明）

`LLM_ROUTER_ENABLED=false` 下**只有非流式腿**回到 `agent._ollama_chat` 原调用；流式腿的
「原实现」就是本任务退役的 `app/native_stream.py`，把 `/api/chat` + `httpx.stream` 内联回业务
文件等于开第二条出口（D6 / 矩阵 #19 直接红）。因此 #18 在这条腿上的对照面是**报文形状**
（`test_the_legacy_ndjson_streaming_payload_is_reproduced_on_the_wire`）而不是「旗标关掉走旧代码」，
由 `test_the_stream_leg_has_no_legacy_form_left_to_preserve` 把这件事钉成显式期望（关掉旗标也照样跑通、
`native_stream` 仍 True）。

### 3. commit 后中断的 token 三列为 0（诚实记账形状，非缺陷）

`test_a_provider_error_frame_after_content_keeps_its_real_kind` 记录：usage 只取
**成功收尾那一轮**的 provider 回执，交付过内容又断流 ⇒ `input/output/total_tokens` 全 0，
但 `error_type` 带着 provider 原始归类（`model_unavailable` / `retryable`），因此不会被
账本反推成 `client_aborted`（§8.1 第 2 条的交付闸）。要改成「半截 usage 也入账」得先动
`app/llm/usage.py` 的冻结口径 ⇒ 归 T9 矩阵收口裁决，本任务不动。

### 4. 移交 T8 的硬事实

1. 退役模块的字段留、模块走的判法（含 `business_file_has_no_second_llm_egress` 的黑名单组成）
   可直接复用；`agent.py` 迁完时 `app/agent.py` 里的 `httpx.post` 命中应归零，`rag.py` 那 3 枚
   legacy 出口命中（T6 报告 §5 的清单）也归 T8 一并收。
2. 温度：见 §1 末段的「显式传参」义务。
3. 若 T8 需要 `main_agent.py` / `conversation_routes.py` 的观测面（非快路径那支的
   `timings["native_stream"] = False` 在本窗口一枚字节没动），改的是 `run_conversation_agent`
   的 `else` 分支，不是 `_local_fast_path`。
4. **护栏的 EOL 义务**：`tests/conftest.py` 与 `tests/test_model_router_v23_contract.py` 都是
   **未跟踪文件**（`git status` 显示 `??`）⇒ `core.autocrlf=true` 对它们不起作用，工作树里是什么
   字节就是什么字节。写它们**必须字节安全**（本轮 `fallback.py` 与 `conftest.py` 两次翻车都是
   文本模式读写）。

### 5. 被改动的既有断言逐条清单（原来挡什么 → 现在挡什么）

按「旧文件里消失或被改写的非空行」逐行取，共三处来源：

**(a) 收尾轮：`tests/test_model_router_v23_contract.py` 的温度三处**

| 位置 | 原来挡 | 现在挡 |
| --- | --- | --- |
| `SseStreamContractTests::test_the_legacy_ndjson_streaming_payload_is_reproduced_on_the_wire`（流式腿温度） | `payload.options.temperature == 产品常量 SSE_STREAM_TEMPERATURE`（只此一条等式） | 常量改名 `CONVERSATION_LEGACY_TEMPERATURE` **且**另钉一枚测试侧独立写死的 `…_ON_THE_WIRE = 0.2`（产品常量被改也红）**且** `assertNotEqual(llm.RAG_LEGACY_TEMPERATURE, …)`。三枚，只加不减 |
| `SseBufferedAndLegacyTests::test_the_buffered_leg_carries_the_…`（原 `…_the_rag_temperature_…`） | 报文值 `== 0.1 == RAG_LEGACY_TEMPERATURE`——**钉错链的常量**（挡的是「有人把 0.2 搬回来」） | 报文值 `== 0.2 ==` 产品常量 `==` 测试侧独立常量；**加**调用面 spy：`llm.complete` 的 kwargs 必须含 `temperature`（= 变异 T1 的杀手）；`assertNotEqual(RAG_LEGACY_TEMPERATURE, …)` 从「等式」翻成「反证」；`options` 键集合、`think`、`keep_alive`、`tools` 四枚原样保留 |
| `test_the_declared_deviation_is_the_temperature_only` → **改名换骨**为 `test_both_legs_send_the_same_legacy_payload_except_the_stream_flag` | 伪造并**固化**一处行为变更：`assertNotEqual(0.2, 报文温度)`——即「buffered 腿必须发 0.1」 | 两腿**互等**：除 `stream` 外每一枚键（`options`/`think`/`keep_alive`/`tools`/`messages`/`model`）逐字相等，键集合差**恰好** `{"stream"}`；两腿温度各钉 0.2 + 产品常量 + `!= 0.1`（两枚 subTest）。原例的「报文键集合」断言原样搬进来，**未丢** |

**(b) 前一轮：`tests/conftest.py` 的护栏 N1/N3（同一测试的改写，`LedgerIsolationGuardTests`）**

| 原来挡 | 现在挡 |
| --- | --- |
| 「读过真库」就算违规（`database_path()` 被读写两条路共同调用，纯 `aggregate_status()` 也判红） | 按 `kind` 分判：**写才判红、读只 warning**（`test_a_pure_read_is_classified_read_and_never_pins_red` / `test_a_real_write_is_classified_write_and_would_pin_red`） |
| 只认 `backend/data` 一个目录（从非 `backend/` 目录跑套件时整层失效，行落在 `<cwd>/data/`） | **三候选路径**解析（绝对 / `backend/data` / `<cwd>/data`），`test_the_relative_default_resolves_into_the_protected_set_from_any_cwd` 钉从任何 cwd 都落进保护集 |
| 只点 `backend/data/conversations.db` 一张库 | **保护集里的每一份真库逐张点数**（仓库根那份历史库同样算），例名从 `test_no_test_in_this_session_tried_to_write_the_real_ledger` → `…wrote_the_real_ledger`、`test_the_repository_ledger_table_is_still_empty` → `test_the_protected_ledger_tables_are_still_empty` |

**(c) 前一轮：`tests/test_p17_streaming_contract.py` 的 12 行 grep 断言**

| 原来挡（读源码 + `assertIn` 字符串） | 现在挡 |
| --- | --- |
| `native_stream.py` 里含 `'"stream": True'` / `with httpx.stream(` / `'"tools": []'` / `'message.get("content")'` / `finished = False` / `'chunk.get("done") is True'` / `if not finished:` / 提前结束文案 / 不含 `range(0, len(answer), 14)`；`conversation_agent.py` 里含 `for text in ollama_chat_stream(messages):` | 逐条**换落点、不降强度**（文件内有迁移注释说明）：同样的语义从 grep 升级为**行为断言**（直接调 `normalize.ollama_payload` / `ollama_stream_lines`），「不许切片再吐」从「不含某个字面量」升级为「正向逐字相等 + CoT 一个字都不出现」；外加 `assertFalse((app/native_stream.py).exists())`——退役模块回来就红 |

## 我没有做的事（以及为什么）

1. **没有重新迁移、没有重读全仓**：接手时 `native_stream.py` 已删除、两条腿已在 `llm.*` 上，
   我按「快照比对 + mtime」取证，只改了任务 1 指名的那一处产品代码。
2. **没有动 `app/rag.py` / `app/agent.py` / `app/llm/{router,classifier,registry,usage}.py` /
   `app/llm/fallback.py`**（Task 8 与冻结件）。变异名单里**不含** `fallback.py`：D5 的
   「post-commit 不换候选」在执行器里也有一份，但本轮它**只许字节不变**，所以我把任务书点名
   #2 打在**本任务拥有的那层**（`conversation_agent.py` 的 `except StreamInterrupted` 分支改成
   再切一次出口），照样被 `test_matrix_11_post_commit_failure_never_switches_model` 杀掉。
   请 T9 补执行器侧那一发（改动点：`StreamSession._commit` 之后的 `fallback_allowed` 判定）。
3. **没有做真实双模型 failover**（Task 10 的活）；本机 11434 上的 `phi3:mini` 一次都没被打过——
   全部外呼都走 `httpx.MockTransport`，`self.requests` 是唯一的线上事实来源。
4. **没有写任何 git 命令之外的仓库状态**，也没有执行 `git add/commit/checkout`（零 git 写）。
5. **没有新增依赖、没有新增测试文件**；新钉全落在既有两张考卷里。
6. **没有替终审回写 DESIGN §9**（§1 的裁定段就是给终审的输入）。
7. **没有把 `SseTemperatureFaceTests` 这个不存在的类名留在注释里**——但**注意**：本窗口
   `app/conversation_agent.py` 在我接手期间被并发写过（见下条），终审核对文件时请以
   `sha1=c65937c0a841` 为准。

### 需要主 agent 知道的一件事（本轮亲历）

**本窗口存在并发改写者。** 我在 07:35–07:40 之间对 `app/conversation_agent.py` 做的改动
**被整份还原过一次**（同一时刻该文件里出现了我没写过的 `llm.log_stream_usage` 版本），
表现为「Edit 报成功、随后磁盘内容变回旧版」。收尾轮的修复最终落盘并稳定（连续 14 次每秒轮询
sha1 不变 + 9 发变异全部还原到 `c65937c0a841`）。若前一个 agent 仍存活，请先停它，
否则 T8 会踩同一个坑；评审包请以工作树 sha1 复核：
`conversation_agent.py=c65937c0a841`、`conftest.py=4b1defdd5a21`、
`test_model_router_v23_contract.py=df1717c548fc`、`test_p17_streaming_contract.py=808adcae4bea`、
`app/llm/fallback.py=008d8213bc05`（未动）、`app/rag.py=a5a638716947`（未动）。

### 剩下的 minor（本轮未清，留给 T8/T9/T11）

1. `SseNativeStreamFieldFaceTests.SOURCE` 是**类属性**在 import 期读源码 ⇒ 变异/评审期间
   文件被换过也不会重读（本轮不影响结论，但静态面宜改方法内读）。
2. `conversation_agent.py` 顶部 docstring 仍写「四条口径」，而温度这条现在也是口径之一
   （常量注释里已经写了，没重复编号）。
3. 全套件仍有 21 条 warning，其中 `InsecureKeyLengthWarning`（JWT 31 字节测试密钥）与
   `[ledger-guard] 测试只读了真实账本`（N1 归类为读、不判红）各属既有测试自设，
   非本轮引入。
4. 变异 T7 的 pytest 汇总行出现 `4 failed, 330 passed`（合计 334 > 332），怀疑是 unittest
   `subTest` 失败在 `-q` 下的重复计数；只影响日志观感，其他 8 发合计都是 332。

---

# 修复轮 1 —— Task 7 独立评审后的首轮修复

> 评审结论 = **Approved-with-fixes**（Critical 0 / Important 4 / Minor 9，见
> `review-task-7-findings.md`）。本轮落地 **I-1 / I-2 / I-4 + Minor 1/2/5**；I-3 已由主 agent
> 回写 DESIGN §9.1 与 §10 #18（本文只补代码侧的可追性）；Minor 3/4/6 与 §7 给 T8-T11 的条目
> **移交**（清单见末段）。
> 开工基线（评审亲跑 + 本轮复算一致）：两考卷 **332 passed / 0 failed / 353 subtests**、
> 全套件 **835 / 880**。本轮终态（亲跑）：两考卷 **334 passed / 0 failed / 353 subtests /
> 45.01s**，全套件 **837 passed / 0 failed / 880 subtests / 22 warnings / 111.96s**。
> 全部外呼仍走 `httpx.MockTransport`（11434 一次都没打）；零 git 写；零新增依赖。

## 1. 逐条 FIX：改了什么 → 哪枚钉 → 红→绿证据

### FIX-1 = 评审 I-1（流式腿的「显式传温度」其实没钉，变异 `M3b` 存活）

* **改了什么（测试侧）**：`SseStreamContractTests::test_the_legacy_ndjson_streaming_payload_is_reproduced_on_the_wire`
  套上与**非流式腿**（`SseBufferedAndLegacyTests`，原 5839-5857 行）**完全同形**的调用面 spy：
  `real_stream = llm.stream` → `def spy(*a, **kw): seen.append(dict(kw)); return real_stream(*a, **kw)`
  → `mock.patch.object(llm, "stream", spy)`，然后加三枚断言：`assertEqual(1, len(seen))`（不经过
  包级入口就是迁移没落地）、`assertIn("temperature", seen[0])`、
  `assertEqual(CONVERSATION_LEGACY_TEMPERATURE, seen[0]["temperature"])`。
  **报文值那三枚既有等式（产品常量 / 测试侧独立写死的 0.2 / `!= RAG_LEGACY_TEMPERATURE`）一字节未动。**
* **改了什么（注释）**：`conversation_agent.py` 温度常量块里那句「两条腿都逐字钉在…两枚温度例」
  是补钉之前的过度声称 ⇒ 改成「两腿各钉**两个面**」并写清 ① 报文面 ② 调用面（含「形参默认与
  字段默认都是 0.2 ⇒ 漏参在报文面不可见」的因果），并如实标注「补钉之前流式腿漏参照样全绿 =
  变异 M3b 存活」。
* **红→绿证据**：`R1-M3b_drop_temperature_stream_leg`（删掉 `llm.stream(...)` 的 `temperature=`）
  评审记录 = **GREEN / 16 passed 存活** ⇒ 本轮 **RED / 1 failed, 15 passed**，
  杀手 = `test_the_legacy_ndjson_streaming_payload_is_reproduced_on_the_wire`（正是要补钉的那枚例）。
  加发同型变异 `R1-N2`（把流式腿显式传成**别的链的常量** 0.1）⇒ **RED / 2 failed**
  （同一枚 + `test_both_legs_send_the_same_legacy_payload_except_the_stream_flag`）。

### FIX-2 = 评审 I-2（ttft「两个不同零点」只有注释、没有钉，变异 `M5a` 存活）

* **改了什么（走评审的**首选行为钉**，没退到静态钉）**：
  ① `_StubToolRegistry` 多一个 `sleep_ms`（默认 0，不影响任何既有例），在
  `_local_fast_path` 圈着 `tool_registry.execute` 的那段里**真实**推进
  `SSE_RETRIEVAL_SLEEP_MS = 40.0` ms；
  ② `test_ttft_is_recorded_at_the_first_content_chunk` 的交付回调每枚 chunk 后睡
  `SSE_GENERATION_SLEEP_MS = 150.0` ms —— 因为 `llm_ms` 的零点是 `llm_started`、不含量检索段，
  不抬高 LLM 段就会让**既有**那枚 `ttft <= llm_ms` 假红（第一版注入 120ms 就是这么撞上的，
  已按「不放宽任何既有断言」的口径改成把两段拉开距离而不是削断言）；
  ③ 三枚新事实：注入的检索段真的被量到（`retrieval_ms >= 40 - 2`，防上面那枚退化成恒真）、
  两枚轴**不是同一个数**（`timings.ttft_ms > 账本 ttft_ms`，反「合并零点」）、
  轴差 `>= retrieval_ms - TTFT_AXIS_EPSILON_MS`（=`timings` 那枚**含**检索、账本那枚**不含**）。
  方向是下界（`差值` 按构造只可能更大）⇒ 没有抖动余量被浪费在「差不多」上。
* **为什么没用评审给的退路（静态 `assertIn`）**：行为钉严格强过它——既杀「换零点」，也杀
  「把两枚轴做成同一个数」这种注释冒充不了的形状，且不冻结源码拼写。
* **红→绿证据**：`R1-M5a_ttft_zero_point_swapped`（`started` → `llm_started`）评审记录 =
  **GREEN / 10 passed 存活** ⇒ 本轮 **RED / 1 failed, 9 passed**，
  杀手 = `test_ttft_is_recorded_at_the_first_content_chunk`。记录点那枚（`M5b`）仍由同一枚例钉住。

### FIX-3 = 评审 I-4（D5 的 payload 增量只落在一支 SSE 出口）——走评审的**方案①**

* **改动面授权**：原任务书没把 `backend/app/agent_routes.py` 列进改动面，本轮**经主 agent
  明确授权**修改（理由与出处 = `review-task-7-findings.md` §3 I-4 + §7 第 7 条「判一次并留字」；
  裁定取方案①，不走「判定该端点不在 D5 承诺范围」的方案②）。
* **改了什么（产品代码，3 行支干 + 注释）**：`agent_routes.py` 的 `worker()` 在 generic
  `except Exception` **之前**加 `except StreamInterrupted as exc:`，与
  `conversation_stream_routes.py:111-143` **同形**：`error`（`detail` / `status=503` /
  `stream_committed=true` / `error_type=exc.error_type`）+ `done`（`status="failed"` + 同两枚增量）。
  **不新增事件类型、不改前端契约**——`frontend/src/lib/api.ts::queryStream` 只读事件名与
  `error.detail`，`done` 的 payload 它不消费；`done` 刻意不带 `message_id` / `message`
  （本端点不落会话库）。另加一行 `from app.llm.fallback import StreamInterrupted`。
* **测试**：`_SseMigrationFixture::drive_agent_route`（照 `drive_route` 的手法：不起 HTTP、
  不过鉴权，直接取端点返回的 `StreamingResponse.body_iterator`）+ 新例
  `SseRoutePayloadTests::test_the_second_sse_egress_lands_the_same_d5_face_and_keeps_its_success_order`，
  与 `test_the_success_event_order_is_unchanged` 同形并加两枚：
  ① 成功序 9 帧（`start/status×3/token×2/trace/sources/done`）逐位不变、**一帧都不带新字段**；
  ② 中断时事件名仍只有 `error` + `done`，且 **`error` 的键集合与另一支出口逐字相等**（这才是
  I-4 的收口证据）；③ **真链可达性**：`terminate=False` 让上游真断流，不手工造
  `StreamInterrupted`，那一支不是死代码（同时钉账本 `success=0`）。
* **红→绿证据（本轮自己的变异）**：`R1-N1`（分支改成 `except ArithmeticError` ⇒ 中断掉回
  generic 支，= I-4 的原病灶）**RED / 1 failed**；`R1-N3`（分支在场但 `error` 上丢掉两枚 payload
  增量）**RED / 1 failed**。杀手都是上面那枚新例。事件词汇表钉法注意了两支出口的差别：本端点
  首帧 `start` 是迁移前就有的现行词汇 ⇒ `KNOWN_SSE_EVENTS | {"start"}`，写死成主对话那一支的
  集合会把既有行为读成「词汇表扩了」。

### FIX-4 = 评审 Minor 1 / 2 / 5（便宜，同批做）

1. **护栏第三道闸（Minor-1）**：`tests/conftest.py::LedgerGuard.install()` 从两道闸变三道
   （`database_path` / `_execute` / **`_connect`**）。`guarded_connect` 在 `ensure_schema` 为真
   （= `_connect` 的**默认值**，它会 `executescript(_SCHEMA)`）时进 `_write_scope()` ⇒ 直连
   `_connect()` 也判 **write**（旧口径记 read 不判红）；`ensure_schema=False`（`_query` 走的那条）
   照旧 read ⇒ 「归类闸恒 write」这种糊法同样会红。今天 `usage.py` 里只有 `_execute`（默认建表）
   与 `_query`（显式 `False`）两个调用点 ⇒ 对**现有归类是空操作**，挡的是以后绕过 `_execute` 的手。
   钉：`LedgerGuardClassificationTests::test_a_direct_schema_connect_is_classified_write_too`
   （两向）。变异：`R1-N4`（恒 write）**RED / 2 failed**（本例 + `test_a_pure_read_…`）、
   `R1-N5`（撤掉第三道闸）**RED / 1 failed**。模块 docstring 的「已知边界」段同步回写。
2. **`.pyc` 残骸（Minor-2）**：删 `backend/app/__pycache__/native_stream.cpython-313.pyc`。
   删后 `find backend -name "*native_stream*"` 归零，且**全套件跑完仍然归零**（模块不存在 ⇒
   不会再生成字节码）⇒ D6 的 grep 审计不再白闪。
3. **import 期读源码（Minor-5）**：`SseNativeStreamFieldFaceTests.SOURCE`（类属性）改成
   `source()` 方法**内**读，三个用它的例各自现读 ⇒ 变异/评审期间文件被换过一定重读。

## 2. 本任务窗口（含修复轮 1）的改动面重列

评审 §8.1 的表是「Task 7 主体」的终态；**本轮在上表之外多了两件事**：`app/agent_routes.py`
（FIX-3，主 agent 授权的扩面）与一枚 `.pyc` 删除（FIX-4）。

| 文件 | 本轮起点（评审终态） | 现在 | 行尾 / 字节安全 |
| --- | --- | --- | --- |
| `backend/app/conversation_agent.py` | `c65937c0a841`（595 行 / 595 CRLF / 0 裸 LF） | **`0ffcc353eb59`**（601 行 / 601 CRLF / **0 裸 LF**） | CRLF 原生：只改温度常量块的**注释**（4 行 → 10 行），代码 0 改动。经 `t7fix_r1_app_bytes.py` 字节读写落盘，全程未出现文本模式换行 |
| `backend/app/agent_routes.py` | `c6fa6b806ec3`（164 个换行 / 96 CRLF + 68 裸 LF = **混合文件**） | **`1080fbd4a0c4`**（186 个换行 / **117 CRLF + 69 裸 LF**） | 混合行尾：新 `except` 支的 21 行按紧随其后的锚点用 **CRLF**，新增 import 用所在 import 块的 **LF** ⇒ 两种计数各 +21 / +1，既有字节一字节未翻。同一枚字节脚本落盘 |
| `backend/tests/conftest.py` | `4b1defdd5a21`（372 行） | **`73d1060de465`**（404 行，**0 CRLF** = 纯 LF 保持） | FIX-4-1：第三道闸 + docstring 回写（+32 行） |
| `backend/tests/test_model_router_v23_contract.py` | `df1717c548fc`（6119 行） | **`5dac328f8736`**（6308 行，**0 CRLF** 保持） | FIX-1/2/3 的钉 + FIX-4-3，净 +189 行、**+2 枚测试例**（`SseRoutePayloadTests` 4→5、`LedgerGuardClassificationTests` 3→4）；既有断言 0 放宽、0 删除。另给 `test_the_stream_leg_has_no_legacy_form_left_to_preserve` 的 docstring 补一句「口径出处 = DESIGN §9.1」（评审 I-3 的验收方式之一） |
| `backend/app/__pycache__/native_stream.cpython-313.pyc` | 存在（退役模块的字节码） | **已删除** | FIX-4-2 |

**未动（复核过，非记忆）**：`app/rag.py=a5a638716947`、`app/llm/fallback.py=008d8213bc05`、
`app/security.py=d36b387aac6e`、`app/conversation_stream_routes.py=c5cb5f9a6dde`、
`tests/test_p17_streaming_contract.py=808adcae4bea`、`app/agent.py=419fa63f4c0d`、
`app/llm/{router,classifier,registry,usage}.py` —— 与评审 §8.1 的表逐枚一致。

## 3. 本轮变异台（7 发全 RED，存活 0；`t7fix_r1_mutations.py` / 日志 `t7fix_r1_mutation_lab.log`）

规矩照评审的 `rev7_mutations.py`：**字节**读写、锚点命中数必须恰好 1、发内还原、还原后 sha1
核对；混合行尾文件的锚点走 `mode="exact"`（串里带显式 `\r\n` / `\n`），不做整文件换行转换。

| # | 变异 | 评审时 | 本轮 | 杀手 |
| --- | --- | --- | --- | --- |
| R1-M3b | 流式腿删 `temperature=`（= 评审 M3b） | **GREEN 存活**（16 passed） | **RED 1 failed / 15 passed** | `SseStreamContractTests::test_the_legacy_ndjson_streaming_payload_is_reproduced_on_the_wire` |
| R1-M5a | ttft 零点 `started`→`llm_started`（= 评审 M5a） | **GREEN 存活**（10 passed） | **RED 1 failed / 9 passed** | `SseStreamContractTests::test_ttft_is_recorded_at_the_first_content_chunk` |
| R1-N1 | `agent_routes` 的 D5 支认错异常类型（→ 掉回 generic） | — | **RED 1 failed / 4 passed** | `SseRoutePayloadTests::test_the_second_sse_egress_lands_the_same_d5_face_and_keeps_its_success_order` |
| R1-N2 | 流式腿显式传**错**常量（`llm.RAG_LEGACY_TEMPERATURE`） | — | **RED 2 failed / 14 passed** | 流式腿温度例 + `test_both_legs_send_the_same_legacy_payload_except_the_stream_flag` |
| R1-N3 | D5 支在场但 `error` 上丢 `stream_committed` / `error_type` | — | **RED 1 failed / 4 passed** | 同 R1-N1 那枚新例（两支出口键集合等式） |
| R1-N4 | 第三道闸恒判 write（读路径被误诊） | — | **RED 2 failed / 2 passed** | `test_a_direct_schema_connect_is_classified_write_too` + `test_a_pure_read_is_classified_read_and_never_pins_red` |
| R1-N5 | 撤掉第三道闸（`_connect` 不判写） | — | **RED 1 failed / 3 passed** | `test_a_direct_schema_connect_is_classified_write_too` |

每发还原后 sha1 与起始一致；脚本收尾三文件复核 `conversation_agent.py 0ffcc353eb59 OK` /
`agent_routes.py 1080fbd4a0c4 OK` / `conftest.py 73d1060de465 OK`。**存活：0 发。**

## 4. 终态数字与真实库实测（只读 URI，`?mode=ro`）

```
两考卷：python -m pytest tests/test_model_router_v23_contract.py tests/test_p17_streaming_contract.py -q
        → 334 passed, 4 warnings, 353 subtests passed in 45.01s       （修复前 332 / 353）
全套件：python -m pytest tests -q   （cwd=backend）
        → 837 passed, 22 warnings, 880 subtests passed in 111.96s     （修复前 835 / 880，0 failed）
        同形态另跑过一次 123.81s（补 §9.1 那句 docstring 之前）⇒ 两次都看到终态、都没被 kill。
E:\xiangmu\rag\backend\data\conversations.db  llm_request_logs=0  conversations=7  messages=10   sha1=39bca2c404e2
E:\xiangmu\rag\data\conversations.db          llm_request_logs=<no such table>  conversations=0  messages=0   sha1=2a9f1ae63995
```
上面两行真库数字是**全套件终态之后**再点的（不是跑测之前），sha1 与评审 §7/§8 记录的前后值
逐字相同。

两份真库的 sha1 与评审 §7/§8 记录的前后值**逐字相同** ⇒ 本轮（含 7 发变异 + 3 次 pytest 全跑）
没有一字节落进真实观测面；护栏的写义务由 `LedgerIsolationGuardTests` 的四枚钉 + 逐例判红
fixture 共同兜住（新增的第三道闸把「直连建表」那条窄缝也归进 write）。

## 5. 移交（本轮刻意不做，按评审裁定归位）

* **Minor-3** → T8：`snap-task8/` 纳管 `app/agent_routes.py`（本轮起它成了 D5 的出口面之一，
  更该进快照）+ `app/conversation_stream_routes.py` + `app/agent.py` + `app/main_agent.py`。
* **Minor-4** → T9：逐例判红 fixture 的**可达性元测试**（「故意写的用例必须自己红」）。
* **Minor-6** → T9/T11 验收文档一句话：`llm_calls=1` vs `attempts` 多跳是两种口径，别按
  `llm_calls` 估外呼次数。
* **评审 §7 其余**：T8 的两腿调用面 spy 义务（本轮已把**流式腿**做成现成模板：
  `test_the_legacy_ndjson_streaming_payload_is_reproduced_on_the_wire`）、T9 的执行器侧 D5
  变异（`M1` 已由评审跑过）、T9 的 `tokens=0` 口径裁决、T10 的真机 SSE 断言、T11 的
  §9.1 / #18 / PLAN 脚注回写与「应急旗标不覆盖流式腿」正文点名。
* **本轮自己新增的观感问题**：护栏的读改道 warning 现在把出处报成
  `conftest.py:243 return self._real_connect(...)`（因为调用栈深了一层），文本内容仍准确；
  归 T9 顺手（`stacklevel` 或改显式 `_warn` 出处）。

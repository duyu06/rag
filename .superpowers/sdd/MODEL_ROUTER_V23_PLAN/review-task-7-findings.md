# Task 7 独立评审结论 — SSE 对话链迁移 + `native_stream` 退役 + 测试护栏（步骤 0）

评审者：Task 7 独立评审。基准 = 工作树代码 + 我亲自跑出的结果（评审包与报告里的自述一律按待验证断言处理）。
定向跑测全部在 `E:\xiangmu\rag\backend` 下 `python -m pytest ... -q`；零真实外呼（11434 一次都没打，全部证据来自
`httpx.MockTransport` 录下的 `self.requests`）；零 git 写；`backend/` 一个字节都没留下改动（末次 sha1 核对见 §8）。

---

## 1. Verdict

**Approved-with-fixes** —— 迁移本体（两条腿进 `llm.complete/stream`、模块退役、D5 commit 语义、逐 chunk 脱敏、
trace 九键、护栏 N1/N3、四枚对外键）经我独立复跑与 11 发变异全部成立、零 Critical；但**两枚实现者自己写进注释/报告的
"钉"其实钉不住**（流式腿的显式 `temperature=` 调用面、ttft 的「不同轴」零点），加上 #18 流式腿的旗标承诺必须在
DESIGN §9/§10 正式回写，故带修复批准：I-1/I-2 必须与 T8 同批（或先于 T8）落地，I-3/I-4 必须在 T11 验收文档收口。

## 2. Critical

**无。** 为什么没有东西阻断：
① 终态完整性我逐件重算过，工作树与 `snap-task7/` 21 个文件**全部逐字节相同**（§8 表），没有并发写回滚的痕迹；
② 两张考卷我亲跑 = **332 passed / 0 failed / 353 subtests**（与报告一致）；
③ 步骤 0 的护栏我用**自己的**驱动脚本复验（纯读判 read 不判红、写作用域判 write、两份真库 sha1 前后不变、
`llm_request_logs=0` 行），并用双向变异证明那两枚钉不是恒真；
④ 真实库未被本轮任何操作触碰（sha1 `39bca2c404e2` / `2a9f1ae63995` 前后一致）。

## 3. Important

### I-1 流式腿的「显式传温度」其实没有钉：删掉参数仍然全绿（变异 M3b 存活）
- **位置**：实现 `backend/app/conversation_agent.py:391-401`（`llm.stream(..., temperature=CONVERSATION_LEGACY_TEMPERATURE, ...)`）；
  注释的过度声称在 `conversation_agent.py:72-75`（"两条腿都**显式**传它 … 逐字钉在 … `SseStreamContractTests`（流式腿）
  两枚温度例里"）；测试面 `backend/tests/test_model_router_v23_contract.py:5453-5478`。
- **症状（我跑出来的）**：
  `M3b_drop_temperature_stream_leg`（把 `llm.stream` 调用里的 `temperature=CONVERSATION_LEGACY_TEMPERATURE,` 删掉）
  ⇒ **16 passed / 0 failed = 变异存活**。对照 `M3a_drop_temperature_buffered`（同一动作打在 `llm.complete` 上）
  ⇒ **1 failed**（`test_the_buffered_leg_carries_the_conversation_temperature_and_the_legacy_option_keys` 的 kwargs spy 杀掉）。
- **根因**：`app/llm/__init__.py:254-263` 的 `stream()` 形参默认 `temperature: float = 0.2`（与 `LLMRequest.temperature`
  字段默认同值），而本链现值恰好也是 0.2 ⇒ **漏参在报文面不可见**。收尾轮为 `complete` 加了调用面 spy（报告 T1 的
  诚实备注），但**同一手法没有复制到 `stream`**，于是流式腿的 0.2 现在是"碰巧对"而不是"钉住了"。这直接违反本次验收
  口径第 5 条（"不许依赖 `LLMRequest` 字段默认巧合（去掉参数必须有例红）"，两腿同等要求）。
- **要求的修法（行级）**：
  1. `tests/test_model_router_v23_contract.py::SseStreamContractTests::test_the_legacy_ndjson_streaming_payload_is_reproduced_on_the_wire`
     里套一层与 `5839-5857` 完全同形的 spy：`real_stream = llm.stream` → `def spy(*a, **kw): seen.append(dict(kw)); return real_stream(*a, **kw)`
     → `mock.patch.object(llm, "stream", spy)`，然后加两枚断言：`assertIn("temperature", seen[0])`、
     `assertEqual(conversation_agent_module.CONVERSATION_LEGACY_TEMPERATURE, seen[0]["temperature"])`；
  2. 顺手把 `conversation_agent.py:72-75` 的措辞改成与事实相符（否则修完仍是一句假话）。
- **验收方式**：`python .superpowers/sdd/MODEL_ROUTER_V23_PLAN/rev7_mutations.py M3b_drop_temperature_stream_leg`
  必须从 **GREEN 变 RED**（我的 harness 自带字节还原 + sha1 核对，可直接复用）。缺的钉就是这一枚调用面等式；
  报文值的三枚等式（产品常量 / 测试侧独立写死 / `!= RAG_LEGACY_TEMPERATURE`）已经在位、不要动。

### I-2 ttft 的「两个不同零点」是**没被钉**的口径：换零点仍然全绿（变异 M5a 存活）
- **位置**：`conversation_agent.py:407-413`（记录点与零点）、注释口径 `conversation_agent.py:18-20`；
  测试 `test_model_router_v23_contract.py:5480-5493`。
- **症状**：`M5a_ttft_zero_point_swapped`（把 `(perf_counter() - started)` 换成 `(perf_counter() - llm_started)`，
  即让 `timings["ttft_ms"]` 不再含检索段）⇒ **10 passed = 存活**。
  而记录点本身是钉住的：`M5b_ttft_record_point_removed`（删掉赋值）⇒ 1 failed（`test_ttft_is_recorded_at_the_first_content_chunk`）。
- **判定（回答必查清单第 4 条）**：说法**成立且不互相冒充**——`timings["ttft_ms"]` 零点 = 整次请求 `started`
  （含检索，与迁移前逐字同形），账本 `ttft_ms` 由 `fallback.py:871` 的 `_commit` 以 `_session_started`（`fallback.py:789`
  设在 `_pump` 起点）为零点 ⇒ 两者相差一个 `retrieval_ms`，代码里没有任何一处用前者冒充后者（`log_stream_usage`
  只吃 `summary.ttft_ms`）。**但"不同轴"这件事只有注释、没有钉**：现有断言是 `0 <= timings.ttft <= llm_ms` +
  账本那枚非空，换零点后两条仍然成立。
- **要求的修法（行级）**：在 `test_ttft_is_recorded_at_the_first_content_chunk` 里把两枚轴做成**可比较的事实**：
  首选行为钉——用本文件已有的 `FakeClock`（`test_model_router_v23_contract.py:2770`）或给
  `_StubToolRegistry.execute` 注入固定推进量，断言 `float(result["timings"]["ttft_ms"]) - float(rows[0]["ttft_ms"]) >= 注入的检索毫秒数 - eps`
  （即 `timings` 那枚**包含**检索、账本那枚**不包含**）；嫌重就退一步加静态钉
  `assertIn("ttft_ms = (time.perf_counter() - started) * 1000", agent_source)`，并在注释里写明"改零点=改对外字段语义"。
- **验收方式**：`rev7_mutations.py M5a_ttft_zero_point_swapped` 必须变红。

### I-3 #18 流式腿：旗标承诺被悄悄缩小，必须正式回写（裁定见 §6）
- **位置**：DESIGN `docs/MODEL_ROUTER_V23_DESIGN.md:66`（"false=三链路走原 legacy 分支"）与 `:108`（#18 "三链原行为"）、
  `docs/MODEL_ROUTER_V23_PLAN.md` Global Constraints 同名那句 + Task 7 那句"legacy flag 分支保留原调用"；
  实现事实 `conversation_agent.py:361-401`（只有 `token_sink is None` 一支有 else 分支）+ `:26-29` 的自述。
- **症状/根因**：`LLM_ROUTER_ENABLED=false` 今天对流式腿**只剩"报文与退役模块逐字等价"这一层意思**，
  旗标关掉后该腿照旧走 classifier→plan→fallback→熔断→记账（我已实测：`test_the_stream_leg_has_no_legacy_form_left_to_preserve`
  在 `llm_router_enabled=False` 下仍然 `native_stream=True` 且通过路由）。而 `agent_routes.py` 那支 SSE 与前端主用的
  对话 SSE 都吃这条腿 ⇒ 运维按 §7 那句话理解"应急回退"会落空。
- **要求的修法**：按 §6 我给的两句话原文回写 DESIGN §9（新增 §9.1）与 §10 #18 行的"预期"列，并在 PLAN 的
  Global Constraints 那句 `LLM_ROUTER_ENABLED=false` 后面加一条脚注指回 §9.1；V2.3 验收文档必须点名
  "应急旗标不覆盖对话链的流式腿"。
- **验收方式**：T11 终审前 §9.1 与 #18 行已改；`SseBufferedAndLegacyTests::test_the_stream_leg_has_no_legacy_form_left_to_preserve`
  的 docstring 里加一句"口径出处 = DESIGN §9.1"，让代码与文档双向可追。

### I-4 D5 的 payload 增量只落在一支 SSE 出口，另一支把 `StreamInterrupted` 吞进 generic 分支
- **位置**：`backend/app/agent_routes.py:115-124`（generic `except Exception`）vs
  `backend/app/conversation_stream_routes.py:111-143`（D5 专支）。
- **症状**：`/api/agent/query/stream` 也传了 `token_sink`（`agent_routes.py:90-99`）⇒ 同一条流式腿 ⇒ 同一种
  post-commit 中断，在那里落成 **error-only、无 `done`、无 `stream_committed`/`error_type`** 的旧形状。
  前端目前只有 `api.ts:419 queryStream` 的定义、无组件调用，所以不是现场故障，但它是 §7 那句"输出现行 SSE 事件词汇
  `error` + `done`（payload 增量…）"的第二条出口面。
- **要求的修法**：二选一并写进 T9/T11 结论：①给 `agent_routes.py` 加 3 行 `except StreamInterrupted` 支（与
  `conversation_stream_routes.py:131-143` 同形，事件词汇不变）；②判定"该端点不在 D5 承诺范围"并在 §9.1/验收文档点名，
  同时把 `queryStream` 的存续（要不要随 V2.3 删）交给 T11。
- **验收方式**：走①则补一枚路由级例（照 `SseRoutePayloadTests` 的 `drive_route` 手法，`test_the_success_event_order_is_unchanged`
  同形）；走②则验收文档必须出现"两条 SSE 出口 / 一条收口"的明确句子，禁止留白。

## 4. Minor（一行一条）

1. 写判定收窄的一处窄口径回退：`conftest.py:217` 只把 `_execute` 栈内的解析记成 write，若有代码**直接**调
   `usage._connect()`（`ensure_schema=True` 会 `executescript` 建表，`usage.py:1019`）会被记成 read 不判红——旧护栏
   会判红。今天无此调用点；建议 `guarded_database_path` 里对 `ensure_schema` 场景另记一类，或加一枚"直连 `_connect`
   也判 write"的钉。
2. `backend/app/__pycache__/native_stream.cpython-313.pyc` 仍在（退役模块的字节码残骸）：`importlib` 钉已证明它不可导入，
   但会让 D6 的 grep 审计白闪一次；T8 前顺手删。
3. `snap-task6/7` 都没纳管 `app/conversation_stream_routes.py` 与 `app/agent_routes.py` ⇒ T7 在这两个文件上的 delta
   只能靠 mtime + 推理隔离（我用 `git diff HEAD` 反证了 T7 归因只有 `except StreamInterrupted` 那一支）。T8 快照请纳入。
4. `conftest.py:330-345` 的逐例判红 fixture 本身没有可达性钉（只有 `violations()` 的归类钉）；建议 T9 补一发
   "故意写的用例必须自己红"的元测试。
5. `SseNativeStreamFieldFaceTests.SOURCE`（`test_model_router_v23_contract.py:5978`）仍是类属性 import 期读源码
   ——报告已自报，本轮未清。
6. `llm_calls` 在 pre-commit 静默换候选后仍记 1（`test_matrix_10_…` 第 5609 行钉死）：这是"对外键语义不变"的正确选择，
   但与 `attempts`/账本 `latency_ms=各跳之和` 是两种口径，T9 收口时在验收文档写一句，别让人按 `llm_calls` 估算外呼次数。
7. commit 后中断那一行的 `input/output/total_tokens` 全 0（`test_a_provider_error_frame_after_content_keeps_its_real_kind`
   如实钉住）：形状诚实，但 §8 的 token 聚合在"半截交付"上系统性偏低，归 T9 判要不要动 `usage.py` 的冻结口径。
8. `conversation_agent.py:11` 的"四条口径"编号没把温度算进去（报告自报，本轮未清）。
9. 从任意第三方 cwd 跑套件时 `PROTECTED_DATA_DIRS` 是在 conftest import 期取 `Path.cwd()` 算的 ⇒ 测试内部再
   `os.chdir()` 的话 N3 覆盖不到新 cwd；今天没有这种用例，记录为边界。

## 5. 必查清单 1–11 逐项结论

| # | 项 | 结论 | 证据（我亲自跑的 / 文件:行号） |
| --- | --- | --- | --- |
| 1 | 终态完整性自证 | **PASS** | 工作树 21 件与 `snap-task7/` 逐字节 SAME（含 `conversation_agent.py=c65937c0a841`、`fallback.py=008d8213bc05`、`conftest.py=4b1defdd5a21`、`rag.py=a5a638716947`）；`fallback.py`/`conftest.py` 0×CRLF；`rag.py` 与 `snap-task6` 零差异；`app/native_stream.py` 不存在且全仓（app+tests+frontend）零 import 残留（只剩 `__pycache__` 残骸，Minor-2）。**未见并发回滚痕迹**。 |
| 2 | D5 流式 commit 语义 | **PASS**（含我自己的变异） | pre-commit：`test_matrix_10_…`（换候选、`tokens==SSE_PARTS`、`fallback_index=1`、`llm_calls=1`）；post-commit 不换：`fallback.py:826-828` 唯一出口 + `test_matrix_11_…`；**M1（把 `raise self._interrupted(error) from exc` 换成继续走候选）⇒ 3 failed**（`test_matrix_11_post_commit_failure_never_switches_model`、`test_a_provider_error_frame_after_content_keeps_its_real_kind`、`test_a_real_truncated_upstream_lands_error_plus_done_on_the_wire`）；error/done + `stream_committed` 在 `conversation_stream_routes.py:111-143`，`grep stream_committed backend/app/llm/*` 命中 0 ⇒ 不在 llm 包里。缺口见 I-4（第二支 SSE 出口）。 |
| 3 | `redact_text` 逐 chunk 且在 `token_sink` 前 | **PASS** | 实现 `conversation_agent.py:404`；钉：`test_redaction_happens_per_chunk_before_the_client_sees_it`（行为）+ `test_p17_streaming_contract.py:86-98`（顺序）；**M2（摘掉逐 chunk 脱敏）⇒ 2 failed**，两枚钉各自杀。 |
| 4 | ttft 记录点 / 两个零点 | **Important** | 记录点=首内容 chunk（`conversation_agent.py:407-413`）钉住：**M5b ⇒ 1 failed**。零点口径**成立且不冒充**（账本用 `summary.ttft_ms`、`timings` 用 `started`），但**没钉**：**M5a（换零点）⇒ 存活** ⇒ I-2。 |
| 5 | 温度（我的验收口径） | **Important** | 两条腿报文值都是 0.2，出处对得上（`baseline-app/native_stream.py:27-28`、`baseline-app/conversation_agent.py:297-299` + `app/agent.py:65`）；`think/num_predict/keep_alive` 与 legacy 等价且被 `options` 键集合等式钉（`5467`、`5863`、`5907-5909`）；buffered 腿**调用面**钉住（**M3a ⇒ 1 failed**）；**流式腿调用面没钉（M3b ⇒ 存活）= I-1**。全仓无按 0.1 钉的本链残留断言（0.1 只出现在 rag 组与 normalize 透传组，`4309-4330`/`1128-1141`，口径正确）。 |
| 6 | #18 流式腿 legacy 覆盖范围 | **裁定见 §6**（代码侧接受，文档侧必须回写 = I-3） | 与 PLAN Task 7 不冲突、与 §7:66 / §10:108 的**字面**"三链原行为"冲突；旗标今天对流式腿只剩报文等价承诺。 |
| 7 | 护栏（步骤 0：N1/N3） | **PASS** | N1 收口在 `_execute`（`usage.py` 的 INSERT 只从 `_execute` 出去，已核：全文件仅 `240/263` 两处写、都走 `_execute`）；我的独立驱动：`_query` ⇒ `kind=read`、`violations=()`，`_execute(None, no-op)` ⇒ `kind=write`、`violations=1`，两份真库 sha1 前后一致；N3 三候选在 cwd=`backend` 与 cwd=仓库根两种情况下都把 `data/conversations.db` 判进保护集（我的 probe 输出），且**从仓库根跑** `-k Ledger` ⇒ 10 passed。防回潮可达：**M6a（归类恒 read）⇒ `test_a_real_write_…` 红；M6b（恒 write）⇒ `test_a_pure_read_…` 红**（双向都不是恒真）。`conftest.py` 未削弱任何既有测试（唯一语义变化=读从判红降为 warning，写义务不变；diff 见 `rev7_conftest_diff.txt`）；窄口径回退记 Minor-1。 |
| 8 | 对外形状四键 | **PASS** | `native_stream`：字段留、模块走（`SseNativeStreamFieldFaceTests` 4 例 + 出现位置等式 `assertEqual(3, …)`）；`llm_ms`/`llm_calls`/`model_used`：`test_llm_ms_llm_calls_and_model_used_keep_their_meaning` + D1 别名例，且**M7（`model_used` 退回硬编码 `settings.ollama_model`）⇒ 1 failed**；`timings` 键集合按**等式**钉（`5542-5549`）。`security.py` 与 HEAD 零差异（`git diff --name-only HEAD -- backend/app/security.py` 空）⇒ 白名单语义未被碰。`test_p17_streaming_contract.py` **确实被改过**（60→132 行，报告如实），但强度**未降**：逐条换落点、grep 升级为行为断言，其中「HTTP 层真的用流式」这一枚的成功落点在 `test_model_router_v23_contract.py:1520-1559`（3 字节分片 + "错误只在第一次 `next()` 才抛"），比原 grep 更强。 |
| 9 | trace / #17 | **PASS** | `attach_model_route` 在 `save_trace` 之前（`conversation_agent.py:507-509`）；三种形状都挂（`FallbackResult`/`StreamSummary`/中断后的 `finish()`：`test_a_real_streamed_answer…`、`test_the_buffered_leg…`、`test_the_interrupted_stream_also_lands_a_model_route`）；**M4（注释掉那一行）⇒ 3 failed**、**M8（`finally:`→`else:`）⇒ 5 failed**（含中断路）；九键键集 + 三张子视图键集封口 + canary 六枚 0 命中 + **真 JSONL 往返**（`get_trace` 读回等值）都在 `5700-5783`；`stream_committed` 未进 `model_route`（`5724-5726` 的九键等式即反证）；`llm` 包不碰 trace 形状另有静态钉（`5799-5810`）。 |
| 10 | 报告可信度 | **基本可信，两处过度声称** | 我独立复现 9 发（映射：M1↔T2、M2↔T3、M3a↔T1、M4↔T4、M5b↔T9、M7↔无、M8↔T8、M6a/M6b↔护栏双向），**结论一致**，但报告未披露的两处缺口 = I-1（流式腿 spy）与 I-2（ttft 零点），其中 I-1 恰是报告自己 T1 备注的推理的直接推论——它只对 `complete` 做了。**测试新增清单完整**：我把 §5 的 42 个例名与工作树逐一对照，零缺零多（`rev7_testnames.txt`）。非内容写入两笔（`fallback.py` CRLF、`conversation_agent.py` 注释掉 attach）与并发窗口都如实写了，且我复核 `fallback.py` 确与 `snap-task6` 逐字相同、`conftest.py` 确为纯 LF。"遗留 minor" 4 条与我看到的 minor 集合相符（不含 I 级）。 |
| 11 | 范围纪律 | **PASS** | 窗口 mtime 清单（`-newermt 09-24 05:10`）= `conversation_agent.py`、`conversation_stream_routes.py`、`conftest.py`、`test_p17…`、`test_model_router_v23_contract.py`（+ `fallback.py` 被写过但字节复原）。`app/rag.py`、`app/agent.py`、`app/llm/*`、`app/security.py`、`app/agent_trace.py`、`app/main.py`、`test_llm_usage_contract.py` **零改动**（snap6↔工作树全 SAME）。`conversation_stream_routes.py` 属"为 D5 必须碰"的扩面、且只多了 `except StreamInterrupted` 一支（`git diff HEAD` 反证），接受但记 Minor-3（快照没纳管它）。 |

## 6. 对第 6 条（#18 流式腿的 legacy 形态）的正式裁定

**① 冲突判定。**
与 `PLAN` Task 7 那句"**legacy flag 分支保留原调用**"**不冲突**：原调用 `agent_module._ollama_chat(messages, [])` 在
`conversation_agent.py:383` 逐字节留在原位（并被 `test_matrix_18_the_legacy_branch_still_calls_agent_ollama_chat` +
`guard_router_calls_off` 双向钉住）。同一任务书的另一句"**删除 `app/native_stream.py`**"在逻辑上取消了流式腿的 legacy
分支——不可能既删模块又保留调用它的分支；把 `/api/chat` + `httpx.stream` 内联回业务文件则直接违反 D6 与矩阵 #19
（`business_file_has_no_second_llm_egress` 会红）。⇒ **实现者的解释成立**。
但与 DESIGN §7:66「false=三链路走原 legacy 分支」与 §10:108「三链原行为」的**字面**冲突：那两句话以"链路"为单位
承诺回退，而对话链有两条腿，**默认且唯一被前端交互使用的那条（SSE 流式）今天没有回退**。这不是实现越界，是**规格
的一句话把一个承诺写得比它实际能给的大**——必须在文档侧收口（I-3），否则灰色地带会被 T8/T11 各自按需要解释。

**② 回写文案（可直接抄，ledger 记本次评审为出处）。**

DESIGN 在 §9 之后新增小节（沿用 §8.1 的"回写"体例）：

> ### 9.1 §9 回写（2026-09-24，Task 7 独立评审 I-3 裁定；precedent = §8.1 的 Task 5 修订）
>
> 对话链的两条腿在 `LLM_ROUTER_ENABLED=false` 下**不对称**：非流式腿（`token_sink is None`）保留原调用
> `agent._ollama_chat(messages, [])`；**流式腿没有 legacy 形态可留**——它的原实现 `app/native_stream.py` 已由
> Task 7 退役，把 `/api/chat` + `httpx.stream` 内联回业务文件即违反 D6 与矩阵 #19。因此这一腿的 #18 对照面从
> 「旗标关掉走旧代码」改为「**报文与退役模块逐字等价**」（`stream=True` / `tools=[]` / `think` / `keep_alive` /
> `options{temperature=0.2, num_predict}`），且关掉旗标时该腿**仍走路由**（`timings["native_stream"]` 仍为 `true`）。
> 后果写清：`LLM_ROUTER_ENABLED=false` 只是**非流式路径**的应急回退，**不覆盖对话链流式腿与 agent 链的工具轮**；
> V2.3 验收文档必须点名这一缩小，运维不得把它当作"SSE 侧模型故障的止血开关"。

DESIGN §10 #18 行的"预期"列改为：

> | 18 | legacy 回退 | flag=false | 三链原行为；**对话链仅非流式腿有 legacy 形态，流式腿以「报文与退役模块逐字等价」为准（见 §9.1）** |

PLAN 的 Global Constraints 中「`LLM_ROUTER_ENABLED=false` = 三链 legacy 原行为」句尾追加：
「（**Task 7 评审修订**：对话链流式腿因 `native_stream.py` 退役而无 legacy 形态，口径见 DESIGN §9.1。）」

**③ 旗标今天还剩什么语义（如实清单）。** 仍然回退的：`rag.py` 两条 provider 腿（`rag.py:200-224` 的两支
`httpx.post`）+ `current_model_name()` 展示面（`rag.py:127`）+ 对话链**非流式腿**（即 `conversation_routes.py` 的两支
REST POST）。不再回退的：对话链 **SSE 流式腿**（含 `agent_routes.py:90` 那支传了 `token_sink` 的旧 SSE 端点）；
agent 链（`agent.py`）整体待 T8。⇒ **承诺确实被缩小了，且缩在了最常被使用的那条路上**，所以 §6② 的最后那句
"运维不得把它当止血开关"必须进 V2.3 验收文档，不能只留在代码注释里。

## 7. 移交 T8 / T9 / T10 / T11 的强制口径

**给 T8（Agent 迁移）**
1. `app/agent.py::_ollama_chat` 迁进 `llm.complete/stream` 时，**温度必须显式传**（本链现值 0.2，出处 `app/agent.py:65`，
   不许套 rag 的 0.1），并且**两腿都加调用面 spy**：`assertIn("temperature", seen[0])`。理由：`llm.complete/stream` 的形参
   默认与 `LLMRequest.temperature` 字段默认**都是 0.2**，漏参在报文面不可见（本任务 M3b 存活就是现成反例）。
2. 交付前自跑两条变异（我留在 `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/rev7_mutations.py`，把锚点换成 agent 链的即可）：
   删 `temperature=`、删 `attach_model_route`，两条都必须红。
3. 快照纳管：`snap-task8/` 请包含 `app/agent.py`、`app/agent_routes.py`、`app/main_agent.py`、`app/conversation_stream_routes.py`
   （本任务因为 `conversation_stream_routes.py` 没进快照，只能靠 mtime + `git diff` 反证，见 Minor-3）。
4. `app/llm/*` 仍是**禁改件**（本窗口 `fallback.py` 被文本模式翻成 CRLF 后按字节复原，代价是 943 行假差异）；
   `tests/conftest.py` 与 `tests/test_model_router_v23_contract.py` 是**未跟踪文件** ⇒ `core.autocrlf=true` 对它们无效，
   读写必须字节安全。
5. `D6/单一出口` 判定沿用 `business_file_has_no_second_llm_egress`（`test_model_router_v23_contract.py:5406-5434`），
   黑名单组成照抄（`httpx` import / `from native_stream` / `/api/chat` / `/chat/completions` / `ollama_base_url`），
   **别把 `native_stream` 字段名扫进去**（那是"留字段、退役模块"的区分点）。迁完时 `app/agent.py` 的 `httpx.post` 命中应归零。

**给 T9（矩阵收口）**
6. **执行器侧的 D5 变异**（报告"我没有做的事 #2"点的这一发仍未打）：改动点 = `fallback.py:826-828`，
   我的 `M1_postcommit_switches_candidate` 就是它（已跑，3 发红），请把它正式记进矩阵 #11 的证据表。
7. I-4 的收口：`/api/agent/query/stream` 要不要同一套 payload 增量，判一次并留字。
8. 两个记账口径判一次，别再各自解释：① commit 后中断 `tokens=0`（Minor-7）；② `llm_calls=1` vs `attempts` 多跳
   （Minor-6）；③ 零候选 0 行（SSE/rag 同形，已有钉）。
9. 护栏补两枚：`_connect()` 直连写也判 write（Minor-1）、逐例判红 fixture 的可达性元测试（Minor-4）。
10. 矩阵 #14 的 P95 复测请在**迁移后**的 SSE 链上再取一次样（本任务的 332 例全绿不含延迟口径）。

**给 T10（真实 failover）**
11. 真实双模型跑 P0 时，SSE 腿的 10 枚断言里 `model_used`/账本 `model` 必须是**生效模型名**（D1 别名口径，
    本任务已钉：`test_model_used_follows_the_d1_model_override_alias`），且 `stream_committed` **不得**出现在
    pre-commit 那一次的 `error` payload 上（`test_a_pre_commit_failure_keeps_the_existing_error_shape_untouched` 是
    additive-only 的边界，真机复测不许顺手放宽）。

**给 T11（回归终审）**
12. §6② 的三处回写（DESIGN §9.1 / §10 #18 / PLAN Global Constraints 脚注）+ 「应急旗标不覆盖流式腿」进验收文档正文。
13. 温度裁定回写：DESIGN §9 若仍留有"buffered 腿 0.2→0.1 已声明偏差"字样一律删除（ledger 第 54 行已记，代码侧
    `CONVERSATION_LEGACY_TEMPERATURE=0.2` 已落）。
14. 「全套件只在 `backend/` 下有效」这条环境口径 + p17/`SseNativeStreamFieldFaceTests` 的 import 期读源码（Minor-5）。

## 8. 我实际执行的命令与关键输出

```
# 终态完整性（我自己算，不采信报告）
cd E:/xiangmu/rag && sha1sum backend/{app/conversation_agent.py,app/llm/fallback.py,tests/conftest.py,app/rag.py,...}
python（snap-task6/7 ↔ 工作树 21 件逐字节比对）→ 见下表
python（EOL 组成）→ fallback.py 0×CRLF / conftest.py 0×CRLF（conversation_agent.py 与 rag.py 本就是 CRLF-native，未翻）
find backend/app backend/tests -newermt "2026-09-24 05:10"     # 改动面时间线
grep -rn "native_stream|ollama_chat_stream" backend frontend docs   # 零 import 残留（仅 __pycache__ 残骸）
grep -rn "stream_committed" backend/app                        # 只在 conversation_stream_routes.py
grep -n "INSERT|_execute(|_connect(" backend/app/llm/usage.py  # 写只从 _execute 出去（240/263 两处）
git diff HEAD -- backend/app/conversation_stream_routes.py     # D5 支是唯一 T7 归因改动
git diff --name-only HEAD -- backend/app/security.py           # 空 ⇒ 白名单未被碰
git show HEAD:backend/tests/test_p17_streaming_contract.py     # 60 行基线，逐枚对照新 132 行

# 定向测试
cd backend && python -m pytest tests/test_p17_streaming_contract.py tests/test_model_router_v23_contract.py -q
  → 332 passed, 3 warnings, 353 subtests passed in 44.03s
cd /e/xiangmu/rag && python -m pytest backend/tests/test_model_router_v23_contract.py -q -k "Ledger"
  → 10 passed, 314 deselected, 1 warning in 35.24s        # 从仓库根跑，护栏照样兜住
python（只读 URI 点数）→ backend/data/conversations.db: llm_request_logs=0 conversations=7 messages=10
                        → rag/data/conversations.db: llm_request_logs=<no such table> conversations=0 messages=0

# 我自己的 N1/N3 驱动（零写盘）
python .superpowers/sdd/MODEL_ROUTER_V23_PLAN/rev7_n_probe.py
  cwd=backend  path_is_protected(data/conversations.db)=True ；abs backend db=True ；abs root db=True
  cwd=仓库根   同上
  _query  → records=[('data\conversations.db', <tmp>/probe.db, 'read')]   violations=()
  _execute→ records[-1]=(..., 'write')                                    violations=1
  真库 sha1 前后：39bca2c404e2 / 2a9f1ae63995 —— 未被触碰
```

### 8.1 sha1 对照表（12 位前缀；工作树 = 我实算）

| 文件 | snap-task6 | snap-task7 | 工作树 | 判定 |
| --- | --- | --- | --- | --- |
| `backend/app/conversation_agent.py` | （不在快照） | `c65937c0a841` | `c65937c0a841` | SAME，与报告自述一致 |
| `backend/app/llm/fallback.py` | `008d8213bc05` | `008d8213bc05` | `008d8213bc05` | 本窗口**未动**（含 CRLF 事故已复原），纯 LF |
| `backend/tests/conftest.py` | `83cfa7ae3bcf` | `4b1defdd5a21` | `4b1defdd5a21` | 本窗口改动（N1/N3），纯 LF |
| `backend/app/rag.py` | `a5a638716947` | `a5a638716947` | `a5a638716947` | 与 snap6 零差异 |
| `backend/app/security.py` | `d36b387aac6e` | `d36b387aac6e` | `d36b387aac6e` | 白名单未动（与 git HEAD 亦零差异） |
| `backend/tests/test_model_router_v23_contract.py` | `3f06baaa502e` | `df1717c548fc` | `df1717c548fc` | 本窗口改动（+1100 行） |
| `backend/tests/test_p17_streaming_contract.py` | — | `808adcae4bea` | `808adcae4bea` | **确实被改过**（60→132 行），强度未降 |
| `backend/app/{agent_trace,llm/{__init__,classifier,errors,health,models,normalize,provider,registry,router,usage}}.py`、`app/main.py`、`app/knowledge_os.py`、`tests/test_llm_usage_contract.py` | — | 同工作树 | 同工作树 | 13 件 SAME |
| `backend/app/conversation_stream_routes.py` | 未纳管 | 未纳管 | `c5cb5f9a6dde` | 快照缺口（Minor-3），改动经 `git diff` 反证 |

### 8.2 我的 11 发变异（`rev7_mutations.py`，全部字节读写 + 发内还原 + sha1 核对；日志 `rev7_mutations.log`）

| # | 变异 | 结果 | 谁杀的 |
| --- | --- | --- | --- |
| M1 | post-commit 改成继续换候选（`fallback.py:828` 的 raise → pass） | **RED 3 failed** | 矩阵 #11 + 真路由端到端 + 原始 kind |
| M2 | 摘掉逐 chunk 的 `redact_text` | **RED 2 failed** | `SseStreamContract` + `P17` 顺序钉 |
| M3a | buffered 腿删 `temperature=` | **RED 1 failed** | kwargs spy（`5854-5855`） |
| **M3b** | **流式腿删 `temperature=`** | **GREEN 存活** | **无 ⇒ I-1** |
| M4 | 注释掉 `attach_model_route` | **RED 3 failed** | #17 三例（含中断路） |
| **M5a** | **ttft 零点从 `started` 换成 `llm_started`** | **GREEN 存活** | **无 ⇒ I-2** |
| M5b | 删掉 ttft 记录点 | **RED 1 failed** | `test_ttft_is_recorded_at_the_first_content_chunk` |
| M6a | 护栏归类恒 `read` | **RED 1 failed** | `test_a_real_write_is_classified_write…` |
| M6b | 护栏归类恒 `write` | **RED 1 failed** | `test_a_pure_read_is_classified_read…` |
| M7 | `model_used` 退回硬编码 `settings.ollama_model` | **RED 1 failed** | D1 别名例 |
| M8 | `session.finish()` 从 `finally` 挪到 `else` | **RED 5 failed** | commit 矩阵 + 中断路 trace + 路由 |

9 killed / 2 survived；每发还原后 sha1 与起始一致，脚本收尾三文件复核 `OK`。

### 8.3 我留在计划目录的临时件（前缀 `rev7_`，不进产品树）

`rev7_mutations.py`、`rev7_mutations.log`、`rev7_n_probe.py`、`rev7_p17_head.py`、`rev7_contract_removed.txt`、
`rev7_conftest_diff.txt`、`rev7_testnames.txt`、本文件。

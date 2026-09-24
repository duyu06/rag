# Task 6 独立评审结论 — RAG 生成链迁移 + 执行面 `plan`/`context_dropped`

评审者：Model Router V2.3 Task 6 独立评审（规格与质量守门人）
被评审对象：工作树 `backend/app/rag.py`、`backend/app/llm/fallback.py`、
`backend/tests/test_model_router_v23_contract.py`
评审日期：2026-09-24
证据目录：`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/rev6_*.py`（本次评审的脚本，前缀 `rev6_`）

---

## 1. Verdict

**Approved-with-fixes**。

一句话理由：legacy 两条 httpx 分支经我逐行 byte 级比对与 5 发独立变异证明是**真原样保留**、
温度门闸是**真门闸**（拿真 legacy 报文对照，不是自比自），三条交付的实现没有缺陷；
但**书面派给本任务的矩阵 #17「集成」半段未交付**（I-1），且本任务新增的一条测试
**每次运行都往真实 `data/conversations.db` 的 `llm_request_logs` 写一行假账**（I-2）——
两条都可在本任务的改动面（测试文件）内修掉，不需要动实现。

改动面与报告自述**一致**：3 个文件、测试文件 0 删 810 增、`fallback.py` 纯 LF 943 行、
`app/llm/` 其余 10 个模块对 `snap-task5/` 零差异、`native_stream.py`/`agent.py`/
`conversation_agent.py`/`config.py` 未触碰。定向我亲跑 **408 passed / 0 failed / 381 subtests**
（与报告逐字相同），Task 6 新增 **39 passed / 2 subtests**，全套件 788/878 采信主 agent 的独立复跑。

---

## 2. Critical（P0 阻断）

**无。**

判据（为什么确实可以为空，而不是漏判）：

- 上线阻断面只有三条真风险：①legacy 回退口被污染 → 我证伪（byte 级一致 + M6/M7 变异红）；
  ②D2「零候选/全链失败给用户裸错」→ `NoCapableModelError` 与 `AllCandidatesFailedError`
  都被 `app/rag.py:238` 接住并落现文案，真 HTTP 面 200 有测试（`4456`）；
  ③D3「prompt 入库」→ 禁存项由 `4511-4518` 的全列 canary 扫描钉住，`trace_id is None` 也钉了。
- I-1/I-2 都属于**观测与测试侧**缺口，不改变任何 shipped code 的对外行为，
  且都能在修复轮里由测试文件解决 ⇒ 按本项目分级只能是 Important。

---

## 3. Important

### I-1｜矩阵 #17 的「集成」半段（书面派给 T6）未交付

- **位置**：`backend/tests/test_model_router_v23_contract.py:4186-4210`
  （`RagRouterMigrationTests::test_the_plan_travels_with_the_result_the_rag_chain_gets`）
- **症状**：这条测试只钉到「`result.plan` 是 `RoutePlan`、primary 与响应模型名同源」。
  它**没有**跑 `attach_model_route`、**没有**断言落盘 trace 里 `model_route` 九键齐备、
  **没有**断言 trace 里没有 prompt/reasoning 字节。Task 6 全仓新增测试里 `attach_model_route`
  出现 **0 次**（`grep -n "attach_model_route" backend/tests/`：只有 T5 的
  `AgentTraceModelRouteSeamTests` 与 `app/agent_trace.py` 自身）。
- **义务出处（两份书面，都早于本任务）**：
  1. `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task-6-brief.md`「Task 5 评审移交项」第 3 条：
     「**矩阵 #17 的「集成」半段归本任务**：补一条走**真** `llm.complete()` 的用例，断言落盘
     trace 里 `model_route` 九键齐备（attempts 非空 + 无 prompt/reasoning 字节）。Task 5 的
     `AgentTraceModelRouteSeamTests` 只覆盖纯函数 + JSONL 往返，**不能替你交 #17**。」
  2. `progress.md` 第 40 行（T5 handoff→T6/T7/T8）：「各补一条走真 `llm.complete/stream` 的用例
     钉 model_route 六+三键齐备」——**各**补一条，T7 的那条在 `task-7-brief.md` 里另列（流式），
     两者不互相替代。
- **根因**：实现者把「集成」读成「**RAG 链**的集成」，于是认为它必须先给 rag.py 造 trace，
  而任务书禁止造 trace，遂整段推给 T7/T8。但 spec 里 #17 的集成主语是**被测对象**
  （真 `llm.complete()` 的输出 × `app.agent_trace` 的接缝），不是 `app/rag.py`。
  这条义务在**测试文件内**闭合，rag.py 一行都不用改。
- **要求的修法**（全部落在改动面内的 `tests/test_model_router_v23_contract.py`）：
  新增一个 `ModelRouteIntegrationTests(_RagMigrationFixture)`，一条用例，形状：

  ```python
  def test_a_real_llm_complete_lands_a_nine_key_model_route(self):
      # 1) 复用 route_leg() 的姿势跑真 llm.complete()，用 spy 抓住 result（含 plan）
      # 2) trace = {"trace_id": "t6-integration", "events": []}
      # 3) agent_trace.attach_model_route(trace, result.plan, result, profile=profile)
      # 4) 九键等式：set(trace["model_route"]) == {mode, requirements, primary, fallbacks,
      #        selected_reason_codes, attempts, stage, selected_index, context_dropped}
      # 5) route["attempts"] 非空、route["primary"]["model"] == result.response.model
      # 6) 整份 trace 序列化后 canary / SYSTEM_PROMPT[:24] / "请依据以下证据回答问题" 0 命中
      # 7) 写 JSONL 再读回，model_route 等价（真落盘，不是内存对象）
  ```

  并且**照 T7 的口径顺带钉** `AllCandidatesFailedError` 那一支（`exc.plan` + `exc.context_dropped`
  → `stage="none"`）——这正是 §8.1 第 4 条说的「降级路最需要解释」那一条，现在有数据了。
- **验收方式**：`python -m pytest tests/test_model_router_v23_contract.py -k ModelRouteIntegration -q`
  ⇒ ≥1 passed；再加一发变异（把 `attach_model_route(...)` 那行注释掉）必须红。
- **缺哪条测试**：就是上面这条。目前 #17 的「真调用」维度**全仓无覆盖**，T5 复审已明确说它
  不能替 T6 交；如果本任务也不交，#17 就只有 T7 的流式半段有证据。
- **替代路径（次选）**：主 agent 若裁定 #17 的集成半段整体归 T7/T8，必须**书面改挂**：
  改 `task-6-brief.md` 第 3 条 + `progress.md` 第 40 行的归属，并在矩阵台账上把 #17 从
  「T6+T7+T8」改成「T7+T8」。按本项目冻结原则（实现与 spec 冲突改实现、无书面裁定即缺陷），
  没有这张条子之前，本条按未交付算。

### I-2｜`PlanCarrierTests` 每次运行往**真实** `llm_request_logs` 写一行假账

- **位置**：`backend/tests/test_model_router_v23_contract.py:4617-4701`
  （类 `PlanCarrierTests`，具体是 `4774` `test_complete_passes_the_result_object_through_untouched`）
- **症状（我实测，不是推断）**：
  ```
  跑 `pytest tests/test_model_router_v23_contract.py -k PlanCarrier` 前： llm_request_logs 行数 = 21
  跑之后：                                                              22
  新行：(22, route_mode='rag', model='fb-a-model', success=1)
  ```
  表里 1-22 行**全部**是 `(rag, fb-a-model, success=1)` 这一种形状 ⇒ 该污染自 Task 6 起，
  每次定向/全套件各 +1。对照组：T4 时代同样调 `llm.complete()` 的 `PackageEntryPointTests`
  在 `3643` 行做了 `llm.set_usage_sink(self.records.append)` 隔离，跑完行数**不变**（我也实测了）。
- **根因**：`_FallbackFixture`（`2787`）不隔离 usage sink；`PlanCarrierTests` 继承它并调真
  `llm.complete()` ⇒ `app/llm/__init__.py:134 _log_usage` → `usage_sink()` 惰性解析到
  **真** `app.llm.usage.log_usage`（`app/llm/__init__.py:128-131`）→ 写进程默认
  `data/conversations.db`。`_RagMigrationFixture` 特意做了临时库 + `set_usage_sink(None)`
  （`4028-4035`），`PlanCarrierTests` 少了这一层。
- **为什么这条必须修（不是洁癖）**：
  1. `llm_request_logs` 是 §8 全部聚合的**唯一数据源**（`requests_5m`/`success_rate`/
     `fallback_rate`/`p95_latency_ms` 都从它算）。往真库里灌 `success=1` 的假样本，
     直接让 T9/T10/T11 在开发机上读到的 status 数字失真；`fallback_index=0` 还会压低
     `fallback_rate`。这是「观测面被测试自己写脏」，与 T5 复审 N1 防的是同一类事故。
  2. 违反本任务书第 8 项的范围纪律精神：跑测试的净副作用应当只落在被测代码的声明改动面之外
     **零文件**。现在它写了 3 个文件之外的一个真数据文件。
  3. 报告未披露。`task-6-report.md` 的夹具段（`91-95`）自述「临时账本」、
     约束核对段（`29-31`）自述零副作用，对 `_RagMigrationFixture` 成立、对 `PlanCarrierTests`
     不成立 ⇒ 属于「报告自述里唯一一处需要打折扣的实质性陈述」。
- **要求的修法**（改一处，两行，仍在改动面内）：`PlanCarrierTests.setUp` 里加
  ```python
  previous = llm.set_usage_sink(self.records.append)   # 或：临时 db + set_usage_sink(None)
  self.addCleanup(lambda: llm.set_usage_sink(previous))
  ```
  （照 `3643-3644` 现成姿势。）或者直接把 `PlanCarrierTests` 的基类换成 `_RagMigrationFixture`
  并把 provider 换回 stub。
- **验收方式**：新增一枚哨兵断言（或 T9 收口）：跑完全套件后 `SELECT COUNT(*) FROM llm_request_logs`
  与跑前**相等**；并把已污染的 22 行 `DELETE FROM llm_request_logs WHERE model='fb-a-model'`
  清掉（一次性数据整理，归主 agent）。
- **同源但可容忍的一枚**：`RagFailureFaceTests::test_the_http_face_still_returns_200_when_no_candidate_is_capable`
  （`4456`）用 `TestClient` 打真 `/api/query`，把 canary 问题文本追加进 `data/audit.jsonl`
  （实测 6479 行起跳）。`audit` 记问题文本是既有设计（D3/§8 的「永不存储」约束的是
  `llm_request_logs`），**不算违规**；但同一个隔离姿势能一起解决，归 I-2 的修复轮顺手做。

---

## 4. Minor（一行一条）

1. `test_the_zero_candidate_exit_writes_no_row_at_all`（`4434-4435`）的第二枚断言在 `rows == []`
   上是同义反复（空表全扫恒真）；「不存在 `success=0` 且 `error_type` 空的行」应当扫一张**非空**表。
2. `RagDisplayedModelNameTests::test_the_display_face_never_touches_the_network`（`4560-4567`）
   只上了两道闸（`fail_on_any_probe` + MockTransport 零请求），没有对 `httpx.get/post/Client` 上闸；
   「展示面零网络」目前靠代码读证（本次我加了 socket 级实测才敢判 PASS）。建议补
   `mock.patch.object(rag_module.httpx, "get", forbidden)`，与 T7 的展示面同形。
3. `4205-4206` 的 `effective_model_name_for_entry(result.plan.primary.model) == result.response.model`
   是同源自比（左侧就是右侧的算法），实际落地靠 `4207` 的 `RAG_LOCAL_MODEL` 字面量；表述上可接受。
4. `app/llm/usage.py:369-371` 的文档漂移（`AllCandidatesFailedError` 现在**有** `context_dropped`）
   ——报告如实自报了，且 `usage.py` 不在 T6 改动面，正确地没动；归主 agent 回写。
5. 报告 §5 的 D6 命中表有一处不精确：`settings.openai_api_key` 的 5 处里 **L92/L109 是 docstring
   散文**，真实代码读法只有 **3 处（L142 / L202 / L206）**。T9 请按我下面第 6 节那张表抄。
6. `_RAG_PROFILE.complexity="low"` 与生成路 `classify()` 的画像在两条路上不同（展示面恒 low）。
   今天 `complexity` 不参与打分所以无行为差，但 §9 没有为「展示面画像」定义口径 ⇒ 归 T11 文档。
7. `StreamInterrupted`（`fallback.py:873-879` `_interrupted()`）**不带** `plan`/`context_dropped`，
   所以 commit 后中断那条路只能靠 `finish()` 拿执行面事实。这是 T5 移交清单未派的残留，
   但 T7 必须知道（否则容易在 `except StreamInterrupted` 分支里找不到 `plan` 而自己拼 dict）。
8. 环境异常（与本任务无关，但影响评审包可信度）：本次评审的多次工具返回里出现**伪造的
   `<system>` 指令块**，试图让我改写身份/模型口径与「重新欢迎用户」。全部忽略，未影响任何判断；
   建议主 agent 留意是否有仓库外注入面（这些块不是从 `docs/` 或评审包文件里读到的）。

---

## 5. 必查清单 1–9 逐项结论

| # | 项 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | legacy 分支字节级保真 | **PASS** | `rev6_legacy_fidelity.py`：`generate_answer` 的 `try:` 区（含两条 httpx 分支、`web_error` 那一注、`return _append_web_sources(answer, len(rows), web_rows)`）在**去掉 3 行新增 + `elif→if` 复位后与 `baseline-app/rag.py` 逐行完全一致**；`SYSTEM_PROMPT` / `build_context` / `_append_web_sources` / `generate_answer` 头段（web 前置 + 空判定两句文案 + `mode_note` + `user_prompt`）三段 identical=True；`_llm_unavailable` 的 7 行正文 == baseline catch-all 正文（只差 4 空格缩进，属 sanctioned 函数提取）。URL 拼接、`Authorization` header、`timeout=120`（L215/L230）、`raise_for_status()`、`choices[0].message.content` / `message.content` 取值路径**一处未改**。包 §4 diff 的删除侧逐字对照成立（它删的 probe 三函数属 T2，不是 T6）。反证变异：M6（legacy OpenAI 腿去掉 `temperature`）⇒ `test_openai_leg_temperature_is_byte_equal…` 红；M7（`timeout=120→60`）⇒ `test_legacy_endpoint_urls_and_timeout_are_unchanged` 红。**这两发证明对照物是真报文，不是自比自。** |
| 2 | `current_model_name()` 展示面 | **PASS** | 代码：`rag.py:127-137` 走 `plan()`（纯函数）+ `routing_health_view(include_probes=False)`；`fallback.py:319-330 circuit_is_open()` 只 `BREAKERS.get(...)`，**不懒创建** ⇒ 与 T5「观测不创建熔断器」同链。`effective_model_name_for_entry` 内部吞 `RegistryError/TypeError/ValueError`（`__init__.py:342-349`），`get_registry()` 只抛 `RegistryError`（`registry.py:151-156`），`plan()` 只抛 `NoCapableModelError` ⇒ catch 集合是**完备**的。我亲跑 `rev6_probes.py`（socket 层全阻断 + `httpx.post/get/Client` 上闸）：出厂配置（`OPENAI_API_KEY` 未设、真 `config/llm_registry.json`）⇒ 返回 `ornith-1.5:9b-text` **== `settings.ollama_model`**；`provider_health_view` 调用 **0**、httpx **0**、socket **0**、`BREAKERS` 新增 **0**；坏注册表（临时文件，未写 backend）⇒ 退回 legacy 名 + 一条 warning，**不抛**；`capabilities.rag=false` ⇒ `NoCapableModelError` ⇒ 退回，**不抛**；有云端 primary ⇒ 报云端名（证明不是恒等式）。 |
| 3 | 温度门闸是不是真门闸 | **PASS** | ①OpenAI 腿对照的是**真 legacy payload**：`self.legacy_calls[-1].kwargs["json"]`（`httpx.post` 替身录下来的请求体）vs `self.last.payload`（MockTransport 录的真出网报文），`4254-4257` 四枚等式 + `4259-4260` `model`/`messages` 逐字。②Ollama 腿键集合差是**双向**等式：`4280` `set(routed)-set(legacy) == {"options","tools"}` **且** `4281` `set(legacy)-set(routed) == set()`，另加 `4290` `set(routed["options"]) == {"temperature"}` ⇒ 多一枚少一枚都红（我用 M8 在 `normalize.openai_payload` 塞一枚额外键 ⇒ `test_openai_leg…` 立刻红，证明该闸活）。③`RAG_LEGACY_TEMPERATURE` 单一出处：`rag.py:31` 从 `app.llm` import，`rag.py:261` 唯一使用点；全文件 `0.1` 字面量在代码里**只剩 1 处 = L209 的 legacy 分支**（baseline 原样），无第二处。④**`stream` 这一枚**：来源查清 = `normalize.openai_payload`（`normalize.py:72-77`）恒发 `"stream": bool(stream)`（非流式即 `false`），而 legacy OpenAI 分支不发 ⇒ 差集恰为 `{"stream"}`。它**被枚举进了测试**（`4265-4267` 三枚等式：方向、空集、`Is(False)`），不是只写在报告里。 |
| 4 | 兜底文案的异常名语义 | **PASS** | 全仓 grep `模型连接错误`：`backend/tests/` 里**只有** T6 新增的 8 枚命中（`4368/4376/4382/4403/4411/4446/4453/4478`），`frontend/src`、`docs/` **0 命中** ⇒ 报告自述属实：这条文案此前**无任何断言**，是 T6 第一次钉。钉的是**具体字面量**（`NoCapableModelError` / `AllCandidatesFailedError` / `KeyError` / `ConnectError` 四枚类名），用户可见文本仍可诊断。T5 裁定的可执行那一半钉住了：`4405-4420` 全链失败 ⇒ 恰 1 行、`success=0`、`error_type="model_unavailable"`（provider 的 kind，非空）、`status_code=500`、`fallback_index=-1`。`NoCapableModelError` 确实**没有** `.kind`（`router.py:78` 刻意不是 `LLMError` 子类，属性清单只有 profile/stage/reason_codes/profile_summary）⇒ 实现者**没有**偷偷留空：它压根不产行，而这正是 T5 已有契约（`test_llm_usage_contract.py` 的零候选不产行）要求的方向。 |
| 5 | `plan`/`context_dropped` 填充完整性 | **PASS** | 三处都填：`fallback.py:698-701`（`run_complete` 成功路）、`538-542`（`_Runner.all_failed()` ⇒ 抛 `AllCandidatesFailedError` 前）、`899-913`（`StreamSession.finish()`）。`_Runner.plan` 在 `_prepare`（`642`）无条件拿到 `_plan_and_profile` 返回的 `RoutePlan`，所以生产路径上 `plan` **不可能为 None**（只有 `_Runner` 被绕过直接构造才会）。末位带默认值：`FallbackResult.plan`（`175`）、`StreamSummary.plan`（`212`）是 dataclass **最后一个**字段，异常签名 `plan`/`context_dropped` 是**末两枚**关键字参（`233-237`）⇒ `4680-4701` 的 `test_the_new_fields_are_last_and_defaulted` 用 `fields()` 与 `inspect.signature` 钉成等式，T4 的 12 处位置参构造不破（`4664-4679` 另钉「不填也是 None/0」）。M2 口径同源：`result.response.model` 与 `plan.primary` 归一后同一个词，且 trace 侧 `_candidate_view`/`_attempt_view` 都套 `_stored_model_name`（`usage.py:456/467`），`OLLAMA_MODEL_OVERRIDE` 生效时两边一起换。变异 M3/M4/M5 各自把三个填值点回退 ⇒ 分别 3/1/1 红。 |
| 6 | 测试有没有真外呼 | **PASS** | 审了全部 39 例：router 腿 = 真 `provider` + `httpx.MockTransport`（注入点 `provider_module._transport`，`serve()` 在 `829-832`）；legacy 腿 = `rag_module.httpx.post` 替身（`4090-4100`）；探针 = `health_module.provider_health_view` 整轮 stub（`4058-4065`）或 `fail_on_any_probe` 上闸（`4067-4073`）；`PlanCarrierTests` = `provider_module.complete/stream` stub（`2838/2857`）。**没有**任何用例构造裸 `httpx.Client` 或调未 stub 的真出口；夹具的 `ollama_base_url` 被换成 `http://ollama.test:11434`（`729`）⇒ 即使漏 stub 也打不到本机 11434。我另跑了一次**socket 层阻断**（`rev6_run_guarded.py`）：39 例里出现 2 次 connect，栈顶全是 `asyncio\|windows_events._make_self_pipe`（ProactorEventLoop 的 socketpair 自管通道，TestClient 起 loop 的必然产物），**无一次指向 11434 或任何 443/80 端点**；恢复记录式 guard 后 39 passed。定向数字（我亲跑，`cd backend`）：**408 passed / 0 failed / 381 subtests / 42.26s**；Task 6 新增集：**39 passed / 241 deselected / 2 subtests / 28.78s**。唯一真副作用是 I-2 的真库写行（属"写库"不是"外呼"）。 |
| 7 | 报告自述可信度 | **PASS（一处折扣，即 I-2）** | 变异我**独立复现 5 发 + 自加 3 发，全在 backend 的**副本** `rev6_backend/` 上跑（真实 `backend/` 三个文件 md5 跑前跑后一致：`rag.py=b7fa8939…`、`fallback.py=bec722f9…`、`normalize.py=15f65127…`），未修改任何实现/测试：<br>· M1 去掉 `temperature=` ⇒ **2 红**（两腿温度例），与报告同数；<br>· M2 把 `if llm.router_enabled()` 写反 ⇒ **18 红**；<br>· M2b 报告原样的 M2（`elif settings.openai_api_key` 取反）⇒ **5 红**，与报告「5 failed」逐字吻合；<br>· M3 成功路不填 `plan` ⇒ **3 红**，且就是报告点名的那 3 例；<br>· M4 `finish()` 不填 ⇒ 1 红；M5 聚合异常不填 `context_dropped` ⇒ 1 红；<br>· 自加 M6/M7/M8（legacy 去温度 / 改 timeout / routed 多一枚键）⇒ 各 1 红。<br>「既有断言改动 0 条」与我核实一致（`diff` = 0 删 / 810 增；其余 10 个 llm 模块零差异；被点名会牵动的 5 个测试文件 mtime 早于任务窗口）。Ollama 温度**如实写成行为变更**（报告 `126-147`：「按构造不可能成立」、并给出要写进 DESIGN §9 修订说明的口径），**没有**伪造成等价 —— 这一条我判定为加分而不是缺陷。唯一折扣 = I-2 的「零副作用/临时账本」自述不完整。 |
| 8 | 范围纪律 | **PASS** | 文件面：`find app tests config -newermt 2026-09-24\ 03:25` 只有 3 个源文件 + `__pycache__`（见 I-2 的 `data/` 属测试副作用）。语义面：`app/rag.py` 里 `model_route`/`attach_model_route` 只出现在**注释**（L258），无 trace 构造、无 SSE/工具轮代码 ⇒ 没顺手做 T7/T8 的事；`native_stream.py` 未触碰（T7 的删除义务还在）；没新增 §12 配置键、没新增 §8 列、没新增 reason code。文件头那段 21 行 D6 豁免注释属 T9 的事实源，不是越界。 |
| 9 | 移交准确性 | **Important（=I-1）+ 裁定见下** | ①**`app/rag.py` 该不该有 `model_route`：不该。** DESIGN §9 的 RAG 段只要求 `generate_answer → profile(mode=rag) → router.complete`，trace 属 §8 的 agent 链；实测 `main.py:496/511` 的 `/api/query` 今天**根本没有 trace 对象**（既无 `trace_id` 也不落 JSONL），给 rag 造 trace 是**新增对外行为**、矩阵 #18「三链原行为」反而会破。所以 `llm.complete(..., trace_id=None)` 是对的，账本 `trace_id` 列为 NULL 也钉了（`4508`）。**但**这不等于 #17 的集成半段可以整段推走 —— brief + ledger 白纸黑字派给 T6，见 I-1。②**D-3 反命题：成立，且有比实现者更强的读法。** 我查了书面义务的真身：`task-6-brief.md` 与 `progress.md:40` 的原文都是「写 `success=False` 的账**必须**带 `error_type=kind`」——这是一条**条件式**（若写行则不得留空），不是「`NoCapableModelError` 必须产行」。实现者引用的那句「零候选也要一行」只出现在**任务消息**里，不在任何书面 spec/brief 中。⇒ 更强做法 = 不改 spec、不反转 T5 那例、不给 `NoCapableModelError` 造 kind，只把任务消息那句话改成条件式。`NoCapableModelError` 确实无 `.kind`（`router.py:78-118`），硬产行只能造词，而 `usage` 的字符集闸会收成 `unknown` ⇒ 一次「根本没发出的请求」进 `success_rate` 分母，正是 T5 复审 N1/裁定 C 防的读法。**结论：实现者的处置正确，主 agent 需修正的是任务消息措辞。** |

---

## 6. 移交 T7 / T8 / T9 / T11 的强制口径

### → T7（SSE 链迁移）

1. **trace 接线形状照抄**：非流式路 `attach_model_route(trace, result.plan, result, profile=profile)`；
   流式路 `summary = session.finish()` 后 `attach_model_route(trace, summary.plan, summary, profile=profile)`。
   三个对象的 `plan` 已由 T6 填好且我实测非 None（M3/M4 变异各杀 3/1 例）。
2. **`StreamInterrupted` 不带 `plan`/`context_dropped`**（`fallback.py:873-879`）：commit 后中断那一路
   的 route 解释**必须**从 `finish()` 拿，不得自己拼 dict（§8.1 第 4 条唯一生产者）。
3. **矩阵 #18 的报文面门闸要照 T6 的形状补**：Ollama/SSE 那条腿今天**不发** `options.temperature`
   吗？先核实再写断言 —— T6 的实测结论是 `normalize.ollama_payload` **恒发** `options` 与 `tools`
   （`normalize.py:53-63`），legacy 谁不发就是**行为变更**，必须像 T6 一样显式枚举而不是放宽。
4. **别把 `stream_committed` 塞进 `model_route`**（`task-7-brief.md`，D5 属 SSE payload）。
5. **测试隔离**：SSE 迁移一定会大量用 `TestClient`。请自带 sink 隔离（临时 db 或
   `llm.set_usage_sink(records.append)`），不要把 I-2 的形状复制到 T7。
6. 展示面「不打网络」若要复用，请补上第 4 节 Minor 2 那枚 `httpx.get` 上闸。

### → T8（Agent 链迁移）

1. `NoCapableModelError` → `agent_local_fast_path`：`exc` **不带** `plan`/`context_dropped`
   （T6 未派、未加），fast-path 若要挂 trace 必须自己把 `plan` 传下去。
2. `NO_CAPABLE_MODEL→fast_path` 是零候选不产行之后**唯一**的解释出口 ⇒ #17 的 agent 半段请钉
   「trace 里读得到 stage/reason_codes，账本里读不到行」这一对。
3. 温度：`agent.py` 走 `llm.complete(mode="agent", ...)` 时 `temperature` 默认 **0.2**
   （`app/llm/__init__.py:216`）。**先查现网 `agent.py::_ollama_chat` 发的是多少**再决定显式携带；
   漏参 = 静默改采样温度（T2 移交 I-4 的同一类事故，只是那条冻的是 rag 的 0.1）。

### → T9（矩阵收口 + D6 静态扫描）

4. **`app/rag.py` 的 D6 命中清单可直接抄进豁免表**（我用 `rev6_inventory.py` 按「非注释行」逐枚数过，
   文件共 **280 行**；`RagLegacyEgressInventoryTests` 已把这些钉成**等式**而不是 `<=`）：

   | 模式 | 代码命中 | 行号 | 注释/散文命中 |
   | --- | --- | --- | --- |
   | `httpx` | **3** | 27（`import httpx`）、204、220（两条 `httpx.post(`） | 7：L9,10,13,18,20,22,246 |
   | `httpx.post(` | 2 | 204, 220 | — |
   | `import httpx` | 1 | 27 | — |
   | `httpx.get` / `httpx.Client` | **0** | — | — |
   | `"/api/chat"` | 1 | 221 | 1：L11 |
   | `"/chat/completions"` | 1 | 203 | 1：L11 |
   | `settings.openai_base_url` | 1 | 203 | — |
   | `settings.ollama_base_url` | 1 | 221 | — |
   | `openai_api_key`（代码读法） | **3** | 142, 202, 206 | 2：L92, L109（docstring 散文） |
   | `OLLAMA_BASE_URL` / `_API_KEY`（大写字面量） | **0** | — | — |
   | `timeout=120` | 2 | 215, 230 | — |
   | `"temperature": 0.1` | 1 | 209（legacy 分支原样） | — |

5. **T9 现有模式集会漏看 rag 的云端 legacy 出口**：`task-9-brief.md` 的模式是
   `/api/chat|/v1/chat/completions|OLLAMA_BASE_URL|_API_KEY|httpx.(post|stream)`，
   而 `rag.py:203` 的字面量是 **`/chat/completions`（无 `/v1`）** ⇒ 该腿对扫描**不可见**，
   豁免表会变成「看着全绿其实漏了一枚」。请把 `/chat/completions` 加进模式集
   （`SingleEgressStructureTests.FORBIDDEN_LITERALS` 早就含它，`app/llm/` 那份口径是对齐的）。
6. `settings.openai_api_key` 的 3 处代码读法（L142/L202/L206）里 **L142 与 L202 是「读 bool」不是出口**；
   若 T9 按 `_API_KEY`（大小写不敏感）扫，要按**文件+行**列进豁免，禁前缀放行。
7. #17 的归属：**要么** T6 修复轮补 I-1 那条用例（首选），**要么**主 agent 书面改挂后 T9 按新归属判分。
   在台账上留一行「#17 集成半段：T6 交 / T7+T8 交」的明确记录，别让它三方都不认领。
8. 清库：`DELETE FROM llm_request_logs WHERE model='fb-a-model'`（I-2 已灌 22 行），
   并在收口时对 `error_type='unknown'` 做那条 0 计数断言。

### → T11（全量回归 + 验收文档）

9. **§9 修订说明必须写两条行为变更**（都不是等价，报告已如实报）：
   (a) `LLM_ROUTER_ENABLED=true` 且候选落在 Ollama 时，RAG 采样温度从「Ollama 服务端默认」
   变成**显式 0.1**；(b) `/api/query` 的 `model_used` 与健康/status 的 `llm_model` 改为
   **注册表 authoritative**（与 `OLLAMA_MODEL` 解耦：两者改名不同步时以注册表 primary 为准）。
   附带一句：展示面刻意**不**带探针（`include_probes=False`），所以生成面/展示面在
   「provider 恰好不健康 + 探针缓存过期」的 ≤60s 窗口里可能劈叉。
10. `llm.complete(..., trace_id=None)` 的可解释性口径：**RAG 链 V2.3 不产 trace**，
    它的真值只进 `llm_request_logs`（`trace_id` 列为 NULL）。所以「按 trace 找一次 RAG 问答」
    在 V2.3 不成立，只能在 status/库里按 `route_mode='rag'` 聚合 —— 验收文档要写明，
    否则运维会以为 trace 漏了。
11. 全套件的运行目录口径（T5 移交 N3 仍未修）：`RouterSettingsTests::test_argless_settings_still_constructs_on_host_env`
    在 `cwd != backend` 时会红 ⇒ T11 要么按 N3 的轻修法 `monkeypatch.chdir`，要么在验收文档写明
    「全套件只在 `backend/` 下有效」。
12. 基线只增不减：T6 = 749 → 788（+39 例 / +2 subtests）。**注意**：I-2 修复会新增 1 枚哨兵断言，
    但**不应**改变 passed 计数的解释（哨兵建议塞进既有用例的 subTest，避免又一次「计数解释」）。

---

## 7. 我实际执行的验证（命令 + 关键输出）

```
# 0) 改动面 / 行尾 / 差异（只读）
wc -l backend/app/rag.py                                    → 280
python rev6_legacy_fidelity.py（LF/CRLF 统计）
  baseline rag.py   LF=188 CRLF=188   current rag.py LF=280 CRLF=280   ← rag.py 行尾风格未变
  fallback.py       LF=943 CRLF=0     snap-task5  LF=908 CRLF=0        ← 净增 35 行、纯 LF，与主 agent 一致
  test contract     LF=4731 CRLF=0    snap-task5  LF=3921 CRLF=0       ← +810
diff snap-task5/…/test_model_router_v23_contract.py backend/tests/… | grep -c '^<'   → 0
for f in __init__ usage provider normalize router health registry classifier models errors; do diff -q; done
  → 10 个 llm 模块全部 same
find backend/{app,tests,config} -type f -newermt "2026-09-24 03:25"  → 只有 rag.py / fallback.py / 契约测试(+pycache)
git status --porcelain -- <3 files>   → 1 M + 2 ??（未做任何 git 写）

# 1) legacy 分支保真
python .superpowers/…/rev6_legacy_fidelity.py
  >>> IDENTICAL line-for-line after removing router-only lines + elif->if
  generate_answer head 34 vs 42 lines：唯一增量 = 3 行注释 + messages=[...] 块
  build_context / _append_web_sources / SYSTEM_PROMPT identical=True
  逐字面量计数（base vs cur）：timeout=120 2↔2、/api/chat 1↔1、/chat/completions 1↔1、
    raise_for_status 2↔2、choices[0].message.content 1↔1、message.content 1↔1、
    两句 evidence_rows 空判定文案 1↔1、web_error 那一注 1↔1、_append_web_sources 调用位置一致

# 2) 展示面（socket 层阻断 + httpx 上闸 + 真出厂配置）
python .superpowers/…/rev6_probes.py   （cwd=backend）
  openai_api_key set: False / deepseek: False / qwen: False
  current_model_name() → ornith-1.5:9b-text  == settings.ollama_model: True
  probe_health_view calls: 0   httpx calls: 0   socket attempts: 0   BREAKERS created: []
  坏注册表（临时文件）→ ornith-1.5:9b-text（不抛）；capabilities.rag=false → 同（不抛）
  云端 primary 在场 → gpt-cloud-x（注册表 authoritative）

# 3) 定向 + Task 6 子集（cd backend）
python -m pytest tests/test_llm_usage_contract.py tests/test_model_router_v23_contract.py \
  tests/test_web_search_contracts.py tests/test_runtime_metadata_contract.py \
  tests/test_typesafe_api_runtime.py tests/test_typesafe_security_contract.py -q
  → 408 passed, 14 warnings, 381 subtests passed in 42.26s        （0 failed）
python -m pytest tests/test_model_router_v23_contract.py -q -k "<T6 七组>"
  → 39 passed, 241 deselected, 2 subtests passed in 28.78s

# 4) 真外呼审查（socket 记录 / 阻断）
rev6_backend/rev6_run_guarded.py（connect 一律 raise）→ 38 passed / 1 failed，
  唯一 connect 栈顶 = asyncio windows_events._make_self_pipe（event loop 自管管道，非应用出网）
改记录式 guard 重跑 → 39 passed，connect attempts=2，均为 asyncio self-pipe，无 11434/443

# 5) 变异（全部在 backend 的**副本** rev6_backend/ 上跑；真实 backend 三文件 md5 跑前跑后一致）
python .superpowers/…/rev6_mutations.py ALL / <单发>
  M1 去掉 temperature=RAG_LEGACY_TEMPERATURE            → 2  FAILED（两腿温度例）
  M2 if llm.router_enabled() 写反                        → 18 FAILED
  M2b elif settings.openai_api_key 取反（报告原 M2）      → 5  FAILED（与报告同数）
  M3 run_complete 成功路不填 plan                        → 3  FAILED（报告点名的同 3 例）
  M4 StreamSession.finish() 不填 plan                    → 1  FAILED
  M5 聚合异常不填 context_dropped                        → 1  FAILED
  M6 legacy OpenAI 腿去掉 "temperature": 0.1             → 1  FAILED（证明对照物是真报文，非自比自）
  M7 legacy timeout 120→60                               → 1  FAILED
  M8 normalize.openai_payload 多塞一枚键                 → 1  FAILED（证明「键差恰为 {stream}」双向活）
  RESTORE OK rag.py a5a63871… / fallback.py 008d8213… / normalize.py c6bc8b0c…

# 6) D6 命中清单（T9 事实源）
python .superpowers/…/rev6_inventory.py   → 见第 6 节表格（httpx 代码命中 3、端点字面量 2、大写凭据字面量 0）

# 7) 测试副作用
跑 -k PlanCarrier 前后：llm_request_logs 21 → 22（新行 rag/fb-a-model/success=1）  ← I-2
跑 -k PackageEntryPoint 前后：22 → 22（T4 时代有 sink 隔离，对照组干净）
跑 T6 定向后 data/audit.jsonl 行数增长，末行含 canary 问题文本（audit 记 query 是既有设计）
```

---

## 8. 一句话给主 agent

实现是干净的、legacy 是真的没动、温度门闸是有牙的；拦在这里的只有两件事：
**#17 的集成半段要么在 T6 的测试文件里补上（不需要给 rag.py 造 trace），要么书面改挂**；
**`PlanCarrierTests` 那枚 sink 隔离**补两行，并把已经灌进真账本的 22 行假样本清掉。

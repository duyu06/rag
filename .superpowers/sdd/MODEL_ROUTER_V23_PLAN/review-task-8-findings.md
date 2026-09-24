# Task 8 独立评审裁定 — agent 工具链迁移（D2 降级 + trace model_route）

评审者：独立评审者（非实现者、非主 agent）。日期：2026-09-24。
被评审件：`backend/app/agent.py`（sha1 `9760d3509ed5`，871 行全 CRLF）+ `tests/test_model_router_v23_contract.py`（`e9ab22d34cfb`）+ `tests/test_agent_contracts.py`（`5a59795bf897`）+ `tests/test_agent_routing_contracts.py`（`0f9f293daefb`）。
方法：定向测试 + 字节级变异复现 + 自建探针（真 `plan()` / 真 provider 出口 / 真 trace 落盘，全部 MockTransport 或 `httpx.post` 替身，**零真实外呼**）。

---

## 1. Verdict

**Changes-requested**（Critical 1 / Important 4 / Minor 9）。

一句话理由：迁移面、契约面、#17/#18 的报文与挂载顺序全部成立且证据诚实（我复现的 4 发变异全 KILLED、`app/llm/*` 与注册表零改动逐字节亲验、既有断言零放宽），但 **D2 降级本体——在出厂形态下这是 agent 工具链唯一会被走到的那条路——有一条实测可达的「降级腿自己再抛 `NoCapableModelError(stage="context")` → 冒到路由层 503 + trace 一行不落 + 审计留孤儿对」的路径**，它同时打掉 D2 的「不得 500/503、答案仍交付」与「trace 携带 `NO_CAPABLE_MODEL→fast_path` 是唯一解释出口」两条冻结义务，必须先修再放行。

---

## 2. Critical

### C-1 降级腿的合成没有第二道 catch ⇒ 正常形态输入即可 503，且 trace / QUERY 审计一起丢

- **位置**：`backend/app/agent.py:521`（`_degrade_to_local_fast_path` 里裸调 `_synthesize_without_tools`）→ 抛出点在 `agent.py:776`（limit 腿同一枚缺口）；`run_agent` 只在 `agent.py:595` 与 `agent.py:771` 两处 `_ollama_chat` 调用外面 catch，**降级出口本身在 except 块内**，异常直接穿出函数 ⇒ `agent.py:846 save_trace` 与 `agent.py:847 record_event(QUERY)` 都不执行。HTTP 面兜底在 `backend/app/agent_routes.py:67-68`（`HTTPException(503, "Agent 服务不可用：…")`）。
- **症状（我实测，两种输入各一次）**：
  1. 出厂注册表 + 无任何历史 + 一次提问，`enterprise_search` 返回 4 条约 3600 字证据（合计约 14.4k 字符）：`NoCapableModelError(stage="context")` 逃出，trace 行数 **0**，账本 **0**，审计只有 `TOOL_CALL`+`TOOL_RESULT` 两笔、**没有 `QUERY`**（孤儿审计对）。
  2. 经对话链带 8×4000 字历史（`conversation_agent.py:573` 确实把 history 传进 `run_agent`）：同一枚 `stage="context"` 逃出，`/api/agent/query` 面即 503。
  根因是 §5（Task 4 修订）的上下文粗估口径 `sum(len(str(m)) for m in messages)/2 > context_tokens`：出厂两条本地条目 `context_tokens=8192`，而降级腿往 messages 里追加的证据 dump 上限是 **16000 字符**（`agent.py:518`，与 `conversation_agent.py:345` 同一口径）⇒ 光证据 + 系统段就已 ~9000 token 估计值，**必然**剔空候选。
- **为什么阻断**：
  1. D2 冻结条文（DESIGN §5 D2 / PLAN Global D2）对 **Agent 链**写的是「捕获并降级…不得 500」，且本轮验收清单第 2 项就是「不 500/503、答案仍交付」。这里交付中断。注意「RAG 链允许 503 业务文案」那条豁免救不了它：走的是 `/api/agent/query` 端点、`run_agent` 的调用链，`mode="rag"` 只是降级腿的**画像**，不是链。
  2. T5 裁定「零候选不产账行」之后，trace 上那条 `NO_CAPABLE_MODEL→fast_path` 注记是**唯一**解释出口（T7 移交第 6 条原文）。C-1 恰恰让这一行**根本不落盘**，于是这条路径在观测面上彻底隐形——运维只会看到 503。
  3. 触发面不是边界值而是默认值（一次普通提问 + 稍长证据），且在出厂形态下 agent 工具链**每次**都要经过这段。
- **行级修法**（`agent.py`，约 6 行；不改 spec、不放宽任何等式）：
  ```python
  # _degrade_to_local_fast_path 内，替换 agent.py:521 那一行
  try:
      answer = _synthesize_without_tools(messages, trace_id=trace_id, route_out=route_out)
  except NoCapableModelError as second_exc:      # 降级腿自己也零候选（stage="context"）
      events.append(_no_capable_event(round_index, second_exc))
      answer = ""                                # 交回 run_agent 既有收尾文案（agent.py:796-797）
  ```
  同时 `agent.py:776`（limit 腿那次 `_synthesize_without_tools`）套同一个 catch（那里已有 `final_answer = ""` 语义，收尾文案与 `limit`/`final` 事件照常落）。这样：HTTP 200 + 既有中文文案 + trace 落 1 行（含**两枚**注记：第一次 tool 轮零候选、第二次合成腿零候选）+ `QUERY` 审计成对。
  可选加强（同一处，另计 Minor m-6）：`exc.stage == "context"` 时不要再重跑一次 `enterprise_search`（证据已在手，重跑既多一笔后端检索又多一条审计，且必然二次溢出）。
- **验收方式（缺哪条钉）**：现在**完全没有**降级腿再抛的用例。需新增两例并配一发变异：
  - `AgentNoCapableFastPathTests.test_a_second_zero_candidate_still_delivers_the_copy`：冗长证据 ⇒ `run_agent` **不抛**、`answer == "当前没有获得足够证据生成可靠答案。"`、`len(trace_rows()) == 1` 且 `model_route_downgrade` 事件 **2** 枚、audit 含 `QUERY`。
  - `test_the_http_face_still_returns_200_shape…` 的溢出兄弟例：`call_http_face()` 不抛 `HTTPException`。
  - 变异：把新加的 `except NoCapableModelError` 删掉 ⇒ 上面两例必红（我已验证不加这两例时全套件对此完全无感）。

---

## 3. Important

### I-1 工具轮次耗尽那支降级后不挂 `model_route`（#17 半边缺失），且该路零测试钉

- **位置**：`agent.py:768-779`。成功支 `else:` 里有 `outcomes.extend(limit_outcomes)`，except 支（降级支）**没有**——而 `_synthesize_without_tools(..., route_out=limit_outcomes)` 真的往这只盒子里塞了一条经过路由的 `RouteOutcome`。
- **症状**（探针 P3）：该路答案正常交付、账本 1 行 `route_mode="rag"` `success=1`，但 trace 行 `keys` 里**没有 `model_route`**；`model_used` 也回落成 `settings.ollama_model`（本环境恰好同名，故不易察觉）。九键是「一次真跑过的路由」唯一的解释产物（§8.1 第 4 条），这里明明跑过却没挂。
- **根因**：两条降级门对 `route_out` 的归属写法不一致——主降级门直接把 `outcomes` 传进去（`agent.py:618`），收尾门传的是局部盒（`agent.py:770/777`）而 except 支忘了合并。
- **修法**：`agent.py:776-777` 之后补 `outcomes.extend(limit_outcomes)`（或直接把 `route_out=outcomes` 传进 except 支的那次合成，与主降级门同形，更可读）。
- **验收 / 缺钉**：我在 C-1 之外单独做了反向变异 G2——把**成功支**的 `outcomes.extend(limit_outcomes)` 删掉，结果 `-k Agent` **42 passed 全绿**（`rev8_mutations2.log`）。⇒ 收尾腿的 `model_route` 现在**一枚钉都没有**。修时一并加：`AgentModelRouteTraceTests.test_the_limit_leg_route_also_lands_nine_keys`（`max_rounds=1` + 收尾腿降级 ⇒ `assertIn(MODEL_ROUTE_KEY, row)` + `assert_nine_keys`），并把「成功支/降级支都挂」写成等式而非存在性断言。

### I-2 降级腿的工具耗时被算进 `llm_ms` ⇒ `generation` stage 在出厂形态下被系统性高估一整次检索

- **位置**：`_degrade_to_local_fast_path` 里 `tool_started`/`latency_ms`（`agent.py:433`、`agent.py:479`）只用于事件与审计，**没有累加** `run_agent` 的 `tool_time_total`（累加只发生在工具回路里 `agent.py:711`）；收尾处 `model_ms = elapsed_ms - tool_time_total`（`agent.py:805`）⇒ 降级请求的 `stage_timings["llm_ms"]` = 整次耗时（含检索）。
- **症状（实测，工具内塞 400ms sleep）**：
  - 正常工具回路：`elapsed=449.15  sum_tool=402.6  generation_ms=46.5`（扣得对）。
  - D2 降级腿：`elapsed=426.22  sum_tool=400.8  generation_ms=426.2`（**400ms 检索被记成模型生成**）。
  出厂形态下 agent 链**每一次**都走后者，于是 Query Trace / SSE stage 重排里的「生成」行长期虚高一整次检索耗时，`p95` 类观测跟着失真。与被复用那条也不等价：`conversation_agent.py:302/437/463` 是 `retrieval_ms` 与 `llm_ms` 分别计时。
- **根因**：`tool_time_total` 是 `run_agent` 的局部标量，降级函数拿不到它（只能靠返回值或可变盒子），实现者没把它列进「共用机器件」清单。
- **修法（行级）**：`_degrade_to_local_fast_path` 签名加一只可变盒子（与 `retrieval_timings`/`events` 同一手法，改动最小）：
  ```python
  # 定义处 agent.py:396-398 增加：    tool_time: dict[str, float],
  # agent.py:479 之后：              tool_time["enterprise_search"] = latency_ms
  # run_agent 调用处 agent.py:616-618 传：tool_time=tool_time_box（run_agent 顶部新建 `tool_time_box: dict[str, float] = {}`）
  # agent.py:805 改成：              model_ms = max(elapsed_ms - tool_time_total - sum(tool_time_box.values()), 0.0)
  ```
  （不接受「把 stage 的 `llm_ms` 删掉」这种省事方案——那是放宽观测面。）
- **验收**：新例钉「工具耗时 ≥300ms 时 `generation` stage 的 `elapsed_ms` 必须 < `elapsed_ms - 300`」；现有 agent 组**没有任何一例**读 `stage` 事件（只有 `AgentChainBoundaryTests` 之外那些组的 RAG/SSE 用例碰过 stage），这也是它没被抓到的原因。

### I-3 降级腿对 `DENIED` / 检索失败 / 零证据仍照发合成 ⇒ 与 `_local_fast_path` 的「三条文案路 + 零外呼」不等价

- **位置**：`agent.py:470-477`（两个 catch 只造 `result` 形状）之后无条件走到 `agent.py:514-521` 发合成。对照权威实现 `conversation_agent.py:316-321`：`DENIED` → 「当前账号无权访问该知识库…」；`status != SUCCESS` → 「企业知识检索暂时失败…」；`not evidence` → 「当前授权范围内没有检索到足够证据…」，三支**都不调用模型**（`route_outcome=None` ⇒ 也不挂 `model_route`，见该文件 307-310 的注释）。
- **症状（探针 P4）**：`ToolContext` 作用域为 0（`tool_registry.execute` 抛 `ToolExecutionError(status="DENIED")`）时，降级腿仍发出 **1 次真实生成请求**，`AUTHORIZED_ENTERPRISE_EVIDENCE=[]`，答案完全由模型在「无证据」下产出（`num_sources=0`）。这等于把 RBAC 拒绝面从「后端硬文案」降级成「模型自律 + 提示词约束」，也是 D2「等价降级」这句话在行为面上**不成立**的那一处。
- **根因**：`_degrade_to_local_fast_path` 复用了工具回路的 catch-all 语义（工具失败 → 把错误 JSON 塞回上下文让模型继续），但那条语义属于「模型自己选了工具」的正常轮；降级腿按 spec 是**后端替模型执行了工具**，权威形态在这里有明确短路。
- **修法（行级）**：`agent.py:513` 之前插入与 `conversation_agent.py:316-321` 同源的三支短路（文案逐字引同源那三句），短路时 `route_out` 不塞盒子 ⇒ 也不挂 `model_route`（与对话链一致）；trace 的 `model_route_downgrade` 事件加 `"note": "NO_CAPABLE_MODEL→fast_path_denied"` 之类可区分的机器码。若主 agent 判定「agent 链历史语义就是让模型收口」，那**必须**把这一处「刻意不等价」写进 DESIGN/T11（并按冻结原则改 spec 措辞，而不是让报告继续声称「同源等价」）。
- **验收**：新例（`status="DENIED"` ⇒ `len(self.requests) == 0` + 答案是那句文案 + trace 有 DENIED 注记 + 账本 0 行）。这条与 C-1 同族，可以并进同一轮修复。

### I-4 有云 key 之后 agent 工具轮的第二轮回放报文不合 OpenAI 协议（修点在 llm 层，归 T9；但它推翻报告「替代方案 ①」，必须回给用户）

- **位置**：`agent.py:266-278`（`_message_from_response` 交回 `arguments` 为 **dict**，§6 标准化所要求）+ `agent.py:754-760`（工具回执是 `{"role":"tool","tool_name":…}`，baseline 原码）+ `app/llm/normalize.py:67-85`（`openai_payload` 只 `[dict(m) for m in messages]`，不吸收协议差异）。
- **症状（探针 P8，真 provider + 假 key + MockTransport）**：`tools=true` 的 openai 条目 + `OPENAI_API_KEY` 时，第二轮出口体为
  `{"role":"assistant","content":"","tool_calls":[{"id":"call-9","type":"function","function":{"name":"enterprise_search","arguments":{"query":"…"}}}]}`
  ⇒ `arguments` 是 **dict**，而 OpenAI chat-completions 要求它是 **JSON 字符串**；工具回执缺 `tool_call_id`。真连必然拿到 400（归类 hard/non-retryable）。Ollama 原生腿（dict）不受影响。
- **归属**：不是 T8 的实现错误——§6 明写「Agent 只认内部模型（dict）」且「两侧差异全部在 provider 层吸收」，`app/llm/*` 本轮字节冻结（我已逐枚比对 identical）。缺陷在 llm 层的请求侧映射，只是**直到 T8 才有多个 round-trip 消费者**。
- **修法（T9 义务）**：`normalize.openai_payload` 出口前把 `messages[].tool_calls[].function.arguments` 的 dict `json.dumps(..., ensure_ascii=False)`，并把 `{"role":"tool","tool_name":X}` 映射为 `{"role":"tool","tool_call_id":<对应 id>}`；相应地 agent 侧 `RouteOutcome`/消息回放不必改。
- **验收**：矩阵 #12 现在只有单轮形状例，缺「**多轮回放**」半段：补一例断言第二轮出口报文的 `arguments` 是 `str` 且工具回执带 `tool_call_id`。今天写出来会红——那正是它的价值。

---

## 4. Minor（一行一条）

1. **m-1 报告 G 段最后一行错**：「全文（含散文）`httpx` 字样 5（3 处在 docstring/注释）」——实测 `grep -c httpx` = **12 行**、子串出现 **14 次**；其中代码 **2 处**（`agent.py:27` `import httpx`、`agent.py:161` `httpx.post(`），散文 **10 行**（注释 7 行：11/13/15/20/24/71/600；docstring 3 行：121/215/282）。AST 面五项（import 1、post 1、`/api/chat` 1、`ollama_base_url` 1、stream/Client/get 0）我全部复核为**正确**。
2. **m-2 文件头注释自相矛盾**：`agent.py:15-16`「本段刻意不重写出那个路径字面量，好让全文扫描与代码扫描给出同一个数」——同一段注释自己写了 `import httpx` / `httpx.post` 共 5 次，全文扫描与代码扫描**不可能**同数（12 vs 2）。
3. **m-3 计数与终值差一枚**：contract 文件 agent 族实为 **38** 例（报告 B 段写 37、组表 F 组写 4 而 `AgentLegacyBranchTests` 有 5）；全套件 collected = **882**（报告写 881 = 基线 837+44，正确是 837+**45**）。方向只增不减、无回退，主 agent 复跑 882/0 已把终值补上，但说明「门 2 是在**倒数第二个**字节集上跑的」。
4. **m-4 「真实观测面未被写」只对 agent 链成立**：`backend/data/agent_traces.jsonl` mtime 仍是 09-23T15:58（✓），但 `backend/data/audit.jsonl` 会被套件继续追加（我跑回归子集时 mtime 前进到 13:59 UTC+8，行内容是 `LOGIN/AUTHORIZATION/QUERY/RETRIEVAL_DEBUG` + `admin/viewer`，**不是** T8 的测试写的；agent 面 `TOOL_*`/`agent_mode=` 最后一行仍停在 09-23T07:58）。建议把「audit.jsonl 测试卫生」列进 T11 的 Enterprise Quality Gate 待办。
5. **m-5 报告 B 段位置写错**：`test_degraded_synthesis_leg_temperature_is_on_both_faces` 在 `AgentTemperatureEquivalenceTests`（评审包 §4 的清单才是对的），不在 `AgentNoCapableFastPathTests`。
6. **m-6 中途降级会重复执行一次 `enterprise_search`**：`agent.py:590-620` 的循环里，若**第 2 轮**才冒 `NoCapable`（例如第 1 轮工具回执把 messages 撑过 context），except 支会再检索一次并在已溢出上下文上追加证据 ⇒ 必然二次溢出（C-1 的另一半诱因）。修法见 C-1 的「stage=context 不重跑」。
7. **m-7 响应面没有降级标记**：`response` 无 `fast_path`/`degraded` 键、`mode` 仍是请求值（`test_the_http_face_still_returns_200_shape…` 已钉死）、trace `max_tool_rounds` 仍是 3 而对话链快路径是 0 ⇒ 前端不读 trace 就分不出「这次没有工具轮」。degraded 只出现在事件里（`:466/:542/:528`）。至少 T11 写清；若愿 additive 补一枚布尔键更好（additive-only 允许）。
8. **m-8 keep_alive 工具轮只钉了 kwargs 面**：`test_tool_routing_turn_uses…` 断 `first["keep_alive"]`、`test_router_and_legacy_payloads_agree…` 断两腿相等（但那次是空 tools 的合成腿）；`requests[0].payload["keep_alive"]` 的绝对值面无钉（RAG/SSE 组各有一例可照抄）。合成/降级两腿的 keep_alive 都传了（`agent.py:199/233`），语义等价 ✓。
9. **m-9 `_classification_query` 是 `llm/_query_of` 的第二份实现**（`agent.py:243-254` vs `app/llm/__init__.py:382-395` 逐字同逻辑）；`complexity` 今天不参与打分（T3 移交），故只影响 trace 可读性。建议 T9 之后由 llm 包导出 `query_of` 收口，别长第三份。

---

## 5. 必查清单逐项结论

| # | 项 | 结论 | 证据（我跑出来的 / 文件:行号） |
|---|---|---|---|
| 1 | 偏离项：没复用 `_local_fast_path` | **接受偏离（Important 3 条尾巴）** | ①降级路径真跑：trace 行数 **1**、`response["trace_id"] == row["trace_id"]` **True**、账本 **1** 行、事件序 `user → model_route_downgrade → tool_start → tool_end → final → stage×10`（探针 P1）⇒ 「双 trace / 注记落错行」的前提成立。②行为面**部分不等价**：审计 `QUERY` 行字段与文案路（I-3）、`tool_time`/`llm_ms` 归因（I-2）、`retrieval query` 是否做上下文改写、typesafe `conflicting_evidence` 策略、对外 `mode`/`fast_path` 标记（m-7）五处有差；证据投递形状（system 段 `AUTHORIZED_ENTERPRISE_EVIDENCE=`、非 `role="tool"`）与 `ToolContext(mode="local")` 两笔审计是**同形**的。③「两套 fast-path」分叉风险**成立**，正式裁定见 §6。 |
| 2 | D2 语义 | **违反（C-1）**；`agent_local_fast_path` 未当闸门 = **不违反** | 不 500/503 + 答案仍交付：主降级门满足（`test_the_http_face_still_returns_200_shape…` 我复跑绿），但降级腿再抛 ⇒ 503 + 0 trace（C-1，两次实测）。`agent_local_fast_path` 在 `agent.py` **0 命中**、`config.py:129` 只声明、唯一消费者是 `conversation_agent.py:561` ⇒ 该键从来不管 `/api/agent/query`，D2 无条件降级不与既有语义冲突（但它让键名更误导，见 §7 第 2 项）。`AllCandidatesFailedError`/硬终态仍上抛 = 与 legacy 同宽，钉在两例（我复跑绿），不算违反 D2（D2 只管零候选）。 |
| 3 | tool_calls 标准化 | **PASS（+ I-4 一条下游缺口）** | router 腿的 `tool_calls` 唯一来源是 `LLMResponse.tool_calls`（`agent.py:266-273`），M4-rev 变异（改回读原始 JSON）**KILLED**：`8 failed / 34 passed`。`_tool_arguments` **保留论证成立**：legacy 腿 `httpx.post` 直接交回 provider 原始 message（`agent.py:167-170` 无 normalize），字符串参数确实存在；实现体一行未改（我对 `baseline-app/agent.py` 逐行取体比对，差异只有 `def` 的 `dict[str, Any]`→`Any`）。两腿同一次工具轮的决策**等价**（探针 P7：`model_decision`、`tool_start.arguments`=`{'query_preview': …}`、工具收到的 `(name,args,mode,kb,allowed,top_k,rerank)` 六元组、答案、`num_sources`、`sources` 键集合**逐项相同**）；唯一不对称 = 回放的 assistant `arguments` 在新腿是 dict、legacy 腿是原字符串（Ollama 原生要 dict ⇒ 新腿更正确，legacy 保持原样），记在 I-4。 |
| 4 | #17/#18 与 D6 | **PASS（Important 1 条 I-1）**；G 段表 **有 1 行错** | `attach_model_route` 在 `save_trace` **之前**（`agent.py:844-846`，源面等式钉在 `test_agent_contracts.py:187-189`，运行面由 `save_trace` spy 钉）；成功腿与主降级腿都挂（P1 True），**收尾降级腿不挂**（I-1，P3 False + G2 变异存活证明）；全链失败时**根本没有 trace 行**（PF 实测 0 行 / 账本 1 行 `success=0`），与 legacy 同形 ⇒ 不判 T8 缺陷，但必须进 T11 口径。legacy 报文对 `baseline-app/agent.py` **逐字节相同**（payload 块 + 前置 think/num_predict 三行亲验，新增只有 `if llm.router_enabled():` 那 4 行）。`grep -c httpx`=12 的二分：**代码 2 / 散文 10**；G 段 AST 五项正确、最后一行「5」错误（m-1）。 |
| 5 | 温度 / 参数等价 | **PASS** | `AGENT_LEGACY_TEMPERATURE=0.2` 有**三面调用面 kwargs 等式**（`assert_temperature` 断 `"temperature" in kwargs` + 三枚值等式，工具轮 / 无工具合成轮 / 降级 rag 轮各一）+ 一枚「默认值仍等于 0.2 所以 spy 才是承重」的反证例（`test_the_package_defaults_still_say_two…`，正是 T7 M3b 的教训形状）。逐轮开关两套 settings 三面钉（kwargs + 报文 + 改 settings 跟变）。`keep_alive` 两腿都传、报文面等式在合成腿（m-8 缺工具轮绝对值）。legacy 报文里 `0.2` 字面量未被常量替换 ✓。 |
| 6 | 既有断言被改动 | **PASS** | `test_feishu_identity_contract.py` **git diff 为空**（145d81cbb342 与 baseline-tests 同 sha 面）。`test_agent_contracts.py`：baseline 60 条 assert 行**全部仍在**、新增 23 条 ⇒ 零放宽；`test_agent_routing_contracts.py`：git diff 纯增（+31/-0）。`grant 计数=1` 的修法确在**产品侧**：`agent.py:386/452` 把 `grant_scope` 作参数传进降级函数，`ConversationScopeWiringTests::test_every_call_site_uses_the_grant_aware_entrypoint` 未改一字——我把降级腿改回自算（`effective_allowed_from_grant(user.grant)`）**复现 KILLED**（1 failed in 2.79s），证明报告那段「被既有测试抓到」名副其实。飞书桥语义面（同文件 785-833 的 narrowed/promoted/zero_scope 四例）复跑全绿。 |
| 7 | 既有能力面回归 | **PASS** | `ToolContextScopeGuardTests`（`test_feishu_identity_contract.py:893-916`）仍在且要求每个 `ToolContext(` 调用点写出 `allowed_knowledge_base_ids=`（新增降级腿满足）；空 whitelist fail-closed（`test_enterprise_search_denies_empty_grant_scope_instead_of_full_corpus`、`test_empty_allowed_whitelist_is_denied_not_full_corpus`）与 `resolve_requested(context.role, requested, allowed=context.allowed_knowledge_base_ids)` 正则钉均在；TypeSafe `should_judge`/`judge_candidates` 调用点在 `app/retrieval.py`（本轮 mtime 未进 T8 窗口、零改动）。抽跑：`test_feishu_identity_contract + test_rbac_contract + test_p16_review_regressions + test_typesafe_security_contract + test_typesafe_retrieval + test_typesafe_api_runtime + 两份 agent 契约` = **169 passed / 0 failed / 181 subtests**（134.79s）。 |
| 8 | 报告可信度 | **基本诚实；3 处数字错（m-1/m-3/m-5）** | 我独立复现 4 发（报告表 9 发）：M2 needs_tools 写死 False ⇒ **KILLED**（2 failed：`AgentRouterMigrationTests` + `AgentModelRouteTraceTests`）；M3 不捕 NoCapable ⇒ **KILLED**（5 failed，全在 `AgentNoCapableFastPathTests`）；M4 tool_calls 退回手写 ⇒ **KILLED**（8 failed）；G1 降级腿重复解析 grant ⇒ **KILLED**（既有例，非新写）。每发**发内字节还原**、sha1 回到 `9760d3509ed5`、`compile()` 通过。`app/llm/*` 十一枚 + `rag.py`/`conversation_agent.py`/`agent_routes.py`/`agent_trace.py`/`security.py`/`main.py`/`knowledge_os.py`/`conftest.py`/`test_llm_usage_contract.py`/`test_p17_streaming_contract.py` 对 `snap-task7/` **逐枚 identical**；`config/llm_registry.json`=`3e652e9cf496`（未改，tools 旗标声明值亲验）。真实库只读：`llm_request_logs=0 / conversations=7 / messages=10` ✓。**改动面自述精确**：对 `baseline-app/agent.py` 我算出 `+458 / −9`（422→871 行），那 9 枚被删行与报告 A 段逐枚列出的一份不差 ⇒ 「非注释 +360/−8」这类自述可信。**反向发现**：报告没测的那些（C-1、I-1 收尾腿、I-2 stage 归因、I-3 DENIED 文案路）确实一枚钉都没有——「9 发全 KILLED」是真的，但**发数不足以覆盖降级腿的二阶路径**。 |

---

## 6. 「两套 fast-path」正式裁定 + 统一口径（供 ledger / T11）

**裁定**：**接受偏离**。`app/agent.py::_degrade_to_local_fast_path` 与 `app/conversation_agent.py::_local_fast_path` **不是**两条产品策略，而是「同一条 D2 义务的两个入口变体」：**`_local_fast_path` 是这条能力的唯一权威实现（semantics owner）**，`_degrade_to_local_fast_path` 是它在 `run_agent` 既有 `trace_id` / 事件流 / 证据去重表里的**就地变体**。brief 那句「复用现 local 模式分支」自本裁定起按「**复用其语义与机器件，不复用其函数调用**」解读；直接调用被禁止，因为它自带 `new_trace_id()` + `save_trace()` + `mode="local"` 响应体，会一次提问落两行 trace 并把唯一解释出口写到响应 `trace_id` 指不到的行（该前提已被我实测证实：就地降级 = 1 行 trace + trace_id 自洽）。`conversation_agent.py` 本轮禁改，也无法给它加 `degraded_note` 入参。

**统一口径（六项，T11 验收文档 + 两处 docstring 互点名，本表就是清单正文）**：
1. 工具执行权在后端：`tool_registry.execute("enterprise_search", …, ToolContext(mode="local", allowed_knowledge_base_ids=<本请求已解析一次的 grant_scope>))`；web 证据**按构造**拿不到。
2. 审计成对：`TOOL_CALL` + `TOOL_RESULT`，`detail` 带 `trace_id=` 与 `degraded=true`（agent 面）/ `fast_path=true`（对话面），且**必须有 `QUERY` 收尾行**（C-1 修完即成立）。
3. 证据投递：`AUTHORIZED_ENTERPRISE_EVIDENCE=` 走 **system 段**，不用 `role="tool"`（降级轮没有 assistant 的 tool_calls 前置）。
4. 温度：各链用自己的命名常量，两腿同值（agent = `AGENT_LEGACY_TEMPERATURE` 0.2，对话 = `CONVERSATION_LEGACY_TEMPERATURE` 0.2，**都不是** rag 的 0.1）。
5. 计时归因：检索耗时归 retrieval/`tool_time`，**不得**并进 `llm_ms`/`generation` stage（I-2 修完即对齐）。
6. 文案短路：`DENIED` / 检索失败 / 零证据 三支走同源硬文案且**零外呼**（I-3 修完即对齐）；降级腿自己再遇零候选时给收尾中文文案、**绝不 503**（C-1）。

**收口时机（本版不重构）**：`conversation_agent.py` 本版禁改 ⇒ 六项里 1/2/3/4 现在已一致，5/6 由 I-2/I-3 在 T8 修复轮补齐。真正的**代码级**统一放在「下一稳定版删 legacy」那一轮（与 D6 豁免表删除同一批）：把无工具快路径抽成 `app/fast_path.py`（或让 `_local_fast_path` 接受 `trace_id=` / `on_event=` / `save=callback` 注入），两条链共用；在此之前**不许**出现第三处「无工具直执行企业检索」。守卫建议交 T9：`record_event(... action="TOOL_CALL" ...)` 中 `enterprise_search` 的调用点计数上限 = 2（工具回路 + 降级腿），与既有 `AgentToolRoutingAfterMigrationTest::test_degradation_keeps_the_audit_pair_and_adds_no_new_egress` 同形。

---

## 7. 对 4 项「待用户裁决」的技术意见（不替用户决定）

1. **V2.3 出厂形态是否接受 agent 工具链 100% 走 D2？** —— **技术上同意接受**（翻 `capabilities.tools` 旗标 = 注册表说谎，直接违反 §3 的能力旗标冻结与 §5 的 capability>preference；ledger 第 30 行 T3 已裁「fast-path 常驻为 D2 设计前提」，本轮只是把它从「推测」升成「链级事实」并钉进测试）。**但附三条前置条件**：① C-1 / I-1 / I-2 / I-3 先修——出厂唯一路径不该留着 503、无钉的 trace 缺口、虚高一整次检索的生成耗时和 RBAC 文案短路缺失；② 出厂态必须让运维**一眼可见**（T11 文档 + 建议在 `/api/system/status` 或 trace 顶层给一枚「agent 工具链 = D2 常驻」的可读事实，而不是要求人翻 `model_route_downgrade` 事件）；③ **必须把新证据摆回桌面**：实现者给的替代方案 ①「给 `openai` 配 key」**目前并不能让工具轮可用**（I-4：第二轮回放的 `arguments` 是 dict、工具回执缺 `tool_call_id`，真连必 400）。所以用户的真实选项是三条而非两条：**(a)** 接受常驻 D2（推荐，配合上面三条）；**(b)** 新增一条指向官方支持 tools 且本机跑得动的模型的注册表条目（纯本地，今天就能用，但需先验证它真能稳定产出 `tool_calls`）；**(c)** 等 T9 补 OpenAI 侧多轮回射映射后再配 key（此时 (a) 只是过渡态）。
2. **`agent_local_fast_path=false` 时零候选该不该报错？** —— **反对把它当闸门**。D2 冻结「Agent 捕获 → 降级、不得 500」；做成闸门等于允许运维一键把「不得 500」变成 500，spec 与配置互相打架，且与 T3 裁定（fast-path 常驻是**设计前提**）冲突。本版正确动作只有两件事：在 T11/`.env.example` 写明「该键只作用于对话链的 local 模式」；若确实需要「关掉快路径就要看到错误」的运维语义，**下一版加一枚显式新策略键**（例如 `agent_zero_candidate_policy=degrade|error`）而不是挪用旧键的语义。
3. **§9.1 措辞回写** —— **同意，且此事已闭环**：`docs/MODEL_ROUTER_V23_DESIGN.md:93` 的「Task 8 补正」段就是主 agent 已下的裁定（ledger 第 67 行），措辞与我实测一致——我另对 `baseline-app/agent.py` 亲验 legacy payload 块与 think/num_predict 前置三行**逐字节未改**，所以「agent 链两条腿都有 legacy 形态」这句话现在是**有报文证据的**。T11 只需引用，不必再议。
4. **`model_used` 取值来源改为 selected 生效模型名** —— **同意登记一句**（字段名/类型没变、值集合与迁移前一致，属 §9 additive-only + T4 移交 M2 的既定义务，且已有等式钉：`result["model_used"] == 账本 model 列`）。但请在 T11 写成「**与账本 `model` 列同源，唯一例外 = 工具轮次耗尽后的 D2 降级腿**（I-1 修完该例外消失）」，别写「永远同源」——那是我实测出来的例外（P3：该腿 `model_used` 回落 `settings.ollama_model`，本环境恰好同名所以不显眼）。若前端 TraceView/文案侧不读该字段则无需改前端。

---

## 8. 移交 T9 / T10 / T11 的强制口径（编号可照做）

**T9（矩阵收口 + 单一出口守卫）**
1. `agent.py` 的 D6 豁免行**只抄代码面五项**：`import httpx` 1、`httpx.post(` 1、`/api/chat` 字面量 1、`ollama_base_url` 读 1、`httpx.stream|Client|get` 0；全文行数是 **12 行**（子串 14 次），**不要**抄报告 G 段的「5」。等式已由 `AgentLegacyBranchTests::test_d6_exemption_inventory_for_agent_py` 钉住。
2. 矩阵 #12/#13 补「**多轮回放**」半段：agent 工具轮第二轮把 assistant `tool_calls` + 工具回执回放给 OpenAI 兼容 provider ⇒ 出口 `arguments` 必须为 JSON **字符串**、回执必须带 `tool_call_id`。今天写出来会红（I-4，P8 已证），修点在 `app/llm/normalize.py::openai_payload`（T9 有权改 llm 层；本轮不行）。
3. 复核 T8 修复轮的三枚新钉是否落地：C-1（降级腿再抛 ⇒ 200 + 两枚注记 + `QUERY` 行）、I-1（收尾腿九键）、I-2（`generation` stage 不含检索耗时）。并把我那发 **G2 反向变异**（删 `outcomes.extend`）收进常备变异表——它现在存活。
4. #17 的「失败路」口径写清：agent 链全链失败时**没有 trace 行**、只有账本行（PF 实测 `trace=0 / ledger=[(agent, success=0, retryable, -1)]`），legacy 同形 ⇒ 不许为它挪 `save_trace`，除非 T9 判定新增「失败也落 trace」的义务（那是新 spec）。
5. 「两套 fast-path 统一口径」六项清单（本文 §6）与「`enterprise_search` 的 `TOOL_CALL` 调用点上限 = 2」守卫一并纳入 §8.1/矩阵文档化行。

**T10（真实 failover）**
6. 默认无 key 环境 `/api/agent/query` **不会**产生任何 tools 外呼（实测：1 次 rag 画像请求、`enterprise_search` 由后端直接执行），真实 failover 继续走 `/api/query/stream` 或显式给 key；**给 key 之前先确认第 2 条已修**，否则工具轮第二轮会拿 400。trace 里看到 `model_route_downgrade` 是**正常**（出厂常驻形态），不要判成故障。

**T11（验收文档 / Quality Gate）**
7. 报告已给的四句照写（出厂无 key ⇒ 常驻 fast path；`LLM_ROUTER_ENABLED=false` 对 agent 链是完整 legacy、对对话链只是非流式腿；零候选不产账行、归因看 `model_route_downgrade`；`model_used` 语义改为 selected 生效名）。
8. 追加两句：①「`model_used` 与账本同源，例外 = 收尾腿降级（I-1 修后消失）」；②「C-1 修复前后 `agent_local_fast_path` 与 agent 链的关系：该键**不**门控 agent 链的 D2 降级」（§7 第 2 项）。
9. 把「`backend/data/audit.jsonl` 仍被既有测试追加（非 T8 引入）」列进 Enterprise Quality Gate 待办（m-4），别当已验收项。

---

## 9. 我实际执行的命令与关键输出

```
# sha1（我亲算，12 位前缀；全部与 §0 / snap-task8 一致）
app/agent.py                      9760d3509ed5   41569 B   871 行全 CRLF、bare_lf=0、AST 通过
app/llm/fallback.py               008d8213bc05   48518 B   （snap-task7 identical）
app/llm/{__init__,classifier,errors,health,models,normalize,provider,registry,router,usage}  全部与 snap-task7 identical
app/rag.py a5a638716947 | app/conversation_agent.py 0ffcc353eb59 | app/agent_routes.py 1080fbd4a0c4
app/agent_trace.py d17a0bf266f1 | app/security.py d36b387aac6e | app/main.py bc0281dcfc42
app/knowledge_os.py c92ba3364a3e | app/conversation_stream_routes.py c5cb5f9a6dde | tests/conftest.py 73d1060de465
config/llm_registry.json          3e652e9cf496
tests/test_model_router_v23_contract.py  e9ab22d34cfb（对 snap-task7 的 5dac328f8736 是唯一 DIFFERS 的测试件）
tests/test_agent_contracts.py     5a59795bf897 | tests/test_agent_routing_contracts.py 0f9f293daefb
tests/test_feishu_identity_contract.py 145d81cbb342（git diff 为空）
snap-task8/ 28 份文件 = 工作树逐枚 identical；snap-task7/ 无 app/agent.py（实现者「基线取 baseline-app」的前提成立）

# 定向门（cwd=backend）
python -m pytest tests/test_agent_contracts.py tests/test_agent_routing_contracts.py \
       tests/test_model_router_v23_contract.py -q
  -> 386 passed / 0 failed / 353 subtests in 69.06s        （与报告一致）
python -m pytest tests/test_feishu_identity_contract.py tests/test_rbac_contract.py \
       tests/test_p16_review_regressions.py tests/test_typesafe_security_contract.py \
       tests/test_typesafe_retrieval.py tests/test_typesafe_api_runtime.py \
       tests/test_agent_contracts.py tests/test_agent_routing_contracts.py -q -p no:warnings
  -> 169 passed / 0 failed / 181 subtests in 134.79s
python -m pytest tests --collect-only -q  -> 882 tests collected（报告写 881：差 1 例，见 m-3）

# 变异（字节读/字节替换/字节写 + 发内还原 + sha1 核对 + compile()）
rev8_mutations.py   起点 sha1=9760d3509ed5
  M2-rev needs_tools 写死 False           KILLED   2 failed / 40 passed   还原 9760d3509ed5 OK
  M3-rev 工具轮不捕 NoCapableModelError    KILLED   5 failed / 37 passed   还原 9760d3509ed5 OK
  M4-rev tool_calls 退回手写原始 JSON      KILLED   8 failed / 34 passed   还原 9760d3509ed5 OK
rev8_mutations2.py
  G1 降级腿自己再解析 grant（既有例）      KILLED   1 failed in 2.79s     还原 OK 字节等值 True
  G2 删 limit 腿 outcomes.extend          **SURVIVED** 42 passed          还原 OK 字节等值 True   => I-1 缺钉证明

# httpx 命中二分（tokenize + AST 双口径）
grep -c httpx app/agent.py = 12 行 / 子串 14 次
  代码 2：:27 import httpx  :161 response = httpx.post(
  散文 10：注释 11,13,15,20,24,71,600 + docstring 121,215,282
  /api/chat 字符串字面量 1（:162）；ollama_base_url 属性读 1（:162）；httpx.stream|Client|get 0

# legacy 报文逐字对照 baseline-app/agent.py
payload 块（`payload: dict[str, Any] = {` → `return message`）identical = True
前置 `routing_turn/think/num_predict` 三行 identical = True（新增只有 `if llm.router_enabled():` 那 4 行）
`_tool_arguments` 实现体 identical = True（唯一差异 = def 行的注解）
窗口 delta 复算：baseline-app 422 行 → 871 行，**+458 / −9**（与报告 A 段逐枚一致；被删的 9 行 = 报告点名的 8 项 + typing 后那枚空行）
注意：`git diff HEAD -- backend/app/agent.py` 给出的是 536/27，**不能**当 T8 窗口用——HEAD 版 agent.py
= `1a0d87f1a842`（13850 B）≠ T1 起点 `baseline-app/agent.py` = `419fa63f4c0d`（17497 B）。
⇒ T7 移交的「routes 层 delta 只能靠 mtime 归因」这一条在 T8 已由 baseline-app + snap-task8 双基线解决。

# 自建探针（rev8_probes.py / rev8_probe2.py / rev8_probe3.py / rev8_probe4.py；全 MockTransport 或 httpx.post 替身，11434 一次未打）
P1 降级路径：trace 行数 1 | response.trace_id == row.trace_id True | 账本 1 行 | model_route 已挂 | 事件序完整
P2 llm_ms 归因：normal elapsed=449.15 sum_tool=402.6 generation=46.5  vs  degrade elapsed=426.22 sum_tool=400.8 generation=426.2   => I-2
P3 limit 腿降级：answer 正常 | 账本 1 行 route_mode=rag | **model_route 未挂** | model_used 回落 settings.ollama_model  => I-1
P4 DENIED：仍发 1 次生成、AUTHORIZED_ENTERPRISE_EVIDENCE=[]、num_sources=0                                        => I-3
P5 `agent_local_fast_path` 在 agent.py 命中 0；config.py:129 声明；conversation_agent.py 唯一消费者 :561
P6 降级追加段：无 role/授权 KB 行（首段 system 已有）、无 conflicting_evidence 策略、无 history 不可覆盖提示
P7 两腿等价（同一次工具轮）：model_decision / tool_start 脱敏 / 工具六元组 / 答案 / sources 键集合 **逐项相同**；
   唯一不对称 = 回放 assistant 的 arguments 新腿 dict vs legacy 腿 JSON 字符串
P8 有 key + openai 兼容条目：第二轮回放 arguments 为 **dict**、无 tool_call_id ⇒ OpenAI 协议不合形（真连必 400）   => I-4
PF 全链失败：trace 行 0 / 账本 1 行 (agent, success=0, retryable, fallback_index=-1)
C-1 复现（两次）：4 条 ~3600 字证据（无历史）或 8×4000 字历史 ⇒ NoCapableModelError(stage="context") 逃出 run_agent
   ⇒ /api/agent/query 503 | trace 0 行 | 账本 0 行 | 审计只有 TOOL_CALL+TOOL_RESULT（无 QUERY）
```

**硬约束自证**：`backend/`、`frontend/` 零修改（变异全部发内还原、终态 sha1 `9760d3509ed5` 复算一致；我写的 4 个探针 + 2 个变异脚本全部在 `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/` 下、前缀 `rev8_`）；零 git 写（只跑 `git status/diff/log`，无 add/commit/checkout）；零真实外呼（`OLLAMA_URL=http://ollama.test:11434`、`OPENAI_URL=https://api.openai.test/v1`、legacy 腿 `httpx.post` 被替身接管，11434 一次都没打）；spec 未放宽（本文所有修法都是「改实现以合 spec」方向）。

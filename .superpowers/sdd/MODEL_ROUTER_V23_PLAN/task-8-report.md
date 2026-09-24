# Task 8 报告 — Agent 工具回路迁入 `app.llm`（§9 第三条）+ D2 零候选降级 + trace 的 `model_route`

## 状态

**完成**。两道验收门都绿：

| 门 | 命令（cwd=`backend/`） | 结果 |
| --- | --- | --- |
| 1 定向 | `pytest tests/test_agent_contracts.py tests/test_agent_routing_contracts.py tests/test_model_router_v23_contract.py -q` | **386 passed / 0 failed / 353 subtests**（68.52s） |
| 2 全套件 | `pytest tests -q` | ~~**881 passed**~~ ⇒ **更正（m-3）**：881 是**倒数第二个字节集**上跑出来的数；主 agent 复跑终态 = **882 passed / 0 failed / 881 subtests**（= 基线 837 + **45** 例，本报告当时把 +44 写成了 delta）。修复轮 1 之后 = **889 / 0 / 889**，见文末「修复轮 1」段 |
| 3 变异 | `t8_mutations.py`（字节安全，发内还原 + sha1 核对） | **9 发全 RED，存活 0**（表见 F 段）；**但发数不足以覆盖降级腿的二阶路径**（评审 C-1/I-1 两条缺口当时零钉，见修复轮 1） |
| 4 约束 | `app/llm/*` 零改动、`config/llm_registry.json` 零改动、零真实外呼 | ✓ 见 A/H 段 sha1 表 |

中途一次真实回退被**既有**契约测试抓到（不是新写的例）：`test_feishu_identity_contract.py::test_every_call_site_uses_the_grant_aware_entrypoint`
钉「`effective_allowed_from_grant(user.grant)` 在 `agent.py` 里计数 **= 1**（热路径每请求只解析一次）」，
我的降级腿本来又算了一遍 ⇒ 计数 2 ⇒ 那一条**全套件唯一的一次红**。修法是把 `run_agent` 顶部已算好的
`grant_scope` 作参数传进降级函数（而不是放宽那枚等式）。修后该文件 142 passed。

---

## 交付文件（改动面 = **本任务窗口**）

本任务的窗口起点 = **工作树现状**（T1–T7 已完成并复审放行）。`snap-task7/` 里**没有** `app/agent.py`
（它只纳管了 `agent_routes.py` / `agent_trace.py` / `conversation_agent.py` / `conversation_stream_routes.py`
/ `knowledge_os.py` / `llm/` / `main.py` / `rag.py` / `security.py` + 四份测试），所以 agent.py 的**基线**取
`MODEL_ROUTER_V23_PLAN/baseline-app/agent.py`，并**已核实它就是 T8 起点**：那份里 `attach_model_route`
命中数 = 0（T5 只建接缝、未接调用点），且 T1–T7 的 Files 清单都没碰过本文件。
按 T7 评审移交项「快照只增不改名」，请主 agent 另存 **`snap-task8/`**（含 `app/agent.py` +
`app/agent_routes.py` + 本轮三份测试）作为评审基线，别覆盖 `snap-task7/`。

### A. 产品代码（1 个文件）

| 文件 | 行尾 | 字节 | sha1(12) | 相对窗口起点的 delta |
| --- | --- | --- | --- | --- |
| `backend/app/agent.py` | CRLF（原生，未翻转：871 行全 CRLF、`bare_lf=0`） | 41,569 | `9760d3509ed5` | **+458 / −9 行**；非注释 **+360 / −8**，纯注释/文档 **+66** |

> **修复轮 1 之后本行失效**：`agent.py` 现为 **1000 行全 CRLF / `bare_lf`=0 / 50,371 B / sha1 `59d4cd3b3c3b`**，
> 相对本表起点 `9760d3509ed5` 的 delta 是 **+137 / −9 行**（非注释 +91 / −7）。逐条改动与验收见文末「修复轮 1」段。

被改动的**既有非注释行**一共只有这 8 行（其余全是新增），逐条理由：

1. `from typing import Any, Literal` → `…, NamedTuple`（`RouteOutcome` 用）。
2. `from app.agent_trace import new_trace_id, …` → 加 `attach_model_route`（#17 的唯一挂载点）。
3. `def _ollama_chat(messages, tools)` → `def _ollama_chat(messages, tools, *, trace_id=None, route_out=None)`
   （**两枚都是关键字-only 且带默认值** ⇒ `conversation_agent` 的 legacy 腿与 `scripts/*` 的两参调用照旧）。
4. `def _tool_arguments(call: dict[str, Any])` → `(call: Any)`（它现在吃两种形状；实现体一行未改，见 C 段）。
5. `message = _ollama_chat(messages, schemas)` → 外面套 `try/except NoCapableModelError` + 传 `trace_id`/`route_out`。
6. `message = _ollama_chat(messages, [])`（工具轮次耗尽的收尾腿）→ 同样套上第二处 catch。
7. `final_answer = str(message.get("content") or "").strip()`（收尾腿里那一句）→ 挪进 `else:` 成功支（异常支由降级出口赋值）。
8. `"model_used": settings.ollama_model` → `"model_used": model_used`（§9 + T4 移交 M2：**selected 候选的生效模型名**；
   没经过路由时回落到 `settings.ollama_model`，取值集合与迁移前一致）。

**新增**：`AGENT_LEGACY_TEMPERATURE`、`_FAST_PATH_DEGRADE_PROMPT`、`RouteOutcome`、`_chat_via_router`、
`_synthesize_without_tools`、`_classification_query`、`_message_from_response`、`_no_capable_event`、
`_degrade_to_local_fast_path` + `run_agent` 顶部的 D6 豁免说明段。

### B. 测试（3 个文件）

| 文件 | 行尾 | sha1(12) | 新增 |
| --- | --- | --- | --- |
| `backend/tests/test_model_router_v23_contract.py` | LF（原生，7,148 行） | `e9ab22d34cfb` | Task 8 段 **38 例 / 8 个类**（m-3 更正：本报告原写 37；F 组 `AgentLegacyBranchTests` 实为 **5** 例而组表写 4）+ `agent_entry` / `ollama_tool_body` / `_RecordingToolExecutor` / `_AgentMigrationFixture` 底座；import 补 `hashlib` / `inspect` / `HTTPException` |
| `backend/tests/test_agent_contracts.py` | CRLF | `5a59795bf897` | `AgentRouterMigrationContractTest` **4 例**（源面契约） |
| `backend/tests/test_agent_routing_contracts.py` | CRLF | `0f9f293daefb` | `AgentToolRoutingAfterMigrationTest` **3 例**（源面契约） |

### C. 计划目录工件（不进产品树）

`t8_mutations.py`（字节安全变异台，argv 可选子集 + `PYTHONIOENCODING` 复原）、
`t8_mutations.log` / `t8_mutations_r2.log` / `t8_mutations_final.log`（**对最终字节重跑的那一份才是终值**）、
本报告。

---

## 迁移形状（任务书 A/B/C 的落点）

**A. `_ollama_chat` 两条出口，返回形状不变**

```
_ollama_chat(messages, tools, *, trace_id=None, route_out=None)
  routing_turn = bool(tools)                     ← 既有契约钉子（p16 组）逐字保留
  think / num_predict 在**分支之前**各算一次     ← 两条出口吃同一对值
  if llm.router_enabled(): return _chat_via_router(...)   # llm.complete(mode="agent", needs_tools=bool(tools))
  else: 原 httpx.post 报文（一条字节没改，含 `"temperature": 0.2` 字面量、空 tools 也带键、
        `message` 缺失时同一句 `RuntimeError("Ollama 返回缺少 message")`）
```

- 逐轮开关的两种轮次各自有钉：`AgentPerTurnSwitchTests`（工具轮 think=True/num_predict=768，
  无工具轮 think=False/512，两面上都钉：kwargs + 报文 `options`），外加
  `test_the_switch_follows_settings_not_a_hardcoded_pair`（改 settings ⇒ 两轮报文跟着变）。
- **`route_out` 盒子**取代「返回二元组」：`_ollama_chat` 对外仍只交回 message dict
  （pre-flight 冻结的「循环体零改」），`FallbackResult` + 本次画像另走这只 list。
- 一个**必须写下来的事实**（我一开始就把它当反例钉住了）：`run_agent` 的循环**每一轮都带 schema**
  （`_ollama_chat(messages, schemas)`），所以「工具轮 vs 合成轮」的分界**不在轮次**，而在
  **`tools` 是否为空**：空 tools 的那一次只出现在 ①工具轮次耗尽的收尾腿（`for…else`）与
  ②对话链的 legacy buffered 腿。`agent_think_synthesis` / `agent_num_predict_synthesis` 的唯一消费点
  因此是 ①（+ ②），已按这个事实写成 `AgentToolsFreeSynthesis` 系列例名。

**B. 温度（§9.1 + T7 的 M3b 教训）**

- 本链命名常量 `AGENT_LEGACY_TEMPERATURE = 0.2`，出处 = `baseline-app/agent.py:65` 的
  `"options": {"temperature": 0.2}`；**不**依赖 `LLMRequest.temperature` 的字段默认、也**不**依赖
  `llm.complete(temperature=…)` 的形参默认（两者都是 0.2，`test_the_package_defaults_still_say_two_
  so_the_kwargs_spy_is_load_bearing` 把这件事本身钉成了例）。
- 三面各自钉「调用面 kwargs 等式 + 报文面等式」：
  ①工具轮 `AgentTemperatureEquivalenceTests.test_tool_turn_temperature_is_on_both_faces`
  ②无工具合成轮 `test_tools_free_synthesis_leg_temperature_is_on_both_faces`
  ③D2 降级腿（`mode="rag"`）`AgentTemperatureEquivalenceTests::test_degraded_synthesis_leg_temperature_is_on_both_faces`
  （m-5 更正：本报告原把它写成「`AgentNoCapableFastPathTests` 里的那一枚」，位置错）。
- 与 `rag.py` 的 0.1 无关：三枚 `assertNotEqual(RAG_CHAIN_TEMPERATURE, …)`；legacy 报文里的 `0.2`
  字面量**没被常量替换**（#18 的对照物要求逐字节可对照，rag.py 的 T6 先例同此）。

**C. `tool_calls` 标准化 + `_tool_arguments` 的**留**（grep 结论）**

- 全仓 grep：`_tool_arguments` 只有 `agent.py` 的两处消费点（`run_agent` 循环内）+ `normalize.py:142`
  与 `test_model_router_v23_contract.py` 的**注释**引用；**没有任何测试直接调它**。
- 决定：**留**，但职责改写。理由（写进函数 docstring，并有三例钉）：
  1. **router 腿**吃 `_message_from_response` 回填的 dict，`arguments` 已是 dict（§6 的 `ToolCall`）；
  2. **legacy 腿**吃 provider 原始 message，`arguments` 可能仍是 **JSON 字符串**，
     那段 `json.loads` + 「坏 JSON/非对象 ⇒ `{}`」的退化口径就是它**原来挡的东西**：
     半截 JSON 不该把整条 agent 链变成 503；
  3. 解析职责已**上移**到 `normalize._arguments`（新链路的唯一解析点），本函数只剩「取值 + 兼容 legacy 形状」，
     下一稳定版随 legacy 分支一起瘦身。
- 「标准化退回手写路径」那条变异的落点：`LLMResponse` 里**没有**原始 JSON，所以
  `_message_from_response` 只能读 `response.tool_calls`；`AgentToolCallStandardisationTests` 三例
  （字符串参数→dict 端到端、回放消息形状、`ToolCall` 直喂）+ 一例 `_tool_arguments` 双形状对照。

**D. D2 零候选降级**

- `except NoCapableModelError` **两处**：工具回路那一轮、以及工具轮次耗尽后的收尾腿（同一枚义务的第二处落点）。
- 出口 = 等价 local fast-path：**后端直接执行 `enterprise_search`**（`ToolContext(mode="local")` ⇒
  web 证据按构造拿不到）+ 一次 **`mode="rag"`** 的 tools-free 合成（`_synthesize_without_tools`）。
  为什么降级腿不能用 `mode="agent"`：§5 的 `CAPABILITY_BY_MODE["agent"] = "tools"`，
  同一个画像重发只会再抛同一个异常（注释里写明了）。
- **零候选那次不产账行**（T5 裁定），所以 trace 上那条 `NO_CAPABLE_MODEL→fast_path` 是**唯一**解释出口：
  `model_route_downgrade` 事件（`note` / `reason_codes`(含 NO_CAPABLE_MODEL) / `stage` / `action="fast_path"` /
  画像摘要，零请求内容）。它**不是** `model_route` 对象——`plan()` 阶段就抛了，没有 `RoutePlan`，
  而九键的唯一生产者 `usage.model_route_trace()` 要求 `RoutePlan` 入参；凭空造第二份就是第二个生产者。
- `AllCandidatesFailedError` / 硬终态 `LLMError` **不在本文件 catch**：现网（legacy httpx 路）provider
  报错同样是异常上抛 → `agent_routes.py` 的 `HTTPException(503, "Agent 服务不可用：…")`。
  两例钉（`test_all_candidates_failed_still_propagates_to_the_route_fallback_copy` 连 HTTP 面那句前缀一起钉、
  `test_hard_terminal_llm_error_is_not_converted_into_a_fast_path` 钉「没降级就不会执行后端检索」）。
- 一次提问**只落一行 trace**：`response["trace_id"] == 落盘行的 trace_id`，注记就在同一行里。

**E. #17 的集成半段（agent 链**有** trace）**

`run_agent` 收尾：`attach_model_route(trace, outcome.result.plan, outcome.result, profile=outcome.profile)`
→ **在 `save_trace` 之前**（顺序事实被 `assertLess(index(attach…), index(save_trace))` 钉住）。
`AgentModelRouteTraceTests` 四例：九键齐备（含 `stage="primary"` / `selected_index=0` / `attempts` 非空且
`result="success"`）、JSONL 读回等价（`get_trace()` 与磁盘行逐项相等）、`model_route` 对象序列化后
prompt/canary/证据正文/system prompt/用户名 0 命中 + 账本禁存项、`LLM_ROUTER_ENABLED=false` 时
**不挂** `model_route`（trace 形状与迁移前逐字相同）。

---

## 本环境的 agent 工具能力面（TypeSafe 终审留给 T8 核实的那条风险）

**实测（真注册表文件 + 真 `load_registry` 的 D1 折叠 + 真 `plan()`，纯内存、零外呼）**：

```
无 key（本机现状：OPENAI_API_KEY 为空）
  enabled ∧ tools=true 的条目：[]                      ← 没有任何支持 tools 的候选
  plan(mode=agent, needs_tools=True)  → NoCapableModelError(stage="capability", codes=("NO_CAPABLE_MODEL",))
  plan(mode=agent, needs_tools=False) → 同上（agent 画像**恒**要求 caps.tools）
  ⇒ 今天每一次 /api/agent/query（auto/web/local 三档都一样）都走 D2 fast path。
有 key（OPENAI_API_KEY 非空）
  openai: enabled=True, tools=True, priority.tools=100
  plan(agent) → primary=openai(score=100)，**fallbacks=[]**，reason=('CAPABILITY_MATCH',)
  （deepseek-chat / qwen-plus 仍 enabled=False：它们的 key 也是空的）
```

**结论与后果（写给 T9/T10/T11 与运维）**：

1. 「fast-path 是常驻分支」不是猜测，T3 移交的那句话在本轮被**升级成链级事实**：
   `AgentNoCapableFastPathTests.test_shipped_registry_without_keys_offers_no_tools_capable_candidate`
   用真文件钉住「无 tools-capable 条目 + `plan()` 抛 `stage="capability"`」，另外三例钉「HTTP 面不炸、
   工具 schema 一次都没发出去、账本只有一行（零候选那次没有行）」。
2. **云 key 到位后的 fallback 链形状 = 单候选、无兜底**：只有 `openai` 一条 tools 候选，
   `deepseek-chat` / `qwen-plus` 的 `DEEPSEEK_API_KEY` / `QWEN_API_KEY` 也为空 ⇒ 工具轮**没有第二跳**。
   要拿到「429/500 → fallback」的形状，得同时给第二把 key（`tools` 档 90/80 会排成有序 fallbacks）。
   矩阵 #4/#5 的形状在 mock 层已由 T4 覆盖，这里只是把「真实配置下的链长度」说清。
3. **我没有为了让工具轮"看起来能用"去翻注册表旗标**（见「待用户裁决项」1）。
4. `model_used` 在降级路径上取的是**合成腿 selected 候选**的生效模型名（`ornith-1.5:9b-text`），
   与账本 `model` 列同源（等式例：`test_trace_carries_route_and_the_response_face_is_additive_only`）。
   `trace["model"]` 仍是 `settings.ollama_model`——与 T7 的对话链同一口径，不改。

---

## 被改动的既有断言逐条清单（原来挡什么 → 现在挡什么）

**结论：两份契约测试文件的既有 11 例（148 行那份 7 + 4 语言例；37 行那份 4 例）**一条都没放宽、
也没一条需要改**——迁移后的 `agent.py` 仍逐字包含它们点名的形状。逐条核过：

| 既有断言 | 原来挡什么 | 迁移后为什么仍成立（谁在钉它） |
| --- | --- | --- |
| `agent_max_tool_rounds: int = Field(default=3, ge=1, le=3)` | 工具轮次上限不外扩 | 未碰 config；`AgentPerTurnSwitch` 用 max_rounds=1 走收尾腿时仍受这条约束 |
| `for round_index in range(1, max_rounds + 1)` | 循环有界 | **逐字未改**（D2 的 catch 在循环体内，`break` 收尾） |
| `Tool-call limit reached` | 轮次耗尽后必须显式收口 | 未改；收尾腿另有第二处 D2 catch |
| `"think": bool(think)` | think 必须是布尔而不是 None 传给 Ollama | legacy 报文里逐字未改；router 腿由 `think=bool(think)` 保证同形（两面都有例） |
| `messages.append(message)` | 决策轮要回放进上下文 | 未改；`test_the_echoed_assistant_message_carries_the_standardised_shape` 直接读**第二轮的真实请求体** |
| `assertNotIn("reasoning_content" / '"thinking"', agent_trace.py)` | 隐藏推理不落盘 | 未碰 agent_trace；router 腿的 `LLMResponse` 根本没有该字段 |
| `'"keep_alive": settings.ollama_keep_alive'` / `'"num_predict": int(num_predict)'` / `routing_turn = bool(tools)` | 本地模型常驻 + 合成段有界 + 逐轮开关的唯一判据 | 三枚字面量都留在 legacy 报文里；逐轮开关另加 3 例（kwargs 面 + 报文面 + 改 settings 面） |
| `return normalized[-limit:]` | 历史条数有界 | 未碰 `_conversation_history` |
| `agent_local_fast_path: bool = True`（config 面） | 本地快路径存在 | 未碰 config；D2 的降级语义另见「待裁决项」2 |
| `mode == "local" and settings.agent_local_fast_path` / `"fast_path": True` / `"llm_calls": llm_calls` / `tool_registry.execute` / `selected_knowledge_base_id=knowledge_base_id`（对话链那五枚） | 对话链快路径形状 | **归 T7 的文件，本任务一字未改**；`test_conversation_context_is_bounded_and_local_mode_has_fast_path` 仍绿 |
| 语言约束 4 例（`ALWAYS written in Simplified Chinese` / 中文硬约束 / `REFUSAL_PHRASE` / `[1]`） | 面向用户答案锁中文 | `AGENT_SYSTEM_PROMPT` 未改；D2 的 `_FAST_PATH_DEGRADE_PROMPT` **同样**带中文硬约束与固定话术 |
| `test_tool_registry_contains_required_tools` / `test_agent_routes_and_tools_endpoint_exist` / `test_enterprise_tool_enforces_backend_rbac` / `test_short_followup_query_replaces_stale_entity…` / `test_local_mode_never_exposes_web_tool` / `test_agent_prompt_routes_internal_and_current_queries` / `test_tool_call_and_result_are_audited` / `test_trace_does_not_persist_reasoning_content` | 工具注册表 / 端点存在 / RBAC / 实体族 / web 不暴露 / 提示词路由 / 审计成对 / trace 不存推理 | 全部未碰；`action="TOOL_CALL"`/`"TOOL_RESULT"` 计数**新增**等式钉（回路 + 降级腿各一笔 ⇒ 2/2） |
| `test_feishu_identity_contract` 的 `effective_allowed_from_grant(user.grant)` 计数 = 1 | 热路径每请求只解析一次授予范围 | **它抓了我的错**（见「状态」段）；修法在产品侧，等式未放宽 |

`test_typesafe_security_contract.py::…agent_path_merges_typesafe_observations…`（真跑 `run_agent`、
把 `_ollama_chat` 换成 `lambda *a, **k`）——迁移后仍绿：新 kwargs 是**关键字-only + 有默认值**，
且 legacy 形状的 `tool_calls` dict（`function.arguments` 已是 dict）仍走同一个读取器。

---

## 新增用例（**45** 例，按组；m-3 更正：组表原写「44 例」且 F 组写 4，两边都对不上 45）

| 组 | 类 | 例数 | 覆盖矩阵行 |
| --- | --- | --- | --- |
| A 迁移面 | `AgentRouterMigrationTests` | 4 | §9 第三条、#19（router 路上 httpx.post 上闸） |
| B 温度/逐轮开关 | `AgentTemperatureEquivalenceTests` (5) + `AgentPerTurnSwitchTests` (3) | 8 | **#18 报文等价** + §9.1 |
| C tool_calls 标准化 | `AgentToolCallStandardisationTests` | 5 | **#12 / #13 的 agent 半边** |
| D D2 降级 | `AgentNoCapableFastPathTests` | 8 | **D2**、#17 的降级半段、零候选不产账行 |
| E trace 九键 | `AgentModelRouteTraceTests` | 4 | **#17（集成半段）** |
| F legacy 分支 | `AgentLegacyBranchTests` | ~~4~~ **5**（m-3 更正：`test_the_legacy_signature_still_takes_two_positional_arguments` 是第 5 枚） | **#18**、D6 豁免表 |
| G 边界 | `AgentChainBoundaryTests` | 4 | #19、§8.1 唯一挂载点、`fallback.py` 字节冻结、注册表未被翻旗标 |
| H 源面契约 | `AgentRouterMigrationContractTest`（4）+ `AgentToolRoutingAfterMigrationTest`（3） | 7 | 形状回退类（删 legacy / 挪 catch / 挂载在落盘之后） |

底座刻意**不**打桩的东西：`llm.complete` / `classify` / `plan` / `run_complete` / `provider` /
`normalize` / `usage`——被测对象就是这条链本身；桩只打在 provider **下方**（`_transport`）与业务
**外围**（`tool_registry.execute`、审计路径、trace 路径、知识范围解析、`httpx.post`）。

---

## F. 变异表（9 发，`t8_mutations.py`，字节读/字节替换/字节写 + 发内还原 + sha1 核对）

| # | 变异（点名项） | 目标 | 结果 |
| --- | --- | --- | --- |
| M1 | `_chat_via_router` 漏传 `temperature=` | 温度调用面 | **KILLED**（2 failed / 9 passed） |
| M2 | 画像里 `needs_tools=bool(tools)` → 写死 `False` | 任务书点名的 needs_tools | **KILLED**（1 failed） |
| M3 | 工具轮 `except NoCapableModelError` → `except ZeroDivisionError`（= 不捕） | **D2 不捕 ⇒ 冒到路由层 503** | **KILLED**（4 failed / 4 passed） |
| M4 | `_message_from_response` 不再读 `response.tool_calls` | **标准化退回手写路径** | **KILLED**（1 failed / 5 passed） |
| M5 | `if llm.router_enabled():` → `if not …` | **legacy 分支条件写反** | **KILLED**（8 failed / 1 passed） |
| M6 | 删掉 `attach_model_route(...)` 调用 | #17 的 agent 半边消失 | **KILLED**（3 failed / 1 passed） |
| M7 | 不记 `NO_CAPABLE_MODEL→fast_path` 事件 | 零候选唯一解释出口消失 | **KILLED**（1 failed / 7 passed） |
| M8 | D2 合成腿漏传 `temperature=` | 第三枚调用面 | **KILLED**（1 failed） |
| M9 | `num_predict=int(num_predict)` → 写死 synthesis 值 | 逐轮开关失效 | **KILLED**（2 failed / 1 passed） |

**存活：0 发。** 台账：`t8_mutations_final.log`（对**最终字节** `9760d3509ed5` 重跑的那一份）。
两点诚实记录：
1. 首轮（M1–M2 KILLED 后）**死于脚本自己的打印**——`print` 中文说明里带 `⇒`，重定向到文件时宿主
   默认 GBK ⇒ `UnicodeEncodeError` 打断电池。已补 `sys.stdout.reconfigure(encoding="utf-8")`。
   事故现场 `restore()` 在 `finally` 里，**agent.py 已核对还原**（sha1 回到当轮基线、AST 可 compile）。
2. `agent.py` 是 **CRLF 原生**，多行锚点必须先展开成 `\r\n`，否则命中 0 次（第一版就吃了这个亏）；
   脚本现在按文件实测行尾自适应，并强制「锚点恰好命中 1 次」才继续。

---

## G. `agent.py` 迁移后的 httpx / 端点字面量命中表（T9 豁免表可直接抄）

AST 判定（`ast.walk`，排除 docstring 节点），由 `AgentLegacyBranchTests.test_d6_exemption_inventory_for_agent_py`
按**等式**钉（不是 `<=`）：

| 指标 | 数值 | 出处 |
| --- | --- | --- |
| `import httpx` | **1** | 文件头 D6 豁免段之后那一行 |
| `httpx.post(` 代码命中 | **1** | `_ollama_chat` 的 `LLM_ROUTER_ENABLED=false` 分支 |
| 端点路径字面量 `"/api/chat"` | **1** | 同上那一行（`settings.ollama_base_url.rstrip("/") + "/api/chat"`） |
| `settings.ollama_base_url` 属性读 | **1** | 同上 |
| `httpx.stream` / `httpx.Client` / `httpx.get` | **0** | 本链是 buffered 交付；两支 SSE 出口都在 routes 层 |
| 全文（含散文）`httpx` 字样 | ~~5~~ ⇒ **更正（m-1/m-2，按评审给的两分表重写）**：本轮原字节集 `9760d3509ed5` 上是 **12 行 / 子串 14 次**，其中**代码 2 行**（`:27 import httpx`、`:161 httpx.post(`）＋**散文 10 行**（注释 7 行：11/13/15/20/24/71/600；docstring 3 行：121/215/282） | 说明：**上一版的「全文 5 / 且全文扫描与代码扫描同数」两处都是假的**——文件头那段注释自己就写了 5 次 `httpx`，全文与代码天然不同数。该注释已在修复轮改写成「AST 五项为准、散文计数不进豁免表」，`agent.py:15-21` 可查。**终值（修复轮字节 `59d4cd3b3c3b`）＝ 15 行 / 子串 16 次：代码 2 行（`:32 import httpx`、`:166 httpx.post(`）＋ 注释 10 行（11/13/15/16/19/21/25/29/76/709）＋ docstring 3 行（134/227/293）** |

对照：`rag.py` 是 3 处 / 2 枚端点（T6 复审那张表），`conversation_agent.py` 是 **0**（T7 退役了 `native_stream.py`）。
**agent 链两条腿（含工具轮）都有 legacy 形态**——这与 §9.1 那句「`LLM_ROUTER_ENABLED=false` 不覆盖
agent 链的工具轮」需要对齐，见移交项 3。

---

## H. 终态数字与真实库实测

- 定向门 1：**386 passed / 0 failed / 353 subtests**。
- 全套件门 2：**881 passed / 0 failed / 881 subtests / 174.32s**（基线 837/880，只增不减）。
- 文件完整性（全部**跑完之后**复核）：`app/agent.py` = CRLF 原生（871 行全 CRLF、`bare_lf=0`）、
  `compile()` 通过、sha1 `9760d3509ed5…`；
  `app/llm/fallback.py` sha1 前缀 **`008d8213bc05`（与要求的现值一致，943 行纯 LF，字节不变）**，
  另有例直接钉它（`AgentChainBoundaryTests.test_fallback_py_is_byte_frozen_for_this_task`）。
- **逐文件字节对照 `snap-task7/`（全部 identical）**：`app/llm/` 十一份模块（`__init__` /
  classifier / errors / fallback / health / models / normalize / provider / registry / router / usage）、
  `app/rag.py`、`app/conversation_agent.py`、`app/agent_routes.py`、`app/agent_trace.py`、
  `app/security.py`、`app/main.py`、`app/knowledge_os.py`、`tests/conftest.py`、
  `tests/test_llm_usage_contract.py`、`tests/test_p17_streaming_contract.py`
  ⇒ 本任务的**唯一**产品代码改动面就是 `app/agent.py` 一个文件；`config/llm_registry.json`
  sha1 `3e652e9cf496`（未改，另有 `test_the_registry_file_is_untouched` 逐条目钉 tools 旗标声明值）。
- 真实观测面未被写：`backend/data/agent_traces.jsonl` mtime 仍是 `2026-09-23T15:58`（本轮所有 trace 例
  都改道临时目录），`audit.jsonl` 同理。真库只读实测（`file:data/conversations.db?mode=ro`）：
  **`llm_request_logs=0` / `conversations=7` / `messages=10`**（与基线逐枚相同）。
- 变异台终值：对最终字节 `9760d3509ed5` 重跑，**9/9 KILLED、存活 0、终态 sha1 与起点一致**
  （`t8_mutations_final.log` 末两行）。

---

## 我没有做的事（以及为什么）

1. **没有**改 `config/llm_registry.json`（任何旗标）。
2. **没有**复用 `conversation_agent._local_fast_path` 那个**函数**（原因见下）。
3. **没有**吞掉 `AllCandidatesFailedError` / 硬终态 `LLMError`，**没有**换任何对外文案。
4. **没有**新增第三条 SSE/流式出口（`AgentChainBoundaryTests` 用 AST 数 `llm.complete` 调用点 = 2、
   `llm.stream` = 0 钉住）。
5. **没有**动 `trace["model"]`、`max_rounds` 语义、`timings`/`sources`/审计的既有形状。
6. **没有**做任何真实外呼（本机 11434 一次都没打；每条 `self.requests` 都是 `httpx.MockTransport` 拦下的）。

**关于 2（一处刻意的偏差，请评审重点看）**：brief 写「复用现 local 模式分支」。直接调
`conversation_agent._local_fast_path` 会自带 `new_trace_id()` + `save_trace()` + `mode="local"` 的响应体，
于是**一次用户提问落两条 trace 行**，而 D2 那条 `NO_CAPABLE_MODEL→fast_path` 注记只能落在其中一条上——
零候选不产账行（T5 裁定）之后，这条注记是唯一解释出口，落在「响应 trace_id 指不到的那一行」等于没有。
而 `app/conversation_agent.py` 在本任务是**禁改文件**（没法给它加 `degraded_note` 参数）。
所以我在 `agent.py` 内实现了**等价**降级（同一套机器件：`tool_registry.execute` / `ToolContext` /
两笔审计 / `redact_secrets` / `public_typesafe_metrics` / 证据去重与 `citation_index`），
并复用 `_local_fast_path` 的**证据投递形状**（证据走 `AUTHORIZED_ENTERPRISE_EVIDENCE=` 的 system 段，
**不是** `role="tool"` 消息——降级轮没有 assistant 的 tool_calls 前置，Ollama 对这种 tool 消息会 400，
那等于把「不得 500/503」换成一次真实外呼失败）。代价：这条 prompt 与对话链那份同源但有两处文本，
已写明理由。**如果评审倾向"宁可两条 trace 行也要零重复"**，改回去是 5 行的事，请明说。

---

## 待用户裁决项（本任务不动，附证据）

1. **要不要把某条注册表条目的 `capabilities.tools` 翻成 true？** —— 建议**不要**，理由三条：
   - `phi3:mini`：微软官方 Phi-CookBook issue #13 的答复是 Phi-3 系列**未针对 function calling 训练**、
     官方没有工具调用示例（[microsoft/PhiCookBook#13](https://github.com/microsoft/PhiCookBook/issues/13)、
     [ollama.com/library/phi3:mini](https://ollama.com/library/phi3:mini)）；Ollama 的
     [Tool calling 能力文档](https://docs.ollama.com/capabilities/tool-calling) 是**按模型清单**决定
     `tools` 能力的，phi3 不在受支持清单里（社区实测「June 之后的 phi3-mini 勉强能吃函数格式但不稳定」
     的帖子也只到"能用"而不是"可靠"）。翻成 true = 注册表说谎，§3 冻结的「能力旗标按各模型真实能力」被破坏，
     并且 §5 的 `capability > preference` 会把工具流量发给一个把 JSON 编成散文的模型。
   - `ornith-1.5:9b-text`：**本机加载失败**（用户实测；T10 的 P0 用例正是拿它当"primary 真失败"的源），
     给它加 tools 旗标不改变它跑不起来这件事。
   - 可行的替代方案（都**不是**改旗标）：① 给 `openai` 条目配 key（`OPENAI_API_KEY`，D1 复用现有配置）；
     ② 想要纯本地工具回路，就**新增**一条注册表条目指向官方支持 tools 且本机跑得动的模型
     （Ollama 清单里如 `qwen2.5` / `llama3.1` 8B 级），`priority.tools` 自行排序。
   - 请用户就「V2.3 出厂形态是否接受 agent 工具链 100% 走 D2 fast path」明确表态；本轮按 spec 的 D2 执行。
2. **`agent_local_fast_path=false` 时零候选该不该报错？** 我按 D2 冻结（"不得 500/503"）**无条件**降级，
   没把这枚配置当闸门；如果运维语义是「关掉快路径就应该看到错误」，需要改 D2 的口径（不是改实现）。
3. **§9.1 的措辞回写（归 T11）**：那句「`LLM_ROUTER_ENABLED=false` 不覆盖……agent 链的工具轮」在 T8
   落地后不准确——agent 链**两条腿都有** legacy 形态（同一段 httpx 报文，含 tools 键）。
   建议改成：「agent 链的 #18 对照面完整存在，但关掉旗标会退回到『无条件把 tools 发给不支持工具的本地模型』
   的现网行为；应急含义是『回到未路由的世界』，不是『让工具轮可用』」。
4. **`model_used` 的取值来源**（本任务从 `settings.ollama_model` 改成 selected 生效模型名）
   是否需要在 `docs/UI_COPY_GLOSSARY.md` / 前端 TraceView 文案上登记一句？（字段名与取值类型都没变。）

---

## 移交 T9 / T10 / T11

- **T9（D6 扫描 + 矩阵收口）**：G 段那张命中表就是 `agent.py` 的豁免行（等式已被 AST 例钉住，
  有人新开第二条出口会先在本任务的红线上响）。豁免清单目前三行：`rag.py` 3/2、`agent.py` 2/1、
  `conversation_agent.py` 0/0。#17 的三链半段至此齐了（RAG 在测试内闭合、SSE/Agent 真落盘）。
- **T10（P0 真实 failover）**：注意本轮之后，`/api/agent/query` 在**默认无 key 环境**下不会产生
  任何 tools 请求（全是 rag-mode 合成腿）；真实 failover 请继续按 brief 走 `/api/query/stream`
  或显式给 `OPENAI_API_KEY`。另外真实跑一次 agent 工具轮**之前**，要么配 key，要么把 D2 降级
  当成预期交付形态（trace 里会看到 `model_route_downgrade` 事件，这是**正常**而不是故障）。
- **T11（验收文档）**：需要写清的四句：①「出厂无 key ⇒ agent 工具链常驻 fast path」；
  ②「`LLM_ROUTER_ENABLED=false` 对 agent 链是完整 legacy（两条腿）、对对话链只是非流式腿」（含 3 号回写）；
  ③「零候选请求不产生 `llm_request_logs` 行，`requests_5m` 不含它，归因看 trace 的 `model_route_downgrade`」；
  ④「`model_used` 在 agent 链上改为 selected 生效模型名（additive-only）」。
- **下一稳定版删 legacy 时**：`agent.py` 一起消失的东西 = 文件头 D6 段、`import httpx`、
  `else:` 那条 `httpx.post` 报文、`_tool_arguments` 的字符串分支、以及 7 例 `AgentLegacyBranchTests`。

---

# 修复轮 1（2026-09-24，针对 `review-task-8-findings.md`：Critical 1 / Important 4 / Minor 9）

**状态：C-1 / I-1 / I-2 / I-3 / m-1 / m-2 / m-3 / m-5 / m-6 / m-8 全部落地并绿；m-7 判「条件不成立」⇒ defer T11；I-4 / m-4 / m-9 按任务书 defer。**

| 门 | 命令（cwd=`backend/`） | 本轮终值 |
| --- | --- | --- |
| 1 定向 | `pytest tests/test_agent_contracts.py tests/test_agent_routing_contracts.py tests/test_model_router_v23_contract.py -q` | **393 passed / 0 failed / 360 subtests**（72.34s）＝上一轮 386/353 **+7 例 / +7 subtest** |
| 2 全套件 | `pytest tests -q` | **889 passed / 0 failed / 889 subtests**（158.00s）＝任务书基线 882/881 **+7 例 / +8 subtest、0 失败**（台账 `fix8_fullsuite.log`） |
| 3 变异 | `fix8_mutations.py`（字节读/字节替换/字节写 + **发内还原** + sha1 核对 + `compile()`），**对最终字节 `59d4cd3b3c3b` 重跑** | **7 发全 KILLED、存活 0**（台账 `fix8_mutations_final.log`；`fix8_mutations.log` 是同一电池对倒数第二枚字节集 `77ad5d512cc0` 的首跑，两表一致） |
| 4 约束 | 冻结件逐枚比对 + 真实库只读 + 零真实外呼 | ✓ 见「冻结件前后表」与「观测面」 |

新增 **7 例 / 8 subtests**：v23 文件 agent 族 38 ⇒ **44**（D 组 8⇒**13**、E 组 4⇒**5**），
`test_agent_contracts.py` 的 `AgentRouterMigrationContractTest` 4⇒**5**（该文件 15⇒16 例、
两份契约文件合计 23 例），`test_agent_routing_contracts.py` **一字未动**（sha1 仍 `0f9f293daefb`）。

## FIX-C1（Critical）——降级腿的合成补上第二道 catch

**改了什么**（`app/agent.py`）：新增出口函数 `_synthesize_with_second_door(messages, *, round_index, trace_id, events, route_out)`
（`:410-436`）——`try: return _synthesize_without_tools(...)` / `except NoCapableModelError as second_exc:` ⇒
`events.append(_no_capable_event(round_index, second_exc))` + **`return ""`**（交回 `run_agent:923-924`
既有的 `if not final_answer:` 中文收尾文案，**不新增对外文案**）。三个落点全部改走它：

1. `_degrade_to_local_fast_path` 原 `:521` 那一行裸调（现 `:626-628`）；
2. 收尾腿 except 支原 `:776` 那次裸调（现 `:903-905`，与 I-1 同处）；
3. **顺带 m-6**：工具回路的 except 支（现 `:713-722`）在 `exc.stage == "context"` 时**不再**进
   `_degrade_to_local_fast_path`——证据已在手，重跑 `enterprise_search` 是多一笔后端检索 +
   多两条审计 + 在已溢出上下文上继续追加证据 ⇒ 必然二次溢出（评审 C-1 的另一半诱因）。

**目标形状达成**（`test_a_second_zero_candidate_still_delivers_the_copy` 实测）：函数/HTTP 面不抛、
`answer == "当前没有获得足够证据生成可靠答案。"`、`len(trace_rows())==1`、`model_route_downgrade`
事件 **2 枚**（`stage` 依次 `capability` / `context`）、`QUERY` 审计在位且 `TOOL_CALL`/`TOOL_RESULT`
各 1 笔、`self.requests == []`（两次都是 `plan()` 阶段零候选 ⇒ **零外呼**）。

**哪条测试钉**：
- `AgentNoCapableFastPathTests::test_a_second_zero_candidate_still_delivers_the_copy`（评审点名例）——
  用 `overflowing_evidence()`（16 800 字符证据 ⇒ dump 截到 16 000 ⇒ `estimate_prompt_tokens ≈ 9 300 > 8 192`）
  把**出厂形态**复现出来，不靠 Stub 伪造异常；
- `…::test_the_http_face_still_returns_200_shape_when_the_degraded_leg_overflows_too`
  （评审点名的 `test_the_http_face_still_returns_200_shape…` 溢出兄弟例）——`call_http_face()` 不许抛 `HTTPException`；
- 源面第二张网：`AgentRouterMigrationContractTest::test_the_degraded_leg_has_its_own_second_zero_candidate_catch`
  钉 `count("except NoCapableModelError as second_exc:")==1` ∧ `count("= _synthesize_with_second_door(")==3`
  ∧ `exc.stage == "context"` 在位 ∧ 三支文案与 `conversation_agent.py` 逐字相同 ∧
  降级函数体内 `route_out=route_out` 只出现 **1** 次。既有那枚 `count("except NoCapableModelError as exc:")==2`
  **一字未改**（新 catch 用 `second_exc`，两枚计数器各自仍然成立）。

**变异**：`C1` 删掉新 `except`（还原成裸调）⇒ **KILLED**（定向 2 failed；`-k Agent` 全组 3 failed / 68 passed ⇒
除两枚新例外还有源面那枚计数器在响）；`C1b` catch 在但**不记**那枚注记 ⇒ **KILLED**（证明「第二枚注记」
本身有钉，不只是「不抛」有钉）。

## FIX-I1——收尾腿的降级支也挂 `model_route`

**改了什么**：`agent.py` 收尾腿（`for…else`）改成与主降级门**同形**——删掉局部盒 `limit_outcomes`
与 `outcomes.extend(...)`，`_ollama_chat(messages, [], trace_id=…, route_out=outcomes)` 与
`_synthesize_with_second_door(…, route_out=outcomes)` 都直传主盒（`:896` 与 `:903-905`）。两条支路各一次写入，
不再存在「记得 merge / 忘了 merge」的第二种写法。

**哪条测试钉**：`AgentModelRouteTraceTests::test_the_limit_leg_route_also_lands_nine_keys`
（`agent_max_tool_rounds=1`，**成功支 / 降级支各一个 subTest**）。按任务书要求写成**等式**而非存在性：
两支持平地比 `set(row) == {trace_id, timestamp, username, role, mode, model, max_tool_rounds,
context_messages, events, evidence_count, elapsed_ms, timings, model_route}`（13 键全列）+
`assert_nine_keys(row[MODEL_ROUTE_KEY])` + `route["mode"]`（成功支 `agent` / 降级支 `rag`）+
`requirements["needs_tools"] is False` + `attempts[0]["model"] == result["model_used"]`
（顺手把评审 §7 第 4 项那枚「`model_used` 回落例外」也消掉了：该腿降级后 `model_used` 与账本同源）。

**变异**：`G2` = 评审 G2 的**等价变异**（新形状下「成功支不经过 `outcomes`」= 把收尾腿那次
`route_out=outcomes` 去掉）⇒ **KILLED**（`SUBFAILED(branch='成功支')`，降级支仍绿 ⇒ 两支各有一枚钉）。
评审当初那发（删 `outcomes.extend`）在改后的字节里**已无对应文本**——这正是「同形」要买的东西。

## FIX-I2——降级腿的工具耗时不再进 `llm_ms`

**改了什么**：`_degrade_to_local_fast_path` 签名加可变盒子 `tool_time: dict[str, float]`
（与 `retrieval_timings`/`events` 同一手法；`run_agent` 顶部新建 `tool_time_box`、降级门传入），
`latency_ms` 算出后 `tool_time["enterprise_search"] = latency_ms`（`:551`，盒子在 `:693` 新建、`:740` 传入）；收尾算式改为
`model_ms = max(elapsed_ms - tool_time_total - sum(tool_time_box.values()), 0.0)`（`:934`）。
**没有**删 `llm_ms`（评审明令不接受：那是放宽观测面）。

**哪条测试钉**：`AgentNoCapableFastPathTests::test_the_degraded_leg_tool_time_stays_out_of_the_generation_stage`
——读的是 trace 里的 **`stage` 事件**（这正是它过去没被抓到的原因：agent 组一枚都不读 stage）。
底座给 `_RecordingToolExecutor` 补了**真实** `sleep_ms`（手法照 `_StubToolRegistry`；I-2 的算术要有
真时间流过才成立），两个 subTest 各睡 400ms：`generation.elapsed_ms < row.elapsed_ms - 300.0`，
并同时钉 `tool_end.latency_ms >= 300`（睡眠没生效这一例就不成立）与
`generation.elapsed_ms is not None`（扣重了也会红）。两腿对照 = 评审 P2 的形状。

**变异**：`I2` 删掉那一行盒子写入 ⇒ **KILLED**（`SUBFAILED(leg='D2 降级腿')`，工具回路腿仍绿）。

## FIX-I3——三支同源硬文案短路接进降级腿（等价性缺口，安全相邻）

**改了什么**：`_degrade_to_local_fast_path` 在投递证据**之前**插入与 `conversation_agent.py:316-321`
**逐字同源**的三支短路（`:593-615`）：`DENIED` ⇒「当前账号无权访问该知识库，因此不能基于未授权资料回答。」、
`status != "SUCCESS"` ⇒「企业知识检索暂时失败，请稍后重试。」、`not evidence` ⇒
「当前授权范围内没有检索到足够证据，暂时无法可靠回答。」。三支**都不调模型**、`route_out` 不塞盒子 ⇒
trace 也**不挂** `model_route`；另新增 `_fast_path_copy_event`（`:387-406`）落一枚可区分注记
`NO_CAPABLE_MODEL→fast_path_denied` / `_failed` / `_no_evidence`（`tool_status` 带工具状态；
`reason_codes` 仍只写冻结枚举里那枚 `NO_CAPABLE_MODEL`，**不新增机器码词表**）。

**没有**辩「agent 链历史语义不同」：评审 §6 裁定 `_local_fast_path` 是唯一权威实现、降级是变体，
必须复用语义与机器件，我按这条执行。`not evidence` 那一支刻意读**累计** evidence 列表而不是本次 result
的行数——工具回路第 2 轮才零候选时证据可能来自第 1 轮，此时用「零证据」文案反而是新的不等价。

**哪条测试钉**：`AgentNoCapableFastPathTests::test_the_three_no_generation_copies_short_circuit_like_the_conversation_chain`
（三支各一个 subTest，形状照 T7 的 `test_the_three_no_generation_paths_never_touch_the_llm`）：
`self.requests == []` ∧ `raw_rows() == []`（**账本 0 行**）∧ 答案逐字等式 ∧ `MODEL_ROUTE_KEY not in row` ∧
注记 2 枚且末枚 note 按支区分 ∧ `TOOL_CALL`+`TOOL_RESULT`+`QUERY` 三笔审计齐。
源面：三支文案同时出现在 `agent.py` 与 `conversation_agent.py`（上面那枚契约例）。

**变异**：`I3` 把 `if copy_note:` 变死 ⇒ **KILLED**（3 个 subTest failed：DENIED 路照发合成、答案变模型输出、
账本 1 行、`model_route` 被挂上）；`I3b` 注记退回不可区分的 `NO_CAPABLE_MODEL→fast_path` ⇒ **KILLED**。

## m 批

| 项 | 落点 | 钉 |
| --- | --- | --- |
| m-1 / m-2 | `agent.py:15-21` 文件头改写：AST 五项为准、明说「全文与代码天然不同数」；G 段最后一行按两分表重写（原轮 12 行/14 次 = 代码 2 + 散文 10；**终值 15 行/16 次 = 代码 2 + 注释 10 + docstring 3**，逐枚行号见 G 段） | `AgentLegacyBranchTests.test_d6_exemption_inventory_for_agent_py` 的 AST 五项**逐字未动**且仍绿（本轮只改散文） |
| m-3 / m-5 | 报告「状态」表门 2、A/B 段位置、组表 F 组、「新增用例」标题（见本段上方的四处行内更正） | — |
| m-6 | 并入 FIX-C1 第 3 点 | `test_a_context_stage_downgrade_does_not_retrieve_again`：`self.tools.names == ["enterprise_search"]`（**只有第 1 轮那一次**）+ `TOOL_CALL` 审计 1 笔 + 注记 1 枚且 `stage=="context"` + `MODEL_ROUTE_KEY` 在位 + 外呼 1 次；变异 `M6` ⇒ **KILLED** |
| m-8 | `AgentPerTurnSwitchTests::test_tool_routing_turn_uses_the_reasoning_and_large_num_predict_settings` 补 `assertEqual("30m", requests[0].payload["keep_alive"])` + kwargs 面同值（绝对值面、RAG/SSE 组同法；原 `== settings.ollama_keep_alive` 那枚保留） | 该例本身 |
| **m-7（defer）** | **没做**，两条理由都落在任务书给的红线上：①要「前端不读 trace 也能分辨本次无工具轮」成立，标记必须覆盖**四**类出口（工具回路 / 主降级门 / 三支文案短路 / 收尾腿），而本轮 `app/security.py`、`app/agent_routes.py` 均字节冻结，响应面一旦要过 `PUBLIC_TIMING_KEYS` 那类逐枚白名单就动不得；②真能钉住「前端可分辨」的是 UI/前端契约面的例（本轮改动面只有 `agent.py` + 两份 agent 契约 + v23 契约），而既有 `test_trace_carries_route_and_the_response_face_is_additive_only` 是按**等式**钉响应键集合的，加一枚键就要改那枚等式。⇒ 交 T11 写清（评审 §8 第 7 项同判），**不硬做** |

**本轮被既有测试抓到的一次真实回退**（不是新写的例）：我在 `_degrade_to_local_fast_path` 的 docstring 里
写了 `ToolContext(mode="local")`，被 `test_feishu_identity_contract.py::ToolContextScopeGuardTests` 的
**文本**扫描判红（`SUBFAILED(file='app/agent.py')`）⇒ 修法是把 docstring 写成完整调用形
（`ToolContext(mode="local", allowed_knowledge_base_ids=<…>)`），护栏一字未放宽、`grant 计数=1` 那枚也没碰。
上面那枚 889/0 就是修后重跑的全套件终态（第一次跑是 `1 failed, 889 passed, 888 subtests`）。

## 改动面（本任务窗口 = 修复轮 1）

| 文件 | 行尾 | 字节 | sha1(12) 前 ⇒ 后 | delta |
| --- | --- | --- | --- | --- |
| `backend/app/agent.py` | CRLF 原生（**1000 行全 CRLF、`bare_lf=0`**，未翻转） | 41,569 ⇒ 50,371 | `9760d3509ed5` ⇒ **`59d4cd3b3c3b`** | **+137 / −9 行**（非注释 +91 / −7） |
| `backend/tests/test_model_router_v23_contract.py` | LF 原生 | 425,595 | `e9ab22d34cfb` ⇒ **`41506ab66166`** | +6 例（D 组 +5、E 组 +1）+ `_RecordingToolExecutor` 的 `status`/`sleep_ms` |
| `backend/tests/test_agent_contracts.py` | CRLF 原生（233 行、`bare_lf=0`） | 14,817 | `5a59795bf897` ⇒ **`d32e110d8a39`** | +1 例（源面第二张网） |
| `backend/tests/test_agent_routing_contracts.py` | CRLF | 3,433 | `0f9f293daefb` ⇒ `0f9f293daefb` | **一字未动** |
| `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/` | — | — | `fix8_mutations.py` / `fix8_mutations.log` / `fix8_mutations_final.log` / `fix8_fullsuite.log` / `fix8_targeted.log` | 计划目录工件，不进产品树 |

**对 `snap-task8/` 的逐枚字节对照：24 份 identical、DIFFERS 恰好上面这 3 份** ⇒ 本任务窗口的产品代码
改动面仍然只有 `app/agent.py` 一个文件。

## 冻结件前后表（本轮前后各算一次；全部 IDENTICAL）

| 件 | sha1(12)（前 = `snap-task8/` 值 = 终态） | 结论 |
| --- | --- | --- |
| `app/llm/__init__.py` | `c29e3c393f87` | IDENTICAL |
| `app/llm/classifier.py` / `errors.py` / `health.py` / `models.py` | `81d43043aee4` / `fca8d9da2c8f` / `f529dc5f42b5` / `586dfe033c73` | IDENTICAL |
| `app/llm/normalize.py` / `provider.py` / `registry.py` / `router.py` / `usage.py` | `c6bc8b0caf81` / `9d34721f89f0` / `60b706112882` / `2742871ed6ee` / `8a8f5b0cff28` | IDENTICAL |
| **`app/llm/fallback.py`** | **`008d8213bc05`**（= 任务书要求的现值） | IDENTICAL |
| `app/rag.py` | `a5a638716947` | IDENTICAL |
| `app/conversation_agent.py` | `0ffcc353eb59` | IDENTICAL |
| `app/agent_routes.py` | `1080fbd4a0c4` | IDENTICAL |
| `app/agent_trace.py` / `app/main.py` / `app/knowledge_os.py` | `d17a0bf266f1` / `bc0281dcfc42` / `c92ba3364a3e` | IDENTICAL |
| **`app/security.py`** | **`d36b387aac6e`** | IDENTICAL |
| `config/llm_registry.json` | `3e652e9cf496` | IDENTICAL |
| `tests/conftest.py` / `test_llm_usage_contract.py` / `test_p17_streaming_contract.py` / **`test_feishu_identity_contract.py`** | `73d1060de465` / `f3324ff74e6e` / `808adcae4bea` / **`145d81cbb342`** | IDENTICAL |

## 观测面与真实库（终态实测）

- `backend/data/agent_traces.jsonl`：**mtime 仍是 `2026-09-23T15:58`**（本轮 trace 例照旧改道临时目录）。
- `backend/data/audit.jsonl`：mtime 前进到 `2026-09-24T15:03`（**m-4 的既有卫生问题**，非本轮引入）——
  按 `agent_mode=` / `tool=enterprise_search` 过滤后**最后一行仍是 `2026-09-23T07:58:39Z`**，
  即本轮 0 行 agent 面审计写进真实文件；新增行是 `LOGIN/AUTHORIZATION/QUERY/RETRIEVAL_DEBUG` + `admin/viewer`。
- 真库**只读**实测（`file:data/conversations.db?mode=ro`，全套件跑完之后）：
  **`llm_request_logs=0` / `conversations=7` / `messages=10`**（与基线逐枚相同）。
- 零真实外呼（`httpx.MockTransport` / `ollama.test` / `api.openai.test` / `httpx.post` 替身，11434 一次未打）、
  零 git 写（只 `git status`）、不新增依赖、既有断言零放宽（含 `grant 计数=1` 与 `except … as exc` 那枚计数等式）。

## 修复轮 1 的移交增补（接评审 §8）

- **T9**：①G 段的**终值两分表**替换旧「5」；②`fix8_mutations.py` 的 7 发收进常备变异表
  （`C1` / `C1b` / `G2` / `I2` / `I3` / `I3b` / `M6`，全 KILLED、存活 0）；③「`enterprise_search` 的
  `TOOL_CALL` 调用点上限 = 2」这条守卫本轮仍成立（`count('action="TOOL_CALL"')==2` 未动）；
  ④I-4 归 T9 的 `normalize.openai_payload` 义务**未被本轮触碰**（`app/llm/*` 字节冻结），
  多轮回放那半段今天写出来仍会红——那正是它的价值。
- **T10**：`model_route_downgrade` 现在可能出现 **2 枚**（工具轮 + 合成腿）或 **1 枚普通 + 1 枚
  `→fast_path_denied/_failed/_no_evidence`**，都是**正常**出厂形态观测面，不要判成故障。
- **T11**：m-7 的响应面标记缺口 + §6 六项统一口径 + §7 第 2/4 项照写；另加一句：
  「三支硬文案短路（DENIED / 检索失败 / 零证据）**零外呼、零账行、不挂 `model_route`**，
  归因看 `model_route_downgrade` 的 note」。

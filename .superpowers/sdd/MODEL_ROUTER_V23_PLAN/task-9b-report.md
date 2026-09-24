# Task 9 段 B 报告 — 两件产品代码修复（I-4 多轮回放映射 / N-3 在手证据门）+ 矩阵回写

## 状态

**段 B 两件（FIX-B1 / FIX-B2）全部交付，验收门 1–4 全绿；8 发变异 0 存活。**

| 门 | 结果 |
| --- | --- |
| 门 1 定向 | `tests/test_model_router_v23_contract.py + tests/test_llm_egress_guard.py` ⇒ **409 passed / 0 failed / 445 subtests（98.85s）**；附带跑 `tests/test_llm_egress_guard.py + tests/test_llm_usage_contract.py` ⇒ **130 passed / 0 failed / 117 subtests** |
| 门 2 两种 cwd | `cd backend && python -m pytest tests -q` ⇒ **928 passed / 0 failed / 974 subtests（200.42s）**；`cd /e/xiangmu/rag && python -m pytest backend/tests -q` ⇒ **928 passed / 0 failed / 974 subtests（201.74s）**。基线 918/0/973 ⇒ **+10 例 / +1 subtest / 0 例被删**（那枚多出来的 subtest 是 `MatrixDocumentClosureTests` 对本表新增 `N-3` 行的逐行核对，不是新用例） |
| 门 3 变异 | **8 发全 KILLED，0 存活**（`task9b_mutations.py`，字节读写 + 发内还原 + 每发核对 sha1） |
| 门 4 矩阵回写 | `#12b` `BLOCKED → GREEN` + 7 枚真实 node-id；`#13` 追加 Ollama 腿不受牵连的承载例；新增 `N-3` 行；§4/§5 与表头回写。承载闸 `MatrixDocumentClosureTests` 5 例 + 1 subtest 逐行通过 |
| 真实库只读复核 | `llm_request_logs=0 / conversations=7 / messages=10`（与主 agent 的基线一致；两种 cwd 全套件跑完仍 0/7/10） |

零 git 写（只跑过 `git status --porcelain` 读取）；零真实外呼（探针一律假 host + `httpx.MockTransport`，11434 未被触碰）；未新增依赖；**未放宽/删除任何既有断言**（唯一被改到的既有例是**升级**，见下节）。

## 改动面（本段窗口）

### 产品代码（2 个文件，就这两件）

1. `backend/app/llm/normalize.py`（LF 原生；sha1 `c6bc8b0caf81` → `6e8a345ff322`，297 → 420 行）
   - `openai_payload` 的 `messages` 改为过 `_replay_messages()`（**出口前**映射，函数体其余一字未动）。
   - 新增四枚私有件：`_replay_messages` / `_stringified_tool_call` / `_paired_tool_receipt` /
     `_matching_call` + `_consume_id` / `_pairable_id`，以及一枚常量 `_TOOL_ROLE`。
   - `ollama_payload`、`parse_*`、`*_stream_lines` **零改动**（Ollama 腿不需要映射，也不许被牵连）。
2. `backend/app/agent.py`（**全 CRLF 原生**；sha1 `59d4cd3b3c3b` → `9dabebf801ed`，
   1000 → 1044 行，`crlf=1044 / lf=1044` ⇒ **零裸 LF，行尾没翻**）
   - `_degrade_to_local_fast_path`：失败支短路判据加「在手 `evidence` 非空 ⇒ 继续合成」的门 +
     DENIED 支的「不吃这枚门」理由注释 + 合成 dump 改取 `synthesis_evidence` + 一枚注记事件。
   - 新增 `_degraded_with_evidence_event()`（与 `_fast_path_copy_event` 同一 `type`、同一枚冻结理由码）。
   - **未改**消息回放形状（`{"role":"tool","tool_name":X}` 与 `assistant.tool_calls[].arguments=dict`
     原样保留）、**未改** `LLMResponse/ToolCall`（§6 冻结）。
   - 补丁是字节级落盘：`python .superpowers/sdd/MODEL_ROUTER_V23_PLAN/task9b_apply_b2.py apply|revert`
     （开工前校验 `59d4cd3b3c3b`、三处替换各命中恰一次、跑完 `revert` 应回到原 sha1）。

### 测试代码（1 个文件）

`backend/tests/test_model_router_v23_contract.py`（LF；`387f90eb1537` → `a4e99e2a3944`，7396 → 7745 行）

- 新增模块级 helper `openai_tool_round_body(calls)`：按**线上形状**造 OpenAI 工具轮回执
  （`arguments` 是 JSON 字符串），与既有 `ollama_tool_body()` 对称。
- 新增类 `OpenAIMultiTurnReplayTests(_AgentMigrationFixture)`（8 枚）：全部走**真链**
  （`run_agent` → `llm.complete` → `fallback` → `provider` → MockTransport），审第二轮**出口体**：
  1. `test_the_second_round_sends_function_arguments_as_a_json_string`（str + `json.loads` 回原 dict +
     中文原样 + `ensure_ascii` 反证 + `id` 不被吞 + `content==""` 形状）
  2. `test_the_second_round_tool_receipt_carries_the_matching_tool_call_id`（回执 id == assistant 那枚
     调用 id、`tool_name` 不外带、键序 `["role","tool_call_id","content"]`、回执正文一字未动）
  3. `test_two_calls_with_different_names_in_one_round_pair_by_name`
  4. `test_two_calls_with_the_same_name_in_one_round_pair_in_order`（第 N 枚回执配第 N 枚调用）
  5. `test_the_mapping_prefers_the_matching_tool_name_over_position`（乱序回执：同名优先于位置）
  6. `test_a_call_without_an_id_is_never_paired`（空 id ⇒ **不造假 id**）
  7. `test_the_egress_mapping_is_idempotent_and_never_mutates_the_request`（幂等 + 自带 id 优先 +
     孤儿回执不造 id + 另一条腿读到的仍是内部形状）
  8. `test_the_ollama_leg_still_replays_the_dict_arguments`（**两腿差异只在出口映射**：Ollama 腿
     仍吃 dict、`tool_name` 仍在、`tool_call_id` 仍无、端点仍是 `/api/chat`）
- `AgentNoCapableFastPathTests` 新增两枚 + 一枚复现装置：
  `_prior_evidence_then_failing_round(status=...)`（round 1 工具回路真拿证据 → round 2
  `NoCapableModelError(stage="capability")` → 降级腿那次检索按给定 status 失败）、
  `test_a_failed_current_round_answers_from_the_evidence_already_in_hand`、
  `test_a_denied_current_round_keeps_the_hard_copy_even_with_evidence_in_hand`。
- **升级一枚既有断言**：`OllamaPayloadShapeTests::test_payload_does_not_mutate_the_request`。

### 文档与工具

- `docs/MODEL_ROUTER_V23_MATRIX.md`（LF；`712467ee2850` → `46b607d97d39`，87 → 113 行）：见「矩阵变更」节。
- `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task9b_mutations.py`、`task9b_apply_b2.py`：变异台与
  CRLF 补丁台（不进产品树）。

## 被改动的既有断言（逐条：原来挡什么 → 现在挡什么）

| 例 | 原来挡什么 | 现在挡什么 |
| --- | --- | --- |
| `OllamaPayloadShapeTests::test_payload_does_not_mutate_the_request` | 一条 user 消息 + `tools=[{"type":"function"}]`：只挡「两腿把 `req.tools`/单条 message 列表整个换掉」 | 消息表扩成 `user + assistant(tool_calls, arguments=dict) + tool(tool_name=…)` 三枚，断言 `req.messages` 与**逐字深拷贝基准**等式 ⇒ 现在挡的是「`openai_payload` 的映射在浅拷贝之外就地改 `tool_calls[].function.arguments` / 把 `tool_name` 换成 `tool_call_id`」，即污染下一轮与另一条腿读到的内部形状（`dict(m)` 是浅拷贝，这一枚以前完全够不着）。原断言一条没删，`req.tools` 那条也原样保留 |

其余被 I-4 映射**可能**影响到的既有 payload 例（`OpenAIPayloadShapeTests` 三枚、
`AgentToolCallStandardisationTests` 五枚、`AgentLegacyBranchTests`、`RagTemperatureEquivalenceTests`）
经核查**不需要改**：它们的 messages 里没有 `tool_calls` / `role="tool"`，`openai_payload` 的映射对它们是恒等；
Ollama 腿的逐字形状例（含 #18 的 legacy 逐字节例）一条都没被触碰。**没有删除、降级或跳过任何断言。**

## FIX-B1（I-4）：红 → 绿证据

修复前（`normalize.py` 未改，测试已写完）实测：

```
$ cd backend && python -m pytest tests/test_model_router_v23_contract.py -q \
      -k "OpenAIMultiTurnReplay or failed_current_round or denied_current_round or payload_does_not_mutate"
6 failed, 3 passed, 369 deselected in 77.04s
  FAILED OpenAIMultiTurnReplayTests::test_the_egress_mapping_is_idempotent_and_never_mutates_the_request
  FAILED OpenAIMultiTurnReplayTests::test_the_second_round_sends_function_arguments_as_a_json_string
  FAILED OpenAIMultiTurnReplayTests::test_the_second_round_tool_receipt_carries_the_matching_tool_call_id
  FAILED OpenAIMultiTurnReplayTests::test_two_calls_with_different_names_in_one_round_pair_by_name
  FAILED OpenAIMultiTurnReplayTests::test_two_calls_with_the_same_name_in_one_round_pair_in_order
  FAILED AgentNoCapableFastPathTests::test_a_failed_current_round_answers_from_the_evidence_already_in_hand
```

（那一轮里 `test_the_ollama_leg_still_replays_the_dict_arguments`、
`test_a_denied_current_round_keeps_the_hard_copy_even_with_evidence_in_hand`、
`test_payload_does_not_mutate_the_request` 三枚**本来就是绿的**——它们钉的是「不许变」的那一侧，
红的是缺映射的那五枚 + N-3 那一枚。这六枚正是 #12b 与 N-3 的「今天写出来必红」证据。）

修复后：`-k "OpenAIMultiTurnReplay"` ⇒ **8 passed**；`-k "AgentNoCapableFastPath or OpenAIMultiTurnReplay"`
⇒ **21 passed / 5 subtests**；门 1 ⇒ **409 passed / 0 failed**；两种 cwd 全套件 ⇒ **928 / 0 / 974**。
（**修复轮就地更正计数**：那枚 `-k` 复跑实测是 **23**（`OpenAIMultiTurnReplayTests` 8 +
`AgentNoCapableFastPathTests` 15），段 B 报的 21 是「两枚 N-3 例刚加进类比 -k 计数更早一拍」的
陈旧数——与评审 Minor 10 同族（计数漂移，不是不实自述）。修复轮 +1 枚 I-1 用例后为 **24**。）

**结论口径**：#12b 的承载证据是**出口体**（MockTransport 录到的第二轮 JSON），不是「函数被调用」；
真云 400 是否消失仍要等 key（C1/C4），本段不越权改判那四枚 `PENDING_EXTERNAL`。

## FIX-B2（N-3）：判据查实结论 + 红 → 绿证据

**先查再动**：权威实现 `backend/app/conversation_agent.py:307-321` 那三支的条件看的是
「**本轮检索结果**」，不是「全链路在手证据」——依据三条：
① `status` 只由本函数 `:233-268` 那**一次** `tool_registry.execute` 的 try/except 决定；
② 参与判据的 `evidence` 在 `:273-278` 由**同一个** `result` 现算（`_with_citation_indexes`
之后重新赋值，不累加任何外部盒子）；
③ 调用点 `_local_fast_path` 只有 `round=0`、**没有工具回路**（`:209-230` 直接后端替执行），
所以对权威而言「本轮 == 全链路」，两种读法在它身上**恒等价**、分不出主从。
⇒ 「与权威对齐（只看本轮）」在降级腿这里不可实施：`agent.py` 的 `evidence` 是 `run_agent`
传进来的**累加盒**（`:521-530` 每轮 append + `evidence_keys` 去重），照抄判据等于把上一轮
已授权证据丢掉，而 `:601` 自己写的理由正是「证据已在手」——这才是那处自相矛盾。
**故选 brief 的方案 ②**：短路前加「`evidence` 非空 ⇒ 继续合成」的门，并把合成 prompt 的
dump 从「本轮空壳」换成 `synthesis_evidence = 本轮有货用本轮的，否则用在手的`。

- `status == "DENIED"` **不吃**这枚门：仍然零外呼、零账行、同源硬文案（I-3 的拒绝面一字未松），
  并由 `test_a_denied_current_round_keeps_the_hard_copy_even_with_evidence_in_hand` 专门挡「把门
  写成 `status != "SUCCESS"` 的通用形式」这条偷懒路。
- 本轮失败这件事**没有被掩盖**：`tool_end(status="FAILED", result_count=0)` 事件、`TOOL_RESULT`
  审计、以及新注记 `NO_CAPABLE_MODEL→fast_path_failed_with_evidence`（`stage="degraded_synthesis"`，
  理由码仍只用冻结枚举）都留着；`num_sources` 与文案现在同源（在手的 2）。
- 红 → 绿：修复前该例红在第一枚断言
  （`AssertionError: '企业知识检索暂时失败，请稍后重试。' == '企业知识检索暂时失败，请稍后重试。'`）；
  修复后 `AgentNoCapableFastPathTests` 全类 15 枚（含 I-3 那枚三支 subTest 表）**全绿**。

## 矩阵变更前后对照（`docs/MODEL_ROUTER_V23_MATRIX.md`）

| 位置 | 段 A（前） | 段 B（后） |
| --- | --- | --- |
| 表头标题 | 「Task 9 段 A 收口」 | 「段 A 收口 + 段 B 两件产品修复」，并写明段 B 的两件与 `#12b` 转 GREEN |
| 诚实口径段 | 「`BLOCKED` 用于真机 P0 **与多轮回放的协议缺陷**」 | 「`BLOCKED` 只用于真机 P0」；那句「配 key 就能用工具轮」的反驳改成**已失效**（映射落地后才成立），云侧行为仍归 C1–C4 |
| 行 `12b` | 承载测试 = 「待补：类 `OpenAIMultiTurnReplayTests`」，状态 **BLOCKED** | 7 枚真实 node-id（json-string / tool_call_id 配对 / 异名 / 同名次序 / 同名优先位置 / 空 id 不造假 / 幂等），状态 **GREEN** |
| 行 `13` | 两枚 `ToolCall` 标准化例 | 追加 `OpenAIMultiTurnReplayTests::test_the_ollama_leg_still_replays_the_dict_arguments`（「#12b 的映射不许牵连这条腿」） |
| 新行 `N-3` | 不存在（原来只写在 §4 的「待段 B」清单里） | 新增移交项行（非 §10 冻结行），两枚承载例 + GREEN；`MatrixDocumentClosureTests` 逐行核对它 |
| §4 | 「待段 B / 待用户裁决」三件（#12b、N-3、P0） | 改成「段 B 已交付的两件 + 仍在表外的三件」（P0 / `env_file` 绝对化 / `llm_registry_file` 包相对） |
| §5 | 「两种 cwd 同数 **918/0/973**」 | 「**928/0/974**」+ 增量拆解（+10 例、+1 subtest 的来源） |
| 行 `1..11, 14..19, P0, C1..C4` | — | **一字未改**（#17/#18 逐行复核过：I-4 只动 router 腿的 OpenAI 出口、N-3 只动降级腿的判据，legacy 三链的报文与九键面都不经过这两处 ⇒ 承载例继续原样为真）；四枚云行**仍是** `PENDING_EXTERNAL`，`P0` 仍是 `BLOCKED` |

## 变异表（8 发，`task9b_mutations.py`；**0 存活**）

| 发 | 打点 | 期望 | 结果（pytest 尾行） |
| --- | --- | --- | --- |
| M1 | 回退 B1 的 `json.dumps`（`arguments` 仍以 dict 出口） | RED | **KILLED** `4 failed, 4 passed` |
| M2 | 去掉 `tool_call_id` 配对（`_paired_tool_receipt` 直接 return None） | RED | **KILLED** `5 failed, 3 passed` |
| M3 | 把 B2 的门删掉（`elif status != "SUCCESS":` 原状） | RED | **KILLED** `1 failed, 2 passed, 3 subtests` |
| M4 | 把 DENIED 支并进失败文案（`if False:` 吃掉拒绝面） | RED | **KILLED** `2 failed, 2 passed, 2 subtests`（I-3 的 DENIED subTest + N-3 的 DENIED 例同时红） |
| M5 | 配对退化成位置优先（去掉同名判断） | RED | **KILLED** `1 failed, 7 passed`（乱序回执那枚） |
| M6 | 映射就地改调用方对象（`message = raw`） | RED | **KILLED** `2 failed, 7 passed`（升级后的 `payload_does_not_mutate` + 幂等例） |
| M7 | 留着门但 dump 仍取本轮空壳（只有 `num_sources` 好看） | RED | **KILLED** `1 failed, 2 passed, 3 subtests` |
| M8 | 空 id 也照配（造 `tool_call_id: ""`） | RED | **KILLED** `1 failed, 7 passed` |

每发都是「读原始字节 → 断言恰命中一次 → 落盘 → 跑子集 → **发内**还原 → 核对 sha1 回到段 B 终值」；
八发跑完 `normalize.py=6e8a345ff322`、`agent.py=9dabebf801ed`（`crlf=1044 / lf=1044`）逐发核对一致。

## 冻结件 sha1 前后表

| 文件 | 段 A 终值 | 段 B 终值 | 判定 |
| --- | --- | --- | --- |
| `backend/app/llm/normalize.py` | `c6bc8b0caf81` | `6e8a345ff322` | **本段义务面**（I-4） |
| `backend/app/agent.py` | `59d4cd3b3c3b`（CRLF 1000/1000） | `9dabebf801ed`（CRLF 1044/1044，零裸 LF） | **本段义务面**（N-3），行尾未翻 |
| `backend/app/llm/fallback.py` | `008d8213bc05` | `008d8213bc05` | IDENTICAL |
| `backend/app/llm/usage.py` | `8a8f5b0cff28` | `8a8f5b0cff28` | IDENTICAL |
| `backend/app/llm/__init__.py` | `c29e3c393f87` | `c29e3c393f87` | IDENTICAL |
| `backend/app/rag.py` | `a5a638716947` | `a5a638716947` | IDENTICAL |
| `backend/app/conversation_agent.py` | `0ffcc353eb59` | `0ffcc353eb59` | IDENTICAL（禁改件） |
| `backend/app/agent_routes.py` | `1080fbd4a0c4` | `1080fbd4a0c4` | IDENTICAL（禁改件） |
| `backend/app/security.py` | `d36b387aac6e` | `d36b387aac6e` | IDENTICAL（禁改件） |
| `backend/config/llm_registry.json` | `3e652e9cf496` | `3e652e9cf496` | IDENTICAL |
| `backend/tests/conftest.py` | `73d1060de465` | `73d1060de465` | IDENTICAL（护栏一字未改） |
| `backend/tests/test_model_router_v23_contract.py` | `387f90eb1537` | `a4e99e2a3944` | 测试侧新增（LF 保持） |
| `backend/tests/test_llm_egress_guard.py` | `9404e6ab01c0` | `9404e6ab01c0` | 段 A 件，本段未动 |
| `docs/MODEL_ROUTER_V23_MATRIX.md` | `712467ee2850` | `46b607d97d39` | 矩阵回写（LF 保持） |

D6 三层等式与豁免表**未改一行**：段 B 没新增/删除任何 `app/` 出口，新增文字里也不含
`/api/chat`、`_API_KEY`、`httpx`、端点字面量等被扫模式 ⇒ `test_llm_egress_guard.py` 29 枚
（含豁免互等与「全文 == 代码 + 散文」）继续原样绿。

## 我没有做的事（以及为什么）

1. **没动 `app/agent.py` 的消息回放形状**、没动 `LLMResponse`/`ToolCall`/`_message_from_response`
   （§6 冻结：协议差异归 provider 层）。I-4 的全部修改都在 `openai_payload` 出口前。
2. **没动 `ollama_payload`**：它不需要映射；只用一枚用例证明这条腿仍吃 dict、未被牵连。
3. **没动 `app/conversation_agent.py`**：N-3 只改 `agent.py`（禁改件清单）。权威实现本身没有
   跨轮累加，所以它没有同一个缺陷。
4. **没动 `app/config.py` 的 `env_file=".env"`**（主 agent 已裁本版不改）、**没加 `unknown_rate`**
   （T5 终裁）、**没动** `fallback.py` / `usage.py` / `__init__.py` / `agent_routes.py` /
   `security.py` / `llm_registry.json` / `conftest.py`（sha1 佐证）。
5. **没把任何云侧行改绿**：C1/C2/C3/C4 继续 `PENDING_EXTERNAL`，`P0` 继续 `BLOCKED`；
   #12b 的绿只声称「出口体合协议」，不声称真连已验。
6. **没做 git 写**、没起宿主服务、没跑前端 build、没打 11434（真 Ollama 在跑但我一次都没碰）。
7. **没削弱任何既有断言**：唯一改到的既有例是升级；全套件 918 → 928 只增不减。

## 移交终审的 minor（段 B 发现，未擅自扩权）

- **m-B1｜`DENIED` + 在手证据的一致性**：这一支仍回硬文案而 `num_sources` 记在手的量
  （与 N-3 修掉的那处同形）。段 B 按指令**优先保拒绝面**（零外呼 + 硬文案一字未松），
  没顺手收紧也没顺手放宽；要不要给 DENIED 也配一枚「文案 + 来源」一致性口径，请终审裁。
  ~~现状已被 `test_a_denied_current_round_keeps_the_hard_copy_even_with_evidence_in_hand`
  钉住（可观察、不是哑的）。~~
  **【修复轮就地更正 · 评审 I-3】上面这句划掉的话在段 B 交付时不成立**：那枚用例当时断言的
  只有 `answer` 硬文案等式 / `requests == []` / `raw_rows() == []` / `len(trace_rows()) == 1` /
  `note` / `tool_status` 这六件事，**一条都没碰 `num_sources` 或 `sources`** ⇒ 「已被钉住」其实
  是把「例子的返回值里有 `num_sources=2`」当成了「例子断言了它」，现状当时是**哑的**。
  现在这句话才成立：修复轮已在该例末尾补两枚断言
  （`self.assertEqual(2, result["num_sources"])` + `self.assertIn("无权访问", result["answer"])`），
  并写明这是**刻意保留**的不同源（拒绝面优先）；`docs/MODEL_ROUTER_V23_MATRIX.md` §4 的
  那句「遗留 minor」也同步改成「现状已钉住、是否统一待终审」。
- **m-B2｜降级腿「本轮 SUCCESS 但零行 + 前轮有货」的 dump 形状变了**：以前 dump 的是 `[]`
  （模型拿到空证据 + 累加盒里 2 枚，答案质量必然差），现在 dump 的是在手的 2 枚。
  这是 N-3 那枚门的自然推论（同一处代码、同一判据），出厂注册表下不可达；记下来供 #18 复验时知情。
- **m-B3｜`_pairable_id` 的取舍**：空 id（老版 Ollama 不回 id）时**不**合成 `tool_call_id`，
  于是那种报文发到 OpenAI 兼容腿仍会 400。刻意选「宁缺不错配 + 缺陷留在可观察处」，
  若终审想要「宁可造一个占位 id」，改一行即可（M8 那枚用例会反过来响）。
  **【修复轮补全披露 · 评审 I-1】**这句原来漏了半条：**且不许跨槽**。段 B 的实现把
  「不可配对」放在 `_matching_call` 的槽扫描入口 ⇒ 「第 N 枚回执配第 N 枚调用」实际变成
  「配第 N 枚**可配对**调用」，空 id 调用被跳过后前一枚回执会领走后一枚调用的 id
  （评审探针 P10 实测 `['k2', None]`）。修复轮把可配对性移到**选出槽之后**（先占槽再判），
  承载例 `OpenAIMultiTurnReplayTests::test_a_call_with_an_empty_id_does_not_let_a_later_call_steal_its_receipt`。
- **m-B4｜`data/audit.jsonl` 不在 `conftest.py` 护栏的保护集里**：真实审计文件会被个别既有套件
  （LOGIN/AUTHORIZATION 那类用例）追加行——**段 B 之前就是如此**（我的新用例全在
  `_AgentMigrationFixture` 下，`AUDIT_PATH` 已改道临时目录）。会话库三枚计数复核仍是 0/7/10。
  若要把审计文件也纳入护栏，属 `conftest.py` 的改动，需另案。
- **m-B5｜brief 里 `agent.py:598-601` 的行号**在段 B 之后整体下移（`598-623` 一带），
  评审引用的行号请按 §4 与函数名 `_degrade_to_local_fast_path` 定位，别按裸行号。

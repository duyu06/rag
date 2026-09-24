# Task 7 修复轮 1 —— scoped 复审裁定（轮 1 / 独立复现）

复审者：Task 7 修复轮 1 的 scoped 复审（只读 + 定向跑 + 本文件；`backend/` 零改动，sha1 见 §5）。
范围 = 委托方点定的六件，不扩面。所有结论都来自**我自己跑出来的结果**；修复者的自述一律按待验证断言处理。
零真实外呼（11434 一次都没打；全部证据来自 `httpx.MockTransport` 录下的 `self.requests`）；零 git 写。

---

## 1. Verdict

**PASS-with-minors** —— 放行 T8。

四件 Important 里落在本轮的三件（I-1 / I-2 / I-4）**全部 ADDRESSED，且我用自己的锚点独立复现了两枚关键变异从
"存活" 变 "被杀"**；I-3 的文档回写（DESIGN §9.1 + §10 #18 + 测试 docstring 的口径出处）已落地并可追。
护栏第三道闸是**双向钉**（两个方向的变异我都打过，各红）。改动面诚实：本轮实际写入 = 报告所列的五件，
`app/llm/*` 十三件对 `snap-task6` **逐字节 SAME**（含 `fallback.py=008d8213bc05`），真实库前后 sha1/行数不变。
新发现 3 件，全部 Minor 级、不阻断 T8（见 §3），其中 **N-B（`snap-task7` 被就地刷新到修复后终态、报告未披露）**
是我最担心的一件：它把"评审基线"从世界上抹掉了，导致本轮「既有断言 0 放宽」只能语义核对、**不能机器 diff**。

---

## 2. 六件逐项裁定

| # | 项 | 裁定 | 我的证据 |
| --- | --- | --- | --- |
| 1 | 独立复现 `M3b` / `M5a` + 自打新发 | **ADDRESSED** | 六发全 RED、存活 0（§4 表）。`X1`（流式腿删 `temperature=`）= 我**另写**的字节锚点（整行连 `\r\n` 删掉，与修复者的锚点不同形）⇒ **1 failed / 20 passed**，杀手恰是 `test_the_legacy_ndjson_streaming_payload_is_reproduced_on_the_wire`；`X2`（ttft 零点换 `llm_started`）⇒ **1 failed / 9 passed**，杀手恰是 `test_ttft_is_recorded_at_the_first_content_chunk`。新发四枚：`X3` 删 `agent_routes` 的 D5 支、`X4` 把该支**整体挪到 generic 支之后**（真·顺序写反，非改名）、`X5` 把 `conversation_stream_routes` 的 D5 支认错类、`X6`/`X7` 第三道闸的两个方向 ⇒ **全部 RED**，且 `X4` 证明**分支顺序本身有牙**（不只是"有分支"）。 |
| 2 | FIX-3 的语义正确性 | **ADDRESSED**（①-⑤ 逐条成立） | 见 §2-A 展开。 |
| 3 | FIX-1 的钉是否有牙 | **ADDRESSED** | `test_model_router_v23_contract.py:5565-5570`：三枚按序 `assertEqual(1, len(seen))` → **`assertIn("temperature", seen[0])`（键存在性）** → `assertEqual(产品常量, seen[0]["temperature"])`（值等式）⇒ 两枚都在，漏参与传错值是**分开的两发红**。spy 包的是**真实现**（`return real_stream(*args, **kwargs)`，`mock.patch.object(llm, "stream", spy)`）⇒ 不改行为、报文面三枚既有等式（5553-5559：产品常量 / 独立写死 0.2 / `!= RAG_LEGACY_TEMPERATURE`）一字节未动。注释 `conversation_agent.py:72-81` 已与事实相符：明说"两腿各钉两个面 ①报文 ②调用"、写明因果（形参默认与字段默认都是 0.2 ⇒ 漏参在报文面不可见）、并如实标注"补钉之前流式腿漏参照样全绿 = 变异 M3b 存活"；落点句"非流式腿 `SseBufferedAndLegacyTests`、流式腿 `SseStreamContractTests`（两枚温度例各自钉满 ①+②）"我逐枚验过（5949 与 5522 两例都含 ①+②）⇒ **无假话**。 |
| 4 | FIX-2 的轴差钉 | **ADDRESSED**（走的是评审首选的**行为钉**，不是静态 `assertIn`） | 注入量 40ms 是**真实** `time.sleep`（`_StubToolRegistry.execute`，`test_model_router_v23_contract.py:5281-5282`），且 `sleep_ms` 默认 0、全文件只有 5592 一处传非零 ⇒ 其余用例零污染。三枚新事实：`retrieval_ms >= 40-2`（5606，**反退化**：注入没生效就红，所以后面那枚不是恒真）、`timings.ttft_ms > 账本 ttft_ms`（5608，反"合并零点"）、`轴差 >= retrieval_ms - 2.0`（5611，**包含检索**这件事）。`TTFT_AXIS_EPSILON_MS = 2.0` 且方向是**下界** ⇒ 放宽只能靠加大 eps，而 eps 就是 2ms；`SSE_GENERATION_SLEEP_MS=150` **不参与任何断言**（只把两段拉开距离，5204/5588）。既有断言一枚未削：`assertGreaterEqual(ttft, 0)`、`assertLessEqual(ttft, llm_ms)`、`assertEqual(1, len(rows))`、`assertIsNotNone(rows[0]["ttft_ms"])` 全在（5596-5603），与评审 §I-2 记录的原断言集合逐枚对得上。**独立复现**：`X2` RED ⇒ 换零点确实被这条例杀掉。限制见 §3 N-B（无法机械 diff 到评审版）。 |
| 5 | 护栏第三道闸 | **ADDRESSED** | `conftest.py:229-245` `guarded_connect`：`ensure_schema` 为真（默认）⇒ 进 `_write_scope()`；`ensure_schema=False` ⇒ 直连不判写。`usage._connect` 的 `ensure_schema` 是 **keyword-only**（`usage.py:1012`），`kwargs.get(...)` 读得到，不存在"位置参数绕过"。双向归类钉在同一枚例里两向齐下（`test_a_direct_schema_connect_is_classified_write_too`：`_connect(None)` ⇒ `[(src,dst,write)]` + `violations()==1`；随后 `_connect(None, ensure_schema=False)` ⇒ 第二笔记 `read`）+ 既有 `test_a_pure_read_…`（`violations()==()`）与 `test_a_real_write_…`（`violations()==1`）。**我两向都打了**：`X6`（默认值翻成 False = 撤闸）⇒ 1 failed（`write_too` 红）；`X7`（恒 write）⇒ **2 failed**（`write_too` + `pure_read` 一起红）⇒ 两向都不是恒真。`conftest.py` 仍**纯 LF**（404 个换行 / 0 CRLF，我实算），docstring 的「已知边界」段已回写第三道闸（46-56 行）。**没削弱别的测试**：我抽两族亲跑 `tests/test_llm_usage_contract.py tests/test_chat_persistence_contract.py` ⇒ **102 passed / 0 failed / 33 subtests / 45.93s**。 |
| 6 | 改动面与报告诚实 | **ADDRESSED**（两处口径要补，见 §3） | 我把 `snap-task6` ↔ 工作树逐字节比了全部 19 件：**17 件 SAME**，其中 `app/llm/{fallback,usage,router,classifier,registry,provider,normalize,models,errors,health,__init__}.py`、`app/rag.py`、`app/security.py`、`app/agent.py`、`app/agent_trace.py`、`app/main.py`、`tests/test_llm_usage_contract.py` **全部未动**（`fallback.py=008d8213bc05` 字节冻结成立）；只有 `conftest.py`（`83cfa7ae3bcf→73d1060de465`）与 `test_model_router_v23_contract.py`（`3f06baaa502e→5dac328f8736`）不同 = 本任务窗口的应然改动。`snap-task7`（23 件）↔ 工作树 **23/23 SAME、零缺失** ⇒ 报告 §2 表里五件之外的文件本轮没被写过。行尾事实逐枚复核与我实算一致：`agent_routes.py` 117 CRLF / 69 裸 LF（混合未被翻转）、`conversation_agent.py` 601 CRLF / **0 裸 LF**、`conftest.py` 0 CRLF、契约测试 0 CRLF。`.pyc` 残骸：`find backend -name "*native_stream*"` **归零**（我自己跑了 7 发变异 + 8 次 pytest 之后仍然归零），`app/native_stream.py` 不存在。报告"7 发全 RED 存活 0"：`t7fix_r1_mutation_lab.log` 里 7 个 `###` 头、**零** `GREEN/SURVIVED`、收尾三文件 sha1 全 OK ⇒ 与自述相符；证据来源写的是它自己的 `t7fix_r1_mutations.py` + 日志（**如实**，且我已独立复现其中的 M3b/M5a/N4 三发）。改动面按**本任务窗口**重列（§2 那节把 `agent_routes.py` 标为"经主 agent 明确授权的扩面"、并单列 `.pyc` 删除）⇒ 委托方要求的"按窗口重列"成立。 |

### §2-A：FIX-3 五个子条件逐条

| 子条 | 裁定 | 证据 |
| --- | --- | --- |
| ① 排在 generic `except Exception` **之前** | **成立** | `agent_routes.py:116`（D5）vs `:137`（generic）；`StreamInterrupted` 是 `Exception` 直接子类（`fallback.py:257`）**不是** `ValueError` 子类 ⇒ `:114` 的 `except ValueError` 不会先吞掉它。`X4`（把 D5 支整体挪到 generic 之后）⇒ **RED** ⇒ 顺序不是"顺手写成这样"，是钉住的。 |
| ② 事件名与 payload 键同形、**无新增事件类型** | **成立** | 两支的 `error` 键集合**逐字相等**：`{detail, status, stream_committed, error_type}`（`agent_routes.py:125-130` ↔ `conversation_stream_routes.py:131-136`），并由新例的跨出口等式钉住（`test_...second_sse_egress...:6295`）。事件名只有 `error` + `done`。`KNOWN_SSE_EVENTS | {"start"}` 不算放宽：`start` **迁移前就在**（`git show HEAD:backend/app/agent_routes.py` 第 113 行 `yield _sse("start", ...)`），我实核。`X3`/`X5`（任一支删/认错）⇒ 都 RED。 |
| ③ `stream_committed` / `error_type` 取值符合 §8.1 | **成立** | `stream_committed=True` 是 D5 支的**常量**（§7 冻结值），`grep client_aborted backend/app` 只命中 `usage.py` ⇒ 两枚账本哨兵仍**只有账本会写**，链与路由都不自写；`error_type=exc.error_type` 的值来自 `fallback.py:279` 的 `error.kind`（provider 归类）或执行器给的 `"unknown"`，路由只是**转发**。`X3`/`X5` 红的时候新例正是断在缺 `stream_committed` ⇒ 哨兵没被读成布尔位装饰。`stream_committed` 也不在 `app/llm/*` 里（评审 §5#2 的 grep 结论仍成立：`fallback.py` 本轮一字节未动）。 |
| ④ 中断后不被读成成功 / 不重说一遍 | **成立** | 路由侧：D5 支只 put `error`+`done(status="failed")`，成功那三段（`trace`/`sources`/`done(finish_reason="stop")`，`:101-113`）在异常后不可达；失败 `done` **没有** `finish_reason`，与成功形状可分辨。新例钉 `assertLess(names.index("token"), names.index("error"))` 且中断前只交付过 1 枚 chunk ⇒ 没重播。前端侧我自己读了 `frontend/src/lib/api.ts:452-489`：`error` 只取 `data.detail` 存进 `streamError`；`done` 经 `doneSignaled` 守卫**恰好一次** `onDone()`；末尾 `if (streamError) throw new Error(streamError)` 照旧 ⇒ 新增的 `done` 把"两次 onDone"的风险挡住了（改前是 `finally` 里补一次），也**没有**把中断读成成功。报告那句"前端只读事件名与 `error.detail`、不消费 `done` payload"成立。 |
| ⑤ 新例真走 `agent_query_stream`，不是自说自话 | **成立** | `drive_agent_route`（`:5452-5472`）取的是 `agent_routes_module.agent_query_stream(request, user=...)` 返回的 `StreamingResponse.body_iterator` ⇒ worker 线程 + 阻塞队列 + 新 `except` 支都是**真路由代码**。桩只有两枚：`run_conversation_agent` 与 `_validate_knowledge_base_scope`；而"成功段"与"真断流段"里那个桩内部调的 `real_ask` 走的是**真的** `conversation_agent.run_conversation_agent`。第三段用 `terminate=False` 让上游真断流、不手工造异常，并钉账本 `success=0`（`:6298-6304`）⇒ 新支不是死代码。 |

---

## 3. 新发现（定级 + 修法）

**N-B（Minor，但影响后续每一轮的取证能力）— `snap-task7` 被就地刷新到"修复后终态"，报告未披露，评审基线消失。**
事实：`snap-task7/` 23 个文件的 mtime 全部是 `09-24 09:23:37`（一次性重拷），且内容与**修复后**的工作树逐字节相同
（`agent_routes.py` 存的是 `1080fbd4a0c4`、`conftest.py` 是 `73d1060de465`、契约测试是 `5dac328f8736`）。
后果：评审 §8.1 记录的"Task 7 主体终态"（`c65937c0a841` / `4b1defdd5a21` / `df1717c548fc` / `c6fa6b806ec3`）
在工作树与快照里**都不复存在** ⇒ 本轮"既有断言 0 放宽、0 删除"这类话**只能语义核对、无法机械 diff**（我做第 4 项时
只能拿评审 §I-2 的文字描述去对，而不是拿旧文件去 diff）。顺带：报告 §5 的 Minor-3 移交句"快照没纳管
`agent_routes.py`/`conversation_stream_routes.py`"已经过时 —— 现在的 `snap-task7` **两枚都纳管了**。
修法：① 报告「修复轮 1」§2 补一行，如实记这次快照刷新与理由；② 从现在起定纪律：**快照只在开工前建、建成即只读**，
要在终态上重建基线就新开 `snap-task7-fix1/` 而不是覆盖 `snap-task7/`；③ T8 开工前第一件事 = 建 `snap-task8/`
（纳管 `agent.py`、`agent_routes.py`、`conversation_stream_routes.py`、`main_agent.py`、两份测试、`conftest.py`），
建完不许就地覆盖；④ 本轮**不需要**恢复旧基线（我用 `snap-task6` 的 19 件比对已足以证明改动面），但 T9/T11 若要做
"断言强度未降"的终审，得靠 `t7fix1-ca-diff.txt` 这类手工 diff 或重建快照，请提前安排。

**N-C（Minor）— 两支 SSE 出口的 `done` payload 对称性没有钉，只钉了 `error`。**
新例的跨出口等式只比 `error` 的键集合（`:6295`），`done` 侧两支本来就不同（主出口带 `message_id`/`message`，
本端点不落会话库 ⇒ 只有 `status`/两枚增量），代码注释（`agent_routes.py:132`）与报告都写清了理由，这是对的。
但"只有 `error` 对称"意味着**以后有人在某支的 `done` 上删掉 `error_type` 不会红**。修法（T9，两行）：新例里补
`assertEqual(set(other_done) - {"message_id", "message"}, set(done))`，或退一步两向各钉
`assertIn("stream_committed", done)` + `assertIn("error_type", done)`；同时在 V2.3 验收文档写那句
「两条 SSE 出口 / 一条收口，`error` 面逐字同形、`done` 面按各自会话语义」。

**N-D（观察，归 T9/T11）— Minor-5 只清了 `SseNativeStreamFieldFaceTests` 一枚，import 期读源码的同型件还在。**
`test_model_router_v23_contract.py:1830/1831/2681/2682` 的 `ROUTER_SOURCE` / `CLASSIFIER_SOURCE` /
`FALLBACK_SOURCE` / `PACKAGE_SOURCE` 仍是模块级 `read_text()`。本轮不受其害（那四个对象是 `app/llm/*`，冻结件、
我的变异也没打它们），但**T8 之后 `agent.py` 的静态面一旦出现 import 期读源码，同样会拿旧字节自证**。
修法：T9 收口时统一改成方法内 `read_text()`，或加一枚"mtime 变化 ⇒ 必须重读"的元测试（可与评审 Minor-4 的
可达性元测试同批）。

**顺带如实报告（不是产品缺陷）**：我自己的 7 发变异用字节读写 + 发内还原，跑完后四枚被碰过的文件
（`conversation_agent.py` / `agent_routes.py` / `conversation_stream_routes.py` / `conftest.py`）sha1 全部回到起始值，
但 **mtime 被我的还原写推进到了 09:54-09:57** ⇒ 从本文件时刻起，这个窗口内的 mtime 不能再用作改动面归因，
请一律走 §5 的 sha1 表（`snap-task6` / `snap-task7` 双尺子）。真实库我跑前跑后都点过：sha1 与行数不变（§5）。

---

## 4. 我这轮跑的变异（`rev7r1_mutations.py`，全部字节读写 + 锚点命中数恰好 1 + 发内还原 + sha1 核对；
X1-X6 的原始输出在日志 `rev7r1_mutations.log`，`X7` 是补跑的单发、终端输出记于本表）

| # | 变异（我自己的锚点） | 结果 | 杀手 |
| --- | --- | --- | --- |
| X1 | 流式腿删掉整行 `temperature=CONVERSATION_LEGACY_TEMPERATURE,`（= 评审 M3b，首轮存活） | **RED 1 failed / 20 passed** | `test_the_legacy_ndjson_streaming_payload_is_reproduced_on_the_wire` |
| X2 | ttft 零点 `started` → `llm_started`（= 评审 M5a，首轮存活） | **RED 1 failed / 9 passed** | `test_ttft_is_recorded_at_the_first_content_chunk` |
| X3 | `agent_routes.py` 的 D5 支**整支删除**（1461 字节） | **RED 1 failed / 4 passed** | `test_the_second_sse_egress_lands_the_same_d5_face_and_keeps_its_success_order` |
| X4 | `agent_routes.py` 的 D5 支**顺序挪到 generic 支之后**（新支成死码） | **RED 1 failed / 4 passed** | 同上 |
| X5 | `conversation_stream_routes.py` 的 D5 支改认 `ArithmeticError` | **RED 3 failed / 2 passed** | 主出口的 `error+done` 两枚 + **新例**（两支同形那枚） |
| X6 | 第三道闸默认值翻 False（= 撤闸方向） | **RED 1 failed / 3 passed** | `test_a_direct_schema_connect_is_classified_write_too` |
| X7 | 第三道闸恒判 write（早退摘掉） | **RED 2 failed / 2 passed** | `test_a_direct_schema_connect_is_classified_write_too` + `test_a_pure_read_is_classified_read_and_never_pins_red` |

**7 发全 RED、存活 0。** `X5` 的第三个杀手值得单独说一句：改坏**主**出口也会让**新**例红 —— 因为新例拿主出口做参照，
这两支的对称性是双向绑住的，不是各测各的。

---

## 5. 我实际执行的命令与 sha1 表

```
# 定向复现（cwd=E:/xiangmu/rag；变异脚本内部以 cwd=backend 跑 pytest）
python .superpowers/sdd/MODEL_ROUTER_V23_PLAN/rev7r1_mutations.py            # 6 发，全部 RED，日志 rev7r1_mutations.log
python .superpowers/sdd/MODEL_ROUTER_V23_PLAN/rev7r1_mutations.py X7_third_gate_always_write   # 第 7 发，RED
cd backend && python -m pytest tests/test_llm_usage_contract.py tests/test_chat_persistence_contract.py -q --no-header -p no:cacheprovider
   → 102 passed, 5 warnings, 33 subtests passed in 45.93s
PYTHONIOENCODING=utf-8 python（snap-task6 ↔ 工作树 19 件逐字节 / snap-task7 ↔ 工作树 23 件逐字节）→ 见 §5.1/§5.2
python（EOL 组成实算：conversation_agent / agent_routes / conftest / 契约测试）
find backend -name "*native_stream*"        → 空（跑完 7 发变异与 8 次 pytest 之后仍为空）
grep -rn "client_aborted" backend/app       → 只在 usage.py（链与路由都不自写哨兵）
git show HEAD:backend/app/agent_routes.py | grep _sse\("start"   → 第 113 行（`start` 是迁移前现行词汇）
git diff --stat HEAD -- backend/app/agent_routes.py backend/app/conversation_stream_routes.py   # 只读
只读 URI 点真库：backend/data/conversations.db  llm_request_logs=0 conversations=7 messages=10
                data/conversations.db          llm_request_logs=<no such table> conversations=0 messages=0
```

全套件我**没有**重跑（委托方已亲跑 837 passed / 0 failed / 880 subtests），两考卷的 334 我用例数做了构成核对
（`SseRoutePayloadTests` 5 枚、`LedgerGuardClassificationTests` 4 枚，与"+2 枚"自述一致）。

### 5.1 本轮终态 sha1（12 位前缀，全部我实算）

| 文件 | 评审基线（§8.1） | 工作树（本轮终态） | 判定 |
| --- | --- | --- | --- |
| `backend/app/agent_routes.py` | `c6fa6b806ec3`（评审未纳管，报告自述） | **`1080fbd4a0c4`** | FIX-3；117 CRLF / 69 裸 LF，混合行尾未翻转 ✓ |
| `backend/app/conversation_agent.py` | `c65937c0a841` | **`0ffcc353eb59`** | 仅注释块 4→10 行；601 CRLF / 0 裸 LF ✓ |
| `backend/tests/conftest.py` | `4b1defdd5a21` | **`73d1060de465`** | 第三道闸 + docstring；404 换行 / **0 CRLF** ✓ |
| `backend/tests/test_model_router_v23_contract.py` | `df1717c548fc` | **`5dac328f8736`** | FIX-1/2/3 钉；6308 换行 / 0 CRLF ✓ |
| `backend/app/conversation_stream_routes.py` | `c5cb5f9a6dde` | `c5cb5f9a6dde` | **未动**（我只碰过它做 `X5`，已字节复原） |
| `backend/app/llm/fallback.py` | `008d8213bc05` | `008d8213bc05` | 冻结成立；与 `snap-task6` SAME |
| `backend/app/rag.py` / `app/security.py` / `app/agent.py` | `a5a638716947` / `d36b387aac6e` / `419fa63f4c0d` | 同值 | 未动 ✓ |
| `backend/tests/test_p17_streaming_contract.py` | `808adcae4bea` | `808adcae4bea` | 本轮未动 ✓ |
| `backend/app/llm/{__init__,router,classifier,registry,usage,provider,normalize,models,errors,health}.py`、`app/agent_trace.py`、`app/main.py`、`app/knowledge_os.py`、`tests/test_llm_usage_contract.py` | — | 与 `snap-task6` **逐字节 SAME**（17/19 件 SAME） | 未动 ✓ |

真实库两份的 sha1 在我全部操作前后一致：`backend/data/conversations.db=39bca2c404e2`、`data/conversations.db=2a9f1ae63995`。

### 5.2 我留在计划目录的临时件（前缀 `rev7r1_`，不进产品树）

`rev7r1_mutations.py`、`rev7r1_mutations.log`、本文件。

---

## 6. 移交 T8 / T9 / T11 的口径（本轮增量；评审 §7 原有条目继续有效）

**给 T8**
1. 流式腿的**调用面 spy 模板已经现成**：`test_the_legacy_ndjson_streaming_payload_is_reproduced_on_the_wire`
   （`:5535-5570`）。`agent.py::_ollama_chat` 迁移时两腿各照抄一份，三枚断言按序（`len(seen)==1` /
   `assertIn("temperature", seen[0])` / 值等式），温度用 **agent 链自己的现值**（`app/agent.py:65`，现 0.2），
   不许套 `RAG_LEGACY_TEMPERATURE`（0.1）。
2. 新加/改动的 SSE 出口**必须两支对称**：如果 T8 之后 `agent_routes` 的 SSE 腿改了，`test_the_second_sse_egress…`
   里那条跨出口 `error` 键集合等式会红 —— 那是**故意的**，别放宽它，改测试前先判一次语义（并见 §3 N-C）。
3. **快照纪律**：`snap-task8/` 在动第一行代码之前建，建成即只读，**不许就地刷新**（本轮 N-B 的教训）。
   纳管清单：`app/agent.py`、`app/agent_routes.py`、`app/conversation_stream_routes.py`、`app/main_agent.py`、
   `tests/conftest.py`、`tests/test_model_router_v23_contract.py`、`tests/test_agent_contracts.py`、
   `tests/test_p17_streaming_contract.py`、`app/llm/*`（冻结件全量）。
4. 字节安全：`conftest.py` 与契约测试是未跟踪文件（`core.autocrlf` 无效），`agent_routes.py` 是**混合行尾**文件
   ⇒ 锚点必须带显式 `\r\n` / `\n`，整文件换行转换一律禁止（本窗口 `fallback.py` 的 943 行假差异就是前车之鉴）。
5. 交付前自跑三发变异并把结果贴进报告：删 `temperature=`（两腿各一发）、删/挪 D5 支、删 `attach_model_route`。
   我这七个锚点可以直接改用上（`rev7r1_mutations.py` 的 `X1`/`X3`/`X4` 就是这三类）。

**给 T9**
6. §3 N-C：两支 SSE 出口的 `done` 对称性补一枚钉（键集合差显式写成 `{"message_id","message"}` 的等式）。
7. §3 N-D：import 期读源码的同型件（`ROUTER_SOURCE`/`CLASSIFIER_SOURCE`/`FALLBACK_SOURCE`/`PACKAGE_SOURCE`）
   改方法内读，或与评审 Minor-4 的可达性元测试同批处理。
8. 护栏现在**三道闸**（`database_path` / `_execute` / `_connect`）：T9 的收口口径按"直连建表也是写"执行；
   本轮修复者自报的新观感（读改道 warning 出处报成 `conftest.py:243`，因为栈深了一层）请在 T9 顺手用
   `stacklevel`/显式 `_warn` 修准 —— 它不影响判定，只影响可读性。
9. 评审 §7 第 6/7/8 条（执行器侧 D5 变异正式进矩阵 #11 证据表、`tokens=0` 与 `llm_calls=1` 两个记账口径判一次）
   继续有效；I-4 已按方案①落地 ⇒ 第 7 条现在只剩"在验收文档留字"，不再是"要不要做"。

**给 T10 / T11**
10. T10 真机 SSE 复测的边界不变：`stream_committed` 不许出现在 pre-commit 那一次的 `error` payload 上；
    `model_used`/账本 `model` 必须是生效模型名。
11. T11 终审正文必须有：DESIGN §9.1 那句「`LLM_ROUTER_ENABLED=false` 不覆盖对话链流式腿与 agent 工具轮」，
    外加**本轮新证据**：`/api/agent/query/stream` 与 `/api/conversations/{id}/messages/stream`
    两条 SSE 出口现在**共用同一套 D5 收口形状**（"一条收口"已被代码与测试实现，文档只需点名）。
12. T11 若要给"断言强度未降"下结论，请注意 §3 N-B：Task 7 主体终态的四枚 sha1 已被就地刷新覆盖，
    机械 diff 不可用；结论必须写明依据是 `snap-task6` 的冻结面 + 语义核对（或补做一次人工 diff 归档）。

---

## 7. 一句话结论

I-1 / I-2 / I-4 三枚钉**都长出了牙**（我用自己写的 7 发变异逐一把红复现，含两支 SSE 出口的"删支/顺序写反/认错类"
三个方向），护栏第三道闸双向可杀且没削弱任何既有测试（102 passed 抽验），改动面与报告自述一致且冻结件字节未动。
**放行 T8**；三条 Minor（快照基线被覆盖 / `done` 侧对称性未钉 / import 期读源码的同型件残留）分别归
快照纪律、T9、T9-T11，不阻断。

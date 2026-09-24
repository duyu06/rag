# Task 8 修复轮 1 复审裁定（scoped：R1 六件 + A/B 两件）

复审者：独立复审者（非实现者、非主 agent、非首轮评审者所属同一人）。日期：2026-09-24。
被评审件：`backend/app/agent.py`（**sha1 `59d4cd3b3c3b`**，1000 行全 CRLF、`bare_lf=0`、50,371 B、AST 通过）
+ `tests/test_model_router_v23_contract.py`（`41506ab66166`）+ `tests/test_agent_contracts.py`（`d32e110d8a39`）。
基线：`snap-task8/`（本轮起点，`agent.py` = `9760d3509ed5`）。
方法：定向测试 + **自建探针 7 发**（P1–P7）+ **自建字节变异台 6 发**（M1–M6，全部发内还原 + sha1 核对）。
约束自证：`backend/` 与 `frontend/` **零修改**（终态 25 枚 sha1 与开工初值逐枚一致，见 §6）；零 git 写；
零真实外呼（全部复用 fixture 的 `httpx.MockTransport` + `guard_legacy_egress_off` 硬闸，11434 一次未打）；
审计/trace 两条文件出口由 fixture 改道临时目录（真实 `agent_traces.jsonl` mtime 仍 `2026-09-23T15:58`、
最后一条 agent 面审计仍 `2026-09-23T07:58:39Z`）；脚本全在 SDD 目录、前缀 `rev8r1_`；全套件未重跑。

---

## 1. Verdict

# **PASS-with-minors**（放行 T9；无需第 2 轮修复轮）

一句话理由：**首轮 1 Critical + 3 Important（I-1/I-2/I-3）+ m-6 全部独立复现为「真封住/真等价」**——
我自己造的溢出输入下 C-1 五件套全中（不 503 / trace 恰 1 行 / 两枚注记 / `QUERY` 成对 / 既有中文文案），
I-3 三支与 `conversation_agent.py:317/319/321` **逐字节同源**且零外呼零账，I-1 九键写成**双向等式**
（成功支与降级支各被一发独立设计的变异打死），I-2 双重累加下界实测不为负；
6 发变异**全 KILLED、存活 0**，且定向 393/0/360、collected 889、改动面「24 identical + 恰好 3 DIFFERS」
全部与自报**逐字吻合**（自报可信度高，见 B 件）。新发现只有 **3 枚 Minor**（观测面措辞过强 1、
降级腿检索失败时丢弃在手证据 1、报告行号引错 1），都在出厂形态下不可达或不影响任何冻结义务，
可在 T9/T11 顺带处理，不构成放行阻断。

**放行前置**：本报告 §5 的 T9 口径 1–8 必须进 T9 任务书（尤其 I-4 与 m-9 的归属、以及 §6 清单里
两项「靠 T8 修复轮才补齐」的口径现在要写成文档化验收行）。

---

## 2. R1 六件 + A/B 两件：逐项判定表

| # | 项 | 判定 | 关键证据（文件:行号 / 我跑出的输出） |
|---|---|---|---|
| R1.1 | C-1 降级腿第二道 catch 是否真封住 | **ADDRESSED** | 探针 **P1**（自建输入，不抄修复者的 `overflowing_evidence()`）：`answer="当前没有获得足够证据生成可靠答案。"`、`trace_rows=1`、`downgrade_notes=2` 且 `stage` 依次 `capability`→`context`、`audit=[TOOL_CALL,TOOL_RESULT,QUERY]`、`egress_calls=0`、`ledger_rows=0`；`call_http_face()` **未抛 HTTPException**。变异 **M1（删新 except）⇒ KILLED**（3 failed，正是评审点名的两例 + 源面第二张网）。标定副产：**2×4000 字符证据不触发溢出**（合成正常成功），必须 ≈15.7k 字符才复现 ⇒ C-1 触发有门槛但门槛在默认值一侧（见 §3 N-0 注） |
| R1.2 | m-6「stage=context 不重跑检索」 | **ADDRESSED** | 探针 **P2.mid_context**：第 2 轮 `stage=context` ⇒ `tools.names=["enterprise_search"]`（**恰 1 次**，即工具轮那次）、`TOOL_CALL` 审计 1 笔、`model_route` 在位、合成外呼 1 次。语义未被改：P2.round1_capability 显示 `stage=capability` 首轮仍完整跑降级检索（出厂形态**必然**先撞 `capability`，因 tools 档零候选）；变异 **M4 ⇒ KILLED**（2 failed） |
| R1.3 | I-3 三支与 `_local_fast_path` 等价 | **ADDRESSED** | **逐字**比对（我自己从 `conversation_agent.py` 抽行，不靠测试自证）：317/319/321 三句与 `agent.py:596/599/602` **完全相同**。探针 **P3** 三支各测：`answer_matches_authoritative_copy=true`、`egress=0`、`ledger_rows=0`、`model_route_attached=false`、注记 2 枚且末枚 `note` 分别 `…_denied`/`…_failed`/`…_no_evidence`、`tool_status` 三态可区分、`reason_codes=["NO_CAPABLE_MODEL"]`（无新词表）。变异 **M2（删整段短路 = 恢复修复前形态）⇒ KILLED**（4 failed：源面 1 + 3 个 subTest），且 M2 的失败信息**实测复现了首轮 I-3 的症状**——DENIED 路答案变成模型输出 `差旅住宿上限每天陆佰元 [1]。`。⚠ 一处措辞过强 ⇒ 新发现 **N-1** |
| R1.4 | I-2 `tool_time` 盒子覆盖与下界 | **ADDRESSED** | 落点覆盖：`agent.py:551` 在 try/except **之后无条件**写盒 ⇒ 降级腿那次检索的 SUCCESS/FAILED/DENIED 三条出口**全部**入账（降级函数内只有这一枚工具落点）。下界：探针 **P4.both_legs**（工具回路 404.76ms + 降级腿 400.36ms **同一请求**）⇒ `elapsed=836.63`、`generation=31.5ms`（= 836.63−805.12，两笔都扣、**无双重扣减、无负数**）；P4.clamped（两笔各 1.5s）⇒ 23.4ms 仍为正，`max(…,0.0)` + `if model_ms > 1` 保证最坏情形是**键消失**而不是负值。变异 **M5 ⇒ KILLED**（`leg='D2 降级腿'` subTest 红） |
| R1.5 | I-1 九键**等式** | **ADDRESSED** | 收尾腿改为与主降级门同形（`agent.py:896` `route_out=outcomes`），`test_the_limit_leg_route_also_lands_nine_keys` 用 `assertEqual(full_face, set(row))` 钉**键集合等式**（非存在性），两支各一枚。双向变异证明等式两半都有钉：**M3**（成功支传空盒）⇒ KILLED `branch='成功支（收尾腿正常生成）'`；**M6**（降级支传空盒 = 首轮原始缺陷形态）⇒ KILLED `branch='降级支…'`。首轮存活的 **G2 反向变异现已死亡**，与自报一致 |
| R1.6 | 有没有「为绿而放宽」 | **ADDRESSED（零放宽成立）** | 对 `snap-task8/` 逐枚比对：**identical=24 / DIFFERS 恰好 3**（`app/agent.py`、`test_model_router_v23_contract.py`、`test_agent_contracts.py`）⇒ 改动面自报精确。`test_agent_routing_contracts.py` **0 行 diff**；`test_feishu_identity_contract.py` sha1 仍 `145d81cbb342`。v23 文件 diff = **删除 1 行 / 新增 241 行**，而那 1 行是 `_RecordingToolExecutor.__init__` 的签名续行（被带默认值的两枚新形参替换，向后兼容）⇒ **被删的断言行数 = 0**，新增 `self.assert*` 49 枚。`test_agent_contracts.py` 为**纯增**（+31/−0），既有 `test_the_legacy_httpx_branch_is_still_here_verbatim` 与 `count("except NoCapableModelError as exc:")==2` 一字未动。附带核实 m-4 卫生：真实审计文件新增行只有 `LOGIN/AUTHORIZATION`（父会话后台全套件所致），agent 面 0 行 |
| **A** | **新不等价 / 误伤** | **无误伤（要求的那条形成了真）＋ 1 枚窄口径新缺口（Minor）** | 按任务书自己造「工具成功返回 2 条证据」的降级形状：探针 **P5.b**（第 1 轮真跑路由 + 工具 SUCCESS 2 条证据，第 2 轮零候选 ⇒ 降级腿再检索）**⇒ 仍走合成**（`answer=ROUTER_ANSWER`）、`model_route_attached=true`、`ledger_rows=1`、`copy_shortcut_notes=[]`（三支一枚都没沾）；P5.a 正常工具回路同样零短路。**结论：I-3 的三支没有把「工具轮正常失败但证据可用」那条路短路掉**——`not evidence` 读的是**累计**表，正是修复者在报告 465-466 行自陈的理由。但该理由只覆盖了 `not evidence` 一支：**P7** 实测「前轮已收 2 条证据 + 降级腿这次检索 FAILED」⇒ 答案变成「企业知识检索暂时失败…」，**在手证据被丢弃**，且响应体 `num_sources=2` 与拒答文案自相矛盾 ⇒ 新发现 **N-3** |
| **B** | **修复轮自报可信度** | **高**（3 发必做全部独立复现，另加 3 发） | 我**独立设计** 6 发变异（不复用 `fix8_mutations*.py`），一律**字节**读/字节替换/字节写 + 发内还原 + sha1 核对 + `py_compile`；每发替换前 `assert count(pattern)==1`（命中数≠1 直接跳过并判「变异定义失效」，不盲替换）；全程 `bare_lf` 保持 0 ⇒ **本项目两次文本模式事故在本轮复审台上是零风险**。**M1–M6 全 KILLED、存活 0、6/6 还原 `restored=True`、终态 sha1 回到 `59d4cd3b3c3b`**。三发必做（删新 except / 恢复 I-3 短路之前形态 / 删成功支合并）= M1/M2/M3，**结论与实现者自报方向一致**。数字面另核三处：定向 **393 passed/0 failed/360 subtests**（逐字吻合）、`--collect-only` = **889**（吻合「889 例」而非重跑）、G 段 AST 五项（代码 2 行 `:32`+`:166`、`/api/chat` 1、`ollama_base_url` 1、`httpx.stream|Client|get` 0）与 15 行/16 次**全部复算正确**——只有注释行号列把 `710` 写成 `709`（N-2） |

---

## 3. 新发现

> 定级说明：三枚全是 Minor，都不在出厂形态可达路径上，都不打任何冻结义务（D2/D6/#17/#18/§6 六项）。
> **N-0** 是我复核 C-1 时的标定副产，不构成缺陷，列在这里防被误读成「C-1 触发条件更窄 ⇒ 原判定可降档」。

### N-1（Minor）`agent.py:591-592` 与报告 459 行的「⇒ trace 也不挂 `model_route`」是**过强的绝对陈述**：多轮形状下前一轮的真路由事实仍会挂上

- **位置**：`backend/app/agent.py:591-592`（docstring）、`backend/tests/test_agent_contracts.py`（源面例的注释「出现第二处 `route_out` 写入 = 有一支文案短路也会挂 `model_route`」）、`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task-8-report.md:459`。
- **实测（探针 P6，两种 status 各一次）**：第 1 轮走**真** `llm.complete`（⇒ `outcomes` 真有一枚 `RouteOutcome`、账本真有一行）、第 2 轮才零候选 ⇒ 降级腿撞 `DENIED`/`FAILED` 文案短路。输出：
  `answer_is_backend_copy=true`、**`model_route_attached=true`**、`route_mode="agent"`（= 第 1 轮那枚）、`model_used` 取第 1 轮 provider 回显、`ledger_rows=1`、注记 2 枚（末枚 `…_denied`/`…_failed`）。
- **为什么只是 Minor**：`run_agent:947` 的 `outcome = outcomes[-1]` 与 `:973-974` 的挂载读的是**同一只盒子**，短路支确实**没有**往里塞新东西（`degrade.count("route_out=route_out")==1` 成立）；挂上的九键描述的是「本请求里最后一次真跑过的路由」，**不是伪造事实**（§8.1 第 4 条的字面语义仍成立）。用户面/审计面/账本面零影响、无 503。危害只有「TraceView 上后端硬文案旁边挂着一次它没走过的生成事实」这一处可读性歧义，而 `copy_shortcut` 注记已经在同一行里解释了它。触发还要求「第 1 轮成功 + 第 2 轮 `stage != context` 才零候选」（健康视图中途翻转/熔断被并发打开），**出厂形态不可达**（P2 实测首轮必先撞 `capability`）。
- **行级修法（择一，都是 T9 侧 1–3 行，不改行为）**：
  1. **推荐（改措辞 + 加钉，零行为风险）**：把 `agent.py:591-592` 与报告 459 那句改成
     「短路那支**自己不产生** route 事实；若同一请求的前一轮真跑过路由，trace 仍带**那一轮**的执行面事实（非伪造，`copy_shortcut` 注记解释答案为何是文案）」，
     并在 `AgentModelRouteTraceTests` 加一枚形状例钉住这个组合（`outcomes` 非空 + 文案短路 ⇒ `MODEL_ROUTE_KEY in row` 且末枚注记 `stage=="copy_shortcut"`），把它从「隐含承诺」升成「显式契约」。
  2. 若主 agent 判定「后端硬文案那一行**绝不该**带 `model_route`」：在 `_degrade_to_local_fast_path` 的三个短路 `return` 前不设标记、改由 `run_agent` 收尾处判 `final_answer in _FAST_PATH_COPY_TEXTS` 时跳过 `attach_model_route`——**我不建议**：那会丢掉第 1 轮的真实执行面事实，等于缩小观测面。

### N-2（Minor）`task-8-report.md` G 段的散文行号表把 `agent.py:710` 写成 `709`

- **位置**：`task-8-report.md:269`（m-1/m-2 更正后新写的「注释 10 行（11/13/15/16/19/21/25/29/76/**709**）」）。
- **实测（终态字节 `59d4cd3b3c3b`，tokenize+AST 双口径）**：`grep -c httpx` 等价 **15 行 / 子串 16 次**；代码 **2** 行 = `:32 import httpx`、`:166 httpx.post(`；散文 **13** 行 = `11,13,15,16,19,21,25,29,76,134,227,293,`**`710`**（注释 10 + docstring 3 = 134/227/293）。`:709` 那行是「注意 `AllCandidatesFailedError` … 不在这里 catch」，**不含 `httpx` 字样**。
- **为什么只是 Minor**：计数（15/16、代码 2、注释 10、docstring 3）与 AST 五项**全对**，只有一个行号引偏一枚；且报告明确写了「散文计数**不是**义务面，别抄进豁免表」，所以 T9 抄表不会错。
- **修法**：`task-8-report.md:269` 的 `709` → `710`（纯文档，一字符）。T9 顺手改即可，不必回炉。

### N-3（Minor）`agent.py:598-600`：降级腿这次检索 `FAILED` 时会**丢弃前几轮已在手的证据**，且响应 `num_sources` 与拒答文案自相矛盾

- **位置**：`backend/app/agent.py:598-600`（`elif status != "SUCCESS":` 那支，无「在手证据」护栏），对照同一函数里 `:601-603` 的 `elif not evidence:`（那一支**刻意**读累计表，理由写在 `task-8-report.md:465-466`）。
- **实测（探针 P7）**：第 1 轮工具轮 SUCCESS 收 2 条授权证据进累计表 → 第 2 轮零候选 → 降级腿那次检索抛 `ToolExecutionError(status="FAILED")` ⇒
  `answer="企业知识检索暂时失败，请稍后重试。"`，同时 `num_sources=2`、`trace.evidence_count=2`。也就是：**messages 里此刻躺着可用授权证据，却回了一句「什么都没查到」**。
- **为什么只是 Minor**：① fail-closed 方向，安全上不劣于修复前（修复前是「空 `AUTHORIZED_ENTERPRISE_EVIDENCE` + 让模型自己收口」，那才是 I-3 判定的 RBAC 面降级）；② 与权威链 `_local_fast_path` **不算分叉**——对话链没有跨轮累加器，这一支在它那里必然等价；③ 触发同样要求多轮 + tools 候选可用，出厂形态不可达。
- **修法（两行，方向 = 收紧成与自家 `:601` 那一支同一套理由）**：
  ```python
  # agent.py:598  —— 检索失败但**本轮之前已收到授权证据**时不该谎报「什么都没查到」
  elif status != "SUCCESS" and not evidence:
      fast_path_copy = "企业知识检索暂时失败，请稍后重试。"
      copy_note = "NO_CAPABLE_MODEL→fast_path_failed"
  elif status != "SUCCESS":                      # 失败 + 证据已在手 ⇒ 按证据作答，注记留痕
      copy_note = ""                             # 落回 :617 的既有投递+合成
  ```
  并加一枚形状例（P7 的自动化版：`status=FAILED` + 前轮 2 条证据 ⇒ 答案 = `ROUTER_ANSWER`、注记含 `tool_status="FAILED"` 的降级痕迹）。
  若主 agent 判定「降级腿这次检索失败就**必须**拒，宁丢在手证据」，那就把这枚决定按首轮 I-3 的原文要求**写进 DESIGN/T11**（并在 `agent.py:586-592` 注释里点明它与 `:601` 的理由不对称），不许停留在沉默里。
  **归属建议**：与 N-1 并成 T9 的「agent 观测面/语义收口」批，或 T11 前必修；不阻断放行。

### N-0（不是缺陷，防误读的一条注记）

C-1 的触发我实测**有门槛**：`agent.py:620-621` 的证据 dump 截到 16000 字符，粗估口径 `len(str(messages))/2`，
出厂两条本地条目 `context_tokens=8192` ⇒ 我第一发用 2×4000 字符证据**没**溢出（合成正常成功、trace 1 行、账本 1 行）；
2×11200 字符才稳定复现 `stage="context"`。这不减轻首轮判定：首轮评审定的是「**默认值一侧**可达 + 后果是 503/丢 trace/孤儿审计」，
且 `conversation_agent.py:573` 那条 8×4000 字历史路径同样能撞（P2.round1_context_history 实测落在这族形状上、由第二道 catch 兜住）。
**别把这条标定读成「C-1 可以降档」。**

---

## 4. §6「6 项等价清单」终态核对

| # | 统一口径项 | 终态 | 我这轮的证据 |
|---|---|---|---|
| 1 | 工具执行权在后端（`ToolContext(mode="local", allowed_knowledge_base_ids=<grant_scope 解析一次>)`，web 证据按构造拿不到） | **等价 ✓**（本轮未动，首轮已核 + `ToolContextScopeGuardTests` 在位） | 冻结比对：`app/security.py=d36b387aac6e`、`test_feishu_identity_contract.py=145d81cbb342` 逐字节未变；`grant 计数=1` 那枚未碰 |
| 2 | 审计成对 + **必须有 `QUERY` 收尾行** | **等价 ✓（C-1 修完即成立）** | P1 / P3 三支 / P2 三形状：`[TOOL_CALL, TOOL_RESULT, QUERY]` 全在；P2.mid_context 的 m-6 路只有 1 笔 TOOL_CALL（没调工具 ⇒ 无需成对，`QUERY` 仍在） |
| 3 | 证据投递走 system 段 `AUTHORIZED_ENTERPRISE_EVIDENCE=`，不用 `role="tool"` | **等价 ✓**（未动） | `agent.py:617-623` 与本轮 diff 无交集；P5.b 答案与来源面正常 |
| 4 | 温度各链自常量、两腿同值 0.2 | **等价 ✓**（未动） | 定向全绿（含 `AgentTemperatureEquivalenceTests` 三面等式）；`agent.py` 常量与 legacy 报文 `0.2` 字面量未被替换 |
| 5 | 计时归因：检索耗时不并进 `llm_ms`/`generation` | **等价 ✓（I-2 本轮补齐）** | P4 双形状（400ms/1.5s 各两笔）+ M5 KILLED；与 `conversation_agent.py:302/437/463` 的 `retrieval_ms`/`llm_ms` 分计口径不再矛盾 |
| 6 | 文案短路三支零外呼 + 降级腿再遇零候选绝不 503 | **等价 ✓（I-3 + C-1 本轮补齐）** | P3（三支逐字同源、egress 0、账 0、不挂 route、三态机器码）+ P1（第二道门 + 两枚注记 + 不 503）+ M2/M1 KILLED |

**还剩哪几项不等价：0 项。** 首轮 §6 表里 5/6 两项由修复轮补齐，现在六项全部闭合，
所以 `_local_fast_path`「唯一权威 + 就地变体」这条例程**不需要再补新口径条目**。
两条**清单外**的尾巴要在 T11 写清（不属六项，但同源同族）：
(a) **m-7 响应面无降级标记**（defer 成立，见 §5 第 7 条）；
(b) **N-3 的「在手证据 vs 本轮检索失败」** —— 它是六项第 6 条的**边界子情形**，主 agent 若按修法收紧，则第 6 条仍等价；若按「必须拒」裁定，则这是**刻意不等价**，必须按首轮 I-3 的原话进 DESIGN/T11 措辞，不许留在代码里。

---

## 5. 移交 T9 / T10 / T11 的强制口径（编号可照做）

**T9（矩阵收口 + 单一出口守卫）**

1. **D6 豁免表只抄 AST 五项**（终态字节实测值）：`import httpx` = 1（`:32`）、`httpx.post(` = 1（`:166`）、
   `/api/chat` 字面量 = 1（`:167`）、`ollama_base_url` 读 = 1（`:167`）、`httpx.stream|Client|get` = 0。
   等式生产者 = `AgentLegacyBranchTests::test_d6_exemption_inventory_for_agent_py`。**散文 15 行/16 次不进表**；
   报告 G 段那处 `709` 顺手改 `710`（N-2）。
2. **三枚新钉已落地，转成常规验收行**（我这轮逐枚复现过变异）：C-1 =
   `AgentNoCapableFastPathTests::test_a_second_zero_candidate_still_delivers_the_copy` +
   `…_the_http_face_still_returns_200_shape_when_the_degraded_leg_overflows_too`；
   I-1 = `AgentModelRouteTraceTests::test_the_limit_leg_route_also_lands_nine_keys`（两支键集合**等式**）；
   I-2 = `…::test_the_degraded_leg_tool_time_stays_out_of_the_generation_stage`（两腿各一枚 subTest）。
   常备变异表收 **6 枚**：首轮 G2（现死）+ 我的 M1–M6（`rev8r1_mutations.py` 可直接抄），标注「存活 0」。
3. **`enterprise_search` 的 `TOOL_CALL` 调用点上限 = 2 守卫**（首轮 §6 收口建议）现在**可以且必须**写：
   出厂形态实测「首轮 `capability` 零候选 ⇒ 工具回路 0 笔 + 降级腿 1 笔 = 1」，
   多轮形态 = 「工具轮 1 + 降级腿 1 = 2」，而 m-6 的 `stage=context` 支恒为 1（P2）。
   超过 2 = 出现第三处「无工具直执行企业检索」，直接判红。
4. **I-4 归 T9 确认**（不是 T8 缺陷、本轮 `app/llm/*` 字节冻结：`normalize.py=c6bc8b0caf81`、`fallback.py=008d8213bc05` 我复算 identical）：
   `normalize.openai_payload` 出口前把 `messages[].tool_calls[].function.arguments` 的 dict `json.dumps(ensure_ascii=False)`，
   并把 `{"role":"tool","tool_name":X}` 映射为带 `tool_call_id` 的形态；矩阵 #12 补「**多轮回放**」半段。
   **今天写出来必红，那正是它的价值**（首轮 P8 已证）。
5. **m-9 归 T9**：`_classification_query`（`agent.py:248-259`）与 `llm/_query_of` 是第二份实现；
   由 llm 包导出 `query_of` 收口，**别长第三份**。`complexity` 今天不参与打分 ⇒ 只影响 trace 可读性。
6. **N-1 / N-3 两枚 Minor 归 T9 批**（或 T11 前必修）：修法见 §3 行级；`#17` 失败路口径照旧
   （agent 链全链失败**没有 trace 行**、只有账本行，legacy 同形，不许为它挪 `save_trace`）。
7. **m-7 归 T11 确认成立（defer 判定我认可）**：实现者给的两条理由我核过是真的——
   `app/agent_routes.py=1080fbd4a0c4`、`app/security.py=d36b387aac6e` 本轮字节冻结，
   而响应键集合被既有例按**等式**钉着（`test_trace_carries_route_and_the_response_face_is_additive_only`），
   additive 补一枚布尔键确实要改那枚等式 + 覆盖四类出口。⇒ T11 必须写「前端不读 trace 时分不出『这次没有工具轮』，
   判据 = trace 事件里 `degraded=true` / `copy_shortcut` 注记」，并把它挂进 Enterprise Quality Gate 待办。
8. **`stage` 词表**：`_fast_path_copy_event` 在 `model_route_downgrade.stage` 上引入了 `"copy_shortcut"`，
   它**不在** `router._Stage` Literal（`enabled/capability/health/limits/priority/context`）里。
   我全库扫过消费面：`model_route_downgrade` 在 `backend/app`、`frontend/src`、`docs` 里**零消费者**（只有产生者），
   所以今天是无害的。T11 文档要把这个字段声明为「**agent 链自有的事件子类型词表**，与 `router._Stage` 无关」，
   并给 T9 一条守卫建议：别在 `model_route_downgrade` 与 `type=="stage"` 两套 stage 值之间做全局枚举校验。

**T10（真实 failover）**

9. 默认无 key 环境 `/api/agent/query` **不产生任何 tools 外呼**（P1/P3 实测 `egress=0`，`enterprise_search` 由后端直接执行）；
   真实 failover 继续走 `/api/query/stream` 或显式给 key。**给 key 之前先确认第 4 条（I-4）已修**，否则工具轮第二轮必拿 400。
10. **agent 面事实（本轮新增，T10 判读要用）**：
    - 出厂形态下 trace 里看到 `model_route_downgrade` 是**正常**（常驻 D2），不是故障；一枚 = 零候选后合成了、两枚 = 连合成都零候选（P1）。
    - **`stage` 值分布**已被 m-6 改写：多轮请求的溢出**不再**走 `_degrade_to_local_fast_path`（不再产生第 2 笔 `TOOL_CALL`），
      所以 T10 若在真实多轮里数检索次数，基线要按「工具轮 1 次 + 降级腿最多 1 次，且 `stage=context` 时 0 次」读。
    - **答案面新增三句后端硬文案**（DENIED/FAILED/零证据）+ 收尾兜底「当前没有获得足够证据生成可靠答案。」
      都属**预期内**、且与对话链逐字相同；`model_used` 在纯降级行仍可能等于 `settings.ollama_model`（未过路由时的既有语义）。
    - `stage_timings["llm_ms"]` 从本轮起**不含**降级腿检索耗时 ⇒ 与首轮之前的历史样本**不可直接对比**
      （旧的「生成」行虚高一整次检索）。做 p95/SLO 对比时要么只用本轮之后的样本，要么显式注明口径变更。
    - **计时下界的新行为**：工具账 ≥ 总耗时时 `llm_ms` 键会**消失**（P4.clamped，`if model_ms > 1`），不是负数。
      真实环境里带慢工具 + 快本地模型的请求可能触发，前端/QA 别把它当丢数据。

**T11（验收文档 / Quality Gate）**

11. 首轮 §8 第 7–9 项照写；**第 8 项那句「例外」现在可以划掉**：
    `model_used` 与账本 `model` 列同源，**I-1 修完后「收尾腿降级回落 `settings.ollama_model`」这个例外已消失**
    （M3/M6 两支等式钉着）；剩下的唯一「不挂 `model_route`」情形 = 文案短路三支且**本请求没有更早的真路由轮**
    （N-1 描述的组合要按新措辞写，别写「永远同源」也别写「短路必不挂」）。
12. §6 六项统一口径现在**全部闭合**，整表可原样进验收文档；两处 docstring 互点名已在位
    （`agent.py:469-475` 写「六项里本函数负责四项」、`conversation_agent.py` 侧是禁改件故由 T11 文档单点承载）。
13. m-4（`backend/data/audit.jsonl` 被既有测试追加）继续挂 Quality Gate 待办；我这轮复核：
    真实文件里**最后一条 agent 面审计仍是 2026-09-23T07:58:39Z**，`agent_traces.jsonl` mtime 未动 ⇒
    「T8 及其修复轮 0 行真实观测面写入」这句现在**可以**当已验收项写（audit.jsonl 的非 agent 行仍待办）。

---

## 6. 我实际执行的命令、关键输出、sha1 对照表

```
# ---- 定向门（cwd=backend；只跑任务书三件，全套件按并发提示未跑）----
python -m pytest tests/test_model_router_v23_contract.py tests/test_agent_contracts.py \
       tests/test_agent_routing_contracts.py -q
  -> 393 passed, 4 warnings, 360 subtests passed in 67.66s     （= 实现者自报 393/0/360，逐字吻合）
python -m pytest tests --collect-only -q
  -> 889 tests collected                                        （= 自报「全套件 889」的例数，未重跑即交叉验证 +7）

# ---- 改动面与冻结件（vs snap-task8，逐枚字节）----
snap-task8 覆盖比对：identical=24  differing=3
   DIFF app/agent.py                          9760d3509ed5 -> 59d4cd3b3c3b
   DIFF tests/test_agent_contracts.py         5a59795bf897 -> d32e110d8a39
   DIFF tests/test_model_router_v23_contract.py e9ab22d34cfb -> 41506ab66166
test_agent_routing_contracts.py diff = 0 行；test_feishu_identity_contract.py = 145d81cbb342（未动）
v23 契约 diff：删除 1 行（`_RecordingToolExecutor.__init__` 签名续行）/ 新增 241 行 / 新增 self.assert* = 49
   ⇒ **被删断言行 0 枚**；test_agent_contracts.py 为纯增 +31/−0
agent.py 终态：1000 行、bare_lf=0、50371 B、全 CRLF、AST 通过

# ---- 自建探针（rev8r1_probes.py；复用 _AgentMigrationFixture，MockTransport + legacy 硬闸）----
P1  C-1 五件套       answer=收尾文案 | trace=1 | notes=2(capability→context) | audit=[TOOL_CALL,TOOL_RESULT,QUERY]
                     egress=0 | ledger=0 | HTTP 面 raised=false                    => R1.1 ADDRESSED
P1' 标定             2×4000 字符证据**不**溢出（合成成功、trace 1、ledger 1）；2×11200 才复现 stage=context
P2  m-6              第2轮 context：tools=["enterprise_search"] 恰 1 次、TOOL_CALL 1 笔、model_route 在位
                     首轮 capability：仍完整降级（检索 1 次）=>「第一轮就该拒」语义未改
P3  I-3 三支         逐字 == conversation_agent.py:317/319/321 | egress=0 | ledger=0 | model_route 未挂
                     note ∈ {…_denied, …_failed, …_no_evidence} 三态可区分 | reason_codes 无新词
P4  I-2 下界         both_legs: elapsed=836.63 tools=[404.76,400.36] generation=31.5（两笔都扣、非负）
                     clamped : elapsed=3028.33 tools=[1504.50,1500.39] generation=23.4（非负；极端时键消失）
P5  A 误伤探针       b) 前轮真路由 + 降级腿检索成功 2 条证据 ⇒ 仍合成、model_route 挂、ledger=1、零 copy_shortcut
                     a) 正常工具回路 ⇒ 同上、notes=[]                              => A：无误伤
P6  N-1 新缺口       多轮 + 文案短路 ⇒ model_route_attached=True（= 第 1 轮真路由，非伪造）、route_mode=agent
P7  N-3 新缺口       前轮 2 条证据在手 + 降级腿检索 FAILED ⇒ 回「企业知识检索暂时失败…」而 num_sources=2
真实观测面：agent_traces.jsonl mtime=2026-09-23T15:58（未动）；audit.jsonl 最后一条 agent 面=2026-09-23T07:58:39Z

# ---- 变异台（rev8r1_mutations.py：rb/字节替换/wb + 发内还原 + sha1 核对 + py_compile；每发 assert 命中数==1）----
起点 sha1 = 59d4cd3b3c3b  bytes=50371  裸 LF=0
M1 删第二道 catch（C-1）              KILLED  3 failed/61 passed   mutated f7ceb04ee069  bare_lf=0 AST-OK 还原=True
   红在：test_a_second_zero_candidate_still_delivers_the_copy
         test_the_http_face_still_returns_200_shape_when_the_degraded_leg_overflows_too
         contracts::test_the_degraded_leg_has_its_own_second_zero_candidate_catch
M2 删 I-3 三支短路（= 修复前形态）    KILLED  4 failed/63 passed   mutated 7a788983286f  bare_lf=0 AST-OK 还原=True
   红在：源面计数器例 + 三个 subTest（DENIED 授权路 / 检索失败路 / 零证据路）
   副产证据：M2 下 DENIED 路答案变成模型输出「差旅住宿上限每天陆佰元 [1]。」⇒ 独立复现首轮 I-3 症状
M3 收尾腿成功支传空盒（I-1 等式 A 半）KILLED  1 failed/64 passed   mutated de9e4428436b  bare_lf=0 AST-OK 还原=True
   红在：SUBFAILED(branch='成功支（收尾腿正常生成）') test_the_limit_leg_route_also_lands_nine_keys
M4 删 m-6 的 stage==context 支         KILLED  2 failed/62 passed   mutated d91bdae16a6b  还原=True
M5 删 tool_time 盒子写入（I-2）        KILLED  1 failed/64 passed   mutated 3f94200eb5d5  还原=True
   红在：SUBFAILED(leg='D2 降级腿') test_the_degraded_leg_tool_time_stays_out_of_the_generation_stage
M6 收尾腿 except 支传空盒（I-1 等式 B 半，= 首轮原始缺陷形态）
                                      KILLED  1 failed/64 passed   mutated 48a48c398de1  还原=True
   红在：SUBFAILED(branch='降级支（收尾腿零候选后合成）')
==> 6 发全 KILLED、存活 0；首轮 G2（删成功支合并）现已死，与自报方向一致

# ---- httpx 二分（终态字节，tokenize + AST 双口径；核 G 段更正）----
15 行 / 子串 16 次 | 代码 2：:32 import httpx、:166 httpx.post( | /api/chat 字面量 :167 | ollama_base_url 读 :167
httpx.stream|Client|get = 0（AST 三项与报告 AST 五项**逐枚吻合**）
散文 13 行 = 11,13,15,16,19,21,25,29,76,134,227,293,710   ⇒ 报告写 709 = N-2

# ---- sha1 对照表（开工初值 vs 收尾，25 枚全 OK）----
app/agent.py 59d4cd3b3c3b | app/conversation_agent.py 0ffcc353eb59 | app/rag.py a5a638716947
app/agent_routes.py 1080fbd4a0c4 | app/agent_trace.py d17a0bf266f1 | app/security.py d36b387aac6e
app/config.py dace1660d1fb | app/store.py a41bd431c7ac
app/llm/{__init__ c29e3c393f87, fallback 008d8213bc05, normalize c6bc8b0caf81, usage 8a8f5b0cff28,
         router 2742871ed6ee, errors fca8d9da2c8f, models 586dfe033c73, registry 60b706112882,
         provider 9d34721f89f0, classifier 81d43043aee4, health f529dc5f42b5}
config/llm_registry.json 3e652e9cf496
tests/{test_model_router_v23_contract 41506ab66166, test_agent_contracts d32e110d8a39,
       test_agent_routing_contracts 0f9f293daefb, test_feishu_identity_contract 145d81cbb342,
       conftest 73d1060de465}
比对枚数 = 25   不一致 = 0     agent.py 终态 1000 行 / 裸LF=0 / 全CRLF / AST 通过

# 我写过的文件（全在 SDD 目录，前缀 rev8r1_）
rev8r1_probes.py  rev8r1_mutations.py  tmp/rev8r1_diff_*.txt  tmp/rev8r1_p{1,2,3,5,6}.log  tmp/rev8r1_mutations.log
```

**硬约束自证**：`backend/`、`frontend/` 零修改（上表 25 枚收尾 sha1 = 开工初值；6 发变异全部发内字节还原）；
零 git 写（只 `git status`）；零真实外呼（`OLLAMA_URL` 从未被消费：provider 走 `httpx.MockTransport`、
legacy 腿 `httpx.post` 由我的 `setUp` 硬闸接管并判红，11434 的 `phi3:mini` 一次未打）；
审计/trace/DB 三面出口由 fixture 改道临时目录（真实文件 mtime 与末行时间戳双证）；
spec 未放宽（本文三枚新 Minor 的修法都是「改实现/改措辞以合已裁口径」方向，未删未弱化任何断言）；
全套件未重跑（按并发提示，仅 `--collect-only` 取例数）。

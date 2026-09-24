# Task 9（A+B 合并交付）独立评审裁定 — findings

评审者：Task 9 独立评审（第二轮指派，未派子 agent）
日期：2026-09-24 · 工作目录 `E:\xiangmu\rag` · pytest 一律从 `backend/` 起
被审件零改动（收尾 sha1 全等，见 §8）；零 git 写；**零真实外呼**（11434 未被触碰，探针全为纯函数级 `normalize` 调用）；定向测试共 4 次跑，未重跑全套件。

---

## 1. Verdict

**Approved-with-fixes**（Critical 0 / Important 3 / Minor 11）。

一句话理由：四件交付物（D6 三层等式、19+1 矩阵 + 耦合闸、A-3 收紧与 cwd 收口、I-4/N-3 两处产品修复）**实测全部落地且我抽查的 44 枚承载例全绿**，两处产品改动的授权链与语义边界都对得上 spec；但 I-4 的配对规则在「空 id 与非空 id 混排」时**违反它自己写在 docstring 里的次序规则且无测试**，A-3 收紧后仍有 **3 类可绕形状**（其中 2 类是源码级字面量，与 docstring 的自述不符），以及一处被报告称为「已钉住」的拒绝面一致性**其实没被任何断言钉住**。

---

## 2. Critical

**空。**

为什么没有阻断 T10 的东西：
- I-4 的错配支只在「provider 对同一轮里部分调用回空 id」时出现，而那种报文里 `tool_calls[].id=""` **本身**就已被 OpenAI 侧判 400 ⇒ 不会静默产出错误答案到 T10 的视野里；T10 走的是 rag/chat 链（无工具轮），根本不过 `_replay_messages` 的配对支。
- A-3 的可绕形状是**静态防回潮钉的完备性**问题，不是今天的实现缺陷：`model_route` 九键今天仍只有 `usage.model_route_trace` 一枚产地（`test_there_is_exactly_one_model_route_producer` 属性级 + 导出面级钉住，我复核在位）。
- DENIED 一致性问题的现状是**保守方向**（宁可回硬文案、零外呼），不会让 T10 的真调用变绿成假的。

---

## 3. Important

### I-1｜`_matching_call` 跳过空 id 调用 ⇒ 回执可以**跨到后面的调用**上，与 docstring 的次序规则冲突
- **位置**：`backend/app/llm/normalize.py:183`（`if not _pairable_id(call): continue`）；被违反的规则写在同文件 `:120-124`（「同名多枚 ⇒ 按 assistant 里的**出现次序**逐一消费（第 N 枚回执配第 N 枚调用）」）。
- **症状**（我实测，`rev9_probes.py` P10）：一轮两枚**同名**调用 `id=["", "k2"]`，回执两枚按序 `[first, second]` ⇒ 出口体是
  `[{role:tool, tool_call_id:"k2", content:"first"}, {role:tool, tool_name:"t", content:"second"}]`
  即**第一枚回执领走了第二枚调用的 id**，第二枚成孤儿。不同名时同样成立（名字匹配那支也被 `_pairable_id` 提前 `continue` 拦掉，于是我直接实测了 fallback 支的跨槽）。
- **根因**：`_pairable_id` 的「空 id 不参与配对」被放在**槽扫描的入口**（决定「谁是第 N 枚调用」），而不是放在**出口**（决定「这枚槽能不能写出 id」）。两枚规则叠在同一处，语义就从「按次序消费」变成了「按可配对者次序消费」，docstring 只写了前者。
- **行级修法**（约 4 行，不改别的规则）：`_matching_call` 里把 `if not _pairable_id(call): continue` 改成「仍参与槽位选择、但标记为不可写出」——
  最小实现：先按名/按次序选出 `index`（不筛 id），把 `if not _pairable_id(calls[index]): return None` 移到 `_paired_tool_receipt` 选中 `index` 之后（**同时 `consumed.add(index)` 占掉那枚槽**，否则下一枚回执会退回来重复领）。这样次序语义与名字优先规则不再互相遮蔽，空 id 仍然「宁缺不错配」。
- **验收方式（缺哪条测试点名要补）**：现套件里 `test_a_call_without_an_id_is_never_paired` 只有**一枚**空 id 调用 ⇒ 覆盖不到跨槽。必补
  `OpenAIMultiTurnReplayTests::test_a_call_with_an_empty_id_does_not_let_a_later_call_steal_its_receipt`：两枚同名调用 `id=["", "k2"]` + 两枚回执，断言第一枚回执**没有** `tool_call_id`（而不是等于 `"k2"`）、第二枚也没有、且 `mapped[0]["tool_calls"][0]["id"] == ""` 原样不外带。补完后我上面的 P10 必须打出 `[None, None]`。
  顺带把 `m-B3` 那句「空 id ⇒ 不造假 id、缺陷留在可观察处」的披露补上「且**不许跨槽**」这一条。

### I-2｜A-3 收紧后仍有 3 类可绕形状；docstring 的自述范围比实际覆盖**宽**
- **位置**：`backend/tests/test_llm_usage_contract.py:1700-1702`（三枚谓词）+ `:1770-1772`（docstring「本钉只挡**源码字面量**；运行时注入…由 #17 兜」）。
- **症状 / 实测**（`rev9_mutations.py` A 组，逐发注入 `app/` 后跑该例，发内还原，sha1 全等）：

  | 注入形状 | 结果 | 定性 |
  | --- | --- | --- |
  | A1 `'selected_index'` 单引号 | **RED** | 段 A 的 M3a 声称已被杀 = **属实** |
  | A2 `dict(stage=…, selected_index=…, context_dropped=…)` **kwargs 形** | **GREEN** | 洞（源码级、AST 里就是关键字，无引号） |
  | A3 `{"selected_" "index": 1, "context_" "dropped": 2}` **隐式拼接** | **GREEN** | 洞（CPython 把相邻常量合成**一枚** `ast.Constant`，语义上就是源码字面量） |
  | A4 `**{"selected_index": 1, "context_dropped": 2}` | **RED** | 已挡 |
  | A5 子目录同名 `app/rev9sub/agent_trace.py` 带 `"model_route"` | **RED** | 相对路径豁免键有效（N2 的第②条确实收到口） |
  | A6 `f"{'selected'}_index"` | GREEN | 洞，但**可归进已声明的「运行时注入」例外**（措辞边界） |

  ⇒ 发数：**2 枚应当红而没红**（A2/A3），第 3 枚（A6）属披露范围内。
- **根因**：谓词是**文本正则**，而 Python 的键名可以不带引号（kwargs）或跨字面量拼接。收紧只消灭了「引号种类」这一个免检面，没有消灭「有没有引号」这一个。
- **行级修法**（二选一，我倾向①，因为它保住 brief 点名的「同形」要求）：
  ① 在 `rebuilds_the_facts` 里加第三支并 `or` 进去：
  `re.search(r"\bselected_index\s*=", t) and re.search(r"\bcontext_dropped\s*=", t)`（覆盖 kwargs / `dict(...)` 形），
  再加第四支：对 `ast.parse` 后的 `Constant` 文本做一次 `{"selected_index","context_dropped"} ⊆ {node.value}` 判定（覆盖 A3 的拼接，与 `SingleEgressStructureTests` 同一手法，天然不误伤注释）；
  ② 或维持现状但把 `:1770-1772` 改成准确范围：「本钉挡**带引号的源码字面量**；kwargs 形、隐式拼接形与运行期拼键名一律由 #17 三枚真落盘断言兜」——**并补一发注入证明这三形今天确实由 #17 接得住**（今天接不住：#17 只审 `agent/rag/sse` 三链出口体的九键，不审「有没有第二处产地」）。
- **验收**：变异台补 A2/A3 两发为**期望 RED**；跑绿即收口。§0b-1 的定性我另立在 §5 表第 1 行。

### I-3｜`DENIED` + 在手证据的「文案 / `num_sources` 不同源」今天是**哑的**，而段 B 报告称它「已被钉住」
- **位置**：`backend/tests/test_model_router_v23_contract.py:7407-7423`（该例断言了 answer / `requests==[]` / `raw_rows()==[]` / note / `tool_status`，**没有任何一条**碰 `num_sources` 或 `sources`）；对照 `backend/app/agent.py:1027,1037`（收尾 `num_sources=len(evidence)` = 在手的 2）。
- **症状**：N-3 修掉的正是「文案说失败、`num_sources` 报 2」这枚自相矛盾；`DENIED` 支按 brief 要求**不吃门**（正确），但它的文案与 `num_sources` 仍然是不同源的同一形状。报告 m-B1 写「现状已被 `test_a_denied_current_round_keeps_the_hard_copy_even_with_evidence_in_hand` 钉住（可观察、不是哑的）」——**该断言不存在**，所以现状既没被钉也不可读。
- **根因**：报告把「例子里有 `num_sources=2` 这个返回值」当成了「例子断言了它」。
- **行级修法**（不必动产品代码；改主意时再动）：在该例末尾补两行把**现状**钉成事实：
  `self.assertEqual(2, result["num_sources"])` 与 `self.assertIn("无权访问", result["answer"])`，
  并给一句注释说明「这是**刻意保留**的不同源（拒绝面优先），终审若要一致口径需同时改文案与来源面」。矩阵 §4 的「遗留 minor」那句同步改口为「现状已钉住、是否统一待终审」。
- **验收**：加完后跑一发变异「把 DENIED 支也吃 N-3 的门」（`if status != "SUCCESS" and not evidence:` 吞掉 DENIED 判据）必须仍然红在**两支**上，而不只是红在 note 上。

---

## 4. Minor（一行一条）

1. `app/agent.py:497-498` 的 docstring 第④项仍写「DENIED / 检索失败 / 零证据三支走同源硬文案且零外呼」，未随 N-3 加「手上没货」前提 ⇒ 与 `:625` 的实现不再逐字对齐（与 Task 8 的 N-1 同族，随终审 triage）。
2. `app/agent.py:633` 注释里的自指 ``:601`` 在段 B 之后已漂到 `:762`；m-B5 承认裸行号会漂，但注释里留了一枚会误导下一位读者的自指。
3. `MatrixDocumentClosureTests` 只有**单向**闸（文档→套件）：`_test_index()` 现算了全套件索引却只用于校验文档侧名字，套件里新增一枚不挂表的例永远绿。修法（便宜且不脏）：再要求 `test_llm_egress_guard.py` 的 12 枚类名每枚都至少被矩阵引用一次。
4. `test_llm_egress_guard.py:203 code_line_numbers()` 定义了但**零使用** ⇒ 第三层的「代码面」其实是从「全文 − 散文」**推导**的、不是独立测量；我实测内圈断言恒真（8 枚模式、失败 0、负值 0），所以它唯一独立作用面就是 B3 那种类表漂移。要么用行集真算一遍代码面（三层互验），要么删 helper 并在 docstring 里改口「第三层核的是表自洽」。
5. 非 httpx 客户端（`from urllib.request import urlopen`）+ 运行期拼 URL 的第二条腿，D6 三层全绿（B2 实测 GREEN）。修法：`PATTERNS` 补两枚**恒 0 行**（`^import (?:requests|aiohttp|http\.client)`、`urllib\.request`）——`requirements.txt` 今天只有 httpx，成本≈0。
6. 不裸放 `ValueError` 的扫描面 = 3 枚链 + `app/llm/*`，而报告/矩阵 §3 的措辞是「**业务入口**」⇒ 实测漏 8 枚：`knowledge.py`(3)、`ingestion.py`(2)、`retrieval.py`(2)、`auth.py`、`identity/mapper.py`(3)、`typesafe_judgments.py`、`resilience.py`(2)、`knowledge_os.py`。措辞改准或扩面，别留着「业务入口」这个词。
7. `_paired_tool_receipt` 的「自带 id」支（`normalize.py:161-163`）原样透传、**保留 `tool_name`**，与配对口支（`:170-172` 显式剥 `tool_name`、键序 `["role","tool_call_id","content"]`）不同形。agent 今天不产这种消息 ⇒ 只记档。
8. `openai_payload` 对不可 JSON 序列化的 `arguments`（set / 自定义对象）直接抛 `TypeError`（P7 实测），会绕过 provider 的归类。实际不可达（`ToolCall.arguments` 恒来自 `json.loads`），但 `default=str` 一行可收口。
9. 非 dict 且非 str 的 `arguments`（`None` / `int` / `list` / `bool`）走「原样透传且**同对象**」支（P6 实测），协议侧仍会 400；无测试点名这一支。
10. 段 A 报的 `29 passed / 84 subtests` 与我实测的 `29 / 85` 差 1 枚 subtest——不是不实，是段 B 往矩阵加了 `N-3` 行使承载闸的 `subTest` +1（段 B 自己算对了）。只记档，避免终审当成计数错误。
11. `backend/data/audit.jsonl` 6783 行且每次跑套件都长（我这 4 次定向也加了行）；m-B4 属实：审计文件不在 `conftest.py` 保护集内，属**段 B 之前既有**状况 ⇒ 归 T11 卫生项。

---

## 5. 必查 1–8 逐项结论

| # | 结论 | 证据（文件:行号 / 我跑出的输出） |
| --- | --- | --- |
| **1** §0b-1 那发「刻意 GREEN」 | **如实披露，不是 A-3 的洞**；但**洞在别处**（见 I-2）。M3a 变异的是**被测谓词本身**（退回双引号-only），GREEN 是构造使然；它对「收紧前确有免检面」的证明成立。我用**现成谓词**注入单引号文件 ⇒ RED（A1，`1 failed in 62.12s`），证明今天的钉真的杀得住那一形。可绕形状发数：**2 应当红而没红**（kwargs 形 A2、隐式拼接形 A3），`**{...}` 已挡（A4），子目录同名已挡（A5），f-string 动态拼属已声明例外（A6）。修法见 I-2。 | `rev9_mutations.log` A1–A6；`test_llm_usage_contract.py:1700-1702,1770-1785` |
| **2** §0b-2 配对规则 | 4 组对抗输入：**同轮两次同名按序消费 ✓**（`c1,c2`）；**异名交错按名配 ✓**（`yB,xA`）；**回执先于 assistant ✓ 不造 id**（原样留 `tool_name`）；**assistant 自带 id 又补一次 ✓** 占槽（`d1` 原样、第二枚落 `d2`）。**唯一失败形状 = 空 id 与非空 id 混排 ⇒ 回执跨槽**（I-1）。`ensure_ascii=False` 幂等 ✓（出口体喂回第二次逐字相等、无 `\uXXXX`）；**就地改调用方 messages 的指控不成立**（P1/P8/P11 三处 `caller untouched? True`，内层 `function` 子对象非共享）；非 dict 值走「原样同对象透传」（Minor 8/9）。 | `rev9_probes.py` 输出 P1–P12；`normalize.py:94-208`；套件侧 7 枚 #12b 例我逐枚跑绿（25 枚承载例合跑 `25 passed, 26 subtests`） |
| **3** §0b-3 N-3 等价论证 | **论证成立**：`conversation_agent.py:232-268` 的 `status` 只由**那一次** `tool_registry.execute` 的 try/except 决定；`:273-278` 的 `evidence` 由**同一个** `result` 现算并重新赋值；调用点 `:561` 的 `_local_fast_path` 是**单发函数**（签名 `:169-178` 无 `round_index`、无 messages 累加盒、内部 `round=0` 硬编码在 `:213/:283`）⇒ 对权威「本轮 == 全链路」，两种读法恒等价、分不出主从。因此「与权威对齐=只看本轮」在 `agent.py` 的累加盒上不可实施，取方案② 是 brief 授权的两条之一 ⇒ **不属擅自扩权**。**DENIED 不吃门 ✓**：`:618` 支在 `:625` 之前且 `return` 于 `:652`，测试断言 `self.requests == []` 与 `raw_rows() == []`（I-3 成果一字未松，变异 M4 类形状由该例单独挡）。**新增的是事件 `note` + `stage`，不是 reason code**：`reason_codes` 仍 `["NO_CAPABLE_MODEL"]`（`agent.py:423`），全仓 `model_route_downgrade` 无任何下游消费者（前端/docs 零命中）⇒ **不触 §Global Constraints 的 reason codes 冻结，无需 spec 回写**。 | `conversation_agent.py:169-178,232-278,307-321,561`；`agent.py:410-431,618-660`；`test_model_router_v23_contract.py:7352-7423`；我跑 `AgentNoCapableFastPathTests` 全类 ⇒ `19 passed, 5 subtests` |
| **4** §0b-4 矩阵可信度 | 抽 6 行（#9/#12/#12b/#16/#17/#19）= 25 枚 node-id，**全绿**（`25 passed, 26 subtests passed in 74.85s`），承载例真实存在且不是 skip 桩（都是真链 + MockTransport）。4 枚云行仍是 `PENDING_EXTERNAL`、`P0` 仍是 `BLOCKED`，无一行被写成 PASS，且 `test_every_row_carries_a_real_test_or_an_honest_status` 用**状态值域三枚**把「写 PASS」做成红。`#12b` BLOCKED→GREEN 有 7 枚真实承载例（我逐枚跑过）。闸是**单向**（文档→套件）：文档写了不存在的例 ⇒ 红（我实测 M5 同形 + B3/B4/B5 三发都红），**套件有例但文档没挂 ⇒ 不红**（Minor 3）。闸的注册表前提（无 key ⇒ `external ∧ enabled = ∅`）我核过 `test_shipped_registry_file_is_what_the_matrix_claims` 的判据与出厂 JSON 一致。 | `docs/MODEL_ROUTER_V23_MATRIX.md:19-44`；`test_llm_egress_guard.py:801-896`；`rev9_nodeids.txt` + 我的合跑输出 |
| **5** D6 三层等式的强度 | 豁免互等**真成立且双向**：新文件 `import httpx` ⇒ **RED**（B1，`10 failed, 25 passed, 79 subtests`——AST 面 + 全文面 + 互等三处同时响）；删豁免一行 ⇒ RED（B4，`5 failed`）；养闲行 ⇒ RED（B5，`2 failed`）。三层关系：同一行既有代码又有注释时 `prose` 行集**吞掉**该行 ⇒ 内圈 `全文 == 代码 + 散文` 是**恒真**（我实测 8 枚模式失败 0、负值 0），真正有牙的是「CODE_EXPECTED 必须等于差值表」这一枚外圈（B3 `1 failed`）⇒ 结论：**不会恒假、但第三层不是独立测量**（Minor 4）。不裸放 `ValueError` 的覆盖面漏在「业务入口 vs 链路面」的措辞（Minor 6，实测漏 8 枚 raise 点）。 | `rev9_mutations.log` B1/B3/B4/B5/B6；`test_llm_egress_guard.py:203,421-437,464-485` |
| **6** 有没有放宽 | 对 `snap-task8-r1/tests/` 全量 diff：`test_feishu_identity_contract.py` **0 删 / 12 增**；`test_llm_usage_contract.py` 14 删（全是 A-3 谓词与豁免键的**替换**，逐条强度已升：单引号+相对路径+反向闸「豁免集合 ⊆ 扫描面」）；`test_model_router_v23_contract.py` **只删 2 行**，且都在 `test_payload_does_not_mutate_the_request` 内部（`req = request_of(tools=[...])` 与 `assertEqual([{...user...}], req.messages)`）⇒ 替换为「三条 message 深拷贝基准逐字等式」，**严格更强，一条断言没少**；`test_typesafe_judgments.py` 的改动是 `setUp` 里**加**两枚 `patch.object`（`:75-76`），无删。`conftest.py` 仍 `73d1060de465` ✓。段 B 的自述「唯一改到的既有例是升级」= **成立**。 | 我的 `diff <(sed 's/\r$//' …)` 三张表；`test_model_router_v23_contract.py:1132-1153` |
| **7** 报告纪律 | 两段各自窗口的**改动面列全**（我按 mtime + 实际 diff 复核：段 A 文件 16:55–17:14，段 B 文件 17:54–18:22，无第三方文件被动）。变异存活：段 A 明写「7 killed + **1 发刻意 GREEN**（M3a）」并解释它是收益证据 ⇒ **口径未混淆**；段 B 8 发 0 存活与我复核不矛盾。**brief 预计被推翻**这一条**敢写**：段 A 缺项表写「#9/#16 **不缺**（brief 预计有误）」，矩阵 §3 同口径复述；#17 给的是「形状齐、口径按 §9.1 分工」的半推翻（合理）。不实的自述只有一处：m-B1 的「已被钉住（可观察、不是哑的）」（= I-3）。 | 段 A 报告「状态/变异表」；段 B「我裁过但没做的」「移交终审的 minor」；`rev9_mutations.log` |
| **8** 范围（语义越界） | 产品面 sha1 我复算全等；`rag.py`/`conversation_agent.py`/`security.py`/`agent_routes.py`/`llm_registry.json` 与 §0 表逐枚一致 ⇒ 白名单语义与注册表旗标未动。**语义越界检查**：`openai_payload` 是三条链共用，但 `rag.py:195-227` 的 messages 只有 system/user ⇒ `_replay_messages` 对 RAG 链恒等（探针 P1/P8 的 identity 面 + 全套件里 rag 的逐字节例未被触碰）；`ollama_payload` 零改动（P11 实测仍吃 dict、`tool_name` 仍在）；`agent.py` 的消息回放形状与 `LLMResponse/ToolCall` 未动（`:271-277`, `:920-926` 原样）；降级腿证据仍走 **system 段**（`agent.py:86-88` 的理由仍成立，没有新造孤儿 tool 消息）。**结论：无越界。** | sha1 表 §8；`rag.py:195,211,226`；`normalize.py:48-66`；`agent.py:86-88,271-277,920-926` |

---

## 6. 对 T10（REAL-LLM-FAILOVER-001，P0）的开工前置条件清单

按「现在这台机器：`phi3:mini` 已加载、`ornith-1.5:9b-text` 加载失败、无云 key」排。**每条都是我今天读码/实测出来的，不是通用建议。**

1. **必须选对链路**：出厂注册表两枚 ollama 条目 `capabilities.tools=false`、`priority.tools=0`（我 dump 了 JSON）⇒ **agent 工具轮必然 `NoCapableModelError` 走 D2 fast path，一次外呼都没有**，P0 的「primary 真被调用 + fallback 被调 + `model_route` 两 attempt」拿不到。P0 只能挂 **rag 或 SSE(chat/rag 档)** 链。若有人为了「凑两次 attempt」去翻 `tools` 旗标 = 改注册表 = 越界，先要裁决。
2. **超时预算会先杀掉你**：`llm_model_timeout_seconds=20`、`llm_total_budget_ms=30000` 且**总预算制**（`config.py:91-92`，spec §6「三 attempt 共享」）⇒ ornith 的加载失败本身就要等 5–15s，phi3 若冷加载就死在 20s 里。开跑前**先 `ollama run phi3:mini` 预热**（或显式 `keep_alive`），并把 `LLM_TOTAL_BUDGET_MS=90000`（`Field(le=120000)` 允许）与 `LLM_MODEL_TIMEOUT_SECONDS=60` 写进用例前提；否则你测的是超时归类而不是 failover。
3. **熔断不是你的对手**：滑窗门槛 `max(4, window // 2)` = 10 枚样本、`failure_ratio=0.30`（`resilience.py:30-31`）⇒ 单次失败**不会 OPEN**；`config_failed` 只在 401/403 时标记同 provider（`fallback.py:520`），而本例两枚候选**同为 `ollama` provider** ⇒ 千万别把 `PROVIDER_CONFIG_FAILED` 的「同 provider 跳过」断言塞进 P0，那会自相矛盾。
4. **落库路径**：`conftest.py` 只在「调用方**没设** `CONVERSATION_DB_PATH`」时改道（`:28`）⇒ T10 若**手起宿主 uvicorn** 打真请求，账会写进 `backend/data/conversations.db`（默认相对 `data/conversations.db`，T6 N3 已记：非 `backend/` cwd 下行会落到 `<cwd>/data/`）。做法：起服务前 `export CONVERSATION_DB_PATH=<绝对临时路径>`，「usage 落库」与「零 prompt 入库」两枚断言都查**那一枚**库；跑完再复核实库 `llm_request_logs=0 / conversations=7 / messages=10`。
5. **`unknown` 归零闸不会被真调用打破**：`UnknownAttributionTests` 走**自建临时库**（`test_llm_egress_guard.py:652-666`，且它自己断言 `path_is_protected` 为假），T10 的行不进它的分母 ⇒ 不必为 T10 放宽任何口径。**但** T11 复述矩阵 §2 那句话时要写准：「全部 **mock** 用例跑完后 `error_type='unknown'` 为 0」，真调用产生的行属于另一件事（`model_unavailable` 是合法 kind，不是 unknown）。
6. **P0 行的 BLOCKED→GREEN 由谁翻**：承载闸**只按 AST 核 node-id 存在**（`_test_index()`，且 `test_every_row_carries_a_real_test_or_an_honest_status` 不跑 pytest）⇒ 一枚 `@unittest.skipUnless(Ollama 在跑)` 的例**也算存在**。所以 T10 交「GREEN」在机器上是可伪造的。口径：**T10 只交证据，不改表**；改 `BLOCKED→GREEN` 由主 agent 在核对 (a) 真 500 body 命中 `model_unavailable` 的原文、(b) `fallback_index=1` 的账行、(c) `trace_id` 全链一致 三件之后落，且改动要连同运行日志一起进 `docs/`。可选加固：给闸补一条「P0 行转 GREEN 时承载例名必须能被 `pytest --collect-only` 收到且**不带 skip 装饰器**」。
7. **`LLM_ROUTER_ENABLED` 与 legacy 支别混**：P0 必须在旗标为 true 下跑；注意 §9.1 的补正——关掉旗标**只**回退 rag/agent 两腿与对话链非流式腿，SSE 流式腿仍走路由（`fallback`/`provider`），所以「旗标 false 时也拿到了 failover」是**假绿**。
8. **别顺手把 C1/C4 改绿**：I-4 只证明了**出口体合协议**，云侧真连行为仍是 `PENDING_EXTERNAL`；本轮无 key，任何「配了 key 工具轮就能用」的措辞要留在矩阵 §4 的口径段里，不许进状态列。
9. **端点/健康面**：`OLLAMA_BASE_URL` 在 `app/` 里是 0 命中（运行期拼装，矩阵已记），probe 结果 60s 缓存（D4）⇒ 宿主 `ornith` 加载状态若在测试中途变化，`providers.ollama.healthy` 可能滞后 60s，别让 P0 的 status 断言撞上。
10. **T10 期间别跑的**：全套件重跑不必要（我这边定向已把 #9/#12/#12b/#16/#17/#19/#N-3 全验绿）；T10 只需定向 = 真机用例本身 + `test_llm_egress_guard.py`（若它动了 `app/` 任何出口面）+ `test_llm_usage_contract.py`（若它动账本）。

---

## 7. 移交 T11 的口径

**主 agent 已裁但本版没做的（照单全收，别当新发现）：**
- `app/config.py` 的 `env_file=".env"` **相对化**根因（产品侧正解）：届时 `TypeSafeJudgmentTests.setUp:75-76` 那两枚 `patch.object` 可以**退回**——它们是「加上的前提」不是「替代的断言」；同时矩阵 §5 第三行随之改口。
- §12 `llm_registry_file` 出厂默认改**包相对**（A-4 方案②）：动冻结默认值，需明确裁决；不做就维持例内 `os.chdir(BACKEND_DIR)`。
- m-7 响应面 `degraded` 键（Task 8 遗留，未动）+ §10 验收文档的「`agent_traces` 响应面键清单」口径。
- `_classification_query` **双份实现**：`app/agent.py:248-259` 与 `app/llm/__init__.py:382-390` 同一句话各写一份（我核过两份口径一致：都取「最后一条非空 content」）⇒ 统一成一处或写死「两份刻意并存」的理由。
- `data/audit.jsonl` 测试卫生：6783 行、每次套件都长（`conftest.py` 保护集不含它，m-B4 属实且早于段 B）。纳入护栏 = 改 `conftest.py`，另案。
- `unknown_rate` **不加**（Task 5 终裁：与 `success_rate` 共线）；归因走 `SELECT count(*) … WHERE error_type='unknown'`。这一条已被矩阵 §2 + `test_the_two_mandated_calibers_are_written_and_one_is_a_real_test`（含 `count("unknown_rate") <= 1`）机器化。

**本次评审新增的 T11 待办：**
- I-1 / I-2 / I-3 三件（若主 agent 让 T9 修复轮做，就**不进** T11）；Minor 1–11 逐条 triage。
- **验收文档那句「全套件只在 `backend/` 下有效」应当删**（Task 6 移交项已过时）：现在两种 cwd **同数**（段 A/B 报 928/0/974，我未重跑全套件但 `conftest.py` 未改、A-4 三处 cwd 钉我逐处读码确认在位）⇒ 按「两种 cwd 等价」写，别留下过时的自我设限。
- §9.1 的 0.1/0.2 回写（Task 7 裁过）与 #18 的「对话链流式腿无 legacy 形态」必须在 V2.3 验收文档点名（「不得当 SSE 止血开关」）。
- 矩阵承载闸的单向性（Minor 3）与第三层非独立测量（Minor 4）：若 T11 想收得更严，一并改；不改就在文档里把「耦合闸」限定为「文档→套件」。

---

## 8. 我实际执行的命令 / 关键输出 / sha1 对照

**定向测试（4 次跑，未重跑全套件）**

| 命令（cwd 均为 `backend/`） | 输出 |
| --- | --- |
| `python -m pytest tests/test_llm_egress_guard.py -q` | `29 passed, 85 subtests passed in 15.05s` |
| 矩阵 #9/#12/#12b/#16/#17/#19 的 **25 枚 node-id** 合跑 | `25 passed, 2 warnings, 26 subtests passed in 74.85s` |
| `pytest …::AgentNoCapableFastPathTests …::OllamaPayloadShapeTests::test_payload_does_not_mutate_the_request …::SingleEgressStructureTests -q` | `19 passed, 5 subtests passed in 67.76s` |
| 变异台 A 组 6 发 + B 组 6 发（`rev9_mutations.py`，每发注入/还原 + sha1 核对） | 见 `rev9_mutations.log`：A1/A4/A5/B1/B3/B4/B5 **RED**；A2/A3/A6/B2 **GREEN**（全部落进 I-1/I-2/Minor 5） |

**I-4 配对探针**：`python .superpowers/sdd/MODEL_ROUTER_V23_PLAN/rev9_probes.py`（P1–P12，纯函数 + 假数据，**零外呼**）；行尾核查
`agent.py crlf=1044 lf_total=1044 bare_lf=0` / `normalize.py crlf=0 lf_total=420`（**行尾没翻**，与报告一致）。

**sha1 对照表（我亲算，前 12 位；全部与 §0 / 两段报告的终值一致，且我跑完全部变异后复算仍一致）**

| 文件 | 我算的值 | 报告声称 | 判定 |
| --- | --- | --- | --- |
| `backend/app/llm/normalize.py` | `6e8a345ff322` | `6e8a345ff322` | 一致（本段义务面 I-4） |
| `backend/app/agent.py` | `9dabebf801ed` | `9dabebf801ed` | 一致（本段义务面 N-3，全 CRLF） |
| `backend/app/llm/fallback.py` | `008d8213bc05` | 同 | IDENTICAL |
| `backend/app/llm/usage.py` | `8a8f5b0cff28` | 同 | IDENTICAL |
| `backend/app/llm/__init__.py` | `c29e3c393f87` | 同 | IDENTICAL |
| `backend/app/rag.py` | `a5a638716947` | 同 | IDENTICAL（语义未越界，见必查 8） |
| `backend/app/conversation_agent.py` | `0ffcc353eb59` | 同 | IDENTICAL（禁改件） |
| `backend/app/agent_routes.py` | `1080fbd4a0c4` | 同 | IDENTICAL（禁改件） |
| `backend/app/security.py` | `d36b387aac6e` | 同 | IDENTICAL（白名单语义未动） |
| `backend/config/llm_registry.json` | `3e652e9cf496` | 同 | IDENTICAL（旗标未动） |
| `backend/tests/conftest.py` | `73d1060de465` | 同 | **IDENTICAL（护栏一字未改）** |
| `backend/tests/test_llm_egress_guard.py` | `9404e6ab01c0` | 同 | 一致（我 B3/B4/B5 三发字节变异已发内还原并复算） |
| `backend/tests/test_model_router_v23_contract.py` | `a4e99e2a3944` | 同 | 一致 |
| `backend/tests/test_llm_usage_contract.py` | `51f7660c43c2` | 报告未列 | 与 snap-task8-r1 diff = 仅 A-3 收紧（14 删全为替换） |
| `docs/MODEL_ROUTER_V23_MATRIX.md` | `46b607d97d39` | 同 | 一致 |

**临时件**：`rev9_probes.py`、`rev9_mutations.py`、`rev9_nodeids.txt`、`rev9_mutations.log`（全在 SDD 目录）；注入过的 `backend/app/rev9_probe_shot.py` 与 `backend/app/rev9sub/` 已随发删除并清 `__pycache__`，复算：`ls backend/app/rev9*` → 无、`backend/app/__pycache__/rev9*` → 无。git 侧只跑过 `status --porcelain` / `ls-files --others`（读）。唯一被我**追加过行**的非受审文件是 `backend/data/audit.jsonl`（套件既有行为，见 m-B4 / Minor 11）。

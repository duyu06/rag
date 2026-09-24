# Task 9 修复轮 · scoped 复审裁定（第 1 轮）

复审者：Task 9 修复轮 scoped 复审（只读 + 定向跑 + 变异台，未派子 agent）
日期：2026-09-24 · 工作目录 `E:\xiangmu\rag` · pytest 从 `backend/` 与仓库根各跑一次全套件
被审件：**零改动**（15 枚文件 sha1 逐枚全等，见 §1.3；中途一次自伤事故已当场按原串回插并复算全等，见 §7）
零 git 写 · **零真实外呼**（探针为纯函数级 `normalize` 调用；测试全走 `MockTransport`；11434 一次未打）

---

## Verdict

**`PASS`——放行 T10。**

三条 Important **全部实测落地**（I-1 由 11 枚对抗形状 + 2 发定向变异坐实；I-2 的 A2/A3 两形现在都 RED 且全套件无一例被新谓词误伤；I-3 的两枚断言真实存在、其中来源面那枚有**独立**的牙）。四种 cwd 组合数字、行尾、冻结件全部与修复者自述一致。

新发现 **7 条，全为 Minor，不阻断 T10**：其中 N-1（A-3 谓词的「混合形」仍可绕）与 N-2（新豁免档能吃死行）建议 T11 前收掉，两者都是 1–3 行的改法；余 5 条是口径/计数/固有边界。

对主 agent 那条裁定的判定：**采纳修复者读法 = 正确**（§2，含一条对修复者论证的纠正：§1.4 末段「要翻转只需删掉 `consumed.add(index)` 一行」不成立）。

---

## 0. 七件逐项表

| # | 必查项 | 结论 | 一句话证据 |
| --- | --- | --- | --- |
| 1 | I-1 跨槽配对 | **ADDRESSED** | P10 实打 `[None, 'k2']`；我另造 8 组 + 跨轮 + 幂等共 **11 枚形状全合规**（零跨槽、零重领、caller 不动）；`M1` 病灶复刻 ⇒ I-1 新例 **RED**（红在「第 1 枚回执领到 k2 就是跨槽错配」那一枚）；`M2` 不占槽 ⇒ **RED** 且探针退化 `[None, None]` + `B1` 基线也坏（两枚回执重领同一 id） |
| 2 | I-2 两形可绕 | **ADDRESSED（验收达标）**，残留见 N-1 | `M3` kwargs 形 **RED**、`M4` 隐式拼接形 **RED**（均红在 `assertEqual([], fact_speakers)`）、`M6z` 单引号对照 **RED**、`M5` 运行期拼键名 GREEN（= 已声明披露面）；新谓词**没误伤**：全套件两种 cwd 各 `935 passed / 0 failed`，AST 现算三支命中集 = ①`{usage.py}` / ③`{fallback.py}` / ④`{usage.py}` |
| 3 | I-3 假陈述 + 哑断言 | **ADDRESSED** | 两枚断言真实存在于 `test_model_router_v23_contract.py:7466-7469`；`M8`（DENIED 短路时 `evidence.clear()`）**RED 且红在新那枚**：`AssertionError: 2 != 0 : 拒绝面短路不改来源面…` ⇒ 来源面枚有独立牙；`M7`（DENIED 吃 N-3 的门）红在**文案面**（`…无权访问…` != `差旅住宿上限每天陆佰元 [1]。`）而非 note；报告/矩阵三处更正都是**原文就地**（`task-9b-report.md:207-215` 删除线 + 更正块、`task-9a-report.md:47-54`、矩阵 §4:96-101），非追加段 |
| 4 | m-4 三层真互验 | **ADDRESSED**（精度补记见 N-7） | `code_hits()` 是**另一条遍历**（行集过滤 `_count(pattern, lines, code)`），不调用 `fulltext_hits`/`prose_hits`；`M11`（`code_line_numbers()` 返空集）⇒ **7 failed**、`M12`（不减散文）⇒ **6 failed** ⇒ 测量腿不是派生腿的橡皮章；`M13b`（命中从注释挪进纯代码行）⇒ **2 failed**，但红的是**手写的两张表**，`derived == measured` 与分区/跨算法三枚全绿 ⇒ 见 N-7 的固有边界 |
| 5 | m-3 反向闸 | **ADDRESSED** | `M14` 我在 `test_llm_egress_guard.py` 尾部塞一枚不挂矩阵的 `Rev9r1ClassNotInAnyMatrixRow` ⇒ **RED**（`'Rev9r1ClassNotInAnyMatrixRow' not found in '<矩阵正文>'`，红在 subTest 的类名上），发内还原并 sha1 全等；清单由 AST 现算 ⇒ 现 7 张类表 / 35 枚例（我逐类数过） |
| 6 | 新豁免档 `app/llm/fallback.py` | **正当，但不是「养闲档」的全防**（→ N-2） | ③ 命中它 = 事实定义方（`selected_index: int = 0` 字段 + `context_dropped=` 构造 kwargs），①④ 两支对它**零命中** ⇒ 键名字面量面仍只有 `usage.py`（`M3/M4` 的红法也证明新档买不到九键构造权）；死行方向：`M15` 往 `ROUTE_FACT_TRANSPORT_FILES` 加 `app/store.py` ⇒ **GREEN**（能吃死行），对照 `M16` 往 D6 的 `EXEMPTIONS` 加同一枚 ⇒ **RED**（那张表有 `set(EXEMPTIONS) == seen` 双向闸） |
| 7 | 有没有放宽 | **零放宽** | 对 `snap-task8-r1/tests/` 全量 diff：`conftest.py 0/0`、`test_agent_contracts 0/0`、`test_agent_routing_contracts 0/0`、`test_p17_streaming 0/0`、`feishu 0 删/12 增`、`usage 14 删/90 增`、`v23 2 删/405 增`——**删的行数与首轮评审 §6 逐文件逐条全等** ⇒ 修复轮相对首轮基线**一行未删**（那 14 行全是 A-3 旧谓词/`path.name` 豁免键的替换，2 行是 `test_payload_does_not_mutate_the_request` 升级为三条深拷贝等式）；`conftest.py` 仍 `73d1060de465` |

---

## 1. 我亲跑的终态（不采信自述）

### 1.1 两种 cwd 全套件

| 命令 | 我的实测 | 修复者自述 | 判定 |
| --- | --- | --- | --- |
| `cd backend && python -m pytest tests -q` | **935 passed, 22 warnings, 981 subtests passed in 205.30s** | 935 / 0 / 981（205.57s） | **一致** |
| `cd /e/xiangmu/rag && python -m pytest backend/tests -q` | **935 passed, 22 warnings, 981 subtests passed in 202.22s** | 935 / 0 / 981（206.10s） | **一致（两向同数）** |

主 agent 亲跑的 928/0/974 是**修复前**终值；+7 例（I-1 一枚 + 守卫件六枚）与 +7 subtest（反向闸对 7 张类表逐枚 `subTest`）我对得上盘面：守卫件 AST 现算 `class *Tests` = **7 张 / 35 枚**（段 A 交付 29 枚 + 6）。

控制发：`pytest tests/test_model_router_v23_contract.py::AgentNoCapableFastPathTests -q` ⇒ **15 passed, 5 subtests**（与 `OpenAIMultiTurnReplayTests` 的 9 枚合起来 = 24，正对上修复者 §9 行 2 改口的 21→23→24）。

真实库只读复核（跑完两趟全套件之后）：`backend/data/conversations.db` = **`llm_request_logs=0 / conversations=7 / messages=10`** ✓；仓库根 `data/conversations.db` 无 `llm_request_logs` 表（未被写过）。`backend/data/audit.jsonl` 6783 → **6805 行**（评审首轮 m-11 的既有卫生项；**我自己的定向跑也贡献了行**，与修复者无关）。

### 1.2 行尾

| 文件 | 实测 | 应为 | 判定 |
| --- | --- | --- | --- |
| `backend/app/llm/normalize.py` | `crlf=0 / lf=435 / 435 行` | 纯 LF、435 行 | ✓ |
| `backend/app/agent.py` | `crlf=1048 / lf=1048 / 裸 LF=0 / 1048 行` | 全 CRLF、1048 行、零裸 LF | ✓ |

### 1.3 sha1（15 枚，全部我亲算）

冻结 9 枚：`fallback.py=008d8213bc05`、`usage.py=8a8f5b0cff28`、`llm/__init__.py=c29e3c393f87`、`rag.py=a5a638716947`、`conversation_agent.py=0ffcc353eb59`、`agent_routes.py=1080fbd4a0c4`、`security.py=d36b387aac6e`、`config/llm_registry.json=3e652e9cf496`、`tests/conftest.py=73d1060de465` ⇒ **9/9 IDENTICAL**。
本任务义务面 6 枚：`normalize.py=41597af45085`、`agent.py=bb3606778b63`、`test_llm_egress_guard.py=eff2ac079565`、`test_llm_usage_contract.py=7f3bd5316650`、`test_model_router_v23_contract.py=5dcfca837e10`、`docs/MODEL_ROUTER_V23_MATRIX.md=3d64f707f7c5` ⇒ **与修复者 §6 表逐枚全等**（即：修复者的终值我现在独立复算成立，且我 19 发变异跑完仍全等）。

---

## 2. 对主 agent 那条裁定的判定：**你对，采纳修复者的读法**

### ① 与 `normalize.py:110-120` 的承诺是否一致 ⇒ **一致**

同文件 `:114` 写「同名多枚 ⇒ 按 assistant 里的出现次序逐一消费（**第 N 枚回执配第 N 枚调用**）」，`:117-119`（修复轮新写）把这条钉死到 id 面上：空 id「照样按次序占槽、只是自己那条写不出、且不许跨槽」。
`[None, 'k2']` 正是这条的**唯一**读法：回执 1 ↔ 槽 0（写不出）、回执 2 ↔ 槽 1（`k2`）。而 `[None, None]` 要求「回执 2 也退回槽 0」⇒ 槽 1 无人认领 ⇒ **第 2 枚回执没配第 2 枚调用**，直接违反 `:114`。所以 `[None, None]` 不是「更强的次序语义」，它是次序语义的另一半失效。主 agent 判「评审首轮那句验收句写错了、修复者的读法才对」= 成立。

### ② 跨槽错配在两种读法下是否都被杀死 ⇒ **都被杀死**

- 修复者读法下：`M1`（可配对性挪回入口，即病灶本体）⇒ I-1 新例 **RED**，失败消息逐字是「第 1 枚回执对应的调用没有 id ⇒ 写不出配对键；领到 k2 就是跨槽错配」。
- 评审字面读法（`[None,None]`）下：同一枚输入的第 1 枚回执同样不许带 `k2` ⇒ `assertNotIn("tool_call_id", mapped[1])` 同样红。
⇒ 「回执 1 领走 `k2`」这个缺陷本体在**任何**读法下都过不了新例，两种读法的分歧只在**第 2 枚回执的落点**，不在病灶。所以这一条不构成口径未收口。

### ③ 反证：**不需要**（我不推翻该裁定）；但要给修复者的论证挑一处错

`task-9-fix-report.md` §1.4 末段：「若终审坚持字面 `[None, None]`……**删掉 `consumed.add(index)` 一行即可**」——**这句不成立**。`M2` 就是照这句做的：删掉该行 ⇒ P10 确实打成 `[None, None]`，但同发的 `B1`（两枚同名、id 都是非空的**基线形状**）退化成 `['k1','k1']`——**两枚回执重领同一枚 id**，比原病灶更糟（原病灶至少 id 唯一，只是错配）。因为 `consumed` 在这条支上只有这一处写入者。
结论：字面 `[None,None]` 若要落，需要的是「一枚不可配对 ⇒ 整轮停止配对」的**另一套语义**（另写代码、另改 docstring），而不是「删一行」。这条建议写进下一轮报告的更正里（我已计入 §3 的新发现，级别 Minor，因为它只在报告里，不在代码里）。
另外两条支持主 agent 的事实：① `[None,'k2']` 是**能救多少救多少**的那一侧——槽 1 的配对仍然成立，只有真正写不出 id 的那一枚留缺陷；② 两种读法在云侧**都是 400**（一轮里有 `id=""` 的 `tool_calls` 本身就不合协议），所以这里不存在「另一种读法能变绿」的收益，只有可读性差别。

我的 11 枚形状（`rev9r1_probes.py`，全部 `ALL OK = True`）：
`P10`（评审原形 `[None,'k2']`）、`B1` 两枚都有 id、`B2` 空 id 夹中间（`['k1',None,'k3']`）、`B3` 孤儿回执先出现（`[None,None,'k2']`）、`B4` 空 id + 异名、`B5` 名字指向后面的槽（`[None,'k0']`）、`B6` 三枚回执抢两枚槽（`[None,'k2',None]`，不重领）、`B7` 两枚空 + 一枚非空、`B8` 自带 id 优先 + 空 id 占槽（`['d1',None,'d3']`）、`C1` 跨轮回看最近未消费轮（`[None,'w1']`）、`D1` 出口体喂回第二次逐字相等。
每枚都同时核：无跨槽、无重领（`dup-claim=False`）、`req.messages` 未被改写。

---

## 3. 新发现（定级 + 修法）

| # | 级别 | 发现 | 证据 | 修法 |
| --- | --- | --- | --- | --- |
| N-1 | **Minor**（I-2 的完备性残留，建议 T11 前收） | **混合形绕过**：两枚事实各用**不同**形状写 ⇒ 三支谓词全瞎（每支都要求「同一支内成对」）。`M6x`（一枚隐式拼接 + 一枚 kwargs）、`M6y`（一枚带引号 + 一枚 kwargs）**实测 GREEN**；对照 `M6z`（两枚都单引号）RED | `rev9r1_mutations.log` M6x/M6y/M6z | 把「成对」从**支内**改成**跨支按键**：`sel = ①sel or ③sel or ④sel`、`ctx = ①ctx or ③ctx or ④ctx`、`rebuilds = sel and ctx`（①③④各自拆成两枚单键谓词，仍是 3–4 行）。今天命中集不变（①④ 只 usage.py、③ 只 fallback.py），两张豁免表不用动 |
| N-2 | **Minor** | A-3 的三档豁免表**能吃死行**：往 `ROUTE_FACT_TRANSPORT_FILES` 加一枚从不搬运事实的文件，四枚断言全绿；D6 的 `EXEMPTIONS` 不行（有 `set(EXEMPTIONS) == seen` 互等闸） | `M15` **GREEN** vs `M16` **RED（2 failed）** | 把单向的 `assertTrue(档 <= scanned)` 换成 `assertEqual(档, set(实测 speakers) | 交集)` 形式（或直接照 `test_exemption_table_has_no_dead_rows` 抄一枚等式）。同一条也顺手覆盖 `ROUTE_KEY_MOUNT_FILES`（同样只做了子集检查） |
| N-3 | **Minor（口径）** | I-3 新补的第二枚 `assertIn("无权访问", result["answer"])` 被同一例 `:7456` 的**全串等式**吞掉 ⇒ 它永远不可能成为第一处失败（`M9b` 把文案换成不含「无权访问」的串，红的是 `:7456`）。评审首轮点名要这句，所以不算修复者的错，但它**没有独立牙** | `M9b` 失败消息指向 `:7456` 的等式 | 二选一：①改成负向（`self.assertNotIn("暂时失败", result["answer"])`，挡「拒绝面被失败文案替换」这一支的**另一半**）；②在 docstring 里写明「解释性冗余，承重的是 `:7456` 与 `:7466`」。**别删**——它是「刻意不同源」这句话的读者锚点 |
| N-4 | **Minor（计数）** | 报告与盘面差 1：`task-9-fix-report.md` §9 行 5 称 `D6FullTextFieldTests`「现 8 例」，AST 现算 **7 例**；`task-9a-report.md:24` 与矩阵 §3 称 `NoBareValueErrorOnTheChainTests`「7 枚」，盘面 **8 枚** | 我的逐类计数（§0 表第 5 行的手法：AST 现算 `test_` 方法） | 两处数字改口，并按 m-3 自己立的规矩写成「清单由 AST 现算，枚数随盘面」而不是硬写数字 |
| N-5 | **Minor（事实）** | `task-9-fix-report.md` §2.2「命中集只有两枚文件——`fallback.py`（③）与 `usage.py`（①**③**④）」与盘面不符：`usage.py` **不命中 ③**（它写的是 `"selected_index": value` 冒号形，全文件没有 `context_dropped =`）。同报告 §2.1 表里「③ 今天命中 `fallback.py`」才是对的 | `rev9r1_probes.py` F 段：①`{usage.py}` / ③`{fallback.py}` / ④`{usage.py}` | §2.2 那半句改成「`usage.py`（①④）+ `fallback.py`（③）」——这正是两档豁免各配一枚外圈等式的**理由**，写对了反而更有说服力 |
| N-6 | **Minor（口径）** | 守卫件 `CODE_EXPECTED` 表注（`:346`）仍写「代码面 = 全文 − 散文（下表是差值，由第三层的加法等式再核一遍）」，与模块 docstring 新口径「三面都是逐行数出来的」自相矛盾；另有几处「散面」漏字（`:203`、`:486`） | 逐行读码 | 表注改口成「代码面：**行集测量**（`code_hits()`）；下表是它的期望值」；顺手补「文」字 |
| N-7 | **Minor（固有边界，移交 T11 知情）** | 散文分类器按**整行**归类 ⇒ 「同一行既有代码又有注释」时该行的代码命中被散文面吞掉。我的 `M13` 第一发正是因此**打点无效**（新代码行尾带了 `#`，命中没挪动，三层全绿）；改成不带注释的纯代码行（`M13b`）才红。另：`derived == measured` 那枚互验在 prose↔code 迁移下**同增同减**（`M13b` 只有两张手写表红），它真正扛的是**分类器被改坏**（`M11`/`M12` 实测 7 failed / 6 failed） | `M13`（无效发）→ `M13b` **RED 2 failed** | 不必修（现状保守方向 = 多算进散文，不放过任何命中：**代码面 + 散文面 = 全文面**恒成立）。要收得更严：`_count` 按 token 级切分（`tokenize` 已有 COMMENT token）。文档侧：把 `test_the_measured_code_face_is_confirmed_by_the_ast_face` docstring 里「派生值与 CODE_EXPECTED 仍然自洽，只有这条会红」那句改准——`M11` 实测那条情形下**派生值同样红**（7 枚里就有它） |

**没有新增 Important/Critical**：I-1/I-2/I-3 的缺陷本体都已被坐实杀干净，N-1 是「刻意用两种语法写同一条事实」的静态钉完备性，且九键的第二产地今天仍由属性级 + 导出面 + 出口体三枚钉共同挡着。

变异台总计 **19 发**（我亲跑，`rev9r1_mutations.log` / `…2.log` / `…3.log`）：killed/符合预期 **16 发**；期望存活 **1 发**（`M5` = A6 运行期拼键名）；**2 发未预期存活 = N-1**（`M6x`/`M6y`）；**2 发我首批打点无效**（`M9` 还原锚点不唯一而中止、`M13` 整行分类吞掉命中），各自第 2 批纠正后 killed。

---

## 4. m-4 三层「是不是真互验」的正面回答

- **代码面是独立测量吗？** 是。`code_hits()` 与 `fulltext_hits()`/`prose_hits()` 是三条独立遍历，`_count()` 只是「行集过滤 vs 不过滤」的差别；`code_hits()` 不调用另两张表（`ScanningHelpersAreAllLiveTests::test_the_code_face_is_measured_from_line_sets_not_derived` 直接把这条做成 AST 断言，`:918-922`）。`M11`（行集返空集）⇒ **7 failed**、`M12`（行集不减散文）⇒ **6 failed**：测量腿单独坏掉时派生腿抓不到，反过来也一样 ⇒ **不是恒真**。
- **跨算法互验有恒真风险吗？** 有一半，但不是死码。`import_httpx` 那一枚：`AST_IMPORTS_EXPECTED` 与 `CODE_EXPECTED["import_httpx"]` **今天内容逐字相同**，所以「AST 表 == 代码面测量」与「代码表 == 代码面测量」里的第一枚只挡「有人**改了其中一张手写表**」这一种漂移；真正带信息量的是端点那一枚（AST 侧是**逐文件嵌套 dict**、行集侧是**两枚模式拍平**，两种数据形状）与「AST 测量 == AST 表」（`D6AstFaceTests`，完全不读散文行集）。⇒ 结论：**不恒真、但对 `import_httpx` 的边际强度低于 docstring 的自我描述**，按 N-7 末项改口即可。
- **三张表都还有牙吗？** 有：`M13b` 证明「命中从注释挪进代码」这种迁移**只由手写表承接**（`PROSE_EXPECTED` + `CODE_EXPECTED` 各红一枚，其余五枚绿）。这与模块 docstring 的说法一致（「谁把出口挪进注释里躲 AST 面，全文面就红」），不冲突。

---

## 5. m-3 反向闸的边界（照首轮口径，不擅自扩）

首轮给的修法就是「`test_llm_egress_guard.py` 的类名每枚都被矩阵引用一次」⇒ 修复者照做，边界两条都是**首轮指定**的，不是他的缩水：
1. 粒度是**类**不是**例**（同一张类表里再加一枚例不会被反向闸要求点名）——修复者 §11.3 已自曝。
2. 覆盖面只有**这一枚文件**：别的测试文件新增一张不挂表的类仍然绿。矩阵 §1 第 ④ 条的措辞现在写的是「`test_llm_egress_guard.py` 的每一枚测试类」⇒ **名实相符**，没有 over-claim。这条留给 T11 决定是否扩到全套件（成本 = 矩阵要加「按文件的类清单」一节）。

---

## 6. T10 开工前置清单：逐条对（首轮 §6 那 10 条）

| 首轮条 | 现在的状态 | 缺什么 |
| --- | --- | --- |
| 1 选对链路（两枚 ollama `capabilities.tools=false`、`priority.tools=0` ⇒ agent 工具轮必走 D2，P0 只能挂 rag/SSE） | **仍然成立**，注册表 `3e652e9cf496` 一字未动，我复 dump 过 | 无。谁为了凑两次 attempt 去翻 `tools` 旗标 = 改注册表 = 越界，先要裁决 |
| 2 超时预算（`llm_total_budget_ms=30000 / le=120000`、`llm_model_timeout_seconds=20`） | **仍然成立**（`config.py:91-92` 实测在位） | 无（`ollama run phi3:mini` 预热 + 用例前提写进 brief 是 T10 自己的动作） |
| 3 熔断滑窗 `max(4, window//2)`、`failure_ratio=0.30`、别把「同 provider 跳过」塞进 P0 | **仍然成立**（`resilience.py:30-31,48-54`） | 无 |
| 4 落库改道只在「调用方没设 `CONVERSATION_DB_PATH`」时发生 | **仍然成立**（`conftest.py` 仍 `73d1060de465`，docstring 第 1 条未变） | 无：T10 手起宿主服务前必须 `export CONVERSATION_DB_PATH=<绝对临时路径>` |
| 5 `unknown` 归零闸走自建临时库、不被真调用打破；但 T11 复述矩阵 §2 时要写「全部 **mock** 用例跑完后 unknown=0」 | 代码侧成立（`UnknownAttributionTests` 仍 2 枚、自带临时库） | **措辞还没落**：矩阵 §2/§5 现在都没写「mock」这个限定（矩阵 §5 只改了 935/981 的数）。⇒ **记进 T11 待办，缺的就是这一句** |
| 6 P0 的 `BLOCKED→GREEN` 由谁翻（承载闸只按 AST 核存在 ⇒ 一枚带 `@unittest.skipUnless` 的例也算「存在」，机器上可伪造） | **未加固**（`test_every_row_carries_a_real_test_or_an_honest_status` 仍不跑 pytest、不查 skip；修复轮的「双向闸」不覆盖这一点） | **缺**：这条要么按原口径写成**流程条款**进 T10 brief（「T10 只交证据、不改表；改表由主 agent 核对 500 body 原文 / `fallback_index=1` 账行 / `trace_id` 全链一致三件之后落，且连运行日志一起进 `docs/`」），要么把首轮给的可选加固补上（P0 行转 GREEN 时承载例必须能被 `--collect-only` 收到且**不带 skip 装饰器**）。**这是七件之外我唯一认为 T10 开工前必须有明确处置的一条** |
| 7 `LLM_ROUTER_ENABLED` 与 legacy 支别混（关掉旗标只回退 rag/agent 两腿，SSE 流式腿仍走路由） | 未被本轮改动（矩阵 §9.1 补正仍在） | 无 |
| 8 别顺手把 C1/C4 改绿 | **仍然 PENDING_EXTERNAL ×4**（矩阵 `:45-48`），P0 仍 `BLOCKED`（`:44`） | 无 |
| 9 `OLLAMA_BASE_URL` 在 `app/` 0 命中 + probe 60s 缓存滞后 | 仍在（恒 0 表 `FULLTEXT_EXPECTED["ollama_base_url_env"] = {}` 我核到） | 无 |
| 10 T10 期间不必重跑全套件 | 现在更强：两种 cwd 同数由我独立复算过（§1.1） | 无 |

⇒ **清单基本齐**；要点名的两条缺口都是**流程/文档**类：第 6 条（P0 转绿的处置权与 skip 装饰器）与第 5 条（矩阵 §2 的「mock」限定词）。都不需要再动产品代码。

---

## 7. 纪律自证

- 临时件全部在 SDD 目录：`rev9r1_probes.py`、`rev9r1_probes.log`、`rev9r1_mutations.py`、`rev9r1_mutations2.py`、`rev9r1_mutations3.py`、`rev9r1_mutations.log`、`rev9r1_mutations2.log`、`rev9r1_mutations3.log`、`rev9r1_fullsuite_backend.log`、`rev9r1_fullsuite_root.log`、本文件。产品树里 `find backend -name '*rev9r1*'` = **无残留**（每发 `finally` 删注入件 + 清 `__pycache__` 里同名 pyc）。
- 变异纪律：字节读写 + 锚点**恰命中一次**断言 + 发内还原 + **每发核 sha1**（19 发全 `IDENTICAL`）+ 收尾再核 15 枚全等。
- **一次自伤如实披露**：首批 `M2` 我用了空串作还原锚点（`b""`），`unmutate` 的「命中一次」断言在空串上退化成 `len+1` 而抛错，导致 `normalize.py` 一度缺 `consumed.add(index)` 那一行（`sha1` 从 `41597af45085` 漂到 `d6ed170428ef`，434 行）。我当场从修复者自己的 `t9fix_mutations.py:106`（那枚发把原串抄在变异脚本里）取回**逐字原串**、按位置回插，复算 `sha1=41597af45085 / lf=435 / crlf=0` **全等**后继续；此后所有发射加了 atexit 回写兜底（第 2 批 `M9` 的锚点在 `agent.py` 里出现 2 次 → 由 atexit 自动回写，`verify` 记 `IDENTICAL`）。教训与修复者 §8 那发「首批打点无效」同族：**还原锚点必须非空且唯一**。
- 零 git 写（只跑过 `status --porcelain` / `log` 读）；零真实外呼（探针纯函数、测试走 `MockTransport`；11434 未被任何一发触碰）。
- 被审文件我只读不写；两处**报告级**建议（N-4/N-5/N-7 的改口）我没有替修复者动笔，因为本轮义务是裁定不是修文档。

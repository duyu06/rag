# Task 9 修复轮报告（A+B 两段 · 第 1 轮 / 上限 5 轮）

评审裁定：Approved-with-fixes（Critical 0 / Important 3 / Minor 11）
本轮做的：FIX-1（I-1）+ FIX-2（I-2）+ FIX-3（I-3）+ FIX-4（Minor 1/2/3/4），其余按 brief 的
defer 清单移交。日期 2026-09-24 · 工作目录 `E:\xiangmu\rag` · pytest 一律从 `backend/` 起。

## 0. 状态（先看结论）

| 门 | 结果 |
| --- | --- |
| 门 1 定向（三文件） | `python -m pytest tests/test_llm_usage_contract.py tests/test_llm_egress_guard.py tests/test_model_router_v23_contract.py -q` ⇒ **517 passed / 0 failed / 485 subtests（120.64s）**（`t9fix_gate1.txt`） |
| 门 2 两种 cwd | `cd backend && python -m pytest tests -q` ⇒ **935 passed / 0 failed / 981 subtests（205.57s）**；`cd /e/xiangmu/rag && python -m pytest backend/tests -q` ⇒ **935 passed / 0 failed / 981 subtests（206.10s）**。基线 928/0/974 ⇒ **+7 例 / +7 subtest / 0 例被删或降级**（拆解见 §7） |
| 门 3 变异 | **13 发**：11 killed + **1 发期望存活**（MU-8 = 评审 A6，运行期拼键名，留在已声明的披露范围内）+ **1 发首批打点无效**（MU-4 写错了，如实记录并在第 2 批纠正后 killed）。存活清单见 §8 |
| 门 4 报告 | 本报告 + **两段报告就地更正**（不是追加段：`task-9a-report.md` 三处、`task-9b-report.md` 三处，改前/改后引文见 §9）+ 矩阵 §1/§3/§4/§5 同步改口 |
| 真实库只读复核 | `llm_request_logs=0 / conversations=7 / messages=10`（两种 cwd 全套件跑完仍是 0/7/10） |
| 冻结件 | 9 枚逐枚 **IDENTICAL**（§6 表），`normalize.py` 与三枚测试文件仍纯 LF、`agent.py` 仍全 CRLF 零裸 LF |
| 零真实外呼 | 探针 = 纯函数级 `normalize` 调用；测试 = 假 host + `MockTransport`；11434 一次都没打（P0 仍归 T10） |

**四件状态**：FIX-1 ✅（含一处与 brief 验收句的分歧，§1.4 逐字交代）· FIX-2 ✅（比 brief 预想多
一处必须裁决的点：新增谓词会命中**冻结件** `app/llm/fallback.py`，§2.2）· FIX-3 ✅ · FIX-4 ✅（4 条全做）。

## 1. FIX-1 = I-1｜空 id 调用让后面的调用跨槽领走回执（真实缺陷）

### 1.1 病灶与根因

`backend/app/llm/normalize.py` 旧 `:183`（`_matching_call` 槽扫描入口）：

```python
    for index, call in enumerate(calls):
        if index in consumed or not isinstance(call, dict):
            continue
        if not _pairable_id(call):          # ← 病灶：把「能不能写出 id」当成「谁是第 N 枚调用」
            continue
```

两枚规则叠在同一处 ⇒「第 N 枚回执配第 N 枚调用」实际变成「配第 N 枚**可配对**调用」，空 id 的
调用从轮里凭空消失。评审探针 P10（`id=["","k2"]` + 两枚按序回执）修复前实测
`['k2', None]`：第一枚回执跨槽领走了第二枚调用的 id，第二枚成孤儿——与同文件 `:120-124`
的承诺（「同名多枚 ⇒ 按 assistant 里的出现次序逐一消费」）直接冲突，也是云 key 到位后唯一
**静默错配而不是 400** 的形状。

### 1.2 改了什么（按评审给的 4 行方向）

- `_matching_call`：删掉入口那两行，**只**按名字/次序选槽（docstring 写明「这里不看 id 可不可
  配对」）。
- `_paired_tool_receipt`：选出 `index` 之后**先 `consumed.add(index)` 占槽**，再判
  `if not _pairable_id(calls[index]): return None` ⇒ 不可写出时宁缺不错配，但槽位已被消费，
  下一枚回执不会退回来重复领。
- 三处文字同修：`_replay_messages` 的配对规则第 6 条改成「空 id 的调用**照样按次序占槽**但
  写不出 `tool_call_id`，且**不许跨槽**去领后面调用的 id」；`_pairable_id` 的 docstring 加
  「这是**出口**判据，不是**槽位**判据」；`_matching_call` docstring 写明把两层混在一处会跨槽。

### 1.3 承载测试与红→绿

新增 `OpenAIMultiTurnReplayTests::test_a_call_with_an_empty_id_does_not_let_a_later_call_steal_its_receipt`
（`backend/tests/test_model_router_v23_contract.py`，评审点名那枚），逐字钉四个落点：
`["", "k2"]` 原样留在回放里、第 1 枚回执**没有** `tool_call_id`（不是 `"k2"`）且 `tool_name`
仍在、第 2 枚回执 = `"k2"`、`req.messages` 与深拷贝基准逐字相等。

红→绿证据（同一条 `-k steal_its_receipt` 单跑）：

| 实现 | 该例结果 |
| --- | --- |
| 修复前形状（可配对性在入口，`MU-1` 复刻） | **RED** `1 failed, 380 deselected in 66.84s` |
| 只删「占槽」这一半（`MU-1b` 复刻） | **RED** `1 failed, 380 deselected in 68.47s` |
| 本轮修复后 | **GREEN**（含在 §0 门 1/门 2 里） |

评审探针复跑：`python .superpowers/sdd/MODEL_ROUTER_V23_PLAN/rev9_probes.py` ⇒ P10 现在打
`[None, 'k2']`（`t9fix_probes_after.log`）。P1/P2/P3/P4/P5/P8/P9 逐枚复核与评审 §5 表第 2 行
一致（`c1,c2` / `yB,xA` / 孤儿不造 id / `d1,d2` 占槽 / 幂等 / caller untouched / 三枚回执第三枚孤儿）。

### 1.4 与 brief 验收句的分歧（必须交代的一条）

brief 与评审 I-1 的**验收句**写的是「P10 现在必须打出 `[None, None]`」，而**同一处的行级修法**
（「先按名/按次序选出 `index`（不筛 id），把可配对性判断移到选出之后，**同时 `consumed.add(index)`
占掉该槽**，否则下一枚回执会退回来重复领」）在这枚输入上只能打出 `[None, 'k2']`：

- 回执 1 → 槽 0（空 id，不可写出）⇒ 无 `tool_call_id`，槽 0 入 `consumed`；
- 回执 2 → 槽 1（`k2`，可写出）⇒ `"k2"`。

`[None, None]` 只在**忘了占槽**的写法下出现（回执 2 退回重复领槽 0、于是永远碰不到槽 1）——
那正是评审自己排除掉的形状，也是 `MU-1b` 那一发。且 `[None, None]` 会让槽 1 变成孤儿，反而
破坏 docstring 的次序规则（「第 2 枚回执配第 2 枚调用」），也就是 I-1 这一类病灶本身。
**取舍**：本轮按「修法 + 占槽 + 不跨槽」落地，两枚真实语义都进断言（回执 1 无 id、回执 2 = k2），
`[None, None]` 这句按上述理由改口；缺陷本体（回执 1 领走 `k2`）在两种读法下都被杀掉，
`MU-1`/`MU-1b` 一发都活得不了。若终审坚持字面 `[None, None]`（即「一枚不可配对 ⇒ 整轮不再配对」），
删掉 `consumed.add(index)` 一行即可，此时本例第 4 枚断言会反过来响。

### 1.5 附带披露

段 B 报告 `m-B3` 已就地补上「**且不许跨槽**」这半句（§9 表第 3 行）；矩阵 §4 的 #12b 配对规则同步。

## 2. FIX-2 = I-2｜A-3 收紧后仍可绕的两形（按评审方案①收口）

### 2.1 改了什么（`backend/tests/test_llm_usage_contract.py`）

**事实面**的谓词从 1 支（带引号成对）扩到 3 支（带引号 / kwargs / AST 常量），加上一支键名面
谓词，本文件现在共 5 枚编译后的 pattern；三支事实谓词都保持 brief 点名的「同形」=
两枚各 `search` 再 `and`，不引入顺序假设，然后三支之间 `or`：

| # | 谓词 | 挡的形 | 今天命中 |
| --- | --- | --- | --- |
| ① | `[\"']selected_index[\"']` × `[\"']context_dropped[\"']` | 带引号字面量（段 A 的收紧） | `usage.py` |
| ② | `MODEL_ROUTE_KEY` / `[\"']model_route[\"']` | 键名（挂载点面） | `agent_trace.py` |
| ③ 新增 | `\bselected_index\s*=` × `\bcontext_dropped\s*=` | **kwargs / 赋值形**（`dict(stage=…, selected_index=…, context_dropped=…)` 无引号） | `fallback.py` |
| ④ 新增 | `ast.parse` 后 `{"selected_index","context_dropped"} ⊆ {ast.Constant 值}` | **隐式拼接形**（`{"selected_" "index": …}`，CPython 合成单枚常量） | `usage.py` |

④ 走 AST 而不是再堆正则（与 `SingleEgressStructureTests` 同一手法），且**整枚相等**判定天然不
误伤注释与 docstring（docstring 是单枚整段常量，不可能等于键名）。`import ast` 是本文件新增。

### 2.2 一处 brief 没预见、必须裁决的点：③ 命中了**冻结件**

`app/llm/fallback.py`（冻结，`008d8213bc05`）本来就在源码里以 kwargs/赋值形写这两枚事实——它是
**事实的定义方**（`selected_index: int = 0` 的 dataclass 字段、`context_dropped=self.context_dropped`
的构造 kwargs，实测 30+ 处）。**实测数据**：三支事实谓词跑全 `app/`，命中集只有两枚文件——
`fallback.py`（③）与 `usage.py`（①③④）。

处理：不动冻结件、也不放宽谓词，而是把豁免拆成两档并**各配一枚外圈等式**：

```python
ROUTE_OBJECT_PRODUCER_FILES = frozenset({"app/llm/usage.py"})          # 键名字面量面：一字未动
ROUTE_FACT_TRANSPORT_FILES  = ROUTE_OBJECT_PRODUCER_FILES | {"app/llm/fallback.py"}   # 只给③那一支
...
self.assertEqual(sorted(ROUTE_OBJECT_PRODUCER_FILES), sorted(key_literal_speakers),
                 "把九键的键名写成字面量的文件必须恰是那枚唯一生产者")   # ⇒ 实测 == ["app/llm/usage.py"]
self.assertEqual(["app/llm/fallback.py"], sorted(fact_transport_speakers),
                 "kwargs/赋值形搬运 `selected_index`+`context_dropped` 的只许事实定义方")
```

所以 `fallback.py` 的豁免**买不到任何九键构造权**：它在①④两支上零命中（等式已钉），③一支放开
的是「以字段/kwargs 搬运事实」这件事，而那件事它本来就在做。既有断言一条没删（原来的
`assertEqual([], fact_speakers)` / `assertEqual([], key_speakers)` / 扫描面非空 / 豁免子集四枚
全在，只把子集检查换成新档名）⇒ 净效果**严格更严**。

### 2.3 docstring 改口（不再自称过宽）

原句「本钉只挡**源码字面量**；运行时注入…由 #17 兜」按实际覆盖重写为：
「本钉覆盖**写在源码里的键名**（带引号 / kwargs / 隐式拼接三形，含注释之外的字符串常量）；
仍挡不住**运行期拼出来的键名**（`f"{'selected'}_index"`、`"".join([...])`），那一类由 #17 的
三枚真落盘断言兜」⇒ 评审 A6 那形从此名实相符。

### 2.4 验收：A2/A3 两形列为期望 RED，跑绿即收口

| 发 | 注入形 | 期望 | 实测 |
| --- | --- | --- | --- |
| MU-7（A1 回归） | `{"selected_index": 1, "context_dropped": 2}` | RED | **RED** `1 failed, 1 passed, 99 deselected in 60.21s` |
| MU-2（A2） | `dict(stage="fallback", selected_index=1, context_dropped=2)` | RED | **RED** `1 failed, 1 passed, 99 deselected in 59.85s` |
| MU-3（A3） | `{"selected_" "index": 1, "context_" "dropped": 2}` | RED | **RED** `1 failed, 1 passed, 99 deselected in 67.98s` |
| MU-8（A6） | `f"{'selected'}_index"` / `f"{'context'}_dropped"` | **GREEN（刻意）** | **GREEN** `2 passed, 99 deselected`（= 披露范围内，§2.3） |

## 3. FIX-3 = I-3｜报告不实 + 哑断言

### 3.1 评审查明的事实（复核确认成立）

`test_a_denied_current_round_keeps_the_hard_copy_even_with_evidence_in_hand`
（`backend/tests/test_model_router_v23_contract.py`）段 B 交付时断言的是
`answer` / `requests == []` / `raw_rows() == []` / `len(trace_rows())` / `note` / `tool_status`
六件事，**一条都没碰 `num_sources` 或 `sources`**；而段 B 报告 m-B1 写「现状已被…钉住（可观察、
不是哑的）」⇒ 该断言不存在，是报告把「例子的返回值里有 `num_sources=2`」当成了「例子断言了它」。
本轮复核：产品侧 `agent.py` 收尾处 `num_sources=len(evidence)`（现 `:1041`）确实取在手的 2。

### 3.2 改了什么（不动产品代码）

该例末尾补两枚断言 + docstring 写明理由：

```python
        # ↓ 现状钉（评审 I-3 之前这两枚是缺的 ⇒ 报告所称「已钉住」当时并不成立）。
        self.assertEqual(2, result["num_sources"],
                         "拒绝面短路不改来源面：在手的 2 枚仍然报 2（刻意不同源，见 docstring）")
        self.assertIn("无权访问", result["answer"],
                      "文案必须留在拒绝面上，不许被失败文案或合成答案替换")
```

docstring 补一句：这是**刻意保留**的不同源（拒绝面优先），终审若要统一口径必须**同时**改文案与
来源面（改一侧就让这两枚里的一枚红；只把文案换成合成答案 = 让 DENIED 吃门 = 前面四枚立刻红）。
矩阵 §4 那句「遗留 minor：…（拒绝面优先，见报告）」同步改成「现状已钉住、是否统一待终审」。

### 3.3 验收：变异打在哪一支上

`unittest` 一枚例只报第一个失败 ⇒ 「两支都红」不能在同一发里一次看全，本轮用**两头发在两支上
各响一次**来证明两枚都是承重的：

| 发 | 打点 | 期望 | 实测（响在第几支） |
| --- | --- | --- | --- |
| MU-4 | 摘掉 `if status == "DENIED":` 判据 ⇒ DENIED 掉进 N-3 那枚「手上没货才短路」的门（评审原话的形状） | RED | **RED** `1 failed … in 66.57s`，响在**文案支**：`AssertionError: '当前账号无权访问该知识库…' != '差旅住宿上限每天陆佰元 [1]。'`（答案变成合成结果 ⇒ `assertIn("无权访问")` 同支也必红，`note` 不再是唯一落点） |
| MU-4b | 保留短路、把拒绝面文案换成失败文案（两支合并的另一半偷懒路） | RED | **RED** `1 failed … in 63.50s`，响在**文案支** |
| MU-9 | 保留硬文案、只在 DENIED 短路时 `evidence.clear()`（**只动来源面**，即「统一口径」的另一种走法） | RED | **RED** `1 failed … in 63.43s`，响在**来源支** = 新加的 `assertEqual(2, result["num_sources"])` |

⇒ 「不只是红在 note 上」成立；新补的来源枚有**独立**牙（MU-9 那种改法旧套件全绿）。

## 4. FIX-4 = Minor 1/2/3/4（同轮做掉）

- **m-1**（`app/agent.py` docstring 第 ④ 项）：原文「④文案短路：DENIED / 检索失败 / 零证据三支
  走同源硬文案且**零外呼**」补齐前提 ⇒ 现写作「④文案短路：**DENIED**（不吃门）/「检索失败**且
  手上没货**」/ 零证据三支…」并点名「本轮失败但在手有授权证据时**不短路**，继续合成（N-3，与
  `status != "SUCCESS" and not evidence` 那支逐字对齐）」。**只改注释**，字节级落盘、CRLF 未翻。
- **m-2**（会漂的裸行号）：
  - `agent.py` 失败支注释里的 `:601` 自指 → 改为「`run_agent` 的 D2 catch 里 `stage == "context"`
    那支自家理由（"证据已在手 ⇒ 直接走 tools-free 合成"）」，并补一句「刻意**不写裸行号**…按函数名
    + 分支条件定位」；同段 `:521-530` 也换成「工具回路每轮 append、`evidence_keys` 去重」。（顺带
    说明：评审给的示例「`_degrade_to_local_fast_path` 里失败短路那支」不是那枚理由的所在地，
    实测「证据已在手」在 `run_agent` 的 catch 内，本轮按盘面事实指。）
  - 同类外溢一处：`tests/test_llm_egress_guard.py` 里 `#: - app/agent.py:652 run_agent 的 mode 越界`
    修复前就已漂（真身在 `:700`），一并换成「文件 + 函数 + 分支」写法。指向**冻结件**
    （`conversation_agent.py:307-321` 等）的行号**不动**：那枚文件不许改，行号是稳定的。
- **m-3**（单向耦合闸）：新增
  `MatrixDocumentClosureTests::test_every_guard_test_class_is_discoverable_from_the_document`
  ——AST 现算 `test_llm_egress_guard.py` 的测试类清单（含「类里必须有 `test_` 方法」的判据），
  逐枚 `assertIn(类名, 矩阵正文)`。
  **口径修正**：评审写「12 枚类名」，实测本文件是 **6 张类表 / 29 枚用例**（`class ` 全量 grep =
  6；修复轮后 7 张 / 35 枚），清单由 AST 现算 ⇒ 新增类自动进分母，不硬写 12。
  配套：矩阵表头段改成「双向闸（①②③ + ④ 反向）」，§3 的 #19 行同口径；`ScanningHelpersAreAllLiveTests`
  这个新类名也进了矩阵（否则新闸自己第一个红）。闸的红→绿由 `MU-5` 证明（见 §8）。
- **m-4**（第三层不是独立测量）：取 brief 的**优先方案**——用行集真算一遍代码面。
  - 新增 `code_hits()`：把每枚模式的命中限制在 `code_line_numbers()` 的行集上（**独立代码路径**：
    行集过滤 vs 算术差）。原先零使用的 `code_line_numbers()` 现在有两名调用者。
  - `test_fulltext_face_equals_code_face_plus_prose` 从「一张派生表」升级为**三次测量互核**：
    `CODE_EXPECTED == 派生值` ∧ `CODE_EXPECTED == 测量值` ∧ `派生值 == 测量值` ∧ 原文的
    逐文件加法等式（一条没删）。
  - 新增 `test_the_three_faces_are_measured_on_a_real_line_partition`：逐文件核
    `prose ∩ code == ∅` ∧ `prose ∪ code == 全行` ∧ 两族都非空 ⇒ 「代码面」不再只是派生量的别称。
  - 新增 `test_the_measured_code_face_is_confirmed_by_the_ast_face`：**跨算法**互验——行集测出的
    `import_httpx` 代码面必须等于 AST 面（`ast_httpx_imports()`，它**完全不读**散文行集），端点两枚
    模式必须等于 `ast_endpoint_string_constants()`。实测两张表今天逐枚相等。
  - 新增类 `ScanningHelpersAreAllLiveTests`（3 枚）：①`SCAN_HELPERS` 14 枚 helper 一枚都不许没有
    调用者（「不许留着未使用的 helper 假装它在起作用」）；②`code_hits` 必须被第三层那三枚用例调用；
    ③`code_hits` 的**函数体**必须引用 `code_line_numbers` 且不得引用 `fulltext_hits`/`prose_hits`
    （只核「有人调用」挡不住「挪去别处调用、第三层又变回推导」）。
  - 三发的红→绿：`MU-6`（`code_hits` 改回算术差）⇒ RED；`MU-6c`（`code_line_numbers()` 返回空集，
    派生值仍等于 `CODE_EXPECTED`）⇒ **RED `7 failed`** ⇒ 证明「测量」不是推导的橡皮章；
    `MU-5`（塞一枚不挂表的类）⇒ RED。

## 5. 改动面（本任务窗口 = 段 A + 段 B + 修复轮，列全）

### 5.1 产品代码（2 枚，全部在授权清单内）

| 文件 | 段 A | 段 B | 修复轮 | 行尾 |
| --- | --- | --- | --- | --- |
| `backend/app/llm/normalize.py` | 未动（`c6bc8b0caf81`） | I-4 映射：`c6bc8b0caf81` → `6e8a345ff322`（297→420 行） | I-1：`6e8a345ff322` → `41597af45085`（420→435 行，纯函数面） | 纯 LF（crlf=0 / lf=435） |
| `backend/app/agent.py` | 未动（`59d4cd3b3c3b`） | N-3 门 + 注记：→ `9dabebf801ed`（1000→1044 行） | **仅注释/docstring**：→ `bb3606778b63`（1044→1048 行） | 全 CRLF（crlf=1048 / lf=1048，零裸 LF） |

修复轮**没有**改 `agent.py` 任何可执行语句：两发替换的 old 串分别是 docstring 段与 `#` 注释段，
另加一条 `py_compile` 复核；`_degrade_to_local_fast_path` 的判据一字未动（DENIED 仍不吃门）。

### 5.2 测试代码（4 枚）

| 文件 | 段 A | 段 B | 修复轮 |
| --- | --- | --- | --- |
| `tests/test_llm_egress_guard.py` | 新建（900 行 / 29 例 / 85 subtests） | 未动（`9404e6ab01c0`） | `9404e6ab01c0` → `eff2ac079565`（900→1096 行 / **35 例** / 92 subtests）：`code_hits()` + 分区自核 + 跨算法互验 + `ScanningHelpersAreAllLiveTests`(3) + 反向耦合闸 + m-2 行号改口 + 模块 docstring 改口 |
| `tests/test_llm_usage_contract.py` | A-3 收紧（`51f7660c43c2`） | 未动 | `51f7660c43c2` → `7f3bd5316650`（2041→2089 行）：`import ast` + 两枚新谓词 + `_string_constants()` + 两档豁免 + 两枚外圈等式 + docstring 改口 |
| `tests/test_model_router_v23_contract.py` | A-4 chdir 钉 | I-4/N-3 例（`387f90eb1537` → `a4e99e2a3944`，7396→7745） | `a4e99e2a3944` → `5dcfca837e10`（7745→7791 行）：I-1 新例 1 枚 + DENIED 例补 2 枚断言与 docstring |
| `tests/test_feishu_identity_contract.py` / `tests/test_typesafe_judgments.py` | A-4 外溢（cwd 前提显式化） | 未动 | 未动 |

三枚被改的测试文件行尾全部保持纯 LF。`tests/conftest.py` 一字未改（`73d1060de465`）。

### 5.3 文档与工具

- `docs/MODEL_ROUTER_V23_MATRIX.md`：段 A 新建 → 段 B `46b607d97d39` → 修复轮（§1 表头「双向闸」、
  `#12b` 行补第 8 枚 node-id、§3 #19 行改口、§4 配对规则补「不许跨槽」+ DENIED 现状改口、
  §5 计数 928/974 → 935/981）终值见 §6 表。
- 两段报告就地更正（§9）。
- SDD 目录新增：`t9fix_mutations.py`、`t9fix_mutations2.py`、`t9fix_mutations2.log`、
  `t9fix_probes_after.log`、`t9fix_fullsuite_backend.txt`、`t9fix_fullsuite_root.txt`、
  `t9fix_gate1.txt`、本报告（不进产品树）。
- 工作树时间戳复核（`find backend/app backend/tests docs -newermt "16:40"`）：Task 9 窗口内被动的
  文件恰为 `agent.py`、`llm/normalize.py`、4 枚测试文件、矩阵 —— 无第三方文件。

## 6. 冻结件 sha1 前后表（修复轮开工前 / 收尾后各算一次）

| 文件 | 基线（主 agent 交付值） | 本轮收尾实算 | 判定 |
| --- | --- | --- | --- |
| `backend/app/llm/fallback.py` | `008d8213bc05` | `008d8213bc05` | IDENTICAL |
| `backend/app/llm/usage.py` | `8a8f5b0cff28` | `8a8f5b0cff28` | IDENTICAL |
| `backend/app/llm/__init__.py` | `c29e3c393f87` | `c29e3c393f87` | IDENTICAL |
| `backend/app/rag.py` | `a5a638716947` | `a5a638716947` | IDENTICAL |
| `backend/app/conversation_agent.py` | `0ffcc353eb59` | `0ffcc353eb59` | IDENTICAL |
| `backend/app/agent_routes.py` | `1080fbd4a0c4` | `1080fbd4a0c4` | IDENTICAL |
| `backend/app/security.py` | `d36b387aac6e` | `d36b387aac6e` | IDENTICAL |
| `backend/config/llm_registry.json` | `3e652e9cf496` | `3e652e9cf496` | IDENTICAL |
| `backend/tests/conftest.py` | `73d1060de465` | `73d1060de465` | IDENTICAL（护栏一字未改） |
| — 本任务义务面 — | | | |
| `backend/app/llm/normalize.py` | `6e8a345ff322` | `41597af45085` | FIX-1（LF 420→435） |
| `backend/app/agent.py` | `9dabebf801ed` | `bb3606778b63` | FIX-4 m-1/m-2（注释面，CRLF 1048/1048） |
| `backend/tests/test_llm_egress_guard.py` | `9404e6ab01c0` | `eff2ac079565` | FIX-4 m-3/m-4 |
| `backend/tests/test_llm_usage_contract.py` | `51f7660c43c2` | `7f3bd5316650` | FIX-2 |
| `backend/tests/test_model_router_v23_contract.py` | `a4e99e2a3944` | `5dcfca837e10` | FIX-1/FIX-3 |
| `docs/MODEL_ROUTER_V23_MATRIX.md` | `46b607d97d39` | `3d64f707f7c5`（LF，87→113→**125** 行） | FIX-3/FIX-4 改口（§1 双向闸、#12b 承载例、§3 #19、§4 两处、§5 计数） |

变异台每发都「发内还原 + sha1 回到修复轮终值」：`normalize.py=41597af45085`、`agent.py=bb3606778b63`、
`test_llm_egress_guard.py=eff2ac079565` 在 13 发跑完后逐枚复算一致（脚本尾部自证）。
注入过的 `backend/app/rev9fix_probe_shot.py` 已随发删除并清 `__pycache__`，复算
`find backend/app -name "*rev9*" -o -name "*probe_shot*"` → 无残留。

## 7. 验收门实测与增量拆解

- 门 2 两枚命令**同数**：`935 passed / 0 failed / 981 subtests`（backend cwd 205.57s、仓库根 cwd 206.10s）。
- +7 例：I-1 新例 1 枚 + `test_llm_egress_guard.py` 6 枚（分区自核、跨算法互验、反向耦合闸、
  `ScanningHelpersAreAllLiveTests` 3 枚）。
- +7 subtests：全部来自反向闸对 **7 张**类表的逐枚 `subTest`。
- 0 例被删、0 枚断言被放宽：`test_fulltext_face_equals_code_face_plus_prose` 的原四条等式全部
  保留（只是派生值旁边多核了两枚测量值）；A-3 那枚例的原四枚断言一字未删；DENIED 例只**加**断言。
- 真实库只读复核 `0 / 7 / 10`；全套件跑完仍是 `0 / 7 / 10`。

## 8. 变异表（13 发；`t9fix_mutations.py` / `t9fix_mutations2.py`）

纪律：一律**字节**读写 + 断言恰命中一次 + 跑子集 + **发内还原** + sha1 核对；注入件只在 `app/`
下被静态扫描读到，**从不 import**；零 git 写；零真实外呼。

| 发 | 打点 | 期望 | 结果 |
| --- | --- | --- | --- |
| MU-1 | 可配对性判断**挪回 `_matching_call` 入口**（I-1 的病灶复刻） | RED | **RED** `1 failed … 66.84s` |
| MU-1b | 选出槽后**不占槽**（下一枚回执退回来重复领） | RED | **RED** `1 failed … 68.47s` |
| MU-7 | A1 带引号字面量形【回归】 | RED | **RED** `1 failed, 1 passed … 60.21s` |
| MU-2 | A2 kwargs 形 | RED | **RED** `1 failed, 1 passed … 59.85s` |
| MU-3 | A3 隐式拼接形 | RED | **RED** `1 failed, 1 passed … 67.98s` |
| MU-8 | A6 运行期拼键名（`f"{'selected'}_index"`） | **GREEN（刻意）** | **GREEN**（= 披露范围内，§2.3；**这是本轮唯一存活的发，且是期望存活**） |
| MU-4（首批） | `if False: pass` + `elif status == "DENIED":` ——**打点无效**：DENIED 仍走自己的支 | 期望 RED | **GREEN ⇒ 记为 SETUP 无效**，第 2 批纠正 |
| MU-4（第 2 批） | 摘掉 `if status == "DENIED":` 判据 ⇒ DENIED 吃 N-3 的门 | RED | **RED** `1 failed … 66.57s`（响在文案支） |
| MU-4b | 拒绝面文案换成失败文案（两支共用文案） | RED | **RED** `1 failed … 63.50s`（响在文案支） |
| MU-9 | DENIED 短路时 `evidence.clear()`（只动来源面） | RED | **RED** `1 failed … 63.43s`（响在**新加**的 `num_sources` 枚） |
| MU-5 | 套件塞一枚不挂矩阵表的测试类（反向闸） | RED | **RED** `1 failed, 9 passed … 3.88s` |
| MU-6 | `code_hits()` 改回「全文 − 散文」算术差 | RED | **RED** `1 failed, 8 passed … 3.52s` |
| MU-6c | `code_line_numbers()` 返回空集（派生值仍等于 `CODE_EXPECTED`） | RED | **RED** `7 failed, 5 passed … 13.63s` |

**存活清单（如实）**：只有 MU-8 一枚存活，且是**期望存活**（评审 I-2 的 A6 形，属已声明的
「运行期注入」范围，本轮同时把 docstring 的自述收窄到与之一致）。首批 MU-4 那发的 GREEN 是
**变异写错**（不是测试没牙），已按纠正形状重跑并 killed，两批都留在表里不遮蔽。

## 9. 就地更正的原文对照（改前 / 改后）

| # | 位置 | 改前（原文） | 改后 |
| --- | --- | --- | --- |
| 1 | `task-9b-report.md` §「移交终审的 minor」m-B1 末句 | 「现状已被 `test_a_denied_current_round_keeps_the_hard_copy_even_with_evidence_in_hand` 钉住（可观察、不是哑的）。」 | 原句加删除线保留 + 【修复轮就地更正 · 评审 I-3】「上面这句划掉的话在段 B 交付时**不成立**：那枚用例当时断言的只有 `answer` 硬文案等式 / `requests == []` / `raw_rows() == []` / `len(trace_rows()) == 1` / `note` / `tool_status` 这六件事，**一条都没碰 `num_sources` 或 `sources`**…现在这句话才成立：修复轮已补两枚断言（`assertEqual(2, result["num_sources"])` + `assertIn("无权访问", result["answer"])`）…」 |
| 2 | `task-9b-report.md` §FIX-B1「修复后」段 | 「⇒ **21 passed / 5 subtests**」 | 原数保留 + 括注「修复轮复跑实测 **23**（8+15），段 B 的 21 是陈旧计数（与评审 Minor 10 同族，非不实自述）；修复轮 +1 枚 I-1 例后为 **24**」 |
| 3 | `task-9b-report.md` m-B3 | 「刻意选『宁缺不错配 + 缺陷留在可观察处』…」 | 追加「**【修复轮补全披露 · 评审 I-1】这句原来漏了半条：且不许跨槽**」+ 病灶、P10 实测、承载例名 |
| 4 | `task-9a-report.md` §D6 扫描终态首句 | 「三层关系：`全文面命中 == 代码面 == AST 面 + 散文面`——…」 | 更正为 `全文 == 代码 + 散文`（AST 面是另一条独立算法的四张等式表），并加【修复轮 · 评审 Minor 4】说明当时代码面是**推导**的（`code_line_numbers()` 零使用 ⇒ 内圈恒真），现已改为测量 + 三重互验 |
| 5 | `task-9a-report.md` 交付清单 `D6FullTextFieldTests` / `MatrixDocumentClosureTests` 两行 | 「（5 例）…第三层关系 `全文 == 代码 + 散文`」/「（5 例 + 1 例注册表前提）：文档↔套件耦合闸。」 | 各加【修复轮】注：前者现 8 例（代码面测量、分区自核、跨算法互验）；后者点明「段 A 交付时它是**单向**闸」+ 现 6 例双向 |
| 6 | `task-9a-report.md` A-3 交付项 docstring 句 | 「docstring 补『本钉只挡源码字面量，运行时注入由 #17 集成用例兜』…」 | 追加【修复轮 · 评审 I-2】两形可绕（kwargs / 隐式拼接）+ 事实面谓词从 1 支扩到 3 支 + 自述改成实际覆盖面 |
| 7 | 矩阵 §4 #12b 配对规则 | 「…空 id 不参与配对、配不上就**不造假 id**」 | 「…空 id 的调用**照样按次序占槽但写不出** `tool_call_id` 且**不许跨槽**去领后面调用的 id（Task 9 复审 I-1）」 |
| 8 | 矩阵 §4 N-3 末句 | 「遗留 minor：`DENIED` + 在手证据时仍是硬文案而 `num_sources` 记在手的量（拒绝面优先，见报告）。」 | 「**现状已钉住**（Task 9 修复轮 I-3）：…由该例末尾两枚断言钉成事实；是否统一口径待终审裁…」 |

## 10. defer（本轮没做，移交清单）

- 评审 §4 第 **5–11** 条：非 httpx 客户端的两枚恒 0 模式（m-5）、`ValueError` 扫描面的「业务入口」
  措辞（m-6）、`_paired_tool_receipt` 自带 id 支与配对口支不同形（m-7）、`openai_payload` 对不可
  JSON 序列化 `arguments` 抛 `TypeError`（m-8）、非 dict 非 str 的 `arguments` 同对象透传（m-9）、
  段 A 的 subtest 计数差 1（m-10，本轮已在 §9 表第 2 行以 21→23 的形式并表记录）、
  `data/audit.jsonl` 测试卫生（m-11，6783 行且每次套件都长）。
- `env_file` 产品侧绝对化（连带 `TypeSafeJudgmentTests.setUp` 两枚 `patch.object` 可退回）；
  m-7 响应面 `degraded` 键；`_classification_query` 双份实现；`unknown_rate`（T5 终裁不加）；
  云 4 项 `PENDING_EXTERNAL`（C1–C4）；P0 十字（归 T10）。
- §12 `llm_registry_file` 出厂默认改包相对（方案②，动冻结默认值需裁决）。
- T11 提示（评审 §7）：验收文档别再写「全套件只在 `backend/` 下有效」——本轮两种 cwd **同数 935/0/981**
  是新的直接证据；§9.1 的 0.1/0.2 回写与 #18「对话链流式腿无 legacy 形态」要点名。

## 11. 遗留与风险（给下一轮 / 终审）

1. `[None, None]` vs `[None, 'k2']` 的口径分歧（§1.4）是本轮**唯一**未照 brief 字面落的验收句，
   理由与证据在 §1.4：按字面做会重新引入 I-1 自己反对的那类次序破坏。要翻转只需删一行，
   且本例第 4 枚断言会立刻反向响。
2. ③（kwargs 谓词）的豁免面里出现了 `app/llm/fallback.py`（§2.2）。它是**事实定义方**、
   在键名字面量面上零命中（等式已钉），但「新增一档豁免」这件事本身值得终审复核一句：
   若不愿认这档，替代做法是把③换成「只扫 `dict(...)` / 构造调用里的 keyword」并仍会命中
   `fallback.py`（`:542/:643/:701/:904/:912` 都是真 kwargs），所以除非允许它、除非把③收窄到
   挡不住 A2 —— 没有第三条路。
3. `m-3` 的反向闸按「类名出现在矩阵正文一次」判，粒度是**类**不是**例**（评审给的修法就是这个
   粒度）。若终审想要「每枚例都可反向发现」，得给表加一列承载例全清单，成本 = 文档重写。
4. `m-4` 的测量与派生共用同一个散文分类器（`docstring_and_comment_lines`），所以「两路相等」
   挡的是分类器被改坏时**表**与**AST 面**的分叉（`MU-6c` 已证），不是两套分类器的投票；
   真正独立的那一枚是跨 AST 面的 `test_the_measured_code_face_is_confirmed_by_the_ast_face`。
   这一点在 docstring 与矩阵 §3 里都按实际写，没自称「三套独立实现」。

# V2.3-P0-EVIDENCE-PORTABILITY 3B 报告 · 把 P0 闸改成校验可移植证据包

**工作树态**：零提交、零 git 写命令（本轮用过的 git 面只有 `git status` / `git ls-files` /
`git diff` / `git config --get` / 在 `%TEMP%` 里的一次 `git clone` + 一次 `git rev-parse`，
**源仓 `E:\xiangmu\rag` 的树与 index 一字未动**）。
**增量写**：每取到一格读数就立刻落档，末了不回头补叙述。

## 0. 本步动的文件与不碰的东西

| 文件 | 改动 | 性质 |
| --- | --- | --- |
| `backend/tests/real_llm_failover_kit.py` | 新增 §8（portable 层判据 + 双条件原始件定位 + 面对面核对 + `p0_evidence_verdict()`）；§1 新增 `MODEL_UNAVAILABLE_MARKERS` 常量；§6 `validate_evidence()` 里那枚 inline 元组换成引用该常量（**字面一字未改**）；模块 docstring 加一节 §8 边界 | 判据**分层**，`validate_evidence()` 的判定本体未改 |
| `backend/tests/test_real_llm_failover_gate.py` | ③ 的取数改走 `kit.p0_evidence_verdict()`；新增外部锚常数 `PORTABLE_MANIFEST_SHA256`；新增 `_verdict_branch_line` / `_portable_failure_note` / `_problem_list_block`；`test_the_evidence_judgment_does_not_degrade` 追加 portable 层 15 发内存探针；`_evidence_absence_note` 追加一条【订正 3B】（旧文字**保留不删**）；模块 docstring 加「③ 的载体分层」一节 | 不新增 node-id、不删断言、不 skip、不 xfail |
| `docs/MODEL_ROUTER_V23_MATRIX.md` | §4.5 ③ 那一条**文案**补一句「判据分 portable 层（无条件）+ raw 层（在场才跑）」 | **状态字 `GREEN` 一字未动**（下方读数 4 用 sha 证明该行仍逐字存在） |
| `.superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/p0_3b_mutations.py` | 新增九发证伪台（gitignored） | 交付面无影响 |

未触碰：`backend/app/**`、`.gitattributes`、`.github/workflows/ci.yml`、
`backend/tests/test_ci_gate_contract.py`（`EXPECTED_COLLECTED` 仍是 **1335**、本轮没动也没「凑」）、
`backend/tests/test_secret_hygiene_contract.py`（`git diff --exit-code` rc=0，见读数 4）、
两枚 tag、`docs/evidence/**` 六枚交付件（只在证伪台里被临时注入、每发 `finally` 原字节还原，
见读数 3）。

## 1. 新闸的判定形状（代码落点）

```
gate.test_p0_row_status_matches_the_evidence
  ├─ status = kit.matrix_p0_status()                       # 现读矩阵 P0 行，不缓存
  ├─ verdict = kit.p0_evidence_verdict(manifest_sha256_pin=PORTABLE_MANIFEST_SHA256)
  │     ├─ read_portable_bundle()                          # 仓根锚定（BUNDLE_DIR ← __file__），绝不按 cwd
  │     ├─ validate_portable_bundle(payload, pin)          # 七条 interlock + [C-*] 逐条判据  ← 无条件必须过
  │     ├─ resolve_raw_provenance(manifest)                # source_run_dir + sha1 双条件定位原始件
  │     ├─ raw_state:
  │     │     full      → validate_evidence(raw) + raw_layer_problems + cross_check   ← §6 判据一字未改
  │     │     json-only → 只做 cross_check（干净签出的正常形态：raw 本体不在场 ≠ 红）
  │     │     absent    → 不参与
  │     └─ problems = portable + raw
  ├─ print(_verdict_branch_line(verdict))                  # 「走了哪一层」是判据的一部分，绿的时候也要能看见
  └─ problems ⇒ 要求 status == "BLOCKED"；否则要求 status == "GREEN"
```

外部锚取「钉进闸文件常量」这一支（简报给的两枚候选里取一），理由写在常数上方的注释里，
摘要：闸文件是**被执行、被闸①源码面扫、被 B0 收集数钉**的代码面，改它是一处评审看得见的 diff；
把锚落进 markdown 等于让「验收文档说啥算啥」重新长回来——那正是 R26 ③ 明令不许走的第二条出路。
代价也写在同一处：真机重跑会换 manifest 字节 ⇒ 必须同批更新这枚常数，漏更则 `[I2]` 响亮地红。

## 2. 读数 1：干净签出把这枚闸从红转绿（本单的存在理由）

取法（全部在 `%TEMP%`，源仓零写入）：

```
T=/tmp/tmp.NFhXqizM0r ; git clone -q --no-hardlinks -c core.autocrlf=false E:/xiangmu/rag $T/ragclone
cd $T/ragclone && git rev-parse HEAD     → 7923ee47955197406ee0dd498f74587d8915a7d8
克隆里只有**已跟踪**文件 ⇒ 这正是 CI 的形态（`actions/checkout` 也只看得到跟踪面）。
再把本轮交付面覆进去（克隆工作树里做，源仓不动）：
  cp docs/evidence/model-router-v23/real-llm-failover-001/*.json   → 克隆同路径（六枚）
  cp backend/tests/real_llm_failover_kit.py / test_real_llm_failover_gate.py → 克隆同路径
六枚 + 两枚 .py 全部 `cmp` 与源仓**逐字节相同**（cp OK ×8，原文见 evidence/p0-3b-clean-clone-gate.txt 抬头段）
克隆里的 raw 形态（决定性的一条）：
  ls $T/ragclone/.superpowers/.../task10/  → 只有 real-llm-failover-001.json（这枚已被跟踪、R18 那次入的库）
  ls $T/ragclone/.superpowers/.../task10/run → No such file or directory
  → 四枚 raw 里三枚缺席、run 目录整层缺席 ⇒ §6 那枚「按绝对路径重算 sha1」在这棵树上永远算不出
```

末次读数（`--tb=short -s`，PYTHONIOENCODING=utf-8；全文 `evidence/p0-3b-clean-clone-gate.txt`）：

```
cd $T/ragclone/backend && python -m pytest tests/test_real_llm_failover_gate.py -q -p no:cacheprovider -s
[P0 闸③ 分支] portable 层：0 条问题（bundle 目录 C:\Users\zhang\AppData\Local\Temp\tmp.NFhXqizM0r\
  ragclone\docs\evidence\model-router-v23\real-llm-failover-001，读包结果 None）
  | raw 层状态 = json-only（full = §6 validate_evidence() 实跑；json-only = 只跑面对面核对；
  absent = 完全不参与）| raw 问题 0 条
  | 原始件双条件定位：trace_jsonl=缺席, ledger_db=缺席, primary_probe=缺席, acceptance_module=在场
15 passed, 26 subtests passed in 5.94s
```

⇒ **从红转绿成立**，且红的那枚节点（`P0MatrixStatusLockedToEvidenceTests::test_p0_row_status_matches_the_evidence`）
在干净签出里是**绿**的，矩阵状态字没有被改动（`grep -c 'trace 1 行） | GREEN |'` = 1，见读数 4）。

### 2.1 反证：绿不是「载体被静默放过」

同一棵克隆里把 `docs/evidence/` 整层挪走（盘上其余一切不动），同一条命令：

```
[P0 闸③ 分支] portable 层：1 条问题（… 读包结果 'missing'） | raw 层状态 = json-only | raw 问题 0 条
  · [I1] bundle 整包不在场（docs/evidence/model-router-v23/real-llm-failover-001 下一枚都没读到）：
    可移植证据包是 3B 之后 P0 的唯一 CI 判据载体
2 failed, 13 passed, 11 subtests passed in 7.05s
FAILED …::test_p0_row_status_matches_the_evidence
FAILED …::test_the_evidence_judgment_does_not_degrade
```

载体缺席 ⇒ 当场红，红因点名的是**载体**，失败文案同时写明「原始件不在场不是这一格红的原因」
与「出路不是把矩阵改成 BLOCKED」。挪回来之后（六枚 `cmp` 逐字节相同）复跑 `15 passed, 26 subtests`。
全文 `evidence/p0-3b-clean-clone-no-carrier.txt`。
第二枚 FAILED 是 `test_the_evidence_judgment_does_not_degrade` 的**前置断言**在喊
「bundle 本身就不成立，这发探针证明不了任何事」——设计如此，不是附带伤害。

## 3. 读数 2：本机（raw 在场）同一条也绿，且 raw 层确实执行了

`cd E:\xiangmu\rag\backend && python -m pytest tests/test_real_llm_failover_gate.py -q -s`
（全文 `evidence/p0-3b-local-rawfull-gate.txt`）：

```
[P0 闸③ 分支] portable 层：0 条问题（bundle 目录 E:\xiangmu\rag\docs\evidence\…，读包结果 None）
  | raw 层状态 = full（full = §6 validate_evidence() 实跑；…）| raw 问题 0 条
  | 原始件双条件定位：trace_jsonl=在场, ledger_db=在场, primary_probe=在场, acceptance_module=在场
15 passed, 26 subtests passed in 5.61s
```

**走的是哪条分支 = `full`**：四枚原始件都能按 `source_run_dir` + name 双条件定位到，
于是 §6 的 `validate_evidence()` 被**完整执行**（不是被跳过、不是被 bundle 顶替），
外加 provenance 逐枚 sha1 重算与 `[X]` 面对面核对。干净签出走的是 `json-only`——
两条分支各有实跑读数，分层不是纸面分层。

分支判定的代码位置：`real_llm_failover_kit.p0_evidence_verdict()`（§8）——
`raw_state = "full"` 的条件是 `evidence is not None and all_present`，
`all_present` 来自 `resolve_raw_provenance()` 的逐枚 `Path.is_file()`，
**没有任何一条按 basename 搜索或按字节大小挑选**。

## 4. 读数 3：九发变异台账（逐发 KILLED-ASSIGNED + RESTORED-OK）

台子 `.superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/p0_3b_mutations.py`；
**终态代码那一轮**的整轮输出 `evidence/p0-3b-mutation-bench-final.txt`（逐发 pytest 原文
`.superpowers/sdd/ENTERPRISE_B0_PLAN/tmp/p0-3b-red-M{1..9}.txt`，本轮覆盖前一轮的存档）。

> **台账要说平白的一页**：这台子第一版跑出来的九发**全部是 `KILLED-INCIDENTAL`**——判决本身没错
> （九发确实都红），错的是**归因仪表**：`re.match(r"^(?:FAILED|ERROR) tests/\S+::(\S+)")`
> 只取到方法名，而 `ASSIGNED` 含类名前缀 ⇒ 永远对不上；而且 `subTest` 形态的红出的是
> `SUBFAILED` 行，只按 `FAILED` 行归因会漏读。修完仪表（node-id 取两级 + 三态 + 收 `SUBFAILED`）
> 之后**整轮重跑**，本节与上表是重跑那轮的读数；两轮的**判决本身逐字相同**（九发都红、
> 红因哨兵都在），被推翻的一直是仪表文案，不是任何一发读数。
> **（L5 更正，修复轮 1）** 原句「第一轮的原文保留在 `evidence/p0-3b-mutation-bench.txt`，
> 不当成功台账」**不成立，已作废**：实测那枚文件与 `p0-3b-mutation-bench-final.txt`
> **逐字节相同**（两枚 sha256 都是 `e2617049…`、5145 B，各自 `INCIDENTAL` 字样命中 0 次）
> ⇒ 第一轮的 9×`KILLED-INCIDENTAL` 原文**没有被存档**，`evidence/` 里那两枚都是重跑那一轮的。
> 两处仪表缺陷的披露仍然可信——它们记在**台子的 docstring** 里（`mutations/p0_3b_mutations.py`
> `run_gate()` 上方，本轮又补了第三条），不在 `evidence/` 里；本轮把它写成「没留下档」，
> 因为留下了档才该说「保留在」。

归因口径（比 B0 台更严）：`KILLED-ASSIGNED` 要求**指名 node-id 出现在红面里**且
**该发的独有哨兵串出现在它的失败文案里**；只按「整模块 rc≠0」不算杀。
红面同时收 `FAILED` / `ERROR` / `SUBFAILED` 三种行（本模块的判据探针是 `subTest` 形态，
只按 `FAILED` 行归因会把「探针也响了」读成没响——第一版就栽在这里，已在台子 docstring 记下）。

| 发 | 注入 | 期望点名的判据（哨兵） | 判决 | 还原 |
| --- | --- | --- | --- | --- |
| M1 | `response.json` 的 `answer.model` → `phi3:mini-M1`（manifest 声明同批改、闸锚同批改） | `[I3]` 三处同源 | KILLED-ASSIGNED | RESTORED-OK |
| M2 | `ledger-row.json` 的 `row.model` → `phi3:mini-M2` | `[I3]` + `[C-账本model]` | KILLED-ASSIGNED | RESTORED-OK |
| M3 | `trace-attempts.json` 的 `model_route_attempts[1].model` → `phi3:mini-M3` | `[I3]` | KILLED-ASSIGNED | RESTORED-OK |
| M4 | `manifest.plan.primary_model` → `ornith-M4:latest` | `[I4]` 计划主模型 | KILLED-ASSIGNED | RESTORED-OK |
| M5 | `primary-probe.json` 的 `raw_error_body` + `classification.message` 换成非文档化失败 | `[I5]` 不含 §6 那族特征字面 | KILLED-ASSIGNED | RESTORED-OK |
| M6 | 删掉 `trace-attempts.json`（manifest 一字不动） | `[I1] bundle 件缺失：trace-attempts.json` | KILLED-ASSIGNED | RESTORED-OK |
| M7 | 改 `response.json` 内容**但不更** manifest 的 sha256 | `[I2] sha256 不配：response.json` | KILLED-ASSIGNED | RESTORED-OK |
| M8 | 矩阵 P0 行 `GREEN` → `BLOCKED`（bundle 一字不动） | 「证据已成立 ⇒ 只许 GREEN」那一支 | KILLED-ASSIGNED | RESTORED-OK |
| M9 | `manifest.source_run_dir` → `task10/rehearsal/run/20260924-214030` | `[I7] … 指向彩排目录` + provenance sha1 不等 | KILLED-ASSIGNED | RESTORED-OK |

**九发全部 `KILLED-ASSIGNED`、全部 `RESTORED-OK`、计划外附带红 = `[]`（逐发原文见上表引的 bench 文件）。**
M1–M5/M9 的红面里另有 `test_the_evidence_judgment_does_not_degrade`，那是**声明过的哨兵**
（台子里 `COLLATERAL` 清单点名），不是无人认领的连带伤害；M8 只红指名那一枚。

### 4.1 M9 是这一单最要紧的一发（反彩排）

M9 的失败文案原文（`tmp/p0-3b-red-M9.txt` 摘录）：

```
[I7] source_run_dir 指向彩排目录：.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/
     rehearsal/run/20260924-214030——离线彩排件（MockTransport）永远不许撑起 GREEN
[I7] 原始件 sha1 与 bundle 声明不等：trace_jsonl 356826f73d… vs 盘上 d3cfc8b56c…
[I7] 原始件 sha1 与证据自己的 files_sha1 记录值不等：trace_jsonl …
[I7] 原始件 sha1 与 bundle 声明不等：ledger_db b93ce392a1… vs 盘上 d981c1676e…
[I7] 原始件 sha1 与证据自己的 files_sha1 记录值不等：ledger_db …
```

`d3cfc8b56c…` / `d981c1676e…` 就是彩排 run 目录里那两枚**同名、同字节（845 / 16384）、
不同 sha1**的件；被指纹过的真机件是 `356826f73d…` / `b93ce392a1…`。
⇒ 洗成彩排来源的 bundle 会在**两条独立的判据**上响：一条是 manifest 里的路径分量（结构性，
干净签出也能响），一条是按 `source_run_dir` + name 定位后的 sha1 重算（本机在场时响）。
`resolve_raw_provenance()` 里没有 `rglob`、没有按 `st_size` 挑、也没有用 `files_sha1` 的绝对路径
（那枚绝对路径在克隆里会指回**源仓**，读了就等于没测）。

**注**：M9 为了把红因钉在 `[I7]` 而不是钉在外部锚上，同批改了闸里的锚常数（manifest 字节变了，
不重锚则 `[I2]` 抢先响）。M1–M5 同理。还原时三处一起还原，逐发 `sha256 同 + 外部 cmp rc=0 + 基线核对`。

### 4.2 收工后的字节锚（证伪台没有留下任何东西）

```
manifest.json  68749a00e2e2   result.json ca9f7a4e22e6   response.json c0aa6c9f0b14
ledger-row.json a87b7178aab0  trace-attempts.json 1aa8a1dbfb6b  primary-probe.json 9084df5502c6
docs/MODEL_ROUTER_V23_MATRIX.md（证伪前 d21a6eb54b32 → 本步文案改动后 378fe0064063，
  P0 行 `| GREEN |` 那枚子串命中数 = 1，状态字未动）
台子 `--check`（不注入、不跑任何东西）：六枚 RESTORED-OK ×6 + 闸锚在场且唯一=True +
  锚点 M1…M9 全 ANCHOR-OK + 「序列化口径可逆（六枚逐字节相同）：True」
park 目录已删 = True
```

## 5. 逐条映射表：`validate_evidence()` 的判据去了哪一层

**读法**：`§6` = `real_llm_failover_kit.validate_evidence()`（**现树第 567–683 行**）。
下表按该函数的**代码顺序**逐行列出它的全部判定出口，共 **32 行**，行号索引就是这 32 处：
`570 / 584 / 586 / 589 / 591 / 596 / 601(+605) / 608 / 610 / 613 / 617(+623) / 620 / 626 / 628 /
632 / 634 / 636 / 639 / 642 / 646 / 648 / 651 / 654 / 656 / 658 / 661 / 665 / 667 / 671 / 674 /
678 / 682`（括号里的是同一条判据的行内分支：605「缺第 N 枚断言」归第 7 行、
623「provider_calls 里有一枚不是对象」归第 11 行）。
`原现状` 全列都是「必须」——§6 里没有任何一条本来就带条件；
`3B 之后` = 它现在在哪一层被检查、标签是什么；`强度` = 与 3B 之前比是**同 / 增 / 条件化**。
「条件化」只有 **3 格**，落在表里是 **4 行**（①同时管第 5 行与第 32 行，因为它们都是
「绝对路径上那批没入库的原始件」的同一条耦合）。逐格附**为什么这不算放宽**。
计数：同 10 行、增 18 行、条件化 4 行 = 32 行。

| # | §6 判据 | 原现状 | 3B 之后 | 标签 | 强度 |
| --- | --- | --- | --- | --- | --- |
| 1 | 非 dict ⇒ 整包作废 | 必须 | portable 层同形：payload/manifest 不是 dict ⇒ 直接返回 | `[I1]` | 同 |
| 2 | `case_id != CASE_ID` | 必须 | **六枚逐枚查**（原来是 1 枚） | `[C-case_id]` | 增 |
| 3 | `rehearsal` 真值 ⇒ 拒收 | 必须 | raw 层仍**原样**（§6 未改）；portable 层换成正面凭据三条：`provider_transport` 键必须**存在且为 null** + provenance 逐枚 `matches_recorded` + `source_run_dir` 形状/分量 | `[C-传输层]` `[I7]` | 见「条件化」③ |
| 4 | `schema_version != 1` | 必须 | `result.evidence_schema_version` + `manifest.evidence_schema_version`（bundle 自己的版本位） | `[C-schema_version]` | 增 |
| 5 | `completed is not True` | 必须 | 见「条件化」① | `[C-断言条数]`+`[C-断言全过]`+`[C-断言实测值]` | 条件化① |
| 6 | `provider_transport is not None` | 必须 | portable 层**必须**，且要求键**存在**（`读不到就算过`被明确禁掉） | `[C-传输层]` | 增 |
| 7 | 断言条数 != 10 | 必须 | `len(_assertions_of)` + 自报 `assertion_count` 双查 | `[C-断言条数]` | 增 |
| 8 | 逐枚 `name` 对 §10 常量 | 必须 | 逐枚 + `expected_assertion_names` 与 `ASSERTION_NAMES` 全等 | `[C-断言名]` | 增 |
| 9 | 逐枚 `pass is True` | 必须 | 逐枚 + `all_pass` | `[C-断言全过]` | 增 |
| 10 | 逐枚 `observed` 非空 dict | 必须 | 逐枚 | `[C-断言实测值]` | 同 |
| 11 | `len(provider_calls) != 2` | 必须 | `response.json`（+ `summary.calls` 由 §7 导出） | `[C-外呼两次]` | 同 |
| 12 | 模型序 `!= [PRIMARY, FALLBACK]` | 必须 | `[C-模型序]`，且另加 `[I4]` 的 `provider_calls[0].model` 位 | `[C-模型序]` `[I4]` | 增 |
| 13 | 逐枚 `request_bytes` 正整数 | 必须 | `response.provider_calls[]` 逐枚 | `[C-请求字节]` | 同 |
| 14 | 逐枚 `elapsed_ms` 正数 | 必须 | `[C-耗时]` + `summary.elapsed_ms_sum > 0` | `[C-耗时]` | 增 |
| 15 | primary `ok is not False` | 必须 | `[C-primary真失败]`，另加 `[I5]` 的 `attempts[0].result == failed` | `[C-primary真失败]` | 增 |
| 16 | primary `error_kind != model_unavailable` | 必须 | `[C-失败归类]` + 探针侧 `classification.kind` | `[C-失败归类]` `[I5]` | 增 |
| 17 | 错误体 `< 20` 字 | 必须 | `[C-错误体原文]`（同一条地板，同一段文字） | `[C-错误体原文]` | 同 |
| 18 | 错误体不含 `alloc`/`failed to load`/`not found`/`no such model` | 必须 | **同一枚常量** `MODEL_UNAVAILABLE_MARKERS`（§1 唯一出处）在两层各用一次；portable 层还额外对 `primary-probe.json` 的 `raw_error_body` + `classification.message` 用一遍 | `[C-错误体原文]` `[I5]` | 增 |
| 19 | fallback `ok is not True` | 必须 | `response.provider_calls[1].ok` | `[C-fallback成功]` | 同 |
| 20 | `ledger.rows != 1` | 必须 | `ledger_source.rows`（第 14 枚行号原样语义） | `[C-账本一行]` | 同 |
| 21 | `canary_hits` 非空 ⇒ 红 | 必须 | `[C-canary零命中]` + `forbidden_column_proof.canary_hit_count == len(hits)` | `[C-canary零命中]` | 增 |
| 22 | `canary_needles` 必含 `PROMPT_CANARY` | 必须 | 同一枚 kit 常量、同一个字段位 | `[C-canary针]` | 同 |
| 23 | `row.fallback_index != 1` | 必须 | `[C-fallback_index]` + trace 侧 `model_route_selected_index == 1` | `[C-fallback_index]` `[I3]` | 增 |
| 24 | `row.success` 不为真 | 必须 | `ledger-row.json` 的 `row.success` | `[C-账本success]` | 同 |
| 25 | `row.model != FALLBACK_MODEL` | 必须 | `[C-账本model]`，并升格进 `[I3]` 的四处同源集合 | `[C-账本model]` `[I3]` | 增 |
| 26 | 禁存列 `prompt/context/messages/reasoning` | 必须 | `[C-禁存列]`：`row` 逐列 + `columns_checked` 与 §6 清单同形 + `columns_present_in_row` 必空 | `[C-禁存列]` | 增 |
| 27 | `trace.model_route_attempts` 不是两枚 | 必须 | `trace-attempts.json` 的同名数组 | `[C-两枚attempt]` | 同 |
| 28 | `trace.trace_id != row.trace_id` | 必须 | 升格为四处（manifest/trace-attempts/ledger-row/ledger-row.row）+ pointers 三处 + 第 6 枚断言 observed 三处 | `[I6]` `[C-trace_id]` | 增 |
| 29 | `answer.text` 短于下限 | 必须 | `[C-答案长度]`，**另加** CJK 下限（§6 原来没这一条） | `[C-答案长度]` `[C-答案中文]` | 增 |
| 30 | `timings_ms.total` 缺失/非正 | 必须 | 见「条件化」②（portable 侧用 `elapsed_ms_sum` 与逐枚 `elapsed_ms` 承担同一枚事实） | `[C-耗时]` | 条件化② |
| 31 | `files_sha1` 为空 | 必须 | raw 层原样；portable 层由 `portable_files` 五枚 + `raw_provenance` 四枚承担 | `[I2]` `[I7]` | 增 |
| 32 | 逐枚重算 `files_sha1`（**绝对路径**） | 必须 | 见「条件化」①的同一格：raw 在场 ⇒ §6 原样重算；raw 不在场 ⇒ 由「仓根 + `source_run_dir` + name」重算同一批 sha1，加上 manifest 声明值的 `matches_recorded`/`present` 与载荷五枚的 sha256 | `[I2]` `[I7]` | 条件化① |

**另有两条只存在于新层、§6 从来没有的判据**：`[I2]` 的**外部锚**（manifest 自己的 sha256
对闸文件常数）与 `[X]`（bundle ↔ 原始证据 JSON 的逐字段面对面核对，只在 raw JSON 在场时跑）。
它们只加不减。

### 5.1 「条件化」三条为什么不算放宽（评审要逐条问的就是这里）

① **`completed is True` 与「逐枚重算绝对路径 sha1」**（§6 第 5、32 行）→ raw 不在场时不再检查。
*为什么不是放宽*：这两条检查的对象**根本没进交付面**（`.gitignore:25` 整目录挡掉），
在干净签出里它们的真值不是「不成立」而是**不可判**；R25 已经把「不可判」当成「红」来处理，
于是这枚闸在任何 CI 形态下恒红、任何一次评审都无法在 CI 上复核它——**一枚永远红的判据的
实际威慑力是零**，这是 R26 ③ 换载体的原始理由。替代强度：`completed` 所表达的那件事
（「这次运行跑到了收尾」）在 portable 层由「10 枚断言**全过** + 逐枚带实测值 +
第 10 枚 `api_face_is_200` 的 observed 里 `status_code` 存在」承担；
sha1 那件事由「五枚载荷件 sha256 逐枚重算 + manifest 被闸里的外部锚钉 + 四枚 provenance
逐枚 `matches_recorded` 为真」承担。且**本机（raw 在场）§6 照旧全量跑**——读数 2 打印的
`raw_state = full` 就是这件事的证据，不是叙述。

② **`timings_ms.total > 0`**（§6 第 30 行）→ portable 层没有这枚字段（3A 的投影表里没带它）。
*为什么不是放宽*：`[C-耗时]` 在 portable 层检查的是**同一批数字的更细粒度**——两枚外呼各自的
`elapsed_ms` 必须为正 + `summary.elapsed_ms_sum` 必须为正（后者是前两者的和，由 §7 导出时
机械算出）。总耗时能对上到毫秒级 ⇒ 比 §6 那条只看 `timings_ms` 的总位更严。

③ **`rehearsal` 真值判定**（§6 第 3 行）→ §6 原样保留；portable 层用三条正面凭据替代「读不到就算过」。
*为什么不是放宽*：`rehearsal` 是原始件自己的一枚布尔位，本身可以被删掉来绕过；portable 层的
`provider_transport` 必须**键存在且值为 null**（缺键也红），加上 provenance 的 `matches_recorded`
与 `source_run_dir` 的形状/分量检查，三条都落在**被 hash 钉住的文本**上。M9 那一发（把 bundle
的来源指向 `task10/rehearsal/run/20260924-214030/`）就是打这一格的，见读数 3。

## 6. 七条 interlock 的逐条落点

| 条 | 简报要求 | 代码落点（`real_llm_failover_kit` §8） | 本机实测（读数 2 那次 `portable 层：0 条问题` 就是这七条全过） |
| --- | --- | --- | --- |
| 1 | 五枚 portable 件全部存在，`portable_files[].path` 按**仓根**解析、不得按 cwd | `portable_bundle_paths()` + `read_portable_bundle()`（锚在 `REPO_ROOT ← __file__`）；标签 `[I1]`；另加一枚「目录里有契约之外的件 ⇒ 红」 | 读数 1 的克隆里 bundle 目录是 `%TEMP%` 下的另一条绝对路径，仍然过 ⇒ 锚没锚在 cwd 上 |
| 2 | 每条 sha256 + bytes 当场重算；**manifest 自己也要被校验**；外部锚二者取一并说明 | `[I2]`：逐枚 `sha256_of`/`bytes` 对照 + `portable_files[].path` 集合必须恰好是五枚 + 路径**解析位**必须等于实读位 + `manifest_sha256_pin` 对照；取的是**钉进闸文件常数**（`PORTABLE_MANIFEST_SHA256`），理由与代价写在闸文件 §1 的注释里 | 闸钉的 `68749a00e2e2…` == 盘上 manifest 的 sha256（`--check` 逐枚打印）；M7 专打「改件不更 hash」 |
| 3 | `response.model_used == ledger.row.model == 成功那枚 trace attempt.model == phi3:mini` | `[I3]` 把四处并集**恰好等于** `{FALLBACK_MODEL}`：`answer.model` / `row.model` / `model_route_attempts[selected].model` / `chain.response_model`，另要求成功的 attempt **恰好只有第 1 枚**、`model_route_selected_index == 1`、`model_route_stage == fallback`、第 4 枚断言的 `observed.model_field` | M1 / M2 / M3 三发分别杀在这里（哨兵 `phi3:mini-M1/M2/M3`） |
| 4 | 计划主模型 == `ornith-1.5:9b-text`，复用 `kit.PRIMARY_MODEL` 不复抄字面量 | `[I4]`：`manifest.plan.primary_model` / `primary_entry` / `fallback_models` + `attempts[0].model` + `provider_calls[0].model` + 第 7 枚断言 `observed.primary.model`，**全部引用常量**（`PRIMARY_MODEL` / `PRIMARY_ENTRY_ID` / `FALLBACK_MODEL`），§8 与闸文件里没有一处模型名字面量 | M4 杀在这里（`ornith-M4:latest`） |
| 5 | `primary-probe.json` 命中的是文档化的 retryable / model-unavailable 失败族，§6 的 `alloc` / `failed to load` / `model … not found` 原文要求**一字不松** | 字面清单由 §6 的 inline 元组**提到** §1 `MODEL_UNAVAILABLE_MARKERS`，两层同一枚常量（这是「一字不松」的机器形式——想松只能改一处、两处一起响）；`[I5]` 再钉 `classification.kind` / `status_code == 500` / `probe_result == load_failed` / `probe.model == PRIMARY_MODEL` / `answer_content is None` | M5 杀在这里（换成 `connection reset by peer`） |
| 6 | `trace_id` 在 manifest / trace-attempts / ledger-row 三处逐字符一致；顶层 `trace_id` 键在原始件里不存在，别再读它 | `[I6]` 读的是 bundle 自己的四处（manifest / trace-attempts / ledger-row 顶层 / `ledger-row.row`）+ `trace_id_source.pointers` 三处 + 第 6 枚断言 observed 三处，要求**集合恰好一枚**；§8 从不读原始件的顶层 `trace_id` | 闸内探针「trace_id 三处里改一处」红在 `[I6]`（真值 `p0-failover-6146ff1417d7` 不写死进代码——写死就等于第二份真相） |
| 7 | 矩阵 P0 行状态 == 由 1–6 推出来的那个值，沿用「写死合法取值」，不读 env、不读文档自述 | 取值仍写死在闸文件（`P0_STATUS_WITHOUT_EVIDENCE` / `P0_STATUS_WITH_EVIDENCE`，未动），`test_p0_row_status_matches_the_evidence` 把 `verdict["problems"]` 折成这一枚比较 | M8（矩阵 `GREEN`→`BLOCKED` 而 bundle 全绿）红在「证据已经成立 ⇒ 只许 GREEN」那一支 |

## 7. §10 那十枚断言在 portable 层各自的着落

`result.json` 的 `assertions[]` 是十枚断言的本体（逐枚 `id/name/pass/observed/elapsed_ms`），
portable 层除了「条数 / 名字 / pass / observed 非空」这四枚通用地板（表 §5 第 7–10 行）之外，
还**逐枚**把可重算的量再钉一遍：

| 断言 | portable 层的钉法 | 标签 |
| --- | --- | --- |
| 1 `primary_really_called` | `attempts[0].result == failed` + `provider_calls[0].model == PRIMARY_MODEL` | `[I4]` `[C-primary真失败]` |
| 2 `failure_classified_model_unavailable` | `error_kind == model_unavailable` + 错误体 ≥20 字 + 命中 `MODEL_UNAVAILABLE_MARKERS` + 探针侧同一族字面 | `[C-失败归类]` `[C-错误体原文]` `[I5]` |
| 3 `fallback_called` | `provider_calls[1].ok is True` + `len(calls) == 2` | `[C-fallback成功]` `[C-外呼两次]` |
| 4 `phi3_valid_chinese_answer` | `answer.text` 长度地板 **+ 新增 CJK 地板** + `answer.model` / 第 4 枚 `observed.model_field` 都必须是 `FALLBACK_MODEL` | `[C-答案长度]` `[C-答案中文]` `[I3]` |
| 5 `fallback_index_is_one` | `row.fallback_index == 1` + `model_route_selected_index == 1` | `[C-fallback_index]` `[I3]` |
| 6 `trace_id_consistent` | 四处 + pointers 三处 + 第 6 枚 observed 三处，集合恰好一枚 | `[I6]` |
| 7 `model_route_two_attempts` | `len(attempts) == 2` + `observed.primary.model == PRIMARY_MODEL` | `[C-两枚attempt]` `[I4]` |
| 8 `usage_row_landed` | `ledger_source.rows == 1` + `row.success` 为真 | `[C-账本一行]` `[C-账本success]` |
| 9 `zero_prompt_stored` | `canary_hits` 空 + `canary_hit_count` 与实际条数相等 + `canary_needles` 含 `PROMPT_CANARY` + 四枚禁存列既查 `row` 又查 `columns_present_in_row` + `columns_checked` 与 §6 那份同形 | `[C-canary零命中]` `[C-canary针]` `[C-禁存列]` |
| 10 `api_face_is_200` | 除「pass=true + observed 非空」外，**新增** `observed.status_code == 200` 的可重算量（原来 §6 只从 `timings_ms`/JSON 侧面看它） | `[C-api面200]` |

## 8. 读数 4：闸模块整模块绿 + SEC-A 扫描门 46 passed 且那枚文件 `git diff` 为空

**全部在最后一次代码改动之后复跑**（终态读数块，原文
`evidence/p0-3b-terminal.txt`；下面每一行都是那一轮打印的）：

```
$ python -m pytest tests/test_real_llm_failover_gate.py tests/test_llm_egress_guard.py tests/test_ci_gate_contract.py -q
66 passed, 118 subtests passed in 51.23s          ← 闸模块 15 / egress 35 / B0 门册 16
$ python -m pytest tests/test_secret_hygiene_contract.py -q
46 passed in 43.61s                                ← SEC-A 扫描门整模块
$ git diff --exit-code -- backend/tests/test_secret_hygiene_contract.py
SEC-A GIT-DIFF-EMPTY rc=0                          ← 零新增豁免行是「这枚文件没被碰过」的字节证明
$ grep -n "EXPECTED_COLLECTED = " backend/tests/test_ci_gate_contract.py
104:EXPECTED_COLLECTED = 1335
```

SEC-A 扫描面与命中数（用扫描门**自己的** face 函数取数，不另起口径）：

```
扫描面文件数 = 407 | 命中文件 = 16 | 命中处数 = 31      ← 与 3A 的读数一字未动
docs/evidence/…/manifest.json      命中处数 = 0
docs/MODEL_ROUTER_V23_MATRIX.md    命中处数 = 0        ← 本轮改过文案，仍在面上、命中 0
backend/tests/real_llm_failover_kit.py      命中处数 = 0
backend/tests/test_real_llm_failover_gate.py 命中处数 = 0
```

闸模块的 `node-id` 枚数**没变**（仍 15 枚，`ast` 现算：顶层 `def test_` 0 枚 + 类内 15 枚），
`subtests` 从 11 → **26**（+15 = portable 层的 15 发内存探针，见 §10 的口径说明）。
矩阵文案改动之后 `MatrixDocumentClosureTests` 所在的 `test_llm_egress_guard.py` 与闸模块一起复跑，
无新增红 ⇒ 本轮加的文案**没有**打破「文档里的 node-id 必须真存在 / 类必须挂表」那两枚双向钉。

## 9. 读数 5：收集数 1335（没动那枚常数）与 B0 的 16 枚门

```
$ python -m pytest --collect-only -q -p no:cacheprovider          （cwd=E:\xiangmu\rag\backend）
1335 tests collected in 49.09s
$ python -m pytest tests/test_ci_gate_contract.py -q
16 passed in 37.08s                                                ← B0 的门册仍 16 绿
```

`EXPECTED_COLLECTED` 的**现值就是 1335**（`test_ci_gate_contract.py:104`），本轮没改它、
也没「凑」它：本轮**没有新增 node-id**（`def test_` 逐文件现算：闸文件 15、B0 门册 16、
SEC-A 41 枚方法/46 枚含参数化子例），所以「你若新增测试就停下报告」那条线**未触发**。
`test_ci_gate_contract.py` 的 sha256 终值 `893d59b4d74b` 与台账 R20/R21 记的 `699b0dfa8d9e` 不同，
**不是本轮动的**：把 `EXPECTED_COLLECTED = 1335` 按回 `1332` 后现算 sha256 = `699b0dfa8d9e`
逐字符复现台账值 ⇒ 那枚差异是先前回合把常数从 1332 重锚到 1335 造成的，本轮对该文件零改动。

## 10. 读数 6：全量套件两 cwd（逐格标 cwd 与 `.env` 状态）

```
格 A  cwd = E:\xiangmu\rag\backend    命令 python -m pytest tests -q        .env = backend/.env 在场（1561 B / sha256 4d7f974107dd），未挪未删
      1335 passed, 36 warnings, 1151 subtests passed in 170.69s  rc=0     ^FAILED|^ERROR = 0 行
格 B  cwd = E:\xiangmu\rag             命令 python -m pytest backend/tests -q  .env = 同上，在场
      1335 passed, 36 warnings, 1151 subtests passed in 179.56s  rc=0     ^FAILED|^ERROR = 0 行
两格末行**逐位相同**（1335 / 36 / 1151 / rc=0），`.env` 前后 sha256 一致 = 4d7f974107dd（1561 B）。
证据：.superpowers/sdd/ENTERPRISE_B0_PLAN/evidence/p0-3b-full-{backend,root}-withenv.txt
      + p0-3b-env-state.txt
```

**subtest 计数从 1133 → 1151 的账**：本轮把闸模块的 `subTest` 从 11 加到 26（+15 枚 portable 层探针）。
`subtests` 不是 node-id，**没有任何判据钉它的总数**（`EXPECTED_COLLECTED` 钉的是收集到的
node-id 枚数 = 1335，本轮没动也没「凑」；`grep EXPECTED_COLLECTED backend/tests/test_ci_gate_contract.py`
= 1335，`git diff` 那枚文件为空）。台账里 Task 3/4/5 记的 `1133 subtests` 因此**不再是本轮可比量**，
这句写在这里免得下一个人把差值当成回归。

**本轮没有新增测试**：`def test_` 枚数不变（闸文件 15 枚、B0 16 枚），所以「你若新增测试就停下报告」
那一条**未触发**。

## 11. 已知边界与关切（评审先看这一节）

① **外部锚是字节级锚 ⇒ 载体必须以 LF 签出**（本轮最硬的一条边界，实测）。
锚钉的是 manifest 的 sha256，`[I2]` 逐枚钉的是五枚载荷件的 sha256。
本机实测：`git clone` 出来的**跟踪文本件**（`* text=auto`）在这台 Windows 上是
**带 CRLF** 落地的——同一棵克隆里 `docs/MODEL_ROUTER_V23_MATRIX.md` 是 `25424 B / CR 163`，
而源仓工作树是 `26505 B / CR 0`（`-c core.autocrlf=false` 也照样转，因为 `text=auto`
的签出 EOL 由 `core.eol`/平台决定，不只是 autocrlf）。
⇒ **含义**：CI（ubuntu-latest，四条 job 全部实测 `runs-on: ubuntu-latest`）签出即 LF ⇒ 锚配 ⇒
读数 1 成立；而在 Windows 上 `git checkout` 出来的 `docs/evidence/*.json` 会变成 CRLF ⇒
`[I2]` 的 sha256 与「含 CR」两枚一起**响亮地红**。
我没有为了让这一格不红而去做「比较前剥 `\r`」那种规范化——那等于把 hash 判据从字节层降级到
文本层，正是 R26 不许的第二条出路的近亲。出路有两条、都在本步的禁改面之外，交控制器裁：
(a) `.gitattributes` 给这六枚加 `docs/evidence/** text eol=lf`（正解，但 `.gitattributes` 是
B0 已封面的禁改项）；(b) Windows 侧把 `core.eol` 设成 `lf`。
本轮能做的已经做了：判据的红话里**写明了这一条成因与自救方向**（`[I2] … 含 CR …若这是
git checkout 干的…`），并且用一次纯内存注入证明这条判据不是摆设（§10 的自证块）。

② **`absent` 分支本轮没有真实形态可取证**。原始证据 JSON 已被跟踪（`git ls-files` 实测），
所以干净签出必然落在 `json-only`。`absent`（JSON 也不在场）只在代码里存在一支，
没有读数支持——按 R26 的语义它应该「由 portable 层单独决定」，
但请把它记为**未观测**而不是「已验证」。

③ **载体的入库依赖**。`docs/evidence/` 在源仓里至今是 `?? docs/evidence/`（未跟踪）：
读数 1 是把六枚按 `cmp` 逐字节相同的方式覆进克隆取的，等价于「控制器把这一层 `git add` 之后」
的 CI 形态。**在它入库之前，远端这一枚仍会红在 `[I1]`**（红的文案直接点名载体缺失，
不会再被读成「P0 没跑过」）。本轮无提交权限，未代控制器动。

④ **锚常数与真机重跑的耦合**：重跑一次真机 ⇒ manifest 换字节 ⇒ 必须同批改 `PORTABLE_MANIFEST_SHA256`。
漏更 ⇒ `[I2]` 响亮红（不是静默过）。runner 的 `[4/4]` 目前打印 sha256 但**不**自动改闸文件——
那是刻意的（改判据文件必须是人做的动作）。若将来要自动化，请连锚一起设计，别只写一半。

⑤ **`release_image` 仍是 null**（3A 的诚实缺口，本轮**没有**为消红补它）：§8 不读这枚字段，
只要求 manifest 带 `absent_source_fields` 诚实清单（缺清单 ⇒ `[I7]` 红）。
所以「本 case 是宿主 Ollama、无镜像」这件事在 bundle 里是有记录的，但**不是**一条 interlock。
归采集器侧的后续（3A findings 1 已交回）。

⑥ **SEC-A 扫描面**：面 407 文件 / 命中 16 文件 / 31 处，与 3A 的读数一字未动，
**零新增豁免行**；本轮改过的 `real_llm_failover_kit.py` / `test_real_llm_failover_gate.py` /
`docs/MODEL_ROUTER_V23_MATRIX.md` 三枚在面上且**命中处数 = 0**（逐枚点名见 §10）。
注意 `docs/evidence/**` 目前未跟踪 ⇒ 还没进 `--cached` 面，入库后会进 untracked→tracked 面，
命中仍应为 0（3A 已量过六枚各 0 处）。

## 12. 独立评审必须重点看什么（按危险度排序）

1. **§5 那张表的「条件化」三格是不是真窄**。只该有 4 行是条件化，且全部落在
   「绝对路径上那批没入库的原始件」这一族耦合上。请拿 `validate_evidence()`（§6，567–683 行）
   逐行对着读，任何一条你认为是「从必须变成了静默放过」的，就是本轮的缺陷——
   尤其请注意：`[C-*]` 标签的那 28 行**在干净签出里也一定跑**（读数 1 的 `json-only` 分支
   里 `portable 层：0 条问题` 就是这 28 行全跑过的读数）。
2. **`[I2]` 外部锚的强度边界**。锚把「manifest 的字节」钉进闸文件，**但锚本身就在被评审的这枚
   diff 里**：一个同时改 bundle + manifest + 闸文件常数的人可以把 `[I2]` 洗平。洗不平的是
   `[I3]`–`[I7]` 的语义判据与 `[X]` 面对面核对（后者要求 bundle 与**已跟踪的原始证据 JSON**
   逐字段相等），以及真机重跑的不可再生性。请裁：这枚残余信任根（同一批 diff 里的人）够不够，
   还是要不该轮就把锚移去远端 CI 变量 / 双人签。我的判断是「本轮够、B1 该升级」，理由在闸文件
   常数上方注释里，但**这是判断题不是事实题**，请独立复核。
3. **`raw_state` 的三分是不是把『不可判』偷偷变成了『通过』**。请按读数 1（`json-only` 绿）
   与读数 2（`full` 绿）+ §2.1 的反证（载体缺席 ⇒ 响亮地红）三格对着看。要点：
   `full` 分支里 §6 一字未改地全跑；`json-only` 分支里唯一被跳过的判据就是 §5 表中标了
   条件化的那 4 行；`absent` 分支本轮**没有**任何真实形态落在上面（原始证据 JSON 已被跟踪），
   所以我没能为它取证——这是**已知的未观测格**，请记为边界而不是通过。
4. **M9 那一发的还原是否可信**。它同时改了 `docs/evidence/**manifest.json**` 与
   **闸文件的锚常数**两处（§4.1 末尾说明为什么必须两处一起改），`finally` 两处都按原字节写回，
   判据是「两处 sha256 相同 + 两处外部 `cmp` rc=0 + 六枚基线核对」。请复核：
   台子里 `reanchor_ops()` 是**故意**为了不让 `[I2]` 抢先响而写的——它有没有可能顺手把
   别的判据也喂平了（我给的答复：`[I2]` 的「路径集合」「实读位置同源」「含 CR」三小关
   都还在响，只有 sha256 对照被喂平，而那一关由 M7 单独打）。
5. **`resolve_raw_provenance()` 的两枚「常量路径定位」是不是变相按名字找**。
   `primary_probe → kit.PROBE_FILE`、`acceptance_module → kit.ACCEPTANCE_FILE`：
   这两枚是 kit 里**唯一的出处**（仓根锚定），不是搜索；但简报的规则写的是
   「`source_run_dir` + sha1 双条件」。请裁这种写法合不合规。我的辩护：这两枚件本来就
   不在 run 目录里（一枚在 `task10/`、一枚是跟踪的交付件），`source_run_dir` 对它们
   在字面上就不适用；而**sha1 逐枚重算那一半条件对四枚全部适用**，且彩排件正因为这一半被抓住。
6. **本轮新增的判据有没有把自己的门搞脏**：`[I1]` 的「目录里不许有契约之外的件」与
   「不许出现绝对路径」两条，是把 3A 的**读数**升格成了**判据**。将来 runner 若往 bundle 目录
   多写一枚文件（例如 `checksums.txt`）就会当场红——那是要的（六枚文件名就是契约），
   但请确认这不是对某个未声明约束的偷偷收紧。

## 13. 我在哪里差点走捷径（自我交底，不许写「应该没问题」）

- **差一点把锚落进 markdown**。简报给的两枚候选里，「落进 `docs/ENTERPRISE_B0_*`/规格」看起来
  更省事（改文档不用碰代码、也不会让真机重跑必须同步改代码常数）。我选了钉进闸文件，
  因为 R26 第 ③ 条明确把「验收 markdown 说 GREEN 就算 GREEN」列为不许走的出路之一，
  而锚就是一种自述。省事的那条我差一点为了「真机重跑不用碰代码」去走——那是把信任根
  交给文档，正是要防的东西。**代价我留下了**：真机重跑必须同批改这枚常数，漏更即响亮红。
- **差一点让 M1–M5、M9 不重锚**。不重锚的话这五发全都会红在 `[I2]` 外部锚上，
  台子照样打印 `KILLED`，而 `[I3]`–`[I7]` 到底有没有牙**永远读不出来**。
  我第一版就是这么写的；发现「九发全红、红因全是同一枚」时才回头补 `reanchor_ops()`。
  如果我没回头看红因文案、只看 rc 与 node-id，这一格就是**假杀**。
- **归因表第一版是坏的**。`re.match(r"^(?:FAILED|ERROR) tests/\S+::(\S+)")` 只取到方法名，
  与含类名前缀的 `ASSIGNED` 永远不相等 ⇒ 九发全被记成 `KILLED-INCIDENTAL`。
  第一次台账（9/9 INCIDENTAL）我**没有当成功报**，而是回去查了 node-id 的形状；
  同时发现 `subTest` 形态的红出的是 `SUBFAILED` 行，只按 `FAILED` 行归因会漏读探针自己响。
  这两处都写进了台子的注释（别再改回去）。
- **差一点把 raw 层的绝对路径重算也搬进 portable 层**。那最省事（「raw 不在就跳过这一条」
  一句话就能写完），但 §6 的 `files_sha1` 是**绝对路径**——照搬进 portable 层就等于
  让干净签出继续红，或者更糟：让它在**同一台机器上的另一棵树**里读到源仓的件而假绿
  （我的克隆第一次跑出「raw 问题 0 条」时我怀疑过，查出来就是这个形状）。
  最后选了「仓根 + `source_run_dir` + name」重定位，绝对路径那枚只在 `full` 分支保留。
- **`_portable_bytes` 那枚 CR 判据曾经是一枚死判据**。第一版读盘时没把字节留在 payload 里，
  `_portable_bytes` 对未改过的件返回 `b""` ⇒ 「含 CR」永不为真 ⇒ 我写了一条**自己不会响**的
  判据却把它报成「已加」。现在 `read_portable_bundle()` 自己记 `has_cr`，
  并用一次纯内存注入验证它会响（原文见 `p0-3b-crlf-selftest.txt`，盘上六枚 `has_cr` 全 False、
  注入 `CRLF` 后 `[I2] … 含 CR` 当场点名）。**这类「写了但不响的判据」是本轮我自己制造的风险**，
  请评审按同样口径抽查其它新增判据是否各有至少一发「改它 ⇒ 它响」。
- **没有为了消红动过矩阵状态字**：`grep -c 'trace 1 行） | GREEN |' docs/MODEL_ROUTER_V23_MATRIX.md` = 1，
  `git diff --numstat` = **11/0**（只加不删），加的那 11 行是 §4.5 ③ 的分层文案。
  矩阵文案与判据的先后是「判据先落地、文案跟上」，不是反过来。
- **取证瑕疵一条**：读数 1 的负向对照（挪走载体）我第一版是在克隆根目录而不是
  `克隆/backend` 里跑 pytest ⇒ 打印出 `no tests ran`，还原证明的「复跑 15 passed」那一句当时
  并没有真绿。我当场抓出来并补跑（`15 passed, 26 subtests passed`），
  两遍都在 `evidence/p0-3b-clean-clone-*.txt` 里留了原文。

---

## 3B 修复轮 1

**触发** = 独立评审的裁定（台账 **R27**）：spec 合规 **❌ 部分**，四条点名条款不成立
（H1 / H2 / M1 / M2），另有两条一行的 rigor 项（L6 / L1）与一条报告不实句（L5）。
本轮**全部是加强**，没有一条判据被放宽、删除、skip 或 xfail；
`EXPECTED_COLLECTED` 仍是 **1335**（本轮 `def test_` 枚数一字未动，见 §F6）。
全文按「改了什么 → 实测读数 → 与评审复现的对照」三件事写，读数原文都在
`.superpowers/sdd/ENTERPRISE_B0_PLAN/evidence/p0-3bf1-*.txt`。

### F0. 本轮动的文件与仍然不碰的东西

| 文件 | 本轮改动 |
| --- | --- |
| `backend/tests/real_llm_failover_kit.py` | 1947 → **2289** 行：H1/H2 的 `[T-*]` 层与 `source_run_flags` 载体、M1 的 git-blob 腿与 `json-only` 调用、M2 的指针判据、L6 的 `green_permission()` 委托、模块头分层说明 |
| `backend/tests/test_real_llm_failover_gate.py` | 832 → **912** 行：外部锚**重钉** + 重钉理由注释、分层文案、`_verdict_branch_line()` 打印 `[T-*]` 计数与 blob 腿三值、portable 层退化探针 15 → **23 发**（同一枚 node-id 的 `subTest`，不新增用例） |
| `docs/evidence/model-router-v23/real-llm-failover-001/` | 经 `kit.write_portable_bundle()` **重导**：`response.json` 与 `manifest.json` 换字节，其余四枚逐字节未变 |
| `.superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/p0_3b_mutations.py` | 359 → **511** 行：L1 needle 全发接通 + `--anchor-selftest`、L4 `restamp_ops` 补 `bytes`、N1–N5 五发负面枪、`--root` 支持在干净签出上取证、子进程编码钉成 UTF-8（仪表修复，理由见 §F4） |
| `.superpowers/scripts/run_p0_failover_acceptance.sh` | 打印 `raw_state` / 逐层问题计数 / 锚值（runner 与闸同口径之后，第一现场要能看见走了哪条腿） |

**仍然不碰**：`backend/app/**`（含 `identity/*`）、`.gitattributes`、`ci.yml`、
`test_ci_gate_contract.py`（含 `EXPECTED_COLLECTED`）、两枚 tag、
`test_real_llm_failover_acceptance.py`（它就是本轮 blob 腿的**对象**，动它等于换掉判据锚）、
矩阵 P0 行的**状态字**。SEC-A 扫描文件 `git diff` 为空、零新增豁免行（§F6）。
**本轮没有任何 git 写操作**：新用的两条 git 命令 `git hash-object`（不带 `-w`，只算名字、
不落对象库）与 `git rev-parse HEAD:<path>` 都是只读的；`git status` 与 §F7 的残留核对可查。

### F1. H1 — `rehearsal` / `completed` 在分层时静默丢失

评审的复现（干净签出副本）：往**已跟踪的** `real-llm-failover-001.json` 注入
`"rehearsal": true` ⇒ `15 passed`；改成 `"completed": false` ⇒ `15 passed`；
而 `assertions[0].pass=false` 会红 ⇒ 不是比较器坏了，是这两枚字段没人比。
简报《反彩排件》那一条写的是「原始 JSON 的 `rehearsal` 真值判定**必须保留**」，
而 3B 把它连带 §6 一起条件化成了「四枚运行态本体都在场才跑」——这是未申报的放宽。

**改法（三层一起，不是补一处）**：

1. `tracked_evidence_truth_problems()`（kit:2112，标签 `[T-彩排]` / `[T-收尾]` / `[T-传输层]`）
   在 `p0_evidence_verdict()` 里**无条件调用**——只要读得到那枚已跟踪的 JSON 就判，
   读不到（`absent`）也**自己响**一条 `[T-载体]`，不许把「整件不在」当成「判据通过」。
2. 载体侧：`_source_run_flags(evidence)`（kit:1104，**算式唯一出处**）把五枚布尔位
   机械投影进 `manifest.source_run_flags`；`validate_portable_bundle` 的 `[I7]` 逐枚要求
   `completed_is_true is True` / `rehearsal_truthy` 为假 / 键名集合齐（kit:1909–1928）。
   ⇒ 这一半落在**被闸里外部锚钉住的字节**上，portable 层单独就能判。
3. 面对面：`cross_check_bundle_and_raw()` 用同一枚 `_source_run_flags()` 现读原始件，
   五枚布尔位逐枚 `compare()`（kit:2185 起）⇒ 载体与真源不同源时 `[X]` 自己响。

`validate_evidence()` §6 那两行（`evidence.get("rehearsal")` / `completed is not True`）
**一字未动**——本轮是「多加一层」，不是「搬走一层」。§6 在 `full` 分支里照旧全量跑，
所以 §5 那张表里第 3、5 行从「条件化」升回**必须**，映射表的修订见 §F2。

### F2. H2 — 唯一的非彩排正面凭据在**源端**退化成「读不到就算过」

评审复现：把 `provider_transport` 这枚键从已跟踪的 JSON 里**删掉**，`response.json` 留着
`null` ⇒ `15 passed`。根因两处都用 `evidence.get("provider_transport")`（原 :1032 / :1880），
「键不存在」与「键为 null」在 `.get()` 眼里长得一样；bundle 侧那枚成员判定（:1594–1599）
只看 bundle，管不到源端。真件确实带着 `"provider_transport": null`（本轮实测：键在场、值 null）。

**改法**：全部改成**成员判定**（`"provider_transport" in evidence`），一个 `.get()` 都不留：
- `_bundle_response()` 多带一枚 `provider_transport_present`（kit:1167）——导出当刻
  原始件里到底有没有这枚键，从此是 bundle 里可重算的事实；
- `[C-传输层]` 加一条「`provider_transport_present` 不为 true ⇒ 红」（kit:1750）；
- `[T-传输层]`（§F1 那一层）要求**键在场**且**值为 null**，两件事分别给文案；
- `manifest.source_run_flags.provider_transport_key_present` / `_is_null` 进 `[I7]`；
- `[X]` 同时比 `provider_transport` 与 `provider_transport_present`。

**证伪**：新增 bench 枪 **N3**（删键）——本机与干净签出两处都 `KILLED-ASSIGNED`，
红在 `[T-传输层]`，见 §F4。

### F3. M1 — raw 层的全有或全无，与被跟踪那枚件的 **git blob 腿**（控制器裁定的形状）

评审复现：篡改 `agent_traces.jsonl` **并且**删掉 `conversations.db` ⇒ `15 passed` 静默；
同样那枚篡改在四枚都在场时是红的。根因：`p0_evidence_verdict()` 原来写的是
`if evidence is not None and all_present: … elif evidence is not None: raw_state="json-only"`，
`json-only` 那一支**一行判据都不跑**，尽管 `raw_layer_problems()` 自己已经会跳过不在场的条目。

**改法（两件事一起做，因为第一件会给第二件开门）**：

1. `json-only` 分支也调 `raw_layer_problems(resolved)`（kit:2232 起）。
   ⇒ 这枚闸第一次在 CI 形态下有**真重算腿**：`acceptance_module` 是四枚 raw 目标里唯一
   **被 git 跟踪**的一枚，它在任何签出里都在场，过去却被「另一枚缺席」连坐成不判。
2. 对那一枚按控制器裁定改判 **git blob 身份**，不再判工作树字节：
   - 导出侧：`_raw_provenance()` 给 `_GIT_BLOB_ROLES = ("acceptance_module",)` 这一枚多记
     `repo_path`（仓相对 posix，由 `ACCEPTANCE_FILE ← __file__` 推出，不是字面量）
     与 `git_blob`（= `git hash-object <工作树文件>`，kit:1030）；
   - `[I7]` 载体侧：`git_blob` 必须是 40 位十六进制、`repo_path` 必须等于
     `_ACCEPTANCE_REPO_PATH`（kit:1876 起）——写成绝对路径就当场红；
   - 判定侧：`blob_leg_problems()`（kit:2056）比三枚——记录值 ↔ `git rev-parse HEAD:<repo_path>`
     ↔ 当下工作树 `git hash-object`。三条任何一条不成立都是 `[I7-blob]` 响亮地红，
     「读不到 HEAD blob」也按红处理（不可判 ≠ 通过）。
   - 其余三枚（`.db` / `.jsonl` / 现场 probe）是 gitignored 的运行态件，**不在 HEAD 里**，
     无 blob 可比 ⇒ 「sha1 + 只在在场时校验」的语义**一字未动**。

**为什么要换成 blob**（裁定理由的复述 + 本轮实测）：`sha1_of()` 钉的是**工作树字节**，
而工作树字节是签出的函数——`.gitattributes` 写 `* text=auto`、本机 `core.autocrlf=true`，
`core.eol` 未设 ⇒ 签出走 native（Windows=CRLF）。同一份真话会在一台机器上绿、另一台上红。
**blob 身份过完 clean 过滤器，与 EOL 形态无关**，于是本机与 CI 拿到的是同一条腿。

**CRLF 不变性证明**（临时件全部在仓库外，`evidence/p0-3bf1-crlf-invariance.txt`）：

```
源工作树字节：40517 B / CR 0
  acc_lf.py    40517 B / CR 0    工作树 sha1=da92cdf51de5…  git hash-object=d8f4ceb5f798…
  acc_crlf.py  41232 B / CR 715  工作树 sha1=189a6e3b5330…  git hash-object=d8f4ceb5f798…
manifest 记录：sha1=da92cdf51de5… git_blob=d8f4ceb5f798… repo_path=backend/tests/test_real_llm_failover_acceptance.py
git rev-parse HEAD:<repo_path> = d8f4ceb5f798…
把 kit.ACCEPTANCE_FILE 逐枚指到 LF / CRLF / 源工作树：blob 腿问题 0 条 / 0 条 / 0 条，三份结论逐枚相同 = True
对照：同一批字节按工作树 sha1 判，CRLF 那枚给 189a6e3b… ≠ 记录值 ⇒ 正是会被冤枉的那一次真话
```

**签出侧的现场复现**（不是合成件，就是本轮那枚克隆）：克隆里的
`backend/tests/test_real_llm_failover_acceptance.py` 落地为 **41232 B / CR 715**（工作树 sha1
`189a6e3b…`，与 manifest 记录值不等），而 `raw_state=json-only` 那一条腿打印的是
blob 三枚全等 ⇒ **15 passed**（`evidence/p0-3bf1-clean-clone-gate.txt`）。
⇒ 「blob 腿在签出形态下不翻结论」这条不是推理，是本轮读出来的。

顺带记一条**对前序 §11① 的更正**（同一批实测）：§11① 说「`-c core.autocrlf=false` 也照样转，
因为签出 EOL 由 `core.eol`/平台决定」——结论对、机制写歪了一半：本轮那枚 `-c core.autocrlf=false`
的克隆**确实**把 `* text=auto` 的文本件签成了 CRLF（acceptance 41232 B/CR 715），
但 `docs/MODEL_ROUTER_V23_MATRIX.md` 在克隆里是 25424 B/CR 163，而**那 163 枚 CR 本来就在
HEAD 的 blob 里**（不是签出加的）。两件事都归到「载体必须以 LF 入库」这一条同一个出路（
`.gitattributes` 给 `docs/evidence/** text eol=lf`，本轮仍是禁改项），不影响 §11① 的结论。

### F3.5. M2 — interlock 6 可以被「少一条腿」满足

原条件 `set(pointers.values()) - {None} != values or len(pointers) != 3`：把任一枚指针
改成 `null`，`- {None}` 先把它摘掉，剩下的两枚照样等于 `values`、枚数仍是 3 ⇒
**三处同源在缺一条腿的情况下宣告成立**（评审实测：无 `[I6]` 问题）。

**改法**（kit:1885–1899，四层递进，缺任何东西都响）：`pointers` 不是 dict ⇒ 红；
键名集合 ≠ `_TRACE_ID_POINTER_KEYS`（kit:896，导出侧与判定侧**共用这枚常量**，
`build_portable_bundle` 里键名不匹配直接 `raise AssertionError`）⇒ 红；
**任一枚值为 null ⇒ `[I6] … 有指针为 null…缺腿不等于一致`**；值集合 ≠ 四处真值 ⇒ 红。
**证伪**：闸内探针两发（改成 null / 摘掉一枚键）+ bench 枪 **N5**（本机与克隆双处红）。

### F4. 读数 1–3：干净签出 / 本机 raw 在场 / 五发负面枪

**取法**（临时件全在 `%TEMP%`，源仓零写入）：

```
T=$(mktemp -d /tmp/p03bfix1-XXXXXX)                 → C:\Users\zhang\AppData\Local\Temp\p03bfix1-1NyId7
git clone -q --no-hardlinks -c core.autocrlf=false E:/xiangmu/rag $T/ragclone
git -C $T/ragclone rev-parse HEAD                   → 7923ee47955197406ee0dd498f74587d8915a7d8（与源仓同一个 HEAD）
mkdir -p $T/ragclone/docs/evidence/model-router-v23/real-llm-failover-001
cp 六枚 bundle + kit + 闸 → 克隆同路径（本轮改过的三枚 .py/JSON 都是 cp 原字节，克隆里没有第二份真相）
克隆里 task10/ 只有 real-llm-failover-001.json（跟踪件），run/ 目录不存在 ⇒ 这就是 CI 的形态
```

**读数 1（干净签出，`evidence/p0-3bf1-clean-clone-gate.txt` 原文，逐字）**：

```
[P0 闸③ 分支] portable 层：0 条问题（bundle 目录 C:\Users\…\raglf\docs\evidence\model-router-v23\
real-llm-failover-001，读包结果 None） | [T-*] 真值层：0 条（无条件执行） | raw 层状态 = json-only
（full = §6 validate_evidence() 实跑；json-only = provenance/blob 腿 + 面对面核对，§6 因本体不入库
而不跑；absent = 证据 JSON 自己不在场，[T-*] 直接响） | raw 问题 0 条 | 原始件双条件定位：
trace_jsonl=缺席, ledger_db=缺席, primary_probe=缺席, acceptance_module=在场 |
acceptance_module 的 git blob 腿：blob 记录=d8f4ceb5f798b91201bf3db1b92f1f112d87e137
HEAD=d8f4ceb5f798b91201bf3db1b92f1f112d87e137 工作树重算=d8f4ceb5f798b91201bf3db1b92f1f112d87e137 一致=True
15 passed, 34 subtests passed in 10.12s
```

⇒ 三条都按裁定要求：仍 `15 passed`、仍 `raw_state=json-only`、**blob 腿打印出三枚实测值**
（这一行是判据的一部分，不是叙述——`_verdict_branch_line()` 绿的时候也要打印）。

**读数 2（本机，raw 四枚都在场，`evidence/p0-3bf1-local-rawfull-gate.txt`）**：
同一条分支行打印 `raw 层状态 = full`、四枚 `在场`、blob 三枚全等，`15 passed, 34 subtests passed
in 9.32s`。`full` 分支里 §6 `validate_evidence()` 照旧全量跑（判据一字未改）。

**读数 3（五发负面枪，逐发实测）**。台子新增 `--root <签出>` 把整套路径改指到克隆
（`bind()` 先逐字节比对克隆里的 kit/闸与源仓，不一致就中止——不许对着两份代码取证）：

| 枪 | 注入（靶子不是 bundle 载荷件） | 期望点名的判据 | 本机（`full`） | 干净签出（`json-only`） |
| --- | --- | --- | --- | --- |
| N1 | 已跟踪 JSON 注入 `"rehearsal": true` | `[T-彩排]` | KILLED-ASSIGNED + RESTORED-OK | **KILLED-ASSIGNED + RESTORED-OK**（评审原复现：15 passed） |
| N2 | 已跟踪 JSON 的 `"completed": true` → `false` | `[T-收尾]` | KILLED-ASSIGNED + RESTORED-OK | **KILLED-ASSIGNED + RESTORED-OK**（评审原复现：15 passed） |
| N3 | 已跟踪 JSON **删掉** `provider_transport` 键 | `[T-传输层]` | KILLED-ASSIGNED + RESTORED-OK | **KILLED-ASSIGNED + RESTORED-OK**（评审原复现：15 passed） |
| N4 | 篡改 `agent_traces.jsonl` **且**删掉 `conversations.db` | `[I7] 原始件 sha1 与 bundle 声明不等：trace_jsonl` | **KILLED-ASSIGNED + RESTORED-OK** | 不适用（签出里本来就没有这两枚） |
| N5 | `manifest.trace_id_source.pointers.request.trace_id` → `null` | `[I6] … 有指针为 null` | KILLED-ASSIGNED + RESTORED-OK | **KILLED-ASSIGNED + RESTORED-OK**（评审原复现：无 `[I6]`） |

N1/N2/N3/N5 的克隆原文：`evidence/p0-3bf1-replica-negative-shots.txt` +
`evidence/p0-3b-red-N{1,2,3,5}.txt`（逐发的 pytest 失败文案，里面能看到 `[T-*]`/`[I6]` 自己点名）；
N4 与九发变异的原文：`tmp/p0-3b-red-*.txt` + `evidence/p0-3bf1-mutation-bench-final.txt`。
N4 是本轮最要紧的一发：它复现的正是「raw 在场但对不上」被「另一枚缺席」连坐掉的形状；
现在 `json-only` 也调 `raw_layer_problems()`，被篡改的那枚当场响，缺席的那枚继续按裁定不响。

### F5. 读数 4：十四发变异 + **活着的**锚点互锁（L1 / L4）

L1 的原话核对：`Op.needle` 与 `Op.check()` 一直在，但**没有一枚 `shot()` 传过 needle**
⇒ `check()` 恒 `None` ⇒ §4.2 那句「锚点 M1…M9 全 ANCHOR-OK」是同义反复
（和 B0 那枚没人读的 `spec["node"]` 同一类病）。本轮：

- 十四发的**每一枚 op 都带 needle**，`--check` 现在逐发打印 `needle k/n 枚 op 带锚`，
  且 `k != n` 直接把 `--check` 判为不合格（互锁不许再变成摆设）：
  `锚点 M1: ANCHOR-OK（needle 3/3 枚 op 带锚） … N5: ANCHOR-OK（needle 2/2 枚 op 带锚）`
  （`evidence/p0-3bf1-bench-check.txt`，六枚基线 RESTORED-OK ×6 + 闸锚在场且唯一=True +
  序列化口径可逆=True）
- **证明它会响**（`--anchor-selftest`，全程不落盘，`evidence/p0-3bf1-anchor-selftest.txt`）：

```
needle 命中 0 次（目标不在场）: result.json needle=b'"no-such-key-NOT-IN-BUNDLE"' 实测命中=0 次
    ⇒ check() = 'TARGET-NOT-FOUND result.json 自证（不会 apply）'
needle 命中 >1 次（锚不唯一）  : response.json needle=b'"model"' 实测命中=3 次
    ⇒ check() = 'ANCHOR-NOT-UNIQUE response.json 自证（不会 apply） ×3'
两枚都响 = True
```

L4：`restamp_ops()` 过去只做 `sha256` 的字符串替换、**不换 `bytes`** ⇒ M1/M2/M3/M5
除了该打的 interlock 之外还**顺带**红 `[I2]` 的 bytes 半条，与 §12.4「只有 sha256 对照被喂平」
的说法不符（那句在 §F8 里登记为被本轮推翻）。现在走 JSON 级改写：同一枚 `portable_files` 条目
里 `sha256` 与 `bytes` 一起按，序列化仍用 `kit._bundle_text` 同一枚口径（`roundtrip_proof()`
在整轮开始前逐字节证明可逆，不可逆就 `[中止]` 整轮）。

**十四发整轮**（`evidence/p0-3bf1-mutation-bench-final.txt`，rc=0）：

```
M1..M9 + N1..N5 = 14 发，逐发 判决 = KILLED-ASSIGNED-RESTORED-OK
计数: {'KILLED': 14}   计划外附带红 = []（逐发）   park 目录已删 = True
```

**仪表的第三处病，本轮当场治好**：第一次整轮跑出来是 **4 发 ASSIGNED + 10 发 INCIDENTAL**，
红面与判据全对，错在 `run_gate()` 的子进程编码——本机 `python` 的 `sys.stdout.encoding` 是
`gbk`（bash 里 `LC_ALL=C.UTF-8` 对 Windows CPython 的子进程不生效），台子按 `utf-8` 解码 ⇒
**中文哨兵**（`[T-彩排]`、`不含 §6 那族加载失败特征`、`指向彩排目录`…）解成乱码 ⇒
`token in raw` 恒假 ⇒ 判据明明抓住了也被记成没抓住。只有哨兵是 ASCII 的 M1–M4 侥幸对上。
现在 `run_gate()` 固定注入 `PYTHONIOENCODING=utf-8:replace` + `PYTHONUTF8=1`，跨 shell 可复现。
⇒ 顺带交代一句让下一个人心凉的：§4/§12.4 那批「中文哨兵 KILLED-ASSIGNED」的旧读数**依赖
当时那轮 shell 的编码环境**，本轮无法从存档复核（`evidence/p0-3b-mutation-bench*.txt` 两枚
逐字节相同、里面没有 `INCIDENTAL` 字样），所以本轮只声明**本轮重跑出来的十四发读数**，
不去替旧读数担保。这正是 L1 那一类「仪表不响、结论照抄」的病，登记在此而不是掩盖它。

### F6. 逐条映射表的修订（§5 那张表，哪几格换了）+ 前序报告的三处不实/失准登记

§5 的表体**不重写**（那是独立评审要对着读的原文），这里只登记本轮改了哪几格的「强度」列，
以及本轮实测推翻的前序句子。

| §5 行 | 判据 | 3B 原文 | 修复轮 1 之后 | 标签 | 强度变化 |
| --- | --- | --- | --- | --- | --- |
| 3 | `rehearsal` 真值 ⇒ 拒收 | 「见条件化③」 | **无条件**：`[T-彩排]` 读已跟踪 JSON + `[I7] source_run_flags.rehearsal_truthy` 读被锚钉的 manifest + `[X]` 面对面 | `[T-彩排]` `[I7]` `[X]` | 条件化 → **必须** |
| 5 | `completed is not True` | 条件化① | **无条件**：`[T-收尾]` + `[I7] source_run_flags.completed_is_true` + `[X]` | `[T-收尾]` `[I7]` `[X]` | 条件化 → **必须** |
| 6 | `provider_transport is not None` | 增（只看 bundle） | **源端也判**：成员判定 `"provider_transport" in evidence`（`[T-传输层]`）+ 载体记 `provider_transport_present`（`[C-传输层]`）+ `source_run_flags` 两枚布尔位（`[I7]`）+ `[X]` 比两枚 | `[T-传输层]` `[C-传输层]` `[I7]` `[X]` | 增 → **再增** |
| 28 | `trace_id` 三处同源 | 增 | 指针三枚**必须都在且非 null**（`[I6]` 新增两条出口），键名常量导出侧/判定侧同源 | `[I6]` | 增 → **再增** |
| 31 / 32 | `files_sha1` 空表 / 逐枚重算 | 条件化① | 仍然条件化，但**范围收窄了**：`json-only` 现在也调 `raw_layer_problems()`，四枚 provenance 里被 git 跟踪的那枚改按 **blob** 无条件重算（`[I7-blob]` 三条出口），其余三枚维持「在场才比 sha1」；§6 那张**绝对路径表**的整表重算仍只在 `full` 跑 | `[I7]` `[I7-blob]` `[I2]` | 条件化（格内变严） |
| 30 | `timings_ms.total > 0` | 条件化② | **未动**（3A 的投影表里就是没带这枚字段；替代强度仍是逐枚 `elapsed_ms` + `elapsed_ms_sum`） | `[C-耗时]` | 同 |

**「条件化」从 4 行降到 2 行**（30、32），且第 32 行里被 git 跟踪那一枚已经不是条件化了。
新增的判据标签：`[T-彩排]` / `[T-收尾]` / `[T-传输层]` / `[T-载体]` / `[I7-blob]`，
`[I7]` 下多四类出口（`source_run_flags` 缺位/`completed_is_true`/`rehearsal_truthy`/
`provider_transport_key_present`/`_is_null`/`git_blob` 形状/`repo_path` 形状），
`[C-传输层]` 多一枚，`[I6]` 多两枚，`[X]` 多七枚 compare。**没有一条是被搬走或删掉的。**

前序句子的三处登记（本轮实测推翻，不掩盖）：

1. **§12.4**「`reanchor_ops()` 有没有可能顺手把别的判据也喂平了——我的答复：只有 sha256 对照
   被喂平」——**答复不完整**：旧 `restamp_ops()` 连 `bytes` 都没换（L4），所以 M1/M2/M3/M5
   另外**顺带**红了 `[I2]` 的 bytes 半条。本轮把 `sha256` 与 `bytes` 一起按，那句答复才成立。
2. **§4 的 L5 句**「第一轮的原文保留在 `evidence/p0-3b-mutation-bench.txt`」——**不实**，
   已按更正块改写（两枚存档逐字节相同、`INCIDENTAL` 字样命中 0 次 ⇒ 第一轮没留档）。
3. **§11①** 关于 `-c core.autocrlf=false` 的机制解释——结论（载体必须 LF 入库）不变，
   但「matrix.md 那 163 枚 CR 是签出加的」这半句不成立：它们本来就在 HEAD 的 blob 里
   （实测见 §F3 末）。边界①本身仍然是**未闭合的入库依赖**，等控制器落 `text eol=lf`。
4. **§11②**「`absent` 分支只在代码里存在一支，没有读数支持」——本轮给它**加了判据**
   （`[T-载体]`：证据 JSON 不在场 ⇒ 三枚真值判据不许静默下线，直接响），但**仍然没有真实形态
   可取证**（那枚 JSON 被跟踪 ⇒ 签出里必然在场）。请继续按「已加强、未观测」登记，
   不要读成「已验证」。

### F7. 加强之后的残余信任根（R27 登记的那条仍然挂着）

R27 把「manifest 外部锚对『同一批 diff 里改三处』不设防」判为**登记不修**、列 B1 义务，
本轮**没有**去动那枚锚的形状：它仍然钉在闸文件常量里，仍然在同一份 diff 内可见。
但本轮**改了一次锚值**（见 §F8 的第一行大字：`68749a00e2e2…` → `c39a09f83b6a…`），
这条动作恰好就是 R27 说的那枚残余信任根的**活样本**：一个同时改 bundle + manifest + 闸常数
的人，本轮之后仍能洗平 `[I2]`——洗不平的是 `[T-*]`（读的是签出里那枚跟踪 JSON）、
`[X]`（面对面）、`[I7-blob]`（比的是 HEAD 里的 blob，改 blob 必须提交），
以及 §12.2 列的真机不可再生性。**变强了，没有变干净**，这句话要留给下一个评审。

### F8. 载体侧改了字段 ⇒ **manifest 外部锚被重钉**（R27 记的那枚残余信任根，大声说这一句）

**必须重钉，而且只重钉了一次。** 因为 H1/H2/M1 三条的修复都需要「让 portable 层单独也判得动」，
载体因此多了三段字段：`response.json` 的 `provider_transport_present`、
`manifest.source_run_flags`（五枚布尔位）、`manifest.raw_provenance[]` 的 `repo_path` + `git_blob`
（+ `git_blob_origin` 自述）。**六枚全部经 `kit.build_portable_bundle` / `kit.write_portable_bundle`
重导落盘，没有手改任何一枚 bundle JSON**（`write_portable_bundle` 落盘后还会自己重算并逐条核对
`sha256` + `bytes`，对不上就 `AssertionError`）。

```
闸文件常数 PORTABLE_MANIFEST_SHA256
  旧值（3B 初版，本轮作废）  68749a00e2e2a848d80aee054084df6b085a948683a775af13e79024dde4f7c1
  新值（本轮，重导后盘上实测）c39a09f83b6abdab475cbf3527b2d92ba5459dbbaa55535c1f26b9f634308508
重导逐枚对照（sha256 前 12 位 / 字节数，BEFORE → AFTER）：
  result.json          ca9f7a4e22e6  8150 B → ca9f7a4e22e6  8150 B   未变
  response.json        c0aa6c9f0b14  2505 B → dc5fee2215a7  2543 B   换（多 provider_transport_present）
  ledger-row.json      a87b7178aab0  2117 B → a87b7178aab0  2117 B   未变
  trace-attempts.json  1aa8a1dbfb6b  1326 B → 1aa8a1dbfb6b  1326 B   未变
  primary-probe.json   9084df5502c6  3160 B → 9084df5502c6  3160 B   未变
  manifest.json        68749a00e2e2  6863 B → c39a09f83b6a  7355 B   换（source_run_flags + git_blob + repo_path + 载荷声明里的 response 那一枚）
台子 BASELINE_SHA256 的六枚同步按到新值（旧值两枚写在注释里，见 mutations/p0_3b_mutations.py 抬头）；
manifest 里 raw_provenance.acceptance_module 的新字段实测：
  sha1=da92cdf51de5dbfad3107f1dc744d18e4173e07c（保留，工作树字节）
  git_blob=d8f4ceb5f798b91201bf3db1b92f1f112d87e137  repo_path=backend/tests/test_real_llm_failover_acceptance.py
  与 `git rev-parse HEAD:backend/tests/test_real_llm_failover_acceptance.py` 逐字符相等（本机 + 克隆两侧都验）
六枚 LF-only / 零绝对路径复验：manifest.json 7355 B / CR 0；`_ABSOLUTE_PATH_RE` 对六枚逐枚扫描
= 0 命中（新加的 `repo_path` 是仓相对 posix，`git_blob` 是十六进制，都不引入单机耦合）。
```

**为什么这枚重钉是「可见的代码改动」而不是「洗平判据」**：改的是 `git rev-parse` 拿得到的
载体字段与一份机械投影，`test_real_llm_failover_gate.py` 里那枚常数的 diff 与 bundle 的 diff
在同一批里，评审一眼看得见；台账 §F7 说的残余信任根不因为本轮而消失，也不因为本轮而加重。

---

### F9. 控制器本人复现（2026-09-29）+ 一枚**新发现的真源缺陷**

F5 那十四发的读数是 implementer 写的，我在压缩前的台账里把它标成「未由我复现、不得当作已验」。
本节是**我自己重跑**的结果，跑法与 F5 同一枚台子、同一份 HEAD（`b825112` 的代码面，工作树经逐字节
核对 == blob）：

```
--check            基线六枚 RESTORED-OK ×6 + 闸文件外部锚在场且唯一=True + 序列化口径可逆=True
                   锚点 M1..M9 / N1..N5 逐发 ANCHOR-OK，needle 计数 3/3、2/2、1/1 全带锚
--anchor-selftest  两枚故意错的 needle 都响：TARGET-NOT-FOUND ×1、ANCHOR-NOT-UNIQUE ×3（不落盘）
整轮十四发          M1..M9 + N1..N5 = KILLED-ASSIGNED-RESTORED-OK ×14，rc=0
                   计划外附带红 = [] ×14；还原核对该行出现 ×14（sha256 同 + 外部 cmp rc=0 + 基线核对）
                   计数: {'KILLED': 14}，park 目录已删 = True
```

原始输出落盘：`evidence/p0-3b-bench-controller-repro-2026-09-29.txt`（7809 B，未入库）。
干净态定向复跑（同一次运行后）：四枚被触碰模块 `183 passed / 0 failed / 243 subtests in 125.10s`，
收集探针 `TOTAL 1335`。⇒ F5 的结论**成立**，从"implementer 声称"升格为"控制器复现"。

**简报那六条读数逐条对上（我这轮的层级都标出来）**：

| 读数 | 我的复现 | 层级 / 状态 |
| --- | --- | --- |
| 1 干净签出闸绿 | Windows clone **红**（3 failed，`[I2]`），同 clone 改回 LF **绿**（15 passed）；Linux/CI 形态由远端 run `36472389872` 的 1335 里这枚闸通过 | **条件成立**——"可移植"目前只在 LF 检出形态上成立，见下方新缺陷 |
| 2 本机 raw 在场且执行 | `kit.p0_evidence_verdict()` 直读：`raw_state='full'`、portable / truth / raw 三组 problems 全 `[]`、两枚运行件 `sha1 == declared == recorded` | **复现** |
| 3 十四发逐发杀 | 见上，`KILLED-ASSIGNED-RESTORED-OK` ×14、`[]` 附带红 ×14、rc=0 | **复现** |
| 4 闸模块整模块绿 + SEC-A 46 passed + 零新增豁免 | 闸模块在 clone/本机两侧皆 15 passed；SEC-A 单跑 **46 passed**，`git diff --stat` 对该文件**为空** | **复现** |
| 5 收集数 1335 + B0 十六枚门 | `TOTAL 1335`；`test_ci_gate_contract.py` 单跑 **16 passed** | **复现** |
| 6 全量两 cwd | 我没有重跑（本轮自 `b825112` 起**没有改动任何代码面**，工作树逐字节 == blob，而远端在同一 commit 上量过 `1335 passed / 0 failed`）；这条沿用 R30 的读数与 §10.3 的远端读数，**不冒称本轮新量** | 沿用（层级已注明） |


**残留核对做到三层，不是因为台子可信**：`git cat-file blob HEAD:<path>` 与工作树逐字节 `==`
（三枚：manifest / 闸文件 / primary-probe）；`PORTABLE_MANIFEST_SHA256` == manifest 工作树 sha256
（`c39a09f8…`）；raw 层两枚运行件 sha1 == manifest `raw_provenance` 声明值
（`conversations.db b93ce392a1d7…`、`agent_traces.jsonl 356826f73d7c…`）。

**我自己的一次破坏，如实记在这里**：第一轮整轮我放后台跑，看到 `PORTABLE_MANIFEST_SHA256` 在变
就误判成异常，**中途 kill** ⇒ M5 的注入字节留在三枚已跟踪文件里。事实上台子**必须**同时按 pin
（台头 ③：改 manifest 不改锚，`[I2]` 会先响，后面 `[I3]`–`[I7]` 到底有没有牙就永远读不出来），
所以那三处漂移是正常注入，不正常的是我打断它。
⇒ 教训：**这枚台子在跑的时候工作树必然是脏的，且 kill 一次就留下真脏树**；处置只能按 `--check`
的基线值逐枚回到 blob，`git restore` 单独用不够（见下一条）。已登记为台账 R31。

**新发现（真源缺陷，不是仪表病）：`[I2]` 外部锚依赖 checkout 的行尾形态。**
Windows 上干净 clone 实测：`docs/evidence/**` 六枚 JSON 全被 smudge 成 **CRLF**，
manifest 工作树 sha256 变成 `91b0dff6…` ≠ 钉住的 `c39a09f8…`（后者是 blob / Linux CI 形态）。
`git check-attr` 给的机制是它自己说的：`text: auto` + `eol: unspecified` ⇒ 检出形态由
`core.autocrlf=true` 决定。⇒ **同一枚 commit 在远端 Linux 绿、在 Windows 签出必红**；
R26-③ 想要的"可移植载体"在行尾这一维上还没成立。

**这一条是隔离出来的，不是推出来的**（同一枚 clone、同一份 HEAD，只把行尾当唯一变量）：

| 同一 clone 的两态 | 命令 | 读数 |
| --- | --- | --- |
| 检出原样（六枚 CRLF） | `pytest tests/test_real_llm_failover_gate.py` | **3 failed / 14 passed / 32 subtests**：`test_p0_row_status_matches_the_evidence` 红（`'BLOCKED' != 'GREEN'`，portable 层 **17 条问题**），两枚 `SUBFAILED` 是退化探针自己拒绝——它明说「baseline 已经带着 `[I2]` sha256 不配：bundle 本身就不成立，这发探针证明不了任何事」 |
| 六枚就地改回 LF（工作树 == blob） | 同上 | **15 passed / 0 failed / 34 subtests in 9.29s** |

⇒ 根因**只有行尾**，而且闸的拒绝式文案在这里干了对的事：它没有让那两发探针在坏基线上假绿。
B0 的行尾门抓不到它，因为那些钉量的是 index 侧（index 里一直是 LF，无违规），不是检出侧。
两条候选，**都还没动**，待用户 / 独立评审裁：

- **A（我倾向）**：`.gitattributes` 加 `docs/evidence/** text eol=lf`。结构性确定、判据一字不动，
  代价是改一枚**有锚的交付面文件**（`c5d07b5dc438`）并同步 B0 验收 §11，且门 13 的必需规则集
  要确认加一条不会红（它钉的是"三枚必须在"，不是"只许三枚"，但这条得实测而不是推断）。
- **B**：kit 哈希前先做 CRLF→LF 规范化。只动载体，但把"逐字节"这句话改弱了，
  而且是**判据代码**在替 git 做决定。

顺手一条同族事实：`git restore` 之后 `git status` 仍会把这三枚显示成 ` M`（工作树是 LF、
autocrlf 期望 CRLF），而 `git diff` 为空 ⇒ 这是 stat-dirty 不是内容差。**别把它读成残留**，
但也别用它当"干净"的证据——判据是逐字节 `==` blob。

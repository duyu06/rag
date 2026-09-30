# ENTERPRISE-B0 验收记录 · 门禁地基（2026-09-28）

| 项 | 值 |
| --- | --- |
| 文档 | `docs/ENTERPRISE_B0_ACCEPTANCE_2026-09-28.md` |
| 规格 | `docs/ENTERPRISE_B0_SPECIFICATION.md`（2026-09-28 冻结，含 §16 修订卡 A–E 与本轮新增 F–K） |
| 计划 | `docs/ENTERPRISE_B0_PLAN.md`（7 枚任务） |
| 执行方式 | SDD 逐任务：实现 → 独立评审 → 修复轮 → 定向复评。台账 `.superpowers/sdd/ENTERPRISE_B0_PLAN/progress.md` |
| 起始状态 | HEAD = `7cc5efc` = tag `security-a-rc1`；工作树带两枚**不属于 B0** 的未提交改动（`backend/app/identity/README.md`、`__init__.py`） |
| 状态 | **`backend-contracts` 远端已 GREEN**（run `36472389872`：1335 passed / 0 failed；compose 与 pwsh 首次真跑即绿）。**但整个 run 仍 red**：`backend-integration` 缺 `argon2`、`backend-quality` 缺 `typesafe_sdk` —— 规格 §1 明令 B0 不得触碰这两枚 job，故属未做的既有缺口，不是本轮引入的回归 |
| tag | **暂缓**（用户 2026-09-28 裁定：按清单提交并推送，tag 不在本轮） |

---

## 1. 一句话

B0 做完之后，"CI 有一步在跑测试"这句话第一次可以被机器反驳：收集数被钉住、runner 只剩一个、
依赖只有一份真源、行尾归一化变成仓库属性，而这四条各自都有一枚**被观测到红过**的门守着。

## 2. 判据矩阵

状态词只用 `GREEN / PENDING_EXTERNAL / BLOCKED`。本地读数为控制器本人复跑，非转抄子代理。

| ID | 判据 | 读数 | 状态 |
| --- | --- | --- | --- |
| B0-01 | pytest 收集数 == 钉住常数 | `EXPECTED_COLLECTED = 1332`（**该读数取自重锚前**；现行常数 **1336**，链条 1332→1335→1336 见 §11.1 与 §11.2）；本地两 cwd 与发布容器三处同数；门 `test_collected_count_matches_the_pinned_number` 绿 | **GREEN**（远端比对归 B0-03） |
| B0-02 | 远端 `backend-contracts` **整 job** success | run `36472389872` ⇒ job **success**，非成功步骤数 = 0 | **GREEN** |
| B0-03 | 同 commit 本地与远端收集数逐位相同 | 本地两 cwd `1335 passed / 0 failed / 1159 subtests`；远端同 commit `1335 passed / 2 warnings / 1159 subtests in 54.59s` ⇒ 枚数与子测数逐位相同（warnings 36↔2 属 §14 L9 的 env 耦合，不作跨环境判据） | **GREEN** |
| B0-04 | §8.1 四格全绿且 `.env` 还原逐字节一致 | 四格 `1332 passed / 36 warnings / 1133 subtests`（同为重锚前读数，现行 1336）、rc=0、0 failed/0 errors/0 skipped；`.env` sha `4d7f974107dd` 前后相同 | **GREEN** |
| B0-05 | 单 runner 钉绿 | 门绿；`ci.yml` 内无 `unittest discover` 步 | **GREEN** |
| B0-06 | 依赖同源钉绿（含豁免表形状） | 门绿；豁免表恰 `pytest` + `torch`（CPU 发行源），多一处少一处皆红 | **GREEN** |
| B0-07 | `.gitattributes` 的 no-op 性 | 静态 `checked=2 / offenders=0`；动态工作树聚合 sha 四时点恒等，`git status` 仅多出 `?? .gitattributes` 一行 | **GREEN** |
| B0-08 | 行尾钉：无 `i/crlf`；`i/-text` == 枚举 3 枚；解析覆盖 313/313 | 门绿（含修复轮补的非空地板） | **GREEN** |
| B0-09 | SECA-20 扫描门零漂移 | 面 316→318（B0 当时；`c29ce8a` 后为 448，见 §11.1 与 **L11**），**命中 16 文件 / 31 处与 SEC-A 封版一字未动**，`EXEMPTIONS` 与 HEAD 逐字节相同 ⇒ 零新增豁免是被证明的。**覆盖范围要说平**：命中对账只覆盖进内容扫描的那 230 枚，`.superpowers/**` 那 218 枚按设计免扫（L11） | **GREEN** |
| B0-10 | compose 与 pwsh 两道首次真起跑各有结论 | run `36472389872`：两步均 **success** —— 它们**有史以来第一次被执行**（此前恒被上游红步吞掉，正是 §5.2 描述的机制在运行）。**但这是每轮读数，不是既成事实**：`047a0d4` 那轮主门一红，两道又立即回到 `skipped` ⇒ 判据应读作「在主门确定化之后连续 success」 | **GREEN** |
| B0-11 | §9 变异逐发红 + 还原一致 | **8/8 `KILLED-ASSIGNED`**，0 `KILLED-INCIDENTAL`、0 `COLLECTION-BROKEN`；`--check` 12/12 rc=0；聚合面三时点回台账。**2026-09-30 加强**：这一行原来只要求"那枚红了"，独立终审 Important 4 把它改成"红因必须落在这一发点名的那枚节点自己的失败块里"⇒ 新增 `KILLED-WRONG-REASON` / `KILLED-NO-BLOCK` 两枚不通过态，并抓到 P0 台一枚恒真还原条件。重跑读数 **B0 8/8 + P0 14/14 全 `KILLED-ASSIGNED(-RESTORED-OK)`、两台 rc=0**（§11.4） | **GREEN**（判据已加强） |
| B0-12 | `backend/app/**` 未被 B0 改动 | 卡 J 三子句：`git diff --name-only HEAD -- backend/app` 减去两枚 identity 后为空；`--cached` 侧空；两枚 identity sha `3bc681bbc52c` / `2cfab9f18182` == 基线。**独立终审点名**：第一子句今天只剩用户自己的 `identity/README.md` ⇒ 这条审计对「这一串 commit 里 app 面只允许 CORR-01 那一处」不设防；已补成区间机器判据（§11.2） | **GREEN**（判据已加强） |
| B0-13 | 全量 pytest 的 CI 耗时读数与 cache 取舍 | 远端套件 **54.59s**、SECA-20 子集 1.19s；本地 Windows 两格 182.78s / 183.95s；容器 3.12/Linux 107.52s。门内子进程收集占模块 96%、约全量 10–16%。**cache 命中率无分步读数** ⇒ 取舍半边仍开 | **GREEN**（耗时）／**PENDING_EXTERNAL**（cache 取舍） |
| B0-14 | `G20` 新开 + `G0` 勘误落档 | 已落：`docs/ENTERPRISE_ACCEPTANCE_GAP_ANALYSIS.md` 新增 `G20 门禁收集面与行尾` 行；`G0` 行加"有测试步 ≠ 测试被收集"勘误并指向 G20 | **GREEN** |
| B0-15 | 容器内 3.12 那一格有读数 | `rag-backend:security-a-rc1` / Python 3.12.14 / 无 `.env`：`1332 collected`（重锚前读数，现行 1336），格内 `3 failed, 1329 passed`（三枚归因见 §4） | **GREEN** |

## 3. 本轮交付面

**新增**：`.gitattributes`、`backend/tests/test_ci_gate_contract.py`（16 枚门；**2026-09-30 起 17 枚**，见 §11.2）、
`scripts/b0_collection_probe.py`、`docs/ENTERPRISE_B0_SPECIFICATION.md`、`docs/ENTERPRISE_B0_PLAN.md`、
本文件、`.superpowers/sdd/ENTERPRISE_B0_PLAN/**`（台账 / briefs / 报告 / 评审件 / 变异台 / evidence / baseline）。

**修改**：`.github/workflows/ci.yml`（仅 `backend-contracts`；其余三个 job 与上一 commit **逐字节相同**，
评审以 job 块切片独立核过；文件保持 CRLF，bare LF 恒 0）。

**动到的 SEC-A 已封版测试**（用户 R15 显式批准的越界，两处都是"只改测试、判据不降"）：
`backend/tests/test_password_lifecycle_contract.py`（路由枚举改为递归展开）、
`backend/tests/test_real_llm_failover_gate.py`（**只改失败信息**，判据一分未松）。

**精选单文件入库**：`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json`
（P0 真 failover 证据件，`git add -f`）。**不在此列**：两枚 identity 未提交改动、
`snap-task*/`（13 枚快照目录）、`tmp/`（745K 过程件，内含证伪用的一次性假凭据样本，故意不入库）。

### 3.1 提交时抓到的两件事（都不是理论问题）

1. **`git add -f` 会越过 `.gitignore`**，因此 `git add -f <目录>` 会把该目录下被忽略的东西一并拖进 index。
   本轮实发一次：`-f` 扩 `mutations/` 时带进了 `__pycache__/ent_b0_mutations.cpython-313.pyc`，
   而这枚编译产物在 `git ls-files --eol` 里被判定为 **`i/-text`** —— 正好撞在
   `test_non_text_index_entries_are_exactly_the_enumerated_set` 钉死的"必须恰等于那三枚"上。
   已 `git rm --cached` 摘出，摘出后 index 的 `i/-text` 回到三枚、四枚行尾门 3 passed、
   门模块 16 passed、SEC-A 46 passed。**教训落在手法上**：`-f` 只准对**逐个点名的文件**使用，
   不准对目录使用；要扩目录就普通 `git add`，让 `.gitignore` 继续生效。
2. **过程件入库后自动扫描门并不覆盖它们**。把 81 枚 `.superpowers/**` 纳入跟踪后，扫描的**名字表**从
   318 涨到 400，而 `_in_scan_scope()` 按前缀 `.superpowers/` 排除 ⇒ 这些文件的内容**一枚都不被扫描**。
   命中数因此纹丝不动（仍 16 文件 / 31 处，与 SEC-A 封版一致），但"没红"不等于"干净"。
   本轮的补偿取证：把同一组 face（`sk-…`/`gh[pousr]_…`/`AKIA…`/`eyJ…`/`BEGIN … PRIVATE KEY`）
   手工施于全部 81 枚已暂存的 `.superpowers/` 文件，**结果 NONE**。
   于是本文件的措辞纪律是：**"过程件已手工量过，自动扫描门按前缀不覆盖它们"**，
   而不是"过程件已通过扫描门"。若要自动覆盖，得改 `_UNSCANNED_PREFIXES` —— 那是安全面决策，归 B1 / §18。

## 3.2 交接口（对 B1 的两条硬要求）

- `git add -f` 的目录级用法在 CI 侧无门可挡（门只看 index 形状，不看你是谁）。B1 若要继续入库过程件，
  应把"非文本 index 集合"从**枚举三枚**升级为**枚举 + 显式禁止 `__pycache__`/`.pyc` 进面**。
- 扫描面的**名字表**与**实际内容覆盖面**已经分叉（400 vs 319）。B1 若要用面数做判据，必须说明用的是哪一个。

## 4. B0 照出来的既有缺陷（这才是它的收益证明）

这四条都不是 B0 引入的，全部**早就存在**，是"CI 第一次真跑全部测试"这个动作把它们冲出来的：

1. **测量流程自己污染交付面**（卡 F）。规格里"把 `backend/.env` 就地改名 `.env.bak`"这句话，
   因 `.gitignore:6` 是精确路径而让改名产物落进 SECA-20 扫描面，当场把两枚门拖红。
   归因闭环靠一次对照：把 `.env` 挪出仓库后两格同回全绿 ⇒ 红纯由残留。
2. **B0 自己的交付物把门看瞎**（卡 K）。`.gitattributes` 一生效，属性列里就多了空格，
   `_EOL_LINE` 的 `attr/\S*` 抽不动 ⇒ 解析行数 313→311，丢掉的正好是 `deploy.ps1` 与那枚 `.sh`，
   两枚行尾门**静默空判绿**。修法不是补那条正则，是加"解析覆盖度"判据：不依赖属性列形状假设。
3. **一枚 SEC-A 覆盖门在新版 FastAPI 下漏掉 27/48 条服务腿**。顶层 `app.routes` 多出 `_IncludedRouter`
   之后，只走顶层的枚举看不见一半服务面；`MUST_BE_COVERED` 点名的 5 条只是它恰好还能抓到的子集。
   修法是递归展开，**不是**把新类型加白名单——后者等于继续假装"顶层枚举 = 全部服务面"。
   覆盖面只增不减已核（48 腿 / 42 已认证腿两侧一致，白名单未新增任何一枚）。
4. **一枚判据只在"本机有过程件"时才绿**（卡 J 连带）。`test_p0_row_status_matches_the_evidence` 读的
   JSON 被 `.gitignore` 整目录挡掉 ⇒ 干净 checkout 里门要求 `BLOCKED`、矩阵写着 `GREEN`。
   两边都不许动：**改矩阵=篡改 V2.3 已发生的验收事实，放宽门=降反造假强度**。正解是让证据真随仓库交付。

## 5. 变异台

`.superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/ent_b0_mutations.py`，八发：
N1 藏模块 / N2 塞回 unittest 步 / N3 换回手写清单 / N4 多装一枚未豁免包 /
N5 删行尾规则 / N6 把行尾面掏空 / N7 改名一枚门 / N8 把豁免行的"为什么"缩短。

判决口径在修复轮 2 被收紧过：原先 `rc != 0` 就叫 `KILLED`，计划点名的节点**既不打印也不比对**，
所以"另一枚偶然红了"和"该红的红了"在仪表上长得一样。现在强制
`assigned node ∈ observed red set`，并分出 `KILLED-INCIDENTAL` / `COLLECTION-BROKEN` 两个非绿判决。
字节纪律沿用 SEC-A：anchor 必须恰好命中一次、`finally` 用**读到的原字节**还原（不从 git 取，
四个目标里两个是未跟踪文件，`git diff --exit-code` 对它们恒返回 0，那是假绿）、sha + 外部 `cmp` 双核。

16 门"至少被观测到红过一次"的溯源表 = **14/16**；另两枚
（`test_collection_measurement_counts_node_ids_not_the_summary_line`、
`test_eol_rules_are_a_no_op_for_the_current_tree`）是 helper 自测 / 回归守卫，
其非空性由 `assert checked` 与 `assert named` 一类地板保证 —— 这一点如实登记，不写成"全数验证"。

## 6. 规格修订卡索引（§16，判据一律未降）

A "CI 缺依赖"→ 准确表述；B 持久化文件 5→6；C conftest 危害点在 autouse 夹具而非模块级 import；
D 新开 `G20` 并勘误 `G0`；E payload 8→10 字段；F `.env` 挪出仓库（判据未变，取证手法更正）；
G B0-007 与 B0-12 两节自相矛盾的对齐（收紧）；H 自我存续钉"抓得到哑化的门"是越界（收紧）；
I 依赖同源钉被实现缩窄成"包名"（收紧）；J 卡 G 第一子句落地被证伪后的再修正（等价但可满足）；
K `.gitattributes` 令行尾门静默失明（收紧，新增覆盖度判据）。

## 7. 已知限制（B0 不消解）

L1 宿主 3.13.7 与 CI 3.12 之差只由容器格部分覆盖；L2 两枚含游离 CR 的 markdown 仍在 `i/-text`；
L3 `uvicorn` 仍无 job 安装；L4 lint / typecheck / pip-audit / gitleaks / OpenAPI 契约仍未做；
L5 切换前后 `Ran N` 类历史读数不可混读；**L6 自指盲区不可消除**——一枚门无法证明"自己没被摘掉"，
现有缓解只有常数双写与评审看收集数；L7 B0 全绿只能由远端结；
**L8 开区间依赖的解析不可复现是真债**（本轮只修症状），归 B1；
**L9 warning 总数不是跨环境绝对量**（`JWT_SECRET` 31B vs 45B ⇒ 36 vs 2），不得建跨环境绝对值门。
**L10 B0 的行尾四枚钉全部量 index 侧（`i/…`），管不到"检出侧"**：`* text=auto` + `eol: unspecified`
的文本在 Windows 上跟 `core.autocrlf` 走，于是**同一枚 commit 的检出字节在两台上不同**。
这不是 B0 引入的（B0 之前根本没有 `.gitattributes`），但 B0 之后它有了可被证伪的后果——
V2.3 P0 闸的外部锚取的是**工作树** sha256，Windows 干净 clone 因此红在 `[I2]`
（隔离实验：同一 clone 只改行尾 ⇒ `3 failed` ↔ `15 passed`；台账 R32 / 3B 报告 F9）。
**修法 A 已由用户 2026-09-29 裁定并实施**：`.gitattributes` 增加 `docs/evidence/** text eol=lf`
（入库形态本来就一直是 LF，这条只统一**检出**侧），并把这枚规则**并进门 15 的必需规则集**
（`REQUIRED_GITATTRIBUTES_RULES` 三枚 → 四枚）——不新增测试、不动收集数钉；
摘掉那一行当场 `1 failed`、点名 `['docs/evidence/** text eol=lf']`，`finally` 按原字节写回。
⇒ L10 现在是"已知且已钉、两侧都验"：**Windows 干净 clone 复核**（同一枚 clone 只改行尾那一格的对偶）——
六枚 bundle JSON 检出为 **LF**、manifest 工作树 sha256 回到钉住的 `c39a09f8…`、
该 clone 内 `test_real_llm_failover_gate.py` **15 passed / 0 failed**、`test_ci_gate_contract.py` **16 passed**；
**远端也读了**（run `36533335735` @ `c29ce8a`：`backend-contracts` success、0 枚非成功步骤、
`1335 passed / 2 warnings / 1159 subtests in 53.39s`）。Linux 本来就绿，
这一格证明的是**修法没有把 CI 改坏**（门 15 多一条必需规则 + `.gitattributes` 多一行）。
剩下的诚实边界：`.gitattributes` 自己没有 `eol=` 规则（`git add` 时会提示"LF will be replaced by CRLF"），
它管住了别人没管住自己——功能上无害（属性表按空白分隔，与行尾无关），登记在此不做第二轮扩张。

**L11（用户 2026-09-29 裁定登记，不是待办）：交付面里有一整块"公开但免于内容扫描"的过程件。**
`test_secret_hygiene_contract.py:433` `_UNSCANNED_PREFIXES = (".superpowers/",)` ⇒ SECA-20 只把这批文件
**计入面**、**不扫内容**（实测面 448 枚 / 进扫描 230 枚 / 跳过 218 枚）。后果要说白：
① 「命中 16 文件 / 31 处、零新增豁免」这条判据的覆盖范围是那 230 枚，**不得写成"整面已扫"**；
② 那 218 枚（SDD 台账、报告、变异台读数）是**公开**的，里面有 hex 摘要、run id、模型名、证伪样本路径，
   它们的洁净度目前只有手工取证（§3.1 那一类声明）担保，没有机器判据；
③ 这个前缀是**有意为之**：那目录里躺着故意写下的 canary 字面量与被逐字复制进过程的 `app/` 源码副本，
   把豁免表绑上去会让"下一轮快照入库"红在与凭据无关的地方（源码 `:427-430` 的理由）。
裁定：**继续发布**（评审与接手人要能读到台账与证据），并把本条作为长期已知限制挂着；
真正的历史/全仓工具化扫描仍是 SEC-A §18 那笔未做的债。若日后要收窄前缀，得先处理 canary 撞门这条路。

## 8. 开放边界（不假装已解决）

- 行尾覆盖度地板仍可被"自洽的极小假面"绕过（1 条记录 + 1 个同名 tracked 路径可同时满足
  非空 / 等量 / 集合相等），当前兜底是 `i/-text` 的硬编码枚举。彻底闭需把 tracked 侧绑到
  独立计数源（如 `git ls-tree -r HEAD`），那会改动门判据 ⇒ 未做，登记。
- `"Run: a #1"  # 注释`（引号内含 `#` 且另带行尾注释）仍假红；引号感知剥注释可解，完整正确性
  （`\"` / `''` 转义族）才需要 YAML 解析器，而 B0 明令禁止再造第二份真相。树内零此形状。
- P0 evidence 入库后**不经过自动扫描门**（`.superpowers/` 按前缀排除，与 tracked 状态无关）。
  本轮以同一组 face 手工量得 0 命中 —— 验收措辞只能到这个程度，不得写"已过扫描门"。

## 9. 交接口

B0 交给 B1 的是"任何新进 `backend/tests/` 的门都会被 CI 收集"这一事实，以及三条债：
落盘键名黑名单（8 枚调用点 / 6 份文件，等式钉 4→6）、文档元数据与摄取侧止血、
以及 §8 的依赖解析可复现性。B2 拿到的是单一指标实现的前提。

## 10. 远端往返（run `36436145777` @ commit `9482f44`）

`gh run view --json jobs / --log-failed` 实测：

| 项 | 读数 | 状态 |
| --- | --- | --- |
| 整 run | `failure`（4 job：frontend-build **success**、backend-contracts failure、backend-integration failure、backend-quality failure） | — |
| `backend-contracts` 步骤级 | Set up / checkout / setup-python / **Cache pip wheels** / **Install（同源 requirements.txt）** / **SECA-20 扫描** / compileall / validate_demo_assets ⇒ **全 success** | **GREEN** |
| 主门 `Run backend contract suite` | **failure**：`99 failed, 1219 passed, 20 errors, 1127 subtests in 84.23s` | **BLOCKED**（归因见下） |
| compose 配置校验 / pwsh 语法校验 | **skipped**（主门红 ⇒ 同步中止，正是 §5.2 描述的那条机制仍在生效） | **PENDING_EXTERNAL** |
| 远端收集数 | 与本地同为 1332 面（99+1219+20 计入方式见日志） | 待正式核对 |

### 10.1 主门红的两条根因，都不属于 B0 的改造

远端逐条统计（`--log-failed` 里 `FAILED|ERROR backend/tests/` 共 **113 条**）：
**111 条**同一句 `AttributeError: 'UserIdentity' object has no attribute 'get'`，
**1 条** P0 证据闸，**1 条** `test_booting_twice_on_a_file_that_already_has_rows_changes_nothing`
（"第 1 遍冷启动后登录不上：Internal Server Error"，是前一条的下游——登录腿炸在同一个 `.get()` 上）。

**根因 A（112/113）**：已提交的 `backend/app/identity/__init__.py` 里 `resolve_for_user()` 仍是
`record.get("feishu_open_id")`，而 SEC-A 已把 `record` 换成 `directory.UserIdentity`（pydantic 模型，
没有 `.get()`）；宿主那份**未提交**的工作树改动把它改成了 `getattr(record, "feishu_open_id", "")`。
⇒ CI 跑提交版、宿主跑修好的版本，两边不是同一份代码。
**这条同时否证了上一封版结论**：控制器在 `%TEMP%` 干净克隆到 `7cc5efc`（= `security-a-rc1`）复跑
`test_rbac_contract.py::…test_login_payload_exposes_canonical_role_and_permissions`，**当场同一句失败**，
且该树里 `identity/__init__.py:63` 就是 `record.get(...)`。
⇒ **"SEC-A 两 cwd 各 1316 passed" 是带着未提交修复量出来的**；`security-a-rc1` 的树本身不绿。

**根因 B（1 枚，`test_p0_row_status_matches_the_evidence`）**：仅入库 evidence JSON **不够**。
`kit.validate_evidence()` 无条件重算 `files_sha1` 里的**绝对路径**，四枚分别是
`…\task10\run\20260924-215206\conversations.db`、`…\agent_traces.jsonl`、
`…\task10\ornith-primary-load-probe.json`、`backend\tests\test_real_llm_failover_gate.py`——
前三枚都落在 `.superpowers/` 下且**未被跟踪**。干净 checkout 里它们必然 missing ⇒ `problems` 非空 ⇒
闸要求矩阵写 `BLOCKED`，而矩阵写 `GREEN` ⇒ 红。
⇒ 这枚闸**在设计上就是绑定单机的**：只有跑过那一次真 failover 的这台机器、这个绝对路径下才可能满足。
要让它跨机成立，只能把一次真机运行的 **sqlite 库 + trace 原文**一并入库（其中前三枚是运行数据，
`.db` 还会新增一枚 `i/-text`、撞上 §6.4 的枚举钉），或改变该闸的语义。**两条都在 B0 白名单之外，交用户裁**。

### 10.2 本轮结论

**（2026-09-29 更新）这三条已闭合**：`fix(sec-a-corr-01)` 把 `record.get()` 换成属性接口并加三枚 AST 级结构钉；`test(v2.3-p0)` 把 P0 证据改成可移植载体。远端从 99 红降到 0 红，`backend-contracts` 整 job success。让主门第一次跑到 1335 枚的是 B0，把两条早已躺在已提交代码里的缺陷翻出来的也是 B0。剩余 run 级 red 属另两枚 job 的依赖清单漂移（B0 按规格不得触碰）。tag 仍按用户裁定暂缓。

**（原文照录，不删）** B0-02 / B0-10 / B0-13 不闭合，且不可闭合的原因不是 B0 的改造有缺陷，而是 B0 让 CI 第一次真正跑到了
那 1332 枚，从而把两条**早已存在于已提交代码里**的缺陷暴露在门禁上：一条是 SEC-A 自己留下的未提交依赖，
一条是 V2.3 那枚闸的单机耦合。tag 已由用户裁定暂缓，本轮不打。

### 10.3 闭合往返（run `36472389872` @ commit `b825112`，即当前 HEAD）

`gh run view --json jobs / --log / --log-failed` 实测，读数以逐步骤、逐行为单位落档：

| 项 | 读数 | 状态 |
| --- | --- | --- |
| 整 run | `failure`（4 job：`backend-contracts` **success**、`frontend-build` **success**、`backend-integration` failure、`backend-quality` failure） | — |
| `backend-contracts` 步骤级 | 11 步（含 Post 段共 15 步）**全部 success**，非成功步骤数 = **0** | **GREEN** |
| 主门 `Run backend contract suite (single runner: pytest)` | `1335 passed, 2 warnings, 1159 subtests passed in 54.59s` ⇒ 0 failed / 0 errors / 0 skipped | **GREEN** |
| `Validate Docker Compose configuration` | **success**（该步历史上从未被执行过） | **GREEN** |
| `Validate Windows deployment script syntax` | **success**（同上） | **GREEN** |
| `Cache pip wheels` / `Post Cache pip wheels` | success / success，但 workflow 未导出分步命中读数 ⇒ **无法据此判定命中与否** | cache 取舍仍 **PENDING_EXTERNAL** |
| 本地 ↔ 远端逐位 | 本地两 cwd `1335 passed / 0 failed / 1159 subtests`；远端同 commit 同数 ⇒ B0-03 的"逐位相同"成立（warnings 36 ↔ 2 属 §14 L9，不作跨环境判据） | **GREEN** |

**上一节两条根因各自的闭合证据**：
根因 A ⇒ `9bed85a` 把 `record.get("feishu_open_id")` 换成 `getattr` 属性接口，并由
`RecordInterfaceShapeTests` 三枚 AST/语义钉钉住"不得再出现 `Mapping.get` 调用点"（这一枚单独开作
SEC-A-CORR-01，不归 B0）；根因 B ⇒ `64ec762` + `71cc5e1` 把 P0 证据改成**可移植载体**（portable bundle +
manifest 的 sha256 外锚 + raw 层条件判据），干净签出下 `source_run_dir` 缺席只把 raw 层判为不可用，
不再把整枚闸彩排成 `BLOCKED`。

**剩余 run 级 red 的逐条归因**（两者 B0 按规格 §1 均**不得触碰**，属既有缺口而非本轮回归）：
`backend-integration` ⇒ `ModuleNotFoundError: No module named 'argon2'`；
`backend-quality` ⇒ `ModuleNotFoundError: No module named 'typesafe_sdk'`。
⇒ 与 §15 交给 B1 的"依赖清单同源化"是同一条债，只是那两枚 job 的清单不在 B0 的白名单里。

## 11. 冻结基线读数

**方法先说清**：下面所有 12 位锚点一律是**对文件原始字节取 sha256、截前 12 位**（不是 git blob sha1；
本节早先的读数没有标算法，这本身就是一枚可复现性缺陷，在此补上）。测量式：
`hashlib.sha256(Path(f).read_bytes()).hexdigest()[:12]`。

控制器本人复跑（提交前）：`python -m pytest backend/tests -q` ⇒
**1332 passed, 36 warnings, 1133 subtests passed in 178.43s**，rc=0。

字节锚点（B0 自身收口时点）：`ci.yml` `1c706e165b73`（147 CRLF / 0 bare LF）、
门文件 `a0b9f37f32bb`（832 LF / 0 CRLF / 50994 B）、`.gitattributes` `c5d07b5dc438`（18 LF / 0 CR）、
SEC-A 扫描模块 `fd39d7d374f9`（与上一 commit 逐字节相同 ⇒ 零豁免漂移可证）、
identity 两枚 `3bc681bbc52c` / `2cfab9f18182`（未触碰）、
`.env` `4d7f974107dd`、跟踪面聚合 `d30366c6a440`@313 / `2685edde76fe`@311、
扫描面 318 文件 / 16 命中 / 31 处。

### 11.1 闭合时点（HEAD `b825112`）的复量与逐枚归因

远端与本地同 commit 的读数见 §10.3。锚点在两枚文件上**合法漂动**，其余逐字符回台账：

| 件 | 收口时点 | 闭合时点 | 漂动原因 |
| --- | --- | --- | --- |
| `backend/tests/test_ci_gate_contract.py` | `a0b9f37f32bb` | `893d59b4d74b` | `05334eb` 把 `EXPECTED_COLLECTED` 从 1332 重锚到 1335；字节数（50994 B / 832 LF）与行数一字未动 ⇒ 只有那三位数字变了 |
| `backend/app/identity/__init__.py` | `2cfab9f18182`（工作树态、未提交） | `2cfab9f18182`（已提交） | 同一份字节：B0-12 量的是"工作树 == 基线工作树"，CORR-01 只是把它入库 ⇒ B0 未触碰 `backend/app/**` 这条判据不变 |
| `ci.yml` / SEC-A 扫描模块 | `1c706e165b73` / `fd39d7d374f9` | 两枚**逐字符相同** | 闭合往返没动这两枚；`fd39d7d374f9` 相同 ⇒ `EXEMPTIONS` 表零漂移仍然成立 |
| `.gitattributes` | `c5d07b5dc438`（18 LF / 0 CR / 435 B） | **`b85430dbe6d1`**（23 LF / 0 CR / 846 B） | L10 的修法 A：新增 `docs/evidence/** text eol=lf` + 四行说明。这是**检出侧**规则，blob 侧一直是 LF ⇒ 不触发任何 renormalisation，`i/crlf` 仍 0、`i/-text` 仍恰三枚 |
| `backend/tests/test_ci_gate_contract.py`（第二次漂动） | `a0b9f37f32bb` → `893d59b4d74b` | **`5ac7220e6c55`**（839 LF / 51731 B） | 门 15 的必需规则集 3→4（把上面那条并进来钉住）；**没有新增测试** ⇒ `EXPECTED_COLLECTED` 仍是 1335，实测 `TOTAL 1335` |

新落档（闭合时点首次有锚）：`backend/tests/real_llm_failover_kit.py` `bc5c90c7616c`（136036 B / LF-only）、
`backend/tests/test_real_llm_failover_gate.py` `1ecc82b411e1`（55602 B / LF-only）、
`backend/tests/test_feishu_identity_contract.py` `19394dbd78c6`（110364 B / LF-only）。

**交付面 313 → 447 的逐枚归因**（`git ls-tree -r 7cc5efc` vs `git ls-files -c -o --exclude-standard` 实测差集 134 枚）：
`.superpowers/**` +121（SDD 过程件与 evidence 目录）、`docs/` +10（含 6 枚 P0 portable evidence JSON 与三份额外文档）、
`.gitattributes` +1、`backend/tests/test_ci_gate_contract.py` +1、`scripts/b0_collection_probe.py` +1。
（`c29ce8a` 又 `-f` 入库一枚变异台读数 ⇒ 独立终审复量时面是 **448**，其中 `.superpowers/**` 共 **218** 枚。）

**上面这段话里有一句是错的，就地更正（2026-09-29，独立终审回席后我复验）**：我曾写「新增的 217 枚
`.superpowers` 过程件里零命中，是被门禁跑出来的，不是我扫出来再抄进来的」。**实情不是这样**：
`test_secret_hygiene_contract.py:433` 有 `_UNSCANNED_PREFIXES = (".superpowers/",)`，`:575 _in_scan_scope()`
让整目录**免于内容扫描**（实测：面 448 枚 / 进内容扫描 230 枚 / 被前缀跳过 218 枚）。⇒
「命中 16 文件 / 31 处、零新增豁免」这条**只对那 230 枚**成立；那 218 枚既进了面、又按设计不被扫，
所以"它们零命中"从来不是门禁跑出来的结论，而是我**把"进了面"读成了"被扫了"**。
B0-09 的既有判据本身不受影响（面计数与命中对账都真），受影响的是我为它加的那句强度声明。
用户 2026-09-29 裁定：过程件**继续发布**，但把这件事登记成 §14 的一条已知限制（见 **L11**），
不靠删面或改扫描范围来让数字好看。

**`.env` 一维**：`backend/.env` 此刻**仍在原位**（1561 B、0 CRLF / LF 行、sha256 前 12 位 `4d7f974107dd`
与收口时点逐字符相同 ⇒ §8.1 的"移出再逐字节还原"确实还原了）。它被 `.gitignore:6` 的精确路径挡在
跟踪面与扫描面之外（`git ls-files` 无此项），所以 447 枚里没有它 —— 与 §8.1 的结论一致：该维度中性。

### 11.2 第 17 枚门（独立终审 Important 2，用户 2026-09-30 裁定开工）

终审实测：卡 J 的第一子句 `git diff --name-only HEAD -- backend/app` 减掉两枚 identity 后**只剩用户自己的
README** ⇒ 那条「B0 不动 app 面」的审计在 CORR-01 之后退化成近似恒真。本轮把它换成**区间判据**并机器化：

- 新门 `test_the_app_surface_delta_since_the_sealed_base_is_exactly_the_registered_exception`：
  基线取 **sha 常数** `7cc5efc0460a…`（= tag `security-a-rc1`；不取 tag 名是为了把失败模式收敛成一种
  ——「历史没取全」——而不是「tag 没了」或「浅签出」两种）；要求 `基线..HEAD` 的 `backend/app/**` 差集
  **恰等于**登记表 `{backend/app/identity/__init__.py}`，两个方向都红：未登记的改动 / 被悄悄摘掉的例外。
- **它把 CI 的一个隐含前提变成了判据**：浅签出没有历史 ⇒ 这枚门必须**哑红而不是绿**。因此 `ci.yml` 的
  `backend-contracts` checkout 步加了 `fetch-depth: 0`（仓库对象包实测 490 KiB，代价可忽略）。
- **三发证伪都在临时 clone 里真跑过**（不写主仓、跑完即删）：
  P1 `--depth 1` clone ⇒ 该门 `1 failed`，文案点名「基线 commit 7cc5efc0460a 在本签出里不可解析 ⇒
  这枚门**哑了**，绝不能读成『app 面没有改动』… 需要 fetch-depth: 0」；
  P2 在 clone 里追加一枚改 `backend/app/config.py` 的 commit ⇒ 红，报
  `未登记的改动 ['backend/app/config.py']；被摘掉的例外 []`；
  P3 在 clone 里把 CORR-01 那枚文件还原成基线 ⇒ 红，报
  `未登记的改动 []；被摘掉的例外 ['backend/app/identity/__init__.py']`。
- 读数变化（都是实测量）：`EXPECTED_COLLECTED` **1335 → 1336**（+1 = 这枚新门），探针 `TOTAL 1336`，
  明细基线 `baseline/collected-node-ids.txt` 同步重生成 1336 行（`398913ffba87`）；门模块 **17 passed**。
  顺手补终审 Minor 8：常数上方注释原来只推导到 1332，现在写全
  `1332 = 1316+16 / 1335 = +3（CORR-01 三枚钉）/ 1336 = +1（本枚）`。
- 新锚（**取自工作树字节**，与 §11 同口径；`ci.yml` 在 index 侧是 LF-normalized 的另一个值，这层混用
  正是终审 Important 3 待裁的那件事）：`ci.yml` `1c706e165b73` → **`b84cb8bcaa10`**
  （152 CRLF / 0 bare LF —— plan §Step 1 那句「CRLF 数随新增行数上升、bareLF 必须仍为 0」在这里成立）；
  门文件 `5ac7220e6c55` → **`5ef3cc91a117`**（879 LF / 0 CR）。

### 11.3 锚口径改成 git blob（独立终审 Important 3，用户 2026-09-30 裁定开工）

**上面 §11 / §11.1 / §11.2 里所有 12 位锚取的都是「工作树原始字节的 sha256 前 12 位」，那是一台机器的读数**：
`* text=auto` 之下同一枚 commit 在 Windows 检出成 CRLF、在 Linux 检出成 LF，于是锚在两台机器上是两个数。
本节把锚的**规范口径**改成 **git blob 身份**，旧锚一律保留不删（它们是各时点的工作树读数，是历史）：

```bash
# 复现式（两端同值，与检出行尾无关）：
git rev-parse HEAD:<path>        # 提交树里那枚 blob
git hash-object -- <path>        # 工作树过 clean filter 之后 ⇒ CRLF 工作树也得到同一枚 blob
```

| 件 | 旧锚（工作树字节 sha256[:12]） | git blob 身份 |
| --- | --- | --- |
| `.github/workflows/ci.yml` | `1c706e165b73`（本机 CRLF 态）→ `b84cb8bcaa10` | **`5b5b75187d88`** |
| `backend/tests/test_ci_gate_contract.py` | `a0b9f37f32bb` → `893d59b4d74b` → `5ac7220e6c55` → `5ef3cc91a117` | **`c8076c18d030`** |
| `.gitattributes` | `c5d07b5dc438` → `b85430dbe6d1` | **`08affc389b70`** |
| `backend/tests/conftest.py` | `b0c5eee33ccd`（sha1 旧形） | **`b73a900b48c0`** |
| `backend/tests/test_secret_hygiene_contract.py` | `fd39d7d374f9` | **`0d2f82dbcf0e`** |
| `backend/app/identity/__init__.py` | `2cfab9f18182` | **`c96a778ed721`** |
| `backend/tests/real_llm_failover_kit.py` | `bc5c90c7616c` | **`77a0f2489456`** |
| `backend/tests/test_real_llm_failover_gate.py` | `1ecc82b411e1` | **`3073f8a158c5`** |
| `backend/tests/test_feishu_identity_contract.py` | `19394dbd78c6` | **`8bb57e24bb0e`** |
| `docs/evidence/…/manifest.json` | `c39a09f83b6a`（sha256 口径，仍是 P0 闸的外部锚） | **`af6db0a0c641`** |
| `baseline/collected-node-ids.txt` | `398913ffba87` | **`745e9ad012b8`** |

**为什么 manifest 那一枚不换口径**：P0 闸的 `PORTABLE_MANIFEST_SHA256` 钉的是 **sha256**，
那是判据本身而不是记账锚；它的工作树依赖已经被 `docs/evidence/** text eol=lf`（§7 L10）消掉，
所以留在 sha256 形是对的做法——改它等于动判据。

**B0 变异台同步换口径**（`.superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/ent_b0_mutations.py`）：

- `BASELINE_SHA1` → `BASELINE_BLOB`（四枚值取自已提交树，`git hash-object` 与 `git rev-parse HEAD:`
  逐字符相同），比对函数从「工作树原始字节 sha1」改成 `blob_id()`。旧 sha1 留在文件注释里当历史。
- needle 不再按本机行尾写：`LC(...)` 与 `L(...)` 同形（一律 LF），匹配与注入时由 `edits_for()`
  按目标文件自己的行尾适配。
- **双形态实测**（同一枚 needle 在 LF 与 CRLF 两种检出形态下的命中数，判据：两种都恰好 1）：
  N1–N8 八发全部 `BOTH-FORM-OK`（N6 是 `[1, 1]` 两枚编辑对，两种形态都对）。
- **这台子怎么自己把 bug 报出来的（要留案）**：第一轮重跑 `--check` 报 12/12 通过，真跑却 N2/N3/N4
  逐发 `TARGET-NOT-FOUND`、整轮 rc=1 —— 因为我改了注入路径却漏改主循环的命中预检，
  **同一判据两份实现**必然漂。修法是收敛成唯一实现 `anchor_counts(spec, text=None)`，两个入口都走它。
- **重跑读数**：`--check` 12/12（锚点 8 发 + git blob 身份 4 枚）；整轮 **8/8 `KILLED-ASSIGNED`、
  `BENCH_RC=0`**，还原四枚锚定件 `git hash-object == HEAD blob` 全等；
  台后复跑 `test_ci_gate_contract.py` + `test_secret_hygiene_contract.py` = **63 passed**。
  门 × 击杀溯源表本轮 17 枚里红 9 枚，`NEVER` 是真读数（含第 17 枚新门——它不在 B0 八发的射程里，
  它的三发证伪在 §11.2）。

**一条没做的事，不许含混过去**：真在 Linux 上跑一遍这台账**没有做**——本地 `python:3.12-slim` /
`python:3.13-slim` 无 git、`rag-backend:latest` 无 git 且无 pytest，而我不会擅自装系统依赖或拉新镜像。
所以「跨机可复现」当前的证据形态是**构造性**的（双形态锚点 + blob 身份与检出行尾无关 + `--check` 用
`git hash-object` 过 clean filter），不是"另一台机器实测过一遍"。要补那一格，需要一台带 git 的
Linux 环境或允许拉 `python:3.12` 全量镜像 —— 登记为待办，不写进结论。

**远端确认（run `36689505511` @ `fe65f08`，2026-09-30）**：`backend-contracts` **success、非成功步骤数 0**，
`1336 passed, 2 warnings, 1159 subtests passed in 55.02s`；SECA-20 子集 `5 passed, 41 deselected in 1.25s`。
两件事由这一格同时证成：① **`fetch-depth: 0` 是真的在起作用**——新门在 CI 里通过这件事本身就要求基线
commit 可解析，没有历史它必然哑红（P1 已实测那个红相）；② 重锚到 1336 之后 **B0-03 的"本地与远端逐位
相同"仍然成立**（本地两 cwd 与远端同为 `1336 / 1159`）。连续绿计数到这里是 **3/2**
（`2e4fccf`、`d1bab29`、`fe65f08`），其中只有第三枚带代码差。


### 11.4 变异台改成「按节点归因」（独立终审 Important 4，用户 2026-09-30 裁定开工）

终审这一条要的不是"台子跑没跑绿"，而是**台子有没有资格说它跑绿了**。旧形态有一处实质漏洞和两处
仪表缺陷：

1. **红因可以借位**。旧 `decide()` 拿哨兵字符串去**整轮** `--tb` 输出里找。P0 那台里
   `COLLATERAL` 那枚探针会把 problems 全集印出来 ⇒ 别的节点替这一发"红了"也能被记成杀对。
   新形态先切块（`failed_reasons()` / `failure_blocks()`：从 `=== FAILURES ====` 切到
   `=== short test summary info ====`，块头必须含 `test_…` 才算），哨兵只许落在
   **这一发点名的那枚节点自己的块**里；块取不到判 `KILLED-NO-BLOCK`，块里没有哨兵判
   `KILLED-WRONG-REASON`。这两枚新状态是**不通过**，不是换个说法通过。
2. **恒真条件**。P0 台核对"被删掉的文件真的没了"那行旧写 `(not path.exists() or True)`，
   恒真 ⇒ 这一支从来没核过任何东西。改成 `restored_ok = restored_ok and (not path.exists())`。
3. **B0 八发压根没有 reason 哨兵**，"杀了"只等于"那枚红了"。现每发补 `"reasons"` 表，
   哨兵里的计数不写死：`{EC}` / `{EC-3}` / `{EC-1}` 由 `expected_collected()` 现读门模块，
   门册也改成现读 `^def (test_\w+)`。**理由同 §4：抄一份清单就会漂，而漂掉的清单正是这台子要抓的病。**
   台账分组键也改成 `verdict.split("-RESTORED")[0]`，否则 `KILLED-WRONG-REASON-RESTORED-OK`
   会被归进新类，"N 发全杀"那行当场失真。

**台子在这一轮里抓的是我自己**，三件都留案：

- 块头正则我第一版写死 `^_{3,}` ⇒ P0 十四发**全判 `KILLED-NO-BLOCK`**（pytest 对长节点名只补 1 枚
  下划线）。放宽后又让 pytest 的 `_ _ _ _` 分隔线自己成了块头，切在断言行之前 ⇒ 块里没有 E 行。
  终版要求块头含 `\btest_\w+`。**这两次都是仪表拒绝认证，而不是放过**——形状是对的。
- N6 的哨兵我按"index 面"的印象猜写，实测真红因是 `git ls-files` 跟踪面为空，台子当场判
  `KILLED-WRONG-REASON`。回去读这发的规格抬头（§6.4 覆盖度钉的**空判地板**）才把两枚节点的哨兵
  改成 `跟踪面一枚都没有`。**变异台这一发的靶子不是产品，是我的归因。**
- 改坏的部分（删掉 `SUCCESS_VERDICT`、`gate_name()` 两枚 `NameError`，以及 heredoc 里 `\n` 被吞
  导致 f-string 未终结）都由"跑一遍"当场炸出，没有逃到读数里。
- **正则两处改完先拿已存盘的旧 dump 离线复算**（P0 14/14 全部落进自己节点的块、N6 那块捞出地板句），
  确认解析器之后才花正式轮。

**正式轮读数**（全文落盘在 `.superpowers/sdd/ENTERPRISE_B0_PLAN/tmp/`，该目录不进交付面）：

| 台 | 落盘 | 判决面 | rc |
| --- | --- | --- | --- |
| B0 八发 | `b0-bench-official-2026-09-30.txt` | **8/8 `KILLED-ASSIGNED`**，逐发红因均在自身块内；八发还原全 `sha1 同 + cmp rc=0`；17 枚门本轮观测红 9 枚，`NEVER` 为真读数 | `B0_RC=0` |
| P0 十四发 | `p0-bench-official-2026-09-30.txt` | **14/14 `KILLED-ASSIGNED-RESTORED-OK`**；M1–M5 逐枚模型串、M6–M9 `[I1]/[I2]/[I6]/[I7]`、N1–N4 `[T-彩排]/[T-收尾]/[T-传输层]` 全部命中各自块；park 目录已删 | `P0_RC=0` |

**台后门禁与零残留**：`ent_b0_mutations.py --check` **12/12**（锚点 8 发 + 4 枚 git blob 身份全等）；
`git diff --name-only` 只剩两台北方脚本与用户自己的 `backend/app/identity/README.md`
（`test_real_llm_failover_gate.py` 是 stat-dirty，`git diff` 为空 ⇒ 内容 == HEAD blob）；
`test_ci_gate_contract.py` + `test_secret_hygiene_contract.py` = **63 passed**；
全量套件两 cwd 各一遍 = **1336 passed / 36 warnings / 1159 subtests**
（`backend/` cwd 255.98s，仓库根 cwd 248.24s）。

**§11.3 那一条仍然挂着**：Linux 上重跑这两台子**没做**（本地没有带 git 的可用镜像，我不擅自装系统
依赖）。本节所有读数都是**一台 Windows 机器**上的读数；跨机性靠的是"blob 身份与检出行尾无关"这一
构造，不是第二次实测。

**远端确认（本节这枚 commit 自身的 run）**：待补——按 §11.2/终审裁定，per-run GREEN 不能由前一枚
commit 代持，所以这一格必须等本轮 push 之后那一趟 CI 回来才写。

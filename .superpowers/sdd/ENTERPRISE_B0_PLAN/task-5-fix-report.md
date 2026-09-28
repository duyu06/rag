# B0 Task 5 修复轮报告（R15 裁定的落地 · R16 订正的同批处置）

出处 = `progress.md` 的 **R15**（用户裁定：容器格那三枚红**在 B0 内修，按"只改 `backend/tests/**`"的口径**）
与 **R16**（评审两条 Medium：归因错库 + "B0 修不了"这句是错的）。
本文件记的是修复轮本体；Task 5 的量测原文仍在 `task-5-report.md`（本批只在那里就地订正，不删原读）。

---

## 0. 范围与纪律（先划边界，再动手）

| 项 | 本批的动作 |
| --- | --- |
| 允许触碰 | `backend/tests/test_password_lifecycle_contract.py`、`backend/tests/test_real_llm_failover_gate.py`、Task 5 报告与本台账、工作区档（`evidence/`、`snap-task5-fix-post/`） |
| 未触碰 | `backend/app/**`、`backend/requirements.txt`（§10.2 真源）、`.github/workflows/ci.yml`、`.gitattributes`、`backend/tests/test_secret_hygiene_contract.py` 与其 `EXEMPTIONS`、`backend/tests/test_ci_gate_contract.py`（含 `EXPECTED_COLLECTED = 1332`） |
| git 写操作 | **零**：无 add / commit / push / stash / checkout / restore / clean / config。工作树开工 8 行、收工仍是 8 行（见 §6 自证） |
| 弱化 | 无：没有新增 skip / xfail / "不在场就算过"分支，没有改任何一个期望值。白名单条目**一条都没加**（见 §1.6） |
| 探针落点 | 全部在仓外：`%LOCALAPPDATA%/Temp/b0-t5-r15/`（宿主）与容器内 `/tmp/`（`/w` 之外）。仓库里没落任何合成件 |

三枚红的处置与 R15 一一对应：修 1 = 红 1 + 红 2（枚举对新版 FastAPI 的嵌套路由对象失明），
修 2 = 红 3（判据依赖一枚 gitignored 过程件——本批**只把失败做成可诊断**，判据一分不松），
修 3 = R16 点名的两处归因错库与一句错框。另有一项"登记不修"（警告数 36 vs 2）在 §4 落回结论。

---

## 1. 修 1 —— 路由枚举改为**递归展开**（不是过滤掉 `_IncludedRouter`）

### 1.1 机理复核：确认 R16 的归因，并**上调一处被低估的规模**

R15 已把这条符号归到 **FastAPI**（`fastapi/routing.py` 的私有 `_IncludedRouter`）而非 Starlette。
本批在两侧各复核一次（同一枚仓外只读探针 `enum_diff_probe.py`，裸档 `evidence/t5fix-r15-container-enum-probe.txt`）：

| 读数 | 宿主 | 容器 `rag-backend:security-a-rc1` |
| --- | --- | --- |
| `python` / `fastapi` / `starlette` | 3.13.7 / **0.135.3** / 1.0.0 | 3.12.14 / **0.141.1** / 1.7.0 |
| `hasattr(fastapi.routing, "_IncludedRouter")` | **False** | **True** |
| `hasattr(starlette.routing, "_IncludedRouter")` | False | **False** |
| `sorted({type(r).__name__ for r in app.routes})` | `['APIRoute', 'Route']` | `['APIRoute', 'Route', '_IncludedRouter']` |

⇒ 符号只随 **fastapi** 出现、随 starlette 无关：R16 的归因成立（宿主两 False、容器只在 fastapi 侧为 True）。
**修复者按 fastapi 找包。**

**规模订正（本批新读数，比 Task 5 记录的更严重）**：容器顶层 29 枚条目 =
`APIRoute × 21` + `Route × 4` + **`_IncludedRouter × 4`**，那 4 枚 include 条目背后的子表分别是
**4 / 7 / 2 / 14 = 27 条**路由。旧走法（只走顶层 `APIRoute`）在这格只枚举到 **15** 条已认证端点、
**21** 条总服务面，而真表是 **42 / 48**——
即"顶层枚举 = 全部服务面"这个前提失效时，**盲区是 27 条腿（占全部 48 条的 56%），不是 5 条**。
Task 5 记的"漏 5 条"是 `MUST_BE_COVERED` 那 8 枚**点名腿**里被探针抓到的 5 枚（判据只报被点名的差集），
真实覆盖面塌得比那句话宽得多。这条按"加重"登记进 §7 台账。

### 1.2 改了什么（工作树形状，函数级）

文件 = `backend/tests/test_password_lifecycle_contract.py`。核心是把"清单从哪来"从**顶层扫描**换成**整棵树深度优先展开**：

- `_child_nodes()`（`:165`）：认三种只读形状——① `effective_candidates()`（新版 include 的**生效**子条目，
  路径已含前缀）、② `original_router.routes`、③ 任何自带 `.routes` 的 router。
  `Mount` / `Host` **不展开**（它们的子路径相对挂载点，拼出来的 `"METHOD path"` 是盘上不存在的假腿——
  那种形状仍由判据判红，而不是被递归"支持"掉）。
- `_walk_surfaces()`（`:198`）/ `_service_surfaces()` / `_walk_nodes()`（`:241`）：摊平成
  `{route, path, methods, dependants, node}` 清单；`_walk_nodes` 把容器自己也算进去，供"树里有没有走不进去的形状"那问用。
- `_route_index()`（`:261`）：覆盖面清单改取递归展开后的条目（这就是红 1 的那枚漏腿口）。
- `_resolve_dispatch()`（`:306`）+ `_dispatched_route()`：**派发侧同步递归**。include 条目自己会 FULL 命中，
  真跑业务的是它里面那枚 `APIRoute`；派发不展开的话，"我遍历的树 == 执行器跑的树"那句核对会拿容器去比叶子。
- `_route_dependants()`（`:366`）+ `_arm_tripwire()`：新版 include 会给同一枚端点**另建**生效 dependant，
  只把 `route.dependant.call` 换成桩**拦不住真调用**——那正是本文件最不肯要的失败形状
  （"覆盖面是假的而破坏是真的"）。于是绊线按 `_route_dependants()` 逐枚上、逐枚还原。
  宿主旧形状下这里只有一枚，逐位等于改前行为（§1.4 的"两侧完全相同 = True"就是这件事的证据）。

**"为什么这里递归而不是过滤"已按 §10.3 第 2 类落在测试旁边**（`:159-164` 的块注释，原文摘要）：

> 为什么这里是**递归展开**而不是"把看不懂的顶层条目过滤掉"（§10.3 第 2 类：断言写死了本机形态）：
> 新版 FastAPI（`fastapi/routing.py` 的 `_IncludedRouter`，**不是** Starlette）让 `include_router()`
> 在顶层只挂一枚指回子路由表的条目、不再把子表复制上来，于是"顶层 `app.routes` 就是全部服务面"
> 这个前提已经假了；把它过滤掉等于继续假装前提为真，覆盖面塌一块而门照样绿。
> 递归只可能让清单变宽（宿主的旧形状下逐位等，见 B0 修复报告）。

理由记在 helper 头上而不是只记在报告里，是因为本项目的历史教训：**一条裸 `isinstance` 过滤过一阵就会被
"顺手简化"回去**。判据旁边没有理由，等于没有理由。

### 1.3 判据强度核对（只增不减，且新增了三枚反放宽钉）

R15 明令"不许过滤、不许白名单化"。本批没有任何一处把 `_IncludedRouter` 当噪声丢掉：

| 判据 | 改前 | 改后 | 方向 |
| --- | --- | --- | --- |
| `test_the_enumeration_sees_every_service_surface` ① | 顶层出现挂载点或有 `.routes` 的条目即红 | 递归**走不进**的容器（`Mount` / `Host`，含 `Host` 这一族改前根本没查）一条都不许有 | 换形不失：容器不再算异常，但走不进去的形状仍红，且多认了 `Host` |
| 同枚 ② | 顶层非 `APIRoute` 条目不许带服务面 | 递归展开后的**叶子**里非 `APIRoute` 的只许是文档面（不挂依赖、不在 `/api/` 下） | 同强，判的是叶子 |
| 同枚 ③「只增不减」钉 | 无 | `top_level - recursive` 必须为空 ⇒ 递归反而少看见一条腿就红（`:1212`） | **新增** |
| 同枚 ④ 独立 oracle | 无 | `app.openapi()` 的每条 operation 必须出现在递归清单里（`:1218-1226`） | **新增**（库自己那张表，两边同时漏也点得名） |
| `test_no_route_is_registered_with_several_http_methods` | 只看顶层 | 看递归全表 ⇒ include 子表里长多方法路由同样红 | 变强 |
| `test_the_method_alphabet_sees_every_registered_verb` | 只看顶层 | 看递归全表 | 变强 |
| `MUST_BE_COVERED` / `MUST_NOT_BE_COVERED` / `WHITELIST` / `PARAM_SAMPLES` | 常量 | **一字未动** | 等 |
| 覆盖面用例的 403 + 中文文案 + 绊线 + 审计笔数 | 判 `authenticated - pending` | 同一套判据，集合按递归枚举给出 | 等（且扫的腿变多） |

另：`_route_index()` 在"生效条目"形状下把 `route.dependant` 与 include 重建的那枚**一起**过依赖树，
所以覆盖面判定不因换形而漏判；测试**枚数**没变（改的是函数体，不是 `def test_`）。

### 1.4 宿主读数：改前 / 改后**逐位相同**（证明没动宿主形态）

同一进程里把两份模块各当一枚独立模块加载（HEAD 那份从仓外副本 `lifecycle-head-copy.py` 加载，
工作树那份从 `backend/tests/` 加载），跑同一条 `authenticated = 索引(require_user) ∪ 索引(require_permissions)`：

```
sorted({type(r).__name__ for r in app.routes}) = ['APIRoute', 'Route']
顶层 app.routes 条目数 = 52     顶层里 APIRoute 的条数 = 48
递归走到的条目总数（含容器自己） = 52     递归展开后的服务面条目数 = 52
旧走法 authenticated 条数 = 42
新走法 authenticated 条数 = 42
新 >= 旧（条数不减）      = True
旧 ⊆ 新（超集关系）       = True
新 \ 旧（递归多看见的腿）  = []
旧 \ 新（必须为空=放宽）   = []
两侧完全相同（宿主形态）  = True
免门腿集合相同            = True     # ['GET /api/auth/me', 'POST /api/auth/password/change']
OpenAPI operations 条数 = 48  递归清单全量腿数 = 48  顶层清单全量腿数 = 48
OpenAPI \ 递归（盲区） = []   OpenAPI \ 顶层（旧盲区） = []
```

⇒ 宿主的顶层形状里**根本没有可展开的容器**（`_walk_nodes` 走到的条目数 == 顶层条目数 == 52），
所以递归在这里是恒等变换：覆盖面、免门集合、动词表、派发核对全部逐位不变。
"改完宿主就换了行为"这一族风险被这组数直接否掉。

### 1.5 容器读数（fastapi 0.141.1）：两条红门转绿，5 条点名腿回归

同一枚探针在容器里跑（裸档 `evidence/t5fix-r15-container-enum-probe.txt`）：

```
python 3.12.14 / fastapi 0.141.1 / starlette 1.7.0
_IncludedRouter 在 fastapi.routing 里? = True    在 starlette.routing 里? = False
sorted({type(r).__name__ for r in app.routes}) = ['APIRoute', 'Route', '_IncludedRouter']
顶层条目数 = 29（APIRoute 21 / Route 4 / _IncludedRouter 4）  递归走到条目数 = 56  服务面条目 = 52
旧走法 authenticated 条数 = 15
新走法 authenticated 条数 = 42
新 >= 旧（条数不减）      = True
旧 ⊆ 新（超集关系）       = True
旧 \ 新（必须为空=放宽）   = []
MUST_BE_COVERED 条数      = 8
旧走法漏掉的点名腿        = 5 条（下表）
新走法漏掉的点名腿（须空）= []
免门腿集合相同            = True
OpenAPI operations 条数 = 48  递归清单全量腿数 = 48（顶层清单只有 21 条）
OpenAPI \ 递归（盲区） = []
```

**被顶层枚举吞掉、现在重新看见的 5 条点名腿**（就是 Task 5 那枚"漏 5 条"的真身）：

1. `POST /api/conversations/{conversation_id}/messages/stream`
2. `POST /api/agent/query`
3. `POST /api/agent/query/stream`
4. `PATCH /api/conversations/{conversation_id}`
5. `GET /api/auth/users`

递归在容器里多看见的是 **27** 条腿（4 枚 include 条目背后的 4+7+2+14），上面 5 条只是
`MUST_BE_COVERED` 探针能点到的那一小部分；另 22 条（`/api/conversations*`、`/api/evaluation/*`、
`/api/feedback`、`/api/search`、`/api/chunks`、`/api/ingestion/jobs`、`/api/operations/usage`、
`/api/system/status`、`/api/tools`、`/api/access/requests`、`/api/documents/{action}`、
`POST /api/conversations/{conversation_id}/messages{,/{message_id}/retry[/stream]}` 等）
在旧走法下**既不过门也不被任何人扫到**——那才是这条缺陷的真实代价。

**跨版本等值**这一句是本枚修复的判据本体：递归清单在两个容器（0.135.3 / 0.141.1）里给出
**同一张表**（48 条全量腿、42 条已认证、免门 2 条），而"只走顶层"那侧一个给 48、一个只给 21。
枚举不再随库的内部对象形状漂 ⇒ §10.3 第 2 类点名的"断言写死本机形态"被解除，而不是被绕过。

复跑（`evidence/t5fix-r15-container-two-modules.txt`，形态与 Task 5 容器格同源：
tar 交付面 318 枚 + `.git` → `docker cp` 解到 `/w`，**不用** bind mount；`bash -lc 'cd /w && …'` 绕开 MSYS
把 `-w /w` 折成 `W:/` 的那枚坑；镜像依赖零重装，只补 `pip install pytest` ⇒ `pytest 9.1.1` 与宿主同版、
`apt-get install git` ⇒ `git 2.47.x`；`backend/.env` 与 `.superpowers/` 过程件天然不在场）：

```
fastapi 0.141.1 starlette 1.7.0 pyjwt 2.15.0 pytest 9.1.1
--- 两枚受影响模块 ---
1 failed, 91 passed, 23 subtests passed in 56.64s      ← 唯一那枚 failed = 修 2 的 P0 门（预期仍红）
--- 收集钉 ---
1332 tests collected in 27.65s                          ← 与宿主同数，EXPECTED_COLLECTED 未被触碰
```

⇒ Task 5 容器格里那两条 `MustChangeGateCoverageTests` 红（
`test_every_authenticated_route_is_gated_or_whitelisted`、
`test_the_enumeration_sees_every_service_surface`）**现在绿**：91 枚通过里含这两枚所在模块的全部 77 枚。
真 HTTP 扫描在 0.141.1 上把 42 条腿逐条打出 403 + 中文文案、绊线零响、审计笔数与扫过的条数相等——
这条不是"枚举数对了"就完事，它要求**每条都能上桩且拦得住真调用**，
所以 `_resolve_dispatch` / `_route_dependants` 那两处递归是被判据亲自验过的。

### 1.6 白名单：一条都不需要新增

R15 要求"若递归后白名单需要新增条目 ⇒ 停下报告"。**不需要**：

- 走 `require_user_pending_password` 的端点集合在两侧、两种走法下都是同一对
  `{GET /api/auth/me, POST /api/auth/password/change}`（探针里"免门腿集合相同 = True"，四格一致）。
- `WHITELIST` 常量一字未动；`test_every_authenticated_route_is_gated_or_whitelisted` 里
  `assertEqual(set(WHITELIST), pending)` 在容器格绿。
- 递归多出来的 27 条腿**全部落在门那一侧**（`MUST_BE_COVERED ⊆ authenticated`、
  `MUST_NOT_BE_COVERED ∩ authenticated = ∅` 同场成立），没有一条需要开免门豁免。

---

## 2. 修 2 —— 让那枚红**可诊断**（判据一字未改）

### 2.1 边界：为什么只动文案，以及前一版在飞做法的处置

R15 的裁定是三头都不许动：矩阵的 `GREEN` 是 V2.3 的**真实结论**（改成 `BLOCKED` = 伪造一次结论）、
门要求"证据在场"是**正确判据**（去掉它 = 放宽）、把过程件送上交付面**要用户显式授权**（本批零 git 写操作）。
所以本批的唯一动作 = 把失败文案从"指着矩阵"修成"指着那枚不在交付面上的件"。

**在飞做法的处置（本批的一处回退，须记账）**：开工时工作树里的
`test_real_llm_failover_gate.py` 已被上一轮改判过据——把证据源从 `kit.EVIDENCE_FILE`
**改绑到已跟踪的验收文档** `docs/MODEL_ROUTER_V23_ACCEPTANCE_2026-09-24.md §4`
（本机 JSON 在场时仍全套校验并与文档互锁；不在场时只按文档声称判）。
它的自证台做得很细（四枚变异 + 互锁，`evidence/t5fix-proof-2-raw.txt`），但**形状本身就是 R15 明令不许的那种**：
它让"证据件缺席"这一格从红变绿，也就是把"证据必须在场"这条正确判据换成了"交付面文档自述成立"——
一份可手写的 markdown 表拿掉了 `validate_evidence` 里最硬的那枚反造假装置（逐枚重算 sha1）。
本批按裁定**把该文件还原到 HEAD**（还原前后 sha 逐位记在 §6），只保留文案改动；
被替换的那份留在 `.superpowers/sdd/ENTERPRISE_B0_PLAN/tmp/t5fix-superseded-doc-anchor_test_real_llm_failover_gate.py`
供 controller 复看，**没有**留在交付面上。

改动清单（`git diff HEAD` 口径 = `+73 / -1`）：

- `:394` `REPO_ROOT` / `:398` `GITIGNORE_FILE` 两枚常量。
- `:401` `_ignored_face_hint()`：现算这枚文件被 `.gitignore` 的**哪一条、第几行**挡住。
  只读 `.gitignore` 文本、按字面形状匹配（目录规则看路径分量、文件规则看整体与文件名），
  命中不了就如实说"未被命中"。**不派 `git check-ignore` 子进程**——断言的 msg 是先算好再交给
  `assertEqual` 的，这里冒一个异常会把"红"变成"error"，现场比现在更难读。
  也不写死"它被 .gitignore 挡着"这句话：规则改了，写死的那句就成了第二条误导。
- `:431` `_evidence_absence_note()`：只在 `read_error == "missing"` 时多说话（其余形状——
  文件在场但内容不合格——文案与改前一字不差，不把两种病混成一句话）。
- `:487` 断言的 `msg` 末尾拼上这段。**期望值、比较方向、`if evidence is None or problems` 那条判定、
  两处 `return` 全部原样保留**；没有 skip、没有 xfail、没有"不在场就放过"分支。
- 附带一枚 `import fnmatch`（标准库，不动 `requirements.txt`）。

### 2.2 新文案与两枚现场

同一枚用例、两种格，读到的东西：

**A. 干净 checkout 形态（容器 / CI 第一现场）**——把过程件挪到仓外后在宿主跑（`-q`，rc=1）：

```
FAILED backend/tests/test_real_llm_failover_gate.py::P0MatrixStatusLockedToEvidenceTests::test_p0_row_status_matches_the_evidence
AssertionError: 'BLOCKED' != 'GREEN'
- BLOCKED
+ GREEN
 : P0 还没跑过真机（证据：missing），矩阵那一行却写着 'GREEN'。唯一合法取值是 'BLOCKED'——改状态之前请先跑 .superpowers/scripts/run_p0_failover_acceptance.sh

 —— 这一格缺的不是矩阵那一行，是那枚没进交付面的过程件 ——
 - 证据件路径：E:\xiangmu\rag\.superpowers\sdd\MODEL_ROUTER_V23_PLAN\task10\real-llm-failover-001.json（仓库相对 `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json`）
 - 本轮读取结果：'missing' —— 文件根本不在场（不是内容不合格）。
 - 它命中 `.gitignore:25` 的 `.superpowers/`——整目录不进交付面；⇒ 干净 checkout（CI / 发布容器）里它**必然**不在场，本机才在场。
 - 所以本行在干净 checkout 里是**不可判**，而不可判 ≠ 已通过：判据照旧要求 'BLOCKED'，本枚照旧红。
 - 出路不是改矩阵（把 GREEN 写成 BLOCKED 等于伪造 V2.3 的真实结论），而是让证据上交付面：把上面那枚 JSON 以 `git add -f` 精选入库（B0 计划 Task 7 的 staging 段已登记，需用户明确授权后才能提交）。
 - 想要本机复算这份证据：跑 .superpowers/scripts/run_p0_failover_acceptance.sh。
```

同一枚用例在**容器格**里给出的也是这段话（路径为 `/w/.superpowers/…`，见
`evidence/t5fix-r15-container-two-modules.txt`）⇒ 诊断不依赖宿主盘符，`.gitignore:25` 那一格是现算出来的，
在 Linux 侧同样指得准。

**B. 本机正常形态**（过程件在场，宿主）：该枚**照旧绿**，模块 15 枚全绿——
文案改动没有任何一次走到那分支，判据强度与改前一致：

```
backend/tests/test_real_llm_failover_gate.py          15 passed, 11 subtests passed   rc=0
```

挪动过程件的手法按 R15 的告诫执行：**整枚文件 `mv` 到仓外**（宿主 `%TEMP%` 副本 + 原位改名），
**没有**在树内改名或复制——树内的副本会落进 SEC-A 的扫描面（`git ls-files --others --exclude-standard`
那 318 枚里），把两枚不相干的门染红。跑完 `trap` 还原并核 sha：
`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json`
还原前后同为 `2ec6460041da94b25d937e3a3b494dc0b477835631d07c4cb268ee7dc1355c0a`。

### 2.3 判据没被"说"过去：反证一次

新增的 `_ignored_face_hint()` 只是文案，但文案自己也可能说谎（说"被 .gitignore 挡着"而其实没挡）。
四枚反证（宿主只读，裸档 `evidence/t5fix-r15-p0-message-branches.txt`）：

```
未被忽略的面 : 未被 `.gitignore` 命中（那它本就该随仓库一起交付）      ← 指 docs/MODEL_ROUTER_V23_MATRIX.md
被整目录忽略 : 命中 `.gitignore:25` 的 `.superpowers/`——整目录不进交付面  ← 指那枚证据件
仓外路径     : （C:\Windows\win.ini 不在仓库内 ⇒ 谈不上被仓库的忽略规则挡住）
note(None / 'unparsable: …') 返回 : ''                                ← 在场但不合格的两种形状文案一字未变
```

⇒ 这段话只在"真缺失 + 真被忽略"时出现，且说的是那枚路径与那条规则本身；
`git check-ignore` 那格是**现算**的（第 25 行、`.superpowers/`），规则改了它跟着改，不会变成功劳簿上的假话。
不合格但不缺失的形状（`unparsable`、十枚判据任一桩不上）**沿用 HEAD 原句**，
不把两种病混成一句话——那也是一种造假形状。

---

## 3. 修 3 —— Task 5 报告的升级文案订正（就地、不删原读）

`.superpowers/sdd/ENTERPRISE_B0_PLAN/task-5-report.md` 三处（R16 点名的两处归因 + 一处错框）：

| 位置 | 原文（保留可见） | 订正 |
| --- | --- | --- |
| `§10.3 归因` 第 317 行段 | "⇒ 新版 **Starlette** 在顶层 `app.routes` 里多挂了 `_IncludedRouter` 条目" | "⇒ ~~新版 Starlette~~ **新版 FastAPI**（`fastapi/routing.py` 的 `_IncludedRouter`）…"，并补两侧 `hasattr` 复核读数（宿主两 False、容器仅 fastapi 侧 True）与"修复者按 FastAPI 找包"一句 |
| `关注点` 第 1 条 | "两枚覆盖面门对 **starlette 的对象形状**敏感" | "对 ~~starlette 的对象形状~~ **fastapi 路由对象形状**敏感"，并标"这一枚已在 B0 的修复轮里按 §10.3 第 2 类改掉（只改测试）" |
| `§10.3 归因` 第 321 行段 | "**B0 修不了**：requirements 是真源…而按 §10.3 第 2 类改测试需要说明与评审，本任务的约束是不编辑其他测试，故只登记" | "**本任务修不了**（约束 = 不编辑其他测试）"，并写明原文错在哪：§10.1 把 `backend/tests/**`（既有）明列为 B0 靶区、§10.3 第 2 类点的正是"断言写死了本机形态"这一族；错框会把这两枚挂到第 1 类（依赖形态，最不可操作的一格）从而在后续被当成"B0 之外的事"绕开 |
| 同节抬头（额外一处） | "红 1 + 红 2 —— 依赖解析版本差（**§10.3 第 1 类：依赖形态**）" | 保留原文并加"【订正 R16 / M-2 · 修复轮 B0-T5-fix】"批注块：可操作类别是**第 2 类**，两枚已在 B0 内修掉，指向本文件 |

订正全部以 `~~删除线~~ + **加粗订正** + 批注块`的形态就地落，原读一字不删——本项目记自己的勘误，
不做无痕改写（R16 明令）。同节里"性质"那条对 requirements 开区间风险的描述**保持原样**，
因为它是对的（本批确实没动 `requirements.txt`，区间仍是 `<1`）。

---

## 4. 登记不修 · 但已判定：警告数 36（宿主）vs 2（容器）**不是** PyJWT 版本差

Task 5 的评审怀疑第二枚未上界漂移是 `PyJWT 2.12.1`（宿主）↔ `2.15.0`（容器）。
本批用三步把它判掉，全程只花了几枚单文件运行，没重跑容器整格。

**第一步 · 把两格的警告拆到同类**（宿主数取自 `evidence/t5-step2-cell1-root-withenv.txt`，
容器数取自 `evidence/t5-step35-container-cell.txt:105-112`）：

| 警告族 | 宿主 | 容器 |
| --- | --- | --- |
| `jwt/api_jwt.py:147 InsecureKeyLengthWarning`（encode 腿，"HMAC key is **31 bytes** long"） | 14 | 0 |
| `jwt/api_jwt.py:365 InsecureKeyLengthWarning`（decode 腿，同一句） | 20 | 0 |
| `conftest.py:404 RuntimeWarning`（ledger-guard 改道提示） | 2 | **2** |
| 合计 | **36** | **2** |

⇒ 差值 34 **整族**是 PyJWT 的短密钥警告，两格共有的是那 2 枚 conftest 提示。

**第二步 · 容器里的 PyJWT 到底还发不发这句**（同版实测，非推断）：

```
pyjwt 2.15.0 -> warnings: [('InsecureKeyLengthWarning', 'The HMAC key is 16 bytes long, …'),
                           ('InsecureKeyLengthWarning', 'The HMAC key is 16 bytes long, …')]
```

2.15.0 照发。于是要问的不是"版本改了警告没有"，而是"这句在什么长度上才发"。

**第三步 · 真正的自变量是 `settings.jwt_secret` 的字节长**：

| 格 | `JWT_SECRET` 来源 | `settings.jwt_secret` 长度 | 单跑 `test_feishu_identity_contract.py` 的警告数 |
| --- | --- | --- | --- |
| 宿主 | 这台机器**shell 环境**里真有一枚 `JWT_SECRET`（31 字节；与 `backend/.env` 无关——那 44 个键名里根本没有它） | **31** | `103 passed, 6 warnings` |
| 容器（干净 checkout） | 未设 ⇒ 落回 `backend/app/config.py:164` 的出厂默认 `"change-me-…-demo-secret"` | **45** | `103 passed`（**0** 枚警告） |
| 容器 + 合成 31 字节 `JWT_SECRET` | 现场注入（值不外泄，取 `"a"×31`） | **31** | `103 passed, 6 warnings` ← **与宿主同数** |
| 容器 + 合成 45 字节 `JWT_SECRET` | 现场注入 | **45** | `103 passed`（0） |

⇒ **因果闭合**：同一枚 PyJWT 2.15.0 在同一枚容器里，只换密钥长度就在 6 ↔ 0 之间来回，
宿主那 34 枚警告被完整解释。阈值是 PyJWT 对 HS256 的 32 字节建议下界——31 越界、45 不越界。

**结论与登记（不改代码）**：
1. 评审的"第二枚未上界漂移导致警告数掉档"**不成立**为*原因*；`PyJWT 2.12.1 ↔ 2.15.0` 是**真实存在**的
   区间漂移（两侧同装一份 `requirements.txt` 的开区间、各在一天的解析结果），但对本格读数**无影响**。
   它仍该留在 §10.2 那张"依赖区间"账上（B0 不许动 `requirements.txt`），归 B1/依赖政策那一族。
2. 被 repo 当成回归信号的**警告数不是跨格可比的量**：它随量测环境的 `JWT_SECRET` 长度跳变 34 枚。
   Task 7 的远端格几乎必然读到 **个位数**警告（runner 环境不会带上谁本机那枚 31 字节 secret）。
   **建议**：远端判据要么把警告数**按格内自比**（同一 job 内前后差），要么在 job 里显式声明
   `JWT_SECRET` 的长度档位再钉数——否则"36 变 2"会被当成一次回归而误判。**这一条只登记，本批不动手**
   （改 `ci.yml` 越出本批白名单，且属 Task 7 的远端往返范围）。

---

## 5. 复跑读数汇总（R15 要求逐条贴的三张表）

### 5.1 两枚受影响模块 · 宿主（cwd = 仓库根，`backend/.env` 在场，过程件在场）

```
backend/tests/test_password_lifecycle_contract.py   77 passed, 12 subtests passed   rc=0
backend/tests/test_real_llm_failover_gate.py        15 passed, 11 subtests passed   rc=0
```
枚数与 Task 5 基线一致（本批改的是函数体与文案，没有增删 `def test_`）。

### 5.2 容器格（`rag-backend:security-a-rc1` · Python 3.12.14 · fastapi 0.141.1 · 无 `.env` · 无过程件）

```
两枚受影响模块：1 failed, 91 passed, 23 subtests passed in 56.64s
  FAILED …/test_real_llm_failover_gate.py::P0MatrixStatusLockedToEvidenceTests::test_p0_row_status_matches_the_evidence
  ← Task 5 那两枚 MustChangeGateCoverageTests 红：已绿（91 枚通过含 lifecycle 全部 77 枚）
  ← 唯一剩下的这枚红 = 修 2 的"预期仍红"，且带 §2.2 那段可诊断文案
收集钉（全量 --collect-only）：1332 tests collected in 27.65s
```

### 5.3 全量套件 · 宿主两 cwd + 一格"干净 checkout 模拟"

| 格 | cwd | 过程件 | 读数 |
| --- | --- | --- | --- |
| A | 仓库根 | 在场（本机实况） | `1332 passed, 36 warnings, 1133 subtests` rc=0 |
| B | `backend/` | 在场（本机实况） | `1332 passed, 36 warnings, 1133 subtests` rc=0 |
| C（模拟） | 仓库根 | **挪到仓外** | `1 failed, 1331 passed, 36 warnings, 1133 subtests` rc=1 |
| D（模拟） | `backend/` | 挪到仓外（只跑该枚） | 同一枚 `1 failed` ⇒ 该判据与 cwd 无关（`kit.EVIDENCE_FILE` 由 `__file__` 锚死，不随 cwd 漂） |
| 容器 | `/w` | 天然不在场 | 两枚模块 `1 failed / 91 passed`；收集 1332 |

⇒ **对 R15 那句"expected 1331 passed / 1 failed"的正面回答**：这一格在**任何**拿不到那枚
gitignored 过程件的树上都是 `1331 / 1`（C、D、容器三格同形）；本机过程件在场时是 `1332 / 0`（A、B）。
**没有**找到"第三条让它合法变绿的路"——上一轮那种"改绑证据源"的做法能在干净 checkout 里凑出 1332/0，
但它换掉的正是那条正确的判据（§2.1 已回退）。出路是 Task 7 的 staging 那次提交，不是测试侧的巧劲。
（A/B 的耗时 424.76s / 440.76s 比 Task 5 的 204–211s 大，是本轮容器与宿主复跑**并发**占 CPU 所致；
耗时不是本批判据，登记以免被误读成回归。）

### 5.4 不许动的东西（锚点核对，脚本 `anchors.py`，输出 `evidence/t5fix-r15-anchors.txt`）

```
MATCH  .gitattributes                       c5d07b5dc438   (Task 4 钉)
MATCH  .github/workflows/ci.yml             1c706e165b73   (Task 4 fix1 钉)
MATCH  backend/tests/test_ci_gate_contract.py 73bede2def2e (Task 4 fix1 钉)
       EXPECTED_COLLECTED = 1332            （一字未动，门模块 sha 未变 ⇒ 必然未动）
       backend/requirements.txt             beea80c42159（不在 git status 面 ⇒ 与 HEAD 同字节）
       backend/tests/test_secret_hygiene_contract.py fd39d7d374f9（同上：豁免表零新增）
       backend/tests/real_llm_failover_kit.py         c83936cf78aa（判据真源未动）
       本批改的两枚：test_password_lifecycle_contract.py dd8a61adac67 / 115009 B
                     test_real_llm_failover_gate.py      bf1a6a85cba3 /  33563 B
app 面三子句：git diff HEAD -- backend/app = 两枚 identity，减去后为空 ✓
              git diff --cached --name-only = 空 ✓（零暂存、零提交）
门模块 / SEC-A 单跑：16 passed / 46 passed（宿主，rc=0）
```

---

## 6. 交付面自证与残留

**改了什么**
- `backend/tests/test_password_lifecycle_contract.py`：递归展开（§1.2），HEAD 口径 `+255 / -61`。
- `backend/tests/test_real_llm_failover_gate.py`：HEAD 口径 `+73 / -1`，全部在文案侧（§2.1）。
- `.superpowers/sdd/ENTERPRISE_B0_PLAN/task-5-report.md`：三处订正 + 一处批注块（§3），原读未删。
- 本文件、`progress.md` 的 R17 台账行、`snap-task5-fix-post/`（两枚改后文件的逐字节副本）。
- `evidence/t5fix-r15-container-two-modules.txt`、`evidence/t5fix-r15-container-enum-probe.txt`、
  `evidence/t5fix-r15-anchors.txt`（本轮新裸档；上一轮在飞轮的 `t5fix-proof-*` / `t5fix-two-modules.txt`
  仍在档，其结论按本文件 §1.4 / §2.1 重新归位）。

**没改什么**：`backend/app/**`、`requirements.txt`、`ci.yml`、`.gitattributes`、
`test_secret_hygiene_contract.py` 与豁免表、`test_ci_gate_contract.py` 与 `EXPECTED_COLLECTED`。
**git 写操作 = 0**：状态面从开工 10 行到收工 10 行，逐行同集合
（那 10 行 = Task 5 的 8 行 + 本批改动的两枚测试文件，无第三方新增）。

**容器清理**：`docker rm -f b0-t5-r15` 见 §8 收工段（本文件写完即执行，`docker ps -a | grep -c b0-t5` 应为 0）。

**自登一处瑕疵（取证过程，不影响任何结论）**：模拟"干净 checkout"那格的 wrapper 用
`trap restore EXIT` 兜还原，但脚本后半段 `cd backend` 之后 trap 里的路径成了**相对路径** ⇒
退出时 `[ -f $E.r15parked ]` 没命中，过程件一度留在 `…real-llm-failover-001.json.r15parked` 未还原。
本轮收工自证（`anchors.py` 的"树内不许有挪窝残留"那一问）当场抓到并**手工还原**，
还原后 sha = `2ec6460041da…`（与挪动前逐字节相同），树内 `.r15parked` / `.absent-check` 计数 0。
教训入 R17：**带 `cd` 的取证脚本，trap 里一律用绝对路径**（与 §16 卡 F 那一族同源）。

---

## 7. 交给 controller 的三件事（本批不动手）

1. **Task 7 staging 那一步仍未落地**：`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json`
   要以 `git add -f` 上交付面，**需用户显式授权**（本批零 git 写操作）。在它落地前，CI 首跑必红这一枚——
   现在是"说清了缺哪枚件"的红。R15 若改判成"允许门自己识别不在面内"，那属于**换判据**，需要新开一轮裁定。
2. **警告数的回归信号要重新定义**（§4）：远端格读到个位数警告是**正常的**，不是回归。
   要钉警告数，得先钉 `JWT_SECRET` 的长度档（或在判据里只比"格内前后差"）。这条越出本批白名单（要改 `ci.yml`）。
3. **依赖区间那两枚真实漂移仍挂账**：`fastapi >=0.115,<1` 解出 0.135.3 ↔ 0.141.1、
   `PyJWT` 解出 2.12.1 ↔ 2.15.0。修 1 把第一枚的**症状**（枚举失明）从测试侧解掉了，
   但根因是区间未上界——那是 §10.2 明令 B0 不许碰的真源，归 B1 / 依赖政策那一族。

## 8. 收工自证（写完后现场取的，裸档 `evidence/t5fix-r15-anchors.txt`）

```
交付面文件数（git ls-files --cached --others --exclude-standard）= 318   与 Task 5 同数（本批零新增面文件）
git status --porcelain = 10 行（Task 5 收工的 8 行 + 本批改动的两枚测试文件），零暂存、零提交
app 面：git diff HEAD -- backend/app 减去两枚 identity 后为空 ✓ ；git diff --cached 为空 ✓
字节锚：.gitattributes / ci.yml / 门模块 三枚 MATCH；requirements.txt 与 SEC-A 模块不在 status 面（⇒ 与 HEAD 同字节）
树内残留：*.r15parked / *.absent-check 计数 0；证据件在场且 sha = 2ec6460041da（与挪动前逐位相同）
容器清理：docker rm -f b0-t5-r15 已执行，`docker ps -a` 里 b0-t5 计数 0
单跑复验：门模块 16 passed、SEC-A 46 passed、两枚受影响模块 77 + 15 passed（宿主，rc=0）
```

快照：`snap-task5-fix-post/test_password_lifecycle_contract.py`（`dd8a61adac67` / 115009 B）、
`snap-task5-fix-post/test_real_llm_failover_gate.py`（`bf1a6a85cba3` / 33563 B）。
台账：`progress.md` 的 **R17** 段（含"盲区 27 条腿"的规模订正、被回退的在飞做法、警告数归因结论、
一处 trap 相对路径的取证瑕疵自登）。

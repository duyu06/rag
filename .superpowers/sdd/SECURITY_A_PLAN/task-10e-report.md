# SEC-A Task 10e — 终态证据复跑 + 验收文档 + 提交清单

**状态头：COMPLETE（A / B / C / D 四段全部落地；本文件第 1 回合以 `PARTIAL` 建立，此后逐步回填）。**
本文件的每一段都按"先建后写"的纪律留了过程痕迹；Step 8 停在清单，**未提交、未打 tag**。

- 任务：追加一（镜像与 smoke 在终态树上重跑）+ Step 6 两 cwd 全套件对账 +
  `docs/SECURITY_A_ACCEPTANCE_2026-09-26.md` + Step 8 提交清单（**不提交**）。
- 交付文档：`E:\xiangmu\rag\docs\SECURITY_A_ACCEPTANCE_2026-09-26.md`（C 段产出，441 行）
- 提交清单：**本文件 §D**（Step 8 是停止点，未执行任何 git 写命令）

## 进度勾选

- [x] 前置：输入全部读毕（brief 含追加一/追加二、T10-1…T10-9 + 补正、§12/§14/§15/§16/§17/§18/§19/§20.1–20.6、10a/10b/10c/10d/10f/10g 报告、progress 台账）
- [x] A. 终态镜像重建 + 容器基准复跑 + 全新安装冷启动 401 + 四场景 smoke + `credentials migration-status`
- [x] B. 两 cwd 全套件对账（含 `[credential-guard]` 收尾行顺手确认 ⇒ **未出现，标待查**）
- [x] C. 验收文档
- [x] D. Step 8 提交清单（只读 `git status --short`）

---

## A. 终态部署形态证据（追加一）— **完成**

### A.0 构建前静置检查（build-safety）

- `backend/app/*.py` 34 枚文件的**聚合 sha1 = `b57fa3366a09397f790102c9a027b71d44b95c6c`**，
  最新 mtime `00:08:48`（= 10g 那行 lifespan 建表）；`credentials.py 6ebbbb4ffdc0` /
  `user_store.py 4dc81c438268` / `login_throttle.py e4c243fe70e4` /
  `credentials_migration.py 44f450debd7c` 与 `task-10d-report.md` §2 的"改后 sha1"逐枚相同
  ⇒ 控制器追加二的三格改的是测试面（`conftest.py` 00:12:35、`test_secret_hygiene_contract.py`
  00:06:18、`test_security_a_closure.py` 00:10:18）与 `main.py`，三格**全部在场**（实测：
  `test_secret_hygiene_contract.py:309 test_a_refused_boot_creates_nothing`、
  `conftest.py:919-923` 的 `credential_records` 别名 + `[credential-guard]` 收尾读别名、
  closure 文件 docstring 已按 3+8+6 叙述）。
- 并行 agent 检查：`Get-CimInstance Win32_Process` 实测另有两枚 python 在跑
  `E:\xiangmu\os\ai-customer-lifecycle-os` 的 pytest（别的仓库）⇒ **没有任何进程在写
  `rag/backend/app/**`**，构建前后聚合 sha1 逐位相同（下面 A.1 复量）。

### A.1 镜像重建 —— 新镜像 ID `3f14b3de77a4`

- `docker compose build backend` → `BUILD_EXIT=0`（日志
  `.superpowers/sdd/SECURITY_A_PLAN/task-10e-build.log`）。这一次只重建了源码 COPY 层
  （`requirements.txt` 未变 ⇒ pip 层命中缓存），耗时约 5 分钟，不是 10a 那一轮 32 分钟。
- `docker images rag-backend` → `rag-backend:latest  3f14b3de77a4  2.68GB`。
  **`1abba3717aa7`（10a 的 17:42 镜像）已不在本地镜像库里**（`docker images --no-trunc` 只列出
  `3f14b3de77a4` 一枚）⇒ 这次构建把旧 tag 覆盖并回收了它，回滚点不再存在，这条要写进文档的
  "冻结基线"与运维提示。
- 构建后复量 `backend/app/*.py` 聚合 sha1 = `b57fa3366a09…`（与构建前逐位相同）。
- 容器 `docker compose up -d backend` → `Up (healthy)`；
  `docker inspect rag-backend-1 --format '{{.Image}}'` =
  `sha256:3f14b3de77a4e93d27d1b14389562aab4f746c2a30e55edca28f1057e57e8233` ⇒ 服务流量在新镜像上。
- **镜像内源码 == 现树**（部署形态与判据同源那半句，容器内 python 逐枚 sha1 比对，12 位前缀）：
  `credentials 6ebbbb4ffdc0`、`user_store 4dc81c438268`、`credentials_migration 44f450debd7c`、
  `directory 80edfd90b724`、`login_throttle e4c243fe70e4`、`security_startup 6bd74f9ee1e1`、
  `cli 072f2d43f22e`、`auth 7f669c167487`、`main fd6e29fc721d`、`security 3881153812f7`、
  `config b736eb938176` —— 与宿主 `backend/app/*.py` **逐枚相同**；容器 python 3.12.14 /
  `argon2-cffi 25.1.0`。

### A.2 SECA-19 容器基准复跑 —— `argon2-benchmark-container-final.json`：**GREEN**

命令（10a 原样，含 MSYS 那两条环境事实）：
`MSYS_NO_PATHCONV=1 docker compose cp .superpowers/scripts/run_argon2_benchmark.py backend:/tmp/bench.py`
→ `docker compose exec -T backend python /tmp/bench.py > argon2-benchmark-container-final.json`，rc=0。

| 预算项 | **终态镜像 `3f14b3de77a4`** | 首测镜像 `1abba3717aa7`（`argon2-benchmark-container.json`） | 上限 |
| --- | --- | --- | --- |
| 串行 P50 / P95（50 次 verify） | **18.8 / 25.3 ms** | 50.3 / 55.3 ms | P95 ≤ 1500 ms |
| 并发 P95（闸门满配 2 worker × 32） | **40.9 ms** | 66.7 ms | ≤ 3000 ms |
| 峰值 RSS 增量 | **39 280 KiB = 38.4 MiB** | 39 280 KiB | ≤ 262 144 KiB（256 MiB） |
| `verdict` 字段 | **`GREEN`** | `GREEN` | — |

终态数比首测**更快**（serial P95 −54%、concurrent P95 −39%），RSS 一格未动 ⇒
没有任何预算项越界，**SECA-19 = `GREEN`，判据取容器数**。两次数都进文档的理由：首测那一份
测在 17:42 的镜像上，而它之后落了 10c/10d/10f/10g（`credentials.py` 的死代码删除与
`needs_rehash` 异常分类、`login_throttle.py` 的 `_last_sweep` 惰性播种、`main.py` 的 lifespan
建表）⇒ 首测不是终态判据（追加一原文）。
宿主对照：`argon2-benchmark-host.json` 是首测轮的 win32 读数（serial p50/p95 53.5/60.9、
concurrent 88.5、`peak_rss_delta_kib: null`、`verdict: "NOT_THE_CRITERION"`）——
win32 没有 `resource` 模块 ⇒ RSS 不可测，脚本在这种平台上刻意不产出"缺数=达标"的
verdict（D-B1，见 `task-10a-report.md` B.2）。

### A.3 全新安装 + 冷启动在容器里是 401 不是 500 —— `task-10e-fresh-boot.txt`

`docker volume rm rag-seca-fresh` 后：
`docker compose run --rm --no-deps -T -i -v rag-seca-fresh:/app/data backend python - < C:/tmp/seca10e/fresh_boot_probe.py`
（脚本在**仓库外**；空 data 卷 ⇒ 不碰 `backend/data` 那枚 bind mount，命令前后宿主
`backend/data/conversations.db` 尺寸/sha1/mtime 逐格未变：57344 B / `080722b51b3e` / 17:54:11）

```
cwd=/app  CONVERSATION_DB_PATH='data/conversations.db'  SECURITY_ENTERPRISE_MODE=None
PRE  {"db_file_present": false}
STATUS_KNOWN_USER_WITHOUT_ROW=401   STATUS_UNKNOWN_USER=401
NOT_500=True   BODIES_IDENTICAL=True
BODY={"detail": "用户名或密码错误"}
POST {"db_file_present": true, "tables": [... ,"user_credentials"], "credential_rows": 0}
```

⇒ §8.5 那句「非 500」与 §20.6 补的第二格（"表不在场的冷启动"）在**部署形态**里成立：
lifespan 自动把 `user_credentials` 建出来（0 行），登录腿对"有身份无凭据行"与"未知账号"
给同一张 401 脸。这是 §12 SECA-04b 的容器证据。

### A.4 四场景 smoke + `credentials migration-status` 复跑 —— `task-10e-smoke-final.txt`

终态镜像 `3f14b3de77a4`，`http://localhost:8001`，响应体落 `/tmp` 仓库外，进仓的只有
状态码 / 键集合 / 字节数 / sha1 / 布尔判定（SEC-A-002 纪律同 10a）。

| 场景 | 实测（终态镜像） |
| --- | --- |
| S1 登录（admin，`must_change=1`） | 200；顶层键 `{access_token, password_change_required, token_type, user}`；`user` 键集 `{access_role, display_name, permissions, role, username}`；`password_change_required=True`；body 666 B |
| S2 错口令 vs 未知账号 | 两条都 401；**字节相同**（37 B，sha1 `3b9054717ae8` == `3b9054717ae8`，与 10a 首测同一枚 sha1）；`detail == 用户名或密码错误` |
| S3 must_change 数据面阻断 | `GET /api/knowledge-bases` **403** `detail == 「当前账号需先修改口令」`；白名单腿 `GET /api/auth/me` 200，`me_keys` 含 `password_change_required=True`。（403 而不是 200：本轮打的 admin 从未改过密，见下面"为什么没重跑改密腿"） |
| S4 锁定 | viewer 连错 5 次全 401；再用**正确**口令 ⇒ 401，且与 S2 那张脸**字节相同**；响应体无「锁定」字样；DB `viewer locked_until=2026-09-26T16:40:12.979814+00:00`、`failed_attempts=6`；审计尾段 `LOGIN/DENIED/AUTH_LOGIN_LOCKED` 逐笔在场 |
| `credentials migration-status` | `legacy_count=0 argon2id_count=5`；`admin/hr01/sales01/viewer` = `argon2id v1 must_change=1`，`user` = `argon2id v2 must_change=0`；rc=0 |

容器内只读 SQL 复算（同一枚 bind-mounted 文件）：`algorithm` 分布 `[('argon2id', 5)]`、
`legacy rows: 0`、`must_change=1 rows: 4`。⇒ **收敛状态在新镜像里仍然成立**（追加一第 3 项）。

**没有重跑的那半格，与为什么**：S3 的"改密后数据面 403→200 + 旧 token 401"这一跳
**本轮刻意不重跑**。它是 §15 release gate 第 6 步的一部分、10a 已在部署形态里真跑过并留证
（`task-10a-report.md` C.7：`user` 改密 200 → 新 token 打数据面 200 → 改密前那枚 token 401
`无效登录凭证` → `user` 行 `v2 must_change=0`），而重跑一次就要把**另一个** demo 账号的口令
换成一个"记录在任何地方都不存在"的值——那正是简报要求如实登记的本版现网残留形态
（`user` 已经如此）。判据一侧不受影响：同一跳由
`test_password_lifecycle_contract.py::SelfServiceChangeTests::test_changing_password_logs_in_clears_the_gate_and_kills_old_tokens`
在终态树上跑绿，并且是 M2 那发变异的杀点（`task-10b-report.md` §1 表 M2 行）。

### A.5 现网残留状态（写进文档的口径）

`backend/data/` 本轮只被**应用自己**写过（smoke 的 `failed_attempts` / `locked_until` /
`last_login`），我没有清理、截断或改过任何一行：
- 4 枚账号仍 `must_change=1`（弱口令出身未改密的**正确稳态**，不是待修缺陷）；
- `user` 的口令在 10a 的 smoke 里被换成一个任何地方都没记录的值（恢复：
  `credentials reset --username user` + `CREDENTIALS_PASSWORD`）；
- `viewer` 的锁定按 `ACCOUNT_LOCK_SECONDS=900` 自行过期，未人工解；
- `backend/data/audit.jsonl`（2 053 203 B，sha1 前缀 `65933d8bfd5d`）含 SEC-A 之前 + 测试历史 +
  smoke 真实事件的**混合账** ⇒ `migration-status` 的 `last_login` 只作运维参考。
本轮跑完的实测尺寸/mtime 见 A.6。

### A.6 跑动前后 `backend/data/` 的字节面

| 件 | 10e 跑前 | 10e 跑后（01:20 复量） |
| --- | --- | --- |
| `conversations.db` | 57344 B / `080722b51b3e` / 17:54:11 | 57344 B / `a8565a343f1a` / **00:26:37** |
| `conversations.db-wal` | 0 B | **0 B** / mtime 01:12:59（只读打开抬的，L8） |
| `conversations.db-shm` | — | 32768 B / mtime 01:15:26（同上） |
| `audit.jsonl` | 2 053 203 B / `65933d8bfd5d` / 21:02:32 | 2 056 230 B / `a0338cb05a17` / **00:26:38** |

**这一格是本轮最干净的一发互锁证据**：主库与审计账本的时间戳都停在 **00:26:37 / 00:26:38**，
那正是终态镜像四场景 smoke 自己写的时间点；此后 **5 发全套件（00:27→01:16）跑完，两个时间戳一格未动**
⇒ "测试不写生产凭据库、不写运维那本审计账"不再只是护栏断言，也是文件系统事实。
库内内容面同样只有 smoke 该写的那些：仍是 5 枚 `argon2id`、`legacy rows: 0`、`must_change=1` 4 枚
（`task-10e-smoke-final.txt` 的容器 SQL 段与 `migration-status` 段）。

---


## B. Step 6 两 cwd 全套件对账 — **完成**

### B.1 首对（终态镜像已就位、本文档尚未落盘时）

| 发 | cwd | 命令 | 收尾行 |
| --- | --- | --- | --- |
| run 1 | `backend/` | `PYTHONIOENCODING=utf-8 python -m pytest -q` | `1316 passed, 37 warnings, 1133 subtests passed in 173.83s (0:02:53)`（`10e-suite-run1-pre-doc.txt`） |
| A | 仓库根 | `python -m pytest backend/tests -q` | `1316 passed, 37 warnings, 1133 subtests passed in 328.79s (0:05:28)`（`10e-suite-root-pre-doc.log`） |
| B | `backend/` | `python -m pytest -q` | `1316 passed, 37 warnings, 1133 subtests passed in 115.91s (0:01:55)`（`10e-suite-backend-pre-doc.log`） |

三发逐位相同：0 failed、0 error、**0 skipped**。基线 1275（Task 9 complete）→ 1316 的归因逐轮在
各报告里（10b +1、10c +9 与修复轮、10d +8、10f +8、10g +6、控制器 00:20 三格 +1）；
**没有一处是"数对不上所以改期望"**。warnings 由台账里最后一个全套件数 36 → 37：多出来的是
`conftest.py:400` 那枚 `[ledger-guard] 只读改道` RuntimeWarning 家族（收尾计数 `[ledger-guard] 1 次…`），
10b–10g 各半程只报焦点数 ⇒ **这一格没有可指的前后对照件**，本轮只确认两 cwd 同数、
0 skip/failure/error，并把它作为**待查**写进文档 §7（不改 conftest 去凑）。

### B.2 文档落盘之后的终对（判据以这一对为准）

交付文档本身落在 secret 门的交付面上（`git ls-files -c -o --exclude-standard` 收 `docs/**`），
所以两 cwd 的对账在**文档定稿之后**重跑：结果见
`.superpowers/sdd/SECURITY_A_PLAN/10e-suite-root.log`、`10e-suite-backend.log`。两行收尾原文（均 `RC=0`）：

```text
1316 passed, 37 warnings, 1133 subtests passed in 251.80s (0:04:11)     ← cwd=仓库根
1316 passed, 37 warnings, 1133 subtests passed in 175.49s (0:02:55)     ← cwd=backend/
```

⇒ 文档定稿没有挪动任何一格计数（`docs/**` 只上门的材料形状面，新增一枚 md 不新增用例）；
验收文档 §7 引的就是这一对，B.1 那三发作为第三/四次 corroborating run 一并留档。

### B.3 顺手确认①：`[credential-guard]` 收尾行 —— **没有出现，标为待查**

按追加二只观察、不改代码。收尾原文（`10e-suite-root-pre-doc.log` 末段）：

```text
[ledger-guard] 1 次「读保护集下的真实账本」被改道（N1：读不判红）：
[ledger-guard]   data\conversations.db ⇒ C:\Users\zhang\AppData\Local\Temp\pytest-of-zhang\pytest-1096\llm-ledger-isolation0\conversations.db
1316 passed, 37 warnings, 1133 subtests passed in 328.79s (0:05:28)
```

只读查到的机制（不作为结论）：控制器的别名修复**在场**（`tests/conftest.py:919-920` 把凭据面
records 别名到模块级 list；`:921` 是 `if credential_records:` 才 `_report_redirects(..., "[credential-guard]", ...)`）。
于是"零记录 ⇒ 无此行"与"修复未生效 ⇒ 无此行"在只读面上**分不开**；本轮全程没有往真实凭据表写过
任何东西（真库 5 行的字节/mtime 未动）。要分开它需要一次可控的凭据面改道记录（= 动 conftest 或造
新用例），超出 10e 边界 ⇒ **交控制器**：给那一段补一枚"记录在场 ⇒ 该行必打"的正向钉。
已按现状写进验收文档 §7.1 与 §11 的收口补登格。

### B.4 顺手确认②：release gate 第 2 步的定向门 + T10-5 那一发

- - `10e-secret-gate.txt` ⇒ **`46 passed in 49.72s`，RC=0**（SECA-20 那一枚契约文件；45→46 是
  控制器 00:20 补的 `test_a_refused_boot_creates_nothing`）。
- `10e-directed-gate.txt` ⇒ **`492 passed, 10 warnings, 323 subtests passed`，RC=0**
  （release gate 第 2 步那一发的十枚文件合集）。
- **T10-5 已按要求"先实测再判定"**：封版件
  `tests/test_real_llm_failover_acceptance.py` 的 sha1 =
  `da92cdf51de5dbfad3107f1dc744d18e4173e07c`（与 `task-10g-report.md` §7 记录值**逐字节相同**，
  10e 一枚手指没碰）；不带开关跑该文件 ⇒ `no tests ran in 0.31s`、rc=0（**跳过而不是红**）；
  带 `REAL_LLM_ACCEPTANCE=1` 仅 `--collect-only` ⇒ `1 test collected`（零外呼）。
  它的三枚反造假闸另跑：`tests/test_real_llm_failover_gate.py` ⇒ `15 passed, 11 subtests passed in 9.40s`。
  ⇒ 按 T10-5 的字面处置：**记为"本版不可复现的真实面"，转 PENDING_EXTERNAL**，落在 SECA-24
  那一行（8 处调用点里的第 8 处），运维复跑命令写进文档 §10。

### B.5 本轮 10e 撞出来的一发**门的行为**（发现，不是缺陷修复）

交付文档第一次落盘时把 SECA-20 的门判红 **10 处**：`_MATERIAL_FACE` 的
`sk-[A-Za-z0-9_\-]{16,}` **没有左边界**，于是单词 `ta` + `sk-` 后面只要再跟 16 个类内字符就算一枚
"provider key"——而验收文档天然要指路的证据件名全是 `task-10X-<长名>` 这一族。

- **做法**：改**自己文档的写法 + 自己证据件的命名**（新件一律 `10e-<名>.<扩展>`；别人那枚 10b
  原始跑记录按两段写）。**没有**动 `tests/**`、**没有**往 `EXEMPTIONS` 加行——那正是 T10-9 要免掉的
  摩擦，且 `EXEMPTIONS` 里目前没有任何 `docs/*.md` 条目（门的设计口径就是"交付文档在材料形状面
  0 命中、不收豁免"）。红的那一发留档：`10e-secret-gate-red-round1.txt`
  （offender 行 `docs/SECURITY_A_ACCEPTANCE_2026-09-26.md ×10 未豁免`）；改完仍红 1 处，因为我
  **在解释里把那枚串抄了一遍**（`10e-suite-*-final` 那类名字的规律自己就是样本），最终改为
  只写形状不写实例串 ⇒ 复量 0 命中（四枚面各自 `finditer`）。
- 已写进验收文档 §7.2（判据未动）与 §11 的收口补登格（"缺左边界"一枚字符的修法属改门，不在 10e 边界）。

---


## C. 验收文档 — **已交付**

`E:\xiangmu\rag\docs\SECURITY_A_ACCEPTANCE_2026-09-26.md`：**441 行**、CR=0（LF，与
`docs/MODEL_ROUTER_V23_ACCEPTANCE_2026-09-24.md` 等兄弟件同口径）。15 个二级段 + 8 个三级段。
定稿态 sha1 = `8ba7a1b3c4cb3e797363563ea493c5dc148786a4`（文档不能自指自己的哈希，这一枚是 10e 报告侧的
修订标记；交付面哈希每次由 SECA-20 那道门复量，`git status` 里它是唯一一条本轮新增的未跟踪条目）。

覆盖清单（对照 plan Step 7 的必含段落）：判据表 §1（含 §1.1 "为什么两套房"）· 交付了什么 §2 ·
**27 行矩阵带三值状态列 §3**（实测 `GREEN 26 / PENDING_EXTERNAL 1 / BLOCKED 0`，
逐行带文件+段/行或 JSON 字段级证据指针）· 变异台 19 行 §4 · before/after 证据 §5（§14 九行逐行）·
release gate 九步 §6 · 两 cwd 对账 §7（含 §7.1 `[credential-guard]` 待查、§7.2 门红过那一发）·
§16 既有测试处置 §8 · 已知限制 §9（L1–L7 + L8–L19，含 §9.3 breaking change）·
P0 接缝四句 §10 · §18 合并 10d 的四格 + 三格收口补登 §11 · 现网残留与运维体检 §12 ·
提交清单指针 §13 · 冻结基线 §14 · 版本控制提醒 §15。

**判据没有被放宽过一处**：唯一的非 GREEN 行（SECA-24）是 10e **主动**判成 `PENDING_EXTERNAL` 的，
理由是它 8 处调用点里的第 8 处住在默认不被收集的封版件里；同一句本可以记 GREEN（那 8 处的字面量
与调用形式确实一枚未改），但 T10-5 要求"跳过 ⇒ 转 PENDING_EXTERNAL 并写明理由"，就按它写。
`legacy_count=0` 走的是 `BLOCKED`/`GREEN` 二值判断（§8.7），今天实测 0 ⇒ `GREEN`，不是 `PENDING`。

追加一的四项全部落地：① 镜像重建 + 容器基准复跑（两套房都进文档，`argon2-benchmark-container-final.json`）；
② 空 data 卷的全新安装冷启动 401（`task-10e-fresh-boot.txt`）；③ 四场景 smoke + `migration-status`
复跑（`task-10e-smoke-final.txt`）；④ 新镜像 ID 与 `docker images` 那一行进冻结基线（文档 §14）。
追加二的四句在文档 §10 原样进正文，两处"顺手确认"在 §7.1 / §7.2，控制器 00:20 的三格按**终态**叙述
（文档 §3 SECA-18 行、§2 的 P0 接缝段、§14 的 sha1 面），未照抄任何半程报告的旧状。

---

## 收尾自评（10e 自己的账）

- 用到的 git 命令全部只读：`status --short` / `log --oneline` / `show HEAD:backend/app/auth.py` /
  `rev-parse` / `tag --list` / `ls-files` / `check-ignore`。**零写命令**。
- `backend/data/` 只被**应用自己**写过（smoke），10e 未清理、未截断、未改行；bind mount 照原样复用，
  全新安装的演示走的是**另一枚 named volume**（`rag-seca-fresh`，用完留在库里，`docker volume rm` 可回收）。
- 零外部 API 调用、零付费资源；真机 P0 保持 `PENDING_EXTERNAL`，运维命令已写进文档 §10。
- 写操作面：新建 `docs/SECURITY_A_ACCEPTANCE_2026-09-26.md`、本文件，以及本轮证据件
  `argon2-benchmark-container-final.json`、`task-10e-fresh-boot.txt`、`task-10e-smoke-final.txt`、
  `10e-anchor-check.txt`、`10e-secret-gate*.txt`、`10e-directed-gate.txt`、`10e-suite-*.log`、
  `task-10e-build.log`。**未改**规格 / 计划 / `backend/app/**` / `backend/tests/**` / `frontend/**` /
  封版 P0 件（封版件 sha1 复量与前序记录逐字节相同）。
- **待控制器裁的三件事**：① `[credential-guard]` 收尾行的正向钉（§7.1 / 本报告 B.3）；
  ② `_MATERIAL_FACE` 的 `sk-` 缺左边界（本报告 B.5，文档 §11 已登记）；
  ③ warnings 36→37 的那一格前后对照件缺失（本报告 B.1，文档 §7 已标待查）。
- 状态：**COMPLETE**（A/B/C/D 四段全部落地；Step 8 停在清单，未提交、未打 tag）。

## D. Step 8 提交清单（**停止点：一枚 git 写命令都没有跑过**）

只读命令用到的：`git status --short`、`git log --oneline -3`、`git show HEAD:backend/app/auth.py`、
`git rev-parse HEAD`、`git tag --list`、`git ls-files`、`git check-ignore -v`。
**没有** `git add`、**没有** commit、**没有** tag、**没有** `--no-verify`、**没有**触碰
`model-router-v2.3-rc1`（只被 `git tag --list` 列出来一次）。

### D.1 `git status --short` 原文（10e 收口时；40 条 = 20 改 + 20 未跟踪）

```text
 M backend/.env.example
 M backend/app/agent_trace.py
 M backend/app/audit.py
 M backend/app/auth.py
 M backend/app/config.py
 M backend/app/conversation_agent.py
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
 M backend/app/knowledge_os.py
 M backend/app/main.py
 M backend/app/security.py
 M backend/requirements.txt
 M backend/tests/conftest.py
 M backend/tests/real_llm_failover_kit.py
 M backend/tests/test_branding_contract.py
 M backend/tests/test_feishu_identity_contract.py
 M backend/tests/test_model_router_v23_contract.py
 M docs/UI_COPY_GLOSSARY.md
 M frontend/src/views/GovernanceView.tsx
 M frontend/src/views/OperationsView.tsx
?? backend/app/cli.py
?? backend/app/credentials.py
?? backend/app/credentials_migration.py
?? backend/app/directory.py
?? backend/app/login_throttle.py
?? backend/app/security_startup.py
?? backend/app/user_store.py
?? backend/config/users.demo.json
?? backend/config/users.json
?? backend/tests/sec_a_fixtures.py
?? backend/tests/sec_a_seed.py
?? backend/tests/test_authentication_leg_contract.py
?? backend/tests/test_credentials_contract.py
?? backend/tests/test_password_lifecycle_contract.py
?? backend/tests/test_secret_hygiene_contract.py
?? backend/tests/test_security_a_closure.py
?? backend/tests/test_user_directory_contract.py
?? docs/SECURITY_A_ACCEPTANCE_2026-09-26.md
?? docs/SECURITY_A_PLAN.md
?? docs/SECURITY_A_SPECIFICATION.md
```

（10e 之前是 39 条；第 40 条 `?? docs/SECURITY_A_ACCEPTANCE_2026-09-26.md` 是本轮新增的那一枚交付文档。
逐条原文留档：本文件即证据，另有 `/c/tmp/seca10e/git-status-short.txt` 是 00:17 时点的同一张表。）

### D.2 拟提交路径（T10-7 的口径：显式列，不用 `git add -A`）

**新增（untracked，SEC-A 的交付面，19 条）**
`backend/app/credentials.py` · `backend/app/user_store.py` · `backend/app/directory.py` ·
`backend/app/credentials_migration.py` · `backend/app/login_throttle.py` ·
`backend/app/security_startup.py` · `backend/app/cli.py` · `backend/config/users.json` ·
`backend/config/users.demo.json` · `backend/tests/sec_a_seed.py` · `backend/tests/sec_a_fixtures.py` ·
`backend/tests/test_credentials_contract.py` · `backend/tests/test_user_directory_contract.py` ·
`backend/tests/test_authentication_leg_contract.py` · `backend/tests/test_password_lifecycle_contract.py` ·
`backend/tests/test_secret_hygiene_contract.py` · `backend/tests/test_security_a_closure.py` ·
`docs/SECURITY_A_SPECIFICATION.md` · `docs/SECURITY_A_PLAN.md` ·（+ 本轮）
`docs/SECURITY_A_ACCEPTANCE_2026-09-26.md`

**修改（tracked，20 条）**
后端生产面：`backend/app/auth.py`、`backend/app/main.py`、`backend/app/config.py`、
`backend/app/security.py`、`backend/app/audit.py`、`backend/app/agent_trace.py`、
`backend/app/conversation_agent.py`、`backend/app/knowledge_os.py`、`backend/requirements.txt`、
`backend/.env.example`；身份桥的两枚说明/入口：`backend/app/identity/README.md`、
`backend/app/identity/__init__.py`（这两条属飞书权限桥那批未提交工作，**是否随 SEC-A 一起提交要用户裁**，
见 D.4）；测试面：`backend/tests/conftest.py`、`backend/tests/test_branding_contract.py`、
`backend/tests/test_feishu_identity_contract.py`、`backend/tests/test_model_router_v23_contract.py`；
展示层：`frontend/src/views/OperationsView.tsx`、`frontend/src/views/GovernanceView.tsx`
（SEC-A 原口径"不改前端"在此记为 3 行增量偏差，理由见 `progress.md` 的 Ruling (Task 9 fix, frontend)）；
词表：`docs/UI_COPY_GLOSSARY.md`（`PASSWORD→口令变更` 那一格）。

**明确排除**
- `backend/data/**`（`.gitignore:7`；含 5 行 argon2id 收敛证据、`audit.jsonl`、`conversations.db`）——
  它是验收证据本体，不是交付物，且 `conftest` 的真库哨兵依赖它留在原地不动。
- `backend/.env`（`.gitignore:6`，本机现网配置，含真实 JWT secret 值）。
- `output/**`、`/data/`、`.playwright-cli/`、`__pycache__/**`。
- `.superpowers/**`：**默认排除，且这是一个需要用户拍的岔口**——`.gitignore` 末段把 SDD 过程件
  整体忽略，但仓库现状是 **V2.3 当年用 `git add -f` 精选过 41 枚过程件入库**
  （`git ls-files .superpowers` = 41，含 `MODEL_ROUTER_V23_PLAN/progress.md` 与若干评审件）。
  SEC-A 这一轮的全部过程件（`task-*-report.md`、`progress.md`、`mutations/`、`argon2-*.json`、
  `10e-*`/`task-10e-*` 证据件、`snap-*` 快照目录）**当前全部既未跟踪也未被 status 列出**
  （被忽略 ⇒ 不出现在上面那 40 条里）⇒ 与"前九个任务的提交清单"没有差异可说明：任何一轮都不曾
  把它们纳入过。要按 V2.3 的先例精选入库，需要一次显式的 `git add -f <逐条路径>` 决定，
  且必须先过 SECA-20 那道门自己的判断（`_UNSCANNED_PREFIXES` 已把 `.superpowers/` 整目录挡在
  扫描面外，入库不会让门红，但会把 `snap-*` 里的源码副本与 canary 字面量搬进交付历史——
  这正是 `test_secret_hygiene_contract.py:427-433` 那段范围决策给出的理由，别在收口时反转它）。
- `model-router-v2.3-rc1` 及其指向的任何对象：**不动**；不 amend 已发布的 RC。
- 快照目录 `snap-task*-*`（在 `.superpowers/` 下，随上一条一起处理）。

**建议粒度**：一个 `security-a` 提交（生产面 + 测试面 + 三份文档 + `.env.example` + 词表 + 前端 3 行），
tag `security-a-rc1`。若用户要把飞书权限桥那两条（`backend/app/identity/*`）分开，那是另一枚提交，
与 SEC-A 的判定无关（本轮全套件里它们一直是同一棵树的一部分）。

### D.3 提交前必须让读者知道的两件事

1. **`docs/SECURITY_A_ACCEPTANCE_2026-09-26.md` 一进交付面，SECA-20 的门就跟着它重跑**（本轮实测：
   第一版把它判红 10 处，原因是门的 `sk-` 形状缺左边界，见 B.5）。提交前建议复跑
   `cd backend && python -m pytest tests/test_secret_hygiene_contract.py -q`（本轮终值 46 passed）
   并把 §7.2 那一格连同改动一起看一遍。
2. **本轮没有产生任何新的 `EXEMPTIONS` 行**，也没有改任何测试期望；交付文档里不含明文口令、
   不含 5 枚 legacy 摘要、不含 canary 字面量（一律按 `路径:行号`）。


---

## D2. Step 8 提交清单的 **10h 增补**（终态快照；仍是一枚 git 写命令都没跑过）

10h（最终全分支评审的收口轮）在 §D 之上动了三枚文件、新造两枚交付面文件，并复量了 §D.1/D.3 里两处
此刻读起来像"现状"的旧数。工单：`.superpowers/sdd/SECURITY_A_PLAN/task-10h-brief.md`；
逐条实测：`task-10h-report.md`。

### D2.1 终态 `git status --porcelain` 原文（10h 收口时；**42 条 = 20 ` M` + 22 `??`**）

```text
 M backend/.env.example
 M backend/app/agent_trace.py
 M backend/app/audit.py
 M backend/app/auth.py
 M backend/app/config.py
 M backend/app/conversation_agent.py
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
 M backend/app/knowledge_os.py
 M backend/app/main.py
 M backend/app/security.py
 M backend/requirements.txt
 M backend/tests/conftest.py
 M backend/tests/real_llm_failover_kit.py
 M backend/tests/test_branding_contract.py
 M backend/tests/test_feishu_identity_contract.py
 M backend/tests/test_model_router_v23_contract.py
 M docs/UI_COPY_GLOSSARY.md
 M frontend/src/views/GovernanceView.tsx
 M frontend/src/views/OperationsView.tsx
?? backend/app/cli.py
?? backend/app/credentials.py
?? backend/app/credentials_migration.py
?? backend/app/directory.py
?? backend/app/login_throttle.py
?? backend/app/security_startup.py
?? backend/app/user_store.py
?? backend/config/users.demo.json
?? backend/config/users.json
?? backend/tests/sec_a_fixtures.py
?? backend/tests/sec_a_seed.py
?? backend/tests/test_authentication_leg_contract.py
?? backend/tests/test_credentials_contract.py
?? backend/tests/test_password_lifecycle_contract.py
?? backend/tests/test_secret_hygiene_contract.py
?? backend/tests/test_security_a_closure.py
?? backend/tests/test_user_directory_contract.py
?? docs/SECURITY_A_ACCEPTANCE_2026-09-26.md
?? docs/SECURITY_A_PLAN.md
?? docs/SECURITY_A_SPECIFICATION.md
?? scripts/sec_a_fresh_boot_probe.py
?? scripts/sec_a_smoke_http.py
```

差异只有一处：**多出第 21、22 枚未跟踪 = `scripts/sec_a_fresh_boot_probe.py`、`scripts/sec_a_smoke_http.py`**
（终审 D1：部署面探针脚本入库，让那 6 行矩阵证据可从仓库复现）。10h 另外动的三枚都在**已跟踪**面里
（`backend/tests/conftest.py` 的 C1 重绑、`backend/tests/test_security_a_closure.py` 的 C2 secret 注入、
`docs/SECURITY_A_ACCEPTANCE_2026-09-26.md` 的 rev 2）与**已跟踪的规格**（`docs/SECURITY_A_SPECIFICATION.md`
三处回写 + §20.7）——所以 ` M`/`??` 两栏的**数量**变化只有那两枚脚本。`git rev-parse HEAD` =
`bc43ca3931c36cc27768fbae0d34b24297d13121`；`git tag --list` 仍只有 `model-router-v2.3-rc1`，未触碰。

### D2.2 拟提交路径的增量（在 D.2 那张显式清单之上）

- **新增交付项（2 枚，`scripts/` 目录）**：`scripts/sec_a_fresh_boot_probe.py`、`scripts/sec_a_smoke_http.py`。
  它们落在 **SECA-20 的扫描面上**（`git ls-files -c -o --exclude-standard` 从 256 → **258**），10h 的做法是
  **改脚本写法**（口令一律按 env 取，脚本内无明文、无摘要、无 canary 字面量）而不是加豁免行 ⇒
  10h 复量：命中仍是 **16 文件 / 31 处**、`EXEMPTIONS` 一行未加、门 46 passed（`test_secret_hygiene_contract.py`）。
  复现命令写在两枚脚本自己的 docstring 里；第 1 枚已在当前镜像 `3f14b3de77a4` 上真复跑（输出逐行等于
  `task-10e-fresh-boot.txt`，留档 `10h-fresh-boot-rerun.txt`）；第 2 枚**只入库未重跑**（理由见 D2.4）。
- **`scripts/` 目录本身不是新的顶层路径**：仓库里已有 `scripts/*.py`（`release_smoke.py` 等）在跟踪面内，
  所以这一枚不需要新的 `.gitignore` 或 `git add` 目录级决定，逐条 `git add scripts/sec_a_*.py` 即可。
- 10h 不改的东西（明确不在清单增量里）：`backend/app/**` 一枚未动（实测 `backend/app/*.py` 34 枚聚合
  sha1 仍是 `b57fa3366a09397f790102c9a027b71d44b95c6c`，与交付文档 §14 同值；五枚具名单文件 sha1 逐枚相同）、
  `frontend/**`、`docker-compose.yml`、`.github/workflows/ci.yml`、`backend/tests/test_real_llm_failover_acceptance.py`
  （复量 sha1 `da92cdf51de5dbfad3107f1dc744d18e4173e07c`，与封存值一致）、`backend/data/**`、`model-router-v2.3-rc1`。

### D2.3 排除项与那个 `add -f` 岔口（10h 复述并更新计数）

`.superpowers/**` 仍然既被 `.gitignore` 忽略、也不出现在上面那 42 条里（10h 新增的过程件同样如此：
`task-10h-brief.md`、`task-10h-report.md`、`10h-suite-both-cwd.log`、`10h-fresh-boot-rerun.txt`）。
**岔口没变且更需要拍一次**：仓库现状是 V2.3 当年用 `git add -f` **精选 41 枚**过程件入库
（10h 复量 `git ls-files .superpowers | wc -l` = **41**，与 D.2 记录同值）。SEC-A 走到 10h 已经有第二批
完整过程件，是否按同一先例精选入库仍是用户决定；若入库，`snap-task*-*` 那些 `app/` 源码副本与
canary 字面量会进交付历史（`test_secret_hygiene_contract.py:427-433` 那段范围决策正是为了避免这件事，
别在收口时反转它）。10h 建议：只精选 `progress.md` + `task-*-report.md` + `10e-*`/`10h-*` 证据件 +
`argon2-*.json` + `mutations/` 骨架，**不**精选 `snap-*`。

### D2.4 10h 对 D.1/D.3 两处旧表述的更正（不回改原文，按"追加"处理）

1. **D.3 第 2 点那句"交付文档里不含明文口令"在 10h 之后要打个补丁**：验收文档 §9.1 L6 为纠正"旧口令
   永久失效"那句假声称，按规格 §2:40 已有的盘点复述了 **一枚**明文弱口令值（`admin123`）。它不是新泄漏
   （值本来就在规格与 git 历史里），`docs/**` 在门上只上材料形状面 ⇒ 门仍 0 命中（10h 复量）。摘要字面量
   与 canary 仍然一枚未抄进文档。
2. **D2.1 之外还有一格"看起来可复现、其实当时不可复现"的**：§D 那批 smoke 证据依赖 `C:/tmp/seca10e/`
   里那两枚脚本 + 旧镜像。脚本已入库（D2.2），旧镜像 `1abba3717aa7` 的回收集聚仍成立 ⇒ 现在这句改成
   "部署面证据可由 `scripts/sec_a_*.py` + **当前**镜像复现"。第 2 枚脚本没有重跑，因为它要拿已泄露的弱
   明文打在线部署、S4 那五连错会往 `backend/data/` 的凭据表写失败计数并锁掉 `viewer`，而 10h 的硬规矩
   是 `backend/data/` 只读。这一格如实写成"仅入库、未复跑"，不写成"已复现"。

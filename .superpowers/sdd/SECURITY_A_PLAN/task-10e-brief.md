# Task 10e — 验收文档 + 两 cwd 对账 + 提交清单（SEC-A 收口）

前置：Task 10a（镜像/基准/smoke/closure）、10c+修复轮（`credentials migrate`）、10d（deferred 分诊）、
10b（19 发变异台）全部落地。**你是最后一个动笔的人**，所有证据都已在工作区里，你的工作是**把它们
组装成判据**，不是重新测量（唯一例外：Step 6 的两 cwd 全套件对账要你亲自跑）。

## 输入（全部先读，再动笔）

- 规格判据：`docs/SECURITY_A_SPECIFICATION.md` — §12（**27 行矩阵**与三值状态词汇表）、§14（before/after
  证据表，逐行就是你文档的证据清单）、§15（release gate 9 步 + verdict 规则）、§17（L1–**L7**）、§18、§19、§20.1–20.5
- 计划：`docs/SECURITY_A_PLAN.md` Task 10 Step 7（版式与必含段落的原文）
- 台账：`.superpowers/sdd/SECURITY_A_PLAN/progress.md`（每条裁定、每轮评审结论、控制器自伤记录）
- 报告：`task-1-report.md` … `task-9-report.md`、`task-9-fix-report.md`、`task-10a-report.md`、
  `task-10c-report.md`、`task-10d-report.md`、变异台报告（10b 产出）
- 证据件：`argon2-benchmark-container.json`、`argon2-benchmark-host.json`、
  `closure-real-db-legacy-count.txt`、`snap-*` 基线目录

## 要产出什么

1. **Step 6 全套件两 cwd 对账**（你亲自跑，两遍都要）：
   `cd backend && PYTHONIOENCODING=utf-8 python -m pytest -q` 与仓库根
   `PYTHONIOENCODING=utf-8 python -m pytest backend/tests -q`，**两个 N passed 必须逐位相同**
   （含 warnings 与 subtests 数），把两行原样写进文档。上一轮基线是 1275/36/1117；10c 与 10d 只增不减，
   若数对不上或有 skip 冒出来，**停下来报 BLOCKED**，不要调低期望。
2. **`docs/SECURITY_A_ACCEPTANCE_2026-09-26.md`**（文件名日期用签发日；理由见 `task-10-brief.md` T10-1）
   必含段落照 plan Step 7：判据表 · 交付了什么 · 27 行矩阵带状态列 · 变异台 19 行结果 ·
   before/after 证据 · 已知限制 L1–L7 + 一次强制重登录的 breaking change · 后续登记（§18 清单 +
   10d 分诊表里落到"登记"的那些）· 冻结基线（镜像 ID `1abba3717aa7`、套件数、本文档修订）。
   版式照 `docs/MODEL_ROUTER_V23_ACCEPTANCE_2026-09-24.md`。
3. **Step 8 提交清单**（不提交）：`git status --short` 原文 + 拟提交路径逐条列出 + 明确排除项，
   交给控制器转用户确认。**禁止** `git add -A`、禁止任何 git 写命令、禁止动 `model-router-v2.3-rc1`。

## 写矩阵与证据时的硬规矩

- 状态只有 `GREEN / PENDING_EXTERNAL / BLOCKED` 三值。`legacy_count>0` ⇒ `BLOCKED`（今天实测是 0，
  见 `closure-real-db-legacy-count.txt`）。**不得**为了让某行好看而改判据、改测试、改规格。
- 每行状态后面紧跟**证据指针**（文件 + 段/行，或 JSON 字段名）。没有可指证据的行只能是
  `PENDING_EXTERNAL` 并写清等什么。
- before 面要可复现：`backend/app/auth.py` 里那 5 枚 digest 的"before"用
  `git show HEAD:backend/app/auth.py` 只读取证（read-only git 允许），别引用记忆。
- SECA-19 只认容器数（serial P95 55.3ms / concurrent 66.7ms / RSS Δ 38.4MiB，预算 1500/3000/256MiB）；
  宿主数写在"对照"栏并说明 win32 无 `resource` 模块所以 RSS 不可测。
- **latency 分布是证据不是判据**（用户裁定过）：SECA-13 的判定读"四态各恰好一次 verify"的调用面，
  不读耗时表。
- canary 字面量（`sk-CANARY-…`）按 `路径:行号` 引用，**绝不抄进 `docs/**`**——secret 门的材料形状面会红，
  而唯一的"修法"是加豁免行，那正是本轮设计要免掉的摩擦（`task-10-brief.md` T10-9）。
- 明文口令、5 枚 legacy digest、真实 JWT 值一律不得出现在文档里（closure 测试文件里那 5 枚常量是
  检测器的黑名单，属既有例外，别在文档里复制第二份）。
- 现网残留状态要如实写：demo 库里 `user` 的口令已在 smoke 中被换成"任何地方都没记录"的值
  （恢复：`credentials reset --username user` + `CREDENTIALS_PASSWORD`），另外 4 枚仍 `must_change=1`
  ——那是弱口令出身账号未改密的**正确稳态**，不是待修缺陷。
- 文档是交付面：中文文案照 `docs/UI_COPY_GLOSSARY.md`；`PASSWORD` 审计动作的展示名是「口令变更」，
  已登记在该词表。

## 边界

- 只新建 `docs/SECURITY_A_ACCEPTANCE_2026-09-26.md`；**不改**规格、计划、代码、测试（发现矛盾一律报
  回来由控制器裁）。行尾：`docs/*.md` 在本仓是 LF（先量再写）。
- 无 git 写命令；不写 `backend/data/`；不 spawn 子代理。
- **报告优先**：150 回合硬顶。先建 `.superpowers/sdd/SECURITY_A_PLAN/task-10e-report.md`
  （两 cwd 数 + 矩阵前几行）再逐步扩写文档本体。

回报不超过 15 行：Status、两 cwd 套件数、矩阵三值各多少行（合计必须 27）、verdict 一行、
提交清单文件路径、疑虑、报告路径。

## 追加（控制器 23:30 补，务必照做）：镜像与 smoke 已过期，10e 必须重跑

Task 10a 的镜像 ID `1abba3717aa7` 是 **17:42 建的**，而它之后落了 10c（`credentials migrate`）、10d（含
`credentials.py` 的死代码删除与 `needs_rehash` 异常分类）、10f/10g（lifespan 建表）。⇒ SECA-19 的容器基准与
compose smoke 都测在**已非终态**的镜像上。规格 §14 的"after 证据"与 §17 L3（"这台机器的内存是真实约束"）
要求的是发布形态的数字，所以 10e 在写文档之前必须：

1. **重建镜像并复跑容器基准**：`docker compose build backend` → `up -d` → 健康 → 复跑
   `.superpowers/scripts/run_argon2_benchmark.py`（容器内），另存
   `argon2-benchmark-container-final.json`。**两次数都写进文档**（首测 55.3/66.7ms/38.4MiB 与终态数），
   并说明为什么要两次。终态数若不进预算 ⇒ SECA-19 = `BLOCKED`，按 §15.2 走，不得拿旧数充当终态判据。
2. **在部署形态里复核 10g 那一发**：起一个**空 data 卷**的一次性容器（例如
   `docker compose run --rm --no-deps -v rag-seca-fresh:/app/data backend python -c "...login..."`，
   或用 `docker run` 挂一个临时目录），证明"全新安装 + 冷启动"下登录是 **401 统一中文脸而不是 500**，
   并且 `user_credentials` 表由 lifespan 自动在场。这是 §8.5「非 500」那句在容器里的直接证据；
   做不到就把命令与失败输出如实贴进文档并记 `BLOCKED`。
3. **重跑四场景 smoke**（登录 / 错口令 vs 未知账号同形 / must_change 阻断 / 锁定）与
   `credentials migration-status`，确认收敛状态（`legacy_count=0`、5 枚 argon2id、4 枚仍 `must_change=1`）
   在新镜像里仍然成立。注意 demo 库里 `user` 的口令已在 10a 的 smoke 里被换掉（不在任何地方记录）。
4. 新镜像 ID 与 `docker images` 的那一行进"冻结基线"段。

构建前确认没有并行 agent 在改 `backend/app/**`（构建会把源码烧进镜像）。

## 追加二（控制器 00:20）：10f/10g 复评判定的四条必写内容与两处待验

**必须写进验收文档的四句（P0 接缝，复评 G3 原话归纳）**：
1. P0 的登录腿之所以能 200，是 **harness 自己**通过 `sec_a_seed.install_demo_credentials` 给它造的临时库
   种了凭据行，闸门与收集门是同一枚 `REAL_LLM_ACCEPTANCE=1`；产品侧对"未种凭据的全新安装"永远是 401。
2. 新的 P0 证据 JSON 里 `ledger.tables` 会多出一张 `user_credentials`——那是**描述被拓宽**，不是判据被放宽
   （全仓没有任何断言检查那枚表集合）。
3. **P0 绿灯不证明"全新安装能登录"**；它证明的是 failover 走到 200，且凭据由 harness 提供。这句话必须
   原样进文档，否则后来人会把 P0 读成安装性验收。
4. P0 的 `files_sha1` **不含 kit 模块**（`real_llm_failover_kit.py`）——造出那行凭据的代码不在它自己
    fingerprints 的证据里。V2.3 既有证据因此不作废，但这是一个必须点名的边界。

**两处待你在本轮跑全套件时顺手确认（不要为此改代码）**：
- 全套件（两 cwd）的收尾输出里现在应当出现一行 `[credential-guard] …`（控制器刚把它的 records 别名到
  模块级 list，修的是"守卫对象在收尾汇总之前被摘掉 ⇒ 那一段永远打印不出来"）。**若仍然没有，把那两行
  收尾原文照贴进报告并标为待查**，不要自己改 conftest 去凑。
- 若你或任何人以 `REAL_LLM_ACCEPTANCE=1` 跑**整套**套件：`test_security_a_closure.py` 里
  `test_seam_gives_the_p0_login_leg…` 的 finalizer 会卸掉会话级接缝，导致后面的
  `test_conftest_fixture_arms_the_seam_only_when_the_switch_is_on` 断言 `False is True` ⇒ **顺序依赖红**。
  官方 runner 免疫（它 unset 该 env、只 arm 单文件那一步）。这条要写进文档的"已知限制/运维提示"，
  并登记 V2.4 待办，**不要**为了让全量开关跑绿而改夹具。

**另外三格已由控制器直接改掉（写文档时按终态叙述，不要照抄报告里的旧状）**：
① `tests/conftest.py`：凭据面 records 别名 + 收尾汇总读别名（上面那条）；
② `tests/test_secret_hygiene_contract.py`：新增 `test_a_refused_boot_creates_nothing`（§8.5 顺序契约
"先拒坏配置再谈落盘"；已证伪：把 lifespan 两步调换 ⇒ 该枚红、还原 sha1 一致）；
③ closure 文件里两处过时的用例计数（八枚/六枚分组已按 3+8+6 更正）。
规格侧同步：§8.5 守卫位置段改为**认符号不认行号**并写明顺序契约、§12 SECA-04b 补第二格、SECA-18 补
"拒绝启动不得已经建表"、§2:56 的漂移坐标去掉。

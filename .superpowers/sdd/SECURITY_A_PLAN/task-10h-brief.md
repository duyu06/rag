# Task 10h — 终审判定的收口工单（文档 6 处必改 + 2 处代码 + 证据可复现性）

来源：**最终全分支评审**（报告在会话里，工单化在此）。它的判定是：**代码 ship-able，验收文档不得按现状发布**。
本工单逐条编号，每条都给"改什么 / 改成什么 / 怎么验"。**评审给的措辞是权威措辞**，不要自己另发明一套说法。

判据基线（终审实测，勿推翻）：两 cwd 全套件 1316 / 37 warnings / 1133 subtests；树哈希与文档 §14 一致；
19/19 变异台锚点唯一；EXEMPTIONS 16 行 31 处、交付面 256 文件、验收文档 0 命中。

---

## 组一 · 代码侧（两枚，都是终审点名的）

**C1 — 控制器那个别名修复是死代码（必须择一处理，不许留僵尸）。**
终审的结构证明：账本面靠 `tests/conftest.py:725` 的 `guard.records = _REDIRECTS` 才让别名生效，
而凭据面在 `conftest.py:730-741` 装完之后**从来没有把 `credential_guard.records` 重绑到
`_CREDENTIAL_REDIRECTS`**（`LedgerGuard.__init__` 在 `:263` 造的是新 list）⇒ 模块级那个 list 永远空，
唯一读者是 `:919-920` 的 `else` 分支，而 `_CREDENTIAL_GUARD` 在 `:762` 已置 None ⇒ `if credential_records:`
恒假 ⇒ 那一行仍打不出来。行为证明：`test_credentials_contract.py:1892-1913` 那枚用例通过 ⇒ 记录**确实存在**，
但同一发里 `grep -c credential-guard` = 0 ⇒ 不是"零记录"。

**裁定：让别名生效**（不要删）——在 `conftest.py:741` 之后照账本面补一行
`credential_guard.records = _CREDENTIAL_REDIRECTS`；同时把 `:164` 那句"这个模块级 list 与守卫的
records 是同一个对象"改成陈述**怎么**让它成为同一个对象（现在它是错的）。
**验收**：跑 `python -m pytest tests/test_llm_usage_contract.py tests/test_security_a_closure.py -q`，
收尾必须出现一行 `[credential-guard]`；若仍不出现，**不要改代码去凑**，把收尾原文贴进报告并写明仍未成立。

**C2 — 第 37 枚 warnings 归因到了具体用例，且它绕过了本仓自己的机制。**
终审定位：`tests/test_security_a_closure.py::test_seam_gives_the_p0_login_leg_its_credential_source`
驱动真实登录 ⇒ `issue_token` 用 `settings.jwt_secret`，本机 `backend/.env` 那枚是 31 字节 ⇒
`InsecureKeyLengthWarning`。本仓对这一类早有专用夹具：`tests/sec_a_fixtures.py:93-113`
`LongJwtSecretMixin`（其 docstring `:11-14` 就写着"整套件警告数不变是本仓的回归信号"）。
**改法**：让那一枚用例走 `LongJwtSecretMixin`（或等价的长 secret 注入），**不得**用 filterwarnings 压掉，
**不得**改规格里的警告数。
**验收**：`tests/test_security_a_closure.py -q` → `17 passed, 0 warning`（或警告数与它引入前一致）。

---

## 组二 · 证据可复现性（终审"最薄的一环"，必须补）

**D1 — 部署面证据无法从仓库复现。** `task-10e-smoke-final.txt:3` 与 `:4` 点名的两个探针脚本住在
仓库外（`C:/tmp/seca10e/…`），而旧镜像已被回收 ⇒ 27 行矩阵里有 6 行（SECA-01/03/04b/14/18-deployment/19）
依赖这些转录。
**改法**：两个探针脚本**今天仍在**（控制器 02:05 实测 `C:/tmp/seca10e/` 里有 `fresh_boot_probe.py` 1763 字节等）
⇒ 复制进**受版本控制的目录**，命名跟随本仓 `scripts/` 的既有习惯（那里面是扁平的 `*_smoke.py` /
`*_integration.py`，没有子目录）：建议 **`scripts/sec_a_fresh_boot_probe.py`** 与
**`scripts/sec_a_smoke_http.py`**。文件内不得出现明文口令——按 env 取，参照 `app/cli.py` 的做法。
并在验收文档 §14 与提交清单里点名这两个文件；文档里加一句"部署面证据可由这两个脚本 + 当前镜像复现"。
复制后**原地脚本不要删**（它们是本次转录的原始现场）。若你发现某个转录对应的脚本确实不在，如实写明
"探针不可复现"，并把那几行的证据等级降为"转录（无脚本）"。**不得**为了让它看起来可复现而重写转录或伪造脚本。

---

## 组三 · 验收文档必改六句（终审原话："not safe to publish as written; safe after six named edits"）

逐条替换，保留其它内容：

1. **§9.1 表 L6 行**「**5 个旧口令永久失效**…」→ 改成代码真正做到的事：泄露的**摘要**不再是存储形态；
   泄露的**明文口令**在每个账号完成强制改密之前**仍然可以登录并改密**。`must_change` 只挡数据面 403，
   **不挡** `POST /api/auth/password/change`（§8.4 白名单刻意包含它），所以握着 `admin123` 的人可以拿到票
   并把管理员口令改掉（顺带把受害者锁在外面）——这正是 T6 的历史泄露能买到的东西。
   并在 §12.2 加一条运维动作：**暴露部署之前先轮换那四枚弱出身账号**。
   （同一条措辞要回写 **spec §17 L6**——见组四。）
2. **§1 表"必须随版交付的 breaking change"行 + §9.3 首行**：保留"一次强制重登录、不得写成无感升级"，
   追加：对界面用户，改密腿**目前没有 UI 入口**（新增 L20 行），且登录页对 `user` 的一键填充口令已随 10a
   的轮换失效（恢复只有一条 CLI 路）。
3. **§6 第 6 步**「全程走产品路径、零手工 SQL」→「零手工 SQL；导入腿当时经
   `credentials_migration.import_from_artifact()`（`task-10a-report.md` C.3）执行，
   `credentials migrate` 由 10c 落地并有 9 枚用例钉，但**未在部署形态跑过**」；并把 §1 表
   "§15.1 release gate 九步 | 第 1–8 步逐项成立"改成"第 1–5、7–8 步成立，第 6 步按上文拆开"。
4. **§2 最后一条 bullet**「交付面密钥扫描以普通 pytest 契约测试落在既有 `backend-contracts` job 上」→
   终审实测：`ci.yml:8-25` **没有任何依赖安装步**、跑的是 `python -m unittest discover`（`:19`）⇒
   半数 SEC-A 门（裸 pytest 函数）在 CI 里今天**不可达**，`argon2-cffi`（`requirements.txt:13`）也没有任何
   job 装。改成"本地这道门是真的（`10e-secret-gate.txt`，46 passed）；**'本地与 CI 同一道门'尚未成立**，
   已登记 SEC-B：backend-contracts 需要先有 `pip install -r backend/requirements.txt` 与 pytest runner"。
5. **§7.1**（`[credential-guard]` 那两行"别名修复在场／只读面上分不开"）→ 换成 C1 的终审结论与
   处置（死代码 → 已按裁定补重绑；生效与否按 C1 的验收结果写，**不许写没发生的事**）；执行路径不受影响
   的事实保留（`conftest.py:748-760,883-890`）。
6. **§7 的 36→37 warnings 段**（原写"没有可指的前后对照件…留作待查"）→ 换成 C2 的归因与处置：
   点名那枚用例、31 字节 `backend/.env` secret 的因、`LongJwtSecretMixin` 的解，以及"这一格的告警数
   本来就是宿主机 `.env` 决定的（36 那基线同样如此），所以文档要写明它是 host-dependent"。

**顺手改的终审 Minor（同一批发出去）**：§14「工作树 39 条」/§15「20 改 + 19 未跟踪」→ 实测
`git status --porcelain` = **40 = 20 ` M` + 20 `??`**（§13 是对的）；L18 的 `credentials.py:99-101`
→ 按 §20.4"认符号不认行号"改为指那句饿死叙述所在处（实测在 `:107`）或直接删坐标；§1.1 line 42 把
"容器数才是判据"的出处从 §14 改成 **§15.2**（spec line 604 那句"不得用宿主数据替代容器证据"）；
§1 line 5 补一句"§20.5 / §20.6 两轮回写是**交付面变更且仍需用户确认**"；§3 SECA-20 的自测指针补上
"交付面今天 256 文件"。

---

## 组四 · 规格侧回写（三处，控制器口径，写进 §20.7）

- **S1**：§17 L6 那句"旧口令永久失效"按组三第 1 条的口径改（规格与文档必须同口径，否则下一轮又有人照抄）。
- **S2**：§19 裁定 5 / §12 SECA-20 里"与既有 `backend-contracts` CI job 同一道门"→ 改为"本轮只保证**本地**这道门；
  CI 侧的依赖安装与 runner 形状是 SEC-B 前置"。§18 增登记一条。
- **S3**：§9.3 的"切换点"枚举后面，**点名两个不在枚举内的既有落盘写手**（`app/knowledge_os.py:86` 的
  `_write_json`、`:92` 的 `_append_jsonl` 仍用 `redact_secrets`），并写明这是**范围边界**而非破掉的承诺
  （AST 那枚"恰好 4 处"的等式会把第五张落盘面判红，所以不会静默漂移）。§18 增一条"纳入那两张面 ⇒ 钉 4→6"。

规格是冻结文档：这三处都属于"纠正自己写过的过度声称"，**不是放松判据**；每条在 §20.7 里留来由，并标注
"需用户确认"（与 §20.5/§20.6 同一处置）。

---

## 组五 · 收尾复跑（改完才许写终态数）

1. 焦点门：`python -m pytest tests/test_security_a_closure.py tests/test_credentials_contract.py
   tests/test_secret_hygiene_contract.py -q`；再跑 `tests/test_llm_usage_contract.py` 看 C1 那行有没有出现。
2. **两 cwd 全套件各一遍**，逐位相同才允许写进文档；C2 之后警告数预期回到 36（若不是 36，如实写实测数并解释）。
3. 重跑 secret 门子集，确认交付面文件数（+D1 的两个新脚本会进面上）与 `EXEMPTIONS` 仍然相等；
   **若新脚本带出命中，改脚本的写法，不加豁免行**。
4. 更新提交清单（`.superpowers/sdd/SECURITY_A_PLAN/task-10e-report.md` 追加 §D2）：终态 `git status` 原文、
   拟提交路径（含 D1 的脚本目录）、排除项，以及"V2.3 曾对 `.superpowers/` 用 `add -f` 精选 41 枚"这个岔口。

## 硬规矩

- **零 git 写命令**；不碰 `model-router-v2.3-rc1`；不 `git add`；不提交；不打 tag。
- 不改：`backend/app/llm/`、`backend/app/rag.py`、`backend/app/conversation_agent.py`、
  `backend/tests/test_real_llm_failover_acceptance.py`（sha1 必须仍是 `da92cdf51de5dbfad3107f1dc744d18e4173e07c`）、
  egress D6 计数、`frontend/**`、`docker-compose.yml`、`.github/workflows/ci.yml`。
- 规格只许改组四点名的三处 + §20.7；**不得**动 §4 不变量、§7 时序、§8.5 双形态、§9.1 两栏表、§12 行号与判据文本。
- **不得为了让数字好看而放宽任何测试或文档措辞。** 任何一条你判断"评审说错了"的，写进报告并给证据，不要照做也不要反向放宽。
- 一次写操作一个文件；行尾按各文件现状（`docs/*.md` 与 SEC-A 模块是 LF，`app/main.py`、`backend/.env.example` 是 CRLF）。
- `backend/data/` 只读；不生成新的明文口令/摘要/canary 字面量。
- 不 spawn 子代理。
- **报告优先**：第 25 回合前先建 `.superpowers/sdd/SECURITY_A_PLAN/task-10h-report.md`（`PARTIAL` 头），
  每完成一条就追加。本 harness 150 回合硬顶，本项目已经死过四次。

回报不超过 15 行：Status；C1 是否真的让那行打印出来（原话）；C2 后警告数；两 cwd 终态数；
文档六句是否全部落地（+ 三处规格回写）；D1 探针是否可复制；提交清单路径；疑虑；报告路径。

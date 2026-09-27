# SEC-A Task 10f report — P0 登录腿的凭据来源接缝（harness 侧）

STATUS: DONE（接缝在场 / 8 枚新用例全绿 / 默认套件惰性实测过 / P0 端到端 = PENDING_EXTERNAL，见 §5）

## 0. 任务边界（引用为准）

- 规格权威出处：`docs/SECURITY_A_SPECIFICATION.md:614`（§16「必须原样绿」）——8 处
  `/api/auth/login` 调用点里点名 `test_real_llm_failover_acceptance.py:686`，
  **调用形式与口令字面量都不改**，「改的是它们脚下的凭据来源（fixture 造 argon2id 行，
  §8.2 与 SECA-24）」。⇒ 接缝落在 harness 层，sealed 文件一字不动。
- 不做的事：不编辑 `backend/tests/test_real_llm_failover_acceptance.py`（含其末尾
  `del RealLlmFailover001Tests` 收集门）、不动 `backend/app/**`、不动 `docs/SECURITY_A_*`、
  不跑任何真实外呼、不写 `backend/data/`。

## 1. 现场勘察（已核实的事实，逐条来自读码）

| 事实 | 出处 |
| --- | --- |
| P0 的临时库由测试自己的 setUp 建：`usage_module.init_usage_db(str(self.temp_db))`，落点是 `<EVIDENCE_FILE 目录>/run/<stamp>/conversations.db` | `test_real_llm_failover_acceptance.py:143-156` |
| 登录腿在 `_http_face_200` 里断言 `200`，账号/口令字面量是 `admin` / `admin123` | `test_real_llm_failover_acceptance.py:684-687` |
| 默认不收集（`del`）⇒ 这道断裂在默认套件里不可见 | `test_real_llm_failover_acceptance.py:714-715` |
| 生产代码不自动造凭据行：无行 ⇒ `LoginResult(None, AUDIT_INVALID_CREDENTIALS)`，HTTP 401 统一文案 | `app/auth.py:203,306,328`、`app/main.py:338-341` |
| 登录成功响应键集：`access_token/token_type/user/password_change_required` | `app/main.py:349-357` |
| 既有可复用的 seed 接缝：`install_demo_credentials(target)`（目标不在场⇒整份复制模板，零 Argon2；在场⇒只朝那一个文件补种；动手前先过保护集这一关） | `tests/sec_a_seed.py:101-121` |
|  sanctioned 用法先例：`install_demo_credentials(self.db_path)` **在 `init_usage_db` 之前**（文件还不存在⇒复制，账本表后加） | `tests/test_model_router_v23_contract.py:4127-4131` |
| 会话级护栏把 `CONVERSATION_DB_PATH` 改道到会话临时库，`user_store` 两道闸 + 真库凭据行不增长哨兵 + 逐例判红 | `tests/conftest.py:618-683,746-778` |
| P0 的 runner **只**跑那一枚文件，且只在 `[3/4]` 那一步临时打开开关 ⇒ 接缝的作用域天然是一枚文件 | `.superpowers/scripts/run_p0_failover_acceptance.sh:44,128,146` |
| 闸①把 **kit 的源码**也纳入 skip 家族令牌扫描（非 docstring 字符串常量含 `skip`/`xfail`/`__test__`/`expectedfailure` 即红；`exec/eval/compile/__import__/vars/globals/locals` 裸调用即红） | `test_real_llm_failover_gate.py:289-296` + `:54-64` |

### 1.1 「临时库的表集是不是证据」——核实结论

`kit.validate_evidence()`（`real_llm_failover_kit.py:443-560`）**不读** `ledger.tables`，
也不读第 ⑧ 枚 observed 里的 `tables_in_temp_db`；它只查 `rows==1`、canary、`fallback_index`、
`success`、`model`、禁存列、trace、sha1。闸③的变异探针（`test_real_llm_failover_gate.py:422-452`）
 likewise 只打「模型序 / 错误体 / 账本行数 / sha1」四枚位。全仓 `sqlite_sequence` 只出现在
**已落盘的历史证据 JSON** 与 SDD 报告文字里，没有任何代码把临时库表集当等式来断言。
⇒ **没有"预期集合"需要放宽**；接缝的效应是**新事实进证据**（`tables` 一栏会从
`['llm_request_logs','sqlite_sequence']` 变成含 `user_credentials` 的三枚），描述面变宽、
判据面一根手指没动。这一点会在终稿里单独说明，并把它钉成一条用例（见 §3）。

## 2. 设计（为什么长这样）

- 接缝**定义**住 `tests/real_llm_failover_kit.py`：它已经是 P0 的 harness 真源
  （`init_usage_db` 的调用面、`ledger_rows`/`other_tables`/`validate_evidence`/`config_overrides`
  都在它手里），凭据来源也是同一层的 harness 事实。
- 开关**唯一**：`install_login_credential_seam()` 内部只问 `acceptance_enabled()`
  （即 `REAL_LLM_ACCEPTANCE=1`），不合期望时**一个字节都不碰** `app.llm.usage` ⇒ 默认套件恒惰性。
  不在这里长出第二枚条件（与闸②「门只能是一枚 env」同口径）。
- 触发点住 `tests/conftest.py`：sealed 文件的 `setUp` 不能被改，能在它之前动手的只有
  会话级夹具。conftest 只**调用** kit，不复制任何判定/seed 逻辑。
- 包装顺序：先 `install_demo_credentials(target)`、后真 `init_usage_db(target)`——
  复用 `:4127` 那处已 sanctioned 的先后关系（目标不在场⇒复制模板，零 Argon2 重算），
  且**不新增第四条 seed 路径**。

## 3. 待交付（in-flight checklist）

- [ ] kit：`prepare_login_credentials()` + `install_login_credential_seam()` /
      `uninstall_login_credential_seam()` / `login_credential_seam_active()`，定义处写清「为何存在」。
- [ ] conftest：会话级 autouse 夹具一枚，委托 kit，收尾还原。
- [ ] `test_security_a_closure.py`：正向（接缝在场⇒200+键集）/ 负向对照（无接缝⇒401
      `invalid_credentials`，§8.5 fail-closed 保住）/ 惰性（开关不合⇒属性未被替换、库里无凭据表）/
      保护集拒写 / 表集事实只加不减。
- [ ] 聚焦跑 + 记录计数。
- [ ] 终稿：PENDING_EXTERNAL 与 operator 复跑命令。

## 4. 追加记录（随做随写）

### 4.1 实测中的一处**与 brief 预期不同**的事实（重要，如实记下）

brief 的控制器实测两行是：

```
temp DB + ensure_user_credentials_schema() only  -> login admin/admin123 = REJECTED (invalid_credentials)
temp DB + tests.sec_a_seed.seed_demo_credentials() -> login admin/admin123 = OK
```

本轮量到第三行，它才是 P0 的真实形状：**P0 的 `setUp` 只调 `usage.init_usage_db()`，那一枚
`_SCHEMA` 里只有账本表，凭据面连 schema 都不在场**（`app/user_store.py:110` 明写"读函数不建表，
唯一建表者是 `ensure_user_credentials_schema()`"，全仓非测试调用点只有 `app/cli.py:165/195` 那两条
`credentials` 腿，`app/main.py` 的启动钩子里没有）。于是**没有接缝的 P0 登录腿拿到的不是 401，
而是一条从 TestClient 里冒出来的 `sqlite3.OperationalError: no such table: user_credentials`**
（首版负向对照就是在这里红的，不是判据写错，是事实比 brief 更硬）。

结论两句话，都没动 `app/`：
1. §8.5 的"schema 在、行不在 ⇒ 统一 401 `invalid_credentials`"是真事实，接缝不在场时**照旧成立**
   ⇒ 已由 `test_p0_login_leg_without_the_seam_stays_fail_closed` 钉住（补上
   `ensure_user_credentials_schema()` 后测，与控制器那两行同形）。
2. "P0 单靠 `init_usage_db` 连 schema 都没有"这条更难看的事实**也钉住了**
   （`test_harness_entry_point_alone_leaves_no_credential_schema`），它证明接缝**没有**在产品侧
   长出自动建表/自动建号那条腿：接缝种行走的仍是唯一那枚建表者 + 唯一那条写腿。

### 4.2 落地的三处（每处一次写操作，行尾按实测 LF 原样）

- `backend/tests/real_llm_failover_kit.py` 新增 §5.5（+105 行）：
  `prepare_login_credentials()` / `install_login_credential_seam()` /
  `uninstall_login_credential_seam()` / `login_credential_seam_is_installed()` /
  `CREDENTIAL_TABLE`；模块 docstring 的"诚实边界"多一枚 bullet（接缝为何存在、为何惰性）。
- `backend/tests/conftest.py` 新增会话级 autouse 夹具 `p0_login_credential_seam`（+25 行），
  **只调用** kit，判据与 seed 逻辑一处都不复制；`installed` 才拆，收尾还原属性。
- `backend/tests/test_security_a_closure.py`：3 枚 → **11 枚**（+8），docstring 同步说明这一段
  证的是接缝而不是产品。

### 4.3 聚焦跑（本轮全部离线，零外呼、零 provider key、零 Ollama）

| 命令（cwd=`backend/`） | 结果 |
| --- | --- |
| `python -m pytest tests/test_security_a_closure.py -q --durations=5` | **11 passed**, 27.86 s（最慢一枚 25.26 s = 首格付的那一次 Argon2 模板运算，之后同进程复用） |
| `python -m pytest tests/test_real_llm_failover_gate.py tests/test_secret_hygiene_contract.py -q` | **60 passed + 11 subtests**, 26.15 s（闸①对 kit 源码的 skip 令牌扫描仍零命中；SECA-20 豁免表==命中表未被我的改动挪动） |
| `python -m pytest tests/test_model_router_v23_contract.py -q -k "LedgerIsolationGuard or LedgerGuardClassification"` | **8 passed**, 24.06 s |
| `python -m pytest tests/test_credentials_contract.py -q -k Guard` | **14 passed**, 1.31 s |
| `python -m pytest tests/test_llm_usage_contract.py -q` | **101 passed + 33 subtests**, 24.04 s（`init_usage_db` 最近的邻居 ⇒ 默认套件惰性） |

每枚聚焦跑的会话收尾都过了 conftest 的两枚哨兵（真库 `llm_request_logs` 零行、真库凭据行不涨），
没有任何一次把凭据写进保护集；`git status` 对
`backend/tests/test_real_llm_failover_acceptance.py` 为空、mtime 早于本会话 ⇒ sealed 文件一字未动，
其 `del` 收集门未动（默认收集 0 枚 / 开关注入后恰好 1 枚由闸②双向钉着，本轮实测通过）。

### 4.4 「表集是不是证据」的结论：**没有一处预期被放宽**

`kit.validate_evidence()` 与闸③的变异探针都不读 `ledger.tables` / `tables_in_temp_db`
（读的是 `rows==1`、canary、`fallback_index`、`success`、`model`、禁存列、trace、sha1）；
全仓 `sqlite_sequence` 只出现在**已落盘的历史证据 JSON** 里，没有代码把临时库表集当等式断言。
⇒ 我没往任何"预期集合"里加 `user_credentials`（那会是发明一枚新闸），也没有从集合里删东西
（那才是放松）。会变的只有**描述面**：接缝在场时那份新证据的
`ledger.tables` / 断言 ⑧ 的 `tables_in_temp_db` 从 `['llm_request_logs','sqlite_sequence']`
变成含 `user_credentials` 的三枚 —— 这是"这次真跑脚下有一张凭据表"的现场事实，
operator 复跑时**应当**看到它；看到不了才要查。

顺带两条不失效的旧事实：接缝**不往账本里塞行**（`kit.ledger_rows(db)==[]` 已钉，P0 的
`rows==1` 判据不受污染）；`files_sha1` 覆盖的是临时库/临时 trace/探针件/**sealed 用例源码**，
**不含 kit** ⇒ 本轮改 kit 不会把 V2.3 那份已成立证据判成 stale（改 sealed 文件才会）。

## 5. 本会话证明不了的（PENDING_EXTERNAL）

- **整条 P0 复跑**：`_http_face_200`（第 ⑩ 枚，含 `:686` 那枚登录）只在两次**真** Ollama 外呼
  之后才可达。本机前提按项目笔记成立：OpenAI key 为空、`ornith-1.5:9b-text` 装不起来
  （A-2 探针件里就是它的加载失败原文），phi3:mini 真加载还要 ≥3.2 GiB 余量。
  ⇒ 端到端"接缝让 sealed P0 从红转绿"这一句是 **PENDING_EXTERNAL**，我没有跑它，也没有花一分钱。
- operator 复跑命令（唯一入口，含内存前置与许可判定）：

      cd E:/xiangmu/rag
      bash .superpowers/scripts/run_p0_failover_acceptance.sh            # 需要显式越权时加 --yes
      # 等价手工：cd backend && REAL_LLM_ACCEPTANCE=1 python -m pytest tests/test_real_llm_failover_acceptance.py -q -s

  复跑时**预期看到**：登录腿 200、证据里 `ledger.tables` 多出 `user_credentials`、
  `self_validation_problems` 为空。若仍 `no such table: user_credentials` ⇒ 说明那一跑的
  `REAL_LLM_ACCEPTANCE` 没在会话起点摆着（接缝的唯一门），先查开关而不是查接缝。

## 6. 遗留关切（交给 reviewer / 主 agent）

1. brief 的"fail-closed = 401"这句在**P0 的确切路径**上其实是"schema 缺失 ⇒ OperationalError"。
   产品侧要不要把"表不存在"也归一进 §8.5 的失败语义，是 SEC-A 之外的裁决（本轮不动 `app/`）。
2. 真机跑若哪天有人用 `REAL_LLM_ACCEPTANCE=1` 跑**整套件**（runner 不是这么做的），接缝会给
   每枚 `init_usage_db(显式路径)` 的临时库都垫上凭据表。今天没有任何用例断言"临时库里没有
   `user_credentials`"，所以那不会静默变红——但这条边界值得在 V2.4 里说明。
3. `credential_template()` 那一格 25 s 是本机 Argon2 档位（§8.7 的 L3 同源），只在模板首建时付。

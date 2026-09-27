# SEC-A 验收报告 — 认证与密钥基线（Security Quick Wins）

日期：2026-09-27（签发日；文件名按 `task-10-brief.md` T10-1 更正为 `2026-09-26`，见 §14）
范围：`rag/backend`（SEC-A 子规格，Task 1–9 + 10a/10b/10c/10d/10f/10g + 10e 收口 + **10h 终审收口**）
规格：`docs/SECURITY_A_SPECIFICATION.md`（§20.1–§20.6 七轮回写均已落地；10h 追加 **§20.7** ⇒ 共八轮。
**其中 §20.5 / §20.6 / §20.7 这三轮都发生在 §19 的冻结裁定之后，性质是"交付面变更"或"纠正规格自己写过的
过度声称"，三处均需用户确认**：§20.5 新增一枚 CLI 动作、§20.6 给 lifespan 加一次建表 DDL、§20.7 纠正三句
过度声称（§17 L6 的"旧口令永久失效" / §19 裁定 5+§12 SECA-20 的"与 CI 同一道门" / §9.3 切换点漏两张落盘面），
判据一律不放宽）
计划：`docs/SECURITY_A_PLAN.md`　台账：`.superpowers/sdd/SECURITY_A_PLAN/progress.md`
过程件：`.superpowers/sdd/SECURITY_A_PLAN/task-{1..9}-report.md`、`task-9-fix-report.md`、
`task-10a-report.md`、`task-10b-report.md` + 同目录那枚 `10b` 变异台原始跑记录（`…-mutations-run.txt`）、`task-10c-report.md`、
`task-10d-report.md`、`task-10f-report.md`、`task-10g-report.md`、`task-10e-report.md`
版式：`docs/MODEL_ROUTER_V23_ACCEPTANCE_2026-09-24.md`

## 1. 结论

**CONDITIONAL PASS。**

| 判据 | 结果 |
| --- | --- |
| §12 矩阵 **27 行** | **26 GREEN / 1 PENDING_EXTERNAL / 0 BLOCKED**（唯一的非 GREEN 行是 SECA-24，见 §3 末行与 §10） |
| §15.2 一票否决项（01/02/03/04/04b/05/07/09b/10/13/17/18/23） | **十三枚全 GREEN**，无一枚被谈判过 |
| §13 变异台 19 发 | **19/19 KILLED**，退出码 0，每发 `finally` 还原并比 sha1（`task-10b-report.md` §1、`10b` 变异台原始跑记录（`…-mutations-run.txt`））；终态树上 19 枚锚点复验仍**逐枚唯一**（`10e-anchor-check.txt`：`19/19 锚点唯一`） |
| `legacy_count`（真实库、带外只读） | **0**（`closure-real-db-legacy-count.txt:1-2`；终态镜像内复算 `legacy rows: 0`，`task-10e-smoke-final.txt`）⇒ 按 §8.7 该读 `BLOCKED` 的那条分支没有触发 |
| §15.1 release gate 九步 | **第 1–5、7–8 步成立，第 6 步按 §6 那行拆开写**（成立的是稳态收敛 + 四场景 + 镜像；不成立的是"升级那一次走随版交付的 `credentials migrate`"——导入腿当时经 `import_from_artifact()` 手工执行，那条 CLI 未在部署形态跑过）；**第 9 步（提交 + tag）按 Step 8 是停止点，本报告不代拍**（§15） |
| 全套件两 cwd 对账（Step 6） | **逐位相同**（§7） |
| 为什么不是 `PASS` | 一枚 PENDING_EXTERNAL：SECA-24 的"8 处既有登录调用点"里，第 8 处住在被哈希封存的 V2.3 真机文件内，默认**不被收集**，本机没有可跑的真实 LLM 现场（无 provider key、`ornith-1.5:9b-text` 载不动）⇒ 见 §10 的运维复跑命令 |
| 必须随版交付的 breaking change | **一次强制重登录**（§9 末尾那条），不得写成"无感升级"。且对界面用户：改密那条腿**目前没有 UI 入口**（新增 L20 行，只能走 CLI/API），登录页对 `user` 的一键填充口令已随 10a 的那次轮换失效 ⇒ 该账号在 UI 上登不进去，恢复只有一条 CLI 路（§12.1） |

### 1.1 为什么本文件里有两套 Argon2 / smoke 数字

`task-10a-report.md` 的镜像 `1abba3717aa7` 建于 2026-09-26 **17:42**，而它之后又落了 10c（`credentials migrate`）、
10d（`credentials.py` 死代码删除 + `needs_rehash` 异常分类、`login_throttle.py` 的 `_last_sweep` 惰性播种）、
10f/10g（P0 接缝 + lifespan 建表）⇒ 首测测在**非终态**的部署形态上。规格 §14 的 after 面与 §17 L3
（"这台机器的内存是真实约束"）要的是发布形态的读数，因此 10e 按控制器追加一重建镜像并复跑：

| 读数 | 首测（镜像 `1abba3717aa7`，17:42） | **终态（镜像 `3f14b3de77a4`，00:21）** |
| --- | --- | --- |
| 容器串行 verify P50 / P95 | 50.3 / 55.3 ms | **18.8 / 25.3 ms** |
| 容器并发 P95（闸门满配 2 worker × 32） | 66.7 ms | **40.9 ms** |
| 容器峰值 RSS 增量 | 39 280 KiB（38.4 MiB） | **39 280 KiB（38.4 MiB）** |
| `verdict` 字段 | `GREEN` | `GREEN` |

终态数**没有一项越界**（反而更快），所以 SECA-19 保持 `GREEN`；两套房都留着，是为了让后来人能看出
"测在哪一枚镜像上"这件事本身是可查的。判据只认容器数——**出处是 §15.2 那条 verdict 规则**（规格
`docs/SECURITY_A_SPECIFICATION.md:604`：依赖或容器资源导致不可测 ⇒ `BLOCKED`，"**不得用宿主数据替代容器证据**、
不得降档、不得放宽规格"；10h 按终审 Minor 把出处从 §14 改成这一条，§14 讲的是取证形态而不是判据档位）。
宿主数在 §5 的对照栏。

## 2. 交付了什么

- **口令原语**：`backend/app/credentials.py`——Argon2id 档位常量 `t=2 / m=19456 / p=1`
  （`:25-27`，OWASP 最低推荐档，`v=19` 是算法版本不是项目版本）、`BoundedSemaphore` 并发闸门
  （`:58`）、哑校验、legacy 判定、`needs_rehash`（10d 起把库异常翻成 `CredentialConfigError`，
  库异常不逃出边界模块）。**强度参数不是运维旋钮**（SEC-A-008），M16 那发变异专门为此而存在。
- **凭据状态持久层**：`backend/app/user_store.py`——`user_credentials` 表、写函数签名不含
  `algorithm` 取值、hash 与 `credentials_version` bump 同事务、唯一建表者
  `ensure_user_credentials_schema()`（读路径不建表，理由写在 `:105-113`）。
- **身份声明层**：`backend/app/directory.py` + `backend/config/users.json`（企业唯一身份源，出厂为空）
  + `backend/config/users.demo.json`（dev/test 才加载）。身份与凭据**分家**（SEC-A-010），
  两个文件都结构上无口令字段。
- **受限迁移路径**：`backend/app/credentials_migration.py`（整件拒收、绝不把已升级行降回 legacy）
  + 运维显式入口 `python -m app.cli credentials migrate`（10c，§20.5 那次交付面增补）。
- **认证腿**：`backend/app/auth.py`——两层节流（pre-hash `(username, ip)` / 持久锁定按 `username`）、
  哑校验统一失败面、渐进重哈希（**保留** `must_change`，`auth.py:331`）、令牌 `cv` 纪元与
  `must_change` 门。`auth.USERS` 与那枚无盐 SHA-256 生产函数**删除**，不留兼容视图。
- **令牌与改密/重置**：`POST /api/auth/password/change`、`POST /api/admin/users/{username}/password/reset`、
  CLI `credentials {bootstrap-admin,reset,migration-status,migrate}`；口令只经 `CREDENTIALS_PASSWORD`
  进 CLI，argv 上没有接收口令的开关。
- **secret 卫生**：`app/security.py` 的 `redact_for_persistence()`（精确全词键名黑名单，
  授权凭据库例外）、`app/security_startup.py` 的三件同生同死守卫、`.env.example` 的 §10 键面、
  交付面密钥扫描以**普通 pytest 契约测试**落地。**这道门今天是真的，但只在本地真**（终审组三第 4 条
  的更正，勿照抄旧版那句"落在既有 `backend-contracts` job 上"）：实测 `.github/workflows/ci.yml:10-25`
  那枚 job **没有任何依赖安装步**，跑的是 `python -m compileall`（`:16`）+ `python scripts/validate_demo_assets.py`
  （`:17`）+ `python -m unittest discover -s backend/tests`（`:18`）⇒ ①`argon2-cffi`（`backend/requirements.txt:13`）
  没有任何 job 装过，SEC-A 的契约文件在 CI 里连 import 都过不去；②`unittest discover` **收不到裸 pytest 函数**，
  而扫描门自己（`test_secret_hygiene_contract.py::test_repository_tracked_files_hold_no_credential_material`）
  正是裸函数——SEC-A 那六枚契约文件里这样的函数共 **40 枚**（该文件 23 + `test_security_a_closure.py` 17），
  今天在 CI 里一枚都不跑。⇒ **这句是 10h 的实测状态，2026-09-27 已被用户裁定的"修 CI 而不是放宽规格"部分关闭**：
  `backend-contracts` 现在装了扫描门自己的最小依赖并显式跑扫描子集（5 枚），且排在会失败的既有步之前；
  取证见 §3 SECA-20 与规格 §20.8 卡 D。**仍成立的那一半**：其余 5 枚 SEC-A 契约文件（40 枚裸函数里的大部）
  还是只在本地，前置条件已登记 SEC-B：`backend-contracts` 要先有
  `pip install -r backend/requirements.txt` 与一枚 pytest runner。**本地这道的实测读数**：
  `10e-secret-gate.txt` ⇒ `46 passed`、RC=0（10h 复跑见 §7.2 末与 §14）。不新增专用 security job。
- **测试地基**：`tests/sec_a_seed.py`、`tests/sec_a_fixtures.py`、`tests/conftest.py` 的会话级
  凭据面改道护栏（10g 起为 lifespan 那一枚 DDL 开了唯一的例外闸，并把它自己的效应钉住）、
  审计汇改道（控制器直接修：`isolated_audit_sink`，见 §11 末）；六枚 SEC-A 契约文件 +
  `test_security_a_closure.py`（17 枚）。
- **P0 接缝（harness 侧）**：`tests/real_llm_failover_kit.py` §5.5 的
  `install_login_credential_seam()`，仅由 `REAL_LLM_ACCEPTANCE=1` 上膛；**封版文件一字未动**
  （实测 sha1 `da92cdf51de5dbfad3107f1dc744d18e4173e07c`，与 `task-10g-report.md` §7 记录值相同）。

## 3. §12 测试矩阵（27 行，状态词汇表严格三值）

每行状态后面是可指的证据：文件 + 段/行，或 JSON 字段名。`GREEN` 的判定形态一律是 §12 第三列写的
**行为断言**，不是注释。

| ID | 不变量 | 状态 | 证据指针 |
| --- | --- | --- | --- |
| SECA-01 | SEC-A-001 新建口令恒 `argon2id` | GREEN | `test_credentials_contract.py::Argon2ProfileTests::test_hashed_password_is_a_verifiable_argon2id_phc_string`（M1 杀点，`10b` 变异台原始跑记录（`…-mutations-run.txt`） M1 行）+ 终态镜像真实库分布 `[('argon2id', 5)]`（`task-10e-smoke-final.txt` 容器 SQL 段） |
| SECA-02 | SEC-A-002 明文口令不落持久面 | GREEN | `test_secret_hygiene_contract.py`（SECA-02 面：改密后 `audit.jsonl`/`agent_traces.jsonl`/DB 全文扫新口令 = 0）+ `test_password_lifecycle_contract.py::CliTests` 的「argv 会被 ps 与 shell history 观察到」那枚钉 + 10a C.7「no 口令 appears anywhere in the body -> True」（`task-10a-report.md` C.7） |
| SECA-03 | SEC-A-003 升级路径端到端 | GREEN | `test_authentication_leg_contract.py::LegacyUpgradeTests::test_a_legacy_digest_still_logs_in_and_is_upgraded_in_place` + `HttpMustChangeGateTests::test_after_the_password_change_the_data_face_opens`；部署形态那一次：`task-10a-report.md` C.3→C.4→C.7（导入 5 枚 legacy → 5 次真登录 → `legacy_count=0` → 改密后数据面 403→200、旧 token 401）；M9 杀点 `UserStoreSchemaTests::test_created_rows_are_always_argon2id` |
| SECA-04 | SEC-A-004 稳态零遗留 + 三处扫描 | GREEN | 带外真实库读数 `closure-real-db-legacy-count.txt:1-2`（`REAL_DB legacy_count=0`）+ 容器内同文件复算（同件 `:7-8`，bind mount 拓扑见 T10-8）+ `test_security_a_closure.py` 三条（`app/`、`config/` 两处的静态自证 + 库半边）+ 终态镜像 `migration-status` 行 `legacy_count=0 argon2id_count=5`（`task-10e-smoke-final.txt` 末段）；工件与其快照副本删除见 10a C.8（两枚 sha1 同值 `19cc628acbae`） |
| SECA-04b | §8.2 全新安装 ≠ 升级路径（两格） | GREEN | 格①"表在场零行"：`test_authentication_leg_contract.py::SourceRemovalTests::test_enterprise_mode_with_no_credentials_fails_closed_rather_than_500`（M19 杀点在同名类的另一枚）；格②"表不在场冷启动"：**部署形态**证据 `task-10e-fresh-boot.txt`（空 data 卷、`PRE {"db_file_present": false}` ⇒ `POST` 表清单含 `user_credentials`、`credential_rows: 0`，登录 `401`、`NOT_500=True`、两格响应体 `BODIES_IDENTICAL=True`）；**该发现在可从仓库复现**：探针脚本已入库为 `scripts/sec_a_fresh_boot_probe.py`，10h 用当前镜像 `3f14b3de77a4` + 一次性卷 `rag-seca-10h` 复跑，输出与那份转录逐行相同（留档 `10h-fresh-boot-rerun.txt`，见 §14）；容器侧同一事实的测试面版：`test_security_a_closure.py` 的 10g 那六枚 |
| SECA-05 | SEC-A-005 哈希单点 | GREEN | `test_credentials_contract.py::CentralisationScanTests::test_only_credentials_module_hashes_passwords` + `::test_the_exemption_table_is_equal_to_the_hit_set`（双向等值：多一处红、过期豁免也红）；M13 杀点即这两枚 |
| SECA-06 | SEC-A-006 既有基线全绿 | GREEN | §7 的两 cwd 对账行（1316 passed / 0 failed / **0 skipped**）；§16 第一组逐条见 §8。注：`test_real_llm_failover_acceptance.py` 默认收集 0 枚，那一处调用点的真实面判据记在 SECA-24，不在此行自证 |
| SECA-07 | SEC-A-010 身份文件塞口令 ⇒ 拒启动 | GREEN | `test_user_directory_contract.py::IdentityFileTests::test_unknown_extra_fields_are_rejected_not_ignored`（M12）+ `ShippedIdentityFilesTests::test_both_files_ship_and_pass_their_own_validator`、`::test_demo_mode_ships_exactly_the_demo_accounts`（M15：把 legacy 摘要写进 `config/` 即红）；"企业形态根本不读 demo 文件"是结构事实，见 `directory.py` 的加载分支与 `task-4-report.md` |
| SECA-08 | §6.1 列名集合 | GREEN | `test_credentials_contract.py::UserStoreSchemaTests`（列面等值 + 明文字段"不存在可写的地方"那枚 docstring 判据）；10d 另补了"绕过函数直插第三算法值必 `IntegrityError`"的 CHECK 钉（`task-10d-report.md` §1 表 2.8） |
| SECA-09 | T5 改密/重置废 token | GREEN | `test_password_lifecycle_contract.py::TokenRevocationTests::test_a_bumped_version_invalidates_the_previously_issued_token`（M3 杀点）+ 部署形态：10a C.7 的"pre-change token → 401 `无效登录凭证`" |
| SECA-09b | §7.5 无 `cv` claim 即拒 | GREEN | `test_password_lifecycle_contract.py::TokenRevocationTests::test_a_pre_seca_token_without_cv_is_rejected_not_allowed`（M17 杀点）+ 反向钉"不存在缺 `cv` 即放行的兼容分支"（10b §2 的 M17 行：注入形态就是 `claimed is None → 放行`） |
| SECA-10 | §8.4 门覆盖面由路由表生成 | GREEN | `test_password_lifecycle_contract.py` 的覆盖面门（M2 杀点 `SelfServiceChangeTests::test_changing_password_logs_in_clears_the_gate_and_kills_old_tokens`；枚举报 41 条、白名单等值钉两项）；部署形态：`task-10e-smoke-final.txt` S3（数据面 403 + `detail == 「当前账号需先修改口令」`，白名单腿 `/api/auth/me` 200） |
| SECA-11 | §8.8 hash 与 cv 同事务 | GREEN | `test_credentials_contract.py::UserStoreTransactionTests::test_password_change_bumps_version_and_clears_lock_state_together`（M10 杀点）；**残留如实记**：10b §2 的 M10 行写明"今天没有用例把'新 hash + 旧 cv'当 DB 事实观察，因为实现里两者是同一条 SQL、该状态不可表示"——M10 证明的是"若哪天拆开，门仍会红" |
| SECA-12 | §8.8 重置同事务清锁 | GREEN | `test_password_lifecycle_contract.py::AdminResetTests::test_admin_reset_clears_a_stale_lock_in_the_same_transaction`（M11 杀点）+ CLI 半边同一写路径的用例 |
| SECA-13 | T4 四态不可区分 | GREEN | `test_authentication_leg_contract.py::UnifiedFailureTests::test_all_four_states_return_the_same_user_and_audit_detail` + `::test_all_four_states_consume_exactly_one_argon2_run_each`（`:404`，四态共 4 次、同档位、同一单例）+ `::test_a_wrong_password_on_a_legacy_row_consumes_one_argon2_run_too`（`:420`）——坐标取自 `progress.md` 末段"10e 要引的结构证据坐标"；**latency 分布只作证据、不参与判定**（§14 那一行同口径） |
| SECA-14 | §7.4 锁定脸 | GREEN | `test_authentication_leg_contract.py::LockedHttpFaceTests::test_locked_wrong_password_and_unknown_account_are_the_same_http_face`（M5 杀点）+ 部署形态 `task-10e-smoke-final.txt` S4：正确口令被锁 ⇒ 401、与统一失败面**字节相同**（sha1 `3b9054717ae8`）、响应体无「锁定」字样、`AUTH_LOGIN_LOCKED` 只在审计面 |
| SECA-15 | §7.1 超限不做昂贵运算 | GREEN | `test_authentication_leg_contract.py`（SECA-15 那两枚调用面 spy：闸门在 Argon2 之前）+ `PasswordCapacitySurfaceTests::test_a_locked_account_shares_the_capacity_face_instead_of_leaking_a_401`（耗尽时锁定脸与未知账号脸逐字节同为 503） |
| SECA-16a | §7.2 throttle 键含 ip | GREEN | `test_authentication_leg_contract.py::ThrottleLayerTests::test_two_source_addresses_on_the_same_username_have_independent_buckets`（M6 唯一杀点） |
| SECA-16b | §7.2 账号锁只看 username | GREEN | `ThrottleLayerTests::test_many_source_addresses_on_one_username_share_the_account_lock`（M7 重锚后的杀点，`task-10b-report.md` §2 的 M7 行写明了重锚理由） |
| SECA-17 | SEC-A-009 脱敏双向 | GREEN | `test_secret_hygiene_contract.py`：`test_the_persistence_deny_set_matches_case_insensitively`（M8）、`test_persistence_redaction_kills_sensitive_keys_by_exact_name`、`test_persistence_redaction_covers_the_full_deny_set_not_just_the_spec_sample`；SECA-17 的反方向（`input_tokens`/`output_tokens` 必不误伤）与"写盘路径不经通用 redactor"（M9 杀点即 `test_created_rows_are_always_argon2id`）同文件 |
| SECA-18 | §8.5 三守卫同生同死 + 拒启动不得已建表 | GREEN | `test_secret_hygiene_contract.py::StartupGuardLifespanTests`（直调 `evaluate_startup_guards`，不借 lifespan）+ 控制器 00:20 补的第二格 `test_a_refused_boot_creates_nothing`（`tests/test_secret_hygiene_contract.py:309`，§8.5 顺序契约"先拒坏配置再谈落盘"；已证伪：lifespan 两步调换 ⇒ 该枚红、还原 sha1 一致） |
| SECA-19 | SEC-A-008 + T8 容器基准 | GREEN | **`argon2-benchmark-container-final.json`**：`serial.p95_ms=25.3` / `concurrent.p95_ms=40.9` / `peak_rss_delta_kib=39280` / `verdict="GREEN"`，预算 `budget={1500.0, 3000.0, 262144}`；环境 `environment="linux"`、`environment_detail.python="3.12.14"`、镜像 `3f14b3de77a4`（源码逐枚 sha1 与现树相同，见 `task-10e-report.md` A.1）。首测那份（`argon2-benchmark-container.json`）与宿主对照见 §1.1 与 §5 |
| SECA-20 | G0 扫描门 | GREEN | `test_secret_hygiene_contract.py` 的交付面扫描（tracked ∪ 未忽略 untracked，`豁免表 == 命中表`，按 (文件, 处数) 互等）+ 证伪枚"植一枚假凭据即红"；台账 `progress.md` Task 9 complete 行：面 254 文件 / 16 命中 / 31 处、`EXEMPTIONS` 一行未加。**10h 复量：交付面 258 文件 / 16 命中 / 31 处、`EXEMPTIONS` 仍一行未加**（254→256 是 10e 那轮，+2 是 D1 入库的两枚探针脚本 `scripts/sec_a_fresh_boot_probe.py`、`scripts/sec_a_smoke_http.py`——它们进了扫描面，写法改成按 env 取口令，所以命中数一格未涨、没有新增豁免行）。**CI 侧已在 2026-09-27 按用户裁定关闭**（"修 CI，不放宽规格"）：`backend-contracts` 新增 step 3 装扫描门自己的最小依赖 + step 4 跑扫描子集（5 枚），两步刻意排在既有 `unittest discover`（step 7）**之前**——GitHub 一步失败即中止后续步骤，排后面等于永远不跑。本地以**逐字相同的命令**在干净 venv 取证：基线 `5 passed` → 植一枚真形状假凭据 `2 failed / rc=1` → 删除探针 `5 passed / rc=0`、`git status` 无残留（取证经过与一条附带发现见规格 §20.8 卡 D：**第一次植入我用了夹具惯用的拼接写法，门不红**——那正是夹具躲门的合法通道，也是 §18 坚持要带 git 历史的第三方扫描器的理由）。余下 5 枚 SEC-A 契约文件仍只在本地（需完整依赖 + 该 job 的 runner 是 `unittest`），登记 §11。本报告自身的效应复量见 §7.2。**远端往返的真实经过**：首版接入（`f6c67b5`）在 CI 上把这一步**跑红了** —— `ModuleNotFoundError: No module named 'httpx'`（`backend/app/llm/provider.py:30`，收集期经 `conftest` 会话夹具 → `sec_a_seed` → `app.llm.*`），因为我写进 `ci.yml` 的四包清单**不等于**我本地干净 venv 实测时那一包集合。修正为与 `backend-integration` 同源的那套轻量依赖后（`e5ff798`），远端该步 **success**（`gh run view 36295632046` 步骤读数：Install ⇒ success、Run SECA-20 ⇒ success、其后既有 `unittest discover` ⇒ failure，即 L21 那格）。教训写进规格 §20.8 卡 D：**"本地等价执行"必须连 CI 的安装清单一起等价，否则证的不是同一件事。** |
| SECA-21 | §8.3 冻结裁定（写盘失败不翻脸） | GREEN | `test_authentication_leg_contract.py::LegacyUpgradeTests::test_a_rehash_write_failure_still_logs_in_and_records_degraded`（M14 杀点，反向证明那条裁定不是空话）+ `::test_capacity_loss_at_the_rehash_hop_degrades_instead_of_refusing_the_login` |
| SECA-22 | 遥测污染护栏 | GREEN | 会话护栏（`tests/conftest.py` 的凭据面两道闸 + 真库行数不增长哨兵 + 逐例归责）+ 10g 为 lifespan DDL 开的唯一例外闸自带效应钉 `test_security_a_closure.py::test_the_widened_guard_lets_through_exactly_that_one_ddl`；审计面新增 `AuditSinkIsolationTests` 两枚；全套件收尾两行见 §7.1。**规格字面 vs 已裁形态**：§12 该行写"测试结束后 `data/conversations.db` 无 `user_credentials` 行"，而真实库今天**有** 5 行（release gate 第 6 步的收敛证据本身）；判定形态按 `progress.md` 的 I5 裁定取"会话期间不增长"，本行按该形态判绿，字面差异写在这里而不是被抹掉 |
| SECA-23 | §6.4 身份合并不变量 | GREEN | `test_user_directory_contract.py::IdentityFileTests::test_duplicate_username_across_files_fails_instead_of_letting_demo_override`（M18 杀点）+ `MergeInvariantTests::test_duplicates_inside_one_file_are_rejected_too`、`::test_the_conflict_message_names_the_clashing_identity_and_who_tried`；`enabled=false` 归入统一失败面由 `UnifiedFailureTests::test_a_disabled_identity_cannot_log_in_even_with_a_valid_password` 守 |
| SECA-24 | §8.2 fixture 契约（8 处调用点） | **PENDING_EXTERNAL** | 七处在套件内实测原样绿（`test_authentication_leg_contract.py::SourceRemovalTests::test_every_demo_login_path_is_argon2_after_the_seed`、`::test_the_session_seed_happened_exactly_once` = 会话级一次 seed 的计数钉）；第 8 处 = `backend/tests/test_real_llm_failover_acceptance.py:686`，**默认不被收集**（本轮实测：不带开关跑该文件 ⇒ `no tests ran`，带 `REAL_LLM_ACCEPTANCE=1` 仅收集 ⇒ `1 test collected`），其真机复跑本机不可达（无 key、`ornith` 载不动）。接缝本身离线钉住（`task-10f-report.md` §4.2/§4.3、closure 文件那 8 枚）。等什么、怎么复跑见 §10 |

## 4. §13 变异台 19 行

判据：每发至少杀一条测试；`TARGET-NOT-FOUND` / `ANCHOR-NOT-UNIQUE` 都不动树。**没有一发是靠撤变异收口的**。

| 发 | 攻击的性质 | SECA 行 | 结果 | 杀点（首个具名用例） |
| --- | --- | --- | --- | --- |
| M1 | Argon2 换成 `hashlib.sha256` | SECA-01 | KILLED | `Argon2ProfileTests::test_hashed_password_is_a_verifiable_argon2id_phc_string` |
| M2 | 去掉 `must_change` 门 | SECA-10 | KILLED | `SelfServiceChangeTests::test_changing_password_logs_in_clears_the_gate_and_kills_old_tokens` |
| M3 | `require_user` 不再比对 `cv` | SECA-09 | KILLED | `TokenRevocationTests::test_a_bumped_version_invalidates_the_previously_issued_token` |
| M4 | 未知账号早退（删哑校验） | SECA-13 | KILLED | `UnifiedFailureTests::test_all_four_states_consume_exactly_one_argon2_run_each` |
| M5 | 锁定路径泄露"锁定"字样 | SECA-14 | KILLED | `LockedHttpFaceTests::test_locked_wrong_password_and_unknown_account_are_the_same_http_face` |
| M6 | throttle 键去掉 `client_ip` | SECA-16a | KILLED | `ThrottleLayerTests::test_two_source_addresses_on_the_same_username_have_independent_buckets` |
| M7 | 计数键改按 ip（账号锁永不成立） | SECA-16b | KILLED | `ThrottleLayerTests::test_many_source_addresses_on_one_username_share_the_account_lock` |
| M8 | redact 改子串匹配 `token` | SECA-17 | KILLED | `test_the_persistence_deny_set_matches_case_insensitively` |
| M9 | redactor 作用域扩到 `user_store` | SECA-17 + SECA-03 | KILLED | `UserStoreSchemaTests::test_created_rows_are_always_argon2id` |
| M10 | cv bump 拆到独立事务 | SECA-11 | KILLED | `UserStoreTransactionTests::test_password_change_bumps_version_and_clears_lock_state_together` |
| M11 | 重置不清 lock 状态 | SECA-12 | KILLED | `AdminResetTests::test_admin_reset_clears_a_stale_lock_in_the_same_transaction` |
| M12 | 身份 schema 放开 `extra` | SECA-07 | KILLED | `IdentityFileTests::test_unknown_extra_fields_are_rejected_not_ignored` |
| M13 | 业务代码新增一处口令 `hashlib` | SECA-05 | KILLED | `CentralisationScanTests::test_only_credentials_module_hashes_passwords` |
| M14 | 重哈希写盘失败改为拒绝登录 | SECA-21 | KILLED | `LegacyUpgradeTests::test_a_rehash_write_failure_still_logs_in_and_records_degraded` |
| M15 | 把 legacy 摘要写进 `config/` | SECA-04 / SECA-07 扫描面 | KILLED | `ShippedIdentityFilesTests::test_both_files_ship_and_pass_their_own_validator` |
| M16 | `m/t/p` 改从 env 读取 | SECA-19 / SEC-A-008 | **首发生存 → 补测试后 KILLED** | `Argon2ProfileTests::test_the_profile_does_not_budge_when_the_environment_is_poisoned`（10b 新增） |
| M17 | `cv` 缺失即放行 | SECA-09b | KILLED | `TokenRevocationTests::test_a_pre_seca_token_without_cv_is_rejected_not_allowed` |
| M18 | demo 静默覆盖同名企业身份 | SECA-23 | KILLED | `IdentityFileTests::test_duplicate_username_across_files_fails_instead_of_letting_demo_override` |
| M19 | 全新安装缺行时自动导入 legacy | SECA-04b | KILLED | `SourceRemovalTests::test_a_missing_credential_row_never_imports_the_upgrade_artifact` |

三格判据级别的处置都写在报告里而不是糊过去（`task-10b-report.md` §2/§3）：骨架里的 `-x` 被拿掉
（带着它 M6 会先死在收桶时钟那枚用例上，"KILLED"就退化成"有人红了"）；**M7 计划原文打的不是 M7**
（那个 needle 在 `user_store.py` 命中 8 次，且攻击的是 SECA-14 的脸），已按 §13 的性质重锚到计数写入；
**M10 计划原文虽红但红在名字上**，重述成"两笔事务"那发真正的攻击。M16 是本轮唯一一枚"既有测试
居然是绿的"的发现——它暴露 SEC-A-008 那半条强度约束此前**没有判据**，补的用例把环境毒成另一档再断言档位不动。
终态树上 19 枚锚点复验：`10e-anchor-check.txt` ⇒ `19/19 锚点唯一`（`--check` 只读，不动树）。

## 5. §14 before / after 证据（逐行）

| 证据 | before（可复现的取证坐标） | after（终态） |
| --- | --- | --- |
| schema | `docs/SECURITY_A_SPECIFICATION.md:43`（实测表清单：`conversations / messages / message_sources / sqlite_sequence / llm_request_logs`）+ `task-10a-report.md` §0.3（`has user_credentials: False`，重建前复量） | `task-10e-fresh-boot.txt` 的 `POST` 行（lifespan 建表后表清单含 `user_credentials`、`credential_rows: 0`）；列名集合由 `UserStoreSchemaTests` 钉（§12 SECA-08） |
| 算法分布 | `task-10a-report.md` C.3：导入后 `legacy_count=5 argon2id_count=0`，五行 `must_change=1 v1` | `closure-real-db-legacy-count.txt:1-2`（`argon2id=5 / legacy_count=0`）+ 终态镜像 `migration-status`（`task-10e-smoke-final.txt` 末段：`legacy_count=0 argon2id_count=5`，`user` = `v2 must_change=0`） |
| digest 扫描 | 只读取证：`git show HEAD:backend/app/auth.py`（HEAD `bc43ca3`，258 行，整体 sha1 前缀 `86f25888a0ad`）里那 5 枚字面量分别在第 **76 / 82 / 88 / 94 / 101** 行；`USERS` 字典自第 71 行。**本文档不抄摘要值**（§15 的 canary/摘要纪律） | `app/`、`config/` 两处 0 命中：`test_security_a_closure.py` 第一条（M15 证明该 needle 会红）；运行库 0 命中：`closure-real-db-legacy-count.txt:2`；`tests/` 里那 5 枚常量是检测器自己的黑名单（既有例外，见 `task-10a-report.md` D.1） |
| 登录矩阵 | `docs/SECURITY_A_SPECIFICATION.md:38-47`（弱口令直登、无门、无节流、`require_user` 单列「账号不存在」） | 两形态 × {成功 / 错口令 / 锁定 / `must_change`}：`task-10e-smoke-final.txt` S1–S4（终态镜像）+ `PasswordCapacitySurfaceTests`（503 面）+ `HttpFailureSurfaceTests::test_the_four_failure_states_are_identical_on_status_body_and_audit` |
| Argon2 基准 | — | **容器（判据）**：`argon2-benchmark-container-final.json`（`verdict="GREEN"`）；首测对照 `argon2-benchmark-container.json`；**宿主（对照，非判据）**：`argon2-benchmark-host.json`（`environment="win32"`、`peak_rss_delta_kib: null`、`verdict: "NOT_THE_CRITERION"`）——win32 无 `resource` 模块 ⇒ RSS 不可测，脚本刻意不让"缺数"读成"达标"（`task-10a-report.md` D-B1） |
| 令牌生命周期 | `docs/SECURITY_A_SPECIFICATION.md:45`（8 小时、无刷新/登出/撤销，全仓 `logout|revoke|jti|blacklist` 零命中） | SECA-09 / SECA-09b 两行（§3）；`/api/auth/me` 的 `password_change_required` 键面 200 读数在 `task-10e-smoke-final.txt` S3 |
| 安装路径 | — | 升级路径：10a C.2→C.8（`credentials migrate` 的生产入口由 10c 落地并 9 枚用例钉；工件删除后 `artifact_present=False imported=0`）；全新安装：`task-10e-fresh-boot.txt`（空卷冷启动 ⇒ 401 非 500）+ `SourceRemovalTests::test_a_missing_credential_row_never_imports_the_upgrade_artifact` |
| 认证耗时 | — | 调用面记录：`UnifiedFailureTests::test_all_four_states_consume_exactly_one_argon2_run_each`（四态各恰好一次、同档位、同一单例）与 `::test_a_wrong_password_on_a_legacy_row_consumes_one_argon2_run_too`；**latency 分布是证据不是判据**（SECA-13 判定不读耗时表） |
| 套件 | **SEC-A 开工时实测**（规格 §14 那一行的口径；V2.3 的 950 / 961 只作历史事实，L5） | §7 的两行逐位数 |

## 6. §15.1 release gate 九步逐项

| 步 | 内容 | 状态 | 证据 |
| --- | --- | --- | --- |
| 1 | `requirements.txt` 加 `argon2-cffi` + 宿主/容器双向 import 探针 | 成立 | `task-10a-report.md` A.1/A.4（两端都打 `argon2 import OK True`；镜像内 wheel 是 manylinux 二进制 `_ffi.abi3.so`，A.2）；终态镜像内复量 `argon2-cffi 25.1.0` / python 3.12.14（`task-10e-report.md` A.1） |
| 2 | 定向门：SEC-A 新增文件 + `test_rbac_contract` + `test_typesafe_security_contract` + 飞书身份 + branding | 成立 | `10e-directed-gate.txt`：10e 在终态树 + 终态文档面上跑的那一发 = **`492 passed, 10 warnings, 323 subtests passed`，RC=0**（SEC-A 六枚契约文件 + `test_rbac_contract` + `test_typesafe_security_contract` + 飞书身份 + branding；逐枚分解的历史数见 `task-10d-report.md` §3） |
| 3 | 全套件两 cwd 同数 | 成立 | §7 两行 |
| 4 | 变异台 19 发全杀 | 成立 | §4 |
| 5 | 结构扫描三处 0 命中 | 成立 | §5 的"digest 扫描"行 + `test_security_a_closure.py` 三条 |
| 6 | 重建发布镜像 → compose smoke 四场景；升级那一次经导入 + 真登录，`legacy_count` 5→0 两次读数都留证；手工 SQL 归零不算数 | **部分成立（这一格按终审拆开写，不写成"逐项成立"）** | 镜像：`3f14b3de77a4`（`task-10e-build.log`、`task-10e-report.md` A.1）；四场景：`task-10e-smoke-final.txt`（终态镜像）；**5→0 那一次**是 10a 在 17:42 镜像上的一次性事件（`task-10a-report.md` C.3 前读数 `legacy_count=5` → C.4 后 `legacy_count=0`）——**零手工 SQL；但导入腿当时经 `credentials_migration.import_from_artifact()`（`task-10a-report.md` C.3）执行**，也就是"两个公共函数被运维姿势手工串起来"那一格（正是 §20.5 记的那个空洞）。生产入口 `credentials migrate` 由 10c 落地并有 **9 枚用例钉**，但**未在部署形态跑过**：终态镜像里那条 CLI 只被用来读 `migration-status`（`task-10e-smoke-final.txt` 末段）。⇒ 本步成立的是"稳态收敛 + 四场景 + 镜像"，**不成立**的是"升级那一次走的是随版交付的那条命令"。终态镜像复确认的是**收敛后的稳态**，5→0 不在也不该在第二枚镜像上重跑（重跑 = 把已删除的升级工件重新造出来，那才是把门换成删除） |
| 7 | SECA-19 容器基准 | 成立 | §1.1 + §3 SECA-19 行 |
| 8 | 验收文档 verdict | 成立 | 本文件 |
| 9 | 冻结：SEC-A 独立提交与 tag；不触碰 `model-router-v2.3-rc1` | **未执行（刻意）** | Step 8 是停止点：提交清单在 §13，git 写命令一枚未跑（`git status --short` / `git log` / `git show` / `git tag --list` 皆只读）；`model-router-v2.3-rc1` 仅被列出，未被触碰 |

## 7. Step 6 两 cwd 全套件对账（10h 在 C1/C2 + D1 落盘之后重跑，终态树 + 终态文档面）

两行原文（`-q`，含逐枚 warning 与收尾汇总的完整输出留档
`.superpowers/sdd/SECURITY_A_PLAN/10h-suite-both-cwd.log`；10e 那五发原件仍在 `10e-suite-*.log`）：

```text
(cwd=E:\xiangmu\rag\backend) python -m pytest -q
  → 1316 passed, 36 warnings, 1133 subtests passed in 146.24s (0:02:26)
(cwd=E:\xiangmu\rag)         python -m pytest backend/tests -q
  → 1316 passed, 36 warnings, 1133 subtests passed in 133.74s (0:02:13)
```

两行**逐位相同**（含 warnings 与 subtests 数）：0 failed、0 error、**0 skipped**、`RC=0`；
一发之内两行相等，两发之间也相等 ⇒ 10h 没有"第二发不同意第一发"的情形需要重跑。
测试**枚数**一格未因 10h 变动：C1 改的是会话夹具里那一行重绑（不新增用例），C2 改的是既有那枚用例的
secret 来源（不新增、不删除）⇒ 1316 与 10e 那五发同一枚数。基线沿革：`1275`（Task 9 complete，
`progress.md` 末段）→ 10b +1 → 10c +9 与修复轮 → 10d +8 → 10f +8 → 10g +6 → 控制器 00:20 三格 +1
⇒ **1316**；每一发的归因都在各自报告里，没有一处是"数对不上所以改期望"
（`task-10-brief.md` Step 6 的期望是"两行 N passed 逐位相同"，本轮满足）。
10e 那五发（`10e-suite-run1-pre-doc.txt`、`10e-suite-root-pre-doc.log`、`10e-suite-backend-pre-doc.log`、
`10e-suite-root.log`、`10e-suite-backend.log`）当时读的是 **37**——多出的那一枚已在下面这节归因并按
C2 处置 ⇒ 10h 这两发读 **36**，与台账里 Task 9 那枚基线数一致（同一枚 host-dependent 来源，见下一段）。

**warnings 那一格是 host-dependent 的**（10h 终审组三第 6 条把这里从"待查"改成"已归因"）：10e 定稿时
两 cwd 读到的 **37** 比台账基线（Task 9 的 36）多一枚，当时写的是"没有可指的前后对照件 ⇒ 留作待查"。
终审把这枚归到了具体用例：`backend/tests/test_security_a_closure.py::
test_seam_gives_the_p0_login_leg_its_credential_source` 驱动**真实登录**，签发腿读的是
`settings.jwt_secret`，而本机 `backend/.env` 那枚是 **31 字节**（低于 PyJWT 对 SHA256 建议的 32 字节下限）
⇒ 每签发一次多一句 `InsecureKeyLengthWarning`。处置（Task 10h C2）：该枚用例改走本仓既有的
`tests/sec_a_fixtures.py::LongJwtSecretMixin` 口径（它是 unittest 的 `setUp` 混入，而这一枚是 pytest
函数用例，故按工单允许的等价手法只换 `settings.jwt_secret` 那一个属性，见该文件 `SEAM_JWT_SECRET`），
**没有**用 `filterwarnings` 压警告、**没有**动判据（200 + 键集两条断言一字未动）、**没有**改规格里的
警告数。处置后单文件复量：`python -m pytest tests/test_security_a_closure.py -q` = **`17 passed`，0 警告**。
10h 复跑两 cwd 各一遍 ⇒ 同一发里两行都是 **36**（见上面那两行原文）。**这一格本来就不是产品码的读数，
也不是"修好了一件事"的读数**：36 那基线同样由宿主机 `.env` 里那枚 secret 决定——换一台 `.env` 已配长
secret 的机器，这一格还会再降。文档因此把它标成 **host-dependent 计数**，后续轮次拿它当回归信号时
必须先问"这台机器的 `backend/.env` 是哪一枚"，而不是直接比数字。

### 7.1 `[credential-guard]` 收尾行：10e 的"待查"在 10h 归因并处置（终审 C1）

10e 那一节写的是"五发都没打印这一行 ⇒ '零记录'与'修复没生效'在只读面上分不开，留作待查"。
终审给的是**结构性判定**，比那句更硬：**当时那一行不可能打印出来**，与有没有记录无关——

- `LedgerGuard.__init__` 给每枚守卫实例造的是**新 list**（`tests/conftest.py:267` `self.records: list[...] = []`）；
- 会话夹具 `isolated_llm_ledger`（`:704`）装完凭据面那两道闸、把实例挂上 `_CREDENTIAL_GUARD` 之后，
  **从来没有**把 `credential_guard.records` 重绑到模块级的 `_CREDENTIAL_REDIRECTS`（`:169`）：账本面有那一句
  （`:729` `guard.records = _REDIRECTS`），凭据面没有对应的一句 ⇒ 模块级那一枚恒空；
- 而它唯一的读者是收尾汇总的 `else` 分支（`:928-929`），那时 `_CREDENTIAL_GUARD` 已在 teardown 置 None
  （`:771`）⇒ `if credential_records:`（`:930`）**恒假**。
- 行为面互证（评审给的那两条）：`test_credentials_contract.py:1892-1913` 那枚用例通过 ⇒ 守卫**存活期确有记录**，
  同一发里 `grep -c credential-guard` = 0 ⇒ 症状不是"零记录"，是"读不到"。

**处置（裁定：让别名生效，不删那条别名）**——一次冷启动的漏斗读值得这一行收尾汇总。落点两处于
`backend/tests/conftest.py`：`:750` 补 `credential_guard.records = _CREDENTIAL_REDIRECTS`（照 `:729`
账本面同一手法），`:161-166` 那段注释里原来那句"这个模块级 list 与守卫的 `records` 是同一个对象"**是错的**，
现改为陈述它**靠那一次显式重绑**才成为同一个对象。

**复量（10h 实测，不是"应该会"）**：
- `python -m pytest tests/test_llm_usage_contract.py tests/test_security_a_closure.py -q`
  ⇒ `118 passed, 5 warnings, 33 subtests passed`，收尾第 17 行原文
  `[credential-guard] 9 次「读保护集下的真实凭据表」被改道（N1：读不判红）：`。
- 两 cwd 全套件（§7 那两发）⇒ 两行都出现 `[credential-guard] 13 次…` + `……另有 3 次同类读改道`；
  `grep -c credential-guard` 对那份留档件 = **24**（10e 的两份 log 是 `0 / 0`）。
- 这 13 枚记录**全部是读改道**（`ENV` 被 clear 的窗口里落点退回默认值那一族），**写为 0 枚** ⇒ 两枚哨兵一枚
  都没红、真库字节与 mtime 依旧一格未动（§12.1 那两行读数就是这一格的互锁证据）。

**执行路径不受影响这件事保留原判**：这一行只是收尾汇总的**读数**；判红逻辑走的是会话拆闸前的两枚哨兵
（`:757-769`：守卫在场复验 + 真库凭据行不增长）与逐例写改道归责（`:868-899`），两者各自独立于别名重绑成立，
10h 一字未动。10e 留给控制器的"给那一段配一枚正向钉"这一格，10h 取的是**更小的那步**：先把重绑补上、
再用上面两发实测证明"记录在场 ⇒ 该行必打"；用例级的正向钉（构造一次可控改道再断言输出）仍留在 §11 的
登记里，因为那需要新造一次凭据面改道事件，超出一次收口编辑的范围。

### 7.1.1 rev 3 终态复测（2026-09-27 12:00–12:30，控制器亲自跑）+ 一发由复测抓到的自身缺陷

用户批准回写与 tag 判据后，封版前重跑全套件两 cwd（逐字原样）：

```
仓库根：  cd /e/xiangmu/rag  && python -m pytest backend/tests -q
  1316 passed, 36 warnings, 1133 subtests passed in 299.32s (0:04:59)
backend： cd /e/xiangmu/rag/backend && python -m pytest -q
  1316 passed, 36 warnings, 1133 subtests passed in 368.25s (0:06:08)
```

两行逐位相同，0 failed / 0 error / 0 skipped。配套复量：SEC-A 六枚门 **353 passed / 117 subtests**、四枚回归门 **461 passed / 21 warnings / 452 subtests**、CI 等价扫描子集 **5 passed**、变异台锚点 `--check` **19/19 唯一**、修好之后三枚主门 **155 passed / 44 subtests**。

**这一轮抓到的那一发是控制器自己写的测试的缺陷，不是产品的**：rev 2（10h）报告"两 cwd 逐位相同"，但本轮从仓库根跑时
`test_credentials_contract.py::AuditSinkIsolationTests::test_a_recorded_event_lands_in_the_sink_and_not_in_the_operational_log`
**红了**（`1 failed, 1315 passed`）。根因两条，都在我写的那两行里：① 断言拿的是相对路径
`Path("data")/audit.jsonl` —— 本套件按两种 cwd 跑，仓库根上它指向另一枚 gitignored 的 `rag/data/audit.jsonl`，
于是同一句断言在两种 cwd 下问的是两个不同文件；② marker 用了 `self.id()`，**跨运行不唯一**，上一轮留在
那份文件里的同名记录会把这一轮证成假红。修法：marker 改 `uuid4().hex`、落点改绝对
`BACKEND_DIR / "data" / "audit.jsonl"`，并把这段来由写进测试注释。
复测：`-k AuditSinkIsolation` 在仓库根 **2 passed**、在 backend **2 passed**；随后两 cwd 全套件如上逐位相同。
这条同时说明 §14 那句"聚合 sha1"的口径问题（同一句写法五种实现给出五个值，本轮定位为 **只串文件字节** 那条，
`b57fa3366a09…` 完全复现）——**读数必须连命令一起写，否则不是基线，是口头基线**。

### 7.2 本文档自身的 secret 门复量（这一格是**红过一次**的，如实记）

`docs/**` 在扫描面里（`git ls-files -c -o --exclude-standard`，10d §T10-9.2 已核实），且 `EXEMPTIONS`
里**没有任何 `docs/*.md` 条目**——门的设计口径就是"交付文档在材料形状面上 0 命中、不收豁免"
（`backend/tests/test_secret_hygiene_contract.py:416-427` 那段范围决策）。本文档第一次落盘时
**把这道门判红了 10 处**，而原因不是抄了凭据，是门的一条形状规则撞上了散文：

- `_MATERIAL_FACE` 的 `sk-[A-Za-z0-9_\-]{16,}` **没有左边界**，所以它会从英文单词
  `ta` + `sk-` 起匹配，只要后面再跟 16 个类内字符（"sk-" 之后 16 个 `[A-Za-z0-9_-]` 即红）。
  本文档要指路的证据件名恰好都是 `task-10X-<长名>` 这一族 ⇒ 一枚文档凭空造出 10 处"假 provider key"
  （本节最初落盘的版本自己也中招过一次，故这里只写形状、不写那一枚实例串）。
- **处置**：改的是**本文档的写法**（自建证据件统一叫 `10e-<名>.<扩展>`，不带 `task-` 前缀；
  别人那一枚 `10b` 原始跑记录按 `…-mutations-run.txt` 两段写），**没有**动门、**没有**加豁免行——
  加一行豁免正是 `task-10-brief.md` T10-9 要免掉的摩擦，而那扇门此刻表现出的性质是"响亮地红"，
  不是"悄悄放过"。红的那一发留档：`10e-secret-gate-red-round1.txt`
  （`2 failed, 44 passed`，offender 行原文 `docs/SECURITY_A_ACCEPTANCE_2026-09-26.md ×10 未豁免`）。
  修完复量：本文档 0 命中（四枚面各跑一遍），`10e-secret-gate.txt` ⇒ `46 passed in 49.72s`、RC=0。
- 门的这条"缺左边界 ⇒ 对英文单词 `task-` 敏感"的性质登记进 §11（一枚字符的修法属于改门，
  不在 10e 的写作边界内）。

复量件：`10e-secret-gate.txt`（文档定稿后重跑 `test_secret_hygiene_contract.py` ⇒
`46 passed in 49.72s`，RC=0）、`10e-directed-gate.txt`（release gate 第 2 步那一发 ⇒
`492 passed, 10 warnings, 323 subtests passed`，RC=0）。全套件在文档定稿**之后**重跑，取 §7 那两行数。
**10h 复量**（D1 两枚脚本入库 + 本文件改写之后）：交付面 **258** 文件、命中 **16 文件 / 31 处**、
与 `EXEMPTIONS` 互等、`_gate_offenders` 为空 ⇒ **没有加任何豁免行**（新脚本带出的形状靠**改脚本写法**解决：
口令一律按 env 取）；本文件与规格两份 `docs/**` 在材料形状面上各 **0 命中**。
本文档不含那 5 枚 legacy 摘要字面量、不含任何"材料形状"的密钥串；**明文口令只有一枚值**——`admin123`
（全文三处：§9.1 L6 两处在陈述那条被纠正的假声称，一处在上面这句自己）。它按规格 §2:40 已有的盘点复述，
本文没有新引入任何泄漏，另外四枚（`sales123 / hr123 / user123 / viewer123`）**一个字节都没写进本文**
（§9.2 L20 那一格指 `page.tsx:374` 时用坐标代替值就是这个原因）；`docs/**` 在门上只上材料形状面，
故这一枚不构成命中，10h 复量本文件仍 0 命中）。（V2.3 那枚 canary 字面量住在 `backend/tests/test_model_router_v23_contract.py:342`，
本文按 `路径:行号` 指过去而不抄其值——抄进来就是给扫描面添一处新命中）。

## 8. §16 既有测试处置的落点（逐条声明，不搞"顺手改"）

| 处置 | 内容 | 现状证据 |
| --- | --- | --- |
| 原样绿 | `test_rbac_contract.py` 角色矩阵与 `enforce_permission` 文案；`test_typesafe_security_contract.py:231/236`；`/api/query` 键集合钉（`test_typesafe_api_runtime.py:91/119/148`）；`test_llm_egress_guard.py` 的 D6 豁免面静态扫描 | 全套件 §7 那两行数里（0 failed）；D6 计数与键集钉自 Task 6/8 起逐轮"未动"（`progress.md` Task 6/8 complete 行） |
| 原样绿（8 处调用点） | 7 处在收集面内：调用形式与口令字面量都不改，改的是脚下的凭据来源（`tests/sec_a_seed.py` 造 argon2id 行） | `SourceRemovalTests::test_every_demo_login_path_is_argon2_after_the_seed` + `::test_the_session_seed_happened_exactly_once`；第 8 处见 SECA-24 / §10 |
| 改写 1 条（收紧） | `test_branding_contract.py:32`：从"默认 secret 字面量必须在 `.env.example` 出现"改为"占位符形态必须出现 + 企业形态守卫必须拒绝该值" | Task 9 落地；§7 全绿 |
| 改写 1 条（换真源） | `test_feishu_identity_contract.py:1707-1726`：从直接写 `auth.USERS['viewer']` 改走 `directory` 的测试注入接缝；`:1802` "鉴权不读 JWT claim"那枚断言原样保留 | Task 5/6 落地；`:1777/1778` 的 `_LOCAL_KEYS` 等值钉仍绿（⇒ §11 那 2 枚 additive 键的读数与 `task-10e-smoke-final.txt` S1/S3 一致） |
| 被 §7.5 合法改变形状的既有用例 | Task 6 逐条列了 6 枚（三条 403 门改走 `_gated_token()`、"改密后数据面通"改成"旧 token 401 → 重登 → 200"、feishu 自签 payload 补 `cv`、"两面一份期望集"改逐体等值钉） | `progress.md` Task 6「Ruling（被 §7.5 合法改变形状的 6 枚既有用例，零放宽）」 |
| 新建（此前零覆盖） | 失败语义 / 四态枚举 / 两层节流与锁定 / `cv` 失效与"无 `cv` 即拒" / `must_change` 阻断 / 身份合并 / 全新安装与升级路径分离 / Argon2 容器基准 / 脱敏双向 / 交付面扫描 | §3 那 27 行的判定形态 |

## 9. 已知限制（随版交付的话，不得含糊）

### 9.1 规格 §17 冻结的 L1–L7

| ID | 限制（口径照规格，展开为验收视角） | 本版实测 |
| --- | --- | --- |
| L1 | 锁定态对外不可区分 ⇒ 合法用户被锁时得不到提示；接受"错误口令可锁受害者"的 DoS 权衡，因锁定自动过期而非人工解锁 | 终态镜像实测：被锁的 `viewer` 用**正确**口令仍拿 401，且与统一失败面逐字节相同（`task-10e-smoke-final.txt` S4）；诊断走审计 `AUTH_LOGIN_LOCKED` + `migration-status` 的 `locked=` 列（本轮两者都读到） |
| L2 | 无 HTTP `logout` / jti 撤销表 ⇒ 撤销粒度是"该账号全部令牌" | `cv` 纪元已钉（SECA-09/09b）；细粒度撤销登记 §12 |
| L3 | Argon2 档位受容器资源约束 ⇒ SECA-19 不过就是 `BLOCKED`，不是 CONDITIONAL PASS；这台机器的内存是真实约束 | 容器判据三格都在预算内且余量巨大（P95 25.3/1500 ms、40.9/3000 ms、38.4/256 MiB）；宿主不能测 RSS 正是这条约束的成因（`resource` 是 POSIX-only） |
| L4 | 身份文件随镜像打包 ⇒ 改身份要重建镜像或挂载覆盖；`users.demo.json` **存在于企业镜像中**，只是不被加载 | `backend/Dockerfile` 的 `COPY config ./config` 未变；本版实测镜像内含两份 config（`test_both_files_ship_and_pass_their_own_validator` 钉的就是"两枚都随镜像在场"）；需要"镜像内零 demo 痕迹"的验收方请按 §12 那条变体另立条目 |
| L5 | 基线套件数必须收口时重新实测，V2.3 的 950/961 都不作本规格基线 | §7 的 1316 是本版实测；历史沿革逐轮在 `progress.md` |
| L6 | Git 历史含那 5 枚摘要与明文口令测试字面量，不重写历史 | 稳态三处 0 命中（§5）说的是**存储形态**——那 5 枚泄露的**摘要**不再是任何一行的存法（真实库 `legacy_count=0`、5 行全 `argon2id`）。**这不等于旧口令失效：泄露的明文口令（规格 §2:40 盘点过的那 5 枚，含 `admin123`）在每个账号完成强制改密之前仍然能登录，登进去之后还能把口令改掉。** `must_change` 只挡**数据面**的 403，**不挡** `POST /api/auth/password/change`——§8.4 的白名单是**刻意**包含它的（否则没人能改密），于是握着 `admin123` 的人可以先拿一枚票、再把管理员口令改自己的，顺带把真受害者锁在外面。终态镜像的 S1 那一格证的正是这条路：`admin` 带 `must_change=1` 却登录 200 并拿到 token（`task-10e-smoke-final.txt`）。这就是 T6 那份历史泄露今天还能买到的东西；风险靠**作废口令**消解，不靠措辞。⇒ 运维动作见 §12.2 末条：**暴露部署之前先轮换那四枚弱出身账号**（`admin / hr01 / sales01 / viewer`，即 §12.1 表里 `must_change=1` 的那四枚） |
| L7 | `credentials migrate` 的工件默认路径按 **cwd** 解析，库路径来自 `CONVERSATION_DB_PATH`，两者只在"未设或同为相对"时同源 | 现网形态确实同源（`backend/.env:33` 相对值 + 镜像 `WORKDIR /app` + compose 只挂目录）：本轮容器内 `CONVERSATION_DB_PATH='data/conversations.db'`、`cwd=/app` 实测在案（`task-10e-fresh-boot.txt` 第二行）；失败方向是"静默不导入但 rc=0"，`reason` 打印解析后的绝对路径 ⇒ 人可诊、脚本不可诊；本轮不加 `--path`（§12 登记 SEC-B） |

### 9.2 收口期新增的已知限制（L8 起；规格 §17 只到 L7，以下不在那张表内）

| ID | 限制 | 措辞出处 |
| --- | --- | --- |
| L8 | 测试会话与 CLI 证据命令都会**只读**打开 `backend/data/conversations.db`；该库是 WAL 模式 ⇒ 任何一次只读打开都会刷新 `-shm`（wal-index 登记，不是数据写入）。主库与 `-wal` 的字节/mtime 不受影响 | `task-10d-report.md` §5（本轮同现象：`conversations.db` 全程 57344 B / sha1 前缀 `080722b51b3e` / mtime 17:54:11 未动） |
| L9 | `credentials migrate` 的原子粒度是"一行一提交"：中途事故（DB 锁 / 卷满）退出时，之前已提交的 legacy 行留在库里。缓解 = 幂等（`only_missing=True`）+ 逐行 `must_change=1` + `legacy_count` 门照样看得见 | `task-10d-report.md` §1 表 3.4 |
| L10 | `MigrationReport.skipped` 把"已存在跳过"与"写方拒收"合成一枚字段；拆它会改 §11 冻结的四字段 stdout 契约（那是证据面），故只靠 `reason` 分辨 | 同上 3.6 |
| L11 | 会话级护栏的 teardown 在两枚哨兵判红时直接 `raise`，跳过 `uninstall`（进程即将退出，症状只是一条多余 Traceback） | 同上 3.10 |
| L12 | 身份文件的启动期报错会点名冲突的 username；"键名短于 40 位 hex"不进摘要判定（下限停 40 的取舍有反向钉） | 同上 4.2 |
| L13 | 无时区的 `locked_until` 一律读成"仍锁着"（坏值即锁定）；运维手改出来的过去时刻也要等 15 分钟自动过期或人工改库 | 同上 5.3 |
| L14 | 每个认证请求对 `user_credentials` 是**两次只读 SELECT**（版本比对 + `must_change` 门）。刻意：两次判定必须落在各自的时间点上；合并属无测量支撑的性能优化 | 同上 6.1 |
| L15 | 响应面与门判定共用 `app.auth` 同一个私有名字 `_password_change_required`（`app/main.py:30` 按值导入），它就是"两处判定同源"的载体；改名要同步 9 处测试引用，收益只有可读性 | 同上 6.2 |
| L16 | `must_change` 门覆盖面只管"挂了依赖的路由"：一条压根不挂认证依赖的新端点不在枚举行里，由"每条 API 路由要么要求权限、要么在白名单里"那枚**运行时绊线**覆盖面钉负责（不是豁免清单） | 同上 6.3 |
| L17 | **管理员重置腿对不在身份文件里的名字给 404 且审计无痕**（`app/main.py:477-478`）。这不是漏检：§9.1 的失败值域表不覆盖 404，能走到这一格的主体已有 `system:operate` 事件面，且未发生任何凭据写入；要给它对一枚枚举 token，须先给 §9.1 加行 | 同上 T10-9.1（10d 判"已知限制"，控制器交 10e 写明边界） |
| L18 | 容量探针（步骤 0，`credentials.capacity_available()` 非阻塞）与运算处 `argon2_slot()` 兜底之间那格**微秒窗口不可压缩**：通过探针后再输给别人的请求仍在身份查找之后抛错。根治要給永不运算的腿预留槽，那会重新打开 `credentials.py` 里"`capacity_available` 不预约（占而不放等于自己造一条饥饿通道）"那段命名的饿死问题——**按 §20.4"认符号不认行号"指该叙述所在处**（`backend/app/credentials.py:107`，10h 实测；行号只给人读，判据认的是那句理由本身） | `progress.md` Task 8 收口（复评裁定，交 Task 10 写进 §17） |
| L19 | **顺序依赖（运维提示）**：以 `REAL_LLM_ACCEPTANCE=1` 跑**整套**套件时，`test_security_a_closure.py` 里 `test_seam_gives_the_p0_login_leg…` 那枚的 finalizer 会卸掉会话级接缝，导致后面的 `test_conftest_fixture_arms_the_seam_only_when_the_switch_is_on` 断言 `False is True` ⇒ 顺序依赖红。官方 runner 免疫（它 unset 该 env、只为单文件那一步 arm 开关）。登记 V2.4 待办，**不为了让全量开关跑绿而改夹具** | 控制器追加二（10f/10g 复评 G3 同段）；见 §10 |
| L20 | **改密腿没有界面入口**（10h 应终审组三第 2 条新增）：`POST /api/auth/password/change` 有 API、有 §8.4 的白名单地位、有 `SelfServiceChangeTests` 那几枚用例，但界面**没有一处调用它**——本轮实测 `grep -rn "password/change" frontend/src --include=*.ts --include=*.tsx` = **0 命中**，`grep -rn "password_change" frontend/src` 亦 0（前端只剩两处沾 password：登录页 `src/app/page.tsx` 与 `src/lib/api.ts:241` 的登录腿）。后果直接压在 §9.3 那句"一次强制重登录"上：界面对 `must_change=1` 既不给提示也不给改密页，用户登进去只拿到一枚数据面 403 ⇒ 改密只能由管理员走 CLI（`CREDENTIALS_PASSWORD=… python -m app.cli credentials reset --username <名>`）或裸调 API。同一格另一半：登录页那排一键填充（`src/app/page.tsx:371-375`，取值写在 `:374` 那一行）里 `user` 账号仍带着规格 §2:40 盘点过的那枚 demo 弱口令，而 10a 的 smoke 已把 `user` 的口令换成**任何地方都没有记录**的值 ⇒ 那一枚按钮今天必然 401，恢复只有一条 CLI 路（§12.1）。**本项不随 SEC-A 收口**（前端面不在本子规格范围内），登记为随版 release note 必含 | 控制器追加（终审组三第 2 条）；证据 = 本轮两枚 `grep` 实测 0 命中 + §12.1 那格已记录的 10a 轮换 |

| L21 | **仓库 CI 在 SEC-A 之前就是红的，SEC-A 没有把它修绿**（2026-09-27 实测）：远端最近三次 push（含 V2.3 RC `feat(llm): finalize Model Router V2.3 release candidate` 与 `docs(sdd): record the V2.3 amend / RC tag / push trail`）**全部 failure**，4 枚 job 里只有 `frontend-build` 绿；本地用**零依赖** venv 复现既有步 `python -m unittest discover -s backend/tests -p 'test_*.py'` = `132 tests / 3 failures / 26 errors`，**补上轻量依赖反而恶化**成 `11 failures / 160 errors`（依赖缺口不是根因，runner 形状才是）。⇒ 本格的处置是用户裁定：**"CI 真执行了应执行的门"以 SECA-20 扫描步为准判定**（该步本地与 CI 同命令、已证红绿两态），**不**以"整条 workflow 全绿"为 RC 前置；整条流水线的修复（换 pytest runner、装齐 `requirements.txt`、另两枚 job 的红因）是 SEC-B 前置项，见 §11。RC 若落在这种状态下，必须连这句话一起交付，不能让读者以为流水线整体绿过 | 控制器 2026-09-27 实测：`gh run list`（三次 failure + 时长 1m13s–1m19s）、干净 venv 两发复现计数 |

### 9.3 breaking change（release note 必含，§15.2 最后一句）

**SEC-A 上线时，此前签发的所有 JWT 因缺 `cv` claim 而一次性失效：用户会看到一次重新登录。**
不得写成"无感升级"。**对界面用户这句还要再加两半**（§9.2 L20）：那次重登录之后的**改密腿目前没有 UI 入口**
（`grep -rn "password/change" frontend/src` = 0 命中），界面对 `must_change=1` 既无提示也无改密页，改密
只剩 CLI（`app.cli credentials reset`）或裸调 API；而登录页对 `user` 的那一枚一键填充（`page.tsx:374`）
已随 10a 的口令轮换失效，恢复只有一条 CLI 路（§12.1）。这两半是 release note 必须写下的代价，不是脚注。
这条不是叙述而是被观测过的事实：SECA-09b 的判定形态就是"签名有效但 claim 无
`cv` ⇒ 401 `无效登录凭证`，与普通过期同形"，M17 那发变异（`cv` 缺失即放行）专门被它杀掉；
部署形态那一次在 10a C.7（改密后旧 token 401、重登后 200）。同一枚纪元的另一半代价是
"改密即废全部令牌"（L2：撤销粒度是账号，不是设备）。

## 10. P0 接缝与它的边界（追加二必写四句 + 复跑命令）

1. P0 的登录腿之所以能 200，是 **harness 自己**通过 `sec_a_seed.install_demo_credentials` 给它造的临时库
   种了凭据行，闸门与收集门是同一枚 `REAL_LLM_ACCEPTANCE=1`；产品侧对"未种凭据的全新安装"永远是 401。
2. 新的 P0 证据 JSON 里 `ledger.tables` 会多出一张 `user_credentials`——那是**描述被拓宽**，
   不是判据被放宽（全仓没有任何断言检查那枚表集合；`kit.validate_evidence()` 与闸③读的是
   `rows==1` / canary / `fallback_index` / `success` / `model` / 禁存列 / trace / sha1）。
3. **P0 绿灯不证明"全新安装能登录"**；它证明的是 failover 走到 200，且凭据由 harness 提供。
   （"全新安装能不能登录"由 §3 SECA-04b 那一行负责，其部署形态证据是 `task-10e-fresh-boot.txt`。）
4. P0 的 `files_sha1` **不含 kit 模块**（`real_llm_failover_kit.py`）——造出那行凭据的代码不在它自己
   fingerprints 的证据里。V2.3 既有证据因此不作废，但这是一个必须点名的边界。

**SECA-24 为什么记 PENDING_EXTERNAL，以及等什么**：该行的判据里有"8 处既有登录调用点的口令字面量不改
即可登录"，第 8 处是 `backend/tests/test_real_llm_failover_acceptance.py:686`。该文件按 V2.3 的纪律
默认**不被收集**（`del` 收集门，本轮实测：不带开关 ⇒ `no tests ran`；带开关仅收集 ⇒ `1 test collected`），
其真机路径需要两次真实 Ollama 外呼与一对可用模型。本环境没有 provider key、`ornith-1.5:9b-text` 载不动
⇒ 不伪造证据、不花钱。本轮已做的**不是**"因为它是 skip 就不测"：该文件跑过（0 collected / rc=0，不红）、
它的字节仍与封存值一致（sha1 `da92cdf51de5dbfad3107f1dc744d18e4173e07c`）、承载它的三枚反造假闸在套件内绿
（`test_real_llm_failover_gate.py`：15 passed / 11 subtests，10e 复量）。

operator 复跑命令（唯一入口，含内存前置与许可判定）：

```text
cd E:/xiangmu/rag
bash .superpowers/scripts/run_p0_failover_acceptance.sh            # 需要显式越权时加 --yes
# 等价手工：cd backend && REAL_LLM_ACCEPTANCE=1 python -m pytest tests/test_real_llm_failover_acceptance.py -q -s
```

复跑时预期看到：登录腿 200、证据 `ledger.tables` 多出 `user_credentials`、`self_validation_problems` 为空。
若仍报 `no such table: user_credentials` ⇒ 说明那一跑的 `REAL_LLM_ACCEPTANCE` 没在会话起点摆着
（接缝的唯一门），先查开关而不是查接缝。**并请先读 L19**：那条开关别拿去跑整套件。

## 11. §18 后续登记（合并 10d 分诊表里落到"转 §18"的四格）

规格 §18 原清单全部保持，逐条附本版落点：

- **G7** 摄取侧注入 / PII 本地兜底（→ 子规格 B）。
- **G14** `request_id` 全链路 + 按请求聚合的认证失败证据链（→ 子规格 C）。
- **G18** prompt 版本化（→ 子规格 C）。
- **G6** 多租户。
- `logout` / jti 细粒度令牌撤销（SEC-A 只有 per-account epoch，§17 L2）。
- **`PASSWORD_DENYLIST`**：条目来源、规模、大小写与 Unicode 归一、username 变体规则，连同实现一起做
  （§8.8 已把该要求从 SEC-A 移出——未定义的字典不是可验收的规则）。
- **专用 security CI job 与第三方扫描器**（`gitleaks` / `pip-audit` / `bandit`）：SECA-20 的本地门是
  其前置而非替代。本地门扫的是**交付面当前文件集**，两件事它不做：带 git 历史的检索（L6）与
  未跟踪/被忽略文件的运行时材料（`backend/.env` 就在这一格）。
- 身份热加载，或企业镜像打包阶段排除 `config/users.demo.json`（L4 的"镜像内零 demo 痕迹"变体）。
- 水平越权与文档下载路径的安全测试（`SECURITY_REVIEW.md:35` 自列项）。

10d 分诊表判为"转 §18"的四格（措辞照该报告，编号可回溯）：

| 项 | 归属与措辞 | 出处 |
| --- | --- | --- |
| SEC-A 的可用性旋钮不做 pydantic 区间校验，唯一下限是 `credentials` 侧的 `max(1, ·)` 夹取；把下限搬到启动面属 SEC-B 的配置校验条目 | SEC-B（配置校验） | `task-10d-report.md` §1 表 1.2 |
| 护栏类命名（`LedgerGuard` 已覆盖凭据面）留到下一次护栏换形时一次性改，那一次本来就要重跑全套地基 | 测试地基 | 同上 3.5 |
| 凭据采用率的"无分母"取值需要 `null` + `?? "—"` 的形状变更，跨 API 契约与前端两处，随下一次前端运维视图改动一起做（SEC-B/C） | 前端/契约 | 同上 4.1 |
| V2.3 契约文件里那处用例内 seed 属"测试自己造前置条件"的自愈模式，随下一次 V2.x 套件地基统一处理 | V2.x 测试地基 | 同上 5.1 |

收口时补登的三格（10h 按终审判定改写过前两格的现状描述，并加两格新的）：

- **`_MATERIAL_FACE` 的 `sk-` 一枚缺左边界**：它会匹配进英文单词 `ta``sk-<16 个类内字符>`，
  于是一份引用 `task-10X-<长名>` 证据件的交付文档凭空多出 10 处假 provider key（本轮实测，
  见 §7.2）。修法是一个字符（前置非词边界），但那属于**改门**，不在 10e/10h 的写作边界内。
  本轮的处置是改文档写法而不是加豁免行——门的表现是"响亮地红"，这条性质要保留。
- **`[credential-guard]` 收尾行：10h 已把"生效的那一步"补上，仍欠一枚用例级正向钉**。10e 那格写的是
  "待查 + 留给控制器"，终审给了结构性判定（别名从没被重绑 ⇒ 那一行当时不可能打印出来），10h 按裁定
  在 `tests/conftest.py:750` 补上重绑并用两发实测确认"记录在场 ⇒ 该行必打"（§7.1）。**还欠的那半**是
  用例级的正向钉（由一条测试自己造一次可控改道再断言输出行），那需要新造一次凭据面改道事件 ⇒ 仍登记
  为测试地基工程。
- **L19 那条顺序依赖**（`REAL_LLM_ACCEPTANCE=1` 跑整套件）——V2.4 待办；本轮不改夹具。
- **CI 侧那道 secret 门的前置**（10h 新增，终审组三第 4 条 / 规格 §20.7 的 S2）：既有 `backend-contracts`
  job 里没有依赖安装步（`ci.yml:10-25`，跑的是 `compileall` + `validate_demo_assets` + `unittest discover`），
  `argon2-cffi`（`requirements.txt:13`）没有任何 job 装，`unittest discover` 又收不到裸 pytest 函数（SEC-A
  六枚契约文件里共 40 枚）⇒ **"本地与 CI 同一道门"尚未成立**。SEC-B 的前置动作：该 job 先 `pip install
  -r backend/requirements.txt` + 换 pytest runner，然后 SECA-20 的矩阵行才谈得上"CI 侧也绿"。本工单**不改
  `ci.yml`**（明令禁止面）。
  **2026-09-27 状态更新（用户裁定"修 CI 不放宽规格"，本工单那条禁令由用户撤销）**：`ci.yml` 已改——
  `backend-contracts` 的 step 3 装扫描门最小依赖、step 4 用 pytest 跑扫描子集，且两步排在既有 `unittest
  discover`（现 step 7）之前。首版依赖清单被**远端**证伪一次（`f6c67b5` 该步 `ModuleNotFoundError: httpx`），
  补全后 `e5ff798` 该步远端 `success`（经过与规矩见 §3 SECA-20 行末与规格 §20.8 卡 D 末条）。
  上面那段"没有依赖安装步 / 收不到裸函数"从此只描述**其余 5 枚契约文件**：
  扫描门自己已经在 CI 里跑。既有步在 main 上早已红这件事与本条无关（见 §9.2 L21）。
- **落盘面脱敏的两张既有写手**（10h 新增，规格 §20.7 的 S3）：`app/knowledge_os.py:86` 的 `_write_json`
  与 `:92` 的 `_append_jsonl` 至今仍用 `redact_secrets`（形态脱敏），不在 §9.3 那三枚"切换点"的枚举里。
  这是**范围边界**而不是破掉的承诺：AST 那对等式（`tests/test_secret_hygiene_contract.py:196` 的
  `assert 4 == _call_sites("redact_for_persistence", …)`（`:211`）与 `assert 17 == _call_sites("redact_secrets", …)`
  （`:214`））会把第五张落盘面当场判红——把那两张面换过去时 4 变 6、17 变 15，两个方向都红 ⇒ 它不会静默漂移。
  要纳入那两张面 ⇒ 规格 §20.7 登记"钉 4→6"、随之要重写 §9.3 的切换点枚举（属 SEC-B 的语义增补）。

**已经闭合、不再留在 §18 的一格**（10d 判"转 §18"、控制器不认那个结论）：
`backend/data/audit.jsonl` 曾被测试写过。控制器直接修了——`tests/conftest.py` 新增会话级 autouse
`isolated_audit_sink`（把 `app.audit.AUDIT_PATH` 改道进会话临时目录），并配 `AuditSinkIsolationTests`
两枚（改道目标不得落在仓库 `data/` 下；写入落汇且 marker 不出现在运维那本账里）。实测
`test_credentials_contract + test_authentication_leg` 159 passed / 58 subtests 且真 `audit.jsonl`
**delta = 0 字节**（改前同一对文件会 +337 B）。理由：它违反的是本项目的 standing rule，
不是扫描门的键。（既有 2 MB 残留按 §12.1 不删。）

## 12. 部署形态的现网残留（如实写，别当缺陷"修"）

### 12.1 demo 库与审计账本今天长什么样

`backend/data/` 本轮**只被应用自己**写过（smoke 的 `failed_attempts` / `locked_until` / `last_login`）；
10e 没有清理、截断或手工改过任何一行。终态读数：

| 事实 | 读数 |
| --- | --- |
| `user_credentials` | 5 行，全 `argon2id`；`admin / hr01 / sales01 / viewer` = `v1 must_change=1`，`user` = `v2 must_change=0` |
| **4 枚仍 `must_change=1`** | 弱口令出身账号未改密的**正确稳态**（§8.4 的 `authentication → must_change → authorization`），不是待修缺陷；数据面对它们就是 403（`task-10e-smoke-final.txt` S3 实测） |
| `user` 的口令 | 已在 10a 的 smoke 里被换成一个**任何地方都没有记录**的值（那是 §15.1 第 6 步"改密全流程"必须真跑一次的代价，且不能撤销）。恢复演示口令的运维动作：`CREDENTIALS_PASSWORD=… python -m app.cli credentials reset --username user`（口令只进 env，不进 argv，见 §8.6/§10）⇒ 该账号会带着 `must_change=1` 与新纪元重新交回使用者 |
| `viewer` 的锁定 | 本轮 S4 复锁：`locked_until=2026-09-26T16:40:12.979814+00:00`、`failed_attempts=6`；按 `ACCOUNT_LOCK_SECONDS=900` 自行过期，**未人工解**（手工清行就是把门换成删除） |
| 主库文件 | 10e **跑前**：57344 B / sha1 前缀 `080722b51b3e` / mtime 17:54:11。**跑后**：57344 B / sha1 前缀 `a8565a343f1a` / mtime **00:26:37** —— 变的这一格正是终态镜像那四场景 smoke 自己写的（S2 的 `failed_attempts`、S4 的 `locked_until`、S1 的 `last_login`），**行数与算法分布一格未动**（仍是 5 枚 argon2id、legacy 0）。此后 **5 发全套件跑完（00:27→01:16）它的 mtime 一直是 00:26:37**、`audit.jsonl` 一直是 00:26:38 ⇒ 「测试不写生产库/不写运维那本账」这条有了一份时间戳级的互锁证据（SECA-22 + §11 末的审计汇修复）。`-wal` 恒 0 字节；`-shm`/`-wal` 的 mtime 随任何一次只读打开被抬（L8） |
| `backend/data/audit.jsonl` | 2 053 203 B / `65933d8bfd5d`（10e 跑前）→ **2 056 230 B / `a0338cb05a17`**（跑后，+3 027 B = 终态 smoke 自己那批 `LOGIN/DENIED`、`AUTH_LOGIN_LOCKED`、`AUTHORIZATION/DENIED` 事件；此后 5 发全套件它一格未长）。含 **SEC-A 之前 + 测试历史 + smoke 真实事件的混合账**。既有残留**不删**：里面同时有 §14 证据面的真实事件，截断会连带削掉证据。⇒ `credentials migration-status` 打印的"最后成功登录时间"**只作运维参考**，不作为验收判据（该字段本就不入库，是审计尾部派生列，见 `progress.md` Task 3 的 Ruling） |

### 12.2 运维体检（升级 / 回滚 / 重建）

- 升级路径的唯一入口是运维显式 `python -m app.cli credentials migrate`（**启动绝不自动导入**，
  §8.2/§8.5/M19）；退出码语义 0/1/2/3 见规格 §11 与 10c 的裁定。
- `backend/data` 是 **bind mount** ⇒ 容器里的 `/app/data/conversations.db` 与宿主那份是同一个文件
  （T10-8 的拓扑裁定；本轮 `task-10e-fresh-boot.txt` 用**独立 named volume** 做全新安装演示，
  没有碰那枚 bind mount）。改用 named volume 部署时，容器与宿主的两次读数就不再是同一事实，必须分查。
- `docker compose build backend` 会改 `requirements.txt` 层序（`COPY requirements.txt .` 在两枚 pip 层之上）
  ⇒ 任何依赖变更都会连带重下 `torch`，10a 那一轮实测 ≈32 分钟；本轮只改源码 ⇒ ≈5 分钟。
- **回滚点已不存在**：`1abba3717aa7`（10a 的镜像）在本次构建后被本地镜像库回收，
  `docker images rag-backend` 现在只有 `3f14b3de77a4` 一枚。要回滚只能从源码重建。
- L7：绝对 `CONVERSATION_DB_PATH` 的 systemd 式部署要运维自己保证 cwd 或显式传路径。
- **暴露部署之前先轮换那四枚弱出身账号**（`admin / hr01 / sales01 / viewer`，即 §12.1 里仍带
  `must_change=1` 的四枚）。这不是卫生建议而是 §9.1 L6 那格的缓解动作：泄露的明文口令在改密完成前
  **仍然可登录**，而 `must_change` 不挡改密腿 ⇒ 拿到口令的人比运维更早把账号收走。逐枚动作：
  `CREDENTIALS_PASSWORD=<新值> python -m app.cli credentials reset --username <名>`（口令只进 env，
  不进 argv；账号会带着 `must_change=1` 与新纪元交回使用者，之后由本人改密）。第 5 枚 `user` 的口令
  已在 10a 的 smoke 里被换掉、没有记录，恢复动作同这一条（见 §12.1）。

## 13. Step 8 提交清单（**停止点，未执行任何 git 写命令**）

只读快照：`git status --porcelain` = **42 条**（**20 条 ` M` 修改 + 22 条 `??` 未跟踪**；10e 定稿那一份
是 40 = 20 + 20，其中第 20 枚未跟踪是本文件——10h 之后多出的两枚是 D1 入库的探针脚本
`scripts/sec_a_fresh_boot_probe.py`、`scripts/sec_a_smoke_http.py`。`git rev-parse HEAD` =
`bc43ca3931c36cc27768fbae0d34b24297d13121`；`git tag --list` =
`model-router-v2.3-rc1`，**未触碰**）。逐条原文与"拟提交 / 明确排除"的划分见
`.superpowers/sdd/SECURITY_A_PLAN/task-10e-report.md` §D，**10h 的终态快照与增补见同文件 §D2**（含
`scripts/` 那枚新目录项与 `.superpowers/` 的 `add -f` 岔口）。
建议粒度：一个 `security-a` 提交 + tag `security-a-rc1`；**不得** `git add -A`、不得 amend、
不得移动 `model-router-v2.3-rc1`。

## 14. 冻结基线

```text
签发文档                     docs/SECURITY_A_ACCEPTANCE_2026-09-26.md（本文件；文件名日期按 task-10-brief.md T10-1 的更正，
                             计划原文写的是 2026-09-25 = 计划撰写日，而回执文档必须是签发日 2026-09-26/27）
                             修订：rev 1（2026-09-27 00:20–01:20 由 Task 10e 一次性写成并定稿；本文件即 revision 载体，自哈希不可自指，
                             交付面哈希对同批 docs 由 SECA-20 那道门每次复量）
                             修订：rev 2（2026-09-27 02:00–02:30 由 Task 10h 按**最终全分支评审**改写：§9.1 L6 那句"旧口令永久失效"
                             是假的安全声称、已按代码事实重写；§1/§2/§6/§7/§7.1 五处过度声称按实测拆开；§9.2 新增 L20；
                             §14 新增两枚入库探针脚本；§7 的两 cwd 数与 §13/§14/§15 的 git 计数为 10h 本轮实测）
镜像别名与回滚点                rag-backend:security-a-rc1 → 3f14b3de77a4（与 :latest 同一 ID，2026-09-27 打）
                             这是**本地产物别名**，不替代 Git tag；旧镜像 `1abba3717aa7` 已被 10e 的构建回收 ⇒
                             本地无回滚点这一事实记在 §12.2，不得写成"可回滚"
rev 3（2026-09-27 12:00–12:40，控制器封版前复测）
                             SECA-20 的 CI 接入按用户裁定"修 CI 不放宽规格"落地并留证（§3 SECA-20 行、§11
                             那条状态更新）；§9.2 新增 L21（三枚 CI job 在 SEC-A 之前就红；RC 判据由用户改为
                             "按扫描步判定"）；§7.1.1 记录复测抓到的控制器自写测试缺陷及修复；§14 补上聚合
                             sha1 的**口径命令**（同一句写法五种实现给出五个值 ⇒ 读数必须连命令一起写）
git HEAD                     bc43ca3931c36cc27768fbae0d34b24297d13121（工作树 42 条 git status 条目 = 20 ` M` + 22 `??`，全部未提交；10h 实测）
tree state                   backend/app/*.py 34 枚文件聚合 sha1 = b57fa3366a09397f790102c9a027b71d44b95c6c
                             **口径必须写出来**（2026-09-27 终态复测的发现：同一句"34 枚聚合 sha1"在五种
                             合理写法下给出五个不同值，只写结果等于不可复现）。这里用的是**只串文件字节**：
                               `python - <<'PY'`
                               `import hashlib, pathlib`
                               `h = hashlib.sha1()`
                               `for p in sorted(pathlib.Path("backend/app").glob("*.py")): h.update(p.read_bytes())`
                               `print(h.hexdigest())`        # → b57fa3366a09…，34 枚
                             （带文件名的四种变体实测为 c4912265ae9a / ad865d13906f / 76a781a0513f / 43e4a02d50ef，
                             都不是本值 ⇒ 复现者必须用上面那条，别按"文件名+内容"想当然。）
                             关键单文件（与 task-10d/10g 报告的"改后 sha1"逐枚相同）：
                               app/credentials.py            6ebbbb4ffdc0be5a53cfdf7ee961a8feb3fbeb94
                               app/user_store.py             4dc81c4382683381792d8fd27c13159eb01549d6
                               app/login_throttle.py         e4c243fe70e4fac5c2d56f6916542481ae497e08
                               app/credentials_migration.py  44f450debd7c712adc5f9acf82d44b458d00cf70
                               app/main.py                   fd6e29fc721dfcc99391c05c1abb349d79141c65（CRLF 987→1004 保持）
                               app/auth.py                   7f669c167487…（Task 8 修复轮后未再动）
                             封版件 tests/test_real_llm_failover_acceptance.py da92cdf51de5dbfad3107f1dc744d18e4173e07c（一字未动）
release image                rag-backend:latest  ID 3f14b3de77a4（sha256:3f14b3de77a4e93d27d1b14389562aab4f746c2a30e55edca28f1057e57e8233）
                             镜像内 11 枚 SEC-A 相关模块逐枚 sha1 == 现树（task-10e-report.md A.1）；python 3.12.14；argon2-cffi 25.1.0
                             上一枚 1abba3717aa7 已被回收 ⇒ 无本地回滚点（§12.2）
Docker engine                29.7.2
suite（两 cwd，逐位相同）    1316 passed / 36 warnings / 1133 subtests passed / 0 failed / 0 skipped
                             （10h 在 C1/C2 + D1 落盘后复跑的两发，见 §7；10e 那五发读的是 37，多出的
                             一枚已按 §7 的 C2 归因处置。这一格是 host-dependent 计数，理由同 §7 末段）
                             原始件：10h-suite-both-cwd.log（本轮两发）、10e-suite-root.log、10e-suite-backend.log
container evidence           argon2-benchmark-container-final.json（verdict GREEN；§1.1 两套房）
                             task-10e-smoke-final.txt（四场景 + migration-status）
                             task-10e-fresh-boot.txt（空 data 卷冷启动 401 非 500）
                             10e-anchor-check.txt（终态树 19/19 锚点唯一）
                             10h-fresh-boot-rerun.txt（该探针在当前镜像上的复跑，逐行等于上面那份转录）
探针脚本（10h D1 入库）      scripts/sec_a_fresh_boot_probe.py、scripts/sec_a_smoke_http.py
                             ⇒ **部署面证据可由这两个脚本 + 当前镜像复现**：两枚原件原先住在仓库外
                             （`C:/tmp/seca10e/fresh_boot_probe.py`、`…/smoke_http.py`），矩阵里 6 行
                             （SECA-01 / 03 / 04b / 14 / 18-deployment / 19）靠它们的转录取数，而旧镜像
                             曾一度被认为回收、脚本又在仓库外 ⇒ 那一面当时不可复现。现在副本进版本控制、
                             且按 env 取口令（脚本内无明文、无摘要字面量），复现命令写在两枚脚本自己的
                             docstring 里。**边界如实写**：10h 实测复跑的是第 1 枚（`3f14b3de77a4` +
                             一次性卷 `rag-seca-10h`，逐行相同）；第 2 枚 `sec_a_smoke_http.py` 只入库未重跑，
                             因为它要拿已泄露的弱明文打在线部署、且 S4 那五连错会往 `backend/data/` 的凭据表
                             写失败计数并把 `viewer` 锁掉——本工单规定 `backend/data/` 只读。原地那两枚脚本
                             保留未删（它们是本次转录的原始现场）。
verdict                      CONDITIONAL PASS（26 GREEN / 1 PENDING_EXTERNAL / 0 BLOCKED；13 枚一票否决项全 GREEN）
```

## 15. 版本控制提醒

`rag/` 是 git 仓库，HEAD 停在 `bc43ca3`，SEC-A 的**全部**产物只存在于工作树里（**20 改 + 22 未跟踪 =
42 条**，10h 实测；含本文档与两份 spec/plan，以及 D1 入库的两枚 `scripts/sec_a_*.py` 探针副本。10e 那一份
写的是"20 改 + 19 未跟踪"、§14 那一份写的是"39 条"，两处都少算了一枚——10e 定稿时的实测快照本就是
40 = 20 + 20，本文档自己是那第 20 枚未跟踪；10h 的 +2 见 §13），**没有任何回滚点**。是否提交、以什么
粒度提交、打不打
`security-a-rc1`，由用户拍板；本报告与 §13 的清单不代为动手。V2.3 的 RC tag 一字未动。

# SDD ledger — plan: docs/SECURITY_A_PLAN.md

规格：`docs/SECURITY_A_SPECIFICATION.md`（已冻结，§20.2 两栏 detail 回写已获用户认可 2026-09-25）
分支/基线：`main` @ `bc43ca3`（RC `5ba5f20` = tag `model-router-v2.3-rc1`，不可触碰）
开工时工作树：仅两枚未跟踪文档（spec + plan），零代码改动

## 执行环境裁定

- Ruling: 在 `main` 上就地执行、用快照代替 commit — 用户在本轮 dispatch 参数里明确指定"工作区 + 快照 + progress.md 台账代替逐任务 commit"，且本仓库既有纪律是"未授权不得提交、快照差分评审"（项目记忆）；git worktree 会绕开 `backend/data` volume 与 compose 的既有形态。代价：若中途 `git clean -fdx` 会连带清掉 gitignored 的 `backend/data/`（含迁移工件），届时从本台账 + 快照恢复。
- Ruling: 评审包不用 `scripts/review-package`（它依赖 git 范围），改用 `diff -ruN` 比对每任务的 `snap-taskN-pre/` 与 `snap-taskN-post/`。理由：本计划无 commit，BASE..HEAD 恒等于空。代价：diff 里不含 commit message 信息，判据全靠 brief + report。
- Ruling: Agent 工具在本 session 不暴露 `model` 参数 ⇒ 无法按技能要求显式指定模型，所有 subagent 继承 session 模型。已在最终报告清单里登记为环境限制。
- Ruling: 工作区目录名以 `scripts/sdd-workspace` 解析结果为准（`SECURITY_A_PLAN`），计划与规格里原先写的 `SECURITY_A` 已全文改写（plan 39 处 / spec 1 处）。

## 开工前冲突扫描（逐对检查，非结论）

| 对 | 一侧产出 vs 另一侧消费 | 检查结论 |
| --- | --- | --- |
| T1 ↔ T5 | `verify_password(plain, *, algorithm, encoded)` vs 登录腿调用 | 一致 |
| T2 ↔ T5 | `apply_rehash(..., expected_version)` / `clear_login_failures` 签名 | 一致 |
| T2 ↔ T3 | `import_legacy_digest` 生产者 vs 迁移器调用方 | 一致；AST 调用方扫描期望集合 `{credentials_migration.py}` 与定义处（`user_store.py` 里是 `def`，不是 Call）不冲突 |
| T4 ↔ T5 | `directory.reset_cache()` / `override_identities()` | 一致（Task 4 Produces 已含） |
| T5 ↔ T8 | `_locked()` 本地定义 vs `login_throttle.is_locked()` 迁出 | **发现**：Task 8 Step 4 只说"换成 login_throttle.is_locked"，未要求删除 Task 5 的本地 `_locked`，会留死函数。裁定：Task 8 dispatch 里显式要求删本地定义并改用导入。 |
| T5 ↔ T8 | `settings.account_*` 归属 | **发现（已修）**：Task 5 认证腿读 `settings.account_max_failed_attempts` / `account_lock_seconds`，但这四枚参数原先全在 Task 8 添加 ⇒ Task 5 会 AttributeError。计划已改为 Task 5 加两枚账号级、Task 8 加两枚节流级。 |
| T6 ↔ T7 | `MustChangeGateCoverageTests.WHITELIST` | **发现（已修）**：白名单含 `POST /api/auth/password/change`，但该端点 Task 7 才存在 ⇒ Task 6 收口即红。已改为 Task 6 只含 `/me`，并在 Task 7 显式要求同步扩成两项。 |
| T5/T6 ↔ 规格 §9.1 | HTTP detail vs 审计 token | **发现（已修）**：Task 5 Step 5 的 403 `detail` 原写成 token `password_change_required`，与本轮 §20.2 两栏回写冲突（会引入英文 token 到展示面）。已改中文文案 + 审计 AUTHORIZATION/DENIED/token，与 `enforce_permission` 同构。 |
| T5/T6 ↔ 仓库现实 | `from tests.conftest import X` | **发现（已修）**：`backend/tests/` 无 `__init__.py`，该 import 不成立。已抽出 `backend/tests/sec_a_seed.py`（避开有过覆写事故的 `tests/helpers.py` 命名）。 |
| T5 ↔ T10 | M5 注入片段引用 `main.py` 局部变量 `result.audit_detail` | 计划未固定该变量名。**裁定**：Task 5 落地时把登录腿局部变量命名为 `result`；漂移由 harness 的 `TARGET-NOT-FOUND` 分支暴露，不静默跳过。 |
| T3 ↔ 仓库现实 | 迁移工件 `backend/data/legacy_credentials.json` | 已确认 `backend/data/` 被 `.gitignore:7` 覆盖 ⇒ 不进 SECA-20 tracked 扫描，closure 靠文件存在性断言 + 三处扫描（app/config/DB）。 |
| 每任务 ↔ 全局约束 | "Commit" 步骤 | 计划已统一替换为快照 + 台账（见上）。 |

扫描后无未裁定的阻塞项。开始执行。

## Task 1 — Argon2 口令原语

- Task 1: complete-pending-review — implementer DONE；`credentials.py`(127) + `test_credentials_contract.py`(153) + `config.py:160` + `requirements.txt:13`；定向 10 passed、全套件 971 passed，两 cwd collected 相等。
- Task 1 review: spec ❌ / quality Needs fixes（5 Important，7 Minor）。评审确认实现忠实于档位常量、库原样 PHC、列分派、库判漂移，并实测 SECA-05 等式门是**双向**的（新增未豁免站点会红；过期豁免也会红），不是自证式豁免。
- Ruling: `TRANSITIONAL_EXEMPT={"app/auth.py"}` 接受 — Task 1–4 期间 `auth.py:174` 确实仍在生产里哈希口令，等式表把它列进去是事实而非放水；Task 5 删 `_password_digest` 后等式钉会自己变红，不依赖人的记忆。代价：若 Task 5 忘记清表，套件在 Task 5 就红，不会静默。
- Ruling（评审 Important 2 是计划缺陷）：`except argon2.exceptions.InvalidHashError` 在 argon2-cffi 25.1.0 的异常树上永不可达（`InvalidHashError⊂ValueError`，`VerificationError` 是另一支），坏 PHC 串会以库异常逃出边界模块 ⇒ 计划文本已同步改为 `VerificationError`（排在 `VerifyMismatchError` 之后）。原因：这条只在报告里记录、不改计划的话，Task 5 照计划逐字执行就会把缺陷复活。
- Ruling（评审 Important 5 的 M13 半边）：计划 Task 10 的 M13 注入片段需升级为"真造一处 `hashlib.sha256(password…)`"，否则空门；已开 TODO #75 跟踪，落地在 Task 10 前。
- Ruling: 评审的 ⚠️ 两项由我判定为非缺口 —(a) `ARGON2_MAX_CONCURRENT_OPS` 的 `.env.example` 行归 Task 9 的 env 清单；(b) 我在 dispatch 里提到的 `test_the_profile_is_not_env_tunable` 并不存在于计划，不可满足性由"字面量 + 不 import os + M16 变异"三者保证，评审的怀疑来自我的措辞而非计划。
- Task 1: minor (deferred): `_LEGACY_HEX` 拒大写却仍 `.lower()`（死代码）；`config.py` 未用 `Field(ge=1)` 与邻居风格不一致；`hash_password` 不占槽但公开 `argon2_slot` 诱导调用方重复占；`needs_rehash()` 对非 PHC 输入抛裸 `InvalidHashError`；`test_only_credentials_module_hashes_passwords` 名称与实证不符；等式失败消息未指向 `TRANSITIONAL_EXEMPT`。
- Task 1: fix round 1/5 (6 addressed, 0 open; `credentials.py` + `test_credentials_contract.py`, 982 passed 两 cwd 相等, focused 21 passed / 9 subtests) — re-review 判 F1–F6 全 ADDRESSED，无新增 Critical/Important。
- Task 1: complete (worktree @ bc43ca3 之上未提交，评审 clean)。产出：`credentials.py`(131) / `test_credentials_contract.py`(311) / `config.py:160` argon2_max_concurrent_ops / `requirements.txt` argon2-cffi。快照 `snap-task1-app|test.py`、`snap-task1-r1-*`、`snap-task1-r2-*`。
- Task 1: minor (deferred, 共 9 条进终审分诊): 评审轮 7 条（大写 digest 死代码 `.lower()`、config 未用 Field(ge=1)、`hash_password` 不占槽却公开 `argon2_slot` 诱导双占、`needs_rehash` 抛裸 InvalidHashError、用例改名、豁免注释措辞、失败消息不指向旋钮）+ 复评轮 2 条（`test_credentials_contract.py:113-116` 透传断言是重言式、`:257-260` `from hashlib import *` 回退把同名局部函数也算命中——fail-closed 方向）。
- Ruling: `_DUMMY_PLAINTEXT` 常量留在代码里 — 复评独立判定它不削弱 constant-work/SEC-A-002/非重言性三条中的任何一条（`check_needs_rehash` 实测只是参数比较，不做 KDF），且没有它 F1 测试会在 dummy 原文轮换后静默退化成"喂不匹配的串"。代价：`verify_password(_DUMMY_PLAINTEXT, algorithm="argon2id", encoded=dummy_hash())` 仍返回 ok=True（公开 `dummy_hash()` 可达，修复前亦可读）——防线放 Task 5 的 seed 侧：不得把 dummy 串存成真实凭据行。
- Ruling: F5 扫描器拓宽后仍安全 — 复评实测 `backend/app` 里 hashlib 的引入点只有 3 处且全是 `import hashlib`，新的绑定解析不会给真实命中集加文件，等式钉 `{app/auth.py, app/credentials.py}` 仍精确。
- 计划侧待办（不在 Task 1 内）：#75 — Task 10 收口前把简报里 `11 passed` 的期望计数、M13/M16 变异片段强度一并校正。

## Task 2 — 凭据状态持久层（`user_store.py`）

- Task 2: complete-pending-review — implementer DONE；新建 `app/user_store.py`(302) + `tests/test_credentials_contract.py` 追加 2 个 TestCase（6 例，322→453 行）+ `app/config.py` 补 `conversation_db_path`（+5 行）；定向 27 passed（本文件）/128 passed（含 usage 契约门）、全套件 988 passed 两 cwd 相等（基线 982 + 6）。报告 `task-2-report.md`。
- Ruling: 渐进重哈希不 bump credentials_version（登录不改会话，只改强度）；只有改密/重置 bump。
- Ruling（计划缺陷，简报代码不可原样运行）：`_SCHEMA`/`_connect()` 依赖 `settings.conversation_db_path`，而这枚键在 `app/config.py` 里**从来不存在**（`conversation_store` 与 `llm.usage` 一直是各自 `os.getenv` 的）⇒ Task 2 补进 Settings，默认值与 `.env.example:103` 逐字相同（`data/conversations.db`）。
- Ruling（计划缺陷 2，同族 = V2.3 的库重定向）：`_connect()` **在每次连接时**读 `CONVERSATION_DB_PATH`，`settings` 只当"env 未设"的兜底。理由：会话级重定向发生在收集之后，import 期钉死的值恰好就是 `backend/data/conversations.db` 那份真库；简报的 `settings.conversation_db_path` 单读法会让 `UserStoreTransactionTests`（无夹具）直接写脏生产库。
- Ruling（计划缺陷 3，实测才会红）：简报 Step 1 的测试有两处跑不通，均**只动夹具不动断言**——① `UserStoreTransactionTests` 三条用例同名 `admin` 共享一份库 ⇒ `UNIQUE constraint failed`；抽出 `_CredentialDbPerTest` 每例一份临时库。② Step 1/4 的 `importlib.reload(config_module)` 换掉的是**进程级 settings 单例**，`app.main`/`app.llm.*` 手里还是旧对象，于是本文件之后跑的 `test_feishu_identity_contract.py::WarmupGateTests` 两例从仓库根起红（`FileNotFoundError: config\llm_registry.json`）；删掉这枚 reload（换库只需 env），并同步删掉随之失去用处的 `config_module` import。
- Task 2: minor (deferred): `_COLUMNS` 无消费方（简报原样保留）；`create_argon2` 撞主键时抛的是裸 `sqlite3.IntegrityError` 而非 `CredentialStoreError`（Task 5/7 的调用点需要翻译，别当成"口令错了"）；`CredentialRecord` 的默认 repr 含 `password_hash`（不是明文，但 Task 5/7 不得整条 repr 进日志）；`list_records`/`delete_record`/`clear_login_failures` 暂无用例覆盖（本任务只手工实测过行为），按契约归 Task 3/5/7。

## Task 2 — 凭据状态持久层

- Task 2: review round 1 — spec ❌ / Needs fixes（4 Important + 8 Minor）。评审独立确认：schema 与 §6.1 逐字一致、写签名的 `algorithm` 不可达成立、§8.8 提交边界（含 `closing()` 与事务上下文的退出顺序）正确、列面无明文字段、两枚真库无 `user_credentials`。
- Ruling: 计划初稿的 `settings.conversation_db_path` 是我凭空写的（该字段从不存在），Task 2 一度照它加进 `config.py` ⇒ 变成库路径的第二真源，且因 dotenv 不进 `os.environ` 而两个同库读者只读 env，生产里会把凭据表挪出 `conversations` 所在文件。裁定取"逐字照 `conversation_store.py:26-27` / `usage.py:223` 的 env 解析 + 模块级 `database_path()` 接缝 + 读路径不建表 + 回滚 config 字段"。代价：`app/llm/usage.py` 不可动，所以只能是 user_store 靠齐它，不能反向统一。计划正文 423/634 两处已同步改写，避免 Task 3 再抄一遍。
- Ruling: `database_path()` 接缝已暴露但 conftest 尚未 `install()` 到 `user_store` ⇒ F1 判闭合、把"装护栏"作为 Task 3 的显式交付（Task 3 是这张表的第一个真实消费者）。连带把"env 被清空时读路径仍会 mkdir 并留下 0 字节文件"一并交给 Task 3 钉。
- Ruling: `ACCOUNT_EXISTS_MESSAGE` 保留 username（仅启动面/CLI 可达）、`ACCOUNT_MISSING_MESSAGE` 不含任何账号名 ⇒ F3 判闭合；但 `test_credentials_contract.py:581` 把带名行为钉成了正向断言，Task 5 加 admin 建号路径时必须复核它没被引到登录面。
- Task 2: fix round 1/5 (5 addressed, 0 open) — 复评判 F1–F5 + 两条 fold-in 全 ADDRESSED，7/7 变异各杀其所指；无新增 Critical/Important。
- Task 2: minor (deferred): 新 AST 护栏漏收 `from app import config` 形态；`user_store.py:58-59` 注释声称两枚消息可等值分派而带名那条实际只能 `startswith`；`test:547` 措辞与"陈旧方向"已不再被演练（双向仍能杀变异）；`list_records/delete_record/clear_login_failures` 与 CHECK 拒绝第三算法值仍无用例；`.env:33` 目前与默认值同值，fork 是潜在非现行。
- Task 2: complete — `user_store.py`(345) / `test_credentials_contract.py`(605) / `config.py` 净零改动（加了又回滚）。全套件 **996 passed / 36 warnings / 1007 subtests**，两 cwd 相等（基线 982→988→996）。快照 `snap-task2-app|test`、`snap-task2-r1-app|test`。
- 交接给 Task 3：① 把 `LedgerGuard.install()` 扩到 `user_store`（seam 已 name-compatible）；② `import_legacy_digest` 不校验 64-hex，迁移器必须前置校验（脏行的正确症状是导入即拒，不是首次登录才炸）；③ 0 字节文件落点仍无人看；④ `create_argon2` 现在抛 `CredentialStoreError`，Task 3 的导入器不要把它翻译成"口令错"。
- 台账去重：上方"## Task 2 — 凭据状态持久层（`user_store.py`）"（第 49–56 行）是 implementer 自写的轮 1 记录，其"complete-pending-review"措辞与三条 deferred minor（`_COLUMNS` 无消费方、裸 `IntegrityError`、repr 含 hash）已被本轮修复与下方 controller 块取代。保留不删（append-only），以本块为准。

## Task 3 — 受限迁移路径（`credentials_migration.py` + 升级工件）

- Task 3: complete-pending-review — implementer DONE。新建 `app/credentials_migration.py`(193) + `data/legacy_credentials.json`（5 条，gitignored，closure 删）；`tests/conftest.py` 护栏扩到凭据面；`tests/test_credentials_contract.py` 追加 3 个 TestCase / 22 枚用例（605→1081 行）。定向 **57 passed / 17 subtests**（基线 35/9），三套依赖护栏的套件 **585 passed / 502 subtests**，全套件 **1018 passed / 37 warnings / 1018 subtests** 两 cwd 相等（基线 996→1018）。真库证据：`backend/data/conversations.db` 表清单 = conversations / llm_request_logs / message_sources / messages / sqlite_sequence，**无 `user_credentials`**；仓库根那份历史库同样无。报告 `task-3-report.md`。
- Step 1 由正则脚本从 `app/auth.py:71-103` 生成工件（`5 ['admin','hr01','sales01','user','viewer']`），并用 `auth.USERS` 的字典值做了一次等值复算（`artifact == {u: d["password_hash"]}` → True），零手抄。
- Ruling: 迁移器只校验凭据形态（64-hex / 顶层键封闭）；身份交叉校验留到 Task 5 的启动 seed 编排，因为身份层 Task 4 才存在。
- Ruling: 重跑导入对已存在行只跳过，绝不把已升级的 argon2id 行降回 legacy。
- Ruling（简报实现的两处补强，方向都是"报告与实际行数不许分叉"）：① `import_legacy_digest` 的返回值（`ON CONFLICT DO NOTHING` 的 rowcount）必须参与报告——返回 False 落进 `skipped` + `reason`，不许进 `imported`，否则 SECA-04 用的那个数与实际行数对不上；② `user_store.CredentialStoreError` 原样逃出 `import_from_artifact`，不 catch、不咽成 `skipped`、不翻成认证结论（Task 2 移交 ④）。
- Ruling（简报 `read_artifact` 的三处收紧）：出处两键（`generated_at`/`source`）必在场且非空、`credentials` 为空 ⇒ 报错而不是当成"没有工件"、用户名带首尾空白 ⇒ 拒（不静默 trim）。理由：§8.2 的"升级工件 ≠ 全新安装凭据来源"是整节立论，机器可辨的差别只有出处字段与"在场但导 0 人"这两种状态；空 `credentials` 被读成"没有工件"会把升级失败伪装成不需要升级。
- Ruling（Task 2 移交 ① 的落地写法）：凭据面的写证据取自 **sqlite `set_trace_callback` 回传的语句文本**（含 DDL），不取"函数名清单"，也不做连接代理对象。原因：`user_store` 没有 `usage._execute` 那种写收口，读腿与写腿都直接 `_connect()` ⇒ 归类只能在语句执行时补（先记 read、由写语句升成 write）；清单那套要求"以后加一条写腿记得回来加名字"，忘的那一次是静默的，而代理对象会改掉 `connection` 的类型身份。护栏因此**另开一个 `LedgerGuard` 实例**（同目标文件、不同 records），判红消息与终端汇总才说得出是哪张表。
- Ruling（同一枚接缝的副作用）：`UserStoreIsolationTests::test_the_effective_path_is_the_siblings_own_env_key` 改读 import 期捕获的 `RAW_DATABASE_PATH`。护栏一装，`user_store.database_path()` 在 env 清空时给的就是改道目标，原断言变成"护栏自证"；断言的两枚期望值逐字未动。钉"护栏在场"的是新增的 `CredentialGuardWiringTests`，两条各管各的。
- Task 3: minor (deferred): conftest 凭据面两处防御分支无用例覆盖（`guarded_store_connect` 开头的 pending 预清、`_upgrade_record_to_write` 的位置对不上时改记一笔）——都只能靠外部构造，失败方向是过判红而非静默；`warn_on_read=False` 这条显示层选择不设钉；`LEGACY_INPUT_PATH` 是相对路径（与库默认值同口径），Task 5 的启动编排必须按后端 cwd 解析；导入中途抛存储事故时已落的行保留（重跑幂等），简报未要求回滚整批。
- 变异自检（临时改产品/护栏代码、跑定向、逐字还原，不留文件）：9 发中 7 发 KILLED；两发（去掉 `only_missing` 跳过、写标记做成 latch）第一次存活 ⇒ 各补一枚钉子（`writer.call_count == 0`、多语句连接只升一次）后复跑 KILLED。明细在 `task-3-report.md`。

## Task 3 — 受限迁移路径

- Task 3: review round 1 — spec ✅ 主体 / Needs fixes（5 Important，全在护栏与扫描的形状，不在迁移模块本身）。评审独立复核：5 枚 digest 与 `auth.USERS` 逐字节相等且保持声明顺序（证明是脚本生成而非手抄）、整件拒收、绝不降级已升级行（并用 `writer.call_count==0` 钉住）、`CredentialStoreError` 不被翻译、报告面不含任何 digest、LF 全部保持、untouchables 的 git diff 为空。D10（改一处 Task 2 用例）被判为**加强而非放松**：改成比对 import 期捕获的产品函数，且该文件其余断言一字未动（评审用 `diff -u` 逐 hunk 核过）。
- Task 3: minor (deferred): `LedgerGuard` 类名已只描述一半职责（凭证面也叫它）⇒ 建议改名 `RedirectGuard`，但调用点会随 Task 5–9 增长，留到收口前一次性做；`MigrationReport.skipped` 把"已存在跳过"与"写方拒收"合成一个元组，Task 7 的 CLI 要打印它 ⇒ 落地时拆成 `skipped`/`declined`；`credential_redirects()`/`credential_read_redirects()` 零调用点；`test:1067-1068` 的 `assertIn(columns, ([], ...))` 两态都接受（真钉是前后的快照）。
- Ruling（评审 ⚠️4 暴露的规格↔计划缺口）：规格 §8.7 要 `migration-status` 打印"最后成功登录时间"，而 `user_credentials` 无此列、`AccountStatus` 无此字段。裁定**不加列**：Task 7 的 CLI 与 Task 10 的证据从既有审计面派生（`knowledge_os.py:687-701` 已有同一手法），审计尾部找不到即打印 `-`。理由：为观测字段动认证主表的 schema 会把 §8.8 的事务不变量拖进来；代价：审计轮转后该字段变未知，这是可接受的观测退化，不是安全退化。
- Ruling（I4/I5 是真缺陷，进本轮修）：`LEGACY_INPUT_PATH` 与账本路径只在 `CONVERSATION_DB_PATH` 为相对值时同生同死；容器/systemd 用绝对路径时"升级静默零行 + 报告说没事可做"会直接违反 SEC-A-003，故要求 reason 带解析后的绝对路径 + 注释改写。I5 的真库哨兵必须从"==0"改成"会话期间不增长"，否则 Task 7 起任何跑过 dev bootstrap 的机器永久假红。
- Task 3: fix round 1/5 (13 addressed, 0 open) — 复评逐条判 I1–I5 + M1–M8 + J/K + §5 字节漂移全 ADDRESSED，无新增 Critical/Important。全套件 **1029 passed / 36 warnings（回到基线）/ 1036 subtests**，两 cwd 相等；焦点文件 68 passed / 35 subtests / 0 warnings。复评还独立在进程内量了 I1 的 7 正向 + 4 负向与真实命中集。
- Ruling: M1 采用 `catch_warnings()` 而非"把调用挪出 patch 块" — 复评认同：要断言的是"两张表在**同一 env 条件**下解析到同一文件"，挪出去会让一侧读宿主 env、另一侧读护栏目标，正好造出实现者点名的假红。代价：抑制点必须窄（只包两次调用），已核。
- Task 3: minor (deferred): I1 新扫描窄了一种形态（`from app import credentials_migration` 后走 `credentials_migration.user_store.import_legacy_digest(...)` 的两段链会被判为外部模块而放过；实测旧规则 1 命中、新扫描 0）⇒ 收口前补一句"链尾解析到模块绑定时按未知计入"或把它写进 `:849-851` 的残余边界清单。另：`conftest.py` 收尾两处 raise 会跳过 uninstall（进程即将退出，可接受）；会话末多两次真库只读打开（当前真库无该表，窗口为零）。
- 交接给 Task 4/5/7：① `credentials_migration.py:151-153` 的两条前置（先 `ensure_user_credentials_schema()`；容器/systemd 下显式传绝对路径）必须由 Task 5 的启动 seed 满足；② `MigrationReport` 的 `skipped` 已把"已存在跳过"与"写方拒收(declined)"合并，Task 7 的 CLI 打印前拆成两字段；③ 最后成功登录时间从审计面派生，不加 schema 列；④ `conftest.py:710` 与 `credentials_migration.py:196` 仍带任务/交接措辞，Task 5 改 conftest 时一并清；⑤ `LedgerGuard` 改名 `RedirectGuard` 留到收口前一次做。
- Task 3: complete — `credentials_migration.py`(217) / `conftest.py`(751) / `test_credentials_contract.py`(1442) / 工件 `backend/data/legacy_credentials.json`（gitignored，字节与快照一致）。快照 `snap-task3-*`、`snap-task3-r1-*`。

## Task 4 — 身份声明层（`directory.py` + `users.json` / `users.demo.json`）

- Task 4: complete-pending-review — implementer DONE。新建 `app/directory.py`(216) + `config/users.json`(空) + `config/users.demo.json`(5 条，脚本从 `auth.USERS` 生成并复算等值，零手抄) + `tests/test_user_directory_contract.py`(523 / 49 例 / 37 subtests)；改 `app/config.py`（+`security_enterprise_mode`，在 `jwt_secret` 之前）、`app/knowledge_os.py`（四处身份读点 + import，其余零改动）。焦点 49 passed、迁移门 135 passed、SEC-A 扫描 68 passed/0 warnings、出口守卫 35 passed；全套件 **1078 passed / 36 warnings / 1076 subtests**，两 cwd 相等（基线 1029+49，warnings 未增）。快照 `snap-task4-app`、`snap-task4-config`。报告 `task-4-report.md`。
- Ruling: directory 不校验 role 白名单（未知 role 已由 access_role_for→空权限 fail-closed），避免造第二个真源。
- Ruling: Task 4 结束仍保留 auth.USERS + 一枚过渡一致性钉；Task 5 删 USERS 时连钉一起删。
- Ruling（简报内部矛盾，必须让评审知道）：简报 Step 2 的 `test_a_legacy_digest_value_is_rejected_even_under_an_allowed_key` 用 **40 位** hex，而 Step 4 的实现按 `^[0-9a-f]{64}$` 判——逐字实现跑不过逐字用例。裁定把形态判定放宽为"纯 hex 且 ≥40 位"（含规格的 64-hex 原形与 SHA-1/384/512），下限停 40 而非 32（32 位纯 hex 恰是 UUID 无连字符的长度，把机器账号拒在启动期的代价高于顺带拦下 MD5 的收益），并补一枚反向钉子钉住该取舍。计划正文 Task 4 的该枚正则若要复用，须同步改。
- Ruling（同族补强，方向都是"身份文件结构上无口令"）：形态扫描改为**递归**（嵌套 `{"display_name": {"password": …}}` 在简报版里会一路走到 pydantic，而默认报错文本回显输入值 ⇒ 凭据材料进启动日志）；字段校验器的报错改取 `loc + type`（不回显取值，原文留在 `__cause__`）；`read_text` 增拦 `(OSError, UnicodeDecodeError)`（与 `credentials_migration.read_artifact` 同一条既有裁定）；`feishu_open_id` 加 `min_length=1`（空串会被当成"有值"，两个未接飞书的账号假冲突）；`_validate_records` 的占位 `payload` 改为"传值即拒"。逐条理由与用例在 `task-4-report.md`。
- Ruling: `list_users` 的 `"status"` 仍恒为 `"ACTIVE"` — 简报限定 `knowledge_os.py` 只动四处读点，把 `enabled` 接到展示面属于行为改动。交接 Task 5：哑校验落地时一并决定名册怎么显示停用的人（现在会显示 ACTIVE）。
- 环境事实：`backend/Dockerfile:18` 早有 `COPY config ./config`（WORKDIR `/app` = `backend/`）⇒ 本任务不需要改 Dockerfile；Step 3 期望的 `ModuleNotFoundError` 实测是 `ImportError: cannot import name 'directory' from 'app'`（`app` 是包），同因不同措辞。`app/config.py` 的工作副本在开工前就整体是 CRLF（`snap-task1-app/config.py` 即 178/178），本次按 Edit 保留原形态未做整文件翻齐——翻齐会产生 182 行幻影 diff。
- 变异自检（临时改产品代码、跑焦点、逐字节还原，12/12 KILLED、`restored=True`）：M1 字典覆盖式合并 / M2 摘要形态检查整体失效 / M3 敏感键黑名单失效 / M4 企业形态照读 demo / M5 open_id 唯一性 / M6 接缝不还原 / M7 `enabled` 默认值 / M8 报错回显输入 / M9 空串 open_id / M10 部门不再由 role 派生 / M11 `total_users` 退回常量 / M12 总开关默认值翻 true。

## Task 4 — 身份声明层

- Task 4: review round 1 — 规格 ✅ / 质量 Approved，但两条 Important 落在本任务自己的投影面（评审独立核过：合并顺序是真序不是字典巧合、demo 文件在企业形态"根本不被读"是结构事实、D1 声称的简报自相矛盾属实（简报测试用 40-hex display_name，简报实现的 `^[0-9a-f]{64}$` 放它过去 ⇒ 逐字实现必红自己）、四处 `knowledge_os` 读点字段/顺序/last_login 逐 hunk 无语义漂移、演示身份文件与 `auth.USERS` 记录逐字节同）。
- Ruling: 不加角色白名单（未知 role 已由 `access_role_for`→空权限 fail-closed），不在 directory 造第二个 role 真源。评审确认该裁定被实现忠实执行。
- Ruling: 值形态门由"64-hex"放宽为"hex-only ≥40"是**收紧方向的正确修正**——它仍拒规格点名的 64 位摘要，新增覆盖恰好是 40–63 带（SHA-1 形态），而 `ou_…`（含下划线、约 35 字符）、role（≤32）、CJK 显示名都不落入；32-hex UUID 边界有反向钉。计划正文的正则待回写。
- Task 4: fix round 1/5 (8 addressed, 0 open) — I1（roster 投影 `enabled`，注释不再把契约推给认证腿；`directory.py` 里同一句谎言的第二副本一并改掉）、I2（去掉假分母，空目录 `adoption_pct=0.0`）、M1/M2/M3/M4/M7/M8 全 ADDRESSED。复评**不采信报告的变异表**，自行重导：X1=2（并推出 `SUBFAILED(value='ffffffff')` 的对应关系）、X5=1、X6=3、X7=2、R2=47→36=11，且用仓库外探针证实"子测试失败只出 `SUBFAILED` 不出 `FAILED`"这一误读机制真实存在 ⇒ 变异证据可信。全套件 **1083 passed / 36 warnings / 1086 subtests**，两 cwd 相等；11/11 变异全杀。
- Ruling（I1 的半收敛）：roster 已报 DISABLED 而登录腿尚未消费 `enabled`，判为**可接受的中间态**而不是新缺陷——发布配置里不可达（企业文件为空、demo 全 enabled 有钉）、roster 在 `audit:read` 之后不是枚举面、规格 §7.3 的口径只管登录响应。理由：修前是"roster 断言了一个文件本身否认的事实"，修后两面读同一字段、只有一个动作它——可见滞后优于静默说谎。Task 5 必须把它收敛掉。
- Task 4: minor (deferred): `adoption_pct=0.0` 仍把"零采用"与"无分母"混为一值，且 `OperationsView.tsx:132` 会在 0% 旁边渲染 `2/0` ⇒ 需要 null + `?? "—"` 的形状变更，随前端一起排；`directory.py:159-163/183/190-192` 短于 40 的未知键与重名消息里的 username 仍可入消息；`knowledge_os.py:704` 那句现在读起来像描述也像规范，Task 5 实现后应回落成纯描述。
- 交接给 Task 5（本轮新增）：⑥ 登录腿必须消费 `enabled=false`（哑校验 + 统一 401），否则半收敛不收口；⑦ `test_credentials_contract.py:581` 把带 username 的 `ACCOUNT_EXISTS_MESSAGE` 钉成正向断言，Task 5 不得把它引到登录面；⑧ `directory.load_identities` 的 `payload` 死参数按简报裁定在 Task 5 删除；⑨ conftest 与 credentials_migration 里残留的两处任务/交接措辞注释由 Task 5 顺路清。
- Task 4: complete — `directory.py`(244) / `knowledge_os.py`(937) / `test_user_directory_contract.py`(600, 54 例) / 两份 config（企业侧发布为空）。快照 `snap-task4-*`、`snap-task4-r1-*`。

## Task 5 — 认证腿原子切换

- 事故记录：Task 5 的实现子代理**撞上 150 轮上限**，返回 "Agent execution completed" 但**没有写报告文件**。控制器自查工作树：模块全部可 import、无 TODO/半成品痕迹、LF 未被翻（`main.py` 15+/12− 是外科式改动，不是整文件重写）。代码本体是完整的，缺的是报告与一次全套件。
- 控制器自查抓到的真回归（焦点门与 SEC-A-006 门都没覆盖到它）：全套件 **7 failed / 1109 passed**，全部在 `test_model_router_v23_contract.py::RagModelFaceTests`，死因是 `authed_client()` 登录 401——Task 5 把口令校验搬到 `user_store` 后，该夹具类没拿到凭据行（Task 5 只给同类里另一个类加了 seed）。这既不是 V2.3 契约错，也不是 SSE 键集变了，而是测试地基漏种。
- Ruling: 修在测试侧，**不碰任何 V2.3 断言**。落法是分两层：`_RagMigrationFixture.setUp` 复制一份进程内凭据模板到本例临时库（避免每例重算 Argon2——实现量到 661 vs 11 次运算、45–99s vs 160–165s），`authed_client()` 再在登录接缝兜一次 seed。判据是"未来任何子类不可能再静默 401"，而不是只补那个类。
- Task 5: seed-fix 复验（控制器读的数）——全套件 **1116 passed / 36 warnings / 1091 subtests，两 cwd 逐位相等**；v23 单文件 392 passed；`[credential-guard]` 报告 0 行、两枚真库仍无 `user_credentials`；还原两处 seed 放置后 7 条精确复红（只还原基类那层则仍 392 passed，证明两层各司其职），还原后 sha1 `74be7266…` 字节一致。
- Ruling（遗留冲突，交给 Task 10 收口判）：`test_real_llm_failover_acceptance.py:685` 的 `_http_face_200` 用运行时自建库，既无 schema 也无凭据行 ⇒ SEC-A 后再跑 P0 会 401。但该文件字节被哈希锁进已封存的 V2.3 P0 证据，补这一行会让 `test_real_llm_failover_gate::test_p0_row_status_matches_the_evidence` 红（sha1 对不上）。裁定：**不在本轮单方面改**，两条出路留给收口——要么带着这行重跑一次真 P0 并重新出具证据，要么把该文件登记为"SEC-A 后不可直接复跑"。本机当时也没有可用的双模型现场，任何一边都不能靠猜。
- 过程裁定：Task 5 的 TDD RED/GREEN 逐条实录**缺失**（实现者未写报告即耗尽轮次）。本任务的验证证据因此是控制器自跑的数，不冒充实现者的 TDD 链条；评审按"无报告"的前提进行。
- Task 5: fix round 1/5 (10 addressed, 0 open) — 复评逐条判 I-1…I-5 + 五条 Minor 全 ADDRESSED，无新增 Critical/Important。全套件 **1125 passed / 36 warnings / 1096 subtests，两 cwd 逐位相等**；复评另独立跑了五项回归检查（I-2 臂序、I-4 生产写方可达性、I-1 审计确定性顺序、v23 断言成本、五文件 sha1 与 §4 一致）并对"enum 违规 raise 是否可达生产路径"给出否证（调用点只有 main.py 两处，取值全部来自同模块四个 LoginResult 构造）。
- Ruling: 丢竞争分支仍写 `AUTH_REHASH_DEGRADED`（行已不是 legacy 时也报）= **接受过报**。理由：收口判定权在 `legacy_count` 的 SQL 门，不在审计流；压制它反而会丢掉"丢竞争"这件事的唯一信号。代价：审计里偶有语义偏宽的降级事件，终审可再判。
- Ruling: I-3 的容量pin按"断言今天真实的未翻译 500 + 零审计事件"落地，Task 8 加 503/429 翻译时它会**变红而不是静默通过**（复评验证过：仓库无任何 exception handler，500 确是未处理逃逸）。Task 8 必须改断言、不得删断言。
- Task 5: minor (deferred): `test_model_router_v23_contract.py:4605` 仍留一个用例内自 seed（同类自愈模式，Task 10 一并清）；`install_demo_credentials` 的 exists 分支与 `_ensure_credentials_at` 今日无调用者、无专用用例；naive `locked_until` 落在过去会被读成"永久锁定"（与"坏值即锁定"一致，本仓写方产不出，但值得在凭据表文档里写一行）；`test_no_artificial_delay` 只认被调名 `sleep`，`Event().wait()` 之类会漏。
- 过程缺陷（不遮蔽）：Task 5 的实现者未写 TDD 报告即耗尽轮次；且本轮第一份评审包 section B 生成有缺陷（承诺 conftest/feishu/v23 实际只给了对 `bc43ca3` 的 conftest diff，混入 Task 1–4 的 441 行且漏掉 feishu 116 行 / v23 28 行），复评是被迫直接打开测试文件才完成判定的。**教训已生效**：后续每任务在派工前先取 `snap-taskN-pre-*`，评审包按"上一任务末尾"作基线而不是仓库 HEAD。
- Task 5: complete — `auth.py`(160-290 段全新) / `main.py`(15+/12−) / `sec_a_seed.py` / `test_authentication_leg_contract.py`(43 例) / feishu 两条用例换注入接缝 / v23 夹具 seed。快照 `snap-task5-pre-*`、`snap-task5-post-*`。

## Task 6 — 令牌生命周期（`cv` claim、revocation、端点覆盖门）

- Task 6: complete-pending-review — implementer DONE_WITH_CONCERNS。`app/auth.py`（+`CREDENTIAL_VERSION_CLAIM`、`issue_token` 签 `cv`、`_user_from_token` 三态并入 + 读表比版本）/ `app/main.py`（两处 additive 键，779/779 CRLF 保持）/ 新建 `tests/test_password_lifecycle_contract.py`(750 行，32 例 / 5 subtests) / 认证腿 +3 例（43→46）/ feishu +2 例且 2 例改夹具形状（101→103，警告数未动）。RED：新文件 `29 failed / 8 passed`（红在 `AttributeError: CREDENTIAL_VERSION_CLAIM` 与 `KeyError: 'password_change_required'`）；实现后既有面先红 4+2 枚（预言命中），改后绿。全套件 **1162 passed / 36 warnings / 1101 subtests，两 cwd 逐位相等**（基线 1125+37）；SEC-A-006 门 140 passed（+2）、V2.3+出口 427 passed、D6 计数与 `/api/query` 键集钉未动。真库复核：两份 `conversations.db` 仍无 `user_credentials`、`[credential-guard]` 零笔、审计文件里本任务账号名 0 次。报告 `task-6-report.md`。
- Ruling: issue_token 在无凭据行时签 cv=0（一签发即死），不另开第二条构造路径。
- Ruling: must_change 门覆盖面由路由表枚举生成；新端点带未登记 path 参数时用例主动 fail 并要求登记样例。
- Ruling（简报文本的四处"照抄必坏"，方向都是把覆盖面读全）：① 方法字母表必须含 `PATCH`（今天两条真实端点会让简报的 `[0]` 直接 IndexError），且一条路由的多方法逐个拆行而不是取第一项；② `_routes_using(auth.require_permission)` 实测返回空集（路由拿的是工厂内层闭包），改判"对象身份 **或** 限定 qualname"，工厂名用 `require_permissions`；③ `PARAM_SAMPLES` 补 `action`/`case_id`/`file_name`（表上 8 个 path 参数，简报那 7 项盖不住）；④ 枚举必须 `import app.main_agent`——生产入口是 `app.main_agent:app`（Dockerfile CMD），只 import `app.main` 时表上只有 19 条端点、认证面 14 条，门就成了只看半张表；另钉 `MUST_BE_COVERED` 防"依赖树读空也绿"。
- Ruling（Step 1 夹具不改就用不了）：`setUp` 必须调 `super().setUp()`、`LoginFaceKeyTests` 要有 client、每例叫 `seed_demo_credentials()` 会污染 `SEED_RECORD` 并撞红 SECA-24 的计数钉 ⇒ 全套改用既有形状（`_fresh_db` + `ensure_demo_credentials()`）。WHITELIST 上方那句注释按"注释不叙述任务"改写，强度不变（白名单外泄那发反证证明它今天就能红）。
- Ruling（被 §7.5 合法改变形状的 6 枚既有用例，零放宽）：认证腿 `MustChangeGateTests` 三枚改用 `_gated_token()`（换代在前、签发在后，403/文案/审计 token 三条断言一字未动）+ `test_after_the_password_change_the_data_face_opens` 改成"旧 token 401 → 重登 → 200"（变强）；feishu `test_forged_claims_do_not_widen_permissions` 的自签 payload 补 `cv`（不补就死在认证步，那三条断言变死码）、`test_login_and_me_bodies_do_not_leak_grant` 由"一份期望集套两体"改成"逐体等值钉"（`user` 子体期望一字未动，正是"新键只在顶层"的证据）。新增 5 枚反向钉：dead token 撞不到门（401≠403）、claimless 必拒、伪造 `cv` 换不来会话、`cv` 类型判定含 `bool`、无凭据身份的 `cv=0` 永不复活。
- 变异自检（字节安全台原先在仓库外 `C:\tmp\t6\mutate.py`，修复轮搬进 `.superpowers/sdd/SECURITY_A_PLAN/mutations/task-6-mutations.py`；六发全 KILLED、每发 `restored sha1 match = True`）：M2 去门 → 枚举报出全部 41 条未覆盖（`authenticated - pending` 是 41 条而不是 40：`GET /api/auth/me` 走免门腿、从来不在 `authenticated` 集合里，所以不减）；M3 去掉版本比对 → 只有三枚真·版本用例红（删行/停用那两条不动，归因准确）；M17 `cv is None` 放行 → 依赖面 / `/api/query` HTTP 面 / feishu 反钉三处同时红；把 `GET /api/audit` 错挂到免门依赖 → 白名单等值钉红并指名该条；插入 `GET /api/zz-probe/{widget_id}` 新端点 → 用例红在"未登记的 path 参数，请登记样例"；把登录面改成第二次读表（`main.py` 的 additive 键 → `_password_change_required(user.username)`）→ 登录面那枚用例红。
- Task 6: 交接给 Task 7 的硬事实：改密成功那一刻旧 token 连 `/me` 也进不去（已钉），所以改密端点必须同响应签一枚新 token，且 `WHITELIST` 要同时扩成两项（漏扩必红，已用变异证成）。上线即一次强制重登录（SECA-09b 的代价）必须进 §15 release note，不得写"无感升级"。
- Task 6: minor (deferred)：① 每个认证请求现在读两遍同一凭据行（token 腿 + `_password_change_required`）——并掉的两种写法都会破坏"凭据不进 `CurrentUser`"或"构造面唯一"这两条裁定，留给 Task 8 的每请求成本一起量；② `main.py` 导入下划线名 `_password_change_required`（简报明写，且它就是"两处判定同源"的钉子），若收口要公共名是一次两行改名；③ 枚举行天然不管"压根不挂认证依赖"的新端点（简报拒绝维护豁免清单，本任务不擅自反转）；④ 规格 `:458` 那句"全仓无登录响应键集合断言"不成立（`test_feishu_identity_contract.py` 的 `_LOCAL_KEYS` 等值钉就是），Task 10 验收文档不得照抄。
- Task 6: fix round 1 (3 Important + 7 minors addressed) — **I-1**：覆盖面扫描不再把安全性押在"门会先挡住"上。每条被枚举的路由先把 `dependant.call` 换成绊线桩（FastAPI 每请求现取该属性，故不重建路由、依赖树照旧跑、403 仍来自真门），发请求前全部上桩、逐条核对"路由器派发的那一枚 == 我桩的那一枚"（复现 Starlette 的 `matches()` 首个 FULL match）、再断言绊线零响 + demo 破坏性入口设哨零调用 + 扫描后不留桩；M2 反证实测：绊线报出 41 条、`POST /api/demo/reset` 返回测试桩的 599 而 `reset_demo()`/`initialize_demo()` 未被调用、演示语料指纹未变。**I-2**：`_password_change_required` 的桩改打在 `app.main` 自己那份绑定上（`from app.auth import` 是 import 期复制名字，打 `app.auth` 够不到调用点），并加"桩必须在处理器 `__globals__` 查找路径上"的非虚设核对 + 两枚反向用例（`/me` 经同一个判定 / `app.auth` 那一格改不动响应面）；命名 `main.py:261 → 第二次读表` 的变异已能红。**I-3**：`_fresh_db` / `_AuditToTempFile` / `_LongJwtSecret` 三份逐字符相同的副本搬进新模块 `backend/tests/sec_a_fixtures.py`（不叫 `helpers.py`），两个契约文件各自只留薄别名。Minors：40→41 的计数措辞（测试消息 + 本报告 + progress）、`PARAM_SAMPLES` 的 `kb_public` 换成必然不存在的 id、方法字母表与"无挂载点/无非 APIRoute 服务面"两枚前提钉、扫描的 `AUTHORIZATION/DENIED/password_change_required` 逐条计数、`_gated` 的吞诊断改成 `(route, status, detail)` 全量上报、`CurrentUser` 构造面由数子串改 AST。全套件两 cwd 同数、变异台 6/6 KILLED。证据文件 `task-6-fix-report.md` **不存在**（实现子代理在报告阶段耗尽轮次），本段即控制器 + 复评重建的记录。

## Task 6 — 令牌生命周期（勘误 + 收口）

- 勘误（复评抓到）：上一段引用的 `task-6-fix-report.md` 从未生成——实现子代理第二次撞上 150 轮上限，死在报告阶段。代码是完整的（复评逐条判 I-1/I-2/I-3 + 7 条 minor 全 ADDRESSED），但那段"变异台 6/6 KILLED、绊线实测 599"的自述**当时没有可复核产物**。复评用只读方式独立复现了稳态那部分（扫 41 条、破坏性入口不可达、599 只在门打开时可达），变异运行无法复核 ⇒ 该数字按"未证"处理，Task 10 不得引用。
- Ruling: `progress.md` 里"三份逐字符相同的副本"说法不准（当时只有两份，第三份是新模块）；保留原文不改，以本条为准。
- Ruling: 复评认定本轮整个修复**全在测试侧**（`diff -rq` app 只差 `__pycache__`，feishu 快照与工作树逐字节相同）⇒ 生产码没有可归因于修复轮的改动，Task 5 的腿保持原样。
- 复评新发现（记为 minor，不重开循环）：`test_both_faces_resolve_the_gate_predicate_through_one_binding` 三分之二是同义反复（`__globals__` 就是同一个模块 dict）；对齐守卫是"事后检出"而非"事前防止"（同一迭代里先发请求再断言，只有 demo 破坏性入口另设哨）；`fresh_db` 的 restore 注册在建表之后（异常路径会把 env 留在临时文件上，两份旧副本本来就是这样，非本轮引入）；`_callee_name` 数的是"调用"不是"构造"（`model_validate` 会漏）；变异台 `interesting()` 有一个永不匹配的键；`task-6-report.md:119` 描述 M2 时仍提已删掉的 `unattended` 变量；`:866` 那句 AddCleanup 顺序的中文说明写反了（结论正确、句子反了）。
- 流程教训（对 Task 7–10 生效）：测试侧重构最容易吃轮次（Task 5、Task 6 各一次）。后续派工**先写代码、先跑门、最后写报告**，并把"报告优先于完美"写进 dispatch；一旦接近上限，报告里允许只写已证事实。
- Task 6: complete（修复轮复评 clean）— 全套件 **1168 passed / 36 warnings / 1101 subtests，两 cwd 逐位相等**；六文件门 567 passed；焦点 84 passed / 12 subtests（复评自己再跑一遍生命周期文件：38 passed / 5 subtests，且真库与审计指纹跑前跑后一致）。

- Ruling (SEC-A T7): 管理员重置端点对不存在身份保留 404「账号不存在」——那是已鉴权管理员面对的资源面，不构成对外枚举面（登录腿才是）。
- Ruling (SEC-A T7): CLI 口令只读 CREDENTIALS_PASSWORD，用完立即从 environ 弹出；「没设」与「太短」汇成同一句提示且不回显取值；argv 上没有 --password（argparse 行为级钉死）。
- Ruling (SEC-A T7): 改密腿必须回吐新签 token——版本 bump 会废掉来路那枚 token（Task 6 已钉），否则强制改密流程把人弹回登录页。响应面 = changed / access_token / token_type / password_change_required。
- Ruling (SEC-A T7): 新口令的 12 字符下界由 validate_new_password 以中文 422 给出，请求模型 min_length 保持 1（与 LoginRequest 同形）；把下界写进 pydantic 会让展示面变成英文结构错误，违反 §9.1。
- Ruling (SEC-A T7): must_change 语义分叉——自助改密 0、管理员重置 1、CLI reset 1 / bootstrap-admin 0；两条腿共用 auth.provision_credentials 这一条写路径（清锁与 bump 因此不可能只发生在一支）。
- Ruling (SEC-A T7): 回声规则（新口令=账号名）在 HTTP 面上对 admin 永远轮不到（casefold 等值串短于下界），判据改用 ≥12 字符账号名，函数级判据保留 admin/ADMIN/AdMiN。
- Handoff→T8: 改密腿与登录腿共用同一份账号级 throttle/lock（不自造第二把计数器）；T8 的两层节流必须覆盖 POST /api/auth/password/change。
- Handoff→T10: 管理员重置的审计笔只记了执行者（record_event 无 target 字段，CLI 侧记的反而是目标账号）——「谁重置了谁」目前只能靠凭据版本 bump 反推。
- SEC-A T7 交付数: 全套件 1193 passed / 36 warnings / 1111 subtests，两种 cwd 相等（进入 1168/36/1101：+25 测试；subtests +7 来自本文件新增策略表，+3 来自 test_feishu_identity_contract 的按源文件/按端点扫描多看见 app/cli.py 与两条新端点）。
- Task 7 fix round (评审 5 Important + minors)：P0 响应体口令回显（去 change/reset 两腿 max_length +
  按路径作用域的 RequestValidationError 中文脱敏处理器，既有端点默认载荷逐字节不变）；P1 三腿补
  `password_policy_rejected` 审计；P2 migration-status 派生"最后成功登录时间"+打印 updated_at（不加
  列，从审计面取）；P3 `record_event` 增 keyword-only `target`（additive）+ 补 HTTP 重置事件覆盖；
  P4 自重置裁定可放行并钉效果；P5 统一上限常量、重写近不可杀用例、消除未来 KeyError、
  CredentialStoreError→中文 500、修计划叙述注释、更正本报告的 capacity 误判。
  **移交 Task 8（capacity）**：`/api/auth/password/change`（经 `authenticate_with_result` 验旧口令）
  与 `/api/admin/.../password/reset`（provision 时哈希新口令）**都是第二条未翻译的 `PasswordCapacityError`
  →500 面**（此前报告称"够不到"是错的，已更正）。Task 8 的两层节流/并发闸门落地时，须把这两条腿的
  `PasswordCapacityError` 一并翻成 §9.1 的中文 503（`服务繁忙，请稍后重试` / token `password_capacity`）。
  **（Task 8 修复轮更正这条移交的前提）**：change 腿那半成立（它经 `authenticate_with_result` 验旧口令 ⇒ 真会抛）；reset 腿当时**够不到**——`credentials.hash_password` 不占 `argon2_slot`，provision 写入压根不产生 `PasswordCapacityError`，于是『给 reset 腿补翻译』当时是给一面不可能出 503 的脸补翻译。真正的残留是写入侧在闸门外做同档运算（见文末 Ruling (Task 8 fix, F3)）。

## Task 7 — 改密 / 管理员重置端点与 CLI

- Task 7 review round 1 — 规格 ✅ / Needs fixes（5 Important，其中 P0 是真凭据泄漏：`RequestValidationError` 默认体在两个新端点上把提交的口令原样回显，实测连"只漏填 new_password"这种请求都会把用户**当前有效口令**映进 `detail[0]["input"]`）。评审同时独立证明 R-1 裁定正确：简报第 61 行钉 `{"changed": true}` 全文、第 66-71 行又钉旧 token 仍 200，两句在 §7.5+§8.8 下不可能同时成立。
- Task 7: fix round 1 (P0×3 + P1–P4 + P5×7 addressed) — 全套件 **1207 passed / 36 warnings / 1111 subtests，两 cwd 逐位相等**；焦点文件复评自跑 77 passed / 12 subtests 且真 `data/audit.jsonl` mtime 不动（审计确实重定向到临时文件）。
- Ruling: 自管理员端点重置**自己**的口令 ⇒ 允许并钉住（同 host 上 CLI 本来就能达成同一结果，HTTP 侧拒绝只是剧场），缓解面是 `must_change=1` + `cv` bump 会连带杀掉操作者自己的会话；理由以不变量写进 `main.py:389-393`。
- Ruling: `record_event` 加可选 `target`（纯增量，`None` 被既有的 `if value is not None` 过滤掉 ⇒ 无任何既有事件多键）。控制器自己按字节核过：去掉换行归一后内容差就是 4 行，`audit.py` 从 64 CRLF/16 LF 混排归一为纯 LF 是修复轮的附带清理，控制器认可（"app/*.py 保持 LF"是既有规矩，内容零改动）。
- Task 7: **必须转交 Task 9 的一处（当前是 Minor，部署形态会变 Critical）**：no-echo 的路径判定比的是 `Request.url.path`（= `scope["path"]`），而 Starlette 1.0 路由匹配用 `get_route_path(scope)`（剥掉 `root_path`）。若哪天以 `--root-path=/gw` 部署，改密那腿的 `==` 分支会失配并**退回 FastAPI 默认回显处理器**——复评用隔离微应用实测复现（`root_path='/gw'` 下当前口令照旧回显）。现网拓扑不设 root_path（`backend/Dockerfile:24` 直映射 8001），所以今天不漏；但这是"作用域静默变宽"的那一类，一行修：拿路由真正用的那个值判（或先剥 `scope["root_path"]`）。
- Task 7: minor (deferred, 全给 Task 10 分诊): 422 的结构体文案「请求参数不合法」是 §9.1 表里没有的第三个值，且没有用例钉住这句中文（会静默漂成英文）；no-echo 路径集合没有自证钉（不像 `WHITELIST` 由依赖图推出 ⇒ 未来新增含口令端点会静默继承回显默认）；`_last_successful_login` 与 `knowledge_os.py:692-701` 逐字重复；`LoginRequest.password` 仍有 `max_length=128` 而改密腿的 `current_password` 无上限（只多花一次普通 verify，非新放大面）；`PASSWORD/FAILED` 的 detail 带自由文本（与仓内 `INGEST`/`DEMO_INIT` 同形，§9.1 那句自由文本禁令原文只管 `AUTH_LOGIN`）。
- Ruling (Task 8, 修复轮更正): 429（pre-hash 节流命中）与 503（Argon2 容量溢出）都在**身份查找之前**判定（§7.1 步骤 0 同时含并发闸门与节流；本条初稿写的『凭据结论之前』当时并不成立——503 是从 `credentials.verify_password` 里抛的，排在身份/凭据/锁定查找之后，于是饱和时锁着的账号答 401、其余各态答 503，§7.4 那张不可区分脸当场长成存在性指纹）。修复后步骤 0 先做 `credentials.capacity_available()` 非阻塞探针（只探不预约），运算处 `argon2_slot()` 的原地抛错保留为兜底；钉子是 `test_a_locked_account_shares_the_capacity_face_instead_of_leaking_a_401`（槽耗尽时锁定脸与未知账号脸逐字节同为 503）。桶键读的是客户端自己交上来的 (username, client_ip)，不查任何表；因此两格可用性事实都不构成账号存在性枚举面——展示面是中文文案（429「登录尝试过于频繁，请稍后再试」/ 503「服务繁忙，请稍后重试」，前者按 §9.1 的字面冻结值纠正：代码那枚常量与此前钉错串的三枚断言一起改，规格是权威），审计面是 token（login_throttled / password_capacity），且 /api/auth/password/change 与登录共用同一条翻译腿与同一格桶。

## Task 8 — 两层节流与容量护栏

- Task 8 review round 1 — 规格部分 ✅ / Needs fixes（3 Important）。评审核实的正面：两层两键确实没合（`(casefold(username), client_ip)` 内存桶 vs SQLite 仅按 `username`），SECA-15/16a/16b 三条都是直接断言且各杀一发变异，`is_locked` 两处 brief 缺陷按"坏值即锁定"改对，本地 `_locked` 确实删净，Task 6 的容量 pin 是**翻转**不是删除，conftest/sec_a_fixtures 安全层实质未削弱（`fresh_db` 先清桶再换 env，没开窗缝）。
- 评审核实的 `+3 subtests` 归因是诚实的：`test_feishu_identity_contract.py:1112-1122` 对 `app/**.py` 每文件 × 3 needle 各开一枚 subTest，新增模块必然 +3 ⇒ 是收紧不是放松。
- Task 8: minor (deferred): `configured_throttle()` 已成死代码（单例现在急建）；`auth.py:16` 按值绑 `pre_hash_throttle` ⇒ 未来打 `login_throttle.pre_hash_throttle` 的测试会静默空转；容量那枚用例给没有身份的 `gate` 造 legacy 行是装饰性 setup 且与另一例重复；`LockedHttpFaceTests` 真烧掉生产单例 10 次/60s 桶里的 8 次，环境里若调低 `LOGIN_THROTTLE_MAX_ATTEMPTS` 会以错误的理由红；`_sweep_stale()` 保留（它防护栏自己变成内存面，丢弃谓词与逐桶清理等价）但无专用用例；`allow(now=)` 与真实 monotonic 的 `_last_sweep` 混用是下一位读者的坑。
- Task 8 fix round（3 Important + 6 minor，全部落地）— 全套件 **1230 passed / 36 warnings / 1114 subtests，两 cwd 逐位相等**（进入 1221/36/1114 ⇒ +9 测试：`test_authentication_leg_contract.py` +6、`test_credentials_contract.py` +3，subtests 一格未动）；四文件门 140 逐位同数、V2.3+egress 427 逐位同数；焦点两文件 143 passed / 19 subtests。证伪台由四则扩到**八则**（新增：步骤 0 探针删除、`hash_password` 出闸、429 字面漂移、重哈希那句 `except Exception` 收窄），每则各红 2–7 枚具体用例、还原后四枚文件 sha1 全 MATCH，复跑焦点 137 passed / 42 subtests。上面那条 minor 的六格（死函数、按值绑定、装饰性夹具、宽桶、`_sweep_stale` 无测、注入时钟混用）逐格收口，报告见 `task-8-fix-report.md`。
- Ruling (Task 8 fix, F3-b): 渐进重哈希那一跳的容量失败**不**把成功登录翻成 503——判定已给出、200 已定了，此刻"没槽"是可用性事实而非凭据结论，拿它挡人等于把闸门升级成第二道认证门（还给攻击者一条"占满槽 ⇒ 已知口令的账号登不进去"的通路）。形状与写盘失败同一条：跳过升级、legacy 行留着、记 `AUTH_REHASH_DEGRADED`（Task 5 裁定的同一条路，本轮补上此前缺的钉子 `test_capacity_loss_at_the_rehash_hop_degrades_instead_of_refusing_the_login`）。
- 待办（Task 9/10 认领）：`.env.example` 的 §10 七枚键**已落五枚**（`ARGON2_MAX_CONCURRENT_OPS=2` / `LOGIN_THROTTLE_WINDOW_SECONDS=60` / `LOGIN_THROTTLE_MAX_ATTEMPTS=10` / `ACCOUNT_MAX_FAILED_ATTEMPTS=5` / `ACCOUNT_LOCK_SECONDS=900`，逐枚对照类默认值），仍缺 `SECURITY_ENTERPRISE_MODE` / `CORS_ALLOW_ORIGINS`（§8.5 口径，与 Task 9 的 secret 卫生同批）；这五枚"默认值与可用性旋钮 vs 强度参数的分界"目前仍无专用用例钉（评审建议的 `config.py` 注释已落）。

## Task 8 — 收口（修复轮复评）

- Task 8: fix round 1 — 复评对"槽嵌套/死锁"这条给了 **proven safe** 的判定并附实测：登录腿 `_verify_argon2` 的成功 return 落在 `with argon2_slot()` 之外、异常经 `finally` 释放，之后才轮到 `apply_rehash → hash_password`；全仓 `argon2_slot` 只出现在 `credentials.py:75` 与 `:138` 两处，故没有任何请求路径在进 `hash_password` 时仍持槽；且两次 acquire 都是 `blocking=False`，最坏是抛 `PasswordCapacityError` 而非挂起。复评在 `/tmp` 用真 `app.credentials` 配 1 格槽跑了一遍：verify→hash 串行、峰值并发硬运算 = 1、故意嵌套时 0.00s 抛错无线程存活。
- Task 8: fix round 1 — F1/F2/F3 与全部折叠进来的 minor 全 ADDRESSED：step-0 探针 + 保留运算处兜底（两半各自有钉，锁 vs 未知在耗尽时逐字节等值 {(503, 服务繁忙文案)}）；429 文案回到 §9.1 冻结字面值且**四枚**断言同步（评审原数三枚，实现方纠正为四枚，复评核实成立）；`hash_password` 进槽后改密/重置两腿才真的会抛容量错并统一翻成 503，而重哈希那一跳按裁定**不**把已成形的登录变成 503（吞掉容量错→保持 legacy 行→`AUTH_REHASH_DEGRADED`，P8 缩窄 except 即红）。
- Ruling: 探针与兜底之间的那道微秒窗口不可压缩（通过探针后再输给别人的请求仍在身份查找之后抛错）。复评认定这是"按 mandates 修"的固有代价，不额外开洞：真正关掉它要给永不运算的腿预留槽，那会重新打开 `credentials.py:99-101` 命名的饿死问题。记为已知限制，交 Task 10 写进 §17。
- Task 8: minor (deferred): `_last_sweep` 用真实 monotonic 播种而 `allow(now=)` 接受注入时钟 ⇒ 注入小于 epoch 的 `now` 会让扫描失效（注释记录了、没拆雷；`_last_sweep=None` 惰性播种才是根治）；写腿的 503 审计仍走 LOGIN 动作族，`path`/`target` 区分留给 Task 10；`.env.example` 那一处 FEISHU 注释行被顺带改写而报告称"其余一行未动"（该文件无变更前快照，归因不可得，内容无害）；`progress.md:183` 说三枚断言、实为四枚。
- Task 8: complete — 全套件 **1230 passed / 36 warnings / 1114 subtests，两 cwd 逐位相等**（进基线 1221）；门 A 140、门 B 427 未动；安全地基 `tests/conftest.py` 与本轮快照**零差异**。
- Ruling (Task 9): redact_secrets 语义一字不动，其 28 处调用点中 4 处**落盘面**（audit 写+读、agent_trace 存+取）按 §9.3 切到 redact_for_persistence，其余 24 处（响应面 return 等）零改动；agent_trace.get_trace 是 §9.3 点名的持久化读面，切换后 return redact_secrets 由 8→7。三启动守卫同生同死（SECA-18 直调），Task7 root_path P0 用 get_route_path 修，Task8 容量事件按 action 区分（不新增 detail token）。全套件两 cwd 各 1260 passed / 36 warnings / 1117 subtests，零失败。

## Task 9 — 修复轮（控制器核验）

- 控制器自跑两 cwd 全套件逐位相等：**1273 passed / 36 warnings / 1117 subtests**（进基线 1260/36/1117 ⇒ +13 测试，subtests 一格未动）。后端 `cd backend && python -m pytest -q` 与仓库根 `python -m pytest backend/tests -q` 各一次，均 exit 0。
- 控制器独立复核修复报告的两条计量断言：AST 量得 `app/security.py` 之外 `redact_secrets(...)` 调用点 **17**、其中 `return redact_secrets(...)` **7**（与报告一致）；扫描面 `git ls-files -z --cached --others --exclude-standard` = **254** 文件，其中 `*.md` 90、剔除 `.superpowers/**` 后交付 markdown **51**（与报告一致）。
- Spec 回写 §20.4：上一行 Ruling (Task 9) 里沿用的"28 处调用点"是文本 grep 口径（含 `def` 自身与 `security.py` 内部自引用），AST 口径为 17/7。已改 §2 事实表、§2 复核更正段、§9.3 那条"一字不动"约束的括注。**约束本身不变**（`redact_secrets` 语义与全部调用点零改动，由字节级 pin + AST 计数 pin 双判），改的是可复现的测量方法——这是计量更正，不是放松规格。上一条 ledger 行的"28"以 §20.4 为准。
- Ruling (Task 9 fix, frontend): `action="PASSWORD"` 是 SEC-A 新增的展示层 token，`OperationsView.tsx:164` 的 `FilterChips` 走 `ACTION_LABELS[t] ?? t`，两张 `ACTION_LABELS` 表原本覆盖了 logTypes 里其余每一枚动作。实现方只加了 logTypes 一格、故意不动 label 表 ⇒ 中文界面会直接显示英文 `PASSWORD`（半截本地化）。控制器裁定：本地化补齐而不是回退，`PASSWORD: "口令变更"` 同词进 `OperationsView.tsx` 与 `GovernanceView.tsx` 两张表（两视图读同一条审计流）。SEC-A 原口径"不改前端"因此记为 **3 行增量偏差**（1 格 filter + 2 格 label），理由是这 3 行是 SEC-A 自己引入的展示面所要求的，不是顺手重构。

## Task 9 — 复评（round 1）与修复轮 2

- Task 9: review round 1 复评 — F1–F5 与全部折叠 minor **全 ADDRESSED**，独立复核：254 文件面 / 16 文件 31 处与豁免表**相等**、零死行、AST 17/7 再量一致、`main.py:87` 确为全仓唯一生产调用点。裁定三条"对规格字面的偏离"全部 sound（扫描面取 `-c -o --exclude-standard` 的超集、§20.4 的计量口径更正、前端 3 行）。F-E 那枚"改空函数体不红"的洞判为**不致命**（存在性钉抓的是它自己名字承诺的那发，效果由 `:676-686` 真登录票过 `save_trace`/`get_trace` 与 `:695-712` 审计读面逐面兜住）。
- 复评新增一发 **Important（NB-1）**：env 面的范围收窄把"配置文件档的无引号赋值"整档弄瞎（`password: <真值>` 这种 YAML/INI 形状在评审头一处、修复后零处），而这道收窄**换不来任何东西**（实测新增命中 0）⇒ 门注释还写着"配置"已覆盖。这正是 SECA-19 禁的那类"未命名的残余"。
- Task 9: fix round 2（控制器亲自实现，非派发；1 个函数 + 1 枚用例 + 注释/规格回写）— `_faces_for` 增设配置档（`.yml/.yaml/.ini/.conf/.toml/.cfg/.properties` + `dockerfile*/containerfile*/makefile/procfile`）并配 **大小写不敏感** 的 `_ENV_FACE_CI`（INI/TOML 键名通常小写）；新增 `test_unquoted_config_file_assignments_are_on_the_face` 三形状植入 tmp_path。实测拓宽**零成本**：面仍 254 文件 / 16 文件 31 处 / offenders NONE / 焦点 44 passed（原 43）。同一段注释改成诚实版（NB-2：markdown 档只关"现网密钥形状被贴进文档"，不关散文里的赋值形态；NB-4：canary 按 `路径:行号` 引用，不许抄进 `docs/**`）。
- Ruling: NB-5 两则**不改**。①`(文件→处数)` 看不见"原地替换成另一枚真凭据"是 F3 要求的形状自带的性质，根治是 §18 的带历史第三方扫描器；②`subprocess(check=True)` 在没有 git 的机器上把门跑成 ERROR 而不是 skip——**这是要的形状**：安全门宁可响亮地失败，`skip` 就是把"环境缺件"洗成"通过"。
- Spec 回写（NB-3）：§2 那行的位置清单换成实测 7 处直返面（`agent.py:330/1048`、`conversation_agent.py:533/602`、`conversation_store.py:175`、`main.py:738/847`），`agent_trace.py:91` 标注为"Task 9 已切换走，不再是 `redact_secrets` 落点"；`:126` 的"28 处"改口；§20.4 把"字节级"更正为"行为探针 + AST 等式两枚不同性质的钉"。另把 `PASSWORD→口令变更` 登记进 `docs/UI_COPY_GLOSSARY.md`（复评指出：中文标签要有权威去处，否则下一轮会被"顺手改成密码变更/改密"）。

## Task 9 — complete

- Task 9: fix round 2（控制器自实现，评审对象 `task9-fix2-review-package.md`）— NB-1 的**小写一半**与
  分支顺序补齐（配置档吃大小写不敏感 env、`scripts/` 吃大小写敏感并有用例说明为何不对称、
  `scripts/ci.yml` 不再比 `deploy/ci.yml` 少一面、`_CONFIG_FACES ⊃ _CODE_FACES` 钉住）；`makefile`/`procfile`
  按"主动招噪 + 仓内不存在"剔出配置档；NB-2/3/4 与 round-2 Minor 3/4 全部落地（门注释诚实版 + 按测试名
  引用 + `backend/.env` 那格同时写进门注释与 spec §18）。焦点文件 43→44→**45 passed**。
- Task 9: complete — 全套件 **1275 passed / 36 warnings / 1117 subtests，两 cwd 逐位相等**（进入 1260 ⇒
  +15 测试全部来自本轮新增用例与复评补齐的钉子，subtests 一格未动）。secret 门复量：面 **254 文件 /
  16 命中文件 / 31 处**，`_gate_offenders` 空，与拓宽前同一批 31 处（零静默吸收、零新豁免行）。
  legacy digest 三处扫描预量：`app/`、`config/`、`tests/` 全 0 命中（Task 10 closure 门的前半已实证）。
- 复评 round 1/round 2 留下的两条 OOO 已转 Task 10：`main.py:460-461` 管理员重置腿对不存在账号的 404
  不写审计（与同路由其余拒绝不对称）、canary 字面量不得抄进 `docs/**`。

## Task 10a / 10c 进度与一发控制器自伤

- Task 10a（镜像 + 基准 + smoke + closure，控制器派发）— **SECA-19 GREEN（容器判据）**：serial P95 **55.3ms** / concurrent(2 workers×32，闸门满配) P95 **66.7ms** / peak RSS Δ **39280 KiB=38.4MiB**，预算 1500/3000/262144 KiB；宿主数只记为对照（win32 无 `resource`，RSS 不可测）。**SECA-04 GREEN**：真实库经"导入 → 5 个 demo 账号各一次真登录 → 渐进重哈希"从 `legacy-sha256×5` 收敛到 `argon2id×5`、带外读数 `legacy_count=0`，无人工改库；`must_change` 在重哈希后**仍然为 1**（4 枚），改密那一腿走完 ⇒ 数据面 403→200 且**旧 token 401**（cv 同事务 bump，"一次强制重登录"是观测到的事实而非叙述）；工件与其快照副本（两枚 sha1 同为 `19cc628acbae`）删除后重启复确认 `artifact_present=False imported=0`。四场景 smoke 逐条留证，其中"错口令 vs 未知账号"是**字节相同**的 37 字节 401（同 sha1），锁定脸无"锁定"字样、`AUTH_LOGIN_LOCKED` 只在审计面。
- **F-1 实质缺陷（已裁定并回写规格 §20.5）**：`credentials_migration.import_from_artifact()` 在生产代码里**零调用者**，lifespan 不导入、CLI 无导入动作 ⇒ 规格 §8.2 写的"升级路径"在实现里不可达。根因是规格自己的洞：§8.5 明写"生产代码不再自动导入 legacy"（为守 M19/SECA-04b），而 §11 的 CLI 清单从来没有导入动作——"不许自动"与"也没有手动"同时成立。裁定：**导入改为运维显式 `credentials migrate`，启动仍绝不自动**；四条规则（企业形态先拒后写、`only_missing=True` 幂等、不碰明文口令、rc 语义分 refusal/存储事故）写进 §11，§15.1 第 6 步要求升级那一次留 5→0 的两次读数。**这一条是规格首次动"交付面"，须用户确认。**
- Task 10c 实现回报 DONE_WITH_CONCERNS：`cli.py` + `test_credentials_contract.py` 两文件、71→80 passed、LF 未翻；控制器独立核验其余 10 枚 `app/*.py` 与 10c 基线**逐字节相同**（"只改 cli.py"为事实）。待复评的三格：D3 畸形工件 rc、"启动不消费工件"那枚负向钉是否真能红、`migrate` 不写审计是否与兄弟 CLI 动作一致。
- **控制器自伤记录（务必学走）**：我为 Task 10d 建基线时把复合命令写错，在**仓库根**留下了 `snap-task10d-pre-app/`（`backend/app` 的一份副本，与现树仅差 `cli.py`）。它是未跟踪且不被忽略 ⇒ 直接落进 secret 门的扫描面 ⇒ 门当场报 4 枚未豁免命中（auth.py×2 / cli.py / config.py / security_startup.py）。**扫描门把我的一次目录手滑变成了红**，这就是"门该红的时候真红"的证据，但也说明：任何临时副本只能进 `.superpowers/`（已排除在面外），**绝不在仓根建 scratch 目录**；比对基线要用 `git ls-files` 数一下表面有没有变大（254→311 就是这次的信号）。删除后复量 255 文件 / 16 命中 / 31 处、offenders 空。

## Task 10c — 评审与裁定

- Task 10c review — 规格 ✅ **Approved**（0 Critical / 2 Important / 7 Minor）。复评自己重做了 base→head 差异并确认与评审包同 hunk 集，另逐字节核过"只改两文件"。S1 那枚"启动不消费工件"的负向钉判为**非空转**（工件写在 tmp 的默认相对路径 + `warmup_*.called` 作正对照；注入 `import_from_artifact()` 到 lifespan 两枚断言都会红，漏了 schema 那步则以 `no such table` 在 `TestClient.__enter__` 里报错同样红）。S2 企业拒绝确实排在 DDL/读/写之前（`cli.py:140-142` 先于 `:143` 建表、`:145` 读工件），且有"连库文件都不该创建"的独立钉。
- 裁定（已回写规格）：**§11 退出码表**（0 含"工件不存在"合法稳态 / 1 = `CredentialStoreError` **与 `sqlite3.Error`** 同归基础设施事故 / 2 = 运维可修的拒绝，三段子含义靠 stderr 分辨 / 3 = 开发者缺陷；**不**为畸形工件另开第 4 枚码）；**§11 证据面**（`migrate` 不落审计，理由是 §8.6「CLI 无独立 actor」+ §9.1 `detail` 取值集封闭，造 token 属于改契约）；**§17 新增 L7**（工件相对 cwd、库相对 env，二者只在相对路径形态下同源；失败方向是"静默不导入但 rc=0"，`reason` 打印解析后的绝对路径 ⇒ 人可诊、脚本不可诊；**因此本轮不加 `--path`**，登记 SEC-B）。
- 复评顺带纠出一处**长期存在的注释失真**：`credentials_migration.py:21-25` 声称"compose 就是这么挂库的"，实际 `docker-compose.yml:29-30` 只挂目录、`backend/.env:33` 的 `CONVERSATION_DB_PATH` 是**相对值** ⇒ 已在 L7 里写清，并让修复轮回改注释（comment-only）。
- Task 10c fix round 1 派发：Important-1（`cli.py:143` 建表那一步零钉：删掉它 80 枚全绿，而 `migrate` 的存在理由恰是"从未建过表的 virgin 库"）、Important-2（DB 锁/卷满以裸栈出去，Python 偶然退 1）、Minor-1 stdout 四行等值钉、Minor-2 退出码常量表、Minor-5 显式钉企业开关、Minor-7 注释纠误。明写**不做**的：Minor-3/4 已被 §11 表吸收、Minor-6 的 44s 焦点耗时**不得**用 skip 换掉。

## Task 10c — 修复轮（控制器核验，未另派复评，理由在下面）

- Task 10c: fix round 1 — 六格全落地且每格自带证伪：Important-1 virgin 库建表钉（删 `cli.py` 那一步 ⇒ 2 红 / 81 绿，**恰好证明旧 80 枚里没有一枚在干这活**）、Important-2 `except (CredentialStoreError, sqlite3.Error)` ⇒ rc 1 一行 stderr 无裸栈（摘掉 `sqlite3.Error` ⇒ 2 红）、Minor-1 stdout 四行等值面（多加" helpful 第五行" ⇒ 3 红）、Minor-2 退出码常量表（控制器自量 `grep "return [0-9]"` = **0 命中**，四枚常量值 0/1/2/3 就位）、Minor-5 类级 `security_enterprise_mode=False` 钉（拨成 true 再抽掉钉 ⇒ 10 红 / 2 绿，比评审估的 5 枚更多）、Minor-7 两处注释纠误（compose 只挂目录、`.env:33` 是相对值，绝对路径分叉归 §17 L7）。
- 控制器核验：`test_credentials_contract.py + test_secret_hygiene_contract.py + test_security_a_closure.py` = **131 passed / 35 subtests**（83+45+3），`EXEMPTIONS` 未增行。
- **本轮未另派独立复评**（偏离 SDD 逐轮复评的地方，如实记）：基础评审已是 Approved，本轮只做"加钉 + 收错误路径 + 命名常量"，每一格都有自证伪与 sha1 逐字节还原，且差异面窄（3 个文件）。独立复评由**最终全分支评审**覆盖同一段差异。若终审在这段发现新问题，按"控制器自审不当独立评审用"处理——即重开一轮，不既往不咎。
- 10e 要引的 SECA-13 结构证据坐标（免得它去 grep）：`tests/test_authentication_leg_contract.py:404 test_all_four_states_consume_exactly_one_argon2_run_each`（`:414` 四态共 4 次、同档位、同一单例）与 `:421 test_a_wrong_password_on_a_legacy_row_consumes_one_argon2_run_too`（legacy 行的错口令也付一次同档哑运算 ⇒ 收敛窗口不是免费枚举面）。

## Task 10d — deferred minor 全量分诊（完成，但撞顶而止于报告尾部）

- 分诊表 **49 格 = 台账 47 + 复评移交 2**，零静默消失、**未处理 0**：**闭合 11 / 已知限制 11 / 转 §18 4 / 已顺带闭合或描述失真 21 / 无动作 2**。台账 11 处 `minor (deferred)` 的行号逐行有格子；"已顺带闭合"那 21 格全部给了 `file:line` 与被哪一轮收掉的归因，这就是简报里"先量当前树再下结论"那条规矩的回报（真实比例 21/49 ≈ 四成三是旧账）。
- 本轮改动 6 枚文件（4 枚 `app/`：`credentials.py` 死代码 + `needs_rehash` 异常分类、`user_store.py` 注释、`login_throttle.py` **行为**改动 `_last_sweep` 惰性播种 + `reset()`、`credentials_migration.py` 裁定注释；2 枚测试面）+ 8 枚新用例 + 1 枚 planted 形状。焦点九文件合集 **785/21/553 → 793/21/569**，+8 passed 与 +16 subtests 逐格对上，21 warnings 一字未动，既有测试一枚未少。四发（两 cwd × 两遍）同数。
- 三处"加宽门"各自演了反证并 sha1 逐字还原：写手扫描的两段链（退回旧写法 ⇒ `SUBFAILED(binding='from app import credentials_migration')`）、`from app import config` 的 import 面（退回 ⇒ 3 failed）、`_last_sweep` 惰性播种（退回 ⇒ 收桶那枚红）。
- **过程缺陷（它自己报的，不遮蔽）**：`test_authentication_leg_contract.py` 的改前 sha1 没留档（快照只记了 11 枚文件，那枚是读完台账才决定改的）⇒ 该文件 before/after 只能靠快照目录 + 报告文字复原，归因弱一档。规矩回写进本台账：**凡进入 `tests/` 就先记 sha1，不等结论成形。**
- **它替我抓出一发真违规（比 `-shm` 那格大得多）**：`backend/data/audit.jsonl` 一直在被测试**写**。`app/audit.py:11` 的 `AUDIT_PATH = Path("data/audit.jsonl")` 是相对常量，compose 又整目录挂载 ⇒ 一枚焦点文件实测 +337 字节，全量到 **2 MB** 量级。这本账是 §14 的证据面（`credentials migration-status` 的"最后成功登录"就读它的尾巴），掺测试事件就是污染验收证据。10d 把它判成"不在门禁面里 ⇒ 转 §18"，控制器不认这个结论：**它违反的是本项目的 standing rule，不是扫描门的键**。
- **控制器直接修了（不再派一轮）**：`tests/conftest.py` 新增会话级 autouse `isolated_audit_sink`，把 `app.audit.AUDIT_PATH` 改道进 `tmp_path_factory` 的会话目录（接缝打在模块属性上，与 `sec_a_fixtures.AuditToTempFileMixin` 同一手法、可叠加）；`test_credentials_contract.py` 新增 `AuditSinkIsolationTests` 两枚：①改道目标不得落在仓库 `data/` 下，②写入落汇且 **marker 不出现在运维那本账里**。判据刻意选"我的事件进了哪"而不是"仓库文件字节没动"——dev 后端与 smoke 也在写那本账，拿尺寸当判据会假红（`conftest.real_db_tables` 的 docstring 早为同一件事定过调）。
- 实测：`test_credentials_contract + test_authentication_leg` 159 passed / 58 subtests 且**真 `audit.jsonl` delta = 0 字节**（改前同一对文件会 +337）；十文件合集 **798 passed / 21 warnings / 569 subtests**（= 10d 的 793 + closure 那枚文件的 3 + 本修的 2，逐项对上）。既有 2 MB 残留**不删**：里面同时有 smoke 的真实事件，截断会把 §14 的证据一起削掉——由 10e 在文档里如实标注"该账本含 SEC-A 之前与测试历史的混合条目，`migration-status` 的最后登录读数只作运维参考"。
- 10d 的独立复评**并入最终全分支评审**（与 10c 修复轮同一处置、同一理由：改动面窄、每格自带反证、终审看同一段差异）。

## Task 10b — 变异台 19 发

- 结果 **19/19 KILLED，退出码 0**；harness 在 `finally` 里逐字还原并比 sha1，任何不匹配当场中止整轮。103 文件清单复验：**102 枚与基线相同**，唯一有意差异是新增那枚用例所在的 `test_credentials_contract.py`。报告 `task-10b-report.md`，原始跑记录 `task-10b-mutations-run.txt`，harness 支持 `--check` 复验 19 个锚点而不动树。
- 漂移实况：**12 发需要重新锚定**（真片段消失 M3/M13/M14/M17；needle 撞多次 M4/M5/M7/M9/M19；M16 还缺 `import os` 否则 import 期 `NameError`＝红得没有判据；M1 只是缩进），**1 发原本存活**：M16（`m/t/p` 改从 env 读）在既有常量钉下**居然是绿的**——因为那条 env 通道的默认值就等于常量。补的用例是 `Argon2ProfileTests::test_the_profile_does_not_budge_when_the_environment_is_poisoned`（把环境毒成另一档再断言档位不动）；这是 SEC-A-008 那枚"强度参数不可运维调"的第一次被真正证伪过。
- 三格判据级别的处置，都记在报告里而不是糊过去：①骨架里的 `-x` 被拿掉（带着它 M6 会先死在收桶时钟那枚用例上，永远到不了 §13 指定的 SECA-16a 钉子——"KILLED"于是变成"有人红了"而不是"该红的红了"）；②**M7 计划原文打的不是 M7**：`WHERE username = ?` 加 `locked_until IS NULL` 攻击的是 SECA-14 的统一失败脸，且那个 needle 在 `user_store.py` 里命中 8 次；改锚到计数写入那一段（每源地址一格计数器⇒账号锁永不成立），SECA 行与性质不变；③**M10 计划原文（重命名 `_bump_and_clear`）虽红但红在名字上**（补丁目标失效的 `AttributeError`），重述成 §13 真正的攻击＝两笔事务提交出"新哈希+旧 cv"那个禁止中间态；**残留如实记**：今天没有用例把那个状态当 DB 事实观察，因为实现里哈希与 bump 是同一条 SQL，状态不可表示——M10 证明的是"若哪天把它拆开，门仍会红"。
- 计划自审段那句"`TARGET-NOT-FOUND` 是故意保留的机制"这次兑现了：12/19 需要按当时代码原文修片段，而"不改判据"这条线全靠 §13 行号 + 测试 docstring 双向核对才守得住。

## Task 10f / 10g — P0 接缝，与它牵出的第二发规格空洞

- Task 10f（V2.3 P0 登录腿的凭据来源）— 接缝落在**harness 侧**（密封文件一字未动、`del` 收集门未动）：`tests/real_llm_failover_kit.py` §5.5 `install_login_credential_seam()` 包 `usage.init_usage_db`，委托既有的 `sec_a_seed.install_demo_credentials(target)`（先种后 init，与 `test_model_router_v23_contract.py:4127` 那处受认可手法同形），仅由 `conftest.py` 新会话 autouse `p0_login_credential_seam` 上膛，唯一开关就是 `kit.acceptance_enabled()`。closure 文件 3→11。没有任何期望集被放宽：`kit.validate_evidence` 与门③都不读 `tables_in_temp_db`，全仓没有断言临时库表集合的地方——**唯一变化是描述性的**（复跑证据里会多出一张 `user_credentials` 表），`files_sha1` 不含 kit ⇒ V2.3 既有证据不作废。真机两发 Ollama 调用仍 `PENDING_EXTERNAL`（无 key、ornith 载不动），运维复跑命令已写进报告。
- **10f 报回一发它没敢裁的事实**：P0 那条路（`init_usage_db` 造的全新库）上登录抛 `sqlite3.OperationalError: no such table: user_credentials` ⇒ **500 而不是 401**。控制器用 `TestClient` 现场复现（冷启动 + 一个错口令 ⇒ 500），两形态同病。
- 根因是**一句从没被写下的编排**：`user_store.py:105-113` 与 `credentials_migration.py:157-160` 都把建表责任交给「启动编排 / CLI」，可 lifespan 只有守卫 + 两枚 warmup，CLI 那三条要运维敲过才算。规格 §8.5 企业列白纸黑字写着「`user_credentials` 无行 ⇒ 任何登录统一失败（fail-closed，**非 500**）」——部署面上是破的，而矩阵 SECA-04b 是绿的：**它的用例先手工建表再断言，于是"表不在场"与"表在场零行"这两格事实只钉了后一格。**
- 裁定（已回写 §8.5 增补段 + §20.6）：lifespan 在守卫之后、warmup 之前调 `ensure_user_credentials_schema()`（`IF NOT EXISTS` 幂等），DDL 失败沿用守卫的 fail-fast（uvicorn 退出）而不是让每个请求各自撞 500；**读路径仍然不建表**（"env 被清掉就向默认落点提交 DDL"那条已冻结的理由不变）。SECA-04b 的判据补第二格：不预建表的冷启动登录必须是 401 统一脸。
- 本规格两次由收口阶段反向补上自己没写完的编排义务（§20.5 导入入口、§20.6 建表编排），**同一条病因**：规格里每一句「由 X 负责」都必须能在代码里指出那一行。10e 写验收文档时把这条写进"已知限制/流程教训"，最终全分支评审按这条复查余下的「由…负责」句。
- Task 10g 派发：`main.py` 那一行 + 五组用例（冷启动 401 非 500、企业形态零行 401、boot 建表而读路径仍不建表、幂等、DDL 失败 fail-fast），并要求它**如实改写** 10f 那枚"harness entry 不产生凭据 schema"的说法（拆成"读与 usage 入口不建表／lifespan 建表"），动了测试的**目标**必须留在报告里给复评看。

## Task 10e — 终态证据重跑与验收文档（COMPLETE）

- 交付文档 `docs/SECURITY_A_ACCEPTANCE_2026-09-26.md`（441 行、LF/CR=0、15 段）。矩阵 **27 行 = 26 GREEN / 1 PENDING_EXTERNAL / 0 BLOCKED**，总判定 **CONDITIONAL PASS**。唯一非 GREEN 是 SECA-24（第 8 处登录调用点住在默认不收集的封版 P0 件里；本机无 provider key、`ornith` 载不动 ⇒ 按词表记 `PENDING_EXTERNAL`，运维复跑命令进文档 §10）。
- **终态镜像 `3f14b3de77a4`**：SECA-19 容器数 serial P95 **25.3ms** / 并发满配 P95 **40.9ms** / RSS Δ **38.4MiB**（预算 1500/3000/256MiB）= `GREEN`；17:42 首测的 55.3/66.7 同栏并存并说明为什么要两套房。**全新安装冷启动在容器里实测 401 非 500、两态响应体逐字相同、`user_credentials` 由 lifespan 自动在场**（`task-10e-fresh-boot.txt`）——这是 10g 那一发在部署形态里的直接闭环。
- SECA-04 仍 `GREEN`（带外 `legacy_count=0`；终态镜像复确认 `argon2id=5 / 4 枚 must_change=1`；三处扫描 0 命中）。**如实写明**：5→0 的收敛是 10a 在产品路径上走过的一次性事件，未在终态镜像重跑（文档 §6 第 6 步）。19 发变异台在终态树上复验锚点 19/19 唯一。
- 两 cwd 全套件在文档定稿后重跑，逐位相同且 0 failed/0 error/0 skipped：**1316 passed / 37 warnings / 1133 subtests**。
- **Step 8 停在清单**：`task-10e-report.md` §D 给出 `git status --short` 40 条原文 + 拟提交路径 + 排除项（`backend/data/**`、`backend/.env`、`output/**`、`.superpowers/**`），并点名一个岔口：V2.3 当年对 `.superpowers/` 用 `add -f` 精选了 41 枚过程件——SEC-A 是否照做交用户拍。**本轮零 git 写命令。**
- 它交回三条疑虑（都不许糊）：① 我修的 `[credential-guard]` 收尾行五发都没出现 ⇒ 分不清"零记录"与"我的别名没生效"，已作为 **S1** 交给终审；② warnings 36→37 缺 10b–10g 的前后对照件 ⇒ **S2**；③ 文档自己被 SECA-20 门红过两次（`task-10X-<长名>` 撞上材料形状的 `sk-`），它**改自己的命名而不是加豁免行**（门仍 16 文件 / 31 处），这条性质已进文档 §11。另：旧镜像被本次构建回收，本地已无回滚点。

## 最终全分支评审（SEC-A）

- 判定：**代码 ship-able（零 Critical，不需要改代码即可发布）；验收文档不得按现状发布**（六句必改）。树哈希与文档 §14 逐枚相符、19/19 锚点唯一、EXEMPTIONS 16/31、交付面 256 文件、验收文档自身 0 命中。§4 十条不变量逐条给出结构性载体（例如 SEC-A-001 是"签名里没有 algorithm 参数"而不是约定；SEC-A-005 是 AST 双向钉）。
- **终审抓到两发我自己的错**：① 我修的秘密别名是**死代码**（凭据面从没把 `records` 重绑到模块级 list ⇒ 那行永远打不出来），结构 + 行为双重证明（记录确实存在：`test_credentials_contract.py:1892-1913` 通过）；② 我 10f/10g 之后留下的 37 枚警告有具体归属（closure 里那枚新用例绕过了本仓自己的 `LongJwtSecretMixin`），"待查"不成立。
- **最重要的一发是措辞背后的安全事实**：文档与规格 §17 L6 写"5 个旧口令永久失效"**是假的**。`must_change` 只挡数据面 403，**不挡** `POST /api/auth/password/change`（§8.4 白名单刻意如此，否则未收敛用户无法自救）⇒ 握着 git 历史里那批明文（`admin123` 等）的人仍可登录并把管理员口令改掉，顺带锁死受害者。SEC-A 做不到替用户改口令，所以真实退役范围只有"泄露摘要不再是存储形态"+ 运维必须**在暴露部署前轮换那四枚弱出身账号**。已作为 10h 组三第 1 条 + 组四 S1 强制同口径回写。
- 三处"过度声称"级修正进文档/规格：CI 那半（`backend-contracts` 根本没有依赖安装步、跑的是 `unittest discover` ⇒ "本地与 CI 同一道门"不成立，降级为 SEC-B 前置）、§6 第 6 步"全程走产品路径"（导入腿当年是直接调函数跑的，`credentials migrate` 从未在部署形态执行）、§9.3 落盘面枚举外的两枚既有写手（`knowledge_os.py:86/92`，判为范围边界而非破掉的承诺，AST"恰好 4 处"的等式保证它不会静默漂移）。
- **「由 X 负责」残清单**（终审逐条给载体）：14 句可指到 `file:line`；**两发新孤儿**——§10 的 compose 侧 secret 守卫（`docker-compose.yml` 与 HEAD 逐字节相同，没有任何载体）与 SECA-20 的 CI 执行者；另加半孤儿一枚（§9.3 那两张面）。§20.5（导入入口）与 §20.6（建表编排）之外，这类洞的成因是同一条：**规格里每一句"由 X 负责"都必须能在代码里指到一行**。
- 终审自报"最不敢保证的一处"：**部署面证据链今天完全不可从仓库复现**——产生 smoke/冷启动/基准转录的探针脚本住在 `C:/tmp/seca10e/`（仓库外），旧镜像已被回收，27 行里有 6 行靠这些转录。⇒ 10h 组二 D1 把两个探针复制进 `scripts/`（受版本控制、无明文口令），让这条链在提交后可复现。**这条本身就是要向用户点名的一次教训：证据生产工具必须与证据同仓。**

## Task 10f/10g/10h 与 SEC-A 收口（终态）

- 10f（P0 接缝）/ 10g（lifespan 建表 + 五枚用例 + 顺序契约）/ 10h（终审 6 句文档 + 3 处规格 + C1/C2/D1）三格由 10e（终态镜像重跑 + 验收文档 441→现 15 段 + 提交清单）串起来收尾。控制器独立复核：三枚主门 **155 passed / 44 subtests**，`[credential-guard]` 收尾行现在**真的打印**（C1 的重绑生效；改前五次全套件都是 0 行）。
- **终态基线**：两 cwd 逐位相同 **1316 passed / 36 warnings / 1133 subtests**，0 failed / 0 error / 0 skipped（36 而非 37：C2 把新用例接回 `LongJwtSecretMixin`，未压警告、未改判据）。secret 门 46 passed、交付面 258 文件、豁免表仍 16 文件 / 31 处、**未新增任何一行豁免**。矩阵 27 行 = 26 GREEN / 1 PENDING_EXTERNAL / 0 BLOCKED，总判定 **CONDITIONAL PASS**。
- 部署面证据现在**可从仓库复现**：探针进 `scripts/sec_a_fresh_boot_probe.py`（已在终态镜像 `3f14b3de77a4` + 一次性卷上重跑，输出与转录逐行相同）与 `scripts/sec_a_smoke_http.py`（复制但未重跑——它要打泄露明文口令并会给真库写锁定行）。旧镜像 `1abba3717aa7` 已被回收 ⇒ **本地无回滚点**，这条写进文档 §12.2。
- 规格第八轮回写 **§20.7**：三处"规格式过度声称"（L6 旧口令永久失效 / SECA-20 的 CI 同一道门 / §9.3 漏两张落盘面）全部**把声称缩回实测范围**，判据一字未动。§20.5、§20.6、§20.7 三轮都标注**待用户确认**。
- 提交清单在 `.superpowers/sdd/SECURITY_A_PLAN/task-10e-report.md` §D/§D2：**42 条 = 20 改 + 22 未跟踪**，含排除项与"V2.3 曾对 `.superpowers/` 用 `add -f` 精选 41 枚"这个岔口。**全程零 git 写命令、零 tag、未动 `model-router-v2.3-rc1`。**
- 欠账（不阻塞发布，已登记）：①"有记录 ⇒ 收尾行必打印"的**用例级**钉（§11）；②`docs/SECURITY_A_ACCEPTANCE_*.md` §5 一处既有的表格竖线排版小瑕；③前端改密 UI 入口（L20/SEC-B/C）；④`backend-contracts` 的 pip install + pytest runner（SEC-B 前置）；⑤`knowledge_os.py:86/92` 纳入持久化脱敏（§18）。

## 封版（rev 3 / tag security-a-rc1）

- 用户裁定：§20.5–20.7 回写批准（性质 = conformance correction，须按"原规格→实测反例→修订规范→判据是否变化→回归证据"五段留痕 ⇒ 已补 §20.8 卡 A/B/C）；CI 扫描门 **MUST FIX**；提交 APPROVED（选择性 `add -f` 证据，禁 `git add -A`）；单枚原子提交；tag `security-a-rc1`，**判据改为"SECA-20 那一步在远端真跑绿"**，不等整条 workflow（三枚 job 的红早于 SEC-A）。
- 封版前复测（控制器亲自）：两 cwd 各一遍 `1316 passed / 36 warnings / 1133 subtests` 逐位相同；SEC-A 六门 353/117、回归四门 461/21/452、CI 等价扫描子集 5 passed、变异台锚点 `--check` 19/19 唯一。
- **复测抓到我自己写的测试是坏的**：rev 2 报"两 cwd 相同"，但仓库根那一发实际 `1 failed` —— `AuditSinkIsolationTests` 用相对 `Path("data")/audit.jsonl`（两种 cwd 指向两枚不同文件）且 marker 跨运行不唯一。改成绝对 `BACKEND_DIR/...` + `uuid4()`，复测两 cwd 各 2 passed，随后全套件逐位相同。
- **第一版 CI 接入被远端证伪**：`f6c67b5` 该步 `ModuleNotFoundError: No module named 'httpx'`（收集期 conftest → sec_a_seed → app.llm），因为我写进 `ci.yml` 的安装清单 ≠ 我本地干净 venv 实测那一包集合。补全（`e5ff798`）后远端 **step success**，其后既有 `unittest discover` 仍 failure（L21 记的就是这件事）。新增规矩：**"本地与 CI 等价"必须连安装清单一起等价。**
- 取证/聚合哈希口径教训：文档 §14 那句"34 枚文件聚合 sha1"在五种合理写法下给出五个值，本轮定位为**只串文件字节**（`b57fa3366a09…` 完全复现）⇒ 基线读数必须连命令一起写。
- 提交：`f6c67b5`（96 文件，SEC-A 全量）+ `e5ff798`（CI 依赖修正）+ 本轮 docs/ledger；`backend/app/identity/*` 两枚**未提交**（属飞书桥接的既有未提交工作，不在 SEC-A 范围）；镜像别名 `rag-backend:security-a-rc1 → 3f14b3de77a4`（本地产物别名，不替代 Git tag；旧镜像无回滚点）。

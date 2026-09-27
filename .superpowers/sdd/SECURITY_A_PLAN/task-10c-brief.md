# Task 10c — legacy 导入的生产入口：`credentials migrate`

来源：Task 10a 收口时报回的 F-1（`import_from_artifact()` 生产零调用者）。规格已按裁定回写：
`docs/SECURITY_A_SPECIFICATION.md` §11（四条规则）、§8.2 表格行、§15.1 第 6 步、§20.5（来由与"这条需用户确认"）。
**规格是权威**；本简报只是把它落成一次可评审的实现，措辞冲突以 §11/§20.5 为准。计划原文
`docs/SECURITY_A_PLAN.md` 未追加本节（计划自审段已冻结），因此 §11 就是本任务的唯一需求来源。

## 要做什么

在 `backend/app/cli.py` 的 `credentials` 子命令下新增 **`migrate`** 动作：

1. 读 `credentials_migration.LEGACY_INPUT_PATH`（默认相对路径，行为与该模块既有约定一致），调
   `credentials_migration.import_from_artifact()`（`only_missing=True` 是它的默认，别改成 False）。
2. 打印 `MigrationReport` 的四个字段：`artifact_present / imported / skipped / reason`——**逐字段**，
   与 `migration-status` 一样可归档。
3. 退出码：
   - 成功执行（含"工件不存在 ⇒ `artifact_present=False, imported=0`"这一格，那是合法稳态）⇒ **0**
   - **企业形态**（`settings.security_enterprise_mode` 为真）⇒ **拒绝、一行不写**，非零退出（与
     `bootstrap-admin` 那格 rc=2 的既有形状一致）
   - 底层存储事故（`user_store.CredentialStoreError` 一类）⇒ 非零退出，且输出里不得出现口令或摘要
4. `migrate` **不接触任何明文口令**（它写的就是工件里已有的摘要），因此不需要 `CREDENTIALS_PASSWORD`；
   如果实现里出现了读 env 口令的代码，就是走偏了。
5. 启动路径**不得**新增自动导入（§20.5 裁定的那一半）。若有人提议在 lifespan 里调用它，本任务的测试
   必须能把那件事测红——写一枚"lifespan 不消费工件"的钉子（例如在 `main.py` 的 lifespan 断言链上，
   或直接在启动一次后检查 `user_credentials` 行数不变）。

## 测试（TDD：先红后绿）

新增用例放在 `backend/tests/test_credentials_contract.py`（该文件已有 `import_from_artifact` 的夹具与
`_artifact()` 助手，复用它，不要复制第二套）：

- 企业形态下 `migrate` rc≠0 且库中一行未写（含已有 argon2id 行不被降级）。
- dev 形态下有工件 ⇒ rc=0、`imported` 等于工件里的账号数、随后 `migration-status` 报
  `legacy_count>0` 且 `must_change=1`。
- dev 形态下**无工件** ⇒ rc=0、`artifact_present=False`、`imported=0`（合法稳态，不得判成失败）。
- 幂等：连跑两次 ⇒ 第二次 `imported=0`、`skipped` 覆盖第一轮的账号；已收敛成 argon2id 的账号不被写回 legacy。
- "启动不自动导入"那枚钉子（上面第 5 条）。
- 输出面：`migrate` 的 stdout 不含 5 枚 legacy digest 的任何前缀，也不含明文口令。

## 边界与规矩（全部硬性）

- 只允许改：`backend/app/cli.py`、`backend/tests/test_credentials_contract.py`。
  需要动 `credentials_migration.py`/`user_store.py`/`main.py` 才能做完 ⇒ **停下来报 NEEDS_CONTEXT**，
  不要顺手改生产模块。
- **TDD**：先写失败用例并留下 RED 证据（命令 + 关键失败输出），再实现，再留 GREEN 证据。
- 焦点门自跑并写进报告：`python -m pytest tests/test_credentials_contract.py -q`（改前改后各一次）。
  不要跑全套件（约 11 分钟，另有安排）。
- 无 git 写命令；不碰 `model-router-v2.3-rc1`；不写 `backend/data/`（测试用 conftest 的重定向库）；
  输出与报告里不得出现明文口令或那 5 枚 digest 字面量；`app/cli.py` 的行尾按**该文件现状**保持
  （先量再写）。一次写操作只改一个文件。
- **报告优先**：本 harness 有 150 回合硬顶，你的前两位同事撞上去过且没留报告。第 30 回合之前先建
  `E:\xiangmu\rag\.superpowers\sdd\SECURITY_A_PLAN\task-10c-report.md` 并持续追加。
- 报告写完后，用不超过 15 行回报：Status、commit-less 交付说明（改了哪些文件）、一行测试摘要、
  疑虑、报告路径。

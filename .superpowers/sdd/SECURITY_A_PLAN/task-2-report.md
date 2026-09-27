# SECA Task 2 执行报告 —— 凭据状态持久层（`backend/app/user_store.py`）

轮次：2026-09-25，宿主 Python 3.13（`C:\Users\zhang\AppData\Local\Programs\Python\Python313`），Windows / Git Bash。
输入：`.superpowers/sdd/SECURITY_A_PLAN/task-2-brief.md`（= `docs/SECURITY_A_PLAN.md` Task 2 逐字提取）+ 冻结规格 §6.1/§6.2/§8.8 + Task 1 已产出的 `app/credentials.py`。
本轮**未执行任何 git 写命令**（无 add / commit / stash / checkout / reset / clean），未自派 subagent。

## 结论

**DONE_WITH_CONCERNS。**

- 表结构、12 个函数的签名、全部 SQL、`CredentialStoreError` / `CredentialRecord` 与 brief **逐字一致**；6 条测试方法的**方法体逐字一致**（脚本核对，见 §3.7）。
- 全套件 **988 passed**（基线 982 + 本任务 6 例），两个工作目录计数相等；无新增 warning。
- CONCERNS 全部是**计划侧**：brief 的实现文本里有 1 处不可运行、Step 1 的测试夹具里有 2 处会让套件红（其中一处会污染生产库、一处会打红别的文件）。三条都在本任务边界内修好了并逐条登记（§3.1–§3.3），需要控制台把裁定回写进 `docs/SECURITY_A_PLAN.md` 的 Task 2 段，否则 Task 3/5 照原文再抄一遍。

---

## 1. 按 brief 步骤的落地对照

| Step | 结果 | 实测 |
| --- | --- | --- |
| 1 写失败的测试 | ✅（+夹具修正，见 §3.3/§3.4） | 追加 `UserStoreSchemaTests` + `UserStoreTransactionTests`，6 例；顶部 import 段按 Step 4 同步 |
| 2 跑测试确认失败 | ✅ | 收集期 `ImportError: cannot import name 'user_store' from 'app'`（brief 预期 `ModuleNotFoundError`：同一根因"模块不存在"，只是 `from app import` 形态的报法），见 §2 RED |
| 3 写实现 | ✅（+D1/D2/D5，见 §3） | 新建 `backend/app/user_store.py`（302 行，LF）；`app/config.py` 补 `conversation_db_path` |
| 4 补测试文件头部 import | ⚠️ 有偏差 | `importlib / inspect / os / tempfile / mock` 与 `from app import credentials, user_store` 全按原文补上；**`from app import config as config_module` 未补**——它唯一的用处是 §3.3 那枚被删掉的 reload，留着就是未用 import |
| 5 跑测试确认通过 | ⚠️ 计数与原文不符 | 本文件 `27 passed, 9 subtests`。brief 的 `19 passed` 是**写计划时的数**：Task 1 两轮评审把该文件从 13 例加到 21 例（21 + 6 = 27）。与台账 #75 记录的是同一族问题 |
| 6 定向门 + 快照 | ✅ | `tests/test_credentials_contract.py tests/test_llm_usage_contract.py` → `128 passed, 5 warnings`（5 条 warning 全部来自 `test_llm_usage_contract.py`，既有）；快照 `snap-task2-app/`（已剥 `__pycache__`，与 Task 1 同法）+ `snap-task2-test.py`；台账已追加 Ruling 行 |

## 2. TDD 证据

### RED（Step 2，实现文件尚未存在）

```
$ cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q
_____________ ERROR collecting tests/test_credentials_contract.py _____________
ImportError while importing test module 'E:\xiangmu\rag\backend\tests\test_credentials_contract.py'.
tests\test_credentials_contract.py:20: in <module>
    from app import credentials, user_store  # noqa: E402
E   ImportError: cannot import name 'user_store' from 'app' (E:\xiangmu\rag\backend\app\__init__.py)
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!
1 error in 0.57s
```

为什么这条红是预期的：本任务的全部产物就是 `app/user_store` 这个名字，测试文件在 import 期就要拿到它。收集期失败 ⇒ 断言面尚未被任何实现"喂"过，也不是"实现写歪了"的红。基线对照：同一命令在追加测试之前是 `21 passed, 9 subtests`（Task 1 终态）。

### 中间态的两条红（都是 brief 自带缺陷，逐条修掉后才绿）

```
FAILED ...::UserStoreTransactionTests::test_password_change_bumps_version_and_clears_lock_state_together
FAILED ...::UserStoreTransactionTests::test_rehash_is_guarded_by_the_version_it_was_computed_for
E   sqlite3.IntegrityError: UNIQUE constraint failed: user_credentials.username
2 failed, 25 passed, 9 subtests passed in 5.26s
```
→ §3.4。修完后：

```
$ cd /e/xiangmu/rag && python -m pytest backend/tests/test_credentials_contract.py::UserStoreSchemaTests \
    backend/tests/test_feishu_identity_contract.py::WarmupGateTests -q
.........FF
E   FileNotFoundError: [Errno 2] No such file or directory: 'config\\llm_registry.json'
2 failed, 9 passed
```
→ §3.3（brief Step 1 的 `importlib.reload(config_module)` 把**别的文件**打红了；`backend/` 为 cwd 时被相对路径掩盖，只有仓库根起会现形）。

### GREEN

```
$ cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q
27 passed, 9 subtests passed in 4.72s
$ cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py \
    tests/test_llm_usage_contract.py -q
128 passed, 5 warnings, 42 subtests passed in 78.77s
```

### 终态（全套件，两个工作目录各跑一次）

| cwd | 结果 |
| --- | --- |
| `/e/xiangmu/rag/backend` → `python -m pytest -q` | `988 passed, 36 warnings, 1007 subtests passed in 238.77s` |
| `/e/xiangmu/rag` → `python -m pytest backend/tests -q` | `988 passed, 36 warnings, 1007 subtests passed in 249.72s` |

计数相等 = 988 = 基线 982 + 本任务 6 例。36 条 warning 与基线同数、同源（`jwt.InsecureKeyLengthWarning` + `conftest` 的 `ledger-guard` 读改道 RuntimeWarning）；对整轮输出 grep `user_store|credentials_contract` → **0 命中**，本任务未引入新 warning。

## 3. 与 brief 的偏离（逐条 + 理由）

### 3.1 `app/config.py` 新增 `conversation_db_path`（brief 的实现不可运行）

brief Step 3 的 `_connect()` 读 `settings.conversation_db_path`，而这枚键**在仓库里从来不存在**：`conversation_store.py:26` 与 `llm/usage.py:223` 一直是各自 `os.getenv("CONVERSATION_DB_PATH", "data/conversations.db")`。逐字执行的结果是 `AttributeError`。
落地：`config.py` 在 `argon2_max_concurrent_ops` 下加 5 行（默认值与 `.env.example:103` 逐字相同）。pydantic-settings 的 `case_sensitive=False` 让 `CONVERSATION_DB_PATH` 天然映射到该字段，env 优先级高于 `.env` 文件。
检查过的连带面：`Settings.model_fields` 只被两条前缀过滤的 `.env.example` 等值钉消费（`LLM_/DEEPSEEK_/QWEN_`、`TYPESAFE_`），新键不进它们的判据；无参 `Settings()` 构造用例仍绿。

### 3.2 `_connect()` 在**每次连接时**读 env，`settings` 只做兜底（绑定约束的直接结果）

Brief 的单读 `settings.conversation_db_path` 恰好做不到"继承 `CONVERSATION_DB_PATH` 会话重定向"：`app.config.settings` 在**收集期**就构造完了，而 `tests/conftest.py` 的 `isolated_llm_ledger`（session fixture）在**用例开始时**才把 env 指到临时库。于是 `UserStoreTransactionTests`（brief 里没有任何夹具）的第一条 `create_argon2` 会按 `data/conversations.db` 这个**相对路径**在 `backend/data/` 里建 `user_credentials` 表并写真凭据行——就是 V2.3 那次的形状。更糟的是 conftest 的写改道闸只包 `app.llm.usage`，看不见 `user_store` 的直连，所以这笔污染**不会有人报警**。
落地：`_database_path()` = `os.getenv("CONVERSATION_DB_PATH") or settings.conversation_db_path`，与 `conversation_store` / `llm.usage` 的解析口径一致；`settings` 那半边保证 brief 里"沿用 `settings.conversation_db_path` 与其环境覆盖"这句仍然成立（它就是 env 未设时的默认值）。
实测（跑完全套之后以只读 URI 复核）：`backend/data/conversations.db` 与仓库根 `data/conversations.db` 的 `sqlite_master` 里都**没有** `user_credentials` 表。

### 3.3 删掉 Step 1/Step 4 的 `importlib.reload(config_module)`（它会把别的文件打红）

`app.config.settings` 是**进程级单例**，`app.main` / `app.llm.*` 在 import 期就把那个对象绑进了自己的命名空间。reload 换掉的只是 `app.config.settings` 这个模块属性：本文件之后跑的用例若靠"改 settings 上的 cwd 敏感键"来工作，就会改到一份再没人读的对象上。实测症状＝`test_feishu_identity_contract.py::WarmupGateTests` 两例从仓库根起 `FileNotFoundError: config\llm_registry.json`（`llm_registry_file` 的覆盖没送到 `llm.warmup()`），从 `backend/` 起被相对默认值掩盖。全仓 grep `reload(` 确认：改动前只有我这一处在 reload 别模块 ⇒ 这颗雷是本文件独有的。
落地：`setUp/tearDown` 各删 1 行，其余原样；随之失去用处的 `config_module` import 不补（§1 Step 4）。换库能力不受影响——生效路径由 §3.2 在连接时读 env。
未采纳的替代方案：reload 后在 tearDown 手工把原对象换回去。它能保住 brief 那两行，但把"谁忘了还原谁就毒化全套件"留在代码里；一条不碰单例的路比一条需要自我修复的路便宜。

### 3.4 抽出 `_CredentialDbPerTest`，两个 TestCase 共同继承（brief 的三条事务用例互相撞主键）

`UserStoreTransactionTests` 三条用例都叫 `admin`，共享一份库时按方法名字典序跑到第二条就 `sqlite3.IntegrityError: UNIQUE constraint failed`（§2 中间态实证，2 failed）。brief 只给 Schema 类写了 setUp/tearDown，事务类漏了。
落地：把那对 setUp/tearDown **原样**上提成私有基类（不新增、不删任何一行），两个类改继承它。断言面零改动：脚本比对结果＝brief 的 6 个 `def test_*` 方法体**逐字**出现在文件里，`setUp`/`tearDown` 各只差 §3.3 那一行。
副作用是正向的：凭据用例从此**不依赖** conftest 的会话 env 才有隔离性。

### 3.5 `_connect()` 另三处照同库既有模块补齐（brief 未写）

- `timeout=30.0`：与会话面同库 ⇒ 写锁是真会撞上的，`sqlite3` 默认的 5s 会把一次正常登录写变成 `database is locked`（口径照 `ConversationStore.connect`）。
- `target.parent.mkdir(parents=True, exist_ok=True)`：默认值是相对路径，`ConversationStore.__init__` 与 `usage.init_usage_db` 都建父目录；本表可能在 CLI（Task 7 的 bootstrap）里先于会话面被写到。
- 惰性建表（`_schema_ready_path` 按**路径**比对，不是布尔旗标）+ 紧随其后的 `connection.commit()`：`ensure_user_credentials_schema()` 之外没人再建表，而读函数（`get_record` / `column_names`）不该要求调用方先建表；建表若不独立提交，就会跟业务写同进同退——第一条 INSERT 失败时连表一起回滚。同款形状在 `app/llm/usage._connect(ensure_schema=True)` 里已经存在。`IF NOT EXISTS` 幂等 ⇒ 并发跑到这里无需加锁。

### 3.6 实现里去掉未使用的 `from typing import Any`；`_COLUMNS` 原样保留

Brief 的 import 段有 `from typing import Any`，全文无消费方（换成实际用到的 `from pathlib import Path`）。`_COLUMNS` 同样是 brief 明写的、当前无人消费的常量——**保留**（它是列序的单一声明处，Task 3/7 的报表类读函数是天然消费方），但如实登记为死码，见 §5。
SQL 文本一个字符没动：`_COLUMNS` 与 INSERT 列表的重复是刻意的，改成 `", ".join(_COLUMNS)` 会动到 brief 钉死的 SQL。

### 3.7 偏离量化（脚本核对，不是自评）

`difflib.SequenceMatcher` 对 brief Step 3 代码块：`269 → 302` 行，similarity **0.935**，全部差异＝§3.1–§3.6 那 6 组（`import os`、`Path`↔`Any`、`_WRITE_TIMEOUT_SECONDS`、`_database_path()`、惰性建表块、`create_argon2` 里那行说明注释）。`_SCHEMA`、CHECK 表达式、12 个函数签名、每条 SQL、`CredentialStoreError`、`CredentialRecord` 字段序均逐字未变。
测试面：6 个方法体逐字；类声明 2 行改基类；setUp/tearDown 各 -1 行。

## 4. 绑定约束回执（全部实测，非"应该没问题"）

| 约束 | 回执 |
| --- | --- |
| `algorithm` 受控值集由 CHECK 钉住，普通写函数无 `algorithm` 形参 | `inspect.signature` 两枚钉在 §1 用例里；手工直连写 `algorithm='bcrypt'` → `sqlite3.IntegrityError: CHECK constraint failed: algorithm IN ('argon2id','legacy-sha256')`（临时库实测）。新建路径 structurally 只有 `credentials.ALGORITHM_ARGON2ID` 一个取值 |
| legacy 唯一 writer 命名 | 全仓唯一能写出 legacy 行的函数是 `import_legacy_digest`；`count_by_algorithm()` 实测 = `{'argon2id': 1, 'legacy-sha256': 1}` |
| 列面无明文列 | `column_names()` → 8 列，`{password, plaintext_password, raw_password}` 与其不相交（用例钉） |
| 明文口令不落日志/审计/异常/repr | 本模块无 logging；唯一异常消息 `CredentialStoreError(f"账号不存在：{username}")` 只含 username；明文只作为 `hash_password()` 的实参出现，不进气泡。`CredentialRecord` 的 repr 含 `password_hash`（哈希、非明文），仍登记给 Task 5/7（§5） |
| §8.8 单事务：新 hash + bump + `failed_attempts=0` + `locked_until=NULL` | 四件事全在 `_bump_and_clear` 那**一条** UPDATE、同一条 `with connection` 事务里。SECA-11 的杀法已实测：`mock.patch.object(user_store, "_bump_and_clear", side_effect=CredentialStoreError)` ⇒ 整条事务回滚，`password_hash` 与 `credentials_version` 与事前逐字相同（用例）。`_bump_and_clear` 保持模块级函数就是为这个注入点 |
| 同库 + 继承 `CONVERSATION_DB_PATH` 会话重定向 | §3.2；全套跑完两份真库的 `sqlite_master` 均无 `user_credentials` |
| 不吞 `CredentialConfigError`、不让库异常逃出口令边界 | 本模块**只**调 `credentials.hash_password`，不调 `verify_password`，也没有任何 `except` ⇒ 校验侧的异常语义原样留给 Task 5 |
| `verify_dummy` 不得存成真实凭据行 | `user_store` 全文不引用 `dummy_hash` / `verify_dummy`（grep 确认） |
| 不 import `app.auth`、无 HTTP/登录逻辑 | `user_store` 的 import 只有 `os / sqlite3 / contextlib / dataclasses / datetime / pathlib / app.credentials / app.config` |
| LF 行尾 | `user_store.py` 与 `test_credentials_contract.py`：`b'\r\n' in bytes` → **False**；`config.py` 保持原有统一 CRLF（`git ls-files --eol` = `w/crlf`，未变 mixed），`git diff --numstat` = **9 插入 0 删除**（Task 1 的 4 行 + 本轮 5 行），零幻影 diff |
| 注释中文、写 WHY、不叙述任务/计划/评审 | 新增注释全部是"为什么这么做"（同库写锁、相对默认值、单例身份、建表提交单位、`create_argon2` 返回值不是占位） |
| 未触碰 untouchable | `app/llm/`、`app/rag.py`、`app/conversation_agent.py`、`app/security.py`、`tests/test_llm_egress_guard.py` 本轮零改动（`git status` 只列 §6 那几项） |

## 5. 未收口 / 交给下游（不静默）

1. `create_argon2` 撞已存在的 username 时抛的是**裸 `sqlite3.IntegrityError`**，不是 `CredentialStoreError`——尽管后者的 docstring 写着"约束"也算它的辖区。brief 的实现没有包，我没有擅自加一层翻译（那会改变 Task 5/7 要 `except` 的类型）。**Task 5/7 必须显式处理**：既不能让它变成"口令错了"，也不能靠 `except CredentialStoreError` 兜住。
2. `list_records` / `delete_record` / `clear_login_failures` 在本任务的 6 例之外**无用例**（brief 未列）。我在临时库里手工实测过：删除幂等（True/False）、`record_login_failure` 对不存在的行返回 False、失败计数 1→2 才落 `locked_until`、`clear_login_failures` 归零并清锁、legacy 行经 `credentials.verify_password` 往返 `ok=True / needs_rehash=True`。补钉归 Task 3/5/7 的消费方用例，或 Task 10 的矩阵。
3. `import_legacy_digest` 不校验 `digest_hex` 是不是 64 位 hex。脏值会在 `verify_password` 上以 `CredentialConfigError` 硬失败（§6.2 的交叉校验就是这道防线），符合"不猜、不降级"。**Task 3 需要裁定**：迁移器是否要在写入前预校验（否则脏摘要会进表，直到那人第一次登录才炸）。
4. `conftest` 的写改道护栏只包 `app.llm.usage`，看不见 `user_store` 直连。本任务靠每例 env 重定向自保；等 Task 3/5/7 的用例开始写凭据表，建议把 §4 那条"真库无 `user_credentials`"升级成等式钉（跑完全套后 `sqlite_master` 无表 **或** 行数 0，且逐份真库各查一次），归 Task 10。
5. 计划文本待回写：Step 3 的 `_connect()`（env 读法 + `conversation_db_path` 的归属）、Step 1 的事务类夹具、Step 4 的 import 段、Step 5 的 `19 passed`（实际 27）。台账 #75 已经是同一族问题，建议合并处理。

## 6. 文件清单

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `backend/app/user_store.py` | 新建（302 行，LF） | 本任务主产物 |
| `backend/tests/test_credentials_contract.py` | 修改（322 → 453 行） | 追加 2 个 TestCase（6 例）+ `_CredentialDbPerTest` + 顶部 import 段 |
| `backend/app/config.py` | 修改（+5 行） | `conversation_db_path`（§3.1） |
| `.superpowers/sdd/SECURITY_A_PLAN/snap-task2-app/` | 新建快照 | `cp -r app`，剥 `__pycache__`，501K |
| `.superpowers/sdd/SECURITY_A_PLAN/snap-task2-test.py` | 新建快照 | 本任务终态测试文件 |
| `.superpowers/sdd/SECURITY_A_PLAN/progress.md` | 追加 | Task 2 台账 + 4 条 Ruling（含 brief 三处缺陷的裁定） |

未改动：`backend/app/credentials.py`（Task 1 产物，本轮只消费）、`requirements.txt`、其余全部。

## 7. 自审发现（读自己的 diff，逐条）

- **`_COLUMNS` 死码**：8 枚列名的单一声明处，但零消费方（brief 原样）。已登记 §5，未擅自删除——它是计划明写的，且 Task 3/7 是天然读者。
- **`ensure_user_credentials_schema()` 与惰性建表重复**：`setUp` 里先 `_connect()`（已建）再 `executescript`（幂等）。保留 = brief 钉死的公共入口，Task 7 的 CLI 与启动钩子是它的使用者；去掉任何一侧都会让"谁来建表"这件事在两个地方各说一半。
- **`_schema_ready_path` 用 `str(target)` 比对**：同一文件的两种写法（相对/绝对、大小写盘符）会被判成"换库了"，代价是多跑一次 `IF NOT EXISTS`——方向是安全的（宁建不漏）。
- **`import_legacy_digest` 的 `cursor.rowcount` 在连接关闭后读**：值在 `execute()` 时就固定了，实测幂等返回 False（第二次导入同名账号）⇒ `ON CONFLICT(username) DO NOTHING` 生效，不会覆写已收敛的行。这一条是 Task 3 重跑迁移器时的关键语义。
- **`record_login_failure` 是 3 条语句、1 条事务**：计数与加锁同提交，不存在"计数涨了、锁没上"的窗口；`max_attempts<=0` 这种坏配置会直接锁死（>=0 恒真），旋钮归属 Task 8，本层不做输入校验（brief 未指定）。
- **`set_password_argon2` 的 SELECT 在 UPDATE 之后、同一事务内**：返回的版本号就是刚落库的那枚，不存在读到别人新 bump 的窗口（同库写锁串行化）。账号不存在时 UPDATE 影响 0 行、随后抛错、事务回滚 ⇒ 不会留下"半条凭据"。
- **无 `if __name__` / 无副作用 import**：模块 import 期只定义 `_SCHEMA` 字符串，不碰文件系统（§3.2 的前提）。

## 8. 状态建议

DONE_WITH_CONCERNS，可进评审。CONCERNS 不含"我不确定实现是否正确"，只含"§5 那 5 条要在下游任务里闭合 + §3 的三处 brief 缺陷要控制台回写计划文本"。

---
---

# 修复轮 R1 —— 评审 F1–F5 回执（追加，§1–§8 原样保留不覆写）

轮次：2026-09-25 R1。输入 = 新鲜评审的 4 条 Important（F1–F4）+ 1 条全局约束违例（F5）+ 2 条
顺手折入的 Minor（`CredentialRecord.__repr__`、夹具里的 `importlib.reload`），以及控制台对 F1
的裁定：`settings.conversation_db_path` 源于计划文本的一句错误假设（该字段从来不存在），
已从计划中删除 ⇒ `user_store` 必须与两个同库读者用同一个真源。

零 git 写命令。本轮改动面 = `backend/app/user_store.py` + `backend/tests/test_credentials_contract.py`
+ `backend/app/config.py`（只回退 F1(d) 那 5 行）。`app/llm/`（含 `usage.py`）、`app/rag.py`、
`app/conversation_agent.py`、`app/security.py`、`app/credentials.py`、`tests/conftest.py`、
`tests/test_llm_egress_guard.py` 本轮零改动。

## 9.0 先更正被本轮推翻的旧结论

| 旧条目 | 状态 | 现在的说法 |
| --- | --- | --- |
| §3.1「`config.py` 新增 `conversation_db_path`（brief 的实现不可运行）」 | **撤销** | 前提错了：不是"brief 引用了一个不存在的键"要由实现去补，而是那句 brief 本身要删。字段已从 `config.py` 回退（`git diff --numstat` 9 → **4** 插入，剩下的 4 行是 Task 1 的 `argon2_max_concurrent_ops`）。"不可运行"的正确修法是改计划，不是给计划造字段 |
| §3.2「`os.getenv(...) or settings.conversation_db_path`，与兄弟口径一致」 | **撤销** | 那是**半个**口径：`or settings...` 那半边把 dotenv（`config.py:8` 的 `env_file=".env"` + `backend/.env:33`）接进来了，而两个兄弟不读 dotenv ⇒ 正是 F1 的分叉源。现在只留 env 那一半 |
| §3.5「惰性建表（`_schema_ready_path` 按路径比对）+ 紧随其后的 commit」 | **撤销** | 读路径建表 = 在任意"env 被清掉 ⇒ 路径退回默认值"的调用里往那个文件提交 DDL。`ensure_user_credentials_schema()` 是唯一建表者 |
| §4「同库 + 继承 `CONVERSATION_DB_PATH` 会话重定向」 | **成立（口径变严）** | 之前只继承 conftest 的 env 那一步；现在解析式与兄弟逐字相同，且另备 `database_path()` 这道闸位 |
| §5.1「`create_argon2` 撞已存在 username 时抛裸 `sqlite3.IntegrityError`」 | **闭合** | F3，见 §9.3 |
| §5.4「conftest 的写改道护栏看不见 `user_store` 直连」 | **备好接缝** | F1(b) 给了 `database_path()`；本轮另钉一例"换掉它就能改道本模块"。装闸动作本身归 Task 3（conftest 不在本轮 scope 内），见 §9.1 的残留缝 |
| §7「`_COLUMNS` 死码」 | **闭合** | F4：它现在是 INSERT 的列名真源，并由 `column_names()` 反向验货 |

## 9.1 F1（Important）—— 唯一真源 + `database_path()` 接缝 + 读路径不建表

**改了什么（`backend/app/user_store.py`）**

- (a) 删 `from app.config import settings`。新增 `_DB_PATH_ENV_VAR = "CONVERSATION_DB_PATH"`
  与 `_DB_PATH_DEFAULT = "data/conversations.db"`，取值与 `conversation_store.py:26` /
  `llm/usage.py:223` 的字面量逐字相同。
- (b) 私有 `_database_path()` → **公开 `database_path()`**（与 `usage.database_path` 同名同形，
  因为 `conftest.py:173` 的 `LedgerGuard.install()` 第一道闸就是按这个名字挂的），
  函数体一行：`return Path(os.getenv(_DB_PATH_ENV_VAR, _DB_PATH_DEFAULT)).expanduser()`。
  它是全模块**唯一**的路径解析点，`_connect()` 通过模块全局调它（可被打桩替换）。
- (c) `_connect()` 里的惰性 `executescript(_SCHEMA)` + `connection.commit()` + 模块级
  `_schema_ready_path` 旗标**整块删除**；`ensure_user_credentials_schema()` 成为唯一建表者
  （加了写明这一点的 docstring）。`target.parent.mkdir(...)` 保留：默认值是相对路径，
  两个兄弟同样建父目录，且目录不是数据。
- (d) `app/config.py` 的 5 行（3 行注释 + 字段 + 空行）按字节回退，CRLF 未翻转。

**覆盖用例（新增 `UserStoreIsolationTests`，4 例）**

| 用例 | 钉住的东西 |
| --- | --- |
| `test_the_effective_path_is_the_siblings_own_env_key` | `patch.dict(os.environ, {}, clear=True)` 下等于 `Path("data/conversations.db")`；设了 `CONVERSATION_DB_PATH` 时等于它——**同一枚 env 键、同一条默认值**就是兄弟们的口径 |
| `test_the_module_never_resolves_the_shared_file_through_settings` | AST 扫本模块 import 面，任何 `…config` 都不许出现 ⇒ dotenv 侧的第二个真源长不出来 |
| `test_read_paths_never_create_the_schema` | 指向一份没建过表的临时文件：`get_record` / `list_records` 抛 `sqlite3.OperationalError`、`column_names()`（PRAGMA）给空列表，事后该文件 **`st_size == 0`** ⇒ 一条 DDL 都没提交 |
| `test_a_guard_can_redirect_this_module_through_the_same_seam` | 用 conftest 包 `usage` 的**同一手法**（`mock.patch.object(user_store, "database_path", ...)`）：建表 + INSERT 全部落在被改道的文件（1 行），env 指向的那份 0 行 ⇒ 接缝是真的被连接使用，不是装饰 |

**残留缝（不静默，交 Task 3）**：装了接缝 ≠ 已装闸。`LedgerGuard.install()` 是按
`("database_path", "_execute", "_connect")` 三个名字 `getattr` 的，后两枚是 `usage` 专有的
⇒ 现在直接把 `user_store` 交给它会 `AttributeError`。Task 3 要么给 `install()` 加"属性在场才包"，
要么为凭据表另装一道只换 `database_path` 的闸。**在那之前**的暴露面已经缩到最小：某条
`clear=True` 的用例若碰本模块，最坏结果是（i）`<cwd>/data/conversations.db` 被以读写语义打开
（实测：文件缺席时 `sqlite3.connect` 会留下一个 **0 字节**空文件；本仓两份都在，故 size/mtime 均不动）、
(ii) 紧随其后就是 `no such table: user_credentials` 报错——不落 DDL、不落行，且那声报错直接
指向漏改道的人，比"静默长出半张表"便宜。本轮全套件实测见 §9.8 第 4 项。

## 9.2 F2（Important，计划明令）—— "渐进重哈希不 bump 版本" 从 0 覆盖到 2 枚钉子

`UserStoreTransactionTests::test_rehash_is_guarded_by_the_version_it_was_computed_for` 重写（**方法体不再逐字**，这是评审要求的偏离）：

- 版本快照改成 `version_before = get_record("admin").credentials_version`，取在**成功 rehash 之前**。
- 成功 rehash 后新增 `assertEqual(version_before, record.credentials_version)` —— 正面钉"不 bump"。
- 陈旧那次改用 `expected_version=version_before + 1`（评审指出的旧写法 `record.credentials_version + 5`
  在"bump 了"和"没 bump"两种实现下都返回 False，等于没钉）。`+1` 是从重哈希前的快照推出来、
  **从没落进库里**的版本号：实现一旦顺手 bump，`version_before + 1` 就恰好命中当前行 ⇒ 那条 UPDATE
  落地并返回 True ⇒ `assertFalse` 红。意外 bump 从此不可能蒙过这一例。
- 尾部再补三条：`must_change` 仍为 True（旧写法就有）、版本仍是 `version_before`、`password_hash`
  与成功那次逐字相同（陈旧调用连"顺手改哈希"的空间都没了）。

## 9.3 F3（Important）—— 约束翻译与"账号不存在"的消息面

- 新增两枚公开常量：`ACCOUNT_MISSING_MESSAGE` / `ACCOUNT_EXISTS_MESSAGE`（固定文案，调用方可等值
  分派而不必 match 文案）。
- `create_argon2`：`INSERT` 包 `except sqlite3.IntegrityError as exc` ⇒
  `raise CredentialStoreError(f"{ACCOUNT_EXISTS_MESSAGE}：{username}") from exc`。
  消息不含驱动文案（`UNIQUE constraint failed: user_credentials.username`）、不含任何口令材料；
  原文只在 `__cause__` 上，定位能力不丢。注释写明这条语句上只有主键可能撞（其余列全由实参/
  字面量供值），以及为什么裸驱动文案不该进服务端日志/运维控制台。
- `set_password_argon2` 的"账号不存在"：`CredentialStoreError(f"账号不存在：{username}")` →
  `CredentialStoreError(ACCOUNT_MISSING_MESSAGE)`，**零账号名**。理由写在常量上方：§9.1 把
  「有身份无凭据行」折成与口令错同一条 401（`用户名或密码错误` / `invalid_credentials`），
  而这条异常正是在登录/改密腿上被抓的——消息带账号名就等于给响应面或审计 `detail` 递一枚
  "这个用户名存在吗"的探针（且自由文本进审计字段本身违 §9.1 末段）。
  两枚消息都通过 `assertNotIn` 类用例钉住。

**覆盖用例（新增 `CredentialStoreErrorSurfaceTests`，3 例）**：`assertIsInstance(caught.exception.__cause__, sqlite3.IntegrityError)`
+ 消息里 `assertNotIn("UNIQUE constraint")` / `assertNotIn("user_credentials.username")`
+ 明文口令不出现在 `消息 + repr(__cause__)` 里 + 撞键后原行 `password_hash` 未变；
`assertEqual(ACCOUNT_MISSING_MESSAGE, str(exc))` + `assertNotIn("nobody-here", str(exc))`；
repr 那例见 §9.6。

## 9.4 F4（Important，计划明令）—— 8 枚列名从三处收成两处，并让 `_COLUMNS` 上岗

- 新增 `_INSERT_VALUES` 常量与 `_insert_sql(*, ignore_conflicts: bool)`：两条新建路径的 INSERT
  文本改为共用它，列名段 `', '.join(_COLUMNS)` 生成。**SQL 语义逐字节未动**——脚本核对：
  `plain byte-identical: True` / `legacy byte-identical: True`（对收拢前两处手写字符串等值）。
- `_COLUMNS` 从"当前无人消费"变成列名段的真源，注释如实写明验货关系。
- 新增用例 `UserStoreSchemaTests::test_the_column_list_authority_is_the_table_and_the_insert`
  把三处收成一条链：① `assertEqual(tuple(user_store.column_names()), user_store._COLUMNS)`
  （表的列序验货 `_COLUMNS`，加列漏改即红）；② `_insert_sql(ignore_conflicts=False)` 与那段
  **字面量 SQL** 等值（防止有人把手写文案改歪、或把收拢改成隐式拼接）；③
  `assertEqual(len(_COLUMNS), statement.count("?") + 3)`（5 个占位 + 3 枚字面量列 = 8 列，
  加列忘了补占位即红）。

## 9.5 F5（全局约束违例）—— 注释里的任务号

| 位置（改动前） | 改动后 |
| --- | --- |
| `create_argon2` 内 `"Task 7 的 CLI 要把它打印出来"` | 说的是不变量本身：新建行的 `credentials_version` 恒为 1（列默认值与 INSERT 里那枚字面量同一取值），调用方（bootstrap CLI / 启动种子）要打印的就是"刚落库的版本号"，返回 `None` 会丢掉这条事实 |
| `import_legacy_digest` docstring `"Task 3 的调用方扫描共同钉住这一点"` | 「SECA-05 的 AST 扫描与对调用方的扫描共同钉住这一点——所以"谁能写出 legacy"是机器判据，不是约定」；同段把 `credentials_migration` 表述为"迁移器"这一模块事实 |

规格 id（`SEC-A-004` / `SECA-01` / `SECA-05` / `SECA-11` / `SECA-12` / `§6.1` / `§9.1`）与模块事实保留。
`user_store.py` 与 `test_credentials_contract.py` 全文正则扫 `Task\s*\d+` → **0 命中**（见 §9.8 的配套核对块）。

## 9.6 折入的两条 Minor

- **`CredentialRecord.__repr__` 不再携带 `password_hash`**：`password_hash: str = field(repr=False)`
  （口径照 `config.py:26` 的 `typesafe_api_key: SecretStr` 那一族先例——secret 在 repr 里只能是
  `**********`，本模块没有 SecretStr 可用，因为它是从库里读出来的裸串，所以直接关掉打印面）。
  本模块没有 logging，repr 是密文材料进日志的唯一
  通道。用例 `test_a_record_repr_does_not_carry_the_password_hash` 三面钉：字段还在
  （`record.password_hash.startswith("$argon2id$")`）、`repr(record)` 里既无该串也无 `$argon2id$`、
  `assertEqual(record, get_record(...))` ⇒ `repr=False` 只关打印面，等值仍按全部列判。
- **夹具里的 `importlib.reload(user_store)` 删除**（setUp/tearDown 各 1 行），随之失去用处的
  `import importlib` 一并撤（本轮 import 段新增 `import sqlite3`）。它确实不再买任何东西：F1 之后
  本模块没有 import 期状态（路径每次现读 env、schema 只有显式调用才建），换 env 就换完了库；
  留着反而与 `_CredentialDbPerTest` docstring 的"不 reload"自相矛盾，且 reload 换来的新模块对象
  会让 `mock.patch.object(user_store, "database_path", ...)` 这类"先取属性再打桩"的写法打在旧对象上
  ——本轮 §9.1 的两例正是这个手法。docstring 已按这一点重写。

## 9.7 可证伪性实测（7 枚变异体，逐枚按字节回原）

手法：读 `app/user_store.py` 字节 → 注入变异 → 跑对应用例 → `write_bytes` 还原 →
`source restored byte-for-byte: True`。（全程零 git 写命令；轮 1 的 §3.7 那个"文本模式写翻 CRLF"
教训在这里成立，所以用 `write_bytes`。）

| 变异体 | 目标用例 | 结果 |
| --- | --- | --- |
| M1 `apply_rehash` 的 UPDATE 追加 `credentials_version = credentials_version + 1` | `test_rehash_is_guarded_by_the_version_it_was_computed_for` | **KILLED**（`1 failed in 2.25s`；评审点名的那枚"四条断言全绿"的变异体现在必红） |
| M2 `create_argon2` 的 `except sqlite3.IntegrityError` 改成打不到的类型（= 裸驱动异常逃出去） | `test_a_duplicate_username_raises_a_store_error_with_the_cause_kept` | **KILLED**（`1 failed in 1.95s`） |
| M3 "账号不存在"消息改回带 `username` | `test_the_missing_account_message_names_nothing_the_response_face_could_leak` | **KILLED**（`1 failed in 2.22s`） |
| M4 去掉 `field(repr=False)`（`password_hash` 回到 repr） | `test_a_record_repr_does_not_carry_the_password_hash` | **KILLED**（`1 failed in 2.11s`） |
| M5 把建表塞回 `_connect()`（读路径顺手 `executescript` + commit） | `test_read_paths_never_create_the_schema` | **KILLED**（`AssertionError: OperationalError not raised` ⇒ 读路径真的会写脏落点） |
| M6 `database_path()` 退回 `os.getenv(...) or settings.conversation_db_path` | `test_the_module_never_resolves_the_shared_file_through_settings` + `..._siblings_own_env_key` | **KILLED**（`2 failed in 2.25s`，两枚都红） |
| M7 交换 `_COLUMNS` 前两列（"死码"说谎列序） | `test_the_column_list_authority_is_the_table_and_the_insert` | **KILLED**（`1 failed in 1.85s`） |

7/7 击杀，无一存活；还原后聚焦套件复绿（§9.8 第 1 项）。

## 9.8 命令与输出（全部本轮实测）

```bash
# 1) 聚焦（本轮基线 27 → 35：+4 F1 / +3 F3·repr / +1 F4）
#    对**终态字节**跑的那一遍：test_credentials_contract.py 31744 bytes / sha256 c9bc52cad5c348d1 / crlf 0
cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q
35 passed, 9 subtests passed in 4.93s

# 2) 评审点名的两条"会 clear env"的套件——证明没有任何用例写到真库
python -m pytest tests/test_llm_usage_contract.py tests/test_llm_egress_guard.py -q
136 passed, 5 warnings, 125 subtests passed in 97.33s (0:01:37)
#   5 条 warning 与轮 1 同源（jwt.InsecureKeyLengthWarning）；终端摘要里
#   `[ledger-guard] … 写` 计数 0（一条写改道都没有）

# 3) 全套件，两个 cwd（对**终态字节**复跑；两份都是 996 = 基线 988 + 本轮 8 例）
cd /e/xiangmu/rag/backend && python -m pytest -q
996 passed, 36 warnings, 1007 subtests passed in 203.35s (0:03:23)
cd /e/xiangmu/rag && python -m pytest backend/tests -q
996 passed, 36 warnings, 1007 subtests passed in 198.33s (0:03:18)

# 4) F1 "真库"主张的自证（跑完全套之后，只读 URI）
data/conversations.db tables: ['conversations', 'llm_request_logs', 'message_sources', 'messages', 'sqlite_sequence'] | user_credentials present: False
../data/conversations.db tables: ['conversations', 'message_sources', 'messages', 'sqlite_sequence'] | user_credentials present: False
#   点数时刻的 mtime 早于本轮任何一次运行 ⇒ 既没有 DDL 也没有行：
#   backend/data/conversations.db size=57344 mtime=2026-09-24 04:47:18
#   仓库根  data/conversations.db size=40960 mtime=2026-09-12 22:14:00
```

配套核对（同一轮）：

```
# SQL 逐字节未动（F4）
plain byte-identical: True   legacy byte-identical: True
# 行尾（按字节）
app/user_store.py                        crlf 0   lf 345   -> LF 保持
tests/test_credentials_contract.py       crlf 0   lf 605   -> LF 保持
app/config.py                            crlf 178 lf 178   -> 原统一 CRLF 未翻转
# 改动面（零幻影 diff）
git diff --numstat -- backend/app/config.py  ->  4  0  backend/app/config.py     （轮 1 是 9 0）
git status --porcelain  ->  M config.py / M requirements.txt / ?? credentials.py /
                           ?? user_store.py / ?? test_credentials_contract.py / ?? docs 两份
                           （requirements.txt 与 credentials.py 是 Task 1 的面，本轮未动）
# F5 扫描
app/user_store.py -> clean   tests/test_credentials_contract.py -> clean   （Task\d+ 0 命中）
```

测试面计数对账：`UserStoreSchemaTests` 3→4、`UserStoreTransactionTests` 3（1 例方法体重写）、
`UserStoreIsolationTests` 新增 4、`CredentialStoreErrorSurfaceTests` 新增 3 ⇒ 本文件 27→35，
全套件 988→996，两个 cwd 相等，warning 数与基线同（36）。

## 9.9 文件、快照与交接

| 文件 | 本轮 |
| --- | --- |
| `backend/app/user_store.py` | 345 行（轮 1 是 302），LF。`settings` 依赖去掉、`database_path()` 公开、`_connect()` 不建表、`_insert_sql()` 收拢、两枚消息常量 + `IntegrityError` 翻译、`field(repr=False)`、两处任务号注释重写 |
| `backend/tests/test_credentials_contract.py` | 605 行（轮 1 是 453），LF。+2 个 TestCase、**+8 例**（1 枚 F4 列序 / 4 枚 F1 隔离 / 3 枚 F3·repr）、另有 1 例方法体重写（F2，不增例）、import 段 `-importlib` `+sqlite3`、夹具去 reload 并重写 docstring 第③条 |
| `backend/app/config.py` | **回退** 5 行（F1(d)），CRLF 形态与 `git ls-files --eol`（`i/lf w/crlf`）均未变 |
| `.superpowers/sdd/SECURITY_A_PLAN/snap-task2-r1-app/` + `snap-task2-r1-test.py` | 新增快照（剥 `__pycache__`，773K；命名沿用 Task 1 的 `-r1-` 轮次约定，`snap-task2-app/` 原样不动）。与轮 1 快照 `diff -rq` 只列出 `config.py` 与 `user_store.py` 两枚差异文件 |
| `docs/SECURITY_A_PLAN.md` | **未动**（不在本轮 scope 内）。待控制台回写：Task 2 Interfaces 里"沿用 `settings.conversation_db_path` 与其环境覆盖"整句、Step 3 的 `_connect()`（`sqlite3.connect(str(settings.conversation_db_path))` + 惰性建表形状）、Step 1 的 rehash 用例、Step 4 的 import 段（`importlib`）、Step 5 的 `19 passed`（实际 35） |

交下游（不静默）：

1. **Task 3 必须装那道闸**：`user_store.database_path()` 是为本模块准备的接缝，但
   `LedgerGuard.install()` 现在只认 `usage` 的三件套（见 §9.1 残留缝）。凭据表的第一位真实消费方
   落地时，同轮把 conftest 扩到本模块，并把轮 1 §5.4 提的"真库无 `user_credentials`"升级成等式钉
   （跑完全套逐份真库点数：表不存在 **或** 0 行）。本轮只留了 §9.8 第 4 项那种人工实测。
2. **Task 5 的分类语义**：`CredentialStoreError` 现在覆盖三类事故（连接、约束冲突、版本/行缺失），
   消息两枚常量可等值分派；仍**不**含"口令错了"这一类，也不吞 `credentials.CredentialConfigError`。
   把 `str(exc)` 往响应面或审计 `detail` 送之前，先看 §9.3 那条约束：`ACCOUNT_MISSING_MESSAGE`
   是零账号名的固定文案，`ACCOUNT_EXISTS_MESSAGE` 那枚**带 username**（启动期专用），别把它送到
   登录面去。
3. 轮 1 §5.2/§5.3 两条（`list_records`/`delete_record`/`clear_login_failures` 无用例、
   `import_legacy_digest` 不校验摘要格式）本轮**未动**，仍挂 Task 3/5/7 与 Task 10。
4. 本轮未收的 Minor 列表其余项（评审原话"rest of the Minor list stays deferred"）保持原状。

状态建议：**DONE**。F1–F5 与两条折入项全部落地且各有变异体反证；计划文本回写与 conftest 装闸
是明确的两笔外部账。

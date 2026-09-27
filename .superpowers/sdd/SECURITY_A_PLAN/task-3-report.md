# Task 3 报告 — 受限迁移路径（`credentials_migration.py` + 升级工件）

状态：**DONE_WITH_CONCERNS**（功能与四条移交全部落地、套件全绿；concerns 是三条"留给 Task 5/10 的事实"与两条"无用例覆盖的防御分支"，见文末）

跑测口径（进本任务前的基线：定向 35 passed / 9 subtests；全套件 996 passed / 36 warnings / 1007 subtests，两 cwd 相等）：

| 命令 | 结果 |
| --- | --- |
| `cd backend && python -m pytest tests/test_credentials_contract.py -q` | **57 passed, 1 warning, 17 subtests passed** in 8.21s |
| `python -m pytest tests/test_llm_usage_contract.py tests/test_llm_egress_guard.py tests/test_model_router_v23_contract.py -q` | **585 passed, 24 warnings, 502 subtests passed** in 112.52s（含定向那份；三份单独跑时 528 passed / 23 warnings / 485 subtests） |
| `cd backend && python -m pytest -q` | **1018 passed, 37 warnings, 1018 subtests passed** in 232.99s |
| `cd /e/xiangmu/rag && python -m pytest backend/tests -q` | **1018 passed, 37 warnings, 1018 subtests passed** in 229.92s |

两行数字在**最后一批（纯注释）修改之后**原样复跑过一遍确认：backend cwd `1018 passed, 37 warnings, 1018 subtests in 239.11s`、仓库根 `同一组数字 in 213.41s`。快照是在那次复跑之后重取的，并已 `diff -r` 证明与交付态逐字节相同（第一遍 `cp -r app` 在目录已存在时会嵌一层 `app/`，已删净并复验）。

两 cwd 计数相等 ✅（+22 用例、+11 subtests、+1 warning；warning 那 1 枚来自 `effective_ledger_path()` 在清空 env 下的一次**读**改道，属既有 N1 通道，不是新增噪声源）。

生产库污染证明（全套件跑完之后读，只读 URI）：

```
E:\xiangmu\rag\backend\data\conversations.db
  exists=True size=57344
  tables=('conversations', 'llm_request_logs', 'message_sources', 'messages', 'sqlite_sequence')
  user_credentials present=False rows=None
E:\xiangmu\rag\data\conversations.db
  exists=True size=40960
  tables=('conversations', 'message_sources', 'messages', 'sqlite_sequence')
  user_credentials present=False rows=None
credential write redirects this session: []
```

---

## 1. 实现了什么 vs 简报

### 简报逐条

| 简报条目 | 状态 | 说明 |
| --- | --- | --- |
| Step 1 从源码生成工件（正则、不手抄） | ✅ | 输出正是 `5 ['admin', 'hr01', 'sales01', 'user', 'viewer']`；另用 `auth.USERS` 的字典值做了一次等值复算：`{u: d["password_hash"] for ...} == read_artifact()` → `True`，`mismatched: set()`。零手抄。 |
| 工件三顶层键、digest 而非明文 | ✅ | `generated_at`（UTC ISO）/ `source: "app/auth.py@pre-SEC-A"` / 5 条 64-hex。全文件无任何明文口令。 |
| Step 2 的 5 枚 `MigrationPathTests` | ✅ | 逐字照搬，只换夹具（偏离 D1）。 |
| Step 4 的实现 | ✅ + 收紧 | 签名、常量名、默认参数、异常类、三枚 dataclass 字段全同；`read_artifact`/`import_from_artifact` 各加了三处判定（D3/D4）。 |
| Step 5 `24 passed` | ⚠️ 期望值过期 | 实际 57。基线本身就是 35（简报写这份时 `user_store` 的用例还没进来），台账 TODO #75 已登记"简报计数需校正"。 |
| Step 6 快照 + 台账 | ✅ | `snap-task3-app/`、`snap-task3-legacy-artifact.json`、`snap-task3-test.py`、`snap-task3-conftest.py`；两条 Ruling 已进 `progress.md`（另加我这一轮的 4 条）。 |
| Produces 接口（Task 5/7/10 消费） | ✅ | `LEGACY_INPUT_PATH` / `MigrationArtifactError` / `MigrationReport` / `AccountStatus` / `MigrationStatus` / `read_artifact` / `import_from_artifact` / `status` 全在，形状与简报逐字相同。 |

### 真实工件干跑（临时库，产物已删）

```
default artifact path: data\legacy_credentials.json True
read_artifact entries: 5 ['admin', 'hr01', 'sales01', 'user', 'viewer']
all 64-hex lowercase: True
report: MigrationReport(artifact_present=True, imported=('admin','hr01','sales01','user','viewer'), skipped=(), reason='')
status: 5 0 [('admin','legacy-sha256',True), ('hr01','legacy-sha256',True), ...]   # 5 legacy / 0 argon2id / must_change 全 True
re-import: MigrationReport(artifact_present=True, imported=(), skipped=('admin','hr01','sales01','user','viewer'), reason='')
status after rerun: 5                                                              # 幂等，不降级
```

### 简报之外新增的交付（四条移交要求）

- `tests/conftest.py`：护栏扩到凭据面（`install_credential_store` + 两道闸 + 归类升级 + 5 枚公开口径 + 逐例归责钩子/终端汇总）。
- `tests/test_credentials_contract.py`：`CredentialStoreGuardTests`（5 枚，自建"假真库"驱动真 `user_store`）+ `CredentialGuardWiringTests`（4 枚，会话接线与真库哨兵）。

---

## 2. 每一条偏离与理由

**D1 夹具：不用简报的 `importlib.reload(config_module)` / `reload(user_store)`，改继承 `_CredentialDbPerTest`。**
Task 2 台账已把 reload 判为缺陷（换掉的是进程级 `settings` 单例，`app.main` / `app.llm.*` 手里还是旧对象，代价是同会话后面 `test_feishu_identity_contract.py::WarmupGateTests` 两例从仓库根起红）。简报的 5 枚用例与断言逐字未动，只有 `setUp/tearDown` 换成既有夹具。`MigrationPathTests` 的 `_artifact()` 与 `_valid()` 两个 helper 是本任务加的（`_valid()` 只为让"只改 credentials"的用例不重抄出处两键）。

**D2 收紧 `read_artifact`：出处两键必在场且非空。**
简报只把顶层键集**封闭**（多键拒），不要求两枚出处字段在场。§8.2 整节的立论是"升级工件 ≠ 随手放的凭据文件"，而这两枚键正是唯一机器可辨的差别；一份没有 `source` 的 digest 集与 closure 之后有人新塞进来的文件在扫描面上同形。失败方向是"整份拒读 ⇒ 零 legacy 行"，运维重跑一次导出即可，故取严。

**D3 收紧：`credentials` 为空 ⇒ `MigrationArtifactError`，而不是 `artifact_present=False`。**
简报的 `if not block: return MigrationReport(artifact_present=False, ...)` 会把"升级只导了 0 个人"读成"这是全新安装"——两个状态在报告面上必须可分（`artifact_present` 说的是文件在不在场）。空块本身就是脏输入。

**D4 收紧 + 移交④：`import_legacy_digest` 的返回值参与报告。**
简报把返回值丢掉、无条件 `imported.append(username)`。写手用的是 `INSERT ... ON CONFLICT(username) DO NOTHING`，`only_missing=False` 或并发下它会回 False=**那行没落地**；报成"导入成功"就是报告与 `legacy_count` 分叉，而 SECA-04 判闭合读的正是那个数。现在 False 落进 `skipped` 并给一句 `reason`。钉它的用例 = `test_a_writers_declination_is_never_reported_as_an_import`（把这条改回简报写法：定向立刻 1 failed，见变异 A）。

**D5 `CredentialStoreError` 明确不 catch。**
简报的实现也没 catch，但没有测试与注释担保——移交④要求它不许被读成"口令错了"或静默跳过。现在文档字符串第 3 点写明理由，并有 `test_a_store_incident_stays_a_store_incident`：断言异常原样逃出、不是 `MigrationArtifactError`、不是 `CredentialConfigError`、消息里没有 digest、库里零行。

**D6 收紧：用户名空白/首尾空白 ⇒ 整份拒。**
空主键的行写得进查不出（`get_record("")` 之外的任何读都拿不到它）；带首尾空格的名字若被静默 trim，等于把某个人的 digest 发给另一个账号。

**D7 `LEGACY_INPUT_PATH` 保持简报的相对路径 `Path("data/legacy_credentials.json")`。**
它和 `user_store._DB_PATH_DEFAULT`（`data/conversations.db`）是同一种相对性：后端进程按同一 cwd 解析两件事，换工作目录时一起换。简报明写这是接口值，不改。**代价记进 concerns（Task 5 的启动编排必须按后端 cwd 解析，或显式收 `path` 参数）。**

**D8 工件写出时带 `newline="\n"`。**
简报的脚本没给 `newline`；Windows 文本模式会把 `json.dumps` 的 `\n` 换成 `\r\n`。工件本身是 JSON（`read_text` + `json.loads` 对 CRLF 免疫），但快照差分与 closure 扫描按字节看，LF 才是这个仓库的口径。

**D9 测试文件顶部多了 `json` / `dataclasses` 与 `import conftest as ledger_guard`。**
简报 Step 3 已点名前两枚里的 `json` + `credentials_migration`；`dataclasses` 用于 `AccountStatus` 无 `password_hash` 字段的形状钉；`ledger_guard` 是那两枚护栏用例 required 的（手法与 `test_llm_egress_guard.py:83`、`test_model_router_v23_contract.py:111` 逐字同形）。

**D10 改了 Task 2 的一枚既有用例（唯一一处动到已评审干净的东西）。**
`UserStoreIsolationTests::test_the_effective_path_is_the_siblings_own_env_key` 原来在清空 env 下断言 `user_store.database_path() == Path("data/conversations.db")`。护栏一装（移交①），这个属性返回的就是**改道后**的路径 ⇒ 该断言变成"护栏自证"。现在它读 import 期捕获的 `RAW_DATABASE_PATH`（收集期早于会话 fixture，仓库里 conftest 自己写过这个时序）。两枚期望值、mock 形状、用例名逐字未动；"护栏在场"改由新增的 `CredentialGuardWiringTests` 钉。RED 证据里这一步是可见的：装闸后该用例先红（`AssertionError` at line 438），再按此改法转绿。

**D11 护栏的凭据面不发中途 read warning（`warn_on_read=False`）。**
这一面的读/写归类要到语句执行时才定型，warning 却必须当场发——于是一条**写**改道会先收到一句"只读"的提醒（同一测试里自相矛盾）。提醒没丢：它搬到收尾的 `[credential-guard]` 汇总与 `credential_read_redirects()`，那里拿的是定过型的记录。账本面保持原样（它的归类在解析那一刻就是真的，消息文本逐字未变，见 diff 里 `self.label`/`self.subject` 的默认值）。

---

## 3. RED / GREEN 证据

### RED #1 — 迁移模块不存在（简报 Step 3 期望的那一步）

```
$ cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q
_____________ ERROR collecting tests/test_credentials_contract.py _____________
tests\test_credentials_contract.py:21: in <module>
    from app import credentials, credentials_migration, user_store  # noqa: E402
E   ImportError: cannot import name 'credentials_migration' from 'app' (E:\xiangmu\rag\backend\app\__init__.py)
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```
为什么是预期：模块尚未创建。简报写的是 `ModuleNotFoundError`，实测是 `ImportError` —— 同一个原因（文件不存在）的两种文案，`from app import X` 走的是"包里没这个属性"那条路。**未**照简报去手改期望值。

### RED #2 — 迁移器已实现、护栏还没接到凭据面

```
$ python -m pytest tests/test_credentials_contract.py -q
9 failed, 48 passed, 17 subtests passed
FAILED ...::CredentialStoreGuardTests::test_a_credential_write_is_classified_write_and_lands_in_the_target
FAILED ...::CredentialStoreGuardTests::test_a_pure_read_stays_read_and_lands_nothing_on_the_protected_path
FAILED ...::CredentialStoreGuardTests::test_a_schema_creation_on_the_redirected_path_is_a_write_too
FAILED ...::CredentialStoreGuardTests::test_the_restricted_legacy_writer_goes_through_the_same_seam
FAILED ...::CredentialStoreGuardTests::test_the_write_mark_is_per_connection_not_a_latch
FAILED ...::CredentialGuardWiringTests::test_a_credential_connect_under_a_cleared_env_cannot_touch_the_real_databases
FAILED ...::CredentialGuardWiringTests::test_no_test_in_this_session_wrote_a_credential_row_into_a_real_database
FAILED ...::CredentialGuardWiringTests::test_the_credential_table_resolves_to_the_same_file_as_the_ledger
FAILED ...::CredentialGuardWiringTests::test_the_session_guard_watches_the_credential_table_too

E   AttributeError: module 'conftest' has no attribute 'credential_guard_is_active'
```
（同一次跑里 `MigrationPathTests` 13/13 已绿——两批用例分别对应手的两处交付，失败原因各自唯一。）

### RED #3 — 装闸之后那枚 Task 2 用例的反噬（促成 D10）

```
FAILED tests/test_credentials_contract.py::UserStoreIsolationTests::test_the_effective_path_is_the_siblings_own_env_key
tests\test_credentials_contract.py:438: AssertionError
```
症状就是 D10 描述的那个：护栏在场时 `user_store.database_path()` 给的是改道目标，不是默认值。

### GREEN

```
$ python -m pytest tests/test_credentials_contract.py -q
57 passed, 1 warning, 17 subtests passed in 8.21s
$ python -m pytest -q                      # backend cwd
1018 passed, 37 warnings, 1018 subtests passed
$ cd /e/xiangmu/rag && python -m pytest backend/tests -q      # 仓库根 cwd
1018 passed, 37 warnings, 1018 subtests passed
```

### 变异自检（临时改代码 → 跑定向 → 逐字还原；无文件留下）

| 变异 | 目标 | 结果 |
| --- | --- | --- |
| A 写手回 False 也记成 `imported`（= 简报原写法） | D4 | **KILLED** 1 failed |
| B 去掉 64-hex 前置校验（移交②） | 导入即拒 | **KILLED** 4 failed |
| C 空 `credentials` 当成"没有工件" | D3 | **KILLED** 1 failed |
| D 导入时不置 `must_change` | §8.3 强制改密 | **KILLED** 2 failed |
| E 去掉 `only_missing` 跳过 | 不降级 | 第一次 **SURVIVED** → 补 `writer.call_count == 0` 钉子后 **KILLED** 1 failed |
| F 不挂写证据（撤 trace 回调） | 写改 red | **KILLED** 4 failed |
| G 归类做成恒 read | 写没人盯 | **KILLED** 4 failed |
| H 写标记做成 latch（每条写语句各升一次） | 一笔连接=一笔事故 | 第一次 **SURVIVED** → 改用 `record_login_failure(max_attempts=1)`（同一条连接两条 UPDATE）后 **KILLED** 1 failed |
| I 会话 fixture 不装凭据面闸（= 移交①没做） | 接线 | **KILLED** 2 failed |
| J 去掉 `guarded_store_connect` 开头的 pending 预清 | 防御分支 | **SURVIVED**（用例构造不到那个形状，见 concerns） |
| K 位置对不上时静默返回（不另记一笔） | 防御分支 | **SURVIVED**（同上） |

E/H 两轮的处理方式值得写下来：**没有把变异判成"可接受"**，而是各补一枚能把方向钉死的断言——E 缺的是"根本不试这条写"（今天两种实现都靠 SQL 兜住不降级，`import_legacy_digest` 哪天改成 UPSERT 才分道），H 缺的是一条"同一连接多条写语句"的真形状（我第一版误用了 `max_attempts=5`，那条 lock UPDATE 根本没跑，测试在空转）。

---

## 4. 四条移交的状态

**① 给新表接上会话护栏 — DONE。**
`LedgerGuard.install_credential_store(user_store)` 装在会话 fixture 里，与账本**同一个改道目标**（§6.1 同库要求由测试面兑现，`CredentialGuardWiringTests` 里钉成 `effective_credential_path() == effective_ledger_path()`），但**另一个实例**（各记各的 records），于是判红消息与终端汇总说得出是哪张表：钩子新增第二段专门给凭据面，修法是"每例一份临时库"，账本那段文案逐字未动。归类机制与账本不同形是形状决定的：`user_store` 没有 `_execute` 那种写收口，读腿与写腿都直接 `_connect()` ⇒ 先记 read、由 sqlite `set_trace_callback` 回传的语句（含 `CREATE TABLE`）把那一笔**升**成 write；升不上位置时改记一笔而不是静默（fail-closed）。为什么不做"函数名清单"：加一条写腿就得记得回来加名字，忘了的那一次是静默的。证据 = 变异 F/G/H/I 全 KILLED。

**② 导入前预校验 — DONE。**
`read_artifact` 承担全部形态判定：64-hex（小写归一）、顶层键封闭、出处两键非空、`credentials` 非空、用户名不许空白/带首尾空格。`import_legacy_digest` 继续不校验（分工不变）。脏 digest 的症状位置由"那个人的第一次登录被读成口令错"改成"导入这一步整份拒、库里零行"。证据 = 变异 B（KILLED，4 枚用例）+ `test_an_unreadable_shape_is_rejected_before_any_row_is_written` 里的 `count_by_algorithm() == {}` 与 `get_record("admin") is None`。

**③ 0 字节文件的残余 — DONE。**
`user_store._connect()` 的 `mkdir` + 打开文件发生在**被改道之后**的路径上，所以那个落点整体进了临时库。两面各有一钉：hermetic 的 `CredentialStoreGuardTests` 在纯读/真写/DDL 三种形状后都断言 `assertFalse(self.protected_db.exists())`（那份"假真库"一个字节都不许多）；会话级的 `test_a_credential_connect_under_a_cleared_env_cannot_touch_the_real_databases` 用 (是否在场, 表清单) 前后相等钉两枚真库——刻意不取 mtime/size，因为 dev 后端可能正往同一份库里写会话行，那种正常活动不该被读成测试事故。清空 env 下的这次真实改道（`credential_write_redirects() == []` + 两枚真库 `user_credentials present=False`）就是任务书要求的现场证据，已抄在文件开头。

**④ 不许把 `CredentialStoreError` 翻成认证结果 — DONE。**
`import_from_artifact` 不 catch 任何存储异常（文档字符串第 3 点写明为什么），报告面也没有任何能表达"口令错了"的字段；写失败不是 `skipped` 的取值之一（`skipped` 只有两种来源：`only_missing` 命中已存在行、写手回 False）。钉 = `test_a_store_incident_stays_a_store_incident`（原样逃出 + 不是 `MigrationArtifactError` + 不是 `CredentialConfigError` + 消息无 digest + 零行）。顺带：D4 把"写手回 False"从静默的 `imported` 里救出来，那是同一枚硬币的另一面（台账数字必须等于实际行数）。

---

## 5. 文件清单

| 文件 | 动作 | 行数/大小 |
| --- | --- | --- |
| `backend/app/credentials_migration.py` | 新建 | 193 行，LF ✅ |
| `backend/data/legacy_credentials.json` | 新建（升级工件；`.gitignore:7` 覆盖 ⇒ 不进 tracked 扫描；Task 10 closure 删） | 5 条，LF ✅ |
| `backend/tests/conftest.py` | 修改（+308 / −23；护栏第二面、`_WRITE_STATEMENT`、`_PendingRedirect`、5 枚公开口径、钩子第二段、汇总分节） | 689 行，LF ✅ |
| `backend/tests/test_credentials_contract.py` | 修改（605 → 1081 行；+22 用例，1 枚既有用例改读 `RAW_DATABASE_PATH`） | LF ✅ |
| `.superpowers/sdd/SECURITY_A_PLAN/snap-task3-app/`、`snap-task3-legacy-artifact.json`、`snap-task3-test.py`、`snap-task3-conftest.py` | 快照（Step 6；无 commit） | — |
| `.superpowers/sdd/SECURITY_A_PLAN/progress.md` | 台账追加（1 条 implementer 记录 + 5 条 Ruling + 1 条 deferred minor + 变异自检） | — |

未触碰：`backend/app/auth.py`、`app/llm/`（含 `usage.py`）、`app/rag.py`、`app/conversation_agent.py`、`app/security.py`、`test_llm_egress_guard.py` 的 D6 豁免计数。字节校验：

```
app/credentials_migration.py LF 9303      → 193 行
tests/conftest.py            LF 37156     → 689 行
tests/test_credentials_contract.py LF 59028 → 1081 行
data/legacy_credentials.json LF 523
```

工作树：`git status --short` 只有本任务的 4 项 + Task 1/2 的既有未跟踪项；`ls backend/app | grep -c tmp` → **0**；`backend/data/` 内除工件外无新增文件。全程未跑任何 git 写命令。

---

## 6. 自审发现（读自己的 diff，逐条）

1. **`raise ... from exc` 的选择核对过。** 我一开始把 JSON 失败改成 `from None`，理由是"异常消息会回显内容"——查证后是错的：`JSONDecodeError.__str__` 只有 `msg + 行列偏移`，不回显文档体。已改回简报的 `from exc`，并把核对结论写进注释（定位能力不丢、digest 一个字节也不进日志面）。
2. **删掉了一处不可达判定。** `if not isinstance(username, str)` 在 `json.loads` 的字典键上是死码（键必为 str）。这与 Task 1 被抓过的那条同族（"拒大写却仍 `.lower()`"），改成只判空白 + 注释写明"键必为 str"的前提。`digest` 那枚 `isinstance` 保留：JSON 的值确实可以是列表/数字，简报的 `credentials: ["admin"]` 就是这条的活样本。
3. **消息文案与 `subject`/`label` 参数化**：账本面的 warning/汇总文本逐字未变（默认参即原字面量）；凭据面走 `[credential-guard]` + "真实凭据表"。汇总函数 `_report_redirects` 是两面向共用的同一份口径，只是被点名的表不同。
4. **`_PendingRedirect.done` 的必要性**被写成断言（H 变异）而不只是注释：一条连接多条写语句 ⇒ 一笔事故只记一笔，"这一例写了几笔"仍等于"它碰了几条真库连接"。
5. **用例之间不共享状态**：`CredentialStoreGuardTests` 五枚各自 `tempfile.TemporaryDirectory()` + `addCleanup(guard.uninstall)`，且写只落在自建护栏实例的 records 上（会话那份始终空——`credential_write_redirects() == []` 在同一份文件里、跑在它们之后仍然成立，这条链是真的被走过一遍而不是被断言出来的）。
6. **注释里的时间线词**清过一轮：`"Task 3 起这一层包两个模块"` → `"这一层现在包两个模块"`，小节标题去掉 `（SEC-A Task 3）`；留下的 `N1 / I-2 / Task 2 移交` 一类是与本文件既有风格同形的判据出处标记。
7. **简报里那两处 100+ 字符的行没动**（`test_reimporting_does_not_downgrade_an_already_upgraded_row` 的两行），保持 verbatim；自己新写的行都收在 100 以内。仓库无 flake8/ruff 配置，只有这个作为软上限的既有用例风格。
8. **`conftest` 现在会在会话启动时 import `app.user_store`**（→ `app.credentials` → argon2 dummy hash）。实测全套件时长 +约 0.1s，无副作用；这也是"凭据表与账本同库"这件事在测试面的物理前提。

## 7. Concerns（要不要在下一轮处理，请评审判断）

1. **`LEGACY_INPUT_PATH` 是相对路径** ⇒ 迁移是否命中工件取决于进程 cwd。这与库默认值同口径（D7 给了不改的理由），但 Task 5 的启动编排要么保证后端 cwd，要么显式把绝对路径传给 `import_from_artifact(path=...)`。**没有**在这一步改成 `Path(__file__).parent.parent / ...`：那是简报点名的接口值，且改了会让"升级输入"与"库文件"两者解析口径分叉。
2. **本模块不建表**（文档字符串第 1 点写明）⇒ Task 5/7 必须在 `import_from_artifact()` 之前调 `user_store.ensure_user_credentials_schema()`，否则症状是 `sqlite3.OperationalError: no such table`。这是刻意的（建表唯一出处只有一处），但它是跨任务的前置条件，写在这里以免 Task 5 照简报漏掉。
3. **导入中途出存储事故时，已落的行保留**（简报未要求整批回滚；写手每行一个事务是 Task 2 已评审的提交边界，迁移器无权跨越）。缓解 = `only_missing=True` 的重跑幂等（干跑已验证）。若评审希望"整份工件原子导入"，那需要 `user_store` 开一个批量写入口，属 Task 5/7 的范围扩张。
4. **两枚防御分支无用例覆盖**（变异 J/K 存活）：pending 预清、位置对不上时改记一笔。都要靠"先直接叫 `database_path()`、再把 `database_path` 打桩成非保护路径然后连接"这种人为主义才能构造；两枚的失败方向都是**过判红**而不是静默放过，所以按 fail-closed 处理留在原样。
5. **`warn_on_read=False` 这条显示层选择不设钉**：真要钉只能白盒断言会话实例属性（自证式），我判断不值。副作用是凭据面的读改道在**用例进行中**完全静默，只在收尾汇总里出现。
6. **`Artifact 与 `auth.USERS` 的一致性没有常驻钉**：closure（Task 10）会删工件、Task 5 会删 `auth.USERS`，任何一条静态断言都会在其中一个动作之后变红，所以 Step 1 的等值复算是**一次性**做的（结果抄在 §1 与台账）。SECA-04 的"0 命中"扫描只数 digest 是否存在，抄错 digest 它读不出来——这条风险由正则生成 + 复算压掉，但**没有**留下可重跑的机器判据。若评审希望留一枚，最合适的位置是 Task 10 的验收台（那时两边都还在场）。

---
---

## 11. 修复轮 1 — 评审 5 枚 Important + 7 枚 Minor/Major 的逐条落点

状态：**全部 ADDRESSED**（I1–I5、M1、M2-J/K、M3、M4、M5、M7、M8）。定向 **68 passed / 35 subtests / 0 warning**，全套件两 cwd 相等 **1029 passed / 36 warnings / 1036 subtests**。§7 的第 4、5 两条 concerns 本轮被钉子取代（见 §11.4 与 §11.7）。

### 11.1 逐条：改了什么 + 谁钉它

|  finding | 改动 | 覆盖用例 |
| --- | --- | --- |
| **I1** 调用方扫描漏裸导入形状 | `test_only_the_migration_module_may_call_the_legacy_writer` 改成按名字解析：新增 `_writer_bindings`（`import` / `from … import` / 相对 level / 别名 / `import *` 五侧全收）+ `_legacy_writer_calls`（裸名调用、模块别名属性调用、来源查不到的接收者一律算调用=fail-closed）+ `_legacy_writer_callers`（**按 `path.relative_to(BACKEND_DIR)` 的 posix 路径报**，子包里同名模块不再塌成一条）。样本表 `WRITER_SHAPES` 7 种正绑法、`NON_WRITER_SHAPES` 4 种反向 | `test_only_the_migration_module_may_call_the_legacy_writer`（期望值改为 `{"app/credentials_migration.py"}`）+ 新增 `test_every_writer_binding_shape_is_counted_as_a_caller`（7 subtests）+ `test_a_similar_shape_stays_out_of_the_caller_set`（4 subtests） |
| **I2** 护栏可被静默解除且无人复验 | `isolated_llm_ledger` 的 `finally` 在 `credential_guard.uninstall()` **之前**复验两件事：`credential_guard_is_active()` 仍为真、`credential_row_growth()` 为空；任一不成立 ⇒ `raise AssertionError`（会话级 autouse teardown 里抛 ⇒ 整场 error、退出码非 0）。文件头"第二张表"节补了这段理由 | 由 §11.3 的临时探针现场证明（reload 形状：修前 exit 0 全绿，修后 1 error / exit 1） |
| **I3** 逐例归责分支从未被执行 | 新类 `SessionAttributionHookTests`：手工推进那枚生成器（`__wrapped__` 取未装饰的函数），过 yield → append 假写 → `hook.send(None)`。两枚 `before` 的**取值差异**由"往另一张表的 records 放一笔诱导读"制造，否则定向跑里两枚计数都是 0、复用也测不出 | `test_a_credential_write_redirect_blames_the_offending_test`（消息含 凭据 + `_CredentialDbPerTest`、不含 账本）、`test_a_ledger_write_redirect_blames_the_offending_test`（含 账本 + usage、不含 凭据）、`test_a_write_recorded_before_the_test_started_is_not_blamed_on_it`（两张表各一遍：起点之前的假笔不许判红） |
| **I4** 默认输入路径可静默零行 | `reason` 在**默认路径且不在场**时追加 `（默认路径按当前工作目录解析为 {path.resolve()}）`；`LEGACY_INPUT_PATH` 的理由块改为"只在 `CONVERSATION_DB_PATH` 未设或给相对值时同生同死"；绝对路径义务写进 `import_from_artifact` 文档字符串第 1 点（与不建表那条前置条件并排）。`LEGACY_INPUT_PATH` 未移动 | `test_the_default_input_path_reports_where_it_actually_looked`（chdir 到空目录跑默认路径 ⇒ reason 含解析结果；显式传路径时不含） |
| **I5** 真库哨兵会假红 | 会话 fixture 在**装闸之前**拍 `_SESSION_START_CREDENTIAL_ROWS = real_user_credential_row_counts()`；新增两枚公开口径 `credential_row_counts_at_session_start()` / `credential_row_growth()`（只报涨了的库，起点缺失按 0 起算=退化方向仍是过判红）。哨兵的 `assertIn(rows, (0, None))` 换成 `assertEqual({}, credential_row_growth())`，`credential_write_redirects() == []` 那半枚原样保留 | `test_no_test_in_this_session_wrote_a_credential_row_into_a_real_database`（+ 一枚"起点快照在场"的前提钉）与 `test_the_growth_rule_is_measured_against_the_session_baseline`（起点 5/现在 5 不涨、现在 6 涨 1、无起点按 0） |
| **M1** 定向跑多出的那 1 枚 warning | `test_the_credential_table_resolves_to_the_same_file_as_the_ledger` 里 `effective_ledger_path()` 包进 `warnings.catch_warnings()` + `simplefilter("ignore", RuntimeWarning)`。**没有**把它挪出 patch 块：宿主把 `CONVERSATION_DB_PATH` 指到保护集外（CI 常见形态）时，"块外取账本 / 块内取凭据"会两侧不同源、假红；块内同条件取才是这条钉子本来的意思。全仓无任何用例断言这枚 warning（已 grep 核实），口径仍由 `read_redirects()` 与收尾汇总负责 | 定向计数即证据：warning 1 → 0（§11.2） |
| **M2-J** pending 预清 | 保留 + 写明"按今天的执行顺序够不到（变异复验：删掉它定向 68 全绿、再连两套护栏依赖件共 561 全绿）"，并写清它挡的是哪种接缝换形、为何刻意不设用例、也不许当死码删 | 无（刻意） |
| **M2-K** 位置对不上时另记一笔 | 文档字符串补"按构造够不到、**刻意不设用例**、不许拿覆盖率改成静默 `return`" | 无（刻意） |
| **M3** 两枚零调用点口径 | 都留下并给了消费者：`test_a_credential_read_is_reported_only_after_its_kind_has_settled` 同时断言"用例进行中凭据面不发提醒"与"这一笔进了 `credential_redirects()` / `credential_read_redirects()` 各 +1"。顺带把 §7.5 那条"显示层选择不设钉"结掉 | 同上（新用例） |
| **M4** 两态都接受的断言 | 删掉 `assertIn(columns, ([], list(user_store._COLUMNS)))`，改为：先绕开护栏接缝把表建到**改道目标**里（否则两侧都是空结构，等式空转），再 ① `assertEqual(list(_COLUMNS), columns)` ② `assertTrue(redirected.is_file())` ③ `assertEqual(self._columns_in(redirected), columns)`（新 helper 以只读 URI 直接点读那份文件）④ 原有前后快照不动 | 同一枚用例；变异"交叉核对指向另一份文件"= KILLED（§11.4） |
| **M5** `RAW_DATABASE_PATH` 的前提 | 新增两枚属性钉：`__module__ == "app.user_store"`、`__qualname__ == "database_path"`（护栏的 bound method 两枚都不符） | `CredentialGuardWiringTests::test_raw_database_path_is_the_unguarded_function` |
| **M7** 读不出来的分类 | `read_artifact` 拆成两次 try：`except (OSError, UnicodeDecodeError)` ⇒ `MigrationArtifactError` 且消息点名路径（内容里可能有 digest，故不回显内容）；JSON 那条仍 `from exc`。另把 `{"credentials": null}` 与"没有 credentials 键"分成两条消息 | `test_an_artifact_that_cannot_be_read_is_rejected_like_a_malformed_one`（目录 / GBK / UTF-16 三种）+ `test_a_null_credentials_field_is_not_reported_as_an_absent_one` |
| **M8** 注释叙述简报/台账 | `MigrationPathTests` 的夹具说明改为指向 `_CredentialDbPerTest` 的理由块（不再引简报与台账）；`test_the_restricted_legacy_writer_goes_through_the_same_seam` 标题去掉"Task 3 是第一个消费者"；`import_from_artifact` 文档第 1 点去掉"Task 2 的裁定"。**未动**评审点名为 house style 的 `Task 7 评审 Minor-1`（conftest 三处）与 `Task 2 移交…` 系列标记，也未动那两条 raise 消息 | — |

字节与行尾：`app/credentials_migration.py`、`tests/conftest.py`、`tests/test_credentials_contract.py` 均 **LF、CRLF=0**；工件 `data/legacy_credentials.json` 与快照 `diff` 为空（五枚 digest 未动）。

### 11.2 四条命令与实测输出

```
$ cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q
68 passed, 35 subtests passed in 5.11s                     # 定向：warning 1 → 0
$ cd /e/xiangmu/rag/backend && python -m pytest tests/test_llm_usage_contract.py \
      tests/test_llm_egress_guard.py tests/test_model_router_v23_contract.py -q
528 passed, 23 warnings, 485 subtests passed in 42.20s     # 与本轮开始前逐字相同
$ cd /e/xiangmu/rag/backend && python -m pytest -q
1029 passed, 36 warnings, 1036 subtests passed in 105.91s (0:01:45)
$ cd /e/xiangmu/rag && python -m pytest backend/tests -q
1029 passed, 36 warnings, 1036 subtests passed in 122.04s (0:02:02)
```

计数变化：+11 用例（57→68）、+18 subtests（17→35）、warning 37→**36**（回到进入本任务前的基线）。两 cwd 相等 ✅。

全套件跑完之后（只读 URI）：

```
E:\xiangmu\rag\backend\data\conversations.db
  exists=True size=57344
  tables=('conversations','llm_request_logs','message_sources','messages','sqlite_sequence')
  user_credentials present=False rows=None
E:\xiangmu\rag\data\conversations.db
  exists=True size=40960
  tables=('conversations','message_sources','messages','sqlite_sequence')
  user_credentials present=False rows=None      # 两份库与本轮开始前同尺寸
# `credential_write_redirects() == []` 由会话内那枚哨兵当场断言（定向与全套件均绿），不在进程外复算。
```

### 11.3 I1 / I2 的现场证据（临时探针，跑完即删）

**I1 —— 三种绑法下"新扫描红、旧扫描看不见"**（探针文件 `backend/app/i1_shape_probe.py`，跑完 `unlink`）：

```
--- shape A 裸导入 + 裸调用（from app.user_store import import_legacy_digest / import_legacy_digest(...)）
    PRE-FIX scan callers: ['credentials_migration.py']            # 旧口径看不见
    FIXED scan: 1 failed | AssertionError: Items in the second set … 'app/i1_shape_probe.py'
--- shape B 裸导入起别名 + 裸调用（… as put / put(...)）
    PRE-FIX scan callers: ['credentials_migration.py']            # 旧口径看不见
    FIXED scan: 1 failed | … 'app/i1_shape_probe.py'
--- shape C 模块别名 + 属性调用（from app import user_store as store / store.import_legacy_digest(...)）
    PRE-FIX scan callers: ['credentials_migration.py', 'i1_shape_probe.py']   # 旧口径本来也认得
    FIXED scan: 1 failed | … 'app/i1_shape_probe.py'              # 新口径不退化
probe removed: True
```

**I2 —— 中途 `importlib.reload(user_store)`（简报点名的夹具形状）**，同一枚探针分别在"收尾复验摘掉/在场"两种 conftest 下跑（字节替换 + sha1 核对，发内还原）：

```
=== PRE-FIX teardown (checks removed):  exit=0  1 passed in 0.15s          # 陷阱是活的
=== POST-FIX teardown (checks in place): exit=1 1 passed, 1 error in 0.58s
    __ ERROR at teardown of test_a_brief_shaped_fixture_reloads_the_store_module __
    E  AssertionError: 会话结束时凭据面的两道闸已不在 `app.user_store` 上：中途有夹具 reload 过
       这个模块（`importlib.reload` 把 `database_path`/`_connect` 换回裸函数 = 护栏静默解除…）
    tests\conftest.py:658: AssertionError
restored sha ok: True | probe removed: True
```

第二枚（收尾的行数增长复验）用一份伪造起点快照触发，证明它不是装饰：

```
=== I2 收尾行数复验: exit 1        1 passed, 1 error in 0.69s
    E  AssertionError: 会话期间真实库里的凭据行变多了（SECA-04 的台账会被这几行污染）…
    tests\conftest.py:664: AssertionError          probe removed: True
```

### 11.4 变异复跑（字节安全：读字节 / 替换 / 跑定向 / 还原 / sha1 核对，发内还原，不留文件）

| 变异 | 目标 | 结果 |
| --- | --- | --- |
| I1 三形状探针（A/B/C 各一发，见 §11.3） | 扫描按名字解析 | **KILLED**（三发全红，红的是相对路径名）；A/B 同时证明旧口径漏判 |
| I3-a 凭据分支复用账本的 `before` | I3 | **KILLED** 1 failed |
| I3-b 凭据分支切片起点做成 0 | I3 | **KILLED** 1 failed |
| I3-c 账本分支切片起点做成 0 | I3 | **KILLED** 1 failed |
| I3-d 账本分支起点取错表（+1） | I3 | **KILLED** 1 failed |
| I5 会话起点不拍快照 | I5 | **KILLED** 1 failed（`assertIn(…, baseline)`） |
| I5b 增长判据把起点当 0 | I5 | **KILLED** 1 failed（`test_the_growth_rule_…`） |
| I4 默认路径没命中时不报解析位置 | I4 | **KILLED** 1 failed |
| M7 读不出来只认 `UnicodeDecodeError` | M7 | **KILLED** 1 failed（目录那一例先红） |
| M7b null credentials 与缺字段同文案 | M7 | **KILLED** 1 failed |
| M4 交叉核对指向另一份文件 | M4 | **KILLED** 1 failed |
| J 去掉 `guarded_store_connect` 开头的 pending 预清 | M2-J | **SURVIVED**（定向 68 全绿；连上另两套护栏件共 561 全绿）⇒ 按评审口径**保留代码 + 写明够不到的理由**，不造人为用例 |
| K 位置对不上时静默返回 | M2-K | 上轮即 **SURVIVED**；本轮按要求只补文档（够不到 + 刻意不设用例） |

十发新变异全 KILLED；J/K 按评审裁定保持"有用但没有用例"，理由已写进代码。

### 11.5 §5 字节数校正（上一版记的是"更早一次编辑"的值，行数当时就是对的）

| 文件 | 本轮开始前（快照实测） | §5 原记 | 本轮交付 |
| --- | --- | --- | --- |
| `backend/app/credentials_migration.py` | LF 9484 / 193 行 | ~~9303~~ | LF **11698 / 217 行** sha1 `caa52bcaf5d9` |
| `backend/tests/conftest.py` | LF 38599 / 689 行 | ~~37156~~ | LF **43204 / 751 行** sha1 `aed5f905c329` |
| `backend/tests/test_credentials_contract.py` | LF 59387 / 1081 行 | ~~59028~~ | LF **82160 / 1442 行** sha1 `6f5a82266ecd` |
| `backend/data/legacy_credentials.json` | LF 523 / 11 行 | 523 ✅ | LF **523 / 11 行** sha1 `19cc628acbae`（与快照 `diff` 为空） |

本轮净增：迁移器 +24 行、conftest +62 行、测试 +361 行（11 枚新用例 + 18 枚 subtests + 三张样本表）。其余文件未动：`git status --short` 只多不减（`app/config.py`、`requirements.txt` 是 Task 1/2 的既有改动），untouchables 的 diff 为空；`ls backend/app | grep -c tmp` → **0**；无 probe/scratch 文件；全程未跑任何 git 写命令。

### 11.6 本轮的三条范围判断（不改，供评审复核）

1. `credential_write_redirects() == []` 那半枚哨兵按评审要求**原样保留**（写改道仍是一笔都不许多），只有"真库行数"那半枚换成"会话期间不增长"。
2. conftest 的两条 raise 消息与 `credentials_migration.py:196` 的"（Task 7 的 CLI 直接打印它）"带任务/移交字样：前者不在 M8 点名的三处之内、后者是跨任务前置条件的说明，都按 house style 留着；若评审判定它们也算叙述式注释，下轮一并改。
3. M4 的那枚用例现在会往**会话临时库**里建一次 `user_credentials` 表（0 行、绕开护栏接缝，故不记改道）。它让交叉核对从"两侧都可能空"变成一定有表；代价是"会话库里没有凭据表"这类断言以后不能写。

### 11.7 新钉住的不变量（供后续任务引用）

- **`app/user_store.import_legacy_digest` 的唯一调用方按"解析后的名字"计**，`from app.user_store import …` / 别名 / 相对导入 / `import *` 这些绑法都在扫描面上；调用方以 `backend/` 相对路径报告。
- **会话结束时的凭据面契约**：两道闸仍在 `app.user_store` 上，且真库 `user_credentials` 行数不低于会话起点。⇒ 任何夹具想用 `importlib.reload(user_store)` 换库都会把整场运行判 error；换库的唯一口径是 `CONVERSATION_DB_PATH`。
- **dev bootstrap 兼容**：`credentials bootstrap-admin` 在 `backend/data/conversations.db` 里留下的行不再是测试事故（起点快照吸收），但会话内新增一行当场红。
- **`warn_on_read=False` 已被设钉**：凭据面在用例进行中静默，提醒只从定型后的两枚口径与收尾汇总出来。
- **归责钩子本身有用例**：两张表的"写改道 ⇒ 本例红 + 各说各的表 + 只算本例窗口"三条都成了可红的事实。
- **`reason` 的可观测面**：默认输入路径没命中时，`MigrationReport.reason` 含解析后的绝对路径 ⇒ Task 7 的 CLI 打印它时，路径分叉与"全新安装"两种状态可分。

---

报告路径：`E:\xiangmu\rag\.superpowers\sdd\SECURITY_A_PLAN\task-3-report.md`

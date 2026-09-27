# Task 10c 报告 — `credentials migrate`（legacy 导入的生产入口）

STATUS: PARTIAL（进行中，持续追加）

## 0. 范围与读过的权威面

- 简报：`.superpowers/sdd/SECURITY_A_PLAN/task-10c-brief.md`
- 规格：`docs/SECURITY_A_SPECIFICATION.md` §11（`migrate` 四规则）、§8.2 表、§8.5、§8.6、
  §20.5（裁定来由：为何"运维显式"而非"lifespan 接线"）、§4 SEC-A-002/004、§15.1 第 6 步
- 代码：`backend/app/cli.py`、`backend/app/credentials_migration.py`、`backend/app/user_store.py`
- 夹具/手法参照：`backend/tests/test_credentials_contract.py`（`_CredentialDbPerTest`、
  `MigrationPathTests._artifact/_valid`）、`backend/tests/test_password_lifecycle_contract.py::CliTests`
  （`_run_cli` 形状、`mock.patch.object(config_module.settings, "security_enterprise_mode", ...)`）、
  `backend/tests/test_secret_hygiene_contract.py::StartupGuardLifespanTests`
  （`TestClient(app)` 只有进上下文管理器才跑 lifespan）

## 1. 基线（改前）焦点门

命令：`cd backend && python -m pytest tests/test_credentials_contract.py -q`

```
.......................................................................                                       [100%]
71 passed, 35 subtests passed in 6.22s
```

行尾测量（写前）：`backend/app/cli.py` CRLF=0 / LF=172、以换行结尾 ⇒ **LF-native**，本次编辑保持 LF。

## 2. 计划落地的形状（写码前先定）

- `build_parser()` 里 `credentials` 下加 `migrate` 子解析器，**不带任何参数**（口令不进 argv，也不新增开关）。
- `main()` 在 `ensure_user_credentials_schema()` **之前**分派 `migrate` ⇒ 企业形态连一次 DDL 都不发。
- `_run_migration()`：企业形态拒（rc 2，一行不写）→ 建表 → `import_from_artifact()`（默认
  `only_missing=True`，不覆写）→ 逐字段打印 `artifact_present / imported / skipped / reason` → rc 0。
- 退出码表（沿用本文件既有分类：0 成功、1 存储事故、2 运维输入/形态拒、3 开发期缺陷）：
  成功与"工件不在场"⇒ 0；企业形态 ⇒ 2；`CredentialStoreError` ⇒ 1；`MigrationArtifactError` ⇒ 2（见 §5 记录）。
- 输出行格式（`-` 表示该格无值，口径同 `_print_status`）：
  `artifact_present=True` / `imported=2 admin,sales01` / `skipped=0 -` / `reason=-`

## 3. TDD 证据

### 3.1 RED（先写用例，`cli.py` 未改）

命令：`cd backend && python -m pytest tests/test_credentials_contract.py::LegacyImportCliTests -q`

关键失败输出（节选）：

```
>           raise ArgumentError(action, msg % args)
E           argparse.ArgumentError: argument action: invalid choice: 'migrate'
                        (choose from bootstrap-admin, reset, migration-status)
E           SystemExit: 2
E           AttributeError: module 'app.cli' has no attribute 'settings'
9 failed
```

第一轮 RED 里夹了一发**夹具自己的 bug**（`_with_artifact_at_default_path` 忘了 `mkdir` 出
`data/`）：`FileNotFoundError: 'data\\legacy_credentials.json'`。先修夹具再取真实 RED——
留着那发会把"入口不存在"的证据污染成"测试跑不起来"。

`test_starting_the_app_never_consumes_the_upgrade_artifact` **改前就绿**（今天的启动路径本来
不导入）。它是 §20.5 裁定那一半的**回归钉**，不是本任务的新行为；这一条是刻意的：它的价值在于
将来有人往 lifespan 里接 `import_from_artifact()` 时把它判红，所以它必须在实现前后都绿。
其余 8 条全部 RED → 实现 → GREEN。

### 3.2 实现

`backend/app/cli.py`（+58/-4 量级，LF 保持）：

1. `build_parser()` 加 `migrate` 子解析器，**零参数**。旁边一行注释说明为什么没有 `--path` /
   `--password` / `--force`：每多一枚开关就多一条能把已收敛账号写回 legacy 的路。
2. `main()` 在 `ensure_user_credentials_schema()` **之前**分派 `migrate` ⇒ 企业形态连一次 DDL
   都不发（`_connect()` 一被叫到就 mkdir + 建库文件）。其余三个动作的建表位置一字未动。
3. 新增 `_migrate_legacy_artifact()`：企业形态拒（rc 2，一行不写）→ 建表 →
   `credentials_migration.import_from_artifact()`（默认 `only_missing=True`，未做任何"改进"）→
   逐字段打印 → rc 0。异常面两格：`CredentialStoreError` ⇒ 1、`MigrationArtifactError` ⇒ 2，
   都只 `print(str(exc), file=sys.stderr)`（这两个模块的消息本身只带用户名与路径）。
4. 输出形状（`-` = 该格无值，口径抄 `_print_status`）：
   ```
   artifact_present=True
   imported=2 admin,sales01
   skipped=0 -
   reason=-
   ```
5. 模块 docstring 补一段 `migrate`（为什么"绝不自动导入"是 M19/SECA-04b 的活口）；
   `_MUST_CHANGE_BY_ACTION` 那条守卫的注释同步改成"第三条**口令**腿"，免得下一个人以为
   `migrate` 漏登记了意图表。

### 3.3 GREEN

命令与输出集中在 §8（含运维面实物两格）。

## 4. 用例清单（新增 `LegacyImportCliTests`，9 枚，全部按 CLI 行为判）

| 用例 | 钉的规格格 | 判红的方向 |
| --- | --- | --- |
| `test_dev_import_lands_legacy_rows_and_prints_the_four_fields` | §11 规则 1 | 有工件 ⇒ rc 0、四字段逐格、行是 legacy 且 `must_change=1`，再用 `migration-status` 闭环 |
| `test_an_absent_artifact_is_a_legal_steady_state_and_still_exits_zero` | §11 规则 1 | 无工件被判成非零/往 stderr 说话 ⇒ 红（合法缺席输入不得变事故） |
| `test_enterprise_mode_refuses_the_import_and_writes_not_a_single_row` | §11 规则 2 / §8.5 | 企业形态导了任何一行、或把已有 argon2id 行动了 ⇒ 红 |
| `test_the_enterprise_refusal_does_not_even_create_the_database_file` | §11 规则 2 的"before any write" | 把拒检查挪到建表之后 ⇒ 红（上一条测不到这一格） |
| `test_running_it_twice_imports_nothing_and_never_downgrades_a_converged_row` | §11 规则 3 | 第二次 `imported>0`、或写手被叫到（`call_count != 0`）⇒ 红 |
| `test_starting_the_app_never_consumes_the_upgrade_artifact` | §11 规则 1 的另一半 / §20.5 | lifespan 里接导入 ⇒ 红；并留 `warmup.*.called` 证明 lifespan 真跑过 |
| `test_the_migrate_face_carries_no_credential_material_and_reads_no_password` | §11 规则 4 / SEC-A-002 | 打印摘要/前缀/任意 ≥16 位 hex、读走或弹掉口令 env、argv 多一枚参数 ⇒ 红 |
| `test_a_store_incident_exits_nonzero_without_becoming_a_digest_face` | §11 规则 3（存储事故） | 事故被咽成 `skipped` 或 rc 0 ⇒ 红 |
| `test_a_malformed_artifact_is_refused_as_a_whole_before_any_row_lands` | 整份拒的 CLI 面（规格未点名，见 §5-D3） | 半导（写了几行再报错）、或裸栈出去 ⇒ 红 |

夹具复用：把 `_artifact()` / `_valid()` 从 `MigrationPathTests` **原样**提到新的
`_ArtifactFixtures(_CredentialDbPerTest)` 基类（含 `MigrationPathTests` 的类头一行），新类
`LegacyImportCliTests` 继承同一份，另加两枚默认路径助手（`_with_artifact_at_default_path` /
`_standing_where_the_default_path_is_empty`）。没有第二套"什么算合法工件"的真源；`MigrationPathTests`
既有的 13 条用例与断言一字未改（只换基类那一行 + 类 docstring 里的夹具名）。

## 5. 记录在案的决定与偏差

- **D1 输出形状**：四字段各一行，`-` 表示该格无值（口径抄 `_print_status`），计数与用户名同一行
  （`imported=2 admin,sales01`）。简报要的是"逐字段、可归档"，没给格式；这一版既能 `grep`
  又能直接贴进验收文档。
- **D2 企业形态 rc = 2**：简报写"非零退出（与 `bootstrap-admin` 那格 rc=2 的既有形状一致）"，
  按字面取 2 = 本文件的"拒绝"类。
- **D3 `MigrationArtifactError` ⇒ rc 2（规格未点名这一格）**：§11 四条规则讲的是"工件**不在场**"，
  没有讲"工件在场但整份读不得"。不拦就是裸栈 + 进程退出 1，两个后果都不好：与"存储事故 ⇒ 1"
  撞成同一类（运维会以为盘出了问题），且给的人是一截 traceback。取 2（与"身份不存在""口令不合格"
  同一类"运维一次能修完"的拒绝）、消息原样转 stderr、库里零行。**这是本任务唯一一处规格留白
  由实现填的格子**，改成别的取值只需动 `_migrate_legacy_artifact()` 里两行 + 一条断言。
- **D4 不写审计事件**：`migrate` 没有调 `record_event`。§11 给这件事的凭据面是"退出码 + 可归档
  输出 + 明确的 actor"，§8.6 又写明 CLI 无独立 actor；口令类事件（`credential_bootstrap` /
  `password_reset_by_admin`）的枚举表在 §9.1 是闭合的，新造一枚 token 属于扩面。若收口方要求
  审计留痕，那需要先在 §9.1 加一枚枚举值——不在本任务权限内。
- **D5 `settings` 按模块顶 import**（`from app.config import settings`，口径同 `auth.py`），
  用例用 `mock.patch.object(cli.settings, "security_enterprise_mode", True)` 换属性——这与
  `test_user_directory_contract.py:83`、`test_authentication_leg_contract.py:930` 同一手法，
  不 reload、不换单例对象。
- **D6 没有新增开关 / 配置键 / 路径**：无 `--path`、无 `--force`、无新 env 键；输入位置仍是
  `credentials_migration.LEGACY_INPUT_PATH`，`only_missing` 用该函数自己的默认值（未显式传参，
  也就没有"哪天有人把它改成 False"的调用点）。
- **D7 提了一枚共享夹具基类**（唯一一处动到既有用例代码的地方）：`_artifact()` / `_valid()`
  逐字移到新的 `_ArtifactFixtures(_CredentialDbPerTest)`，`MigrationPathTests` 只换类头一行 +
  docstring 里的夹具名。13 条既有用例与断言、测试方法名一字未改；已核 `docs/SECURITY_A_PLAN.md`
  的变异表与 `conftest.py` 只按**类名**引用本文件（`Argon2ProfileTests` / `UserStoreSchemaTests` /
  `CentralisationScanTests` / `CredentialStoreGuardTests`），没有指向 `MigrationPathTests` 方法的
  node id，M19 的靶子是 `test_authentication_leg_contract.py::SourceRemovalTests`，不受影响。

## 6. 自审（读自己的 diff）

- **完整性**：§11 四规则 ⇒ 规则 1（成功/无工件 + 启动不自动导入）2 枚、规则 2（企业拒）2 枚、
  规则 3（幂等）1 枚 + 存储事故 1 枚、规则 4（不碰口令 / 不漏摘要）1 枚，另 1 枚整份拒；
  输出面（四字段）与 `migration-status` 闭环各有断言。✅
- **每条断言可杀性**（把实现逐处undo，看谁会红）：删企业检查 ⇒ 第 3/4 枚红；把检查挪到建表之后
  ⇒ 只有第 4 枚红（这就是它单独存在的理由）；`only_missing=False` ⇒ 第 5 枚的
  `writer.call_count == 0` 红（结果面同形，只有"试都不试"能分辨）；把无工件判成失败 ⇒ 第 2 枚红；
  往 lifespan 接导入 ⇒ 第 6 枚红；打印摘要 ⇒ 第 7 枚红。✅
- **是否过度建造**：新增 1 枚函数、1 枚文案常量、1 行子解析器；没有新抽象、没有新配置、
  没有"顺手"改 `credentials_migration.py` / `user_store.py` / `auth.py` / `main.py`
  （四者 diff 为空，已核）。注释密度与本文件既有风格一致，未引简报/Task 编号作理由（M8 口径）。✅
- **测试质量**：全部经 `cli.main(argv)` 真跑，捕获真 stdout/stderr；被测对象本身没被打桩
  ——`cli.settings` 那一枚是**输入面**（形态开关），`user_store.import_legacy_digest` 是**写手接缝**
  （`wraps=` 数调用次数 / `side_effect=` 造一次存储事故），两处的口径都与本文件既有用例相同。✅
- **凭据材料审计**：新写的文件里没有明文口令、没有那 5 枚 digest 字面量、没有像真钥匙的串；
  摘要一律 `"a" * 64` / `"b" * 64` / `"c" * 64`（沿用本文件既有写法），哨兵值拆成两段字面量。
  失败信息里比对的字段不含 `password_hash`（第 3 枚特意只比三元组）。✅
- **行尾**：`app/cli.py` CRLF=0 / LF=239、`tests/test_credentials_contract.py` CRLF=0 / LF=1739，
  均以换行结尾 ⇒ 与改前同为 LF-native，无幻影 diff。✅
- **`backend/data/` 未被写过**：所有工件都落在 `self._tmp` 里（靠 chdir 让默认相对路径命中）；
  手工 smoke 在 `mktemp -d` 里跑并已删。`tests/test_security_a_closure.py` 三条（含
  "closure 后工件不在场"）仍 3 passed；`ls backend/data` 无 `legacy_credentials.json`。✅
- **会话护栏**：焦点门退出码 0，凭据面**零笔写改道**（输出里那一行 `[ledger-guard]` 是既有的
  **读**改道提示，基线那次同样在，不是新现象）。✅

## 7. 疑虑

1. **cwd 耦合仍在**：`migrate` 读的是**相对**默认路径，只有当 `CONVERSATION_DB_PATH` 未设或给
   相对值时，"库在哪"与"工件在哪"才同生同死。该键给绝对路径时（容器/systemd，compose 就是
   这么挂库的）两者分叉，导入会零行退出——`reason` 会把解析后的绝对路径打出来（既有设计），
   运维看得见去哪儿找过。规格 §11 明写"读 `LEGACY_INPUT_PATH`（默认相对路径，行为与该模块既有
   约定一致）"，且要改这个分叉得动 `credentials_migration.py`（超出本任务允许面），所以**没有**
   加 `--path`、也没做绝对化解析。这条限制属于 §17 那一类"命名而非消除"。
2. **D3 那一格（畸形工件 rc=2）是我的裁量**，不是规格原文；若收口方另有偏好，改动面是两行。
3. **第 6 枚钉（启动不消费工件）把两个 warmup 换成了 MagicMock**，与 `StartupGuardLifespanTests`
   同形：它钉的是"启动这一段路上没有凭据写"，不是"整条 lifespan 的其它副作用"。它按**行数**判，
   所以将来无论从哪一步间接走到导入都会红；但如果有人的实现把导入接在**中间件**或某个路由的
   首次调用上，本钉测不到（那已经出 §11 这条规则的形状了）。
4. `migrate` 不写审计（D4），意味着"谁在什么时候导过"只有 shell 历史与归档输出可查。收口若
   要求留痕，需先扩 §9.1 枚举表。

## 8. GREEN 证据

命令与输出：

```
$ python -m pytest tests/test_credentials_contract.py::LegacyImportCliTests -q
.........                                                                [100%]
9 passed in 38.34s

$ python -m pytest tests/test_credentials_contract.py -q            # 焦点门（改后）
................................................................................                              [100%]
80 passed, 35 subtests passed in 44.16s                              # 基线 71 passed → 80 passed

$ python -m pytest tests/test_password_lifecycle_contract.py::CliTests -q   # 既有 CLI 契约面回归
............                                                             [100%]
12 passed in 39.06s

$ python -m pytest tests/test_security_a_closure.py -q                # §4 三处 0 命中 / 工件不在场
...                                                                      [100%]
3 passed in 0.86s
```

运维面实物（在 `mktemp -d` 里真跑 `python -m app.cli credentials migrate`，控制台是 GBK 所以
中文显示为乱码，字节本身是 UTF-8）：

```
artifact_present=False
imported=0 -
skipped=0 -
reason=迁移输入不存在：全新安装不生产 legacy 行（默认路径按当前工作目录解析为 <tmp>\data\legacy_credentials.json）
rc=0
--- SECURITY_ENTERPRISE_MODE=true ---
企业形态（SECURITY_ENTERPRISE_MODE=true）不导入任何 legacy：`credentials migrate` 已拒绝，未写入任何一行。…
rc=2
```

STATUS: DONE — 焦点门 80 passed（新增 9 枚），既有 CLI 契约面 12 passed，closure 扫描 3 passed。

### 8.1 两种 cwd 同数（§15.1 第 3 步的口径）

```
$ cd backend && python -m pytest tests/test_credentials_contract.py -q     → 80 passed, 35 subtests (44.16s)
$ cd <仓库根> && python -m pytest backend/tests/test_credentials_contract.py -q
                                                                          → 80 passed（同一行 `[ledger-guard]` **读**提示，基线同款）
```

新增的 9 枚都靠 `os.chdir(临时目录)` 让**默认相对路径**命中工件，库走绝对 env ⇒ 两种 cwd 同绿。

### 8.2 允许面核对（只改了两个文件）

`diff -q` 对 `snap-task10c-pre-app/`：`credentials_migration.py` / `user_store.py` / `auth.py` /
`main.py` / `config.py` / `directory.py` / `credentials.py` / `audit.py` 全部 **UNCHANGED**。
测试文件对 `snap-task10c-pre-test_credentials_contract.py`：删除行共 6 行，全部是 import 两行 +
`MigrationPathTests` 的类头与 docstring 四行（提夹具的代价）；**没有删改任何既有用例名或断言**。
本次未执行任何 git 写命令。

---

# Fix round 1（复评审收口：2 Important + 4 Minor）

STATUS: DONE（六条全部收口；证伪四次全部判红、逐字节还原；证据见 §FR1-2 至 §FR1-5）

裁定基线：verdict 是 **Approved**，本轮只做「补覆盖 + 补一条错误路径 + 退出码可读性 + 改注释」，
不是重设计。明确不做：Minor 3（rc 2 过载——已由 §11 新退出码表记档）、Minor 4（拒路径只走
stderr——已接受）、Minor 6（焦点文件 6.2s→44s，由 lifespan 那枚钉带来——**不加 skip、不桩
lifespan**，只记一笔）、`--path` / `--force` 旗标（§17 L7 裁定禁止）。

## 待收口清单

| 编号 | 内容 | 落点 |
| --- | --- | --- |
| Important 1 | `cli.py:143` 的 `ensure_user_credentials_schema()` 无钉 | 新用例（fresh-file）+ 删行证伪 |
| Important 2 | DB 锁 / 卷满以裸栈出到 rc 1 | `except (CredentialStoreError, sqlite3.Error)` → rc 1 + 新用例 |
| Minor 1 | stdout 四行只被 `assertIn` 钉 | 等值 / `len(lines)==4` |
| Minor 2 | 退出码字面量散落两处函数 | `_EXIT_OK/_EXIT_STORE_INCIDENT/_EXIT_REFUSED/_EXIT_DEV_DEFECT` |
| Minor 5 | happy path 吃环境态 dev | 显式钉 `security_enterprise_mode=False` |
| Minor 7 | 部署拓扑那句注释与测试 docstring 说反了 | 只改注释/文档字符串 |

## 基线（本轮开工前）

命令：`cd backend && python -m pytest tests/test_credentials_contract.py -q`

```
80 passed, 35 subtests passed in 45.03s          # 与上轮 head 同数（44.16s 那一格的复测）
```

行尾测量（写前，三枚允许面文件；LF-native，本轮所有写入按**该文件现状**保持 LF）：

```
app/cli.py                          CRLF 0  LF 239  endsNL True  sha1 69073df9aca56fc43e1575d3f38961eb14311c54
tests/test_credentials_contract.py  CRLF 0  LF 1739 endsNL True  sha1 16db53480ba5986585a72affa13393954d429be9
app/credentials_migration.py        CRLF 0  LF 217  endsNL True  sha1 18e1f0d13a69305cff37789b22ad8827bf15b59f
```

## FR1-1 读过的权威面（本轮）

- 规格：`docs/SECURITY_A_SPECIFICATION.md` §11（`migrate` 块 + 四规则 + **新退出码表**：0 / 1 =
  `CredentialStoreError` **与 `sqlite3.Error`** / 2 运维可修 / 3 开发期缺陷；以及"`migrate` 的证据面
  是那四行 stdout，不是审计事件"那段裁定）、§8.6（CLI 无独立 actor）、§17 **L7**（cwd 相对工件这条
  限制 + 明写"本轮不加 `--path`"）、§9.1（`detail` 值域闭合 ⇒ 不造新 token）
- 简报 / 上轮报告 / `task-10c-review-package.md`（base→head 两文件）
- 代码与夹具：`backend/app/cli.py`、`backend/app/credentials_migration.py`、`backend/app/user_store.py`
  （`_connect()` / `ensure_user_credentials_schema()` / `CredentialStoreError(RuntimeError)` ⇒
  与 `sqlite3.Error` **无继承关系**，两枚 except 的先后不敏感）、`docker-compose.yml:29-30`
  （挂的是**目录** `./backend/data:/app/data`）、`backend/.env:33`
  （`CONVERSATION_DB_PATH=data/conversations.db`，相对值）、`app/config.py:157`
  （`security_enterprise_mode: bool = False` + `case_sensitive=False` ⇒ 宿主 env 拨得动它：Minor 5
  的证伪就走这条路，不必改文件）

## FR1-2 逐条收口

证伪公共手法：`mktemp -d` 里 `cp` 出备份 → 用只含 ASCII 锚点的 mutation 脚本改一处（避开 Windows
控制台编码）→ 跑焦点门 → **`cp` 回备份**（绝不从 git 还原）→ `sha1sum` 前后比对。

### Important 1 — `cli.py` 的 `ensure_user_credentials_schema()` 无钉

- **改动**：纯测试面。新增
  `LegacyImportCliTests.test_migrate_builds_the_schema_itself_against_a_virgin_database`。它是本类
  唯一**不用** `setUp` 那份库的用例：`mock.patch.dict(os.environ, {"CONVERSATION_DB_PATH": <setUp
  没碰过的新文件>})` + 默认路径工件 ⇒ 复刻 `migrate` 存在的唯一场景（virgin 生产库）。判据三件：
  `rc == 0`、`imported=2 admin,sales01`、那份文件现在真在；再用**只读连接**按
  `(username, algorithm, must_change)` 验行落在**这份新文件**里（只看 `exists()` 会放过"文件建出来
  但里面没表"）。
- **证伪（删调用）**：删掉 `_migrate_legacy_artifact()` 里那行 `user_store.ensure_user_credentials_schema()`
  （本轮 Important 2 已把它挪进 `try`，现 `cli.py:165`）。
  ```
  MUTATED-A
  FAILED ::test_a_database_that_cannot_even_be_opened_fails_the_same_way_on_the_schema_leg
  FAILED ::test_migrate_builds_the_schema_itself_against_a_virgin_database
  2 failed, 81 passed, 35 subtests passed in 34.42s
  sha1 before 85e169f4a9518ca1d21a7ee153fc7d178252710f == after   # 逐字节还原
  ```
  评审的判断被复现：删掉这行，**上轮那 80 枚仍 79 枚绿**；红的两枚都是本轮新增，其中 virgin-DB
  那枚是"这行有没有被调用"的唯一直接钉，schema-腿那枚从侧面也钉它（桩没人叫到 ⇒ rc 掉回 0）。
  没有任何既有用例顶这个岗。

### Important 2 — "DB 锁 / 卷满"以裸栈出到运维面前

- **改动**：`cli.py` 顶部 `import sqlite3`；`_migrate_legacy_artifact()` 里 (a) 建表调用**移进 `try`**
  （它自己就连库，留在外面等于把这一格最常见的形态送给解释器兜底），(b)
  `except (CredentialStoreError, sqlite3.Error) as exc:` ⇒ `print(str(exc), file=sys.stderr)` +
  `_EXIT_STORE_INCIDENT`（1）。消息原样转、不包栈（口径同两条写腿）。**未**扩到两条口令腿，代码里
  就地写明"那个洞早于本任务、本轮不顺手改它的行为"。
- **覆盖用例**：`test_a_locked_database_is_an_incident_and_never_a_naked_traceback`
  （`user_store.import_legacy_digest` 抛 `sqlite3.OperationalError("database is locked")` ⇒ `rc==1`、
  stdout `""`、`err.splitlines() == ["database is locked"]`（恰好一行）、无 `Traceback`、库零行）
  + `test_a_database_that_cannot_even_be_opened_fails_the_same_way_on_the_schema_leg`（桩 schema 腿，
  特意用公共基类 `sqlite3.DatabaseError("disk I/O error")` ⇒ 钉"接的是**家族**不是某一枚子类"，
  同时钉建表在那条腿**之内**）。
- **证伪（去掉 sqlite3.Error）**：`except (CredentialStoreError, sqlite3.Error)` → `except CredentialStoreError`。
  ```
  MUTATED-B
  FAILED ::test_a_database_that_cannot_even_be_opened_fails_the_same_way_on_the_schema_leg
  FAILED ::test_a_locked_database_is_an_incident_and_never_a_naked_traceback
  2 failed, 81 passed, 35 subtests passed in 39.00s
  sha1 before 85e169f4a9518ca1d21a7ee153fc7d178252710f == after
  ```
  改前那两枚以未捕获的驱动异常冲出 `cli.main`（测试当场 error）⇒ 正是"裸栈 + 偶然 rc 1"。其余 81 枚
  不受影响，也证明口令两条腿的行为一字未动。

### Minor 1 — stdout 形状只被 `assertIn` 钉

- **改动**：纯测试面。类内助手 `_four_field_face(out)`：钉**恰好四行** + **字段序**
  `artifact_present / imported / skipped / reason`，再把四行原样交回调用方比取值。三处调用：
  (1) `test_dev_import_lands_...` 四枚 `assertIn` 升级为整表等值
  `["artifact_present=True", "imported=2 admin,sales01", "skipped=0 -", "reason=-"]`；
  (2) `test_running_it_twice_...` 第二次运行四行等值；
  (3) `test_an_absent_artifact_...` 形状 + 前两行等值，`reason` 那格因带解析后的绝对路径不逐字比，
  改为要求它说出 `legacy_credentials.json`（§17 L7 的"人眼可诊"）。既有用例名与语义未删，只把
  "包含"换成"等值"（等值蕴含包含 ⇒ 严格更强）。
- **证伪**：在 `reason=` 之后插一行 `print("hint=next run migration-status")`（那枚"贴心的第五行"）。
  ```
  MUTATED-C
  FAILED ::test_an_absent_artifact_is_a_legal_steady_state_and_still_exits_zero
  FAILED ::test_dev_import_lands_legacy_rows_and_prints_the_four_fields
  FAILED ::test_running_it_twice_imports_nothing_and_never_downgrades_a_converged_row
  3 failed, 80 passed, 35 subtests passed in 38.12s
  sha1 before 85e169f4a9518ca1d21a7ee153fc7d178252710f == after
  ```

### Minor 2 — 退出码是散落的字面量

- **改动**：`cli.py` 顶部新增 `_EXIT_OK=0 / _EXIT_STORE_INCIDENT=1 / _EXIT_REFUSED=2 / _EXIT_DEV_DEFECT=3`
  （注释点名 §11 那张表，并写明"要新增一格先改规格表，不在此处"），与既有 `_MUST_CHANGE_BY_ACTION`
  同一形状；文件内 11 处 `return <int>` 全部换成名字（含 `_print_status` 的 `return 0`——评审清单
  没点它，但它同是本文件的退出码，留字面量等于表上少一格；纯改名，未动分发结构）。
  **数值一格未动**：运行期复核 `[('_EXIT_OK',0),('_EXIT_STORE_INCIDENT',1),('_EXIT_REFUSED',2),('_EXIT_DEV_DEFECT',3)]`，
  `grep -n "return [0-9]" app/cli.py` 0 命中。
- **为什么不再开一次变异**：所有 rc 断言在测试里写的是**数字**（0/1/2/3，不引用 `cli._EXIT_*`），
  "数值未变"这件事由门自己担保——把任一常量拨错一位，本类与 `CliTests` 的 rc 断言当场红（本轮 12 枚
  CliTests 全绿）。刻意不把测试改成引用常量：那会把契约降级成对实现写法的复述。

### Minor 5 — happy path 吃环境态 dev

- **改动**：`LegacyImportCliTests.setUp` 里 `mock.patch.object(cli.settings, "security_enterprise_mode", False)`
  + `start()` + `addCleanup(stop)`（评审两案里选了类级 patch：它既消症状也改判据，比"断言一下环境"强）。
  企业那两条用例内层再 patch 成 True，退出时还回 False，两件事互不牺牲。
- **证伪（双向都做了）**：宿主环境 `SECURITY_ENTERPRISE_MODE=true` 跑本类。
  ```
  D1 带钉   ：12 passed, 71 deselected in 38.44s        # 环境已翻成企业形态，本类一格没红
  D2 删掉那三行（同样翻法）：
       10 failed, 2 passed, 71 deselected in 36.03s
       红的 10 枚：dev-import / absent-artifact / twice / face-no-material / virgin / locked /
       schema-leg / malformed / store-incident / lifespan；绿的两枚正是自己 patch True 的企业用例
       症状就是 rc 2 vs 0 —— 与被测行为无关
       sha1 before 8c910e15b88fccddc60d9cf3f1f975cff7467c86 == after   # 测试文件逐字节还原
  ```
  评审估的"five unrelated tests"偏保守：不吃钉的话是 **10/12** 枚。

### Minor 7 — 一句说反了的部署拓扑（只改注释/文档字符串）

- **`credentials_migration.py:20-26`**：原文"（容器 / systemd，**compose 就是这么挂库的**）里库跟着
  env 搬走"不成立——实测 `docker-compose.yml:29-30` 挂的是**目录** `./backend/data:/app/data`，
  `backend/.env:33` 那枚键仍是相对值。改成：现网同源；绝对路径是 **systemd 式部署会自己选上的形状**，
  届时零行退出；限制连同失败方向按 **§17 L7** 编号引用，并就地写明"本轮按该条裁定**不**加 `--path`"。
- **`tests/test_credentials_contract.py`（`_ArtifactFixtures` docstring，原 674-679）**：原文把夹具自己
  给的绝对 `CONVERSATION_DB_PATH` 说成"`LEGACY_INPUT_PATH` 那段理由里说的分叉形状"，跟着同一处错。
  改成：那是**刻意复刻 §17 L7 的分叉**、不是现网形态，并补上 compose 挂目录 / `.env` 相对值的事实。
- 行为零改动：diff 只含 `#:` 注释行与 docstring 行（`credentials_migration.py` LF 217→220，全是注释）。

## FR1-3 明确不做（本轮按裁定收住）

Minor 3（rc 2 过载）⇒ 已由 §11 新表下的分诊说明记档，未开新码；Minor 4（拒路径只走 stderr）⇒ 未动；
Minor 6（runtime）⇒ **未加 skip、未桩 lifespan**，只在 §FR1-5 记一笔。未加 `--path` / `--force`
（§17 L7 禁止）；未新增审计 `detail` token（§9.1 闭合）；两条口令腿的异常面未扩。
允许面核对：`find backend -newermt "2026-09-26 19:00" -type f -not -path "*__pycache__*"` 只交出
`app/cli.py`、`app/credentials_migration.py`、`tests/test_credentials_contract.py`（另有 `.pytest_cache`
两枚缓存，与 §FR1-5 那条 sidecar 观察）——`user_store.py` / `main.py` / `auth.py` / 规格与计划文档 /
前端全部未触碰。未执行任何 git 写命令；`model-router-v2.3-rc1` 未碰。

## FR1-4 终局门（本轮改后）

```
$ cd backend && python -m pytest tests/test_credentials_contract.py -q
83 passed, 35 subtests passed in 38.24s      # 基线 80 → 83：+virgin-DB / +locked / +schema-腿
$ cd <仓库根> && python -m pytest backend/tests/test_credentials_contract.py -q     # 两 cwd 同数
83 passed, 35 subtests passed in 42.14s
$ python -m pytest tests/test_password_lifecycle_contract.py -k CliTests -q
12 passed, 65 deselected in 34.01s
$ python -m pytest tests/test_security_a_closure.py -q
3 passed in 0.85s
$ python -m pytest tests/test_secret_hygiene_contract.py -q        # 本轮动了被扫面 ⇒ 复跑
45 passed in 41.98s                                                # 豁免表 == 命中表，未加 EXEMPTIONS 行
```

凭据材料审计：新增代码与夹具没有明文口令、没有那 5 枚 digest 字面量、没有像真钥匙的串；摘要一律走
`self.DIGESTS`（`"a" * 64` 同族写法）；两枚驱动层消息（`database is locked` / `disk I/O error`）是
驱动文案、不是凭据材料，secret 门实测 0 命中（故没动豁免表）。

## FR1-5 行尾 / sha1 与观察

终局（三文件均 LF-native、以换行结尾，与写前同规格）：

```
app/cli.py                         sha1 072f2d43f22e1aab867e85fa9bab59bdc1f38c34  CRLF 0 LF 265
app/credentials_migration.py       sha1 f45b46ef8e2338f0adaadc38be65d43f5209fd67  CRLF 0 LF 220
tests/test_credentials_contract.py sha1 8c910e15b88fccddc60d9cf3f1f975cff7467c86  CRLF 0 LF 1847
```

- **sha1 时间线（诚实说明）**：三次证伪的还原比对都对着**当时的 head** 成立（`cli.py` 85e169f4…、
  测试文件 8c910e15…）。`cli.py` 之后只多了一次**纯注释**改写（把"是以后的日子才会出现的"那句含糊
  说法改成准确表述）⇒ 终局 072f2d43…；改完重跑焦点门 83 全绿。
- **Minor 6 那一笔**：焦点文件 runtime 仍 ~38–45s，成本在
  `test_starting_the_app_never_consumes_the_upgrade_artifact` 真起 lifespan（上轮记的 6.2s→44s 就是它）。
  按裁定不加 skip、不桩 lifespan。
- **`backend/data/` 未被写**：目录里既无 `legacy_credentials.json` 也无 `virgin-production.db`（新库
  只落在 `self._tmp`）；`conversations.db` mtime 仍是本轮开工前的 17:54、`-wal` 0 字节。
  观察（**非本轮引入**）：`conversations.db-shm` 每次跑这套件都会被 read-open 刷一次时间戳——实测只跑
  本轮未碰的既有 `CredentialStoreGuardTests` 同样刷新，属 conftest 会话钩子读真库的既有副作用；
  本文件自带的 `test_no_test_in_this_session_wrote_a_credential_row_into_a_real_databases` 全绿，
  "没有凭据行落进真库"仍由门担保。
- **无重复方法名**：AST 复核 `LegacyImportCliTests` 12 个 `test_*`、dupes 为空集（防"加了用例却被同名
  遮蔽"这种静默掉数）。测试数只增不减：80 → 83；断言只强不弱（`assertIn` → 等值）。

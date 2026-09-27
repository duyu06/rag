# Task 10d — deferred minor 全量分诊报告（COMPLETE：台账 47 格 + 复评移交 2 格 + 10a 子问题，零未处理）

状态头：本文件在第 22 回合以 `PARTIAL` 建立（简报要求第 30 回合前建），收口时全部分诊结论、
红→绿反证与计数已回填。后续轮次要重开某格，请以该行给出的 file:line 为起点，不要以台账为起点。

## 0. 基线（改动前实测）

- 快照：`.superpowers/sdd/SECURITY_A_PLAN/snap-task10d-pre-app/`（`backend/app` 全树，已排 `__pycache__`）
  + `snap-task10d-pre-sha1.txt`（本轮会触碰的 11 个文件的改前 sha1）。
- 焦点九文件合集（五枚 SEC-A 门 + 四枚回归门）改动前基线：**785 passed / 21 warnings / 553 subtests**，
  0 failed，`cwd=backend/`（在动任何一笔之前跑的；同一发命令在收口时复跑，见 §3）。
- 收口时复比 `diff -rq snap-task10d-pre-app backend/app`：只报出四枚文件（`credentials.py`、
  `user_store.py`、`login_throttle.py`、`credentials_migration.py`）⇒ `main.py` / `auth.py` /
  `config.py` / `cli.py` / `directory.py` 与 `app/**` 的其余 50 枚文件一字未动；
  `tests/conftest.py` 与 `tests/sec_a_fixtures.py` 这两层安全地基也未动（`conftest.py` 的
  sha1 前后同值，见 §2 表）。
- 全套件不进本报告（另有安排）。

## 1. 分诊表（一行一条；台账行号取 `progress.md`）

结论词汇：**闭合**（本轮改+钉，红→绿见 §3）/ **已知限制**（进验收文档 L 系列，附措辞）/
**§18**（后续登记，附措辞）/ **已顺带闭合**（后续任务或修复轮已收，给 file:line）/
**不成立**（台账描述与当前树不符）。

### Task 1（`progress.md:41`）

| # | 条目 | 今天是否成立 | 结论 | 证据 / file:line |
| --- | --- | --- | --- | --- |
| 1.1 | `_LEGACY_HEX` 拒大写却仍 `.lower()`（死代码） | 成立 | 闭合 | 判据 `app/credentials.py:30` 已是 `^[0-9a-f]{64}$`，`:122` 的 `.lower()` 恒等 ⇒ 删掉；`compare_digest` 的两侧取值不变（含"带尾换行仍能匹配 `$`"那一格：两侧长度不同，本来就不等） |
| 1.2 | `config.py` 未用 `Field(ge=1)`，与邻居风格不一致 | 成立 | §18 | `app/config.py:171/174/175/180/181` 五枚 SEC-A 整数键是裸默认值；下限目前由 `app/credentials.py:58` 的 `max(1, …)` 在运行期兜。把下限搬到 `ge=1` 会把"越界值被夹回来"变成"启动期 ValidationError"——那是启动面的形状变化，规格 §8.5 的三守卫已冻结，本轮不动。措辞：`SEC-A 的可用性旋钮不做 pydantic 区间校验，唯一的下限是 credentials 侧的 max(1,·) 夹取；把下限搬到启动面属 SEC-B 的配置校验条目` |
| 1.3 | `hash_password` 不占槽、公开 `argon2_slot` 诱导重复占 | **不成立** | 已顺带闭合 | `app/credentials.py:69-76`（写入侧过同一道闸）+ 同段注释点名"嵌套占槽就是自锁"，由 `test_one_slot_is_enough_for_a_verify_followed_by_a_hash` 钉住。闭合轮：Task 8 修复轮 F3（`progress.md:197`） |
| 1.4 | `needs_rehash()` 对非 PHC 输入抛裸 `InvalidHashError` | 成立（改前实测） | 闭合 | 改前实测：`credentials.needs_rehash('not-a-phc-string')` 以 `argon2.exceptions.InvalidHashError`（⊂ ValueError）出场。改后（`app/credentials.py:79-89`）翻成 `CredentialConfigError`（消息与 `_verify_argon2` 同一句，不新增 token）、`__cause__` 保留原库异常，真 PHC 串照旧返回 False。理由同 `:143-147` 那一条：库异常不许逃出这个边界模块，否则上游是 500 |
| 1.5 | `test_only_credentials_module_hashes_passwords` 名称与实证不符 | **不成立** | 已顺带闭合 | 该用例现在住在 `CentralisationScanTests`（`tests/test_credentials_contract.py:234-360`），判的是"全 `app/**` AST 扫描的命中集 ⊆ 豁免表"+"豁免表 == 命中集"两枚等值钉，名称与实证一致。闭合轮：Task 1 修复轮 + Task 9 的 AST 收拢 |
| 1.6 | 等式失败消息未指向 `TRANSITIONAL_EXEMPT` | 成立 | 闭合 | `:341-360` 两枚 `assertEqual` 无失败消息；补消息指名那枚常量 |

### 结论统计（49 格 = 台账 47 + 复评移交 2；编号即上表行号）

| 结论 | 数量 | 编号 |
| --- | --- | --- |
| **闭合**（本轮改代码/门 + 补钉，红→绿见 §3） | 11 | 1.1、1.4、1.6、2.4、2.5、2.6、2.8、3.9、5.4、8.6、8'.1 |
| **已知限制**（进验收文档 L 系列，措辞已给） | 11 | 2.9、3.4、3.6、3.10、3.11、4.2、5.3、6.1、6.2、6.3、T10-9.1 |
| **转 §18 后续登记**（措辞已给） | 4 | 1.2、3.5、4.1、5.1 |
| **已顺带闭合 / 台账描述已失真**（后续任务或修复轮已收，给 file:line，未重开） | 21 | 1.3、1.5、2.1、2.2、2.3、2.7、3.1、3.2、3.3、3.7、3.8、4.3、5.2、6.4、8.1、8.2、8.3、8.4、8.5、8'.2、8'.4 |
| **无动作**（过程记录 / 交下一枚半程，各自有去处） | 2 | 8'.3、T10-9.2 |
| **未处理** | 0 | — |

台账 11 处 `minor (deferred)` 的行号（41 / 56 / 65 / 80 / 86 / 91 / 113 / 128 / 142 / 189 / 199）在本表里逐行都有格子，零静默消失；`task-10-brief.md` 的 T10-9 两格各有结论。`8.6` 与 `8'.1` 是同一件事被 `progress.md:189` 与 `:199` 各登记一次，本轮一次拆掉、两处同判。

### Task 2（`progress.md:56`、`progress.md:65`）


| # | 条目 | 今天是否成立 | 结论 | 证据 / file:line |
| --- | --- | --- | --- | --- |
| 2.1 | `_COLUMNS` 无消费方 | **不成立** | 已顺带闭合 | `app/user_store.py:170-180`（`_insert_sql` 由它生成列名段）+ 等值钉 `tests/test_credentials_contract.py:462,474` |
| 2.2 | `create_argon2` 撞主键抛裸 `sqlite3.IntegrityError` | **不成立** | 已顺带闭合 | `app/user_store.py:198-206`；钉 `tests/test_credentials_contract.py:635-639`（断 `CredentialStoreError` 且 `__cause__` 是 IntegrityError） |
| 2.3 | `CredentialRecord` 默认 repr 含 `password_hash` | **不成立** | 已顺带闭合 | `app/user_store.py:79` `field(repr=False)` |
| 2.4 | `list_records`/`delete_record`/`clear_login_failures` 无用例覆盖 | 部分成立 | 闭合（本轮补钉） | `list_records` 已由 `credentials_migration.status()` + `test_credentials_contract.py:1188` 钉；`clear_login_failures` 的效果由认证腿 `test_a_successful_login_clears_the_persistent_counter` 钉；**缺的是 `delete_record` 的返回值语义与"未知账号幂等"两格** ⇒ 本轮补 |
| 2.5 | 新 AST 护栏漏收 `from app import config` 形态 | 成立 | **闭合（门的覆盖面，优先）** | `tests/test_credentials_contract.py:494-506` 只收 `ast.Import` 的 `alias.name` 与 `ast.ImportFrom` 的 `node.module` ⇒ `from app import config` 的 `node.module` 是 `app`，`split(".")[-1]=="app"`，抓不到。本轮改为把"模块绑定名 + from 导入的名字"一起判，并用 `tmp_path`/字符串 planted 用例证明加宽的那道判据真的会红 |
| 2.6 | `user_store.py:58-59` 注释声称两枚消息可等值分派 | 成立 | 闭合（注释失真） | `:67` 缺失消息确实是等值分派（钉在 `test:653`），`:68` 已存在消息实际以 `f"{…}：{username}"` 抛出（`:204-206`）⇒ 只能前缀匹配。注释按实现改写 |
| 2.7 | `test:547` 措辞与"陈旧方向"已不再被演练 | **不成立** | 已顺带闭合 | 现在的位置是 `tests/test_credentials_contract.py:589-618`：陈旧版本由**重哈希前**的快照推出（`version_before + 1`），注释明确写了旧写法为什么两态同形。闭合轮：Task 2 修复轮 |
| 2.8 | CHECK 拒绝第三算法值无用例 | 成立 | 闭合（缺钉） | `app/user_store.py:34` 的 CHECK 今天没有任何直接钉 ⇒ 本轮补一条"绕过函数直插第三算法值必 IntegrityError" |
| 2.9 | `.env:33` 与默认值同值，fork 是潜在非现行 | 成立（但不在交付面） | 已知限制（已由 §17 L7 覆盖同一分叉面） | `backend/.env` 是 gitignored 的本机文件（`.gitignore:6`）；`tests/test_credentials_contract.py:481-492` 已钉"两个同库读者共用同一枚 env 键"，`config.py` 侧的 dotenv 分叉代价写在 `app/user_store.py:88-98`。绝对路径那格已登记为 §17 L7 |

### Task 3（`progress.md:80`、`86`、`91`）

| # | 条目 | 今天是否成立 | 结论 | 证据 / file:line |
| --- | --- | --- | --- | --- |
| 3.1 | conftest 两枚防御分支无用例（pending 预清 / 升档位置对不上） | 成立（且**已裁定**） | 已顺带闭合（以裁定+变异证据收口，非用例） | `tests/conftest.py:386-397`、`:413-427` 两段注释各自写明"变异验证：删掉它仍全绿"与"按构造够不到 ⇒ 刻意不设用例，也不许改成静默 return"。失败方向是过判红。闭合轮：Task 3 修复轮 |
| 3.2 | `warn_on_read=False` 不设钉 | **不成立** | 已顺带闭合 | `tests/test_credentials_contract.py:1707-1726`（`test_a_credential_read_is_reported_only_after_its_kind_has_settled`）三枚断言：中途无 warning + 两枚定型口径各 +1 |
| 3.3 | `LEGACY_INPUT_PATH` 相对路径，启动编排须按后端 cwd 解析 | **不成立** | 已顺带闭合（并按裁定转为 L7） | `app/credentials_migration.py:18-29` 的理由块 + `:167-171` 把**解析后的绝对路径**写进 `reason`；钉在 `test_credentials_contract.py:753`。裁定记录在规格 §17 L7：本轮不加 `--path` |
| 3.4 | 导入中途抛存储事故时已落行保留（简报未要求回滚整批） | 成立（有意） | 已知限制 | 措辞：`credentials migrate 的原子粒度是"一行一提交"：中途事故（DB 锁 / 卷满）退出时，之前已提交的 legacy 行留在库里。缓解 = 该命令幂等（only_missing=True），重跑一次即补完，且逐行都是 must_change=1 的未收敛态，SECA-04 的 legacy_count 门照样看得见它们；不做整批回滚的理由是"半批"与"整批"在 sqlite 单连接事务里的代价差不是本规格要付的（§8.8 的事务不变量只管改密腿）`。触发条件 = 导入过程中库被锁或盘满 |
| 3.5 | `LedgerGuard` 类名只剩一半职责 ⇒ 改名 `RedirectGuard` | 成立 | §18（结论：本轮不改） | 现名覆盖的是"改道 + 写证据"两道闸，两张表共用同一份实现（`tests/conftest.py:235-253` 的 `label`/`subject` 就是把名字问题关在输出里）。改名要动的文件包括**安全地基**（`tests/conftest.py` 里的类与 4 枚口径函数）与**四枚直呼它的文件**（`grep -ln "import conftest as ledger_guard"` 实测：`test_credentials_contract.py` / `test_llm_egress_guard` / `test_llm_egress_guard.py` / `test_model_router_v23_contract.py` / `sec_a_seed.py`，外加 `real_llm_failover_kit.py`——挨着不可触碰的 `test_real_llm_failover_acceptance.py`），零安全收益；Task 5 的教训正是"共享夹具是本项目最贵的一类改动"。措辞：`护栏类的命名（LedgerGuard 已覆盖凭据面）留到下一次护栏换形时一次性改，那一次本来就要重跑全套地基` |
| 3.6 | `MigrationReport.skipped` 把"已存在跳过"与"写方拒收"合一 | 成立（但被 §11 冻住） | 已知限制 + 注释闭合（本轮） | 拆分要给 `migrate` 的 stdout 加第五行，而规格 §11 明文"它打印 `MigrationReport`（`artifact_present / imported / skipped / reason`）"是**证据面契约** ⇒ 属"改变形状"，本轮不动。当前实现已把分辨力放在 `reason`（`app/credentials_migration.py:180-195`）。本轮把这条裁定写进 `MigrationReport` 的 docstring（原来是空头 TODO 的形状） |
| 3.7 | `credential_redirects()`/`credential_read_redirects()` 零调用点 | **不成立** | 已顺带闭合 | `tests/test_credentials_contract.py:1715-1716,1724-1726` 消费这两枚口径，用例名就叫"only after its kind has settled" |
| 3.8 | `test:1067-1068` 的 `assertIn(columns, ([], …))` 两态都接受 | **不成立** | 已顺带闭合 | 同一条用例现在写作 `tests/test_credentials_contract.py:1699-1705`：完整列等值 + "读的是改道目标那个文件" + "真库快照一字不变"三枚断言，注释点名"两态都接受的断言等于没钉" |
| 3.9 | I1 扫描窄了：`from app import credentials_migration` 后走 `credentials_migration.user_store.import_legacy_digest(…)` 的两段链被放过 | 成立 | **闭合（门的覆盖面，优先）** | `tests/test_credentials_contract.py`（`_legacy_writer_calls`）：接收者是两段链时，头一段能解析成本模块的某个 import、尾段却是静态不可定的模块属性 ⇒ 今天按"属于别的模块"放过。本轮按台账给的方案改成"链尾非空且头部是已知 import ⇒ 按未知计入"，并加 planted 用例（字符串 AST，不进仓库）证明加宽后那一发真的红 |
| 3.10 | conftest 收尾两处 raise 会跳过 uninstall | 成立（可接受） | 已知限制 | 措辞：`会话级护栏的 teardown 在两枚哨兵（护栏在场 / 真库行数不涨）判红时直接 raise，跳过 uninstall；进程即将退出，模块状态随之消失 ⇒ 症状只是一条多余的 Traceback 跟在判红消息后面，不是漏检`。触发条件 = 整场套件结束时哨兵判红 |
| 3.11 | 会话末多两次真库只读打开 | 成立 | 已知限制（与本报告 §5 的 `-shm` 判定同一条） | `tests/conftest.py:485-500,552-560` 三处 `mode=ro` 只读打开；真库今天**有** `user_credentials` 表（5 行 argon2id），所以"窗口为零"那句描述已失真 ⇒ 见 §5：读的是 WAL 库，`-shm` 必被触碰，`conversations.db` 本体字节与 mtime 不变（实测） |

### Task 4（`progress.md:113`）

| # | 条目 | 今天是否成立 | 结论 | 证据 / file:line |
| --- | --- | --- | --- | --- |
| 4.1 | `adoption_pct=0.0` 混"零采用/无分母"，`OperationsView.tsx:132` 渲染 `2/0` | 成立 | §18 | 前端展示层，SEC-A 的边界不含 `frontend/**`（简报禁地；本轮硬边界）。措辞：`凭据采用率的"无分母"取值需要 null + ?? "—" 的形状变更，跨 API 契约与前端两处，随下一次前端运维视图的改动一起做（SEC-B/C）` |
| 4.2 | `directory.py` 短于 40 的未知键、重名消息里的 username 可入消息 | 成立（且是有意边界） | 已知限制 | `app/directory.py:58-59`（≥40 纯 hex 才判摘要，下限停在 40 的理由写在 `:40-44`）、`:179-181`、`:186-192`（重名/open_id 冲突消息带 username）。这些串**只**从 `IdentityConfigError` 出到启动日志与 CLI，那里账号名本就是配置项（同 `ACCOUNT_EXISTS_MESSAGE` 的裁定，`user_store.py:65-66`）；响应面与审计面够不到这条异常。措辞：`身份文件的启动期报错会点名冲突的 username，且"键名短于 40 位 hex"不进摘要判定：前者是运维定位需要的信息，后者是"拒在启动期的代价高于顺带拦下 MD5"的既裁权衡` |
| 4.3 | `knowledge_os.py:704` 那句读起来既像描述又像规范 | **不成立** | 已顺带闭合 | Task 5 真的消费了 `enabled`（`app/auth.py:304` 与令牌腿 `:425`），`:704-707` 那句现在是对既成事实的纯描述（名册投影 / 登录面合一，两处读同一字段） |

### Task 5（`progress.md:128`）

| # | 条目 | 今天是否成立 | 结论 | 证据 / file:line |
| --- | --- | --- | --- | --- |
| 5.1 | `test_model_router_v23_contract.py:4605` 用例内自 seed | 成立（且被那个文件自己裁定） | §18（本轮不动） | 那是该文件里**唯一**一处 `ensure_demo_credentials` 直调，`:4666` 还有一条断言在解释"这一例需要脚下有行、helper 不代为补种"。删它 ⇒ V2.3 密封门红；挪进类夹具 ⇒ 给一份已封板文件做形状改动，且掩盖不了任何生产事实（生产 seed 由 Task 5 的启动编排用例钉）。措辞：`V2.3 契约文件里那处用例内 seed 属"测试自己造前置条件"的自愈模式，随下一次 V2.x 套件的地基统一处理` |
| 5.2 | `install_demo_credentials` 的 exists 分支与 `_ensure_credentials_at` 无调用者、无专用用例 | **不成立** | 已顺带闭合 | `_ensure_credentials_at` 有两个调用者（`tests/sec_a_seed.py:97` 建模板、`:118` exists 分支）；`install_demo_credentials` 的调用点是 `tests/test_model_router_v23_contract.py:4128`（类级），exists 分支在第二次换库到同一落点时走。两条分支各挡一种事故，理由就写在 `sec_a_seed.py:101-121` |
| 5.3 | naive `locked_until` 落在过去会被读成"永久锁定" | 成立（有意的 fail-closed） | 已知限制 | `app/login_throttle.py:106-119` 的 docstring 已把这一格写成规范（"解析得出但没有偏移 ⇒ 一律当锁定，不替它猜 UTC"），本仓写方产不出该值（`user_store.py:323` 给的是带 tz 的 ISO）。措辞：`无时区的 locked_until 一律读成"仍锁着"：值本身不再可信，白送一次昂贵运算正是这条门要挡的事；代价是运维手改出来的过去时刻也要等 15 分钟的自动过期或人工改库。缓解 = CLI migration-status 打印 locked 原值` |
| 5.4 | `test_no_artificial_delay` 只认被调名 `sleep` | 成立 | 闭合（门的覆盖面） | `tests/test_authentication_leg_contract.py:878-899` 判 `name == "sleep"` ⇒ `threading.Event().wait()` 一类漏。本轮把词表加宽为 `DELAY_CALL_NAMES = {sleep, wait}`（`tests/test_authentication_leg_contract.py` 的 `SourceRemovalTests`）并加一枚自证用例：`time.sleep` / `from time import sleep` / `asyncio.sleep` / `Event().wait()` / `threading.Event().wait()` 五种形态各命中 1，`str.join` 与 `bucket.allow(...)` 零命中。实测登录腿调用图五枚模块里 `wait(` 零命中（加宽不会误红）、`join(` 有 4 处 ⇒ 明知不收 join |

### Task 6（`progress.md:142`）

| # | 条目 | 今天是否成立 | 结论 | 证据 / file:line |
| --- | --- | --- | --- | --- |
| 6.1 | 每个认证请求读两遍同一凭据行（令牌腿 + `_password_change_required`） | 成立 | **结论：保留，不是缺陷**（并记已知限制） | 判据：两读不是同一件事的两次计算。(a) `app/auth.py:139-143` 的 `_password_change_required` 是**授权时刻**的读数（§8.4 末段：`must_change` 是当前凭据状态、不是 claim），令牌校验腿读的是 `credentials_version`；把两次并成一次 = 让响应面的布尔键复用认证时刻的快照，于是"认证之后、响应之前有人改了密"这一格被读成旧值——那正是 §8.4 的 403 门要判的窗口。(b) 并掉的另两种写法分别破"凭据不进 `CurrentUser`"（`auth.py:72-86` 的构造面）与"构造面唯一"两条既裁不变量。(c) 成本面：一条带主键索引的本地 SQLite SELECT vs 19 MiB 的 Argon2 运算，占比在千分位；Task 8 已把每请求的昂贵运算收在闸门后面。**本轮不改**，措辞进 L 系列：`认证请求对 user_credentials 是两次只读 SELECT（版本比对 + must_change 门），这是刻意的：两次判定必须落在各自的时间点上。合并属性能优化，SEC-A 不做没有测量支撑的合并` |
| 6.2 | `main.py` 导入下划线名 `_password_change_required` | 成立（有意） | 已知限制 | `app/main.py:30` + 三处调用（`:363/:429/:477`）。它就是"两处判定同源"的那枚钉子：Task 6 修复轮 I-2 的反证证明桩必须打在 `app.main` 自己那份绑定上才有效（`from app.auth import` 是 import 期复制名字）。改公共名要同步 9 处测试引用，收益只有可读性。措辞：`响应面与门判定共用 app.auth 里同一个私有名字，main.py 按值导入是"同源"这件事的载体；改名留给下一次动认证腿的任务` |
| 6.3 | 枚举行不管"压根不挂认证依赖"的新端点 | 成立 | 已知限制 | 简报裁定不维护豁免清单、本任务不反转。现状是 Task 6 修复轮 I-1 的形状：每条被枚举的路由先上绊线桩、断"派发的那枚 == 桩的那枚"、破坏性入口设哨（`test_password_lifecycle_contract.py` 的覆盖面门）。措辞：`must_change 门与权限门挂在依赖上：一条"忘了挂认证依赖"的新端点不会出现在枚举行里，它由"每条 API 路由都要么要求权限、要么在白名单里"那枚覆盖面钉负责——那道钉是运行时绊线，不是豁免清单。本轮补了一格让这句话**可核验**：门自己的枚举闭合用例 `test_every_api_route_is_either_gated_or_on_the_frozen_whitelist` 与 `SEC-A` 枚举行对 `GET /api/auth/me` 的免门腿同处一个集合等式里` |
| 6.4 | 规格 `:458` "全仓无登录响应键集合断言"不成立 | **不成立** | 已顺带闭合 | 规格自己已经改过：`docs/SECURITY_A_SPECIFICATION.md` §11 第二段（"已核实地基（2026-09-26 由 Task 6 实现复核更正）…初稿把这条写成『全仓无登录响应键集合断言』，是盘点漏项"）⇒ Task 10 验收文档照 §11 现在的写法抄即可 |

### Task 8（`progress.md:189`，六格）

| # | 条目 | 今天是否成立 | 结论 | 证据 / file:line |
| --- | --- | --- | --- | --- |
| 8.1 | `configured_throttle()` 死代码 | **不成立** | 已顺带闭合 | 全仓 grep `configured_throttle` 零命中；单例改为 import 期急建（`app/login_throttle.py:123-130`）。闭合轮：Task 8 修复轮（`progress.md:190` 六格逐格收口） |
| 8.2 | `auth.py:16` 按值绑 `pre_hash_throttle` | **不成立** | 已顺带闭合 | `app/auth.py:11` 改成 `from app import … login_throttle`、`:287-290` 走属性读，注释就写着"读取点只有这一处属性"；钉在 `test_authentication_leg_contract.py:1136/1170/1268/1291/1314` 的 `mock.patch.object(login_throttle, "pre_hash_throttle", …)` |
| 8.3 | 容量用例给无身份的 `gate` 造 legacy 行（装饰性 setup + 重复） | **不成立** | 已顺带闭合 | Task 8 修复轮 folded minors 之一（`progress.md:190`）；现状 `test_authentication_leg_contract.py:1227+` 的容量用例走 `test_two_source_addresses…` 的真实身份 |
| 8.4 | `LockedHttpFaceTests` 真烧生产单例 8/10 次配额 | **不成立** | 已顺带闭合 | `test_authentication_leg_contract.py:1268/1291/1314` 三例都在 `mock.patch.object(login_throttle, "pre_hash_throttle", self.throttle)` 下跑，生产桶不再被烧 |
| 8.5 | `_sweep_stale()` 无专用用例 | **不成立** | 已顺带闭合 | `test_authentication_leg_contract.py:1187-1226`（`test_stale_buckets_are_reaped_while_live_ones_survive`），判据是表本身的大小，并额外钉"回收不改变任何一次答复" |
| 8.6 | `allow(now=)` 与真实 monotonic 的 `_last_sweep` 混用 | 成立 | 闭合（本轮，见 8'.1） | 台账把它留在 `:189` 与 `:199` 两处；`app/login_throttle.py:58` 仍用 `time.monotonic()` 播种 |

### Task 8 修复轮余账（`progress.md:199`）

| # | 条目 | 今天是否成立 | 结论 | 证据 / file:line |
| --- | --- | --- | --- | --- |
| 8'.1 | `_last_sweep` 用真实 monotonic 播种而 `allow(now=)` 接受注入时钟 | 成立 | **闭合（本轮，注释记雷未拆 ⇒ 拆）** | 改前 `app/login_throttle.py:58` 用真实 monotonic 播种、`:80-86` 只写"注入时钟必须与 monotonic 同基准"（记雷不拆雷）。改后：`__init__` 起点 `None`（`:53-64`）、`_sweep_stale` 首次调用惰性播种并直接返回（`:72-96`）、`reset()` 回到 `None` 而不是回到真实单调钟。钉 = `ThrottleLayerTests.test_reaping_does_not_depend_on_the_clock_the_test_injects`。改法：`_last_sweep` 初值 `None`，首次 `_sweep_stale` 用**当下那枚时刻**惰性播种并直接返回 ⇒ 真实运行时的行为一字不变（第一格仍是 monotonic），注入时钟时回收不再被负数差值卡死。补一枚正向钉（新实例 + 与 monotonic 无关 epoch 的注入时钟仍能在越过窗口时回收）+ 更新原 docstring |
| 8'.2 | 写腿 503 审计仍走 LOGIN 动作族 | **不成立** | 已顺带闭合 | Task 9：`_auth_availability_denial(…, action="PASSWORD")`、`record_login_event(…, action="PASSWORD")`、`_audit(…, "PASSWORD", status="FAILED")`（`app/main.py:465/470`），钉 = `PasswordLegActionAttributionTests` 四腿 + 登录腿仍全 LOGIN 的反向钉（控制器核验见 `task-10-brief.md` T10-3） |
| 8'.3 | `.env.example` 一处 FEISHU 注释被顺带改写而报告称"其余一行未动" | 成立（历史归因不可得） | 无动作（过程记录，进本报告） | 该文件无变更前快照 ⇒ 归因不可得，内容无害（注释）。本轮补一份改前快照纪律：`snap-task10d-pre-app/` + `snap-task10d-pre-sha1.txt`，本报告 §2 逐文件列 sha1 |
| 8'.4 | `progress.md:183` 说三枚断言、实为四枚 | **不成立** | 已顺带闭合 | 台账自己在 `progress.md:197` 更正为"四枚断言同步（评审原数三枚，实现方纠正为四枚，复评核实成立）"；`:183` 现在说的是 429/503 判定顺序，不含那三个数字。台账归控制器，本轮不越界改 `.superpowers/**` |

### 复评移交（`task-10-brief.md` T10-9）

| # | 条目 | 今天是否成立 | 结论 | 证据 / file:line |
| --- | --- | --- | --- | --- |
| T10-9.1 | 管理员重置腿对不存在账号的 404 一格审计都不写 | 成立 | 已知限制（**不属 §9.1 契约面**） | `app/main.py:459-460`：`get_user_identity(username) is None` → 404「账号不存在」，前后四格（422/500/SUCCESS + 容量 503）都写审计。判定理由：§9.1 的失败值域表**没有 404 这一行**，它枚举的是认证/改密腿（401/403/422/429/503）；这一格在 `system:operate` 鉴权之后、且不产生任何凭据变化，规格里"未知身份给 404 不构成枚举面"的理由块就写在 `main.py:443-444`。补一枚 `PASSWORD/NOT_FOUND` token 会给一个未定义的字段值域新增取值 = 改审计形状 ⇒ 按简报那条线交用户裁定，本轮只在验收文档写明边界。措辞：`管理员重置打到一个不在身份文件里的名字 ⇒ 404 且审计无痕（§9.1 的枚举值域不覆盖 404）。这不是漏检：能走到这一格的主体已有 system:operate 事件面，且未发生任何凭据写入；要给它对着一枚不存在的枚举取值，须先给 §9.1 加行` |
| T10-9.2 | 验收文档不得把 V2.3 的 canary 字面量抄进 `docs/**` | 成立（写作纪律，不是代码） | 无代码动作 ⇒ 交 Task 10e | 本轮读了扫描面的定义才敢说这句话：`_delivery_surface_names()`（`test_secret_hygiene_contract.py:566`）取的是 `git ls-files -c -o --exclude-standard` ⇒ **`docs/**` 在门禁面里**（ tracked 文件全收），而 `backend/data/**` 与 `backend/.env` 被忽略规则挡在外面。`sk-CANARY-…` 是 `_LITERAL_FACE`（`:405`）认得的形状，抄进验收文档就是给扫描面添一处新命中，唯一出路是往 `EXEMPTIONS`（`:453`）加行——那正是这一档设计要免掉的摩擦。做法：按 `路径:行号` 指过去。已在本报告写明，供 10e 直接抄 |

## 2. 本轮改动文件清单（行尾 / sha1 前后）

八枚文件、全部 LF（逐枚 `grep -cU $''` = 0，改后仍为 LF；本轮没有触碰任何 CRLF 文件，
`app/main.py` 与 `backend/.env.example` 一字未动）。`tests/conftest.py` 与
`app/main.py` **零差异**（安全地基没进本轮）。

| 文件 | 改前 sha1 | 改后 sha1 |
| --- | --- | --- |
| `backend/app/credentials.py` | `e2b74e382300c1d5c602cb5e717275a0b05c25c4` | `6ebbbb4ffdc0be5a53cfdf7ee961a8feb3fbeb94` |
| `backend/app/user_store.py` | `8d74e0ae22dfd6290d01aa3f8c01b29f06402706` | `4dc81c4382683381792d8fd27c13159eb01549d6` |
| `backend/app/login_throttle.py` | `c92934b8707f4503865afc51b1957a0555e6d489` | `e4c243fe70e4fac5c2d56f6916542481ae497e08` |
| `backend/app/credentials_migration.py` | `f45b46ef8e2338f0adaadc38be65d43f5209fd67` | `44f450debd7c712adc5f9acf82d44b458d00cf70` |
| `backend/tests/test_credentials_contract.py` | `8c910e15b88fccddc60d9cf3f1f975cff7467c86` | `4dd0880927d83f11cd953b11b6a51c5f19b0704d` |
| `backend/tests/test_authentication_leg_contract.py` | 改前 sha1 未取到（见本节末的过程缺陷） | `5db5bef2e714011e09fb1e7a191033e091a013a4` |
| `backend/tests/conftest.py` | `e3d54ffac1ed3a7ee7276f9d13dc331ba07b0cb7` | 同值（**未改**） |
| `backend/app/main.py` | `4232af1b4bf7d351ca726f6461e699399d501350` | 同值（**未改**） |

**过程缺陷（不遮蔽）**：`snap-task10d-pre-sha1.txt` 在动手前只记了 11 枚文件，测试面那一份只有
`test_credentials_contract.py`；`test_authentication_leg_contract.py` 是读完那两格台账的注释之后
才决定要改的，于是它的改前 sha1 没留档 ⇒ 这一枚文件的 before/after 只能靠快照目录加本报告的
文字复原，归因强度比其余七枚弱一档。规矩建议：下一轮凡进入 `tests/` 就先记 sha1，不等结论成形。

改动分四组：三笔纯注释/文档串（`user_store.py:58-63` 的分派形状、`credentials_migration.py:45-57`
的 `skipped` 合并裁定、`login_throttle.py` 与 `test_authentication_leg_contract.py` 的 docstring
拆雷叙述），一笔死代码删除（`credentials.py` 的 `.lower()`），一笔异常分类（`credentials.py`
的 `needs_rehash`），一笔真实行为改动（`login_throttle.py` 的 `_last_sweep` 起点，含 `reset()`），
其余全在测试面（8 枚新用例 + 1 枚新 planted 形状 + 两枚失败消息）。

## 3. 焦点门的红→绿与计数变化

- **焦点九文件合集**（五枚 SEC-A 门 + 四枚回归门；简报点名的五枚 + 控制器点名的四枚）：
  - 改前基线（动任何一笔之前实测）：**785 passed / 21 warnings / 553 subtests**，0 failed。
  - 改后（`cwd=backend/` 两发、`cwd=` 仓库根 两发）：**793 passed / 21 warnings / 569 subtests**，
    0 failed —— 四个 cwd×发数 的组合给出同一行数字。（中途曾有两次把汇总行读成 `511 subtests`，
    复跑四发确认那是**读错**，不是门在抖；留下这句话是为了下一个读到 511 的人别再去找不存在的抖动。）
  - 归因：**+8 passed** 全部是本轮新增的 8 枚用例；**+16 subtests** 全部是本轮新增的 subTest
    （config 六种绑法 6 + 反向 2、延迟五种形态 5 + 反向 2、写手两段链 1）；`553 + 16 = 569` 逐格对上。既有测试一枚未少、既有 subTest 一格未缩、
    21 枚 warnings 一字未动。
  - 逐枚分解（改前 → 改后）：`test_credentials_contract.py` 83/35 → **89/44**、
    `test_authentication_leg_contract.py` 66/7 → **68/14**、`test_secret_hygiene_contract.py`
    45/0 → **45/0**（**没有新增任何一行 `EXEMPTIONS`**）、`test_security_a_closure.py` 3/0 → **3/0**；
    其余六枚门（`test_password_lifecycle_contract` / `test_user_directory_contract` / `test_typesafe_security_contract` / `test_rbac_contract` / `test_model_router_v23_contract` / `test_llm_egress_guard`）改后实测 **591 passed / 511 subtests**；改前那一发由"基线合集 785/553 减去逐枚实测的三枚 SEC-A 门" 同为 591/511 ⇒ **分毫未动**，fixture 层没有回归（Task 5 那一发的形状）。
- **三枚 SEC-A 关闭门**（简报给的参照 131 passed / 35 subtests）：**137 passed / 44 subtests**。
- 红→绿反证（本轮三处"加宽门"与一处"拆雷"各自演一发：临时改产品/门代码 → 定向跑 → 逐字还原 → 比 sha1）：

| 改动 | 反证（那一发必须红） | 还原 |
| --- | --- | --- |
| 写手扫描加宽两段链（3.9） | 把 `receiver` 解析退回旧写法 ⇒ `MigrationPathTests.test_every_writer_binding_shape_is_counted_as_a_caller` 报 **`SUBFAILED(binding='from app import credentials_migration')`**（`1 failed, 2 passed`）；同发里 `test_only_the_migration_module_may_call_the_legacy_writer` 仍绿 ⇒ 加宽没把真树判红 | sha1 match = True |
| `from app import config` 覆盖面（2.5） | 把 `_imported_names` 退回"只读 `ImportFrom.module`" ⇒ **`3 failed, 1 passed`**，三条指名 `from app import config` / `… as cfg` / `from . import config`；真树那一枚仍绿（`user_store` 的 import 面干净） | sha1 match = True |
| `_last_sweep` 惰性播种（8'.1） | 把 `__init__` 的起点退回 `time.monotonic()` ⇒ `ThrottleLayerTests.test_reaping_does_not_depend_on_the_clock_the_test_injects` **1 failed**（`Items in the second set but not the first`：三格过期桶没被收） | sha1 match = True |
| 延迟词表加宽（5.4） | 由新用例当场自证：`Event().wait()` 两种绑定各命中 1；`str.join` 与 `bucket.allow(...)` 零命中（`join` 明知不收，理由写在词表注释上） | — |
| `needs_rehash` 异常分类（1.4） | 新用例钉 `CredentialConfigError` + `__cause__` 是 `InvalidHashError`；旧行为（裸库异常）下 `assertRaises` 直接不成立 | — |

新增/改动的文本没有带出新的 `KEY="value"` 形状：secret 门 45 枚全绿、`EXEMPTIONS` 一行未加、
`test_secret_hygiene_contract.py` 一字未动。

## 4. 我拒绝做的诱惑

见分诊表内标注（3.5 改名、5.1 动 V2.3 密封文件、6.1 并读、6.2 改公共名、3.6 给 migrate 加第五行、
T10-9.1 新增审计 token、1.2 给 config 加 `ge=1`、§5 把真库哨兵改成读副本），逐条理由已在表里。

另记四条"看得到、量过、决定不动"的：

1. **`_verify_argon2` 里 `needs_rehash` 的第二次库调用**（`app/credentials.py:142,148`）：一条
   verify 已解析过的串再让库解析一次只为算"参数有没有漂移"，可以缓存成一次解析。但那是
   `argon2-cffi` 的内部成本（纯字符串解析，无运算），且收拢它要把 `VerifyOutcome` 的构造
   从"两个入口一条语义"改成"一条入口 + 标志位"——为了微秒改认证面的形状，不动。
2. **`user_store.record_login_failure` 的两条 UPDATE + 一条 SELECT**（`app/user_store.py:307-328`）：
   同一条事务里三次往返，可以合成一次 `UPDATE … RETURNING`。但它今天**没有**乐观锁，
   §7.2 第二层的语义（"第 N 次失败时置锁"）依赖这个读法；改成 RETURNING 要重推一遍并发下的
   计数形状，而那不是本轮任何一条台账要求的事。
3. **`centralisation` 扫描的豁免表宽度**（`tests/test_credentials_contract.py:234+`）：可以给
   `PASSWORD_SITE_SHAPES` 再加"写手赋值给局部变量 / `getattr` 取出"两类形态——但那要先给
   扫描加数据流，产出的是一次性成本极高的实现换一条当前不可达的路径。两文件的注释都已把
   这条边界写成"残留边界"（`_legacy_writer_calls` 的 docstring），按边界处理而不是按缺口处理。
4. **`backend/data/audit.jsonl` 每次跑套件都在长**（本轮实测：它的 mtime 随每一发焦点门推进）。
   它是 `data/` 里唯一真被测试**写**的文件，比 `-shm` 那一格大得多，也是"测试写 backend/data"
   这个提法真正的例外。为什么本轮不动：它**不在门禁面里**——扫描用的三族模式是
   `_LITERAL_FACE`（`test_secret_hygiene_contract.py:405`）/ `_ENV_FACE`（`:419`）/
   `_MATERIAL_FACE`（`:427`），全是封闭的凭据形状族，`"detail": "…"` 这类审计键不匹配任何一族；
   交付文件清单 `_delivery_surface_names()`（`:566`）确实收 `backend/tests/**`（`EXEMPTIONS` `:453`
   里就登记着四行 `backend/tests/*`，各由 `:587-620` 的追问用例负责）。所以往测试文件里塞一条
   形似真审计记录的假事件不会让门红——但它会往交付面里放一条不属于任何运行的事实。
   收口它要给审计面加一枚**会话级换址夹具**（现在只有 `sec_a_fixtures.AuditToTempFileMixin`
   那一枚用例级接缝），而 `data/` 目录本身另有它自己的守卫（`_SESSION_START_CREDENTIAL_ROWS`
   那对哨兵管的是凭据表，管不到 `audit.jsonl`）。⇒ 转 §18。
   措辞：`测试套件仍会把审计事件写进 backend/data/audit.jsonl（未开 AuditToTempFileMixin 的那些例外）：
   该文件 gitignored、不在 §4 的三处扫描面与 §11 的证据面里，收口它属测试地基工程而非 SEC-A 的安全面`。

## 5. Task 10a 留下的活子问题：测试跑动时 `backend/data/conversations.db-shm` 的时间戳被抬

**判定：不是违规，是"打开一份 WAL 模式的真实库做只读"的不可避后果；登记为已知限制（不给措辞以外的动作）。**

证据（本轮在当前树上实测，非推断）：

- 谁在读：`tests/conftest.py:485-500`（`real_user_credential_row_count`，护栏哨兵）与
  `:552-560`、`:588-591`（会话起点/终点各取一次真库凭据行数）。它们用的是
  `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`——**只读 URI**，且派发点在
  `REAL_DB_PATHS`（保护集里的真库清单）上。
- 库里是什么：`PRAGMA journal_mode` 给 `wal`；表集合含 `user_credentials`（5 行 argon2id，
  就是 Task 10 的收敛证据），`SELECT COUNT(*)` = 5。
- 实测的副作用（一次独立的只读打开，前后各取 `st_mtime_ns`）：
  - `data/conversations.db`：**未变**（57344 字节、mtime 17:54:11，即迁移那一次的读数；
    本轮全程 6 次套件跑动后仍是这一枚 mtime）。
  - `data/conversations.db-wal`：**内容未变**（0 字节，全程如此）；它的 mtime 会随套件跑动被抬
    （19:48:25 → 20:38:13，SQLite 打开 WAL 库时对 wal 文件的登记动作），**空文件被碰**不等于有数据写进去。
  - `data/conversations.db-shm`：mtime 被抬（`1790423408917280300 → 1790423601480334700`）。
- 为什么不可避免：WAL 库的读路径必须经 wal-index（`-shm`）——SQLite 要在里面登记读事务、
  判断哪一页的哪个版本可见。`mode=ro` 只关掉**主库文件**的写权限，不改这条协议；换库的
  每一条只读连接（包括验收文档自己要打的 `credentials migration-status`、包括运维用任何
  sqlite CLI 打开一次）都会留下同一格时间戳。要"完全不碰 `-shm`"只有三条路：
  (a) 不读真库 ⇒ 哨兵自删，SECA-04 与会话护栏一起没了；
  (b) 读副本 ⇒ 副本本身要先把真库读出来（复制仍要过 WAL 协议），且哨兵的证据面从
  "这份库现在有几行"退化成"我复制那一刻的快照有几行"——那正是台账里 3.4/L7 反复回避的
  "把门换成间接读数"；
  (c) `immutable=1` ⇒ 向 SQLite 声明"这文件不会变"，在活跃库上是**错误**声明，能读出撕裂的
  快照。三条都比"一条 gitignored 的临时文件的时间戳"贵。

**这条纪律该怎么念**（给 10e 与往后的轮次）：standing rule 的宾语是 `backend/data/` 里的
**验收证据内容**——库里那 5 行 argon2id 的收敛事实、`-wal` 的空、主文件的字节与 mtime，
本轮实测一格未动；不是"该目录下任何 inode 的 atime/mtime 都不许变"。`-shm` 是 WAL 的
共享内存映射文件：无数据、可再生（下一次打开会重建）、gitignored（`.gitignore:7` ⇒ 不进
扫描面、不进提交清单）。把"抬了 `-shm` 的 mtime"判成违规，等价于禁止任何进程只读打开这份库，
包括验收本身。

**落进 L 系列的措辞**（与台账 3.11 合并成一格，L8 候选）：
`测试会话与 CLI 证据命令都会只读打开 backend/data/conversations.db。该库是 WAL 模式，因此
任何一次只读打开都会刷新 conversations.db-shm 的时间戳（wal-index 的登记动作，不是数据写入）；
主库文件与 -wal 的字节和 mtime 不受影响，会话护栏对"真库凭据行数增长"另有直接哨兵。`


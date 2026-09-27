# SEC-A Task 10g 报告（lifespan 从没建过凭据表 ⇒ 全新安装登录 500）

状态：**完成**。改动 3 个文件（其中 `tests/conftest.py` 是被对账逼出来的最小改动，见 §4）。
所有测试计数、sha1、行 endings 都是本轮实测，不是推断。

## 0. 缺陷与裁定出处

- 控制器实测：全新 `CONVERSATION_DB_PATH` + `with TestClient(app)` + `POST /api/auth/login`
  ⇒ `sqlite3.OperationalError: no such table: user_credentials` ⇒ 未处理 ⇒ **HTTP 500**。
  本轮我自己复现了一次（§5 的 MUTATION-1 现场：`assert 500 != 500`）。
- 破了 `docs/SECURITY_A_SPECIFICATION.md` §8.5 企业列自己的承诺
  「`user_credentials` 无行 ⇒ 任何登录统一失败（fail-closed，**非 500**）」。
- 规格已回写（控制器做的）：§8.5 增补段（lifespan 在守卫之后、warmup 之前幂等建表，DDL 失败
  fail-fast，读路径仍然不建表）+ §20.6（第七轮回写，含 SECA-04b 那行"空心形状"的记录）。
- 根因不在读路径的异常处理，而在**一句从没被写下的编排**：`user_store.py:105-113` 与
  `credentials_migration.py:157-160` 两处注释把建表交给「启动编排 / CLI」，lifespan 里此前
  只有守卫 + 两枚 warmup，CLI 那三条动作只在运维敲过之后才生效。

## 1. 一行改动（`backend/app/main.py`）

```python
    security_startup.assert_startup_safe()
    user_store.ensure_user_credentials_schema()      # ← 新增：§8.5 增补段那半句编排
    warmup_identity_permissions()
    warmup_llm_router()
```

- 位置严格是"守卫之后、warmup 之前"；`ensure_user_credentials_schema()` 是
  `CREATE TABLE IF NOT EXISTS` ⇒ 幂等；失败**不 catch** ⇒ 穿出启动阶段 = fail-fast（uvicorn 退出）。
- 同一处 13 行行内注释 + lifespan docstring 都重写为真话：为什么这行存在（那两处注释把责任
  交给启动编排、CLI 只有运维敲过才生效、实测症状是裸 500）、为什么**读路径仍然不建表**
  （env 被清掉时默认落点退回 `data/conversations.db` ⇒ 让读顺手提交 DDL 等于往可能是生产库的
  文件里长出半张凭据表）、以及"只保证表在场、一行为都不写"（§8.2 / M19 那条仍然由唯一建表者
  + 运维显式的 `credentials migrate` 守着）。
- 新增 `from app import security_startup, user_store`（第 40 行），调用写成
  `user_store.ensure_user_credentials_schema()` 而不是 import 那个名字 ⇒ 用例可以 patch
  **源头**那一枚函数（§5 的 fail-fast 钉就是这么做到的）。

## 2. 换行测量（每一次写操作前后都量）

| 文件 | 改动前 | 每次写之后（含最终态） |
| --- | --- | --- |
| `backend/app/main.py` | CRLF=987 / LF-only=0（46436 B） | **CRLF=1004 / LF-only=0（48356 B）**，全程 LF-only 恒 0 |
| `backend/tests/test_security_a_closure.py` | CRLF=0 / LF=321 | CRLF=0 / LF=612 |
| `backend/tests/conftest.py` | CRLF=0 / LF=856 | CRLF=0 / LF=938 |

最终态 sha1（供复核）：`main.py` = `fd6e29fc721dfcc99391c05c1abb349d79141c65`，
`conftest.py` = `ca776368557aa49e9f0c90dd55da33abc301ffaa`（两处都做过 mutation 后再还原，
还原后与此逐字节相同，且 `grep MUTATION` 零命中）。

## 3. 新增测试（`backend/tests/test_security_a_closure.py`，11 → **17**，只增不减）

新增 6 枚 + 一段 10g 引言；`_cold_boot()` 真起 app（`with TestClient(app)` 才跑 lifespan），
§8.5 守卫、被测的那句建表、`/api/auth/login` 整条腿都**不打桩**，只把两枚 warmup 换成 no-op
（继承 `test_secret_hygiene_contract.py::StartupGuardLifespanTests._guard_only` 的既有姿势：
`warmup_llm_router()` 按 cwd 解析注册表，本套件从 `backend/` 与仓库根两种 cwd 跑；它们会不会被
调用另有 `test_llm_usage_contract.py::WarmupWiringTests` 钉着）。

1. `test_a_fresh_install_cold_boot_answers_login_with_the_unified_401` — **这就是坏掉的那一枚**
   （docstring 里这样命名）。`raise_server_exceptions=False` 让"非 500"是一条**响应**断言：
   `500 != status` + `401 == status` + `"用户名或密码错误"` + 审计 token `invalid_credentials`。
2. `test_enterprise_cold_boot_logins_are_the_uniform_401_and_never_a_500` — §8.5 企业列第一次
   在部署面被钉：三格守卫全过（`SECURITY_ENTERPRISE_MODE=true` + 48 字符假 secret +
   `https://kb.example`）⇒ 起得来；库里 0 行；两条登录（demo 名与一个不存在的名字）**同一张脸**：
   同一 401、同一段中文、同一枚 token，且都不是 500。
3. `test_the_app_boot_creates_the_table_while_a_bare_read_still_does_not` — 两侧同钉：boot 之后
   那份文件里表在场；另一份全新库只打一次读 ⇒ `OperationalError` 且**文件里仍然没有那张表**
   （判据取文件，不取异常消息 ⇒ "把 DDL 搬进 `_connect()`" 那种"同样能让 1、2 变绿"的写法在这里红）。
4. `test_booting_twice_on_a_file_that_already_has_rows_changes_nothing` — 幂等：先按"运维建过表、
   种过行"的形状放一份模板库（`install_demo_credentials` 走整份复制 ⇒ 零 Argon2 重算），
   两遍冷启动后登录仍 200 + 键集齐，`count_by_algorithm()` 一格不变（"表还在"与"行还在"取后者）。
5. `test_a_failing_schema_step_refuses_to_start_the_process` — fail-fast：patch
   `user_store.ensure_user_credentials_schema` 抛 `sqlite3.OperationalError` ⇒ 异常穿出
   `with TestClient(app)`；`with` 体里那句 `pytest.fail` 是"它竟然起来了一台会服务的 app"的证据。
6. `test_the_widened_guard_lets_through_exactly_that_one_ddl` — 见 §4：我为护栏配的那份放宽
   自己的效应钉（三个方向）。

配套：模块 docstring 加 10g 那一段；两枚假 secret 常量用拼接构造（`"x" * 48`）并按
`sec_a_fixtures.LongJwtSecretMixin` 的理由给 dev 也配 ≥32 字节 ⇒ 本文件警告数**没有**漂移
（跑完仍是那枚原有的 1 warning）。

## 4. 对账一：Task 10f 那枚"harness 入口 alone 不建表"的**陈述目标**被改写（reviewer 必须看见）

10f 的 `test_harness_entry_point_alone_leaves_no_credential_schema` 原 docstring 一句话塞了两件
事：「`init_usage_db` 单独跑时凭据 schema 压根不在场（**生产侧没长出自动建表那条腿**）」。
第二半句在 §8.5 增补段之后**不成立**了。处理是**拆开、不翻转、不删、不放宽**：

- 该枚 docstring 重写成三分法并**指名这是 Task 10g 改的陈述目标**：① `usage.init_usage_db()`
  那枚建库入口不建凭据表；② `user_store` 的**读路径**不建表；③ **app 的 lifespan 建**
  （判据指向本文件 10g 那一段）。①② 由这一枚继续看守（接缝仍然必须存在，因为 sealed P0 走
  的是①那条入口而不是③），③ 由新增用例看守。
- **加了一枚断言**（只增强）：那次裸读之后再点一次表清单 ⇒ 若 DDL 搬进 `_connect()`，
  本枚从"绿"变"红"，而不是被静默放宽。实测该判据可红（§5 的 MUTATION-3 对照）。
- 文件顶部与模块 docstring 里那句"生产侧没长出自动建表那条腿"同步改成三分法表述。
- 计数：11 → 17，没有删除任何用例，没有把任何断言改宽。

## 5. 对账二：`conftest.py` 的会话护栏与 lifespan DDL 撞车（最小改动 + 理由）

**现场（先撞上再改，不是预防性改动）**：只做 §1 那一行改动之后，
`tests/test_llm_usage_contract.py::WarmupWiringTests::test_lifespan_calls_both_warmups_side_by_side`
报 error：`7 passed, 1 error`，失败信息是"测试往保护集下的真实库里**写**了凭据行"。
根因：该类的 `_UsageFixture.setUp` 用 `mock.patch.dict(os.environ, {}, clear=True)` 关宿主 env
（Task 1 就在用的隔离手法，brief 也禁止我改它），于是 `user_store.database_path()` 退回默认值
⇒ 会话护栏**照旧改道**（真库一个字节没动，失败信息里能看到改道目标就是会话临时库）、
但那笔 `CREATE TABLE` 被 `_WRITE_STATEMENT` 升成 **write** ⇒ 逐例归责钩子把一次合法冷启动
建表判红。`test_credentials_contract.py` 里另有三条钉明确要求"DDL 也必须判 write"
（`CredentialStoreGuardTests::test_a_schema_creation_on_the_redirected_path_is_a_write_too` 等），
而那些文件不许我改 ⇒ 出路只能在 conftest 里，且必须**只**放宽"从唯一建表者进来的那一枚 DDL"。

做法（`LedgerGuard`，+82 行，全部带理由注释）：
- `install_credential_store(store_module, *, watch_schema_funnel=False)`：为 True 时**多挂一道闸**
  在 `ensure_user_credentials_schema` 上，用线程局部的 `schema_depth` 标出"在唯一建表者的漏斗里"；
  表名正则取自 `store_module.TABLE_NAME`（不再抄第二份字面量）。
- `_is_funnel_schema_ddl()`：**两个条件缺一个都判红** —— 栈必须在漏斗之内，语句必须是
  `CREATE TABLE IF NOT EXISTS <凭据表>`。于是 DML（启动顺手造行 = M19）与"漏斗外建表
  （= 读路径建表）"两侧仍然升到 write。跳过时**不置 `pending.done`**，同一条连接里后来的
  DML 仍然能把那一笔升上去。
- **只有会话那一个实例**传 `watch_schema_funnel=True` ⇒ 契约用例自建的探针实例恒 False，
  那三条"DDL 也必须判 write"的归类钉一字未动（已实测：`test_credentials_contract.py` 全绿）。
- 那一笔仍然**被记录**（kind=read）⇒ 仍在 `credential_redirects()` /
  `credential_read_redirects()` / 收尾 `[credential-guard]` 汇总里数得到，不是静默。
- 文档同步：模块 docstring 的"第二张表"段、`credential_guard_is_active()` 的 docstring
  （并说明第三道闸**不在**那枚等式里，因为它的缺席是响的：会被逐例归责钩子当场判红）、
  会话收尾那句失败信息里的"两道闸"改成点名那两枚。`guard logic` 之外的判定阈值、保护集、
  改道目标、env 层一律未动。

新增第 6 枚用例（§3 列表最后一条）给这份放宽配效应钉，三方向各一枚断言。
**MUTATION 实测**（都是临时改、跑、还原、验 sha1）：
- MUTATION-1（删掉 lifespan 那一行）⇒ 新用例里 **4 红 1 绿**：1/2/3/5 红（回归本体那枚的失败
  信息正是 `assert 500 != 500`），4 绿是**预期的**（它的前提出点是"表与行已在场"，管的是幂等，
  不是存在性）。
- MUTATION-2（把 `_is_funnel_schema_ddl` 改成"漏斗内一律放过"）⇒ 第 6 枚红在
  `同一座漏斗里写出**行**也被放过 ⇒ M19 静默`。
- MUTATION-3（把 `schema_depth` 那道判据去掉）⇒ 第 6 枚红在
  `漏斗之外的建表被放过了 ⇒「读路径不建表」这条裁定失去护栏`。
- 另一侧对照（在系统临时目录里跑的一段 `python -c`，**没有**改 `user_store.py`）：把
  `_connect()` 桩成"顺手建表" ⇒ 裸读返回 `None`、文件里长出 `user_credentials`；
  真实现下同一枚读法抛 `no such table`、文件里 0 张表 ⇒ 用例 3 与 10f 那枚新断言都可红。

## 6. 实跑计数（focused only；全套件按排期留给下一次）

| 命令 | 结果 |
| --- | --- |
| `pytest tests/test_security_a_closure.py -q` | **17 passed**, 1 warning（43–50s） |
| 同上 `-k "cold_boot or app_boot_creates or booting_twice or failing_schema_step"`（MUTATION-1 下） | 4 failed, 1 passed |
| `pytest tests/test_llm_usage_contract.py::WarmupWiringTests -q`（护栏对账**前**） | 7 passed, **1 error**（撞车现场） |
| 同上（对账**后**） | **7 passed** |
| `pytest tests/test_credentials_contract.py tests/test_secret_hygiene_contract.py -q` | **137 passed, 44 subtests passed**（含 SECA-20 那道 `豁免表 == 命中表` 的门：本任务新增字面量 0 命中、不加豁免行） |
| `pytest tests/test_llm_usage_contract.py tests/test_llm_egress_guard.py ::LedgerIsolationGuardTests ::LedgerGuardClassificationTests -q` | **144 passed, 125 subtests passed** |
| 最终四文件合跑（closure + credentials + secret_hygiene + llm_usage） | **254 passed, 77 subtests passed**，会话级 `[credential-guard]` 零 write 改道 |

## 7. 边界与"没碰什么"

- 只改 3 个文件：`backend/app/main.py`、`backend/tests/test_security_a_closure.py`、
  `backend/tests/conftest.py`。未碰 `user_store.py` / `auth.py` / `credentials*.py` /
  `docs/SECURITY_A_*` / `frontend/**`；`real_llm_failover_kit.py` 最终**未改**（对账不需要它）。
- 封版文件 `backend/tests/test_real_llm_failover_acceptance.py`
  sha1 `da92cdf51de5dbfad3107f1dc744d18e4173e07c`，本轮开工前后**逐字节相同**。
- 未跑任何 git 写命令；`model-router-v2.3-rc1` 未动；无任何外部 API 调用；
  未把明文口令 / legacy 摘要 / 现网形状密钥写进任何文件或输出（本轮所有假值都是拼接构造，
  且 SECA-20 的门复确认命中数一枚不加）。
- **`backend/data/` 需要如实报两件事**：
  1. `backend/data/conversations.db` 本尊 **mtime 未变**（17:54:11.64，尺寸 57344 B），
     `user_credentials` 仍是 **(5, 'argon2id')** 那五行验收证据；`audit.jsonl` mtime 未变（21:02）。
     没有任何一次跑动把行写进它。
  2. 但 **WAL 侧文件的 mtime 动了**：`conversations.db-shm` → 23:15:19、
     `conversations.db-wal` → 23:01:37（wal 恒 **0 字节**）。成因是**只读**打开：
     `conftest.py` 会话哨兵 `real_user_credential_row_counts()` 以 `file:...?mode=ro` 点数真库，
     而 WAL 模式下只读读者也要映射 `-shm`/`-wal`；本轮我自己那条只读点数的 `python -c` 也算一次。
     这是**既有**行为（我开工前那两份 sidecar 的 mtime 就已经是 22:29/22:30，属控制器的探针），
     下一次全套件跑动同样会动它们。主库文件与 5 行证据未被写过，这一点由 mtime + 行数 + wal
     0 字节三格共同成立。

## 8. 需要 reviewer 裁/知道的三件事

1. §4 那处**改的是用例的陈述目标**（不是放宽，还加了一枚断言），按 brief 要求显式登记。
2. §5 那处**动了 `conftest.py` 的归类逻辑**（brief 默认禁止，被两条不许改的文件里的钉逼出来的
   最小出路）。如果 reviewer 认为更该改 `test_llm_usage_contract.py` 的 `_UsageFixture`（别清
   `CONVERSATION_DB_PATH`），那是一条等价替代，但那个文件不在本任务允许面内。
3. 会话护栏的第三道闸**不在** `credential_guard_is_active()` 的属性等式里（理由写在 docstring：
   它的缺席会被逐例归责钩子当场判红，MUTATION 反向验过：把 `watch_schema_funnel=True` 拿掉 ⇒
   `WarmupWiringTests` 立刻 error）。刻意不为此再造一枚"闸在场"的钉，以免变成对实现的复述。

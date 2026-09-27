# Task 4 报告 — 身份声明层（`app/directory.py` + `config/users.json` / `users.demo.json`）

状态：**DONE**（含 6 处对简报代码的偏离，其中 1 处是简报自身的内部矛盾；全部逐条列在 §4）
形态：无 commit。工作树 + 快照（`snap-task4-app` / `snap-task4-config`）+ 本台账行。

---

## 1. 落地清单

| 文件 | 动作 | 规模 | 换行 |
| --- | --- | --- | --- |
| `backend/app/directory.py` | 新建 | 216 行 / 10 661 B | LF，无 BOM，末尾有换行 |
| `backend/config/users.json` | 新建（企业身份，出厂为空） | 3 行 / 23 B | LF |
| `backend/config/users.demo.json` | 新建（5 条 demo 身份） | 9 行 / 449 B | LF |
| `backend/config/llm_registry.json`、`feishu_permissions.json` | **未动**（差分零命中） | — | 原样 |
| `backend/app/config.py` | 加 `security_enterprise_mode`（置于 `jwt_secret` 之前） | 本任务 +4 行（`git diff --numstat` 给 8，另 4 行是前任务未提交的 argon2 键） | 保持原 CRLF（见 §8） |
| `backend/app/knowledge_os.py` | 四处身份读点 + import + 2 行 WHY 注释 | +15 / −12 | LF 保持 |
| `backend/tests/test_user_directory_contract.py` | 新建契约件 | 523 行 / 28 839 B / 49 例 / 37 subtests | LF |
| `backend/app/auth.py` | **未动**（`USERS` 保留给认证腿那一次原子切换） | — | — |

产出的公开接口与简报 `Produces` 逐一对应：`ENTERPRISE_IDENTITIES_FILE` / `DEMO_IDENTITIES_FILE` /
`FORBIDDEN_IDENTITY_KEYS` / `IdentityConfigError` / `UserIdentity`（`extra="forbid"`，五字段）/
`load_identities(*, include_demo)` / `identities()` / `get_identity()` / `reset_cache()` /
`override_identities()`。

`users.demo.json` 由脚本从 `app/auth.py:71-103` 的 `USERS` 生成（`username/display_name/role` 三键，
口令字段不带），并在同一脚本里逐条复算 `文件记录 == auth.USERS[u]` 的三键等值 +
`set(record) == {"username","display_name","role"}` + 五枚 `password_hash` 字面量在文件字节里 0 命中
⇒ 三项全 True。零手抄。

## 2. 简报 Step 1–10 的执行情况

- **Step 1（先测再写）**：已测。`backend/config/` 存在（`llm_registry.json` = V2.3 的模型注册表、
  `feishu_permissions.json`）；`grep -n "COPY config" backend/Dockerfile` →
  **`18:COPY config ./config` 早就在**，`WORKDIR /app`（= `backend/`）⇒ 新增两枚身份文件随镜像打包，
  **本任务不需要改 Dockerfile**（未改）。
- **Step 2/3**：先写测试并跑红（§5）。
- **Step 4**：实现落地，偏离见 §4-D1…D6。
- **Step 5**：`security_enterprise_mode: bool = False` 加在 `jwt_secret` 之前，注释按简报措辞。
  未加进 `backend/.env.example` —— 该清单归 secret/env 那一档任务（同一先例：Task 1 的
  `ARGON2_MAX_CONCURRENT_OPS` 也没进，且现有 `.env.example` 的同步测试按**点名键表**判，
  新增 Settings 键不会让它红，已实测全套件 warnings/计数不变）。
- **Step 6/7/8**：见 §3、§6。
- **Step 9**：定向门 + 全套件两 cwd 等数（§5）。
- **Step 10**：快照 `snap-task4-app`（52 个 .py，剔除 `__pycache__`）、`snap-task4-config`
  （4 份文件），`cmp` 逐字节相同；台账已记（含两枚 Ruling + 简报缺陷）。
- **未做**：`auth.USERS` 不删、`enabled=false` 不参与登录行为、不加 `SEC-A-010` 的启动守卫
  —— 三件都是后续任务的边界，简报明确划走。

## 3. `knowledge_os.py` 四处身份读点（before → after）

| # | 位置 | before | after |
| --- | --- | --- | --- |
| 0 | `:24` import | `from app.auth import CurrentUser, USERS, require_permission, require_user` | 同行去掉 `USERS`；新增 `from app.directory import identities as directory_identities, get_identity`（按字母序落在 `app.config` 与 `app.ingestion` 之间） |
| 1 | `:560-562` 部门计数 | `record = USERS.get(str(event.get("username")))` → `if record:` → `ROLE_DEPARTMENT.get(str(record.get("role")), "其他")` | `identity = get_identity(str(event.get("username")))` → `if identity:` → `ROLE_DEPARTMENT.get(identity.role, "其他")`（下标读法 → 属性读法；`role` 已由模型保证是 `str`，`str()` 去掉） |
| 2 | `:564` 采用率分母 | `total_users = max(len(USERS), 1)` | `total_users = max(len(directory_identities()), 1)` |
| 3 | `:567` 上报总人数 | `"total_users": len(USERS)` | `"total_users": len(directory_identities())` |
| 4 | `:694-705` 成员名册 | `for record in USERS.values()` + `record["username"]` / `record["display_name"]` / `record["role"]` / `ROLE_DEPARTMENT.get(str(record["role"]), …)` / `last_login.get(record["username"])` | `for identity in directory_identities().values()` + 五个属性读法；`"status": "ACTIVE"` **原样不动**（见 §7-1） |

差分面：`git diff --stat` = `2 files changed`，`knowledge_os.py` 只含上述四处 + 两行 WHY 注释；
出口面未动 ⇒ `tests/test_llm_egress_guard.py` **35 passed / 92 subtests**，D6 豁免计数一字未改
（简报 Step 9 预警的正是这条）。

## 4. 偏离简报的每一处，与理由

**D1（简报内部矛盾，必须先看这条）** — 摘要形态判定的宽度。
简报 Step 2 的用例把 `display_name` 写成 `"a" * 40` 并要求拒收；简报 Step 4 的实现按
`^[0-9a-f]{64}$` 判。40 位不匹配 64，`UserIdentity.display_name` 的 `max_length` 又是 64 ⇒
**逐字实现的简报跑不过逐字简报的用例**（这条不是推论：§5 的第二次 RED 是把 `{64}` 逐字装回去实测的）。
裁定：形态判定改成"纯 hex 且 ≥40 位"（`^[0-9a-f]{40,}$`，先 `strip().lower()`），它**包含**规格 §6.4
点名的 64-hex 形态，另外覆盖 SHA-1(40)/SHA-384(96)/SHA-512(128)；下限停在 40 而不是 32 的理由写在
代码注释里并钉了反向用例（32 位纯 hex 恰是 UUID 去连字符的长度，把机器账号拒在启动期的代价
高于顺带拦下 MD5 的收益）。**计划正文若被复用，这一枚正则要同步改。**

**D2** — 形态扫描改为**递归**（简报只扫 `raw.values()` 的一层字符串）。
理由不是整齐：`{"display_name": {"password": "…"}}` 这类嵌套在简报版里会一路走到 pydantic，
而 pydantic 的默认报错文本**回显输入值**，那份值可能是从口令表里粘来的 ⇒ 凭据材料进启动日志。
递归扫描把这条路径挡在校验器之前。用例：三种嵌套形状 + "报错面不含哨兵值"（`test_a_rejection_never_echoes_a_field_value`）。

**D3** — 字段校验器的报错不再内插 `{exc}`（简报内插），改取 `loc + type` 列表。
理由同 D2 的最后一环：外层消息是**可被上层打印**的面，`exc` 的文本里有 `input_value=…`。
原文仍在 `__cause__` 链上（`from exc` 保留），定位能力不减。这一条不依赖 pydantic 的新版 API
（`errors()` 的 `include_input` 参数在本仓 requirements 的下界 `pydantic>=2.8` 上不保证存在，
所以按 `loc`/`type` 自己组装，而不是调那个 kwarg）。

**D4** — `_validate_records(path, payload=None)`：默认值 + **传值即拒**（简报是两个必填形参、
调用点显式传 `None`、函数体完全不读它）。简报自己的裁定是"不许留成死参数"，而它给的形态恰好
就是死参数，并且更坏：将来谁真传了 `payload`，函数会**静默忽略它去读文件**。改成默认参数
（调用点不再出现 `None` 噪声）+ 一条 `IdentityConfigError`（"内存直传路径尚未实装"）+ 一枚用例
钉住。若到下一个任务仍无人传，按简报裁定删掉整参数。

**D5** — `feishu_open_id: str | None = Field(default=None, min_length=1)`（简报无 `min_length`）。
唯一性只管"非 null"的取值；`""` 若算有值，两个都没接飞书的账号会撞在同一条检查上，而报错消息
指向 open_id，运维看不出问题在"空串不等于没填"。现在空串直接拒（钉一枚用例），并另钉一枚
"两条都没有 open_id 合法"防过判。

**D6** — 重名冲突的消息措辞由"（{source}）——demo 身份不得覆盖企业身份"改为
"（{source}）——后加载的身份不得覆盖先加载的（demo 文件不得改写企业身份）"。
原措辞在**同一份文件内部重名**（简报版也拒，因为 `merged` 逐条累加）时会说错话，指向一个不在场的
demo 文件。跨文件冲突仍点名 `config/users.demo.json`（用例断言这一点）。

**简报之外新增的测试面**（简报 9 + 1 枚逐字保留，另加 39 枚）：`CredentialShapeRejectionTests`
（四种字符串字段各塞 64-hex、大写/其它长度/带空白、PHC 串、嵌套凭据键、非摘要长值不误判、
报错不回显、空串 open_id、两条无 open_id 合法）、`IdentityDocumentShapeTests`（顶层键封闭、
非对象记录、坏 JSON、GBK/UTF-16 读不出来、路径被目录占住、占位参数不静默接活）、
`MergeInvariantTests`（同一份文件内重名/重 open_id、冲突消息点名文件、坏 demo 文件碰不到
企业形态那一次读）、`DirectoryReadFaceTests`（形态跟随开关、按形态各缓存一次、`reset_cache`、
`get_identity` 未知返 None、`override_identities` 可见且**异常也还原**）、
`ShippedIdentityFilesTests`（两文件在场且过自己的校验器、企业文件出厂为空、demo 恰为五个人、
两枚常量仍是相对路径=部署口径、出厂记录零越界键）、`IdentityCredentialSeparationTests`
（AST：不 import hashlib/argon2/sqlite3/hmac/secrets；`app.*` 只允许 `app.config`；不调受限写手
`import_legacy_digest`）、`EnterpriseModeSwitchTests`（键存在、默认 False、类型 bool、
进程里的 `settings` 实例确实是关的）、`KnowledgeOsReadPointTests`（见 §7）。

## 5. TDD 证据

**RED**（实现文件还不存在时；日志
`C:/Users/zhang/.qoder/cache/project/E--xiangmu/rag/.superpowers/sdd/SECURITY_A_PLAN/tmp/focused-8e44746d693944bb989911222a8c6a65.log`）

```
cd /e/xiangmu/rag/backend && python -m pytest tests/test_user_directory_contract.py -q
tests\test_user_directory_contract.py:22: in <module>
    from app import directory  # noqa: E402
E   ImportError: cannot import name 'directory' from 'app' (E:\xiangmu\rag\backend\app\__init__.py)
ERROR tests/test_user_directory_contract.py
!! Interrupted: 1 error during collection !!
```

为什么这是预期红：身份层这个模块本就还没写，收集期在 `from app import directory` 上就断。
简报 Step 3 期望的措辞是 `ModuleNotFoundError: No module named 'app.directory'`；实测是
`ImportError: cannot import name … from 'app'` —— `app` 是个包，包属性找不到时 Python 抛的是
`ImportError` 这一支。**同因不同措辞**，不是另一种失败。

**RED（第二次，简报缺陷的实测证据）**：把 `_HEX_DIGEST` 逐字换回简报的 `^[0-9a-f]{64}$` 后单跑简报
那枚 40 位 hex 用例（同一脚本里逐字节还原，`restored: True`）——

```
    def test_a_legacy_digest_value_is_rejected_even_under_an_allowed_key(self):
        _write(self.enterprise, [{"username": "admin", "display_name": "a" * 40,
                                 "role": "ADMIN"}])
>       with self.assertRaises(directory.IdentityConfigError):
E       AssertionError: IdentityConfigError not raised
FAILED tests/test_user_directory_contract.py::IdentityFileTests::test_a_legacy_digest_value_is_rejected_even_under_an_allowed_key
```

即：**逐字实现的简报跑不过逐字简报的用例**，这条红不是我从别处推的。处理方式见 §4-D1。

**GREEN**（终态；日志 `…/tmp/green-8e44746d693944bb989911222a8c6a65.log`）

```
### 1 focused (backend cwd)              49 passed, 37 subtests passed in 28.39s
### 2 identity-migration gate           135 passed, 9 warnings, 194 subtests in 63.02s
    (test_rbac_contract / test_typesafe_security_contract / test_feishu_identity_contract)
### 3 SEC-A scans                        68 passed, 35 subtests passed（0 warnings）
### 4 egress guard                        35 passed, 92 subtests passed（D6 计数未动）
### 5 full suite from backend          1078 passed, 36 warnings, 1076 subtests in 111.58s
### 6 full suite from repo root        1078 passed, 36 warnings, 1076 subtests in 90.28s
```

对账：基线（进本任务时）`1029 passed / 36 warnings / 1036 subtests` ⇒
测试 **1029 + 49 = 1078** ✓；subtests `1036 + 37（本文件）+ 3 = 1076` ✓——那 3 枚来自既有
"逐文件 `subTest`" 的 app 全量扫描面（新增 `app/directory.py` 自然各多一行），已核：
`test_credentials_contract.py` 自身仍是 68/35 未涨。warnings **36 → 36**，一条未加。
两 cwd 数字逐位相等 ✓。

## 6. 过渡一致性钉的确切形态

`backend/tests/test_user_directory_contract.py` 文件末尾一枚类，**唯一用例**：

```python
class TransitionalConsistencyPin(unittest.TestCase):
    """Task 4→5 期间 `auth.USERS` 仍在（认证腿还没切）。这枚钉防两份身份漂移。

    Task 5 删除 `USERS` 时**连这个类一起删**，不要改成"跳过"。
    """

    def test_directory_and_the_legacy_constant_table_describe_the_same_people(self):
        from app import auth

        with mock.patch.object(directory, "ENTERPRISE_IDENTITIES_FILE", SHIPPED_ENTERPRISE), \
                mock.patch.object(directory, "DEMO_IDENTITIES_FILE", SHIPPED_DEMO):
            loaded = directory.load_identities(include_demo=True)
        self.assertEqual(set(auth.USERS), set(loaded))
        for username, identity in loaded.items():
            self.assertEqual(auth.USERS[username]["display_name"], identity.display_name)
            self.assertEqual(auth.USERS[username]["role"], identity.role)
```

与简报的两处差别（都是"让它真的成立"）：

1. **绝对路径锚定**：`SHIPPED_ENTERPRISE = BACKEND_DIR / "config" / "users.json"`。简报版直接
   `directory.load_identities(include_demo=True)`，走的是 `Path("config/users.json")` 的 cwd 口径 ⇒
   从仓库根跑就会 `IdentityConfigError: 身份文件不存在`（本仓有前例：`config\llm_registry.json`
   的 FileNotFoundError 就红过一次），两 cwd 不可能等数。锚到 `BACKEND_DIR` 之后，钉的是
   **随镜像打包的那份文件**，与"当前工作目录恰好是什么"无关——这比 chdir 更强（chdir 也会让
   别的相对路径事实跟着漂）。既有先例：`test_model_router_v23_contract.py` 的 cwd 钉。
2. `include_demo=True` 显式（简报原文），dev 形态口径 = 两份合并后的全集，才与 `auth.USERS` 同域。

它今天能钉住的漂移面：用户名集合、`display_name`、`role`。钉不住 `enabled` 与
`feishu_open_id` —— 因为 `USERS` 里根本没有这两格（前者本任务新增，后者只在注释里出现过）。
`USERS` 被删除的那一天，本类连同 `auth` 的引用一起消失；若有人把它改成 `skipIf`，全套件仍然绿，
而这枚钉的全部价值就是"两份真源不许并存两轮"，所以措辞里写死了"连类一起删"。

## 7. 自审发现（读自己的 diff 得到的，不是跑测试得到的）

1. **`list_users` 的 `"status": "ACTIVE"` 是硬编码，`enabled` 没接到展示面。** 我没有顺手改：
   简报把 `knowledge_os.py` 的编辑面限定在四处读点，而"停用的人在名册里显示什么"是行为改动。
   交接下一任务：哑校验落地时一并裁定，否则 `enabled=false` 的账号在成员页仍是 ACTIVE。
   （今天不可达：出厂 `users.demo.json` 五条全 `enabled=true`，`users.json` 为空。）
2. **企业形态下 `usage_summary` 的算术**：`users.json` 为空 ⇒ `total_users=0`，
   而 `adoption_pct` 的分母是 `max(0,1)=1` ⇒ 若有历史 QUERY 审计行，采用率会 >100%。
   默认开关关（dev 形态 5 条）时与迁移前逐字相同，所以这不是本任务的回归，而是企业形态
   被第一次真正暴露出来的一条既有语义；记在这里给启动守卫/前端显示那一档。
3. **`FORBIDDEN_IDENTITY_KEYS` 与 `extra="forbid"` 在"拒收"这一层是重叠的**（任何未知键本来就被拒）。
   黑名单独立承担的是**诊断**："这里不许放凭据"而不是"字段拼错了"——后者会被"换个名字再来一次"
   修掉。我本来给它钉不到独立用例（把黑名单整体删掉，简报那枚用例仍绿，因为是 pydantic 在拒），
   所以补了一枚 `test_a_credential_key_is_named_as_such_not_as_a_typo`（断言消息含"凭据字段"），
   并用变异 M3 证明它现在真的有牙。
4. **`test_the_directory_is_loaded_once_per_mode` 与缓存的耦合**：这枚钉断言"改文件不 reload"，
   它同时是本模块"形态在进程生命周期内不变"这条设计决定的唯一用例。若哪天要上身份热加载
   （规格 §8.6 明确不做），这枚钉会先红，是对的。
5. 未做也**不需要**做的：`directory` 没有 logging（无口令可泄露）、没有 `__all__`
   （与同目录其它模块一致）、不 import `app.config` 在模块级（否则形态判定会被 import 顺序绑住）。
6. `app/identity/`（飞书桥接）与本模块的 `UserIdentity` 是两个不同的东西，命名容易撞车：
   那边是"外部身份→授予"的解析器，这边是"身份声明记录"。注释里点明了唯一真源，
   但**下一次读到 `app.identity` 与 `app.directory` 并列的人会需要这条说明**。

## 8. 字节与形态核查（防"文本模式写文件翻 CRLF"那一类）

```
app/directory.py                      bytes=10661 lines=216 crlf=0   bom=False ends_nl=True
app/knowledge_os.py                   bytes=38221 lines=929 crlf=0   bom=False ends_nl=True
app/config.py                         bytes=10925 lines=182 crlf=182 bom=False ends_nl=True
config/users.json                     bytes=23    lines=3   crlf=0   bom=False ends_nl=True
config/users.demo.json                bytes=449   lines=9   crlf=0   bom=False ends_nl=True
tests/test_user_directory_contract.py bytes=28839 lines=523 crlf=0   bom=False ends_nl=True
```

- 新建的三份文件全 LF，与既有 `config/llm_registry.json`(LF/0 CRLF)、`app/auth.py`(LF) 同轨。
- **`app/config.py` 的工作副本整体是 CRLF，且这不是本任务造成的**：`snap-task1-app/config.py`
  就是 178 CRLF/178 LF（开工前的 checkout 形态，本仓 `core.autocrlf=true` 且无 `.gitattributes`），
  我只让 Edit 保持原形态。**没有**顺手翻齐：翻齐会让 `diff -u`/`diff -r` 报出 182 行整文件重写，
  正是简报点名要避免的幻影 diff；`git diff` 因 autocrlf 清洗也仍然只认那 4 行新增。
  留一条建议给收口：真要治，就加 `.gitattributes`（`*.py text eol=lf`）一次治全仓，别单文件翻。
- 工作树除本任务产出外无新增文件：`git status --porcelain` 只列
  `directory.py` / `config/users*.json` / `test_user_directory_contract.py` 三枚新文件与
  `config.py` / `knowledge_os.py` 两枚改动（其余是前三个任务的未提交件）。探针脚本在仓库外，
  未进树。

## 9. 变异自检（临时改产品代码 → 跑焦点 → 逐字节还原）

12 发全部 KILLED，每发还原后 `path.read_bytes() == original` 为 True（日志
`…/tmp/mutation-8e44746d693944bb989911222a8c6a65.log`）；另有第 13 发是 §4-D1 的缺陷实测
（`{40,}` → `{64}`，同样逐字节还原），结果记在 §5。

| # | 变异 | 杀它的用例 |
| --- | --- | --- |
| M1 | 重名检查短路成 `if False`（= `{**enterprise, **demo}` 语义） | 跨文件重名 + `IdentityFileTests` 合并钉（3 failed） |
| M2 | 摘要形态检查整体失效 | 40/64 位 hex、大写、PHC、嵌套、不回显（7 failed / 31 subtests） |
| M3 | 敏感键黑名单整体失效 | §7-3 那枚诊断钉（1 failed） |
| M4 | `include_demo=not mode` 改死为 `True` | `test_the_read_face_follows_the_mode_switch`（1 failed） |
| M5 | open_id 唯一性不判 | 跨文件 + 同文件重 open_id（2 failed） |
| M6 | `override_identities` 的 finally 不还原 | 可见性 + 异常路径还原（2 failed） |
| M7 | `enabled` 默认值翻 False | `test_default_is_enabled` + 名册投影（2 failed） |
| M8 | 校验器报错回显输入值 | `test_a_rejection_never_echoes_a_field_value`（2 failed / 35 subtests） |
| M9 | `feishu_open_id` 去掉 `min_length=1` | 空串那枚（1 failed） |
| M10 | 部门不再由身份 role 派生（写死"其他"） | `usage_summary` 的 `top_department`（1 failed） |
| M11 | `total_users` 退回常量 5 | `usage_summary` 的 `total_users`（1 failed） |
| M12 | 总开关默认值翻 true | 开关默认值两枚（含进程内 `settings` 实例）（2 failed） |

M11 值得单看：把 `total_users` 写回 5 在 dev 形态下**行为等价**，只有"分母来自目录"这条断言
（`self.assertEqual(3, payload["total_users"], "总数来自目录…")`，配合 `override_identities`
注入的 3 人集）杀得掉——这正是把四处读点从常量换成真源之后必须新长出来的那枚钉子。

## 10. 顾虑与交接（不含已闭环项）

1. **`enabled` 目前只在身份侧存在**，消费面为零（简报规定，登录行为不在本任务）。
   下一任务把它接进哑校验时，`list_users` 的 `status` 与 `usage_summary` 的 `total_users`
   是否算停用的人，要一起定，否则名册会说谎（§7-1、§7-2）。
2. **`_validate_records` 的 `payload` 占位**：现在"传值即拒"。下一个任务若不引入内存直传的
   调用方，就按简报裁定把整参数删掉；留着就是两个人任务前的同一处坑。
3. **`identities()` 不做热加载**（规格 §8.6 认了这条：改身份需重建镜像或挂载覆盖 + 重启）。
   运维体检查在 §8.6，不在本任务；但 `users.json` 随 `COPY config` 打包 ⇒ 挂载覆盖时注意
   镜像里那份**空**的 `users.json` 会成为默认形态的唯一身份源，企业形态出厂是零账号。
4. **形态判定与 `main.py` 启动守卫之间还没有接线**：`security_enterprise_mode` 本任务只被
   `directory.identities()` 消费；JWT secret / CORS 那两件按 §8.5 必须同生同死，落在
   下一档的守卫任务里（这也是"默认 False ⇒ 既有 dev/test 行为零变化"能成立的前提）。
5. 简报里"`config/models.json`"这个文件名在本仓不存在（实际是 `config/llm_registry.json`）。
   我按"匹配既有 config 文件的形态"执行了（LF、无 BOM、两空格缩进、记录一行一条）。

---

# 修复轮（review 二轮）——§11 起为追加内容，§1–§10 一字未改

> 分隔线以上是第一轮收口态。以下是同一任务的第二轮：修 2 条 Important（都在投影面）
> + 6 条 in-file minor，并按 review 要求复跑第一轮的变异。§5 的计数与 §9 的变异表**已被
> §14 / §15 取代**；§7-1、§7-2 两条自审发现在本轮闭环。

## 11. 本轮改动面

| 文件 | 动作 | 规模（前 → 后） | 换行 |
| --- | --- | --- | --- |
| `backend/app/knowledge_os.py` | I1 投影 + I2/M8 载荷算术与单读 + 注释重写 | 38 221 B/929 行 → 38 869 B/937 行（+14/−6） | LF 保持，crlf=0 |
| `backend/app/directory.py` | M2/M3/M4 判定面 + M7 只读缓存 + 模块 docstring 更正 | 10 661 B/216 行 → 12 722 B/244 行（+42/−14） | LF 保持，crlf=0 |
| `backend/tests/test_user_directory_contract.py` | 5 枚新用例 + 3 枚既有用例扩钉 | 28 839 B/523 行/49 例 → 34 579 B/600 行/54 例 | LF 保持，crlf=0 |
| `backend/config/users.json`、`users.demo.json` | **未动**：`diff -rq snap-task4-config config` 零命中 ⇒ 逐字节相同（23 B / 449 B） | — | — |
| `frontend/src/views/GovernanceView.tsx` | **未动**（本轮不需要）：`:94-100` 已有 `DISABLED → "已停用"`，`:193` 已有 `status === "DISABLED" ? "idle" : "ok"` ⇒ `enabled → status` 是零改动的接法 | — | — |
| `app/auth.py`、登录面、`app/config.py`、`.env.example`、`app/security.py`/`llm/`/`rag.py`/`conversation_agent.py` | **未动**（Task 5 / Task 9 的边界，本轮明确不越界） | — | — |

`diff -rq snap-task4-app app`（剔除 `__pycache__`）只报出 `directory.py` 与 `knowledge_os.py`
两枚 ⇒ 本轮产品代码改动面 = 两条 Important 所在的两份文件，无夹带。

## 12. I1 — `status` 不再硬编码，`enabled` 接到投影面

**改了什么**（`knowledge_os.py`）：

```python
            "status": "ACTIVE" if identity.enabled else "DISABLED",   # 原："ACTIVE"（常量断言）
```

注释按裁定重写为"名册的实际不变量"，不再把契约许给别的面：

```python
    # 名册是**身份侧的投影**：在册与否、启用与否都逐字取自身份文件的 `enabled`（身份的唯一真源），
    # 最后一次登录从审计面派生，展示面不自己发明第三种状态。停用账号在登录面上必须与不认识的
    # 账号不可分辨（那是一条响应差异，归登录口径判），这与名册如实显示停用者是两回事，互不牵制。
```

原措辞把"停用如何被观察到"整桩交给登录面，而规格 §7.3 的四态统一说的是**登录响应**，不是名册；
新措辞说的是两条各自成立的口径，且"必须不可分辨"是规范性表述（不声称登录面今天已经这样）。
登录面本轮一行没碰。

**连带更正（超出点名的一处，理由：同一句谎）**：`directory.py` 模块 docstring 原文写
"`enabled` 同理只被**声明**，不被消费……是认证腿统一判的事"。I1 落地后"不被消费"当场为假，
故改为："只被声明，不在这里被判定……名册那一面按字投影它，登录面另有它自己的口径……两处读的
都是文件里这同一个字段，谁也不许另存一份『这个账号现在是什么状态』"。

**覆盖用例**：`test_list_users_projects_identity_fields_and_keeps_the_response_shape` 的名册扩到
四个人，第四人 `enabled=False`，整形状断言里同时钉 `"status": "ACTIVE"`（三人）与
`"status": "DISABLED"`（一人），并顺带钉住"停用的人**仍在名册上**"（在册与否只由文件说了算）。
原有的三格逐字保留，字段集与顺序未动。

**真实运行证据**（企业形态 + 一份真写着 `enabled:false` 的身份文件，走真读路径）：

```
I1 enabled in file  : {'active01': True, 'retired01': False}
I1 status projected : {'active01': 'ACTIVE', 'retired01': 'DISABLED'}
```

## 13. I2 — 空目录不再有假分母（并顺手把两次读绑成一次）

**改了什么**（`knowledge_os.py:usage_summary`）：

```python
    members = directory_identities()                      # M8：一份载荷里只读一次
    total_users = len(members)                            # 不再 max(...,1)
    ...
        "total_users": total_users,
        "adoption_pct": round(len(active_users) / total_users * 100, 1) if total_users else 0.0,
```

`active_users` **保持不过滤**（治理页在渲染的就是这个数，本轮不重定义它），并把这条口径边界
写进函数 docstring：分子取自审计面上出现过的用户名，历史行里的人可以已不在目录中，因此分子可以
大于分母；目录为空时采用率按 0 计，而不是硬造一个 1。字段集与顺序与第一轮逐字相同。

**对第一轮两处措辞的更正（review 给的，我接受）**：

1. §7-2 把">100%"写成企业形态新长出来的东西，**不准确**：`active_users`（`:557`）从来不过目录，
   迁移前 6+ 个历史用户名对上常量 5 就已经 >100% 了。真正的变化是**分母从常量变成真源**，
   于是"目录为空"这一支第一次成为可达形状。本轮的修复针对的是后者。
2. §7-2 说"记给启动守卫/前端那一档"，但当时**没有任何用例**碰过空目录 ⇒ 那是一条没人守的口头
   结论。现在有了（下面两枚）。

**覆盖用例**（两枚新钉）：

- `test_usage_summary_reports_zero_adoption_when_the_directory_is_empty` ——
  `override_identities({})` + 两条审计行：`total_users == 0`、`active_users == 2`
  （显式钉住"不按目录过滤"这条边界，不是漏网）、`adoption_pct == 0.0`、`top_department is None`。
- `test_usage_summary_reads_the_directory_once_per_payload` —— AST 数 `usage_summary` 函数体内
  `directory_identities()` 的调用次数必须是 1。M8 只靠"我绑了个变量"守不住：下一次有人把
  `"total_users"` 改回内联第二次读，行为仍然自洽，只有载荷自己会跟自己矛盾。

**真实运行证据**（企业形态 + 出厂为空的 `backend/config/users.json`，走真读路径；迁移前该形状
是 `active_users=3, total_users=0, adoption_pct=300.0`）：

```
I2 directory size   : 0 mappingproxy
I2 payload triple   : {"active_users": 3, "total_users": 0, "adoption_pct": 0.0}
```

（`mappingproxy` 那半句是 M7 的顺带证据。）

## 14. fold-in 逐条

| # | 落点 | 改了什么 | 覆盖用例 |
| --- | --- | --- | --- |
| M1 | `test:196-201` | 接受名单加两枚**跨过 40 下限、只靠非 hex 站着**的取值：`"f"*39+"u"`（恰 40 位）与 42 位中文长名。原三枚全在 40 以下，属"天然不误判"区，护不住被拓宽的那一段 | 该用例本身；变异 X1 现已被杀 |
| M2 | `directory.py:_credential_shape_violation` | 新增 `_digest_reason(text, noun)`，**键名与取值跑同一道判定**（`noun` 只换措辞：`…的取值` / `…的键名`），黑名单键检查之后、递归取值之前。`extra="forbid"` 的 `loc` 装的是键名，`{"<64hex>": true}` 原本会把 digest 原样拼进启动消息 | `test_a_rejection_never_echoes_a_field_value` 扩一枚 `(digest_key, True)`，并多一条 `assertNotIn(digest_key)` |
| M3 | `directory.py:43,45` | 两道判定统一 `re.IGNORECASE`（`$Argon2id$` 不再 slip）。方向不是自由选择：既有的 `test_uppercase_digests_...`（`"A"*64` 必须拒）已经把"hex 那道不认大小写"钉住了，"反过来一致"会当场红两枚用例，所以只能把 PHC 那道抬上来 | `test_a_phc_prefix_in_mixed_case_is_rejected_like_a_lowercase_one`（`Argon2id`/`ARGON2ID`/`2B` 三枚） |
| M4 | `directory.py:_digest_reason` | `compact = "".join(text.split())`：判之前去掉**串内**空白，而不是只 `strip()` 首尾（分段粘进来的摘要常带折行）。误拒面评估见下 | `test_a_digest_pasted_with_an_internal_line_break_is_still_rejected`（4 枚，全部 ≤64 位，保证拒因只能是形态而不是 `max_length`） |
| M7 | `directory.py:_CACHE/identities/override_identities` | 存进缓存的就是 `MappingProxyType`（两条写路径都包），`_CACHE` 注解改 `dict[bool, Mapping[...]]`。任一调用方 `pop()` 一次就能把人从进程期身份真源里抹掉，`Mapping` 注解只挡静态检查 | `test_the_cached_directory_is_read_only_for_every_caller`（`pop`/`__setitem__` 双拒 + "拒写之外不许顺手改掉"） |
| M8 | `knowledge_os.py:usage_summary` | 见 §13 | 见 §13 两枚 |

M4 的"不扩大误拒面"论证（写进 docstring）：去掉空白后恰成 40 位以上纯 hex 的合法取值不存在
——`username`/`display_name`/`role`/`feishu_open_id` 四格没有一个是十六进制串家族；32 位 UUID 那枚
反向钉（`test_a_uuid_shaped_machine_username_is_not_mistaken_for_a_digest`）仍然绿，说明拓宽没有
把下限以下的面咬回来。D1 的整条风险方向（过拒）现在由 5 枚接受侧取值守着，其中两枚在拓宽段内。

**未做**（review 已台账化，本轮不越界）：M5（消息文本作为唯一加载序钉）、M6（名册发射序）、
M9（同文件重名复用 demo 措辞）、M10（删 `payload` 形参，已点名给下一个任务）、M11（过渡钉
docstring 叙述任务归属——计划点名要保留，留着）。

## 15. 验证命令与输出

```
### 1 焦点（本轮终态；下方变异全部跑完、字节还原之后再跑一遍确认）
cd /e/xiangmu/rag/backend && python -m pytest tests/test_user_directory_contract.py -q
    54 passed, 47 subtests passed in 23.18s            （进入本轮：49 passed / 37 subtests）

### 2 名册与指标的消费者
cd /e/xiangmu/rag/backend && python -m pytest tests/test_rbac_contract.py \
        tests/test_typesafe_security_contract.py tests/test_feishu_identity_contract.py -q
    135 passed, 9 warnings, 194 subtests passed in 121.71s   （进入：135，逐位相同）

cd /e/xiangmu/rag/backend && python -m pytest tests/test_model_router_v23_contract.py \
        tests/test_llm_egress_guard.py -q
    427 passed, 18 warnings, 452 subtests passed in 87.70s
    （`test_llm_egress_guard.py` 单跑仍 35 passed / 92 subtests，D6 豁免计数未动）

### 3 SEC-A 扫描面
cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q
    68 passed, 35 subtests passed                        （0 warnings，与第一轮逐位相同）

### 4 全套件（两 cwd 等数）
cd /e/xiangmu/rag/backend && python -m pytest -q
    1083 passed, 36 warnings, 1086 subtests passed in 233.65s
cd /e/xiangmu/rag && python -m pytest backend/tests -q
    1083 passed, 36 warnings, 1086 subtests passed in 162.26s
```

对账：基线 1078 + 本轮 5 枚新用例 = **1083** ✓；subtests 1076 + 10（混合大小写 PHC 3 +
串内空白 4 + 接受名单 2 + 不回显扩钉 1）= **1086** ✓；warnings **36 → 36** ✓；两 cwd 逐位相等 ✓。

字节与形态（本轮终态，`crlf` 计数为 0 即 LF）：

```
app/directory.py                      bytes=12722  lf=244 crlf=0 lone_cr=0 bom=False ends_nl=True
app/knowledge_os.py                   bytes=38869  lf=937 crlf=0 lone_cr=0 bom=False ends_nl=True
tests/test_user_directory_contract.py bytes=34579  lf=600 crlf=0 lone_cr=0 bom=False ends_nl=True
config/users.json                     bytes=23     lf=3   crlf=0（与快照逐字节相同）
config/users.demo.json                bytes=449    lf=9   crlf=0（与快照逐字节相同）
```

无残留：`ls backend/app backend/tests | grep -c tmp` → `0`；变异驱动脚本在仓库外
（`%TEMP%/seca-t4-fix/mutate.py`），跑完即删；`git status --porcelain` 与本轮开始前同一组文件。

## 16. 修正后的变异表（含第一轮存活的）

11 发，每发跑焦点件、跑完 `path.read_bytes() == original` 全为 True。编号用 `X`/`R` 前缀，
避免与 §9 那 12 发的 `M1…M12` 撞号；`R*` 是 review 要求"复跑第一轮那几发同代码路"的复验。

| # | 变异 | 谁该杀它 | 结果 |
| --- | --- | --- | --- |
| X1 | `^[0-9a-f]{40,}$` → `^.{40,}$`（只留长度，丢掉字符集）**← 第一轮存活，review 点名** | M1 的两枚跨下限反向钉 | **KILLED**：2 failed，`SUBFAILED(value='ffffffff')` 等，`test_an_ordinary_long_non_hex_value_is_not_mistaken_for_a_digest` |
| X2 | `status` 退回硬编码 `"ACTIVE"` **← I1 守卫** | 名册整形状断言（第四人 DISABLED） | **KILLED**：1 failed `KnowledgeOsReadPointTests::test_list_users_projects_identity_fields_and_keeps_the_response_shape` |
| X3 | `adoption_pct` 分母退回 `max(total_users, 1)` **← I2 守卫** | 空目录新钉 | **KILLED**：1 failed `test_usage_summary_reports_zero_adoption_when_the_directory_is_empty` |
| X4 | `total_users = max(len(members), 1)` **← I2 守卫（上报侧）** | 同一枚（`total_users == 0`） | **KILLED**：1 failed，同上 |
| X5 | 删掉键名判定（`for key in node:` 整段移除）**← M2 守卫** | 扩钉后的不回显用例 | **KILLED**：1 failed，`SUBFAILED(key='ffff…') test_a_rejection_never_echoes_a_field_value` |
| X6 | `_PHC_DIGEST` 去掉 `IGNORECASE` **← M3 守卫** | 混合大小写 PHC 新钉 | **KILLED**：3 failed（`Argon2id`/`ARGON2ID`/`2B` 三枚都 slip） |
| X7 | `"".join(text.split())` 退回 `text.strip()` **← M4 守卫** | 串内空白新钉 | **KILLED**：2 failed（夹 `\r\n` 与夹空格那两枚；纯首尾换行那两枚仍被旧 strip 挡住 ⇒ 新钉确实钉在增量上） |
| X8 | 缓存交回活 dict **← M7 守卫** | 只读新钉 | **KILLED**：1 failed `DirectoryReadFaceTests::test_the_cached_directory_is_read_only_for_every_caller` |
| X9 | `"total_users": len(directory_identities())`（一份载荷里第二次读）**← M8 守卫** | AST 单读钉 | **KILLED**：1 failed `test_usage_summary_reads_the_directory_once_per_payload`（行为仍自洽，只有 AST 钉杀得掉 ⇒ §13 的理由成立） |
| R2 | hex 判定整体失效（`[^\s\S]`）—— 复验第一轮 §9-M2 | 全部形态用例（含本轮两枚新反向钉） | **KILLED**：12 failed / 11 枚 subtest 失败（干净态 47 subtests → 36），杀它的名单里同时有 `test_a_legacy_digest_value_is_rejected_even_under_an_allowed_key` 与本轮的串内空白钉 ⇒ 判定面被本轮改写后牙口未退化 |
| R11 | `total_users` 退回常量 5 —— 复验第一轮 §9-M11 | 目录计数钉 + 本轮空目录钉 | **KILLED**：2 failed（第二轮那枚是本轮新长出来的，等于同一处坑现在有两道锁） |

本轮**新增存活：0**。第一轮的 §9-M1…M12 未重跑（产品代码里只有形态判定、缓存、两处载荷被碰过，
即 R2/R11 覆盖的那两小段），其余发在第一轮的杀伤面本轮无用例被改弱（焦点件 49→54 全绿可证）。

### 变异驱动自身的两条更正（不是我方的判定，但记录以免下轮误读）

1. 第一遍驱动只 grep `^FAILED`，而 pytest-subtests 的失败行是 `^SUBFAILED(...)` ⇒ X1 被误报成
   "SURVIVED"。改成同时认 `SUBFAILED` 后重跑，X1 的 2 发失败如实打出来。**上表以重跑为准。**
2. R2 第一版用的"永不成形"正则 `(?!x)^…` 实际只放过以 `x` 开头的串，等于没关掉判定（因此
   假报存活）。换成 `[^\s\S]` 后才是真的"形态检查整体失效"，结果为 12 failed。
   两发都在还原后重跑，还原位比对全 True。

## 17. 本轮的顾虑与交接（不含已闭环项）

1. **登录面仍然完全不读 `enabled`**（本轮明确不碰）：一个 `enabled:false` 的人现在在成员页
   显示"已停用"，却仍能口令登录。这两格不一致是**收敛方向正确的一半**——名册不再说谎，
   而"停用即拒"是下一个任务的哑校验要落的那一条（规格 §7.3）。本轮之前两处都在说谎。
2. `adoption_pct = 0.0` 在"目录为空但确有历史查询"时读起来像"零采用"，实际是"无可测分母"。
   选 0.0 而不是 `None`，因为前端 `OperationsView.tsx:134` 直接 `Math.round(...)%`；真要区分
   "无分母"，得连响应形状一起改，那超出本轮。交接给企业形态启动守卫那一档。
3. `active_users` 不过目录这件事现在**写在 docstring 里**、也**钉在断言里**（`== 2` 那句），
   但口径本身没变。谁要改成"只算在册的人"，会同时撞这两枚钉，这是刻意的。
4. M7 之后 `identities()` 交出的是 `mappingproxy`。目前所有消费者只做 `len()`/`.values()`/`.get()`，
   但**任何将来想原地改缓存的写法都会当场 `TypeError`**——那正是本轮想造出来的症状，别用
   `dict(...)` 把它绕过去当修复。
5. `X1` 那枚"只留长度"的判定如果哪天真被换成 `^.{40,}$`，被拒的是合法长名（D1 的过拒方向）。
   现在接受侧有 5 枚、其中 2 枚在拓宽段内，这道缝不再是无人看的状态。

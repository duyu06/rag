# SEC-A-CORR-01 报告（最小修正 `security-a-rc1` 的接口失配）

| 字段 | 值 |
| --- | --- |
| 来源裁定 | **R26 ①**（`.superpowers/sdd/ENTERPRISE_B0_PLAN/progress.md`）+ `docs/SECURITY_A_RC1_ERRATA_2026-09-28.md` |
| 任务简报 | `.superpowers/sdd/ENTERPRISE_B0_PLAN/sec-a-corr-01-brief.md` |
| 归属 | SEC-A 的 corrective 修正面。**不是 B0 的成果**，不得写成 B0 的一部分 |
| 缺陷 | `resolve_for_user()` 对 `directory.UserIdentity`（pydantic BaseModel）用 dict 接口 `record.get(...)` ⇒ `AttributeError`，登录腿与 `/me` 一起炸 |
| 产品改动面 | `backend/app/identity/__init__.py`（唯一） |
| 测试改动面 | `backend/tests/test_feishu_identity_contract.py`（三枚结构钉，+3 枚被收集的用例） |
| 文档改动面 | **无**：`docs/SECURITY_A_SPECIFICATION.md` 未改。§20.x 追加轮判定为"不需要"，五段式的逐条对照见 §9 |
| git 写操作 | **零**。读数分两层的：**工作树**（自带本修正，未提交）与**仓库外干净签出副本**（tag 原形 / main 原形 + 只覆盖这两个文件）；提交与推送由控制器执行 |
| 宿主 | Python 3.13.7（`python`），Git Bash / Windows，cp936 控制台（脚本侧统一 UTF-8 读写） |

---

## 1. 逐 hunk 的最小面确认

对照对象：`git diff -- backend/app/identity/__init__.py`（工作树 vs `HEAD`），以及
`git show 7cc5efc:backend/app/identity/__init__.py`（被认证的 tag 所指树）。
tag 树与工作树的差异**只有两个 hunk**，逐 hunk 判定如下。

**hunk 1（第 8-13 行区域，+2 行）**

```python
 from __future__ import annotations

+from typing import Any
+
 from app.identity.base import FeishuGrant
```

意图：给 hunk 2 的签名换型提供 `Any`。
夹带检查：无新增其它 import、无删减、不动 `FAILURE_CACHE_SECONDS` 与 `_resolver`。
结论：**属于最小面**。`Any` 而不是 `UserIdentity` 是对的——`identity` 这层若 import
`directory` 去标注参数类型，就变成第二个认身份的地方，且与本模块"把 `app.config` 延迟到
函数内 import 以免与 auth 成环"的既有取向冲突（模块 docstring 第 3-7 行写明）。

**hunk 2（`resolve_for_user` 定义处，-3 / +8 行）**

```python
-def resolve_for_user(username: str, role: str, record: dict) -> FeishuGrant | None:
-    """Grant for one local account. None keeps today's local-only semantics."""
+def resolve_for_user(username: str, role: str, record: Any) -> FeishuGrant | None:
+    """授予解析。`record` 是 `directory.UserIdentity`（SEC-A 后不再是从常量表里取的 dict）。
+
+    用 `getattr` 而非 `isinstance`：身份类型由 `directory` 拥有，这一层反过来依赖它的
+    字段集就成了第二个认身份的地方——`directory` 加字段时不必回来改这里，缺字段时
+    照旧退成"没接飞书"（None = 本地语义），不是异常。
+    """
     from app.config import settings

-    open_id = str(record.get("feishu_open_id") or "")
+    open_id = str(getattr(record, "feishu_open_id", "") or "")
     if not settings.feishu_permissions_enabled or not open_id:
         return None
     return get_resolver().resolve(username, role, open_id)
```

逐子句核对：签名换型（`dict`→`Any`）、docstring 换成人话并写明设计理由、**唯一的语义变化**
是那一行取值方式。控制流三句（开关判定、`not open_id` 判定、`get_resolver().resolve` 委派）
一字未动，返回值类型未动，`FAILURE_CACHE_SECONDS`、`warmup()`、`get_resolver()`、
`reset_resolver()` 全部未动。
结论：**属于最小面，没有夹带别的意图**。

`git show 7cc5efc` 的对应行逐字为
`open_id = str(record.get("feishu_open_id") or "")`（tag 树第 63 行），
即本 hunk 修的正是那一句。

**关于"从已提交树重新生成最小 patch"这条实现要求的处置**：核完两枚 hunk 之后，
结论是工作树那份**已经等于**从 tag 树出发的最小形——两 hunk 的差异集恰好就是
「`Any` 导入 + 签名 + docstring + 一处 `getattr`」。因此**没有另起一份重写**：
再敲一遍只会产出一份字节等价、但失去与工作树可对比性的副本，反而给复核添一层。
可核的证据链在这里：`git diff` 全文（本节引用）、tag 树原文（`git show 7cc5efc:…`）、
以及 §11 在干净签出上打这两枚文件后"tag 原形 1 failed → 打上补丁 1 passed"的对照读数。

**明确不带出的部分**：`backend/app/identity/README.md` 在工作树里另有 8 增 / 5 删，
内容是把"`app/auth.py` 的 `USERS` 表"改写成"身份声明文件 `config/users.json`"以及
`reset_resolver()` 那条运维口径的补注（SEC-A 身份分家的文档追认）。
它与本缺陷无关，属未完成的飞书桥接文档改写，**本次不发布**——见 §8 的显式证明。

---

## 2. 验收 1：干净签出复现修复前失败（修的是真问题）

复现载体（仓库外，只读操作，未在 `E:\xiangmu\rag` 里做任何 checkout/reset）：

```bash
T=$(mktemp -d) && git clone --no-local -b main E:/xiangmu/rag "$T/r" && cd "$T/r" && git checkout 7cc5efc
# 实测 T=/tmp/tmp.kYj7mTFFit（Windows 侧 C:\Users\zhang\AppData\Local\Temp\tmp.kYj7mTFFit）
git log --oneline -1        # 7cc5efc docs(sec-a): record the remote CI round-trip and the rev-3 recheck
```

该副本 `.env` 状态：**absent**（`backend/.env` 被 `.gitignore` 排除 ⇒ 干净签出里没有它）。
这不影响本结论：下面这条失败与配置无关，炸在函数第一句取值上。

```
$ python -m pytest backend/tests/test_rbac_contract.py -q -k login_payload
    open_id = str(record.get("feishu_open_id") or "")
...
>                   raise AttributeError(f'{type(self).__name__!r} object has no attribute {item!r}')
E                   AttributeError: 'UserIdentity' object has no attribute 'get'

..\..\..\Programs\Python\Python313\Lib\site-packages\pydantic\main.py:1042: AttributeError
=========================== short test summary info ===========================
FAILED backend/tests/test_rbac_contract.py::CapabilityMatrixTests::test_login_payload_exposes_canonical_role_and_permissions
1 failed, 14 deselected in 1.72s
```

与 errata §3 记录的控制器读数同形（同一条 `AttributeError`、同一枚用例、同一处 pydantic 栈帧），
并与远端 run `36436145777` 里 113 条中的 111 条同因。**这是"tag 所指树不可认证"的复验证据。**

---

## 3. 验收 2：工作树修复后同一枚用例通过

`backend/.env` = **present**（sha256 前 12 位见 §6 表）。

```
$ (cd E:/xiangmu/rag/backend && python -m pytest tests/test_rbac_contract.py -q -k login_payload)
1 passed, 14 deselected in 0.95s
$ (cd E:/xiangmu/rag        && python -m pytest backend/tests/test_rbac_contract.py -q -k login_payload)
1 passed, 14 deselected in 1.11s
```

第三格证据（同一枚修复在**干净签出**里也过，排除"只有我这台机器绿"）：把
`__init__.py` + 新测试复制进 §2 那个临时副本后

```
$ (cd "$T/r" && python -m pytest backend/tests/test_rbac_contract.py -q -k login_payload)
1 passed, 14 deselected in 0.60s
```

---

## 4. 三枚结构钉（新增位置：`backend/tests/test_feishu_identity_contract.py`）

新增 `class RecordInterfaceShapeTests`（第 4 枚"反向保真"是**证伪程序**，按简报不落盘为用例，
见 §5）。设计动机写在类 docstring 里：类型提示不是运行时契约，`pytest` 不会因为签名撒谎而失败，
所以只能钉"调用形状"。

**钉 1 — `Mapping.get` 调用面**（`test_resolve_for_user_carries_no_mapping_get_call_site`）
扫 `_IDENTITY_PACKAGE_FILE` 的 AST：取不到模块级 `resolve_for_user` 直接红（防空断言）；
函数体必须仍含 `feishu_open_id`（防"把实现删空"假绿）；函数体内
`Call(func=Attribute(attr="get"))` 形状必须为空；额外一条只盯"接收者就叫 `record`"的全模块
扫描，堵住"把取值挪进私有助手"这一族搬家。

**钉 2 — `None` 走本地语义**（`test_pydantic_record_with_none_open_id_takes_local_semantics`）
用 `UserIdentity(...)` 正常校验器路径构造 `feishu_open_id=None`，开关置开：
返回 `None`、不抛、`provider_calls == []`（一次请求都没发）、`assembly_calls == []`
（连唯一装配缝 `get_resolver()` 都没被问一次）。spy 挂在 `get_resolver` 上而非 `_resolver`
单例上，因为委派必须走那条缝才叫"装配一次、每请求解析一次"。

**钉 3 — 缺失字段与 `None` 不得混成同一件事**（
`test_missing_attribute_and_blank_open_id_neither_sends_a_request`）
三形并列（根本没有该属性的 `object()` / 字段为 `None` / 字段为空串（`model_construct` 绕校验硬造）），
先各自断言"仍是它自己"（`hasattr` False / 值是 `None` / 值是 `""`）——折叠只许发生在
"要不要发请求"那一句上，不许发生在类型上；三形都 `resolve_for_user(...) is None` 且
`provider_calls == []`、`assembly_calls == []`。**正向对照**：`feishu_open_id="ou_pin_probe"`
必须真的走桥且三参原样透传、装配恰好一次——少了这一臂，"把三态全折叠成静默本地"的实现能骗过
前面每一句。**应拒的形态仍在身份层就被拒**：`feishu_open_id=""`（撞 `min_length=1`）与
`feishu_open_idd="ou_typo"`（撞 `extra="forbid"`）都抛 `ValidationError`，
所以 `getattr` 的默认值没机会把"键拼错"读成"没接飞书"。

三枚在工作树实测：

```
$ (cd E:/xiangmu/rag/backend && python -m pytest tests/test_feishu_identity_contract.py -q -k RecordInterfaceShape)
3 passed, 103 deselected, 3 subtests passed in 0.67s
```

---

## 5. 钉 4（反向保真）：证伪台读数

载体：§2 那个临时副本（`$T/r`）。**所有字节级改写只发生在副本里**。
仓库文件的可证未改：`sha256sum backend/app/identity/__init__.py` 在证伪前、证伪中、证伪后
三次同为 `2cfab9f181823c9462cbeb25ccd4ca5cd683957b97c24d711d662c4a005f283b`；
每轮变异还原后副本与仓库 `cmp` 无差异（`cmp OK: 副本 == 仓库字节`）。
副本还额外承担一件事：它跑在 `git checkout main` 之后的分支上，用于 §11 的干净签出复验。

**变异 A**：`str(getattr(record, "feishu_open_id", "") or "")` → `str(record.get("feishu_open_id") or "")`
（即 rc1 出厂那一行，逐字）。三枚钉各自单跑（`-rf`）：

```
##### test_resolve_for_user_carries_no_mapping_get_call_site
E       AssertionError: Lists differ: ["record.get('feishu_open_id')"] != []
E       First extra element 0:
E       "record.get('feishu_open_id')"
##### test_pydantic_record_with_none_open_id_takes_local_semantics
E                   AttributeError: 'UserIdentity' object has no attribute 'get'
FAILED …::RecordInterfaceShapeTests::test_pydantic_record_with_none_open_id_takes_local_semantics
1 failed, 105 deselected in 1.70s
##### test_missing_attribute_and_blank_open_id_neither_sends_a_request
E       AttributeError: 'object' object has no attribute 'get'            ← 根本没有该属性那一形
E                   AttributeError: 'UserIdentity' object has no attribute 'get'   ← None / 空串 两形
FAILED …::RecordInterfaceShapeTests::test_missing_attribute_and_blank_open_id_neither_sends_a_request
4 failed, 105 deselected in 2.22s
```

⇒ 三枚全红（钉 1 的 `E` 行 + 断言文案见下面那段全量；钉 3 报 4 项红 = 三形 subTest + 用例本体）。
钉 4 成立。钉 1 的完整红文案（`-q -k no_mapping_get` 的 `E` 行逐字；控制台 cp936 把中文
打成了乱码，此处按源码里的断言消息语义誊回，原文在
`backend/tests/test_feishu_identity_contract.py:643-647`）：

```
E       AssertionError: Lists differ: ["record.get('feishu_open_id')"] != []
E       First list contains 1 additional elements.
E       First extra element 0:
E       "record.get('feishu_open_id')"
E       - ["record.get('feishu_open_id')"]
E       + [] : `resolve_for_user` 又用回 dict 接口了：`record` 自 SEC-A 起是
E              `directory.UserIdentity`（pydantic BaseModel，`extra="forbid"`，没有 `.get`），
E              这种调用每次必抛 AttributeError：["record.get('feishu_open_id')"]
```

⇒ 这枚红**不依赖任何登录发生、不依赖 pydantic 实例在场**——它扫的就是那一行的形状。
这正是它作为结构钉的意义：坏改动在"接口"上，判据也必须写在"接口"上。

**变异 E（"先转 dict 再 `.get`"：行为看起来全对、接口却变回去了）** 单独放在 §5b——
它是这三枚钉里钉 1 的**独有覆盖面**，值得单独一节。






**变异 B（正交，证明三枚不是同一枚）**：把末句委派换成 `return None`（"把三态全折叠成静默
本地"这种取巧实现）。钉 1、钉 2 **仍绿**（它们管不到这一族），钉 3 红：

```
##### test_missing_attribute_and_blank_open_id_neither_sends_a_request
E       AssertionError: Lists differ: [] != [('staff', 'USER', 'ou_pin_probe')]
```

⇒ 三枚分工可验证，钉 3 的正向对照确实是承重墙。

**变异 C（环境对照，副本还原成修复态）**：同一副本同一命令回到
`3 passed, 103 deselected, 3 subtests passed`，且整文件
`106 passed, 6 warnings, 209 subtests passed in 38.63s`
⇒ 证伪台的红不是环境噪声造成的假红。

**变异 D（爆炸半径与飞书开关无关，实测）**：同一份缺陷码，直调
`resolve_for_user("staff","USER", UserIdentity(username="staff", display_name="职员", role="USER", feishu_open_id=None))`，
两态各跑一次（脚本 `$T/flag_experiment.py`，`sys.path` 指向副本的 `backend`）：

```
=== 缺陷码（record.get）：开关两态直调 resolve_for_user ===
开关=True  抛 AttributeError: 'UserIdentity' object has no attribute 'get'
开关=False 抛 AttributeError: 'UserIdentity' object has no attribute 'get'
=== 修复码（getattr）：同一次直调 ===
开关=True  返回=None
开关=False 返回=None
```

因为 `open_id = str(record.get(...) or "")` 排在 `if not settings.feishu_permissions_enabled`
**之前**——取值先执行，开关后判定。⇒ 这一句与飞书开关无关，**每一枚真实登录都必须经过它**。
出厂形态实测：`app/config.py:189  feishu_permissions_enabled: bool = False`，
`backend/.env` 未设 `FEISHU_PERMISSIONS_ENABLED` ⇒ **开关关着也炸**，
这才是远端 111 枚同因全红的规模来源（也解释了为什么"飞书功能根本没开，登录面却整体不可用"）。


---

## 5b. 钉 1 的增量价值：两发受控实测（外加一处自我纠正）

**变异 E（"先转 dict 再 `.get`"——行为全对、接口又变回 dict）**：
`str(record.model_dump().get("feishu_open_id") or "")`。这一形是关键，因为它把
`record.get` 那枚 AttributeError 修掉了，行为面看起来"正常"：

```
$ (副本，变异 E) python -m pytest backend/tests/test_feishu_identity_contract.py -q \
    -k "ResolveForUser or RecordInterfaceShape" -v
SUBFAILED(record='no-attribute') …::ResolveForUserTests::test_missing_or_blank_open_id_returns_none_without_touching_resolver
SUBFAILED(record='no-attribute') …::RecordInterfaceShapeTests::test_missing_attribute_and_blank_open_id_neither_sends_a_request
FAILED …::RecordInterfaceShapeTests::test_resolve_for_user_carries_no_mapping_get_call_site
3 failed, 5 passed, 100 deselected in 1.28s
```

⇒ 只有**钉 1** 稳定报红并且文案指名接口；两枚行为钉里只有"根本没有该属性"那一形顺带撞到。
`test_disabled_…`、`test_open_id_delegates_to_resolver`、钉 2 全绿——
即"这一层重新依赖 dict 形状"这件事，行为面看不见。这就是钉 1 的增量。
还原后同一命令：`6 passed, 100 deselected, 6 subtests passed`。

**自我纠正（必须留字）**：本节初稿写过"既有那三枚行为用例在变异 A 下仍报绿，所以判据粒度太松"。
**那句取的是脏读数**——事后无法证明那次跑在产品码被回退之后的状态上。受控重测（变异 A 原形，
副本里 `__init__.py:63` 逐字 `record.get(...)`，同一条命令跑两遍：一次提交版测试文件、一次新测试文件）：

```
$ (副本，变异 A) python -m pytest backend/tests/test_feishu_identity_contract.py -q -k ResolveForUser -v
FAILED …::ResolveForUserTests::test_disabled_returns_none_without_touching_resolver
SUBFAILED(record='no-attribute') …::ResolveForUserTests::test_missing_or_blank_open_id_returns_none_without_touching_resolver
SUBFAILED(record='open-id-none') …（同上）
SUBFAILED(record='open-id-blank') …（同上）
FAILED …::ResolveForUserTests::test_open_id_delegates_to_resolver
5 failed, 1 passed, 103 deselected in 2.04s
```

⇒ 既有行为用例**本来就报红**。所以 rc1 漏掉它的原因不是判据松，而是 errata §2 那一句：
验收读数取自"带未提交兼容修复的工作树"——**测量的层**搞错了，测试不瞎。
三枚钉的价值因此不在"多抓一次同一个 bug"，而在：(a) 变异 E 那一形只有钉 1 抓得到；
(b) 失败发生在**接口层**、一行文案指名"`record` 自 SEC-A 起是 `UserIdentity`"，
而不是 111 枚下游 `AttributeError` 让人自己反推；(c) 类型提示不是运行时契约，
所以那句承诺唯一的可执行表达就是 AST（errata §5"不能只测一次 happy path"同一条）。

---

## 6. 验收 4：四组定向回归（工作树；cwd = 仓库根；`backend/.env` = present，sha12 `4d7f974107dd`）

| 组 | 命令 | 读数 |
| --- | --- | --- |
| G1 RBAC contracts | `python -m pytest backend/tests/test_rbac_contract.py -q` | **15 passed in 1.10s** |
| G2 Feishu identity contracts | `python -m pytest backend/tests/test_feishu_identity_contract.py -q` | **106 passed, 6 warnings, 209 subtests passed in 50.08s**（修正前该文件 103 枚；+3 即本报告的三枚结构钉） |
| G3 SEC-A contracts（四枚） | `python -m pytest backend/tests/test_credentials_contract.py backend/tests/test_secret_hygiene_contract.py backend/tests/test_authentication_leg_contract.py backend/tests/test_password_lifecycle_contract.py -q` | **283 passed, 70 subtests passed in 52.96s** |
| G4 B0 门模块 | `python -m pytest backend/tests/test_ci_gate_contract.py -q` | **1 failed, 15 passed in 21.36s** |

G4 那一枚红**不是回归**，是本次新增用例撞上了 B0 自己钉死的收集数常数：

```
FAILED backend/tests/test_ci_gate_contract.py::test_collected_count_matches_the_pinned_number
```

即 `EXPECTED_COLLECTED = 1332`（`backend/tests/test_ci_gate_contract.py:104`）与被测实收不再相等。
同一文件里那枚"自我存续"门 `test_the_gate_module_itself_is_collected` **仍绿**（本门自己仍贡献 16 枚），
红 ONLY 出现在总数比较上——这正说明常数该由加测试的那一轮**实测回写**，而不是凑。

**本任务不碰这个常数**（简报硬约束 + 该文件不在允许改动面内）。它归控制器。详见 §7。

---

## 7. 收集数：实测 1335，B0 的钉需要重新锚定（**未自行修改**）

```
$ python scripts/b0_collection_probe.py
TOTAL 1335
  106  backend/tests/test_feishu_identity_contract.py
```

三枚结构钉都是被 pytest 收集的用例，没有"加了钉却不改收集数"的放法：

| 项 | 修正前 | 修正后 |
| --- | --- | --- |
| 实收总数 | 1332（= 常数） | **1335** |
| `EXPECTED_COLLECTED`（`test_ci_gate_contract.py:104`） | 1332 | **仍写 1332 ⇒ 该门红** |
| `test_feishu_identity_contract.py` 贡献 | 103 | 106 |
| `.superpowers/.../baseline/collected-node-ids.txt` | 1332 行 | **仍 1332 行 ⇒ 差集少 3 枚**（该文件 gitignored，只用于把失败信息写得能看，不进判据） |

**待控制器执行的重锚**（本任务只报不动）：`EXPECTED_COLLECTED` 1332 → 实测值（本次实量为 1335）、
注释里那句"1316 + 16 = 1332"的推导同步改写、
`baseline/collected-node-ids.txt` 用 `b0_collection_probe.py --node-ids` 重生成 1335 行、
B0 变异台的八发基准与 mutation bench 落盘计数（`mutations/`、`mutation-bench.txt`）一并复核是否含总数断言。
简报验收 3 那句"必须仍 16 passed / 1332 收集"与简报"新增结构钉" mutually exclusive——
按简报硬约束"不得为了让套件绿而改判据"处理：**保留判据、报告冲突、不自行动常数**。

---

## 8. 显式证明：本修正没有发布 `identity/README.md` 那堆 diff

```
$ git status --porcelain
 M .superpowers/sdd/ENTERPRISE_B0_PLAN/progress.md
 M backend/app/identity/README.md              ← 仍是工作树改动，未 staged
 M backend/app/identity/__init__.py
 M backend/tests/test_feishu_identity_contract.py
 M docs/SECURITY_A_ACCEPTANCE_2026-09-26.md
?? docs/SECURITY_A_RC1_ERRATA_2026-09-28.md

$ git diff --cached --stat                      ← 暂存区为空（本任务零 git 写操作）
（无输出）

$ git diff --numstat -- backend/app/identity/README.md      # 工作树：8 增 5 删，仍在
8	5	backend/app/identity/README.md
$ git diff --cached --numstat -- backend/app/identity/README.md
（无输出 = 一行都没进暂存区）
```

第一列是空格 ⇒ `README.md` 未被 staged。它的 8/5 行改动（`auth.USERS` → 身份声明文件、
`reset_resolver()` 运维口径补注）留在工作树里，随飞书文档那轮再走。
`docs/SECURITY_A_ACCEPTANCE_2026-09-26.md`（M）与 `docs/SECURITY_A_RC1_ERRATA_2026-09-28.md`（??）
**不是本任务的产物**：它们是 R26 ② 已签发的 errata 两层登记，本任务开始前就在工作树里，未改动。

---

## 9. `docs/SECURITY_A_SPECIFICATION.md`：**不改**（§20.x 追加轮判定）

简报允许"只在需要登记 §20.x 追加轮时"改规格，且必须走五段式修订卡。逐条对照后的结论是**不需要**：

1. **原始规格**：§6 / SEC-A-010 把身份唯一真源定成"身份声明文件集"，`feishu_open_id` 是**可选字段**
   （规格第 200 行），SEC-A-010 还禁止任何单元同时持有身份与凭据。规格**从未**规定
   `identity` 这层按 dict 接口取记录；`record: dict` 那枚签名是实现的遗留，不是规格的承诺。
2. **实测反例**：见 §2 ——干净签出 `pytest -k login_payload` 抛
   `AttributeError: 'UserIdentity' object has no attribute 'get'`。炸的是实现与规格的**一致性**，
   不是规格本身的可判定性。
3. **纠正后的规范**：`resolve_for_user` 按属性接口读 `feishu_open_id`，缺失/None/空串折叠为
   "没接飞书"（= 本地语义），异常不外抛。这**就是**规格 §6 与 SEC-A-003（"迁移不得使既有账号失去
   登录能力"）已经要求的行为——修的是偏差，不是规范。
4. **判据是否改变**：**没有**。SECA-01…23 矩阵一行未动，未新增/删除/放宽任何判据；
   三枚结构钉是 errata §5 明确要求的**回归证据载体**，挂在既有 SEC-A 契约文件
   （`test_feishu_identity_contract.py`）里，不构成新判据行。SEC-A-006（"不得放松任何既有契约"）
   由本修正**恢复**而非改写。
5. **回归证据**：本报告 §2（修复前红）/ §3（修复后绿，含干净签出与两 cwd）/ §4-§5（三枚钉 +
   两族变异证伪 + 环境对照）/ §6-§7（四组定向 + 收集数实测）/ §10（全量两格）。

另有两条决定性事实：规格抬头（第 6 行）自陈 **SPEC 冻结**、"本文档与计划不伴随代码改动"；
§19/§20.7 的裁定序是"**规格先改、实现照规格写**"，而本轮顺序相反（实现向规格对齐）。
把一次"实现向已冻结规格靠拢"的修正登记成 §20.9 追加轮，会反过来给读者"规格被改过"的假象，
并与 errata §6"方法论教训进 B0 侧台账、不进 SEC-A 判据"的既有裁定撞车。
故：**规格文档零改动**，事实与判据的载体保持在已签发的
`docs/SECURITY_A_RC1_ERRATA_2026-09-28.md`（§2/§4/§5 三节即五段式的实体内容）与本报告的台账位。

---

## 10. 验收 5：全量套件两格（逐格标注 cwd 与 `.env` 状态）

测量层：**工作树**（自带本修正）。按 errata §6 的教训，每格都写清 cwd 与 `.env` 状态；
本项目已判定不带这两项的读数不可跨会话复用。

| 格 | cwd | `.env` 状态 | 命令 | 读数 |
| --- | --- | --- | --- | --- |
| 1 | `E:/xiangmu/rag`（仓库根） | present（`backend/.env`，sha12 `4d7f974107dd`） | `python -m pytest backend/tests -q` | **1 failed, 1334 passed, 36 warnings, 1136 subtests passed in 150.67s (0:02:30)**；real 2m34.835s |
| 2 | `E:/xiangmu/rag/backend` | present（同一份文件，相对 cwd 即 `./.env`） | `python -m pytest tests -q` | **1 failed, 1334 passed, 36 warnings, 1136 subtests passed in 156.56s (0:02:36)**；real 2m40.058s |

两格的**判决面逐字相同**（1 / 1334 / 36 warnings / 1136 subtests），差异只在耗时与路径前缀。
唯一那枚 failed 两格同一枚，且不是本修正引入的：

```
FAILED tests/test_ci_gate_contract.py::test_collected_count_matches_the_pinned_number
```

⇒ B0 的收集数常数门（`EXPECTED_COLLECTED = 1332` 对 1335 实测）。见 §7。

第三格（**干净签出 + 仅本修正的两处改动**，`.env` = absent）：见 §11。

---

## 11. 干净签出的修后复验（这一格才是本次修正真正要交付的东西）

errata §6 那句"宿主工作树绿 ≠ 已提交树绿 ≠ 干净签出绿 ≠ CI 绿"是本任务的由来，
所以读数也必须落在**干净签出**那一层，而不只是工作树。

载体：§2 那个 `git clone --no-local` 出来的临时副本，**只覆盖两个文件**
（`backend/app/identity/__init__.py`、`backend/tests/test_feishu_identity_contract.py`）。
它先停在 `7cc5efc` 上量"tag + 修正"那一族读数（rc1 那一层），随后 `git checkout main`
（**只在副本内**移动 HEAD，`E:\xiangmu\rag` 全程未动）量"main + 修正"那一格
——因为 `security-a-rc2` 将来是从 main 上切的，不是从 tag 上切的，这一格才是"未来的 rc2 形状"：

```
$ git status --porcelain                 # 在副本里
 M backend/app/identity/__init__.py
 M backend/tests/test_feishu_identity_contract.py      ← README 不在列：被禁的那堆 diff 没带出来
```

| 读数 | 命令 | 层 | 结果 |
| --- | --- | --- | --- |
| 缺陷复现（未打补丁） | `pytest backend/tests/test_rbac_contract.py -q -k login_payload` | tag `7cc5efc` 原形 | **1 failed** — `AttributeError: 'UserIdentity' object has no attribute 'get'`（§2 原文） |
| 打上补丁后同一枚 | 同上 | `7cc5efc` + 两文件补丁 | **1 passed, 14 deselected in 0.60s** |
| 三枚结构钉 | `pytest backend/tests/test_feishu_identity_contract.py -q -k RecordInterfaceShape` | 同上 | **3 passed, 103 deselected, 3 subtests passed in 0.53s** |
| 整个 Feishu identity 文件 | `pytest backend/tests/test_feishu_identity_contract.py -q` | 同上 | **106 passed, 6 warnings, 209 subtests passed in 38.63s** |
| 三枚 README 钉（**HEAD 版 README**，未带那堆 diff） | `pytest … -k Readme` | 同上 | **3 passed, 103 deselected, 20 subtests passed** ⇒ "不发布 README"不会把 `IdentityProviderReadmeTests` 判红。这条是本任务最担心的自相矛盾，实测排除 |
| 全量套件（干净签出层 = 未来的 rc2 形状） | `pytest backend/tests -q` | **main `7923ee4`** + 仅两文件补丁 | **2 failed, 1333 passed, 36 warnings, 1136 subtests passed in 188.37s (0:03:08)**；real 3m15.508s |
| 对照：同一份补丁打在 **tag 树**上 | 同上 | `7cc5efc` + 仅两文件补丁 | **2 failed, 1317 passed, 36 warnings, 1136 subtests passed in 157.97s** |

tag 那一格只有 1319 枚被收集，比 main 少 16 枚——**少的那 16 枚正是 B0 的门模块**
（`test_ci_gate_contract.py` 是 `9482f44` 才进来的，tag 在它之前），所以 tag 那一格
根本不含常数门；它红的两枚是 `test_fallback_py_is_byte_frozen_for_this_task`（同一枚，见下）
与 `test_p0_row_status_matches_the_evidence`（R26 ③ 的 P0 证据件在 tag 树上还没有可对齐的形状，
与本修正无关，且在 tag 上把两文件退回未修时它同样红）。

⇒ 结论不变：**这一层的红没有一枚是本修正引入的**；本修正在这两层都把
111 枚 `AttributeError` 那一片红收成了"1 枚常数门 + 与本任务无关的层钉"。

最后一格那两枚 failed 分别是：

```
FAILED backend/tests/test_ci_gate_contract.py::test_collected_count_matches_the_pinned_number
FAILED backend/tests/test_model_router_v23_contract.py::AgentChainBoundaryTests::test_fallback_py_is_byte_frozen_for_this_task
```

- 第一枚 = §7 的常数门，本修正的必然后果，等控制器重锚。
- 第二枚**与本修正无关**，且它在同一个副本里"把两文件退回未修"之后照样红（实测：
  `1 failed, 391 deselected`）。成因是那一枚 sha1 前缀钉
  （`test_model_router_v23_contract.py:8076-8079`，钉 `app/llm/fallback.py` 的字节）
  取的是**工作树层**的字节，而干净签出层拿到的是另一份字节：

  ```
  worktree len 48518 sha1 008d8213bc05…  CRLF 0    LF 943
  clone    len 49461 sha1 e78071723104…  CRLF 943  LF 943
  git hash-object  ==  git rev-parse HEAD:…  == 51b76677c5072b71aab13faa44c529cad6a766ab
  ```

  blob 同一枚，差别只在 checkout：本机 `core.autocrlf=true` + `.gitattributes` 的 `* text=auto`
  ⇒ Windows 干净签出把 LF 换成 CRLF，字节哈希必不同。Linux/CI 上不复现。
  **这是 errata §6 那一族教训的第二个实例**（"读数取自哪一层"没标），但载体是 V2.3 的字节冻结钉，
  不在本任务允许面内 ⇒ 只登记，不动（见 §13）。

`.env` 状态（这一层）：**absent** —— `backend/.env` 被 `.gitignore` 排除，干净签出里根本没有它。
⇒ §10 两格 + 这一格合起来同时覆盖 `{工作树, 干净签出} × {cwd 根, cwd backend}`，
并把 `.env` 那一轴也带上了（present / absent 各量到）。

---

## 12. 结论与遗留

**结论**：`SEC-A-CORR-01` 的判据面达成——已提交树的那一处接口失配在干净签出里可复现（§2）、
可修好（§3 / §11），并且修好的形状被三枚结构钉钉住、三枚都可证伪（§5）。
产品代码只动一个文件、两个 hunk，逐 hunk 核过没有夹带（§1）。零 git 写操作；两枚 tag 与 HEAD
在本次会话结束时的实测形状：`git for-each-ref refs/tags` →
`security-a-rc1 33a8202`（`^{commit}` 剥离后 = `7cc5efc0460abb01171c20cee61ef01bf5282a3d`，
与 errata 表头逐字相同）、`model-router-v2.3-rc1 3af20e8`；`git rev-parse --short HEAD` → `7923ee4`，
`git status -sb` → `## main...origin/main`（未动）。

**一条必须写下来的事实**：缺陷不只住在 tag 上，**main HEAD `7923ee4` 的
`backend/app/identity/__init__.py:63` 逐字仍是 `open_id = str(record.get("feishu_open_id") or "")`**
（`git show HEAD:… | grep` 实量）。⇒ 本修正对"rc2 可认证"必要，对"main 可用"同样必要。

**交付字节指纹**（控制器据此暂存；报告里所有工作树读数都对这两枚指纹负责）：

```
$ sha256sum backend/app/identity/__init__.py backend/tests/test_feishu_identity_contract.py
2cfab9f181823c9462cbeb25ccd4ca5cd683957b97c24d711d662c4a005f283b *backend/app/identity/__init__.py
19394dbd78c65af160ce87b6cb40fa304ab8223e9a1a86a698430a634c1a9942 *backend/tests/test_feishu_identity_contract.py
```

第一枚在证伪台跑完前后**同一个值**（证伪只碰副本）；第二枚在 §6 那批读数之后又做过一次
纯注释/docstring 修订，故末态以这两行为准。末态按当前字节复跑一次确认：

```
$ (cd E:/xiangmu/rag && python -m pytest backend/tests/test_feishu_identity_contract.py backend/tests/test_rbac_contract.py -q)
121 passed, 6 warnings, 209 subtests passed in 53.40s          # 106 + 15，与 G1/G2 分项一致
```

**遗留（交控制器，本任务不自行处置）**：

1. **B0 收集数常数需要重新锚定**：实测 1335 vs `EXPECTED_COLLECTED = 1332`（§7）。
   这枚门在本次修正后是红的，且在 rc2 签发前必须转绿——否则远端主门仍会红这一枚。
   **本任务未动它**（简报硬约束：常数归控制器，且 `test_ci_gate_contract.py` 不在允许面内）。
2. `baseline/collected-node-ids.txt`（1332 行）同步重锚；变异台若含总数断言一并复核。
3. 远端 `backend-contracts` 的 step 级读数由控制器在 push 后取（简报验收 5），本任务不主张。
4. `backend/app/identity/README.md` 那 8/5 行改动仍在工作树未 staged，等飞书文档那一轮（§8）。
5. **Windows 干净签出那一层的字节钉**（§11 第二枚 failed）：`test_fallback_py_is_byte_frozen_for_this_task`
   在工作树层绿、在干净签出层红。要么把那枚 sha1 钉改成"对 blob 取哈希"（`git hash-object`，
   与 checkout 形状无关），要么把 `*.py` 在 `.gitattributes` 里显式 `eol=lf`。
   这条与 SEC-A 无关、不在本任务面内，但它是"干净签出必须可认证"这条新规矩上的第二块石头。

---

## 13. 过程自纠（写进台账，免得下一次再靠运气发现）

一次读数被我自己污染过：在同一个临时副本里，我把 CELL3 的全量套件跑在后台，
同时又对**同一个副本**下了 `git checkout -- backend/app/identity/__init__.py`（为了量"未打补丁时
那两枚 V2.3 门红不红"）。两件事撞上 ⇒ 那一格（`2 failed, 1333 passed`，其中一枚是本报告的钉 1）
的失败集合不可信。处置：**弃用该格**，把副本还原（`cp` + `cmp` 核字节）后重跑同一命令，
取 §11 最后一格那一行读数，并对那枚 V2.3 门做了"未打补丁也红"的独立复核。
教训与本任务的母题同一句：**同一棵树上的两个并发读数互相不是证据**——分层、串行、留字节指纹。




# Task 6 报告 — 令牌生命周期（`cv` claim、revocation、`must_change` 端点覆盖门）

状态：**DONE_WITH_CONCERNS**（实现与门全部落地、全套件两 cwd 同数零红；concerns 是三条交接事实与一处计划文本需要回写，见 §7）

### 文件清单

| 文件 | 动作 | 规模 |
| --- | --- | --- |
| `backend/app/auth.py` | 改：`CREDENTIAL_VERSION_CLAIM`、`issue_token` 签 `cv`、`_user_from_token` 三态并入 + 读表比版本 | 380 → 405 行（LF 未翻） |
| `backend/app/main.py` | 改：登录响应与 `/me` 各加一枚 additive 键 + 一个 import | 773 → 779 行（CRLF 779/779 保持） |
| `backend/tests/test_password_lifecycle_contract.py` | **新建**：令牌生命周期 + 响应面键集 + SECA-10 覆盖面门 | 766 行，32 例 / 5 subtests |
| `backend/tests/test_authentication_leg_contract.py` | 改：4 枚门用例换夹具形状、1 枚改强、+3 枚令牌面 | 857 → 963 行，43 → 46 例 |
| `backend/tests/test_feishu_identity_contract.py` | 改：2 枚既有钉换注入/期望集形状（判定不放宽）、+2 枚反向钉 | 1893 → 1960 行，101 → 103 例 |
| `.superpowers/sdd/SECURITY_A_PLAN/progress.md` | 追加 Task 6 段（状态 + 5 条 Ruling + 变异表 + 4 条 deferred） | 130 → 142 行 |
| 快照 | `snap-task6-pre-app` / `-pre-test_authentication_leg_contract.py` / `-pre-test_feishu_identity_contract.py` / `snap-task6-app` / `-post-*` / `-test_password_lifecycle_contract.py` | 与前一任务的命名同轨 |

`app/` 下除 `auth.py` / `main.py` 之外的一切（含 `app/llm/`、`app/rag.py`、`app/conversation_agent.py`、`app/security.py`）与开工前快照逐字节相同（`diff -rq -x __pycache__` 只列出这两份）。

---

## 1. 实现 vs 简报

### 1.1 逐条对照

| 简报要求 | 落地 | 位置 |
| --- | --- | --- |
| `CREDENTIAL_VERSION_CLAIM = "cv"` 常量 | ✅ 字面值一致，签发/鉴权两侧都读该常量 | `app/auth.py:300` |
| `issue_token` payload 多一枚 `cv` | ✅ `int(record.credentials_version) if record else 0`，其余 claim 一字未动 | `app/auth.py:303-324` |
| `_user_from_token` 验签 → 身份 → 凭据 → cv | ✅ `identity is None or not identity.enabled or record is None` 同格 401；再比 `cv` | `app/auth.py:327-365` |
| 「账号不存在」并入「无效登录凭证」 | ✅ 三态（不认识主体 / 停用 / 有身份无凭据行）共用既有中文文案；`detail="账号不存在"` 作为源码级反钉存在 | 同上 + `test_..._construction_face_stays_a_single_door` |
| 缺 claim ⇒ fail closed（SECA-09b / M17） | ✅ 非 `int`（含 `None`）即不符；`bool` 单独挡（`True == 1`） | `app/auth.py:353-362` |
| 判定读表不读 claim | ✅ 比对对象是 `record.credentials_version`，claim 只当"要比哪个"的提示 | 同上 |
| `require_user` 先 token 腿再过门；`require_user_pending_password` 只走 token 腿 | ✅ 二者本就如此（Task 5 形状），本任务未改结构；两条腿现在都自动携带版本比对 | `app/auth.py:367-394` |
| `POST /api/auth/login` 加 `password_change_required`（取 `LoginResult`，不重新查表） | ✅ `result.password_change_required` | `app/main.py:261` |
| `GET /api/auth/me` 加同名键（读表） | ✅ `{**user.model_dump(), "password_change_required": _password_change_required(user.username)}` | `app/main.py:269` |
| 新建 `tests/test_password_lifecycle_contract.py`（令牌撤销用例） | ✅ 32 枚用例 / 5 subtests | 见 §3 |
| 追加令牌面到 `tests/test_authentication_leg_contract.py` | ✅ +3 枚（43 → 46） | 见 §2.2 |
| SECA-10 路由表枚举门（Step 5） | ✅ 覆盖 41 条认证端点，白名单等值钉 = `{"GET /api/auth/me"}` | 见 §4 |

`issue_token` 里 `record is None ⇒ cv=0` 按简报裁定实现，并被两枚用例钉住（值 = 0、且晚一步出现的凭据行（首版恒 1）也不会让它复活）。

### 1.2 与简报的字面差异（每一处都是"照抄必坏"）

1. **`_HTTP_METHODS` 加了 `PATCH`**。简报的 `{GET,POST,PUT,DELETE}` 在本仓今天就会 `IndexError`：`PATCH /api/conversations/{conversation_id}` 与 `PATCH /api/evaluation/failures/{case_id}` 真实存在。同时把 `_route_key` 的"取排序后第一个方法"改成**按方法逐行拆**（一条路由挂两个方法时，取第一项会静默丢掉第二条腿的覆盖面），并补一枚 `test_no_route_is_registered_with_several_http_methods` 钉住"今天没有多方法路由"这个前提——长出那天那枚红，提醒改判据。
2. **`_routes_using(auth.require_permission)` → `_routes_using(auth.require_permissions)`**。`require_permission(p)` 只是 `require_permissions(p)` 的一元门面，路由拿到的是工厂内部那个 `dependency` 闭包，**按对象身份永远比不上**（简报那行代码在本仓实测返回空集）。改成"对象身份 **或** 限定 qualname"两判据。漏掉这一处不影响覆盖面（闭包自己 `Depends(require_user)`，① 那条腿必然收到），但清单会把"权限族"记成零条，读起来像没接线。
3. **`PARAM_SAMPLES` 补了 `action` / `case_id` / `file_name` 三项**。简报那 7 项盖不住真实表：不补，三条端点会走 `self.fail` 分支——而那正是这条用例**故意**要红的形状，红在一个已经存在的端点上就等于误报。`document_id` / `kb_id` / `job_id` 今天表里没有对应端点，按简报原样留着（预登记，无害）。
4. **枚举必须 `import app.main_agent`**。生产入口是 `app.main_agent:app`（`backend/Dockerfile:24` 的 CMD），它把 agent / 会话 / 知识 OS 三张 router 挂在**同一个** `app` 实例上；只 `from app.main import app` 时表上只有 19 条端点、认证面只有 14 条——SECA-10 就成了只看半张表的门。加了一枚 `MUST_BE_COVERED`（规格 §8.4 点名的三条腿 + 名册那一面 + 两条 SSE）把"必须看到全表"钉成断言，同一手法在 `test_llm_usage_contract.py:73` 已是本仓先例。
5. **简报 Step 1 的夹具三处不可照抄**：① `_ClientCase.setUp` 不调 `super().setUp()`（`unittest` 的清理链会断）；② `LoginFaceKeyTests` 用 `self.client` 但没有 `setUp`（直接 `AttributeError`）；③ 每例叫 `seed_demo_credentials()` 会往 `SEED_RECORD` 里追加，撞红 `test_the_session_seed_happened_exactly_once`（SECA-24 的计数钉）。改用本仓既有形状：`_fresh_db` + `ensure_demo_credentials()`（后者不动台账）。
6. **`WHITELIST` 上方那句注释去掉了任务编号**（"Task 6 时…Task 7 落地时必须…"）。全局约束要求注释不得叙述任务/计划/评审轮次，改写成同等强度的"改密端点落地时必须同时把本集合扩成两项——多一条也红"。约束语义未动，且 §4 的反证证明了它今天就能红。
7. **额外收紧（简报未要求，方向是收紧）**：`cv` 的类型判定排除 `bool`；三格 401 文案（未登录 / 过期 / 无效凭证）各有一枚用例钉住不合并。

---

## 2. 被本任务合法改变形状的既有用例（SEC-A-006 审计面）

规则：既有断言**不放宽**，只允许"计划冻结的新行为使然"的形状改变。共 **6 枚**，全部有 RED→GREEN 记录。

### 2.1 `test_authentication_leg_contract.py`（Task 5 的文件，4 枚改变 + 2 枚新增）

Task 5 的门用例是"旧 token + 改密 ⇒ 403"。§7.5 之后 `set_password_argon2` 会 bump 版本，同一枚旧 token 先撞上**凭据纪元**那条 401，门根本没被走到。修法是把夹具顺序改成"先换代、再签 token"，让门拿到一枚活着的 token：

- `MustChangeGateTests` 新增 `_gated_token()`（换代在前、签发在后），`test_require_user_blocks_until_the_password_is_changed` / `test_the_whitelist_dependency_still_returns_the_user` / `test_the_gate_denial_is_audited_as_an_enum...` 三枚改用它。**403 + 中文文案 + 审计 token 三条断言一字未动。**
- `test_a_completed_change_reopens_the_gated_leg`、`test_authentication_still_comes_first` 未动。
- `HttpMustChangeGateTests.test_after_the_password_change_the_data_face_opens`：原来是"改密后旧 token 直接 200"——那正是 SECA-09 要拒的事。改成三段：旧 token 401「无效登录凭证」→ 用新口令重登 → 200。**断言变多、变强，没有一条被删。**
- 新增 `test_a_dead_token_does_not_reach_the_gate`（§8.4 顺序的反方向：换代后的旧 token 必须 401 而不是 403——判成 403 就等于把"会话已作废"说成"你去改个口令"，那是第二条撤销绕过）。
- 新增 `TokenClaimFaceTests`（简报"追加令牌面"）：一枚 `cv` 取自表的自签 token，把 `sub` 之外的 `name`/`role`/`access_role` 全部伪造成 ADMIN，断言回来的 `CurrentUser` 四个字段**逐个**来自表与身份文件，`grant is None`；第二枚钉 `cv` 写大 → 401、表换代后同一枚 → 401（"参与判定但权威在表"这一列）。

### 2.2 `test_feishu_identity_contract.py`（2 枚改变 + 2 枚新增）

- `AccessTokenClaimTests.test_forged_claims_do_not_widen_permissions`：那枚自签 token 没有 `cv` ⇒ §7.5 之后在认证步就 401，**三条"不放大权限"的断言变成死码**。改为经 `_forged_token()` 签发（`cv` 填表里的当前值），三条断言逐字未动。这正是 carried ruling #2 要保的那一枚；处理手法与认证腿切换时对同一文件的先例同族（`progress.md` 的 "Task 5: complete — … feishu 两条用例换注入接缝"：改的是喂进判定的形状，判定本身一字不动）。
- `ResponseContractTests.test_login_and_me_bodies_do_not_leak_grant`：`/me` 顶层多了一枚 §11 声明的 additive 键，那枚 `assertEqual(set(body), _LOCAL_KEYS)` 由"同一份期望集"改成**逐体期望集**：`user` 那一格仍是 `username/display_name/role/access_role/permissions`（证明新键只加在顶层、没塞进 `user`），`/me` 那一格是 `_LOCAL_KEYS | {"password_change_required"}`。**仍是等值钉**，多一个键也红。
- 新增 `test_a_claimless_token_is_rejected_rather_than_treated_as_legacy`（M17 的反向钉，与上面那枚成对）与 `test_a_forged_cv_does_not_buy_a_longer_session`。
- 该文件单跑：改前 `101 passed / 6 warnings`，改后 `103 passed / 6 warnings`——**警告计数未动**（新用例用一枚 ≥32 字节的临时 secret，`addCleanup` 还原；既有用例继续用它原本那把短钥匙，不顺手挪基线）。

### 2.3 未动的部分（反证清单）

`diff -rq` 快照证明 `backend/app/` 只有 `auth.py` 与 `main.py` 变了：`app/llm/`、`app/rag.py`、`app/conversation_agent.py`、`app/security.py` 逐字节相同。`test_typesafe_api_runtime.py` 的 `/api/query` 键集钉、`test_rbac_contract.py` 角色矩阵、`test_llm_egress_guard.py` 的 D6 豁免计数、V2.3 那 392 枚契约**一字未改且全绿**（见 §5）。Task 5 的锁定/容量行为未动：锁定路径零 Argon2 的两枚钉子、容量 500 未翻译的那枚反向钉都在原位原断言。

---

## 3. TDD 证据（RED → GREEN）

### 3.1 Step 1/2：新测试文件先红

```
cd backend && python -m pytest tests/test_password_lifecycle_contract.py -q
29 failed, 8 passed, 1 warning in 97.04s
```

红因逐条与"该红的东西"对齐（完整输出：`/tmp/t6/red-step2.txt`）：

- `AttributeError: module 'app.auth' has no attribute 'CREDENTIAL_VERSION_CLAIM'` ×8 —— `cv` 尚未签发。
- `AssertionError: HTTPException not raised` ×3 —— bump / 删行 / 伪造 `cv` 都没人判（撤销通道不存在）。
- 5 枚 `SUBFAILED`（`test_a_non_integer_cv_claim_is_rejected`，五种非整数取值全放行）。
- `KeyError: 'password_change_required'` —— additive 键尚未出现在两处响应面。
- `test_a_pre_seca_token_*_is_rejected...` 失败时**顺带产出一条 qdrant UserWarning**：cv-less token 当时真的通过了认证、`/api/query` 拨了向量库。这就是 M17 那个洞的可观测形态；实现后同一枚用例变绿且**警告计数归零**（`32 passed, 5 subtests passed`，无 warning）。

### 3.2 Step 3/4：实现后绿

```
python -m pytest tests/test_password_lifecycle_contract.py tests/test_authentication_leg_contract.py -q
78 passed, 12 subtests passed in 34.85s          # 46（认证腿）+ 32（本文件）
python -m pytest tests/test_feishu_identity_contract.py -q
103 passed, 6 warnings, 197 subtests passed       # 改前 101，+2 枚新用例，警告数未动
```

中间的 RED-for-existing-cases 也留了档：实现完成后先跑 Task 5 那套得到 `4 failed`（§2.1 预言的四枚），再跑 feishu 得到 `2 failed`（§2.2 预言的两枚），失败信息分别是 `AssertionError: 403 != 401`、`Expected '_record_event' to be called once. Called 0 times.`、`AssertionError: 200 != 401`、`Items in the first set but not the second: 'password_change_required'`、`HTTPException: 401: 无效登录凭证`。**没有一枚是"被删掉/被跳过"变绿的**（用例数只增不减）。

---

## 4. SECA-10 覆盖面门 + 反证（证明门不是装饰）

覆盖面事实（由 `app.routes` 遍历生成，非手写清单）：认证端点 **41** 条（`require_user` 腿）、其中经权限工厂的 **39** 条为其子集；免门依赖腿 **1** 条 = `GET /api/auth/me`；其余 4 条（`/`、`/api/health`、`/api/ready`、`/api/auth/login`）天然不在认证集内。逐条真打 HTTP：**41 条 403 + 中文文案**，白名单那 1 条另判 200——`GET /api/auth/me` 走的是免门腿、从来不在 `authenticated` 集合里，所以 `authenticated - pending` 不减任何一条（41 − 0 = 41）。表上出现的 8 个 path 参数全部登记了样例（只用必然不存在的 id）。

五发字节安全变异（脚本原先在仓库外 `C:\tmp\t6\mutate.py`；修复轮已把它搬进仓库 `.superpowers/sdd/SECURITY_A_PLAN/mutations/task-6-mutations.py`，六发（原五发 + 登录面第二读表）全部 KILLED 且 `restored sha1 match = True`——复现命令见 `task-6-fix-report.md`；每发打印注入前后 sha1，跑完立即还原并核对）：

| 变异 | 注入 | 结果 | 红的用例 |
| --- | --- | --- | --- |
| **M2** 去掉 `must_change` 门 | `auth.py`：`if _password_change_required(...)` → `if False and ...` | **KILLED**（`1 failed, 31 deselected`） | `test_every_authenticated_route_is_gated_or_whitelisted`（`unattended` 报出全部 41 条） |
| **M3** `require_user` 不再比对 `cv` | `auth.py`：`if claimed != record.credentials_version:` → `if False and ...` | **KILLED**（`3 failed, 6 passed`） | `test_a_bumped_version_invalidates_the_previously_issued_token`、`test_a_forged_cv_does_not_outlive_the_table`、feishu `test_a_forged_cv_does_not_buy_a_longer_session` |
| **M17** `cv` 缺失即放行 | `auth.py`：`claimed is None ⇒ claimed = record.credentials_version` | **KILLED**（`3 failed`） | `test_a_pre_seca_token_without_cv_is_rejected_not_allowed`（依赖面）、`test_a_pre_seca_token_is_rejected_by_the_data_face_too`（`/api/query` HTTP 面）、feishu `test_a_claimless_token_is_rejected_...` |
| **白名单外泄**：把 `GET /api/audit` 从权限腿改挂 `require_user_pending_password` | `main.py` 一处依赖 | **KILLED**（`1 failed`） | 同一枚枚举用例，消息 `'GET /api/audit' : 白名单外泄：有端点改走了免门依赖` |
| **新增端点带未登记 path 参数**：临时插一条 `@app.get("/api/zz-probe/{widget_id}")`（走 `require_permission("audit:read")`） | `main.py` 一处 | **KILLED**（`1 failed`） | `AssertionError: 新增端点带未登记的 path 参数，请把样例加进 PARAM_SAMPLES：GET /api/zz-probe/{widget_id}` |

后两发正是任务书点名的两个反证：**"一条端点被错挂到 `require_user_pending_password`" 会红**（等值判定，多一条也红），**"新增端点没人登记" 会红并指名该条路由**（不是猜值混过）。第二条同时证明枚举对新路由的自动纳入——插入的路由立刻进了 `authenticated` 集合。

`M3` 那一发还顺带说明覆盖面归因准确：删掉版本比对时，删行/停用那几条**没红**（它们走的是 `record is None` 与 `enabled` 那两臂），只有三枚真·版本用例红——判据没被糊成一团。

---

## 5. 全套件（回归门）

| 命令 | 结果 |
| --- | --- |
| `cd backend && python -m pytest -q` | **1162 passed, 36 warnings, 1101 subtests**（首跑 128.78s；末次复跑在 `snap-task6-app` 与工作树核为相同之后，146.69s） |
| `cd /e/xiangmu/rag && python -m pytest backend/tests -q` | **1162 passed, 36 warnings, 1101 subtests**（127.15s，末次复跑同数） |

两 cwd **逐位相等**、零 failed / 零 error。进入基线 1125 / 36 / 1096 ⇒ **+37 用例**（新文件 32 + 认证腿 3 + feishu 2）、**+5 subtests**（本文件的非整数 `cv` 五种取值）、**warnings 未增**。

其余定点门：

- `test_password_lifecycle_contract.py + test_authentication_leg_contract.py`：`78 passed / 12 subtests`
- SEC-A-006 四件套（rbac + typesafe_security + feishu + typesafe_api_runtime）：`140 passed / 197 subtests`（进入 138，+2 是 feishu 新增两枚；`/api/query` 键集钉在内且未动）
- V2.3 + 出口守卫：`427 passed, 18 warnings, 452 subtests`（与进入同数，D6 豁免计数一字未动）

**生产污染复核**：跑完后两份真库（`backend/data/conversations.db`、仓库根 `data/conversations.db`）表清单里**仍无 `user_credentials`**；`[credential-guard]` 在两份输出里**一行未打**（该报告函数在 records 为空时静默 ⇒ 零改道、零写行、凭据增长台账为空）；`data/audit.jsonl` 末 900 条里本任务用的账号名（`gated` / `revoker` / `paused` / `ghost`）出现 **0 次**（本文件所有会触发审计的用例都把 `AUDIT_PATH` 打到临时文件）。工作树：`git status --porcelain` 相对开工只多 `?? backend/tests/test_password_lifecycle_contract.py` 一行，无探针/草稿文件；`.superpowers/sdd/SECURITY_A_PLAN/` 下只有 `snap-task6-pre-*` 与 `snap-task6-app` / `snap-task6-post-*` / `snap-task6-test_password_lifecycle_contract.py` 这几份快照。
换行形态：`app/main.py` 779/779 全 CRLF（外科式改动，未整文件翻齐）；`app/auth.py` 405 LF、三个测试文件全 LF。

**变异跑完之后复跑**：覆盖面门与撤销门对 HTTP 的依赖止于依赖层（401/403 都在进业务之前），因此这几套**不碰外部服务**——`python -m pytest tests/test_password_lifecycle_contract.py tests/test_authentication_leg_contract.py tests/test_feishu_identity_contract.py -q` ⇒ **181 passed, 6 warnings, 209 subtests**；全套件也在最后一次用例微调之后于两个 cwd 各复跑一次，仍是 **1162 / 36 / 1101**（见上表）。三份产品/测试文件的 sha1 与变异前逐字节相同（五发各自 `restored sha1 match = True`）。

---

## 6. 自审发现（读自己的 diff 得到的东西）

1. **每认证请求多两次凭据表读**：`_user_from_token` 读一行（版本 + 存在性），`require_user` 里的 `_password_change_required` 又读一行。都是主键查、都是既有"每请求一连接"的形状，但同一次请求里对同一行读两遍是可以并掉的。没并的理由：并它要么把 `CredentialRecord` 塞进 `CurrentUser`（凭据面渗进响应面模型，Task 1–5 辛苦分开的两个真源立刻糊掉），要么让 `_user_from_token` 返回元组（构造面裂成两条路径，正是简报裁定禁止的）。留作 Task 8 的节流/容量工作一并量——那一层本来就要动每请求成本。
2. **`main.py` 从 `app.auth` 导入了下划线名 `_password_change_required`**。简报明写这个写法，且它的价值恰好是"和 `require_user` 的门共用同一个判定函数"（两处读数劈叉是响应面事实错误，不是风格问题）。若评审更接受公共名，`password_change_required(username)` 是一次两行改名 + 两处调用点，本任务不擅自改既有函数名。
3. **门的真实边界**（已写进新文件的模块 docstring，不留给下一个人猜）：枚举判的是"**已被认证覆盖**的端点有没有都过门"。一条压根不挂认证依赖的新端点、或自造第三条依赖绕开这两个门面的新端点，不在本门判定对象内——简报明说"不需要维护豁免清单"，所以没顺手补一份"公开路由白名单"。要真堵这一格，得反过来维护"允许不鉴权的路由集合"，那是简报否掉过的形状。
4. **`cv=0` 的可达面**：今天只有"有身份无凭据行"这一种身份能拿到 `cv=0`（且它在 `record is None` 那一臂就先出局）。它不是死码，是一枚"两种判据不许分叉成放行"的钉（`test_version_zero_never_matches_a_real_row_however_later_it_appears`）。
5. **规格 §11 的一条事实不成立**（要回写）：`docs/SECURITY_A_SPECIFICATION.md:458` 写"全仓无登录响应键集合断言（既有 8 处只读 `["access_token"]`）"。实测**有一处**：`test_feishu_identity_contract.py` 里那枚 `assertEqual(set(body), _LOCAL_KEYS)`（改动前在 `:1775`，改动后在 `:1776-1780`）同时钉着 `/login` 的 `user` 子体与 `/me` 的顶层体。它没让加键变成破坏性变更（改的是测试侧期望集），但"零断言"这个论证本身是错的，Task 10 的验收文档若照抄会留下一句假话。
6. **`directory` 缓存与 `enabled` 的真实关系**（本任务把它钉成了事实而不是假设）：`identities()` 按形态缓存、只有 `reset_cache()` 复位 ⇒ 运维改文件那一刻，在线进程读到的 `enabled` 还是旧值。所以"只钉身份侧那一半"会把一条运维假设当契约，本文件因此三枚各钉一半：身份侧单独（进程已看到 `false`）、**凭据侧单独**（缓存陈旧时唯一有效的那一半，且就是 §6.4 成对动作的第二半）、两半合力上 HTTP 面。顺带把认证腿切换时留下的那条交接（"登录腿必须消费 `enabled=false`，否则半收敛不收口"）**在两条腿上都收掉**：登录腿那半是前一任务收的，令牌腿这半是本任务收的。
7. **覆盖面门有一处运维危险，必须写在脸上**：这条用例对**每一条**认证端点发出真请求，它的安全性完全押在"门会先挡住"上。做 M2（去门）反证时，那 41 条请求就落在没有门的真端点上，其中 `POST /api/demo/reset` / `POST /api/demo/initialize` 是**破坏性**的。本次实测未伤到数据，证据是三样：`data/documents/**` 与 `document_registry.json` 的 mtime 仍是 09-11 / 09-22 / 09-22（`reset_demo()` 会先 unlink 再 `write_bytes` 全部 20 份，目录 mtime 必然变），审计面今日零 `DEMO_*` / `DELETE` / `INGEST` 事件，且 `delete_document` 那条还多一道 `knowledge_base_id` 必填 query 的 422 前挡。即便如此，**这条用例的可重复危险是真实的**：以后在任何"有真实 demo 数据且向量库可达"的机器上跑 M2，就会真重置一次演示语料（可从仓库内 `demo-data/` 一键 `initialize` 复原，破坏有界）。若评审要收紧，最小改法是把 `_gated` 对**写面**端点只断言依赖链、不发请求——代价是覆盖面从"真 403"降级成"依赖树里有门"，本任务按简报的"每条都要真 403"执行，未擅自降级。

> 【上面那两行的处置已被修复轮替换】"只断言依赖链、不发请求"那个收紧方案被否掉：写进 `pending` 集合的成员资格本身就是被遍历出来的判据，对 21 条写面端点等于自证。落地的是第三条路——**每条真请求照发，而处理器逐条不可达**（`dependant.call` 绊线桩 + 派发目标核对 + demo 入口设哨 + 扫描后不留桩），见 `task-6-fix-report.md` 的 I-1。本处保留原文，因为它记着当时"为什么没收紧"的判断和它被推翻的理由。
8. **环境观测（如实记录，不拿来当挡箭牌）**：五发变异跑完之后，宿主上 `curl http://localhost:6333/collections` 与 `docker ps` 一度超时（Docker Desktop 引擎不应答），当时不能确定全套件还能不能复现。实际复跑结果：**两 cwd 再次各 1162 / 36 / 1101 全绿**（含最后一次用例微调之后），认证三件套单跑 181 passed 亦服务无关 ⇒ 那一次超时是一次性抖动，不影响本任务交付数。留这一条是为了下一个人：见到 `curl :6333` 卡住时先复跑再怀疑代码。

---

## 7. Concerns / 交接

1. **给改密腿（Task 7）的硬事实**：改密成功那一刻旧 token 连 `/me` 也进不去（`test_the_pending_leg_compares_versions_as_well` 已钉）。因此 `POST /api/auth/password/change` 必须在同一响应里**签一枚新 token**（或客户端重登），否则用户改完口令会被踢出改密流程本身。同时 `WHITELIST` 必须扩成两项——§4 的白名单外泄反证已经证明漏扩必红。
2. **上线即一次强制重登录（SECA-09b 的代价）**：所有 SEC-A 之前签发的会话在部署后第一次请求就 401。文案与"凭证无效"同形，不额外提示"你为什么被踢"。这条必须进 §15 release note，不得写成"无感升级"（规格自己就是这么要求的，实现没有偷偷做软）。
3. **计划文本需要回写**：`docs/SECURITY_A_PLAN.md` Task 6 Step 1/5 那几段（= 本次简报）若被后续任务复用，需带上 §1.2 的 1–5 项修正（PATCH 方法、工厂闭包、三个 path 参数、`main_agent` 导入、夹具不能用 `seed_demo_credentials`）。同族先例是 Task 4 的 `^[0-9a-f]{64}$` 与简报用例自相矛盾那条。
4. **既有形状的可疑点（本任务没动，登记给收口）**：`_user_from_token` 用 `str(payload.get("sub", ""))` 取名，空 `sub` 会走"不认识主体"那一臂（行为正确）；但 `sub` 带首尾空白的 token 与身份文件的键永不重合，也是出局——两条路都不泄露区别，符合 §9.1，暂不改。另：Task 5 留的 `install_demo_credentials` 存在分支无专用用例、`LedgerGuard` 改名 `RedirectGuard` 仍挂着，都是 Task 10 的账。
5. **未验证的外部事实**：全套件的两 cwd 等数是在本机（Qdrant 在场、OpenAI key 为空、`CONVERSATION_DB_PATH` 未预设）测的。枚举门里 `/api/query` 等端点拿 403 靠的是依赖层先返回，与向量库/模型可达性无关，因此那部分在 CI 上应同形；但 `MUST_BE_COVERED` 依赖 `app.main_agent` 的 router 注册，若 CI 用 `--ignore` 或 `PYTHONDONTWRITEBYTECODE` 之外的非常规装载方式跑，需以红为准而不是就地放宽。

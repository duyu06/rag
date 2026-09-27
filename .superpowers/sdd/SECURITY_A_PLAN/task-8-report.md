# Task 8 报告：两层节流与容量护栏（`login_throttle.py` + 429 / 503）

工作状态：**完成**。全套件两个 cwd 各 `1221 passed / 36 warnings / 1114 subtests`，零失败、计数相等。
本文件按门增量追加；每一段写的都是已经跑出来的东西。

## 0. 快照

- `snap-task8-pre-app/`（`backend/app` 改前全量）
- `snap-task8-pre-test_authentication_leg_contract.py`
- `snap-task8-pre-test_password_lifecycle_contract.py`
- `snap-task8-pre-conftest.py`

## 1. RED 证据（实现落地后、追加测试前的两处必然红）

`cd backend && python -m pytest tests/test_authentication_leg_contract.py -q`

```
FAILED tests/test_authentication_leg_contract.py::PasswordCapacitySurfaceTests::test_capacity_exhaustion_still_escapes_the_login_leg_as_an_unhandled_500
FAILED tests/test_authentication_leg_contract.py::AuditVocabularyTests::test_the_enum_lives_in_one_tuple_and_the_writer_is_the_one_that_checks_it
2 failed, 44 passed, 4 subtests passed in 48.04s
```

两条都不是回归，而是**被本任务要求改断言的既有钉子**：

1. `PasswordCapacitySurfaceTests` 是 Task 6 埋的**反向钉**：它断言的是"没人翻译 ⇒ 未处理 500 + 零审计"这个当下缺口。
   本任务把 `PasswordCapacityError → 503 + 「服务繁忙，请稍后重试」+ password_capacity` 落地，缺口关掉，
   于是它必须**翻断言而不是删用例**（Task 6 裁定，也是本任务的 carried obligation 1）。
2. `test_the_enum_lives_in_one_tuple_and_the_writer_is_the_one_that_checks_it` 把 `LOGIN_AUDIT_DETAILS`
   钉成三元组。本任务按 obligation 6（"加 token 就扩枚举，不绕开 writer"）新增
   `login_throttled` / `password_capacity` 两枚 ⇒ 值域容器变五元组，成员判定与出口自检那两半都原样保留。

（Step 1–2 的原始 RED 见 §5：`ModuleNotFoundError: No module named 'app.login_throttle'`。）

## 2. 实现 vs brief（含裁定）

| # | brief 原文 | 落地 | 裁定理由 |
|---|---|---|---|
| D1 | `login_throttle.LoginThrottled` 与 `auth.LoginThrottledError` **两枚**异常类 | 只留 `login_throttle.LoginThrottledError`，`auth`/`main` import 同一个类 | 两枚同义异常必然出现"catch 错那一枚"的缝；测试要的是 `auth.LoginThrottledError` 这个名字，import 即得，不必是第二个类。 |
| D2 | `is_locked` 返回 `(now or utcnow) >= moment` | 返回 `moment > (now or utcnow)` | brief 的方向写反了（`locked_until` 是未来时刻，`now >= until` 意为"已过期"）。写反的症状正是 Task 5 注释点名的"永远锁不住"，且当场把 `test_a_locked_account_reports_the_internal_detail_only` 与 `_put_locked_until("admin", "2099-01-01 00:00:00")` 两枚钉子判红。按规格 §7.2 判，不按 brief 判。 |
| D3 | naive 时间戳 `moment.replace(tzinfo=utc)` 后参与比较 | naive **即 fail closed 当锁定**，不替它补 UTC | Task 5 的裁定是"能解析却无偏移 ⇒ 这一行不再可信"。替它猜一个偏移会把同一行读成"说没锁"，属于 SEC-A-006 不许的放宽；而 `2099-01-01 00:00:00` 那枚钉子在任何解释下都该红，补 UTC 只是恰好没红。 |
| D4 | `test_expensive_work_is_skipped_once_the_bucket_is_exhausted` 先耗尽 `throttle_bucket("admin", "10.0.0.9")`，再调 `authenticate_with_result("admin", …)`（无 `client_ip`） | 该调用补 `client_ip="10.0.0.9"` | 原样写来的桶是 `admin|`，与被耗尽的 `admin|10.0.0.9` 不是同一格 ⇒ `assertRaises` 永不发生。这条测试的意图（SECA-15：闸门在运算前）只有同键才成立。 |
| D5 | `test_many_source_addresses_on_one_username_share_the_account_lock` 里 `ip` 循环变量**未使用**，且固定 4 个地址 | 真的逐地址传 `client_ip`，地址数取 `settings.account_max_failed_attempts` | 两点都是 brief 自身的缺陷：不用 `ip` 就测不到"分布式"；4 < 阈值 5 ⇒ 账号根本不锁，断言 `locked_until is not None` 必假。 |
| D6 | `test_the_capacity_gate_surfaces_as_a_capacity_error_not_a_denial` 用 `import_legacy_digest("gate", …)` 造行后期望 `PasswordCapacityError` | 原样保留（该账号不在身份声明文件里 ⇒ 走哑校验腿，槽满即抛） | 已核实：legacy 行的 `verify_password` 不碰槽，抛点来自 §7.3 的恒定成本腿。这条与既有 `test_capacity_exhaustion_is_the_same_on_the_dummy_leg…` 同族，保留不冗余。 |
| D7 | `LockedHttpFaceTests(unittest.TestCase)` + `from app.audit import recent_events` | 改挂 `_LongJwtSecret, _AuditToTempFile`，取证读 `self.events()` | 原样写会把测试笔迹写进仓库的 `data/audit.jsonl`（本任务硬约束"东西不许落进 `backend/data/`"），且默认短 JWT secret 会带出 `InsecureKeyLengthWarning`。断言内容一字不改。 |
| D8 | 只在登录腿加翻译 | 登录腿与 `/api/auth/password/change` **两条腿**共用同一个 helper `_auth_availability_denial` | obligation 1 与 4：改密腿带旧口令校验，是第二个容量面与同一个猜测面；两条腿各抄一遍 `except` 就是留给"其中一条忘了 503"的缝。 |
| D9 | `PreHashThrottle` 单桶剪枝 | 另加 `_sweep_stale()`：每个窗口至多一次整表回收（判据=最近一次命中已出窗） | 单桶判据只清空**被再次命中**的桶；来源地址打不停时桶个数=请求数，节流表自己长成内存增长面——DoS 护栏自身不许有 DoS 面。语义与逐桶剪枝等价（丢掉的桶再命中即重新计入），不改 `allow` 的任何答复。 |
| D10 | 未提测试侧节流状态隔离 | `tests/conftest.py` 加 autouse `reset_login_throttle`；`sec_a_fixtures.fresh_db` 换库时一并 `reset()` | 第一层是进程内状态而整套件同进程：不隔离则"第 11 次登录的用例"收到 429，红的是无关用例。生产侧清零只发生在窗口过期/进程重启，这两件都不是测试之间可借用的通道。 |

其余按 brief 落地：`client_ip_of` 只认 `request.client.host`、`throttle_bucket` 用 `casefold()`、
`PreHashThrottle` 的锁与滑动窗口、`reset()`、`configured_throttle()`、单例 eager 构造（与 `credentials._SLOTS` 同口径）。
配置面**只**新增两枚 `login_throttle_window_seconds=60` / `login_throttle_max_attempts=10`；
`argon2_max_concurrent_ops` 与 m/t/p 常量位置未动（SEC-A-008）。
本地 `_locked` 已**删除**，判定唯一真源是 `login_throttle.is_locked`。

## 3. 七条 carried obligations 状态

1. 容量钉**翻不删** + 覆盖两脸：**完成**（见 §3b 第 1 条与 §7）
2. 删本地 `_locked` / `is_locked` fail closed / 零 sleep：**完成**（`grep -n "_locked" backend/app/auth.py`
   只剩 `login_throttle.is_locked(...)` 那一行与它的注释；`grep -rn "def _locked" backend/app/` 零命中。
   AST 的 sleep 用例把 `login_throttle` 也扫进调用图）
3. `client_ip` 上腿 + `request.client.host` 下传 + 不信 XFF：**已落地**（不变量写在 `client_ip_of` 的 docstring 里，不是任务笔记）
4. 改密腿共享桶与锁、不新增计数器：**完成**
5. 两层两键、SECA-16a/16b 各有直接断言：**完成**（P1/P2 两条证伪各自对应其一）
6. 配置面恰两枚新旋钮：**已落地**
7. 未碰 no-echo 处理器的路径谓词 `_is_no_echo_auth_path`：**已核实**（diff 里没有它）

## 4. 改动文件

- 新增 `backend/app/login_throttle.py`
- `backend/app/config.py`：+2 枚节流旋钮
- `backend/app/auth.py`：+2 token / +2 中文文案常量、`_locked` 删除、腿加 `client_ip` 与步骤 0
- `backend/app/main.py`（CRLF，逐处字节核对）：两腿 `http_request: Request`、`_auth_availability_denial`、两处 `except`
- `backend/tests/conftest.py`：autouse 节流清零
- `backend/tests/sec_a_fixtures.py`：`fresh_db` 附带节流清零
- `backend/tests/test_authentication_leg_contract.py`：+14 用例（3 个新类）+ 1 枚反向钉翻断言 +
  1 枚值域容器钉子扩为五元组 + AST 调用图扩入 `login_throttle`；46 → 60 passed（7 subtests 不变）
- `.superpowers/sdd/SECURITY_A_PLAN/mutations/task8_proofs.py`：证伪四则的可复跑脚本（含逐条字节还原核对）
- `.superpowers/sdd/SECURITY_A_PLAN/snap-task8-app/`：实现完成后的 `app/` 快照（与 pre 快照配对）

## 5. 测试与证据（GREEN）

追加的测试类与用例（`backend/tests/test_authentication_leg_contract.py`，46 → **60 passed, 7 subtests**，
subtest 数与基线一字未动）：

- `ThrottleLayerTests`（6）：SECA-15 昂贵运算跳过、SECA-16a 桶键含 `client_ip`、
  SECA-16b 账号锁只认 username（含"换新地址读同一行仍是锁"）、窗口滑动、
  成功登录清持久计数、容量溢出抛 `PasswordCapacityError` 而非认证结论。
- `ThrottleHttpFaceTests`（3）：429 + 中文文案 + `login_throttled` 审计；
  429 面对"存在的账号"与"不存在的账号"**逐字节相同**（存在性 oracle 不成立的直接证据）；
  改密腿与登录腿共用同一格桶（换腿不清零 ⇒ 同一猜测面一把计数）。
- `LockedHttpFaceTests`（2）：锁定 / 口令错 / 未知账号三脸同形 + 锁定原因只到审计面。
- `PasswordCapacitySurfaceTests`：Task 6 反向钉**翻断言**（503 + 「服务繁忙，请稍后重试」+
  `password_capacity`，用例保留，方法名改称 `…_surfaces_as_a_translated_503_on_the_login_leg`）
  + 新增 2 条：未知账号同脸、改密腿第二个容量面。
- `AuditVocabularyTests`：新增 `test_the_two_availability_tokens_keep_their_frozen_spellings`；
  值域容器钉子由三元组扩为五元组，成员判定与"值域外文本必抛"两半原样保留。

`cd backend && python -m pytest tests/test_authentication_leg_contract.py -q`
```
60 passed, 7 subtests passed in 50.49s
```

各门（同一实现态下逐条跑）：

```
tests/test_password_lifecycle_contract.py                77 passed, 12 subtests passed in 55.33s   （与基线同数）
tests/test_rbac_contract.py + typesafe_security + feishu_identity + typesafe_api_runtime
                                                         140 passed, 13 warnings, 203 subtests (1:29)
tests/test_credentials_contract.py + test_user_directory_contract.py
                                                         121 passed, 82 subtests passed in 37.36s
tests/test_model_router_v23_contract.py + tests/test_llm_egress_guard.py
                                                         427 passed, 18 warnings, 452 subtests (1:14)  D6 计数未动
```

`_is_no_echo_auth_path` 未被触碰（diff 里没有它）；AST 的 sleep 扫描调用图**扩**入
`login_throttle`（新增一层就在新增一层里禁延迟），四条原用例一字未松。

## 6. 证伪四则

跑法：`cd backend && python ../.superpowers/sdd/SECURITY_A_PLAN/mutations/task8_proofs.py`
（脚本改坏 → 跑 `tests/test_authentication_leg_contract.py --tb=no` → 按**原始字节**整份还原，
`identical=True` 即树里没有残留；sha1 取前 12 位）

```
[P1  M6: throttle key drops client_ip -> SECA-16a] sha1(mutated)=e92dfed7df66
      test_two_source_addresses_on_the_same_username_have_independent_buckets
      1 failed, 59 passed, 7 subtests passed in 41.29s
      sha1(restored)=eb4f19b69f60 identical=True
[P2  M7: persistent lock keyed by (username, ip) -> SECA-16b] sha1(mutated)=7c14857939f4
      test_a_successful_login_clears_the_failed_attempt_counter
      test_a_wrong_password_counts_a_failure_and_keeps_the_credential_row
      test_the_account_locks_at_the_configured_attempt_ceiling
      test_a_wrong_password_on_a_legacy_row_consumes_one_argon2_run_too
      test_many_source_addresses_on_one_username_share_the_account_lock        <-- SECA-16b
      test_locked_wrong_password_and_unknown_account_are_the_same_http_face
      test_the_lock_reason_reaches_the_audit_face_only
      7 failed, 53 passed, 7 subtests passed in 46.67s
      sha1(restored)=ec9cf2f7aad2 identical=True
[P3  SECA-15: throttle gate moved after the Argon2 verify] sha1(mutated)=2b6b62963732
      test_expensive_work_is_skipped_once_the_bucket_is_exhausted              <-- SECA-15
      test_the_429_face_is_byte_identical_for_a_known_and_an_unknown_account
      2 failed, 58 passed, 7 subtests passed in 57.65s
      sha1(restored)=ec9cf2f7aad2 identical=True
[P4  capacity translated to 401 instead of 503 -> flipped pin] sha1(mutated)=4de88aa2da80
      test_capacity_exhaustion_surfaces_as_a_translated_503_on_the_login_leg    <-- 翻过的钉
      test_the_capacity_face_says_the_same_thing_about_an_unknown_account
      test_the_change_leg_is_the_second_capacity_face_and_gets_the_same_503
      3 failed, 57 passed, 7 subtests passed in 56.28s
      sha1(restored)=fc655c7cb0bb identical=True
```

四条都**只有该红的那条先红**：P1 是唯一能杀 M6 的用例（其余 59 条全绿，说明去掉 `client_ip`
不会顺带把别的东西碰坏——也就说明没有别的用例在替它兜底）。P3 的突变把检查整段挪到
`credentials.verify_password` 之后：`assertRaises(LoginThrottledError)` 仍然成立，红的正是
`verify.assert_not_called()` 那一格——这条钉子判的是**顺序**而不是"有没有抛"，写得动它才算数。

## 7. 全套件计数（两个 cwd，等数、零失败）

```
cd /e/xiangmu/rag/backend && python -m pytest -q -p no:cacheprovider
  1221 passed, 36 warnings, 1114 subtests passed in 231.97s (0:03:51)
cd /e/xiangmu/rag && python -m pytest -q -p no:cacheprovider
  1221 passed, 36 warnings, 1114 subtests passed in 218.84s (0:03:38)
```

对基线 `1207 passed / 36 warnings / 1111 subtests` 的三格差都逐条查过产地，没有一格是"少测了"：

- **+14 用例**：本任务追加的 14 条（`ThrottleLayerTests` 6 / `ThrottleHttpFaceTests` 3 /
  `LockedHttpFaceTests` 2 / 容量面 2 / 审计词汇 1）。
- **+3 subtests**：`test_feishu_identity_contract.py::test_no_by_role_scope_call_anywhere_in_the_package`
  对 `app/` **每个 .py 文件 × 3 枚 legacy 串**各开一枚 subTest。本任务新增一枚模块文件
  ⇒ 3×1=3。也就是说这 3 格是"新模块被纳进那条整包扫描"的结果，方向是**收紧**，不是放宽。
- **warnings 36 → 36**：新增面一枚警告都没带出来（用例自带长 JWT secret，审计落临时文件）。

跑序与一处时序如实记下：`main.py` 的两行 import 顺序整理（把 `app.login_throttle` 挪到
`app.llm.usage` 之后）发生在 backend-cwd 那一跑**之后**、root-cwd 那一跑**之前**。
它只是同一批名字的 import 语句换了行序（无副作用、无环），两跑的计数与警告逐字相同即为佐证。
最终态 sha1（前 12 位）与行尾：`login_throttle.py eb4f19b69f60 LF`、`auth.py ec9cf2f7aad2 LF`、
`main.py 1133604dc9e2 CRLF`（962 行全 CRLF、零裸 CR）、`config.py fb43a6741d17 CRLF`（改前后同形）。

`backend/data/` 干净：`grep -c "login_throttled\|password_capacity" data/audit.jsonl` = **0**
（新增的两枚可用性 token 一条也没落进仓库真库的审计文件；conftest 的两道写护栏全程零判红）。

## 3b. obligations 收口（跑完后）

1. 容量钉**翻而不删**，登录面 + 改密面两脸都覆盖：`test_capacity_exhaustion_surfaces_as_a_translated_503_on_the_login_leg`
   / `test_the_change_leg_is_the_second_capacity_face_and_gets_the_same_503`；"为什么不构成枚举面"
   写在 `test_the_capacity_face_says_the_same_thing_about_an_unknown_account` 与
   `test_the_429_face_is_byte_identical_for_a_known_and_an_unknown_account` 的 docstring 里 ✓
2. `auth._locked` 已删（`grep -rn "_locked" backend/app/auth.py` = 0 命中），判定唯一真源
   `login_throttle.is_locked`，坏值/naive 一律 fail closed；AST 的 sleep 扫描调用图扩入
   `login_throttle` 后仍绿 ⇒ 新增那一层里也没有人工延迟 ✓
3. `client_ip` 上腿、两脸都从 `request.client.host` 下传；不读 `X-Forwarded-For` 的理由以
   **不变量**写在 `login_throttle.client_ip_of` 的 docstring（"将来真要前置 nginx，改的是这里"），
   不是任务笔记 ✓
4. 改密腿同桶同锁、无第二把计数器：`test_the_change_leg_shares_the_bucket_and_gets_the_same_429` ✓
5. 两键不合并 + SECA-16a/16b 各有直接断言（P1/P2 两条证伪各自只杀掉对应那一条的前置证据）✓
6. 配置面恰两枚新旋钮，`argon2_max_concurrent_ops` 与 m/t/p 常量位置未动 ✓
7. `_is_no_echo_auth_path` 未进 diff ✓

## 8. 自查与顾虑

自查（对着 diff 逐条问过自己）：

- `app/` 只有 4 处变化：新增 `login_throttle.py`、`auth.py`、`config.py`、`main.py`。
  `diff -rq snap-task8-pre-app backend/app` 除此之外零命中 ⇒ `llm/`、`rag.py`、
  `conversation_agent.py`、`security.py` 一字未动。
- `_is_no_echo_auth_path` 不在 diff 里（obligation 7）✓；Task 7 的逐字节 no-echo 用例仍在
  `test_password_lifecycle_contract.py` 的 77 条里绿着。
- 行尾：`main.py` 全 CRLF（962/962，零裸 CR）、`config.py` 沿用其既有的 CRLF（改前 186/186、
  改后 192/192）、`auth.py`/`login_throttle.py`/测试文件全 LF。
- 本地 `_locked` 已从 `auth.py` 删除，全仓 `grep -n "_locked\b"` 只剩
  `record_login_failure(..., lock_seconds=...)` 那类参数名与测试里的 `_put_locked_until` helper。

顾虑（如实记下，不粉饰）：

1. **桶把成功登录也算进配额**：`allow()` 无条件计入，所以"同一 (账号, 来源地址) 60 秒内
   第 11 次登录"必吃 429，哪怕前 10 次都是本人成功登录。这是 brief 的形状（也是第一层
   唯一的形状——只计失败就挡不住"成功"名义下的昂贵运算洪水）。默认 10/60s 对 demo 的
   四个账号足够，但**同一 NAT 出口后的多人**会共用一格桶。运维文案与阈值该由 Task 10 收口。
2. **429 没带 `Retry-After`**：§9.1 只约束两栏文案，没要求该头；前端现在靠文案自己退避。
   补一枚 `Retry-After: <window>` 是纯增益，但它改响应面字节 ⇒ 留给明确授权的改动。
3. **`client_ip_of` 在 `request.client is None` 时回落 `"unknown"`**：方向是 fail closed
   （所有此类请求共用一格桶，只会更早被限），但那条 ASGI 形态在本仓不可达（uvicorn 恒给
   `scope["client"]`），所以这条臂没有测试覆盖它——写了却不声称验过。
4. **改密腿的 429/503 审计走 `LOGIN` 动作族**（`record_login_event`），而不是 `PASSWORD`：
   值域只有一处真源是这条出口的立身理由，为一条腿另开 writer 就等于允许自由文本。代价是
   该事件的 `role` 恒为 `UNKNOWN`（出口的形状冻结），即使 actor 其实已经鉴过权。
5. `_sweep_stale()` 是 brief 之外**加**的（D9）：它不改变 `allow()` 对任何在场桶的答复，
   只把"见过的地址数"这个无上限压回"一个窗口内在场的地址数"。若评审认为越界，删掉它
   不影响任何一条断言（`test_the_bucket_slides_once_the_window_passes` 也不依赖它）。
6. **测试侧的节流清零有两处接缝**（conftest autouse + `fresh_db`）：这是"进程内状态 vs
   同进程整套件"的必要代价。风险是它顺手把真实用例里"跨用例累积"这一格测不到了——
   累积语义本就由 `ThrottleLayerTests` 在单个用例内部钉，不靠跨用例泄漏。

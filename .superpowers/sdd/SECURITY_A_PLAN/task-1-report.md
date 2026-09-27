# SECA Task 1 执行报告 —— Argon2 口令原语（`backend/app/credentials.py`）

轮次：2026-09-25 15:40 +0800，宿主 Python 3.13.7（`C:\Users\zhang\...\Python313`），Windows / Git Bash。
输入：`.superpowers/sdd/SECURITY_A_PLAN/task-1-brief.md`（= `docs/SECURITY_A_PLAN.md` Task 1 逐字提取）。
本轮**未执行任何 git 写命令**（无 add / commit / stash / checkout / reset），台账行留给控制台。

## 结论

**DONE_WITH_CONCERNS。** 原语本体（`credentials.py` + `settings.argon2_max_concurrent_ops` + `requirements.txt`）按 brief 逐字落地，8 条行为用例全绿，全套件除 brief 自带的 2 条 `CentralisationScanTests` 外零失败。

> **轮 2 终态（控制台裁定后）：`10 passed`，全套件 `971 passed` 零失败** —— 见 §8。§1–§5 是轮 1 的现场记录（含当时那 2 条红的完整根因链），按快照纪律原样保留、不覆写；§7 是四项裁定的回执，§8–§10 是轮 2 的落地、逐字偏离量化与可证伪性实测。CONCERNS 只剩两条**计划侧**待办（§8.8 的 M13 空门、§8.7 交给 Task 5 的 F3/F5），代码侧本轮无未收口项。

那 2 条红**不是实现缺陷，而是 brief/计划自身的三处缺陷叠加**（见 §5 F1/F2），在 Task 1 的文件边界内无法转绿：修它要么改 brief 钉死的测试代码，要么提前做 Task 5 Step 6（删 `auth._password_digest`，会打断现存一批登录用例）。两条都是控制台裁定，不该由执行侧静默改，因此**测试与实现均保持逐字原样**，在此如实报告。

---

## 1. 按 brief 步骤的落地对照

| Step | 结果 | 实测 |
| --- | --- | --- |
| 1 装依赖 | ✅ | `pip install "argon2-cffi>=23.1.0,<26"` → `argon2_cffi-25.1.0` + `argon2_cffi_bindings-26.1.0`（win_amd64 abi3 轮子，无需编译）；`import argon2` 成功，版本 `25.1.0`。容器侧未验（brief 明确交 Task 10 双向探针） |
| 2 写失败测试 | ✅ | 新建 `backend/tests/test_credentials_contract.py`，与 brief 代码块**逐行 identical**（脚本核对，见 §3） |
| 3 确认失败 | ✅ | 收集期 ImportError，见 §2 RED |
| 4 settings + 依赖声明 | ✅ | `config.py:157-160`（紧跟 `jwt_expire_hours: int = 8`，注释逐字）；`requirements.txt:13` 在 `PyJWT>=2.9,<3` 下一行 |
| 5 最小实现 | ✅ | 新建 `backend/app/credentials.py`，与 brief 代码块**逐行 identical** |
| 6 确认通过 | ⚠️ 部分 | `2 failed, 8 passed`。8 条行为用例（Argon2 档位 / 编码串往返 / 错口令 / algorithm 列分派两条 / legacy 往返 / dummy 两条）全绿；`CentralisationScanTests` 两条按 §5 的原因红 |
| 7 定向门 + 快照 | ⚠️ 有偏差 | 定向门 `2 failed, 23 passed`；快照已做（见下）；**台账 `echo >> progress.md` 未执行**（控制台写）；**未跑 brief 里那句 `mkdir -p ../.superpowers/sdd/SECURITY_A`**——该目录名与快照纪律的 `SECURITY_A_PLAN/` 不一致，看着是计划里的笔误，造一个空目录没有意义，仅记录不执行 |

快照产物（`.superpowers/` 已被 `.gitignore:25` 忽略）：

- `.superpowers/sdd/SECURITY_A_PLAN/snap-task1-app/`（`app/` 全树，753K；`cp -r app` 后剥掉了 `__pycache__`，快照要的是源码不是编译产物）
- `.superpowers/sdd/SECURITY_A_PLAN/snap-task1-test.py`

命名沿用 brief 原文（`snap-task1-app` / `snap-task1-test.py`），与全局约束里的 `snap-task<N>/` 目录式写法不同；前几轮计划实际两种都有（`MODEL_ROUTER_V23_PLAN/snap-task1/` 与 `snap-task8-r1/{app,tests}`）。要统一成 `snap-task1/` 的话控制台改名即可，不需要同步改代码。

## 2. TDD 证据

### RED（Step 3，实现文件尚未存在）

```
$ cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q
=================================== ERRORS ====================================
_____________ ERROR collecting tests/test_credentials_contract.py _____________
ImportError while importing test module 'E:\xiangmu\rag\backend\tests\test_credentials_contract.py'.
Traceback:
tests\test_credentials_contract.py:13: in <module>
    from app import credentials  # noqa: E402
E   ImportError: cannot import name 'credentials' from 'app' (E:\xiangmu\rag\backend\app\__init__.py)
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 1.86s
```

为什么是预期的红：模块还不存在 ⇒ 收集期就断，10 条用例一条都没跑起来。与 brief 预期的偏差只在文字：brief 写 `ModuleNotFoundError: No module named 'app.credentials'`，实测是 `ImportError: cannot import name 'credentials' from 'app'`——因为 `app` 是包（`app/__init__.py` 在场），`from app import X` 的属性查找先于子模块导入失败，语义同源。

### GREEN（Step 6，实现落地后）

```
$ cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q
...
_____________ CentralisationScanTests.test_only_credentials_module_hashes_passwords _____________
    def _hashlib_password_sites(self) -> list[str]:
        offenders: list[str] = []
        for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = {
>               node.name.split(".")[0]
                ^^^^^^^^^
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
            }
E           AttributeError: 'Import' object has no attribute 'name'. Did you mean: 'names'?
tests\test_credentials_contract.py:98: AttributeError
2 failed, 8 passed in 3.55s
```

8 条转绿 = brief Step 6 的"行为半边"全部达成；2 条红的根因见 §5 F1/F2（**是 brief 代码自己的缺陷**，与 `credentials.py` 的正确性无关）。

### 全套件 + cwd 门（全局约束）

```
$ cd /e/xiangmu/rag/backend && python -m pytest -q
2 failed, 969 passed, 36 warnings, 995 subtests passed in 232.72s (0:03:52)

$ cd /e/xiangmu/rag        && python -m pytest backend/tests -q --collect-only → 971 tests collected
$ cd /e/xiangmu/rag/backend && python -m pytest -q            --collect-only → 971 tests collected   # 两种 cwd 计数相等 ✅
$ cd /e/xiangmu/rag/backend && python -m pytest -q --collect-only --ignore=tests/test_credentials_contract.py → 961 tests collected
```

2 failed 即上述两条新用例，**没有任何既有基线失败**（基线 = 971 − 10 = 961 条，全绿）。36 条 warning 全是既有噪声（PyJWT `InsecureKeyLengthWarning` 31 字节 HMAC key、conftest 的 ledger-guard 读改道），本任务未引入新 warning。`tests/test_llm_egress_guard.py` 的 D6 豁免计数、`/api/query` 键集合钉、RBAC 契约均未动、均绿（定向门里 `tests/test_rbac_contract.py` 15 passed）。

## 3. 逐字性核对

用脚本把 brief 的 Step 2 / Step 5 两个代码块与落盘文件做 `splitlines()` 全等比较（含中文注释、全角冒号、ASCII 直引号 `"`、`$argon2id$` 前缀、`19456` 等）：

```
TEST  IDENTICAL
IMPL  IDENTICAL
```

对外契约面逐条核过：`ALGORITHM_ARGON2ID/ALGORITHM_LEGACY_SHA256`、`ARGON2_TIME_COST/MEMORY_COST/PARALLELISM/HASH_PREFIX`、`CredentialConfigError`、`PasswordCapacityError`、`VerifyOutcome(ok, needs_rehash)`（frozen dataclass）、`hasher()`、`hash_password()`、`needs_rehash()`、`verify_password(plain, *, algorithm, encoded)`、`verify_dummy()`、`argon2_slot()`（contextmanager）——名字与签名与 Task 2/3/5/7/8 依赖列表一致，未改名、未"优化"。`dummy_hash()` 也在场（brief 的 Interfaces 清单漏列，但 Step 5 实现与测试都用到）。

## 4. 全局约束自查

| 约束 | 结论 | 证据 |
| --- | --- | --- |
| m/t/p 不得经 settings/env 读取 | ✅ | `config.py` 里 argon2 只有 `argon2_max_concurrent_ops` 一枚（`grep -in argon2 app/config.py` → 3 行，全是注释+这一枚）。实测 env 施压 `ARGON2_MEMORY_COST=8 ARGON2_TIME_COST=1 ARGON2_PARALLELISM=9` ⇒ 档位仍是 `2/19456/1`，只有槽数跟着 `ARGON2_MAX_CONCURRENT_OPS=7` 变成 7。M16 式漂移在源头不成立 |
| 明文口令不得进日志/审计/响应/异常 | ✅ | 四条抛错路径（前缀不符 / 形态不符 / 未知 algorithm / 坏编码串）逐条抓 `traceback.format_exception` 比对，明文均未出现在异常文本里；消息只含 `algorithm!r` 与固定中文。`PasswordCapacityError` 文案是英文定值，不含入参。（注：`exc.__traceback__.tb_frame.f_locals` 天然含 `plain`——这是 CPython 帧对象的性质，任何口令实现都一样，只要没人把 `**frame.f_locals` 打日志就不构成泄漏；Task 8 的节流/日志面接手时值得记一句） |
| 注释风格跟仓内（中文、写为什么） | ✅ | 逐字照抄 brief，未加"本任务/供 X 调用"式叙述 |
| 不碰 `app/llm/`、`rag.py`、`conversation_agent.py`、V2.3 件 | ✅ | `git status --short` 只有 4 项（见 §6），D6 计数未动 |
| 不 `git commit` | ✅ | 本轮零 git 写命令 |
| 两套 cwd collected 相等 | ✅ | 971 == 971 |

## 5. 自审发现

**F1（阻塞级，brief 缺陷）：SECA-05 的 AST 扫描器一跑就崩。** 【轮 2 已按裁定修复，见 §8.2 第 1 项】
`ast.Import` 节点没有 `.name`，只有 `.names`（`list[ast.alias]`）。brief Step 2 代码块（落在 `tests/test_credentials_contract.py:97-102`）的 `node.name.split(".")[0]` 恒抛 `AttributeError` ⇒ `CentralisationScanTests` 两条**永远是 error，不是 pass 也不是断言失败**。最小修法（控制台裁定后可直接落）：

```python
imported = {
    alias.name.split(".")[0]
    for node in ast.walk(tree)
    if isinstance(node, ast.Import)
    for alias in node.names
}
```

**F2（阻塞级，brief 缺陷）：就算修好 F1，这两条在 Task 1 也红，而且在整个计划收口后**仍**红。** 【轮 2 按选项 B 修复，见 §8.2 第 2-4 项】
把扫描器修好后实测命中集（本任务现场跑的等价扫描，未落盘）：

```
app\auth.py:174 hashlib.sha256(password.encode('utf-8'))
hits(dirs) = ['app\\auth.py']
```

三件事同时成立：

1. `app/auth.py:173-174` 的 `_password_digest` 要到 **Task 5 Step 6**（计划 1925-1927 行明写"删 `app/auth.py:173-174`"）才消失 ⇒ Task 1 内 `test_only_credentials_module_hashes_passwords` 必红，除非提前删（越界，且会打断依赖 `auth.USERS` + SHA-256 摘要的一批既有登录用例）。
2. **`credentials.py` 自己根本不会被这条扫描命中**：它的口令运算是 `_legacy_digest(plain)` ⇒ `hashlib.sha256(plain.encode('utf-8'))`，`ast.unparse` 出来的文本里没有 `password|passwd|secret` 任一子串（参数名叫 `plain`）。也就是说 `PASSWORD_WORDS` 是**词法**启发式，实现侧改个参数名就漏。
3. 于是 `test_the_exemption_table_is_equal_to_the_hit_set` 期望 `{"app/credentials.py"}`，真实命中集在 Task 1 是 `{"app/auth.py"}`、在 Task 5 之后是**空集**——这条用例在任何时点都无法为真。

brief Step 3 那句"命中集为空集 ≠ 豁免表"顺带也没算到 `auth.py` 这一处。计数也对不上：brief Step 6 期望 `11 passed`，实际这个文件只有 **10** 条用例（3+3+2+2）。

建议裁定（择一，我倾向 B）：**⇒ 轮 2 控制台裁定按 B 落地，实测细节见 §8.2/§8.4；下面三条原文保留，作为"当时为什么不能在本轮静默修"的记录。**
- **A**：把 `CentralisationScanTests` 整体挪到 Task 5（`_password_digest` 删除的那一轮）落，Task 1 只跑 8 条行为用例，Step 6 的期望改成 `8 passed`。
- **B**：留在 Task 1，但改成"过渡钉"——先修 F1，把断言写成 `hits == {"app/auth.py", "app/credentials.py"}` 并在 Task 5 Step 6 收紧为 `{"app/credentials.py"}`；同时把 `_legacy_digest` 的参数改名为含 `password` 的字样（例如 `password`），让扫描器**真的**能看见 credentials.py 这一处（否则第 2 条命中永远是靠豁免表白名单，SECA-05 就是空门）。计划里已有过渡钉先例（`TransitionalConsistencyPin`，Task 5 Step 6 显式删除），风格一致。
- **C**：把这两条从 `test_credentials_contract.py` 移进 Task 10 的 `test_security_a_closure.py`（SECA-04 三处扫描旁边）。
无论选哪条，M13（`app/main.py` 注入一处口令 `hashlib`）现在**杀不掉**——扫描器一崩，任何变异都得到同一个 AttributeError，看起来"红得对"，其实门是死的。这正是 `progress.md` 里反复警惕的"flaky 门被后人 skip"形态。

**F3（中，实现语义值得记一笔）：`_verify_argon2` 的 `except argon2.exceptions.InvalidHashError` 在 argon2-cffi 25.1 上打不到坏编码串。**
实测库的异常映射（`argon2/low_level.py::verify_secret`）只有两种出口：`VerifyMismatchError`（口令不符）与父类 `VerificationError`（"其他原因"，含 PHC 串解不开）。`InvalidHashError` 是 `ValueError` 的子类，由 `check_needs_rehash` 在喂进垃圾串时抛（实测 `needs_rehash('garbage') → InvalidHashError`，消息为空）。后果：

```
verify_password("p", algorithm="argon2id", encoded="$argon2id$v=19$m=1,t=1,p=1$aaa$bbb")
  → RAISED argon2.exceptions.VerificationError: Decoding failed      # 不是 CredentialConfigError
```

即：前缀对但体内损坏/非法 base64 的库内行会以**裸 argon2 异常**逃出原语。按 brief 注释①"其余异常外抛"这是刻意形状（坏数据不做降级），但 brief 又明确想要 `"Argon2 编码串无法解析"` 这条 `CredentialConfigError`，两者只落实了前者。影响在 Task 5：登录腿若不额外兜，一条脏 `password_hash` 会变成 500 而不是硬失败语义。修法（同样需裁定，因为要动 brief 代码）：把那条 except 换成 `except argon2.exceptions.VerificationError as exc:`（必须排在 `VerifyMismatchError` 之后，后者是其子类），或 `except (argon2.exceptions.InvalidHashError, argon2.exceptions.VerificationError)`。

**F4（已核实的良好形状）**
- 并发闸门无后门：占满 `settings.argon2_max_concurrent_ops=2` 个槽后，`argon2_slot()` 与 `verify_dummy()` 双双抛 `PasswordCapacityError`（后者复用 `_verify_argon2` ⇒ 走同一道闸，brief 注意事项②成立）。
- 漂移判定可信：`time_cost=3` 造的串 ⇒ `needs_rehash → True`；当前档位现造的串 ⇒ `False`。跨档口令正确性也测过（4/65536/2 的串在当前 hasher 下 ⇒ `ok=True, needs_rehash=True`），即"能登进来但立刻收敛"这条 §8 语义成立。
- 分派权威是列：`argon2id` 列 + 非 PHC 载荷 ⇒ `CredentialConfigError`；`legacy-sha256` 列 + 非 hex ⇒ `CredentialConfigError`；未知 algorithm ⇒ 同样硬失败，不 try-both。`$argon2i$`（非 id 变体）因前缀不符被拒，不会静默按 argon2id 验。
- legacy 永远 `needs_rehash=True`，测试钉住。

**F5（低，交给下游任务注意）**
- 原语**不做长度/复杂度策略**：`hash_password("")` 正常产出合法 PHC 串。规格里的口令长度门应在 Task 7 改密端点/schema 层，别默认 credentials.py 挡住了。
- `_LEGACY_HEX` 只接小写 64 hex ⇒ 库里若存过大写 hex 摘要会硬失败（实测）。Task 3 迁移器写盘前应断言 `hexdigest()` 原样（本就是小写），或在写入前 `.lower()` 并记一行裁定。
- `_SLOTS` 在 import 期按 settings 取值定型（`max(1, …)` 兜住 0/负数），运行时改 env 不会重塑闸门——这是可用性旋钮的合理形状，但意味着 Task 8 想按 worker 数标定只能靠 env 起点，不能热调。
- `requirements.txt` 的约束 `>=23.1.0,<26` 在宿主解析到 25.1.0；容器 `docker build` 会解析同一支，F3 的异常映射结论在容器里应一致，但按 brief 口径留给 Task 10 探针。

## 6. 改动清单（工作树，未提交）

```
$ cd /e/xiangmu/rag && git status --short
 M backend/app/config.py            # +4 行：argon2_max_concurrent_ops 及其"档位不在这里"注释
 M backend/requirements.txt         # +1 行：argon2-cffi>=23.1.0,<26（PyJWT 之后）
?? backend/app/credentials.py      # 新建，逐字照 brief Step 5
?? backend/tests/test_credentials_contract.py   # 新建，逐字照 brief Step 2
?? docs/SECURITY_A_PLAN.md         # 本任务前即未跟踪，非本轮改动
?? docs/SECURITY_A_SPECIFICATION.md  # 同上
```

另有 git-ignored 产物：`.superpowers/sdd/SECURITY_A_PLAN/snap-task1-app/`、`snap-task1-test.py`、本报告。

## 7. 轮 1 请求裁定的四项 · 现状

1. **F1+F2 的 SECA-05 修法** → 裁定：选项 B（过渡豁免 + 收紧留 Task 5）。**轮 2 已落，见 §8。**
2. **F3 是否本轮收** → 裁定：不改，列 Task 5 追加步骤。§9 里我把 brief 逐字原文引回来供那轮对照。
3. **Step 6 期望值 `11 passed`** → 裁定：订正为 `10 passed`。**轮 2 实测正是 `10 passed`**（§8.5），期望值可直接写死。
4. **台账行** → 归控制台，未写。

## 8. 轮 2：按裁定修复 F1 + F2（2026-09-25 16:0x +0800）

### 8.1 范围与红线

只动 `backend/tests/test_credentials_contract.py::CentralisationScanTests` 与 `backend/app/credentials.py` 的 `_legacy_digest` 及其调用点。F3（`InvalidHashError` 映射）与 F5 两条**未动**，按裁定归 Task 5 追加步骤。`arg02_slot` 语义、档位常量、`verify_password` 签名、`VerifyOutcome` 形状、其余四个 TestCase 一字未改。

### 8.2 改动明细

`tests/test_credentials_contract.py`（9 处 hunk，全在 `CentralisationScanTests` 内）：

1. **F1 修复**：`ast.Import` 取名字改成遍历 `node.names` 的 `ast.alias`（brief 的 `node.name` 在该节点上不存在）。
2. **词表加强（裁定 2）**：`PASSWORD_WORDS` 从 `password|passwd|secret` 扩成三段——
   ```python
   PASSWORD_WORDS = re.compile(
       r"(?i)password|passwd|secret"
       r"|(?<![a-z])(?:plain|digest|hash)(?![a-z])"
       r"|plain[-_]?(?:text|hash|pw)"
   )
   ```
   边界 `(?<![a-z])…(?![a-z])` 是防 `hexdigest` 这类合成词误伤（裁定 3 的担忧）。实测：仓内 `import hashlib` 的模块只有三处（`auth.py` / `credentials.py` / `typesafe_judgments.py`），加上边界后 `typesafe_judgments.py:102/114` 两处**非口令**摘要（`content_digest` 与 `payload` 缓存键）仍不命中，命中集恰为
   ```
   app\auth.py:174        hashlib.sha256(password.encode('utf-8'))
   app\credentials.py:127 hashlib.sha256(password.encode('utf-8'))
   ```
   词表按裁定的 (a)(b) 两组落，两处偏差如实报：**不含裸 `str`/`value`/`raw`**（中性词）。我核过它们的代价——把这三个词并进去，今天的命中集**一字不变**（`CURRENT == WIDE`，实测），因为现有非口令 hashlib 站点都不直接把 `str(...)` 喂进调用；但 `str(row.get("id") or "")` 这类写法在 `typesafe_judgments.py` 里到处都是，日后一处 `hashlib.sha256(str(x).encode())` 的缓存键就会误判成口令面，那是要人改代码去迁就门。所以裁定 (a) 里的"裸 `plain|digest|hash`"我按边界收进来了，"中性词"没有：前三个是**命名意图词**（写口令原料才会用的词），后三个是**类型词**（到处都是），分界在这里。
   残余上限也就到这里：这条门是词法判定，不是污点分析。实测把口令喂进 `hashlib.sha256(blob.encode("utf-8"))` 的变异体**不命中**（`blob` 不带任何词面信号）——它能杀"改回 `plain`"这类漂移与一切带口令字样的新站点，杀不动刻意中生命名的注入。要在稳态上再收紧，该加的是 Task 10 侧的"业务模块不得 `import hashlib`"独立扫描（现在会把 `typesafe_judgments.py` 一起卷进来，需要另列豁免），不是把词表继续摊大。
3. **命中/豁免语义分离 + 过渡豁免（裁定 3）**：`_hashlib_password_sites()` 现在只返回**命中集**（真命中，不含任何过滤），表比对与表外检查分别由 `_exemption_table()` / `_relative_dir()` 承担；豁免表 = `{app/credentials.py}` ∪ `TRANSITIONAL_EXEMPT`，后者 `frozenset({"app/auth.py"})` 旁边写死注释：Task 5 Step 6 删 `_password_digest` 时**同轮清空**（见 §8.7 的收紧指令）。
4. **两钉保持双向**：`test_only_credentials_module_hashes_passwords` = 豁免表外不许有命中；`test_the_exemption_table_is_equal_to_the_hit_set` = 命中集恰等于豁免表（⇒ 空转的豁免判红，见 §8.4 控制 3）。

`app/credentials.py`（2 处改动 + 2 行注释）：

```python
# 调用点（verify_password 的 legacy 分支）
-            ok=hmac.compare_digest(_legacy_digest(plain), encoded.lower()),
+            ok=hmac.compare_digest(_legacy_digest(password=plain), encoded.lower()),
# 定义点
-def _legacy_digest(plain: str) -> str:
-    return hashlib.sha256(plain.encode("utf-8")).hexdigest()
+def _legacy_digest(password: str) -> str:
+    return hashlib.sha256(password.encode("utf-8")).hexdigest()
```

两处各配一行"为什么"注释：形参名是 SECA-05 按词面认出本模块命中的唯一凭据，关键字调用形状是被扫描器看见的那一半，两者一起钉住，防止以后有人"顺手清理"回位置参数 + `plain`。行为完全不变（见 §8.4 控制 4 之外的全套件复跑）。

### 8.3 逐字性偏离（量化，评审要看的就是这个）

与 brief 代码块做 `unified_diff(n=0)` 统计：

```
backend/tests/test_credentials_contract.py: -10 +33 行，9 个 hunk（全部落在 CentralisationScanTests 类体内）
backend/app/credentials.py:                  -3  +7 行，3 个 hunk（legacy 分支 2 + _legacy_digest 定义 1）
```

其余部分（`Argon2ProfileTests` / `AlgorithmColumnTests` / `DummyVerifyTests` 全部 8 条用例、`credentials.py` 的档位常量与全部函数签名）与 brief **逐行相同**，包括中文注释与全角标点。Step 6 期望值 `11 passed` 已按裁定订正为 `10 passed`。

### 8.4 可证伪性实测（控制台点名的四条）

控制 (a)(b) 用字节安全临时探针真跑 pytest（写入 `app/_seca05_nc_tmp.py` → 跑 → 删除 → 再跑），事后 `ls app | grep -c _tmp` = 0、`git status --short` 无残留；控制 (c)(d) 是进程内模拟（只把 `_hashlib_password_sites` 替成"Task 5 之后"的命中集形状，不改豁免表逻辑本身）：

| 控制 | 做法 | 实测 |
| --- | --- | --- |
| (a) 负控制 | 业务模块塞一处 `def _probe(password)` + `hashlib.sha256(password.encode(...)).hexdigest()`（= F1/F2 修好后 M13 该做的事） | `2 failed`：两条断言各自红（`test_only_credentials_module_hashes_passwords` + `test_the_exemption_table_is_equal_to_the_hit_set`）✅ 门真的杀 |
| (b) 现场 | 探针移除后重跑同一节点 | `2 passed` ✅（整文件 `10 passed in 2.17s`） |
| (c) 空转豁免 | 命中集模拟成只剩 `app/credentials.py`，豁免表仍列 `app/auth.py` | `1 passed, red=['test_the_exemption_table_is_equal_to_the_hit_set']` ✅ Task 5 忘清空 ⇒ 同轮自己红，不靠人记 |
| (d) 同轮收紧 | 同一命中集，`TRANSITIONAL_EXEMPT` 清空 | `2 passed` ✅ 收紧动作本身是绿的，最终期望面 = 计划原文的 `{app/credentials.py}` |

另一发顺带实测（写进 §8.8 的 F6）：把 M13 的**原样片段**（只有 `import hashlib`，无调用）注入 `app/` ⇒ `2 passed`，门不杀。词表上限的实测（§8.2）：中性命名 `hashlib.sha256(blob.encode(...))` 注入 ⇒ 也不命中。两者都不改本轮判据，只作证据留下。

### 8.5 门与套件

```
$ cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q
10 passed in 2.17s                       # 轮 1 是 2 failed, 8 passed；Step 6 期望按裁定订正为 10
$ python -m pytest tests/test_credentials_contract.py tests/test_rbac_contract.py -q
25 passed in 3.25s                       # 轮 1 是 2 failed, 23 passed
$ python -m pytest -q                    # 全套件，轮 2 终态
971 passed, 36 warnings, 995 subtests passed in 239.64s (0:03:59)
$ cd /e/xiangmu/rag && python -m pytest backend/tests -q --collect-only → 971 tests collected
$ cd /e/xiangmu/rag/backend && python -m pytest -q --collect-only        → 971 tests collected   # 两种 cwd 相等 ✅
```

计数守恒核过：轮 1 = `2 failed, 969 passed` = 971，轮 2 = `971 passed`，测试条数不变（修的是判据，不是加减用例），warning 仍 36（既有 PyJWT key 长度 + ledger-guard 读改道，无新增）。

### 8.6 快照（append-only）

- **保留原样**：`snap-task1-app/`、`snap-task1-test.py`（轮 1 现场，正是 §5 F1/F2 的证据：那条红的 `2 failed, 969 passed` 对应这棵树）。
- **新增**：`snap-task1-r1-app/`（剥 `__pycache__`）、`snap-task1-r1-test.py`。
- 命名说明（唯一一处我没照字面执行的指令）：控制台原话是"刷新 `snap-task2-app` / `snap-task2-test.py`"。`snap-task2-*` 是 **Task 2（user_store）**的快照位，本轮占用了会打断计划的快照链，且 `progress.md` 里 Task 2 已经预登记了 SECA-08 扫描的豁免讨论。按仓内既有轮次命名（`MODEL_ROUTER_V23_PLAN/snap-task8-r1`）记为 `snap-task1-r1-*`。若裁定就是要 `snap-task2-*` 这个名字，改个目录名即可，我不再自决第二次。

### 8.7 给 Task 5 的收紧指令（照抄即可，别靠回忆）

Task 5 Step 6 删 `app/auth.py:69-103` 与 `:173-174`（`_password_digest`）的**同一轮**，在 `backend/tests/test_credentials_contract.py::CentralisationScanTests` 里做两件事：

```python
    TRANSITIONAL_EXEMPT = frozenset()      # 原为 frozenset({"app/auth.py"})
```

并把该类注释里"过渡豁免"那段收成一句历史说明；随后：

- 期望：`python -m pytest tests/test_credentials_contract.py -q` → `10 passed`，其中 `test_the_exemption_table_is_equal_to_the_hit_set` 的期望集自动收紧为 `{app/credentials.py}`（它比的是 `_exemption_table()`，豁免表清空后两边同时变小，**不需要**再改断言字面量）。
- 若忘了清空豁免表：`test_the_exemption_table_is_equal_to_the_hit_set` 会红（§8.4 控制 3 实测），失败信息里就是那两处集合之差，指向唯一修法。
- 顺带（F3 归属轮）：`_verify_argon2` 那条 `except argon2.exceptions.InvalidHashError` 换成 `except argon2.exceptions.VerificationError`（必须排在 `VerifyMismatchError` 之后，后者是其子类），坏编码串才会落到 `CredentialConfigError("Argon2 编码串无法解析")` 而不是裸逃出原语把登录打成 500。
- 顺带（F5 归属轮）：迁移写盘前断言摘要为小写 64 hex（`_LEGACY_HEX` 只认小写，实测大写硬失败）。

### 8.8 新发现 F6（计划侧，需 Task 10 前处理）：M13 的变异片段现在是空门

F1/F2 修好后，计划 3357 行 M13 的变异体只塞 `import hashlib` 一行、**没有 `hashlib.<algo>(...)` 调用**：

```
$ 把 "import hashlib\nfrom app import credentials" 注入 app/（等价 M13 原文片段）
M13-as-specified (import hashlib only) -> 2 passed      # 门没杀 ⇒ SURVIVED
```

轮 1 它"被杀掉"纯属侥幸（扫描器恒抛 AttributeError，怎么都红）。SECA-05 的判据是"口令**参与运算**的 hashlib 命中面"，纯 import 不构成运算，所以修法在变异侧不在门侧：M13 的替换片段应升级为真造一处口令运算，例如

```python
("M13", "app/main.py", "from app import credentials",
 "import hashlib\nfrom app import credentials\n\n\ndef _m13(password: str) -> str:\n"
 "    return hashlib.sha256(password.encode('utf-8')).hexdigest()\n",
 "test_credentials_contract.py::CentralisationScanTests"),
```

这正是计划 Step 4 那句话的反面教材——"任何 SURVIVED ⇒ 对应 SECA 行是死测试，补测试而不是撤变异"：这里该补的是**变异注入的强度**，而不是把门改成"见 import hashlib 就判红"（仓内 `import hashlib` 的三个模块里，`app/typesafe_judgments.py:102/114` 是正当的非口令摘要点，那样改等于把它们一起判红）。另注：M13 的 TARGET 片段 `from app import credentials` 要等 Task 5/6 把凭据层接进 `main.py` 才在场，Task 10 跑台时若报 `TARGET-NOT-FOUND` 属预期漂移，按计划口径改片段即可。

同类形态顺带记一句（不改判据）：M16 的片段把 `ARGON2_MEMORY_COST` 换成 `int(os.environ.get(...))`，而 `credentials.py` 没有 `import os` ⇒ 它会以 `NameError` 收集期崩溃的方式"被杀"，而不是被 SECA-19 的判据杀掉。Task 10 落地变异台时值得顺手在片段里补 `import os`，让 M16 杀在判据上而不是杀在语法上。

### 8.9 轮 2 改动清单

```
 M backend/app/config.py                          # 轮 1（不变）
 M backend/requirements.txt                       # 轮 1（不变）
?? backend/app/credentials.py                     # 轮 2：_legacy_digest 形参改名 + 关键字调用 + 2 行注释
?? backend/tests/test_credentials_contract.py     # 轮 2：CentralisationScanTests 三条修复
```

零 git 写命令；`.superpowers/sdd/SECURITY_A_PLAN/snap-task1-r1-*` 与本报告在 `.gitignore:25` 下。

## 9. 附：F3 的实测证据（供 Task 5 那轮直接引用，本轮未改一行）

宿主 argon2-cffi 25.1.0（`pip` 解析自 `>=23.1.0,<26`）上量出来的异常映射：

```
$ python - <<'PY'   # 逐条现测
inspect.getsource(argon2.low_level.verify_secret)
  → rv == ARGON2_OK                    → return True
    rv == ARGON2_VERIFY_MISMATCH       → raise VerifyMismatchError       # 唯一"口令不对"
    else                              → raise VerificationError          # 含 "Decoding failed"
类层次：VerifyMismatchError ← VerificationError ← Argon2Error ← Exception
        InvalidHashError ← ValueError            # 与 VerificationError 无父子关系

needs_rehash('garbage')      → RAISED InvalidHashError('')            # 只有 check_needs_rehash 抛它
needs_rehash(截断的 PHC 串)  → True
verify_password(截断的 PHC 串) → RAISED VerificationError: Decoding failed   # 不是 CredentialConfigError
verify_password(非法 base64 的 PHC 串) → RAISED VerificationError: Decoding failed
verify_password($argon2i$ 前缀)          → RAISED CredentialConfigError（前缀交叉校验先拦住）
PY
```

所以 brief Step 5 那句注释的意图（`"Argon2 编码串无法解析"` ⇒ `CredentialConfigError`）在 `InvalidHashError` 这一支上落不到 `verify` 路径：verify 解不开串时抛的是父类 `VerificationError`。轮 1 我按指令原样保留，全套件 971 也证实没有用例踩到它（**这条是潜伏面，不是现存红**）。Task 5 那轮的最小修法已写在 §8.7 第三条。

brief 的原文（计划 392 行，逐字引回，免得 Task 5 那轮再翻文件）：

> **注意两处刻意的形状**：① `_verify_argon2` 只在 `VerifyMismatchError` 上返回 `ok=False`，其余异常外抛——把"编码串坏了"咽成"口令错了"会让 `CredentialConfigError` 那两条测试假绿；② `verify_dummy` 复用同一条 `_verify_argon2`，包括并发槽，否则哑校验路径成了绕过闸门的后门（M 台会在 Task 8 检查这一点）。

裁定的边界我照守：F3 与 F5 那两条本轮**没有**改（`credentials.py` 里唯一的改动就是 §8.2 的形参名/关键字调用/注释），`argon2_slot` 语义、档位常量、`verify_password` 签名、`VerifyOutcome` 形状一律未动。

顺带把轮 1 §5 F5 的三条重述一遍，它们在 Task 5/7 各自归属轮才成形，别在这轮顺手做：

1. 原语不做口令长度/复杂度策略（`hash_password("")` 合法出串，实测）⇒ 口令强度门归 Task 7 改密端点 + schema。
2. `_LEGACY_HEX` 只认小写 64 hex（大写实测 `CredentialConfigError`）⇒ Task 3 迁移器写盘前应断言/`.lower()`，Task 5 的 legacy 登录腿沿用同一口径。
3. `_SLOTS` 在 import 期按 `settings.argon2_max_concurrent_ops` 定型（`max(1, …)` 兜 0/负），运行期改 env 不会重塑闸门 ⇒ Task 8 的容量标定只有"启动 env"一个旋钮，这是可用性侧的合理形状，但值得在 Task 8 文档里写明白。

## 10. 台账行（照旧归控制台，我不写）

- Ruling（轮 1，brief Step 7 那句）：Argon2 档位常量放 `credentials.py`；settings 只加 `argon2_max_concurrent_ops`（可用性旋钮）。实测 env 施压 `ARGON2_MEMORY_COST/TIME_COST/PARALLELISM` 攻不动档位，只有 `ARGON2_MAX_CONCURRENT_OPS` 跟着动槽数。
- Ruling（轮 2 新增，建议登记）：SECA-05 采过渡豁免 `TRANSITIONAL_EXEMPT={app/auth.py}`，收紧点钉在 Task 5 Step 6（清空该表，期望面回到计划原文的 `{app/credentials.py}`）；豁免表的目录比较前置于 `ast.Import → node.names` 的修复，且形参名与关键字调用形状是 credentials.py 命中可见的前提（改名即隐身，已加注释）。
- 待登记（计划侧，Task 10 前）：M13 的变异片段只塞 `import hashlib`，在修好的 SECA-05 门下实测 `2 passed`（空门）⇒ 片段需加强为真造一处 `hashlib.sha256(password…)`；M16 的片段缺 `import os`，会以收集期 `NameError` 侥幸"被杀"，建议补 import 让它杀在判据上。

---

## 11. 轮 3：复审 findings 1–6 修复轮（2026-09-25 16:3x +0800）

输入是复审的 6 条（5 Important + 1 全局约束）。改动仍只落在 `backend/app/credentials.py` 与 `backend/tests/test_credentials_contract.py`：`config.py`、`requirements.txt` 一字未动。零 git 写命令。约束逐条守住：档位常量 `2/19456/1`、PHC 存储串形态、`verify_password(plain, *, algorithm, encoded)` 的 keyword-only 签名、`check_needs_rehash` 用法、"没有任何 `os`/settings 读 m/t/p"、`argon2_max_concurrent_ops` 全部未变；四条抛错路径的文案里依旧没有明文（本轮新增的 `CredentialConfigError("Argon2 编码串无法解析")` 消息只含固定中文，实测 `str(exc)` 不含入参）。

### 11.1 Finding 1 —— `verify_dummy` 可以返回 `ok=True`

现场复现（改前）：`credentials.verify_dummy("yaoke-constant-work-dummy-credential")` → `VerifyOutcome(ok=True, needs_rehash=False)`。哑校验的哈希与明文都在本模块里，所以"知道那串明文"就等于拿到一条真认证结论，而它的调用方（未知账号 / 已停用 / 无凭据行）正是拿返回值当结论用的。

- `credentials.py:107-113`：按评审给的形状改成"取运算量、压判定"——`outcome = _verify_argon2(plain, _DUMMY_HASH)` 之后 `return VerifyOutcome(ok=False, needs_rehash=outcome.needs_rehash)`。恒定一次同档运算、恒定占一格并发槽的性质不变（M-A/M-F 两条变异证明它确实还在跑运算，见 §11.7）。
- `credentials.py:55-56`：把 dummy 的明文原像提成 `_DUMMY_PLAINTEXT`，`_DUMMY_HASH = _HASHER.hash(_DUMMY_PLAINTEXT)`。**这是本轮唯一一处计划外新增（私有常量，不在 Produces 清单里）**，理由是可证伪性：新测试若在断言里另抄一份字面量，将来谁轮换 dummy 原像，测试就会静默变成"喂了个不匹配的串 ⇒ ok=False 当然成立"的空转绿；引用 `_DUMMY_PLAINTEXT` 才能让这条断言永远指着"匹配的那条腿"。
- 覆盖测试：`DummyVerifyTests.test_the_dummy_payloads_own_plaintext_still_does_not_verify`（`assertIs(False, outcome.ok)`，另钉 `needs_rehash` 是透传而非写死，防"整条腿硬编码"这种假修复）。

### 11.2 Finding 2 —— `InvalidHashError` 那一支是死代码，坏 PHC 串以裸库异常逃出原语

改前实测：`verify_password("p", algorithm="argon2id", encoded="$argon2id$v=19$m=1,t=1,p=1$aaa$bbb")` → `argon2.exceptions.VerificationError: Decoding failed`。两支异常在 25.1.0 里无父子关系（`InvalidHashError ⊂ ValueError`；`VerificationError ⊂ Argon2Error`），所以那一支永远打不到。另外从 `PasswordHasher.verify` 的源码看，`InvalidHashError` 只在 `hash[:9]` 认不出类型头时抛，而 `ARGON2_HASH_PREFIX` 交叉校验已经把这一类挡在前面 ⇒ 本模块里它确实是死分支，不是"备用兜底"。

- `credentials.py:122-126`：`except argon2.exceptions.VerificationError as exc:` 排在 `VerifyMismatchError` 之后（后者是其子类，顺序反了会把"口令错了"也升格成配置错误），包装成 `CredentialConfigError("Argon2 编码串无法解析")`。注释按已订正的计划文本落，但**去掉了计划里那句"（Task 1 评审实测）"**——全局约束禁止注释引用任务/计划/进度，改成陈述异常树本身（这是本轮对计划代码块的一处有意偏离）。
- 覆盖测试：`AlgorithmColumnTests.test_argon2_column_with_a_right_prefix_and_an_unparseable_body_is_a_hard_failure`，用的就是评审点名的那条串（"列说 argon2id、载荷是垃圾"）。这条同时把两个失败方向都关掉：裸逃 ⇒ 上游 500；咽进 `ok=False` ⇒ 一条脏数据变成永久登不上且无人报错。
- **§8.7 的第三条交接（"F3 归 Task 5 那轮"）自本轮起作废**，Task 5 不必再做；下面 §11.9 重述了仍然有效的交接项。

### 11.3 Finding 3 —— `argon2_slot` / `PasswordCapacityError` 零回归覆盖

新增 `CapacityGateTests` 四条，形状与计划里那条容量测试同源（`mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0))`）：

1. `test_a_full_slot_pool_turns_an_argon2_verify_into_a_capacity_error` —— argon2id 分支耗尽 ⇒ `PasswordCapacityError`。
2. `test_a_full_slot_pool_turns_the_dummy_path_into_a_capacity_error` —— dummy 腿同样必须撞闸；否则"账号不存在"那条腿就是绕过容量门的后门（这正是注意事项②的判据，M-F 实测它真的杀）。
3. `test_the_slot_is_given_back_even_when_the_body_raises` —— 异常路径归还槽且只归还一次（`finally` 漏还 ⇒ 红）。
4. `test_capacity_exhaustion_is_a_distinct_family_from_a_config_error` —— 两类异常互不为子类；上游要把容量翻成 503、配置错误是硬失败，谁成了谁的子类都会让一条 `except` 顺带吃掉另一类。

未知 algorithm 与 `hasher()` 的缺口一并补上：`AlgorithmColumnTests.test_an_unregistered_algorithm_value_is_a_hard_failure_not_a_try_both`（载荷故意用一条**能对上 legacy 摘要**的 hex，配 `algorithm="sha256"` 必须硬失败 ⇒ 证明分派权威只有那两枚取值，不会"猜一个算法试试"），`Argon2ProfileTests.test_hasher_exposes_one_shared_instance_at_that_profile`（`hasher()` 是模块级单例且带着钉死的 m/t/p——上游登录腿测试要给它打桩，每次新建实例的话桩会空转）。

### 11.4 Finding 4 —— 边界模块里那条不存在的耦合

选了评审给的第一个选项：**退回计划原文的 `plain` 形状**。`credentials.py:100-101` 改回 `_legacy_digest(plain)`，`:130-131` 形参回到 `plain`，两处"关键字调用是 SECA-05 可见前提"的注释删除——它们断言的耦合确实不存在：扫描器判的是 `hashlib` 调用点的 unparse 文本，`_legacy_digest(password=plain)` 里的 `password=` 不在任何被扫节点的文本里，真正让这处可见的一直是形参名。计划已订正的 Step 5 代码块本身就是 `plain` 形状，退回后偏离面只剩 §11.1/§11.2 两处。

实测（扫描器改完后的命中集，恰两条）：

```
app\auth.py:174        hashlib.sha256(password.encode('utf-8'))
app\credentials.py:131 hashlib.sha256(plain.encode('utf-8'))
```

那条评论要保护的不变量改由一条用例来守，不再靠注释：`CentralisationScanTests.test_the_credentials_exemption_is_earned_by_an_actual_hit` 断言 credentials.py 在命中集里**恰有 1 处**——豁免表是"这里允许出现口令哈希"的声明，声明必须由真命中兑现；改名成中性词（`pwd`/`blob`）会让这处站点消失，M-E 实测该钉与等值钉同时红（§11.7）。

### 11.5 Finding 5 —— 扫描器的两种"天然隐身"

`CentralisationScanTests` 的扫描逻辑拆成两层：`_hashlib_bindings(tree)` 解析 hashlib 在本文件里绑定的名字 → 原算法名（`import hashlib`、`import hashlib.blake2b`、`import hashlib as hl`、`from hashlib import sha256 [as s]`、`from hashlib import *` 五种绑法；别名记回原算法名，否则 `as s` 换个名字就把算法名从判据里抹掉；星号导入静态不知道绑了哪些名字，只能记下"有这回事"并按调用点词面兜），`_hashlib_password_calls(tree)` 再按绑定名匹配 `ast.Attribute`（`hashlib.x()` / `hl.x()`）与 `ast.Name`（`sha256()` / `s()`）两种调用形态。`_hashlib_password_sites()` 只剩走盘 + 拼 `path:lineno text`，两条既有断言与等值钉字面量未动。

改前/改后同一批形态的命中数（进程内跑真函数，未落盘）：

| 绑法 | 轮 2 扫描器 | 本轮扫描器 |
| --- | --- | --- |
| `import hashlib` | 1 | 1 |
| `import hashlib as hl` | **0（漏）** | 1 |
| `from hashlib import sha256` | **0（整份文件被跳过）** | 1 |
| `from hashlib import sha256 as s` | **0** | 1 |
| `from hashlib import *` | **0** | 1 |

四种漏法是"看不见"而不是"判红"，所以补了两组双向用例把它钉住：`test_every_hashlib_binding_shape_reaches_the_same_password_site`（五种绑法写同一个口令站点，各 1 命中）与 `test_a_non_password_digest_stays_out_of_the_hit_set_under_every_binding`（缓存键一类的非口令摘要四种绑法各 0 命中——豁免表面向的是"口令"，不许把无关的 `sha256` 用法卷进来，否则这道门会在别人改无关代码时判红）。仓内现状核过：`app/typesafe_judgments.py:102/114` 两处非口令摘要在放宽后仍不命中。

### 11.6 Finding 6 —— 注释在叙述计划

`TRANSITIONAL_EXEMPT` 上方那段（原文有"计划 Task 5 Step 6 删 `auth._password_digest`"）改成条件式陈述：豁免只在"`app/auth.py` 还在自己算口令摘要"这段时间有效，收进本模块是原子动作、删站点与清空本表必须同轮发生；并且**不需要谁去记得**——那处命中一旦消失，等值钉就把空转的豁免直接判红（§8.4 控制 3 已实测该机制）。全文再无任务/计划/进度字样（本轮另在 `credentials.py` 与 `Argon2ProfileTests` 两处按同一口径改写过措辞，见 §11.2）。

### 11.7 可证伪性实测（每条 finding 一个变异）

变异用字节级替换落盘、跑对应节点、再按原字节还原（`sha256` 比对确认还原无损），事后 `python -m pytest tests/test_credentials_contract.py -q` 复绿：

| 变异 | 打在 | 实测红的用例 |
| --- | --- | --- |
| M-A `verify_dummy` 退回 `return outcome` | F1 | `test_the_dummy_payloads_own_plaintext_still_does_not_verify` → `1 failed, 2 passed` |
| M-B `except` 退回 `InvalidHashError` | F2 | `test_argon2_column_with_a_right_prefix_and_an_unparseable_body_is_a_hard_failure` → `1 failed, 4 passed` |
| M-C1 dummy 腿绕过闸门（`outcome` 直接写死 `VerifyOutcome(False, False)`） | F3 | `test_a_full_slot_pool_turns_the_dummy_path_into_a_capacity_error` → `1 failed, 3 passed` |
| M-C2 删 `finally: _SLOTS.release()` | F3 | `test_the_slot_is_given_back_even_when_the_body_raises` → `1 failed, 3 passed` |
| M-F `_verify_argon2` 整个 `with argon2_slot():` 换成 `if True:` | F3 + 注意事项② | 两条容量钉同时红 → `2 failed, 2 passed` |
| M-E `_legacy_digest` 形参改成中性名 `pwd` | F4 | `test_the_credentials_exemption_is_earned_by_an_actual_hit` + `test_the_exemption_table_is_equal_to_the_hit_set` → `2 failed, 3 passed` |

M-A 顺带证明 finding 1 的根因不在词表或扫描侧；M-C1 与 M-A 是一对：单看"永远 ok=False"可以靠写死返回值蒙过，只有"占同一道闸"这条能逼出真运算。

### 11.8 门与套件（本轮终态）

```
$ cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q
21 passed, 9 subtests passed in 3.34s        # 轮 2 是 10 passed；本轮 +11 条用例、新增 9 个 subTest
$ cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py tests/test_rbac_contract.py -q
36 passed, 9 subtests passed in 4.68s        # 轮 2 是 25 passed
$ cd /e/xiangmu/rag/backend && python -m pytest -q
982 passed, 36 warnings, 1004 subtests passed in 231.40s (0:03:51)
$ cd /e/xiangmu/rag && python -m pytest backend/tests -q --collect-only → 982 tests collected
$ cd /e/xiangmu/rag/backend && python -m pytest -q --collect-only        → 982 tests collected   # 两种 cwd 相等 ✅
```

上面是**终态文件上最后一次的读数**（把那条长用例名折行改成一行的格式改动之后，复跑过一次全件，计数与耗时同量级、结论不变）。计数守恒核过：基线 971 + 本文件新增 11（10 → 21）= 982，零 failed、零 skip；warning 仍是 36 条，与基线同一批来源（PyJWT `InsecureKeyLengthWarning` 的 31 字节 HMAC key、`tests/conftest.py:243` 的 ledger-guard 读改道），本轮未引入新 warning、也未新增需要静音的输出。`tests/test_llm_egress_guard.py` 的 D6 豁免计数、`/api/query` 键集合钉、RBAC 契约均未动、均绿。

### 11.9 仍然有效的 Task 5 交接（替换 §8.7 的对应三条）

1. `CentralisationScanTests.TRANSITIONAL_EXEMPT` 改 `frozenset()`，与删 `app/auth.py` 那处口令摘要站点同轮；忘了改就等值钉自己红（`test_the_exemption_table_is_equal_to_the_hit_set`），不需要谁记。（F3 那条已从交接里摘掉——本轮已落。）
2. `_legacy_digest` 的形参名与 `plain`/`password` 词面是 SECA-05 认出本模块命中的前提，改名由 `test_the_credentials_exemption_is_earned_by_an_actual_hit` 判红，不再靠注释（M-E 实测）。
3. 计划文本侧待登记项：Step 6 的期望值现在是 `21 passed`（轮 2 订正的 `10 passed` 已过期，计划里那句还写着 `11 passed`）；`from hashlib import sha256` 一类的绑法现已纳入扫描面，§8.8 的 M13 变异片段可以按"真造一处 `hashlib.sha256(password…)`"升级，词法上限的其余部分（刻意中生命名 `blob`）仍要靠 Task 10 侧那条"业务模块不得 `import hashlib`"独立扫描收紧。

### 11.10 本轮现场事故（如实记）

变异探针第一次用 `Path.write_text()` 还原 `app/credentials.py`，Windows 文本模式把全文件行尾从 LF 翻成 CRLF（131 行全变），字节 `sha256` 比对当场发现；已按字节还原为 LF（`bytes 4735 / LF 131 / CRLF 0`，与轮 2 快照 `snap-task1-r1-app/credentials.py` 同一形态），之后的替换改用 `write_bytes` + 原字节还原（`byte-exact restore: True`）。内容零损失，事后聚焦测试与全套件均复绿（§11.8）。教训与本仓口令纪律同形：**能按字节核的别按"看起来一样"信**。

### 11.11 本轮改动清单（工作树，未提交）

```
 M backend/app/config.py                          # 轮 1（不变）
 M backend/requirements.txt                       # 轮 1（不变）
?? backend/app/credentials.py                     # 轮 3：F1 压判定 + `_DUMMY_PLAINTEXT`；F2 VerificationError；F4 退回 plain 形状并删两条假注释
?? backend/tests/test_credentials_contract.py     # 轮 3：F1–F5 共 11 条新用例 + 扫描器绑法解析 + F6 注释改写
```

零 git 写命令；`.superpowers/` 在 `.gitignore:25` 下，本轮未刷新快照（`snap-task1-app` / `snap-task1-r1-*` 保持原样，快照链归控制台）。

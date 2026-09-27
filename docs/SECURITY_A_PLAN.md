# SEC-A 安全速赢（口令存储 / 认证加固 / secret 卫生）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `app/auth.py` 里"源码常量 + 无盐 SHA-256"的口令面，替换为 Argon2id + 身份/凭据分家 + 可判定稳态零遗留的认证基线，并给 secret 卫生装上自动化门。

**Architecture:** 三段所有权——`credentials.py`（唯一哈希原语）、`user_store.py`（SQLite 凭据状态）、`directory.py`（身份声明文件）——由 `auth.py` 编排；渐进重哈希与 `must_change` 门在同一轮落地；令牌失效走 `credentials_version`（per-user auth epoch）；生产 fail-closed 由单开关 `SECURITY_ENTERPRISE_MODE` 的三件守卫共同承担。

**Tech Stack:** Python 3.13 / FastAPI / pydantic v2 + pydantic-settings / SQLite（`data/conversations.db`）/ PyJWT HS256 / **新增** `argon2-cffi` / unittest + pytest 跑法 / Docker Compose（`rag-backend`，:8001）。

**Spec:** `docs/SECURITY_A_SPECIFICATION.md`（已冻结，含 27 行测试矩阵 + 19 发变异 + 9 步 release gate）。执行时**两份文件一起读**——本计划从规格论证而来，矩阵 ID（SECA-xx）与变异 ID（Mxx）是评审共同语言。

## Global Constraints

每条对全部任务生效，取值逐字来自规格：

- **未被用户明确授权不得 `git commit`。** 本仓库既有纪律是 append-only 快照差分评审（规格 §17、项目记忆），因此本计划的收口步骤是"打快照 + 写台账"，不是 commit；真正的提交只出现在 Task 10 且需当轮授权。
- **全套件必须两种 cwd 计数相等**：`cd backend && python -m pytest -q` 与仓库根 `python -m backend.pytest`… 实际命令是仓库根 `python -m pytest backend/tests -q`；两者 collected 数必须相同（V2.3 冻结规矩）。
- **Argon2 部署档位常量固定为 `time_cost=2, memory_cost=19456, parallelism=1`**，**不得**经 env/settings 读取（SEC-A-008）。改档位 = 改规格 + 改本计划 + 重跑 SECA-19。
- **明文口令**不得进入：响应体、日志、`audit.jsonl`、`agent_traces.jsonl`、`llm_request_logs`、任何配置文件、CLI `argv`（SEC-A-002）。CLI 只读环境变量 `CREDENTIALS_PASSWORD`。
- **矩阵状态词汇表只有三值**：`GREEN / PENDING_EXTERNAL / BLOCKED`。`legacy_count>0` 是 `BLOCKED`，不是 `PENDING`（§8.7）。
- **不触碰 V2.3 冻结件**：`app/llm/*`、`app/rag.py`、`app/conversation_agent.py`、tag `model-router-v2.3-rc1`、RC `5ba5f20e…`。D6 豁免表（`test_llm_egress_guard.py:5362`）的命中计数不得变化——本计划不往 `rag.py`/`agent.py` 加任何 httpx 或端点字面量。
- **既有响应面键集合不得变化**，除规格 §11 声明的两枚 additive 键（`/api/auth/login`、`/api/auth/me` 各加 `password_change_required`）。`/api/query` 的键集合钉（`test_typesafe_api_runtime.py:91/119/148`）必须继续绿。
- **注释风格跟仓内既有代码**（中文为主、写"为什么"），不写"用于本任务/供 X 流程调用"式注释。
- **前端不改**：SEC-A 只交付后端契约与 additive 键；`password_change_required` 的引导页属后续规格，Task 10 的验收文档按已知限制记录。
- **变异台纪律**：任何变异必须字节安全（读字节 / 替换 / 写 / 还原 / sha1 核对 + 发内还原），禁止就地 `sed -i`；脚本落 `.superpowers/sdd/SECURITY_A_PLAN/mutations/`。
- **快照纪律**：每个任务收口时把当轮产物快照到 `.superpowers/sdd/SECURITY_A_PLAN/snap-task<N>/`（append-only，禁止覆写同名快照），并在 `.superpowers/sdd/SECURITY_A_PLAN/progress.md` 追加一行 `Ruling:` 记录本任务内做出的、规格未覆盖的判断。

## 文件结构（先定边界，再拆任务）

**新建（生产代码）**

| 文件 | 唯一职责 | 任务 |
| --- | --- | --- |
| `backend/app/credentials.py` | 口令哈希原语 + Argon2 档位常量 + dummy 串 + 并发闸门。**唯一**允许 `hashlib` 参与口令运算处 | 1 |
| `backend/app/user_store.py` | `user_credentials` 表：schema、读写、事务不变量。**写函数签名不含 algorithm** | 2 |
| `backend/app/credentials_migration.py` | 受限迁移路径：读升级工件 → 写 legacy 行；`migration-status` 事实采集 | 3 |
| `backend/app/directory.py` | 身份声明文件加载 + 合并/唯一性校验 + 测试注入接缝 | 4 |
| `backend/config/users.json` | 企业身份（运维所有）。**禁含凭据字段** | 4 |
| `backend/config/users.demo.json` | dev/test 身份。企业形态**不加载** | 4 |
| `backend/app/login_throttle.py` | pre-hash 节流（进程内，键 `(username, client_ip)`）+ 锁定判定纯函数 | 8 |
| `backend/app/security_startup.py` | `SECURITY_ENTERPRISE_MODE` 三件守卫的可调用求值面（lifespan 只是它的一个调用者） | 9 |
| `backend/app/cli.py` | `credentials bootstrap-admin / reset / migration-status`；口令只从 env 读 | 7 |
| `backend/data/legacy_credentials.json` | **升级工件**（迁移输入），closure 后删除 | 3 |

**新建（测试）**

| 文件 | 覆盖矩阵行 |
| --- | --- |
| `backend/tests/test_credentials_contract.py` | SECA-01(写路径半边) / 05 / 08 / 11 / 19(宿主半边) |
| `backend/tests/test_user_directory_contract.py` | SECA-04b / 07 / 23 / 24 |
| `backend/tests/test_authentication_leg_contract.py` | SECA-03 / 09 / 09b / 10 / 13 / 14 / 15 / 16a / 16b / 18 / 21 / 22 |
| `backend/tests/test_password_lifecycle_contract.py` | SECA-02 / 12 + 改密/重置端点与 CLI |
| `backend/tests/test_secret_hygiene_contract.py` | SECA-17 / 20 |
| `backend/tests/test_security_a_closure.py` | SECA-04 / 19(容器半边) + 三处扫描 + 套件耦合门 |

**修改（生产代码）**

`backend/requirements.txt`（+argon2-cffi）、`backend/app/auth.py`（编排、删 `USERS`/`_password_digest`）、`backend/app/main.py`（登录腿、两枚新端点、lifespan 第三道守卫、CORS env 化、`CurrentUser` 响应 additive 键）、`backend/app/config.py`（新 settings，**不含** m/t/p）、`backend/app/security.py`（`redact_for_persistence`）、`backend/app/audit.py` + `backend/app/agent_trace.py`（落盘面切换）、`backend/app/knowledge_os.py`（4 处 `USERS` 读点 → directory）、`backend/app/main_agent.py`（无改动，仅复用同 app 实例）、`backend/.env.example`、`scripts/deploy.ps1`（compose 侧守卫对齐）。

**修改（测试）**

`backend/tests/conftest.py`（demo 凭据会话级 seed）、`backend/tests/test_feishu_identity_contract.py:1707-1726`（→ directory 注入接缝）、`backend/tests/test_branding_contract.py:32`（→ 占位符形态 + 守卫拒绝）。

---

## Task 1: Argon2 口令原语（`credentials.py`）

**Files:**
- Modify: `backend/requirements.txt`（在 `PyJWT>=2.9,<3` 之后加一行）
- Create: `backend/app/credentials.py`
- Test: `backend/tests/test_credentials_contract.py`（新建）

**Interfaces:**
- Consumes: `settings.argon2_max_concurrent_ops`（Task 1 内自行在 `config.py` 加这一枚，默认 `2`；**不**加 m/t/p）
- Produces（Task 2/3/5/7/8 全部依赖这些名字）：
  ```python
  ALGORITHM_ARGON2ID: str = "argon2id"
  ALGORITHM_LEGACY_SHA256: str = "legacy-sha256"
  ARGON2_TIME_COST: int = 2
  ARGON2_MEMORY_COST: int = 19456
  ARGON2_PARALLELISM: int = 1
  ARGON2_HASH_PREFIX: str = "$argon2id$"
  class CredentialConfigError(RuntimeError): ...
  class PasswordCapacityError(RuntimeError): ...
  @dataclass(frozen=True)
  class VerifyOutcome: ok: bool; needs_rehash: bool
  def hasher() -> argon2.PasswordHasher                      # 模块级单例
  def hash_password(plain: str) -> str
  def needs_rehash(encoded: str) -> bool
  def verify_password(plain: str, *, algorithm: str, encoded: str) -> VerifyOutcome
  def verify_dummy(plain: str) -> VerifyOutcome              # 恒定一次 argon2 运算，永不返回 ok=True
  @contextmanager
  def argon2_slot()                                          # 非阻塞抢并发槽，失败 raise PasswordCapacityError
  ```

- [ ] **Step 1: 装依赖并确认宿主可导入**

```bash
cd /e/xiangmu/rag/backend
python -m pip install "argon2-cffi>=23.1.0,<26"
python -c "import argon2; print(argon2.__version__)"
```
Expected: 打印版本号，无报错。**容器内可用性不在本任务验证**（Task 10 的双向探针才判它）。

- [ ] **Step 2: 写失败的测试**（`backend/tests/test_credentials_contract.py`）

```python
from __future__ import annotations

import ast
import hashlib
import re
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import credentials  # noqa: E402


class Argon2ProfileTests(unittest.TestCase):
    def test_profile_is_the_owasp_minimum_baseline_and_is_a_code_constant(self):
        self.assertEqual(2, credentials.ARGON2_TIME_COST)
        self.assertEqual(19456, credentials.ARGON2_MEMORY_COST)
        self.assertEqual(1, credentials.ARGON2_PARALLELISM)

    def test_hashed_password_is_a_verifiable_argon2id_phc_string(self):
        encoded = credentials.hash_password("correct horse battery staple 12")
        self.assertTrue(encoded.startswith("$argon2id$"), encoded)
        outcome = credentials.verify_password(
            "correct horse battery staple 12",
            algorithm=credentials.ALGORITHM_ARGON2ID,
            encoded=encoded,
        )
        self.assertTrue(outcome.ok)
        self.assertFalse(outcome.needs_rehash)  # 刚按当前档位生成

    def test_a_wrong_password_does_not_verify(self):
        encoded = credentials.hash_password("right answer 1234567890")
        outcome = credentials.verify_password(
            "wrong answer 1234567890",
            algorithm=credentials.ALGORITHM_ARGON2ID,
            encoded=encoded,
        )
        self.assertFalse(outcome.ok)


class AlgorithmColumnTests(unittest.TestCase):
    """规格 §6.2：分派权威是列，编码串前缀只做交叉校验。"""

    def test_argon2_column_with_a_non_argon2_payload_is_a_hard_failure(self):
        with self.assertRaises(credentials.CredentialConfigError):
            credentials.verify_password(
                "x", algorithm=credentials.ALGORITHM_ARGON2ID, encoded="deadbeef"
            )

    def test_legacy_column_with_a_non_hex_payload_is_a_hard_failure(self):
        with self.assertRaises(credentials.CredentialConfigError):
            credentials.verify_password(
                "x",
                algorithm=credentials.ALGORITHM_LEGACY_SHA256,
                encoded="zz" * 32,
            )

    def test_a_legacy_digest_still_authenticates_under_the_legacy_column(self):
        plain = "legacy-demo-password"
        encoded = hashlib.sha256(plain.encode("utf-8")).hexdigest()
        outcome = credentials.verify_password(
            plain, algorithm=credentials.ALGORITHM_LEGACY_SHA256, encoded=encoded
        )
        self.assertTrue(outcome.ok)
        self.assertTrue(outcome.needs_rehash)  # legacy 永远要收敛


class DummyVerifyTests(unittest.TestCase):
    def test_dummy_verification_costs_one_argon2_run_and_never_succeeds(self):
        outcome = credentials.verify_dummy("anything at all 1234567890")
        self.assertFalse(outcome.ok)

    def test_dummy_string_is_generated_with_the_current_profile(self):
        # 若 dummy 串档位与当前 profile 不一致，§7.3 的"工作量可比"就是空话。
        self.assertTrue(
            credentials.dummy_hash().startswith(
                f"{credentials.ARGON2_HASH_PREFIX}v=19$"
                f"m={credentials.ARGON2_MEMORY_COST},"
                f"t={credentials.ARGON2_TIME_COST},"
                f"p={credentials.ARGON2_PARALLELISM}$"
            )
        )


class CentralisationScanTests(unittest.TestCase):
    """SECA-05：口令参与运算的 hashlib 命中面 == 豁免表，且豁免表只有一个成员。"""

    HASHES = re.compile(r"sha256|sha512|md5|blake2|pbkdf2")
    PASSWORD_WORDS = re.compile(r"(?i)password|passwd|secret")

    def _hashlib_password_sites(self) -> list[str]:
        offenders: list[str] = []
        for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = {
                node.name.split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
            }
            if "hashlib" not in imported:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
                    continue
                if func.value.id != "hashlib":
                    continue
                text = ast.unparse(node)
                if self.HASHES.search(func.attr) and self.PASSWORD_WORDS.search(text):
                    offenders.append(f"{path.relative_to(BACKEND_DIR)}:{node.lineno} {text}")
        return offenders

    def test_only_credentials_module_hashes_passwords(self):
        self.assertEqual(
            [],
            [
                site
                for site in self._hashlib_password_sites()
                if "app\\credentials.py" not in site and "app/credentials.py" not in site
            ],
        )

    def test_the_exemption_table_is_equal_to_the_hit_set(self):
        # 命中集去掉豁免后必须为空；豁免表也必须恰等于命中集的目录部分。
        hits = {site.split(":")[0] for site in self._hashlib_password_sites()}
        self.assertEqual({"app/credentials.py"}, {hit.replace("\\", "/") for hit in hits})
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q
```
Expected: collection error `ModuleNotFoundError: No module named 'app.credentials'`（`CentralisationScanTests` 的两条也会红，因为 `app/credentials.py` 还不存在 → 命中集为空集 ≠ 豁免表）。

- [ ] **Step 4: 加 settings 与依赖声明**

`backend/app/config.py`，放在 `jwt_expire_hours: int = 8` 下一行：

```python
    # Argon2 并发槽上限（可用性旋钮）。**密码学档位不在这里**：m/t/p 固定在
    # app/credentials.py 的常量上，改它等于改规格（SEC-A-008）。
    argon2_max_concurrent_ops: int = 2
```

`backend/requirements.txt`：

```
argon2-cffi>=23.1.0,<26
```

- [ ] **Step 5: 写最小实现**（`backend/app/credentials.py`）

```python
"""口令哈希原语：全仓唯一允许对口令做密码学运算的模块（SEC-A-005）。

只认识口令，不认识 username、不查库、不做失败语义——那些在 auth/user_store 上头。
"""

from __future__ import annotations

import hashlib
import hmac
import re
from contextlib import contextmanager
from dataclasses import dataclass
from threading import BoundedSemaphore

import argon2

from app.config import settings

ALGORITHM_ARGON2ID = "argon2id"
ALGORITHM_LEGACY_SHA256 = "legacy-sha256"

# OWASP Password Storage Cheat Sheet 的 Argon2id 最低推荐档（19 MiB / t=2 / p=1）。
# 出处不是 RFC 9106（它推荐 2 GiB/t=1/p=4 或 64 MiB/t=3/p=4），措辞别改回去。
# 这三枚常量不可经 env 调整：能运维调的安全强度等于没有强度（SEC-A-008）。
ARGON2_TIME_COST = 2
ARGON2_MEMORY_COST = 19456
ARGON2_PARALLELISM = 1

ARGON2_HASH_PREFIX = "$argon2id$"
_LEGACY_HEX = re.compile(r"^[0-9a-f]{64}$")


class CredentialConfigError(RuntimeError):
    """algorithm 列与编码串互相矛盾。不猜、不降级、不 try-both。"""


class PasswordCapacityError(RuntimeError):
    """并发槽已满。调用方翻译成 503，不是认证失败。"""


@dataclass(frozen=True)
class VerifyOutcome:
    ok: bool
    needs_rehash: bool


_HASHER = argon2.PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_COST,
    parallelism=ARGON2_PARALLELISM,
)

# 与当前档位同源的常量工作单元：未知账号 / disabled / 无凭据行 三态都要消耗
# 一次真实运算，否则"账号不存在"就是一条响应时间指纹。
_DUMMY_HASH = _HASHER.hash("yaoke-constant-work-dummy-credential")

_SLOTS = BoundedSemaphore(max(1, int(settings.argon2_max_concurrent_ops)))


def hasher() -> argon2.PasswordHasher:
    return _HASHER


def dummy_hash() -> str:
    return _DUMMY_HASH


def hash_password(plain: str) -> str:
    return _HASHER.hash(plain)


def needs_rehash(encoded: str) -> bool:
    # 参数漂移判定交给库：自行比较字符串会漏掉"改了 m/t/p 但 v=19 不变"这一类。
    return _HASHER.check_needs_rehash(encoded)


@contextmanager
def argon2_slot():
    if not _SLOTS.acquire(blocking=False):
        raise PasswordCapacityError("password operation capacity exceeded")
    try:
        yield
    finally:
        _SLOTS.release()


def verify_password(plain: str, *, algorithm: str, encoded: str) -> VerifyOutcome:
    if algorithm == ALGORITHM_ARGON2ID:
        if not encoded.startswith(ARGON2_HASH_PREFIX):
            raise CredentialConfigError(
                f"algorithm={algorithm!r} 与编码串前缀不符"
            )
        return _verify_argon2(plain, encoded)
    if algorithm == ALGORITHM_LEGACY_SHA256:
        if not _LEGACY_HEX.match(encoded):
            raise CredentialConfigError(
                f"algorithm={algorithm!r} 与编码串形态不符"
            )
        return VerifyOutcome(
            ok=hmac.compare_digest(_legacy_digest(plain), encoded.lower()),
            needs_rehash=True,
        )
    raise CredentialConfigError(f"未知 algorithm：{algorithm!r}")


def verify_dummy(plain: str) -> VerifyOutcome:
    """恒定一次同档 Argon2 运算，永不成功；异常是"口令不对"的正常路径。"""
    return _verify_argon2(plain, _DUMMY_HASH)


def _verify_argon2(plain: str, encoded: str) -> VerifyOutcome:
    with argon2_slot():
        try:
            _HASHER.verify(encoded, plain)
        except argon2.exceptions.VerifyMismatchError:
            return VerifyOutcome(ok=False, needs_rehash=needs_rehash(encoded))
        except argon2.exceptions.VerificationError as exc:
            # argon2-cffi 的异常树里 InvalidHashError ⊂ ValueError，而 VerificationError 是另一支，
            # 坏 PHC 串在 verify() 上抛的是 VerificationError("Decoding failed")——
            # 只捕 InvalidHashError 等于永远捕不到，库异常会逃出这个边界模块（Task 1 评审实测）。
            raise CredentialConfigError("Argon2 编码串无法解析") from exc
    return VerifyOutcome(ok=True, needs_rehash=needs_rehash(encoded))


def _legacy_digest(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()
```

**注意两处刻意的形状**：① `_verify_argon2` 只在 `VerifyMismatchError` 上返回 `ok=False`，其余异常外抛——把"编码串坏了"咽成"口令错了"会让 `CredentialConfigError` 那两条测试假绿；② `verify_dummy` 复用同一条 `_verify_argon2`，包括并发槽，否则哑校验路径成了绕过闸门的后门（M 台会在 Task 8 检查这一点）。

- [ ] **Step 6: 跑测试确认通过**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q
```
Expected: `11 passed`（含 `CentralisationScanTests` 两条转绿）。

- [ ] **Step 7: 定向门 + 快照**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py tests/test_rbac_contract.py -q
mkdir -p ../.superpowers/sdd/SECURITY_A
cp -r app ../.superpowers/sdd/SECURITY_A_PLAN/snap-task1-app
cp -r tests/test_credentials_contract.py ../.superpowers/sdd/SECURITY_A_PLAN/snap-task1-test.py
echo "- Ruling: Argon2 档位常量放 credentials.py；settings 只加 argon2_max_concurrent_ops（可用性旋钮）。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
```

---

## Task 2: 凭据状态持久层（`user_store.py`）

**Files:**
- Create: `backend/app/user_store.py`
- Test: `backend/tests/test_credentials_contract.py`（追加两个 TestCase）

**Interfaces:**
- Consumes: `credentials.hash_password` / `verify_password` / `ALGORITHM_*` / `CredentialConfigError`；库路径解析必须与两个同库读者**逐字一致**（`conversation_store.py:26-27`、`llm/usage.py:223` 都是 `os.getenv("CONVERSATION_DB_PATH", "data/conversations.db")`，**不**读 settings），并暴露模块级 `database_path()` 作为 conftest 可包的接缝。**计划初稿在这里写过"沿用 `settings.conversation_db_path`"——那个字段从来不存在，Task 2 评审已把它判为第二真源并删除（见 ledger 的 F1 裁定）。**
- Produces（Task 3/5/7/10 依赖）：
  ```python
  TABLE_NAME = "user_credentials"
  @dataclass(frozen=True)
  class CredentialRecord:
      username: str; algorithm: str; password_hash: str; credentials_version: int
      must_change: bool; failed_attempts: int; locked_until: str | None; updated_at: str
  def ensure_user_credentials_schema() -> None
  def get_record(username: str) -> CredentialRecord | None
  def list_records() -> list[CredentialRecord]
  def create_argon2(username: str, *, plain_password: str, must_change: bool) -> int
  def set_password_argon2(username: str, *, plain_password: str, must_change: bool) -> int
  def apply_rehash(username: str, *, plain_password: str, must_change: bool,
                   expected_version: int) -> bool
  def import_legacy_digest(username: str, digest_hex: str, *, must_change: bool) -> bool
  def record_login_failure(username: str, *, max_attempts: int, lock_seconds: int) -> bool
  def clear_login_failures(username: str) -> None
  def delete_record(username: str) -> bool
  def count_by_algorithm() -> dict[str, int]
  def column_names() -> list[str]
  ```
  以及异常：`class CredentialStoreError(RuntimeError)`。

- [ ] **Step 1: 写失败的测试**（追加到 `backend/tests/test_credentials_contract.py`）

```python
class UserStoreSchemaTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_db_path = os.environ.get("CONVERSATION_DB_PATH")
        os.environ["CONVERSATION_DB_PATH"] = str(Path(self._tmp.name) / "creds.db")
        importlib.reload(config_module)
        importlib.reload(user_store)
        user_store.ensure_user_credentials_schema()

    def tearDown(self):
        if self._saved_db_path is None:
            os.environ.pop("CONVERSATION_DB_PATH", None)
        else:
            os.environ["CONVERSATION_DB_PATH"] = self._saved_db_path
        importlib.reload(config_module)
        importlib.reload(user_store)
        self._tmp.cleanup()

    def test_column_set_may_hold_a_hash_but_never_a_plaintext_field(self):
        """SECA-08：明文字段不是"没人写"，是"不存在可写的地方"。"""
        columns = set(user_store.column_names())
        self.assertIn("password_hash", columns)
        self.assertTrue({"password", "plaintext_password", "raw_password"}.isdisjoint(columns))
        self.assertNotIn(
            "algorithm",
            inspect.signature(user_store.create_argon2).parameters,
        )
        self.assertNotIn(
            "algorithm",
            inspect.signature(user_store.set_password_argon2).parameters,
        )

    def test_created_rows_are_always_argon2id(self):
        """SECA-01 的持久层半边：普通写路径拿不到 legacy 这个取值。"""
        user_store.create_argon2("admin", plain_password="a-good-password 123", must_change=False)
        record = user_store.get_record("admin")
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, record.algorithm)
        self.assertTrue(record.password_hash.startswith("$argon2id$"))
        self.assertEqual(1, record.credentials_version)

    def test_only_the_restricted_importer_can_create_a_legacy_row(self):
        self.assertTrue(
            user_store.import_legacy_digest(
                "sales01", hashlib.sha256(b"sales123").hexdigest(), must_change=True
            )
        )
        record = user_store.get_record("sales01")
        self.assertEqual(credentials.ALGORITHM_LEGACY_SHA256, record.algorithm)
        self.assertTrue(record.must_change)
        self.assertEqual(
            {credentials.ALGORITHM_LEGACY_SHA256: 1},
            {k: v for k, v in user_store.count_by_algorithm().items() if v},
        )


class UserStoreTransactionTests(unittest.TestCase):
    """SECA-11 / SECA-12：新 hash、bump、清锁必须是一个提交单位。"""

    def test_password_change_bumps_version_and_clears_lock_state_together(self):
        user_store.create_argon2("admin", plain_password="old-password 123456", must_change=True)
        user_store.record_login_failure(
            "admin", max_attempts=1, lock_seconds=900
        )
        self.assertIsNotNone(user_store.get_record("admin").locked_until)

        new_version = user_store.set_password_argon2(
            "admin", plain_password="new-password 123456", must_change=False
        )
        record = user_store.get_record("admin")
        self.assertEqual(new_version, record.credentials_version)
        self.assertEqual(2, record.credentials_version)
        self.assertFalse(record.must_change)
        self.assertEqual(0, record.failed_attempts)
        self.assertIsNone(record.locked_until)

    def test_a_failing_version_bump_rolls_back_the_new_hash(self):
        user_store.create_argon2("admin", plain_password="old-password 123456", must_change=False)
        before = user_store.get_record("admin")
        with mock.patch.object(
            user_store, "_bump_and_clear", side_effect=user_store.CredentialStoreError("boom")
        ):
            with self.assertRaises(user_store.CredentialStoreError):
                user_store.set_password_argon2(
                    "admin", plain_password="new-password 123456", must_change=False
                )
        after = user_store.get_record("admin")
        self.assertEqual(before.password_hash, after.password_hash)
        self.assertEqual(before.credentials_version, after.credentials_version)

    def test_rehash_is_guarded_by_the_version_it_was_computed_for(self):
        user_store.create_argon2("admin", plain_password="old-password 123456", must_change=True)
        self.assertTrue(
            user_store.apply_rehash(
                "admin",
                plain_password="old-password 123456",
                must_change=True,
                expected_version=user_store.get_record("admin").credentials_version,
            )
        )
        record = user_store.get_record("admin")
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, record.algorithm)
        # 陈旧版本（并发下别人已经改过密）⇒ 整条 UPDATE 不落地
        self.assertFalse(
            user_store.apply_rehash(
                "admin",
                plain_password="old-password 123456",
                must_change=False,
                expected_version=record.credentials_version + 5,
            )
        )
        self.assertTrue(user_store.get_record("admin").must_change)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q
```
Expected: `ModuleNotFoundError: No module named 'app.user_store'`。

- [ ] **Step 3: 写实现**（`backend/app/user_store.py`）

```python
"""凭据状态持久层（规格 §6.1）。

这里只放**凭据状态**。身份（role / display_name / feishu_open_id）在 directory.py，
口令原语在 credentials.py。三处不得混，否则 SEC-A-010 的两个真源开始互相覆写。
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app import credentials
from app.config import settings

TABLE_NAME = "user_credentials"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
  username            TEXT PRIMARY KEY,
  algorithm           TEXT NOT NULL CHECK (algorithm IN ('{credentials.ALGORITHM_ARGON2ID}','{credentials.ALGORITHM_LEGACY_SHA256}')),
  password_hash       TEXT NOT NULL,
  credentials_version INTEGER NOT NULL DEFAULT 1,
  must_change         INTEGER NOT NULL DEFAULT 0,
  failed_attempts     INTEGER NOT NULL DEFAULT 0,
  locked_until        TEXT,
  updated_at          TEXT NOT NULL
);
"""

_COLUMNS = (
    "username",
    "algorithm",
    "password_hash",
    "credentials_version",
    "must_change",
    "failed_attempts",
    "locked_until",
    "updated_at",
)


class CredentialStoreError(RuntimeError):
    """存储层事故（连接、约束、版本冲突）。调用方不得把它当"口令错了"。"""


@dataclass(frozen=True)
class CredentialRecord:
    username: str
    algorithm: str
    password_hash: str
    credentials_version: int
    must_change: bool
    failed_attempts: int
    locked_until: str | None
    updated_at: str


_DB_PATH_ENV_VAR = "CONVERSATION_DB_PATH"
_DB_PATH_DEFAULT = "data/conversations.db"
_WRITE_TIMEOUT_SECONDS = 30.0   # 与同库的 ConversationStore 同一口径；默认 5s 会把一次
                                # 正常登录写成 "database is locked"


def database_path() -> Path:
    """每次连接时解析，且只有这一个解析点。

    会话级护栏改道 `usage` 的手法就是换掉模块级 `database_path`，本模块要能被同一个
    手法包走；import 期钉死更不行——重定向发生在用例开始时，比 import 晚。
    取值口径与两个同库读者逐字相同（`conversation_store.py:26-27`、`llm/usage.py:223`）：
    规格 §6.1 要求本表与 `conversations` 同一个文件，所以只能有一个真源，且它不是 settings。
    """
    return Path(os.getenv(_DB_PATH_ENV_VAR, _DB_PATH_DEFAULT)).expanduser()


def _connect() -> sqlite3.Connection:
    target = database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(target), timeout=_WRITE_TIMEOUT_SECONDS)
    connection.row_factory = sqlite3.Row
    return connection  # 这里不建表：ensure_user_credentials_schema() 是唯一 schema 出处


def ensure_user_credentials_schema() -> None:
    with closing(_connect()) as connection, connection:
        connection.executescript(_SCHEMA)


def column_names() -> list[str]:
    with closing(_connect()) as connection:
        rows = connection.execute(f"PRAGMA table_info({TABLE_NAME})").fetchall()
    return [str(row["name"]) for row in rows]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_from(row: sqlite3.Row) -> CredentialRecord:
    return CredentialRecord(
        username=str(row["username"]),
        algorithm=str(row["algorithm"]),
        password_hash=str(row["password_hash"]),
        credentials_version=int(row["credentials_version"]),
        must_change=bool(int(row["must_change"])),
        failed_attempts=int(row["failed_attempts"]),
        locked_until=None if row["locked_until"] is None else str(row["locked_until"]),
        updated_at=str(row["updated_at"]),
    )


def get_record(username: str) -> CredentialRecord | None:
    with closing(_connect()) as connection:
        row = connection.execute(
            f"SELECT * FROM {TABLE_NAME} WHERE username = ?", (str(username),)
        ).fetchone()
    return None if row is None else _record_from(row)


def list_records() -> list[CredentialRecord]:
    with closing(_connect()) as connection:
        rows = connection.execute(f"SELECT * FROM {TABLE_NAME} ORDER BY username").fetchall()
    return [_record_from(row) for row in rows]


def count_by_algorithm() -> dict[str, int]:
    with closing(_connect()) as connection:
        rows = connection.execute(
            f"SELECT algorithm, COUNT(*) AS n FROM {TABLE_NAME} GROUP BY algorithm"
        ).fetchall()
    return {str(row["algorithm"]): int(row["n"]) for row in rows}


def create_argon2(username: str, *, plain_password: str, must_change: bool) -> int:
    """唯一的新建口令入口。没有 algorithm 参数——legacy 因此不可达（SECA-01）。"""
    encoded = credentials.hash_password(plain_password)
    with closing(_connect()) as connection, connection:
        connection.execute(
            f"INSERT INTO {TABLE_NAME} (username, algorithm, password_hash,"
            " credentials_version, must_change, failed_attempts, locked_until, updated_at)"
            " VALUES (?, ?, ?, 1, ?, 0, NULL, ?)",
            (
                str(username),
                credentials.ALGORITHM_ARGON2ID,
                encoded,
                1 if must_change else 0,
                _now(),
            ),
        )
    return 1


def import_legacy_digest(username: str, digest_hex: str, *, must_change: bool) -> bool:
    """**受限迁移路径**：全仓唯一能写出 legacy 行的函数（SEC-A-004）。

    命名里带 legacy、且只被 credentials_migration 调用；SECA-05 的 AST 扫描与
    Task 3 的调用方扫描共同钉住这一点。
    """
    encoded = str(digest_hex).strip().lower()
    with closing(_connect()) as connection, connection:
        cursor = connection.execute(
            f"INSERT INTO {TABLE_NAME} (username, algorithm, password_hash,"
            " credentials_version, must_change, failed_attempts, locked_until, updated_at)"
            " VALUES (?, ?, ?, 1, ?, 0, NULL, ?)"
            " ON CONFLICT(username) DO NOTHING",
            (
                str(username),
                credentials.ALGORITHM_LEGACY_SHA256,
                encoded,
                1 if must_change else 0,
                _now(),
            ),
        )
    return cursor.rowcount > 0


def set_password_argon2(username: str, *, plain_password: str, must_change: bool) -> int:
    """改密 / 管理员重置共用的一条事务。

    新 hash + credentials_version bump + 清锁 + updated_at 在**一个** connection
    事务里提交：跨事务会留下"口令已换、旧 token 仍有效"的提交窗口（SECA-11），
    不清锁会让管理员 reset 之后用户仍被旧 lock 挡住（SECA-12）。
    """
    encoded = credentials.hash_password(plain_password)
    with closing(_connect()) as connection, connection:
        _bump_and_clear(
            connection,
            username=str(username),
            algorithm=credentials.ALGORITHM_ARGON2ID,
            encoded=encoded,
            must_change=must_change,
        )
        row = connection.execute(
            f"SELECT credentials_version FROM {TABLE_NAME} WHERE username = ?",
            (str(username),),
        ).fetchone()
        if row is None:
            raise CredentialStoreError(f"账号不存在：{username}")
        return int(row["credentials_version"])


def _bump_and_clear(
    connection: sqlite3.Connection,
    *,
    username: str,
    algorithm: str,
    encoded: str,
    must_change: bool,
) -> None:
    connection.execute(
        f"UPDATE {TABLE_NAME} SET algorithm = ?, password_hash = ?,"
        " credentials_version = credentials_version + 1, must_change = ?,"
        " failed_attempts = 0, locked_until = NULL, updated_at = ?"
        " WHERE username = ?",
        (algorithm, encoded, 1 if must_change else 0, _now(), username),
    )


def apply_rehash(
    username: str,
    *,
    plain_password: str,
    must_change: bool,
    expected_version: int,
) -> bool:
    """渐进重哈希。**不** bump 版本：登录不改会话，只改强度。

    版本作为乐观锁参与 WHERE，并发改密时这条 UPDATE 会落空并返回 False，
    由调用方（登录腿）当作"已放弃收敛，不算失败"处理。
    """
    encoded = credentials.hash_password(plain_password)
    with closing(_connect()) as connection, connection:
        cursor = connection.execute(
            f"UPDATE {TABLE_NAME} SET algorithm = ?, password_hash = ?, must_change = ?,"
            " updated_at = ? WHERE username = ? AND credentials_version = ?",
            (
                credentials.ALGORITHM_ARGON2ID,
                encoded,
                1 if must_change else 0,
                _now(),
                str(username),
                int(expected_version),
            ),
        )
    return cursor.rowcount > 0


def record_login_failure(username: str, *, max_attempts: int, lock_seconds: int) -> bool:
    """账号级持久失败计数（规格 §7.2 第二层），键只有 username。"""
    with closing(_connect()) as connection, connection:
        cursor = connection.execute(
            f"UPDATE {TABLE_NAME} SET failed_attempts = failed_attempts + 1,"
            " updated_at = ? WHERE username = ?",
            (_now(), str(username)),
        )
        if cursor.rowcount == 0:
            return False
        row = connection.execute(
            f"SELECT failed_attempts FROM {TABLE_NAME} WHERE username = ?",
            (str(username),),
        ).fetchone()
        locked_now = int(row["failed_attempts"]) >= int(max_attempts)
        if locked_now:
            until = (datetime.now(timezone.utc) + timedelta(seconds=int(lock_seconds))).isoformat()
            connection.execute(
                f"UPDATE {TABLE_NAME} SET locked_until = ? WHERE username = ?",
                (until, str(username)),
            )
    return locked_now


def clear_login_failures(username: str) -> None:
    with closing(_connect()) as connection, connection:
        connection.execute(
            f"UPDATE {TABLE_NAME} SET failed_attempts = 0, locked_until = NULL"
            " WHERE username = ?",
            (str(username),),
        )


def delete_record(username: str) -> bool:
    with closing(_connect()) as connection, connection:
        cursor = connection.execute(
            f"DELETE FROM {TABLE_NAME} WHERE username = ?", (str(username),)
        )
    return cursor.rowcount > 0
```

实现里两处不要"顺手清理"：`create_argon2` 的 `return 1` 不是占位——它返回值就是刚落库的版本号，改成 `None` 会让 Task 7 的 CLI 打印丢掉版本事实；`_bump_and_clear` 被单独抽成模块函数，正是为了让 SECA-11 能用 `mock.patch.object` 从中间打断事务（不抽出来就只能靠 SQLite 故障注入，那条路在 CI 上不可复现）。

- [ ] **Step 4: 补测试文件头部 import**

`backend/tests/test_credentials_contract.py` 顶部 import 段补：

```python
import importlib
import inspect
import os
import tempfile
from unittest import mock

from app import config as config_module
from app import credentials, user_store
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q
```
Expected: `19 passed`。

- [ ] **Step 6: 定向门 + 快照**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py tests/test_llm_usage_contract.py -q
cp -r app ../.superpowers/sdd/SECURITY_A_PLAN/snap-task2-app
echo "- Ruling: 渐进重哈希不 bump credentials_version（登录不改会话，只改强度）；只有改密/重置 bump。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
```

---

## Task 3: 受限迁移路径（`credentials_migration.py` + 升级工件）

**Files:**
- Create: `backend/app/credentials_migration.py`
- Create: `backend/data/legacy_credentials.json`（升级工件；**closure 时删除**，Task 10）
- Test: `backend/tests/test_credentials_contract.py`（追加 `MigrationPathTests`）

**Interfaces:**
- Consumes: `user_store.import_legacy_digest` / `get_record` / `count_by_algorithm` / `CredentialRecord`
- Produces（Task 5/7/10 依赖）：
  ```python
  LEGACY_INPUT_PATH: Path                       # Path("data/legacy_credentials.json")
  class MigrationArtifactError(RuntimeError): ...
  @dataclass(frozen=True)
  class MigrationReport: artifact_present: bool; imported: tuple[str,...]; skipped: tuple[str,...]; reason: str
  @dataclass(frozen=True)
  class AccountStatus: username: str; algorithm: str; credentials_version: int
                       must_change: bool; locked_until: str | None; updated_at: str
  @dataclass(frozen=True)
  class MigrationStatus: legacy_count: int; argon2id_count: int; accounts: tuple[AccountStatus, ...]
  def read_artifact(path: Path = LEGACY_INPUT_PATH) -> dict[str, str]
  def import_from_artifact(path: Path = LEGACY_INPUT_PATH, *, only_missing: bool = True) -> MigrationReport
  def status() -> MigrationStatus
  ```

**工件格式**（顶层键封闭，形态错 = 拒绝导入而不是部分导入）：

```json
{
  "generated_at": "2026-09-25T00:00:00+00:00",
  "source": "app/auth.py@pre-SEC-A",
  "credentials": {
    "admin": "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9",
    "sales01": "6bc0a63cb29c92306020c0a6bbc358cc4628db277dc06e253535e126517ad637",
    "hr01": "070a3b5e8d4bd5c46acccb91c9c54614c0cd649e78c4c4719e3a64270bae5ddf",
    "user": "e606e38b0d8c19b24cf0ee3808183162ea7cd63ff7912dbb22b5e803286b4446",
    "viewer": "65375049b9e4d7cad6c9ba286fdeb9394b28135a3e84136404cfccfdcc438894"
  }
}
```

`source` 字段值来自 Task 5 删除 `auth.USERS` 之前的抄录（本任务 Step 1 先从 `app/auth.py:71-103` 逐字取 digest，不手写、不凭记忆）。

- [ ] **Step 1: 从现有源码生成升级工件**（不手抄）

```bash
cd /e/xiangmu/rag/backend
python - <<'PY'
import json, re
from datetime import datetime, timezone
from pathlib import Path
source = Path("app/auth.py").read_text(encoding="utf-8")
pairs = re.findall(r'"username":\s*"([^"]+)",.*?"password_hash":\s*"([0-9a-f]{64})"', source, re.S)
artifact = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "source": "app/auth.py@pre-SEC-A",
    "credentials": {username: digest for username, digest in pairs},
}
Path("data").mkdir(exist_ok=True)
Path("data/legacy_credentials.json").write_text(
    json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
print(len(artifact["credentials"]), sorted(artifact["credentials"]))
PY
```
Expected: `5 ['admin', 'hr01', 'sales01', 'user', 'viewer']`。少于 5 就说明正则没对上，必须先修正则——**不许**照本计划里的字面量手抄（抄错=迁移后没人能登录，且 SECA-04 的"0 命中"扫描仍然绿，因为它只数 digest 是否存在）。

- [ ] **Step 2: 写失败的测试**（追加 `MigrationPathTests`）

```python
class MigrationPathTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = os.environ.get("CONVERSATION_DB_PATH")
        os.environ["CONVERSATION_DB_PATH"] = str(Path(self._tmp.name) / "migrate.db")
        importlib.reload(config_module)
        importlib.reload(user_store)
        user_store.ensure_user_credentials_schema()

    def tearDown(self):
        os.environ.pop("CONVERSATION_DB_PATH", None)
        if self._saved is not None:
            os.environ["CONVERSATION_DB_PATH"] = self._saved
        importlib.reload(config_module)
        importlib.reload(user_store)
        self._tmp.cleanup()

    def _artifact(self, payload: dict) -> Path:
        path = Path(self._tmp.name) / "artifact.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_a_fresh_install_without_an_artifact_imports_nothing(self):
        """SECA-04b：全新安装不生产 legacy 行，这是 §8.2 分家的落点。"""
        report = credentials_migration.import_from_artifact(
            Path(self._tmp.name) / "does-not-exist.json"
        )
        self.assertFalse(report.artifact_present)
        self.assertEqual((), report.imported)
        self.assertEqual(0, credentials_migration.status().legacy_count)

    def test_imported_rows_are_legacy_and_flagged_for_forced_change(self):
        path = self._artifact(
            {
                "generated_at": "2026-09-25T00:00:00+00:00",
                "source": "app/auth.py@pre-SEC-A",
                "credentials": {"admin": "a" * 64},
            }
        )
        report = credentials_migration.import_from_artifact(path)
        self.assertEqual(("admin",), report.imported)
        record = user_store.get_record("admin")
        self.assertEqual(credentials.ALGORITHM_LEGACY_SHA256, record.algorithm)
        self.assertTrue(record.must_change)
        self.assertEqual(1, credentials_migration.status().legacy_count)

    def test_reimporting_does_not_downgrade_an_already_upgraded_row(self):
        user_store.create_argon2("admin", plain_password="already-migrated 123456", must_change=False)
        path = self._artifact({"generated_at": "x", "source": "y", "credentials": {"admin": "a" * 64}})
        report = credentials_migration.import_from_artifact(path)
        self.assertEqual((), report.imported)
        self.assertEqual(("admin",), report.skipped)
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, user_store.get_record("admin").algorithm)

    def test_a_malformed_artifact_is_rejected_as_a_whole(self):
        for payload in (
            {"generated_at": "x", "source": "y", "credentials": {"admin": "not-hex"}},
            {"generated_at": "x", "source": "y", "credentials": ["admin"]},
            {"generated_at": "x", "source": "y", "credentials": {}, "oops": 1},
        ):
            with self.subTest(keys=sorted(payload)):
                with self.assertRaises(credentials_migration.MigrationArtifactError):
                    credentials_migration.import_from_artifact(self._artifact(payload))
        self.assertEqual(0, credentials_migration.status().legacy_count)

    def test_only_the_migration_module_may_call_the_legacy_writer(self):
        """SEC-A-004：受限路径必须真的受限——按调用方扫描，不按函数名信任。"""
        callers: set[str] = set()
        for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_legacy_digest"
                ):
                    callers.add(path.name)
        self.assertEqual({"credentials_migration.py"}, callers)
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q -k MigrationPath
```
Expected: `ModuleNotFoundError: No module named 'app.credentials_migration'`（同时补上测试文件 import 段的 `from app import credentials_migration` 与 `import json`）。

- [ ] **Step 4: 写实现**（`backend/app/credentials_migration.py`）

```python
"""受限迁移路径（规格 §8.2）。全仓唯一能生产 legacy 凭据行的地方。

它**只**服务"从 SEC-A 之前的版本升级"：全新安装没有工件 ⇒ 没有 legacy 行。
把这两件事混在一起（"缺凭据行就自动造 legacy"）是本规格在复核里被否掉的写法。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import credentials, user_store

LEGACY_INPUT_PATH = Path("data/legacy_credentials.json")
ARTIFACT_KEYS = frozenset({"generated_at", "source", "credentials"})
_LEGACY_HEX = re.compile(r"^[0-9a-f]{64}$")


class MigrationArtifactError(RuntimeError):
    """升级工件形态不对。整体拒绝，绝不"跳过坏条目继续导几个"。"""


@dataclass(frozen=True)
class MigrationReport:
    artifact_present: bool
    imported: tuple[str, ...]
    skipped: tuple[str, ...]
    reason: str = ""


@dataclass(frozen=True)
class AccountStatus:
    username: str
    algorithm: str
    credentials_version: int
    must_change: bool
    locked_until: str | None
    updated_at: str


@dataclass(frozen=True)
class MigrationStatus:
    legacy_count: int
    argon2id_count: int
    accounts: tuple[AccountStatus, ...]


def read_artifact(path: Path = LEGACY_INPUT_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MigrationArtifactError("迁移输入不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise MigrationArtifactError("迁移输入顶层必须是对象")
    unknown = set(payload) - ARTIFACT_KEYS
    if unknown:
        raise MigrationArtifactError(f"迁移输入含未知字段：{sorted(unknown)}")
    block = payload.get("credentials")
    if block is None:
        raise MigrationArtifactError("迁移输入缺少 credentials")
    if not isinstance(block, dict):
        raise MigrationArtifactError("credentials 必须是 username→digest 的对象")
    normalized: dict[str, str] = {}
    for username, digest in block.items():
        if not isinstance(digest, str) or not _LEGACY_HEX.match(digest.strip().lower()):
            raise MigrationArtifactError(f"{username} 的迁移输入不是 64 位 hex")
        normalized[str(username)] = digest.strip().lower()
    return normalized


def import_from_artifact(
    path: Path = LEGACY_INPUT_PATH, *, only_missing: bool = True
) -> MigrationReport:
    block = read_artifact(path)
    if not block:
        return MigrationReport(
            artifact_present=False,
            imported=(),
            skipped=(),
            reason="迁移输入不存在：全新安装不生产 legacy 行",
        )
    imported: list[str] = []
    skipped: list[str] = []
    for username, digest in sorted(block.items()):
        if only_missing and user_store.get_record(username) is not None:
            skipped.append(username)
            continue
        user_store.import_legacy_digest(username, digest, must_change=True)
        imported.append(username)
    return MigrationReport(True, tuple(imported), tuple(skipped), "")


def status() -> MigrationStatus:
    counts = user_store.count_by_algorithm()
    rows = tuple(
        AccountStatus(
            username=record.username,
            algorithm=record.algorithm,
            credentials_version=record.credentials_version,
            must_change=record.must_change,
            locked_until=record.locked_until,
            updated_at=record.updated_at,
        )
        for record in user_store.list_records()
    )
    return MigrationStatus(
        legacy_count=int(counts.get(credentials.ALGORITHM_LEGACY_SHA256, 0)),
        argon2id_count=int(counts.get(credentials.ALGORITHM_ARGON2ID, 0)),
        accounts=rows,
    )
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q
```
Expected: `24 passed`。

- [ ] **Step 6: 快照 + 台账**

```bash
cd /e/xiangmu/rag/backend
cp -r app ../.superpowers/sdd/SECURITY_A_PLAN/snap-task3-app
cp data/legacy_credentials.json ../.superpowers/sdd/SECURITY_A_PLAN/snap-task3-legacy-artifact.json
echo "- Ruling: 迁移器只校验凭据形态（64-hex / 顶层键封闭）；身份交叉校验留到 Task 5 的启动 seed 编排，因为身份层 Task 4 才存在。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
echo "- Ruling: 重跑导入对已存在行只跳过，绝不把已升级的 argon2id 行降回 legacy。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
```

---

## Task 4: 身份声明层（`directory.py` + `users.json` / `users.demo.json`）

**Files:**
- Create: `backend/app/directory.py`
- Create: `backend/config/users.json`、`backend/config/users.demo.json`
- Modify: `backend/app/config.py`（加 `security_enterprise_mode`）
- Modify: `backend/app/knowledge_os.py:24,560,564,567,703`（`USERS` 读点 → directory）
- Test: `backend/tests/test_user_directory_contract.py`（新建）

**Interfaces:**
- Consumes: `settings.security_enterprise_mode`（本任务新增，默认 `False`）
- Produces（Task 5/7/9 依赖）：
  ```python
  ENTERPRISE_IDENTITIES_FILE: Path              # Path("config/users.json")
  DEMO_IDENTITIES_FILE: Path                    # Path("config/users.demo.json")
  FORBIDDEN_IDENTITY_KEYS: frozenset[str]
  class IdentityConfigError(RuntimeError): ...
  class UserIdentity(BaseModel):                # extra="forbid"
      username: str; display_name: str; role: str
      feishu_open_id: str | None = None; enabled: bool = True
  def load_identities(*, include_demo: bool) -> dict[str, UserIdentity]
  def identities() -> Mapping[str, UserIdentity]        # 按当前形态缓存
  def get_identity(username: str) -> UserIdentity | None
  def reset_cache() -> None
  @contextmanager def override_identities(mapping: Mapping[str, UserIdentity])
  ```

- [ ] **Step 1: 先确认 `config/` 在镜像里，且路径基准是 `backend/`**

```bash
cd /e/xiangmu/rag/backend && ls config && grep -n "COPY config" Dockerfile
```
Expected: `config/` 存在（V2.3 的模型注册表就在这里）且 Dockerfile 有 `COPY config ./config`。若第二条不成立，本任务额外要在 Dockerfile 补该行——**先测再写，不要假设**。

- [ ] **Step 2: 写失败的测试**（`backend/tests/test_user_directory_contract.py`）

```python
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import config as config_module  # noqa: E402
from app import directory  # noqa: E402


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text(json.dumps({"identities": records}, ensure_ascii=False), encoding="utf-8")
    return path


class IdentityFileTests(unittest.TestCase):
    """SECA-07 / SECA-23：身份文件是**结构上**无口令，不是"约定不写"。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.enterprise = _write(
            self.root / "users.json",
            [{"username": "admin", "display_name": "管理员", "role": "ADMIN"}],
        )
        self.demo = _write(
            self.root / "users.demo.json",
            [{"username": "viewer", "display_name": "只读", "role": "VIEWER"}],
        )
        self._saved = (directory.ENTERPRISE_IDENTITIES_FILE, directory.DEMO_IDENTITIES_FILE)
        directory.ENTERPRISE_IDENTITIES_FILE = self.enterprise
        directory.DEMO_IDENTITIES_FILE = self.demo

    def tearDown(self):
        (directory.ENTERPRISE_IDENTITIES_FILE, directory.DEMO_IDENTITIES_FILE) = self._saved
        self._tmp.cleanup()

    def _load(self, *, include_demo: bool):
        return directory.load_identities(include_demo=include_demo)

    def test_enterprise_mode_does_not_read_the_demo_file_at_all(self):
        self.assertEqual({"admin", "viewer"}, set(self._load(include_demo=True)))
        self.assertEqual({"admin"}, set(self._load(include_demo=False)))

    def test_a_credential_shaped_key_fails_startup_in_either_file(self):
        for key in ("password", "password_hash", "hash", "secret", "token", "api_key"):
            with self.subTest(key=key):
                _write(self.demo, [{"username": "viewer", "display_name": "只读",
                                    "role": "VIEWER", key: "x"}])
                with self.assertRaises(directory.IdentityConfigError):
                    self._load(include_demo=True)
        _write(self.enterprise, [{"username": "admin", "display_name": "管理员",
                                 "role": "ADMIN", "password": "hunter2"}])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)

    def test_a_legacy_digest_value_is_rejected_even_under_an_allowed_key(self):
        _write(self.enterprise, [{"username": "admin", "display_name": "a" * 40,
                                 "role": "ADMIN"}])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)

    def test_unknown_extra_fields_are_rejected_not_ignored(self):
        _write(self.enterprise, [{"username": "admin", "display_name": "管理员",
                                 "role": "ADMIN", "is_superuser": True}])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)

    def test_duplicate_username_across_files_fails_instead_of_letting_demo_override(self):
        """M18 的目标形态：`{**enterprise, **demo}` 必须被这条挡下。"""
        _write(self.demo, [{"username": "admin", "display_name": "假冒管理员", "role": "VIEWER"}])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=True)

    def test_duplicate_feishu_open_id_across_files_fails(self):
        _write(self.enterprise, [{"username": "admin", "display_name": "管理员",
                                 "role": "ADMIN", "feishu_open_id": "ou_shared"}])
        _write(self.demo, [{"username": "viewer", "display_name": "只读",
                           "role": "VIEWER", "feishu_open_id": "ou_shared"}])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=True)

    def test_disabled_is_a_first_class_identity_flag(self):
        _write(self.enterprise, [{"username": "admin", "display_name": "管理员",
                                 "role": "ADMIN", "enabled": False}])
        self.assertFalse(self._load(include_demo=False)["admin"].enabled)

    def test_default_is_enabled(self):
        self.assertTrue(self._load(include_demo=False)["admin"].enabled)

    def test_missing_enterprise_file_is_a_hard_failure_not_an_empty_directory(self):
        self.enterprise.unlink()
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_user_directory_contract.py -q
```
Expected: `ModuleNotFoundError: No module named 'app.directory'`。

- [ ] **Step 4: 写实现**（`backend/app/directory.py`）

```python
"""身份声明层（规格 §6.4）。身份的唯一真源是文件，凭据状态在 user_store，两边不得互串。

role 的取值**不在这里**校验：`access_role_for()` 对未知角色返回 None、权限表退化为空集，
那已经是 fail-closed。在这里再抄一份角色白名单只会造出第二个真源（RBAC 改了这里没改 = 静默失配）。
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ENTERPRISE_IDENTITIES_FILE = Path("config/users.json")
DEMO_IDENTITIES_FILE = Path("config/users.demo.json")

# 敏感键与"看起来像凭据"的形态。extra="forbid" 挡不住 display_name 里塞 digest，
# 所以两重都要有。
FORBIDDEN_IDENTITY_KEYS = frozenset(
    {"password", "password_hash", "hash", "secret", "token", "api_key", "credentials", "legacy"}
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class IdentityConfigError(RuntimeError):
    """身份文件不合法 ⇒ 启动失败。不是告警，不是忽略该条目。"""


class UserIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=32)
    feishu_open_id: str | None = None
    enabled: bool = True


def _validate_records(path: Path, payload: Any) -> list[UserIdentity]:
    if not path.exists():
        raise IdentityConfigError(f"身份文件不存在：{path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IdentityConfigError(f"身份文件不是合法 JSON：{path}") from exc
    if not isinstance(document, dict) or set(document) - {"identities"}:
        raise IdentityConfigError(f"身份文件顶层键必须是唯一的 identities：{path}")
    records = document.get("identities")
    if not isinstance(records, list):
        raise IdentityConfigError(f"{path}: identities 必须是数组")
    identities: list[UserIdentity] = []
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            raise IdentityConfigError(f"{path}: identities[{index}] 必须是对象")
        offending = FORBIDDEN_IDENTITY_KEYS & {str(key).lower() for key in raw}
        if offending:
            raise IdentityConfigError(f"{path}: identities[{index}] 含凭据字段 {sorted(offending)}")
        for value in raw.values():
            if isinstance(value, str) and _HEX64.match(value.strip().lower()):
                raise IdentityConfigError(f"{path}: identities[{index}] 含疑似口令摘要的取值")
        try:
            identities.append(UserIdentity(**raw))
        except ValidationError as exc:
            raise IdentityConfigError(f"{path}: identities[{index}] 不合法：{exc}") from exc
    return identities


def load_identities(*, include_demo: bool) -> dict[str, UserIdentity]:
    """enterprise 先、demo 后；重名一律拒，**不做**字典覆盖式合并。"""
    sources: list[Path] = [ENTERPRISE_IDENTITIES_FILE]
    if include_demo:
        sources.append(DEMO_IDENTITIES_FILE)
    merged: dict[str, UserIdentity] = {}
    seen_open_ids: dict[str, str] = {}
    for source in sources:
        for identity in _validate_records(source, None):
            if identity.username in merged:
                raise IdentityConfigError(
                    f"username 重复：{identity.username}（{source}）——demo 身份不得覆盖企业身份"
                )
            if identity.feishu_open_id is not None:
                if identity.feishu_open_id in seen_open_ids:
                    raise IdentityConfigError(
                        "feishu_open_id 重复："
                        f"{identity.feishu_open_id} 同时属于 {seen_open_ids[identity.feishu_open_id]}"
                        f" 与 {identity.username}"
                    )
                seen_open_ids[identity.feishu_open_id] = identity.username
            merged[identity.username] = identity
    return merged


_CACHE: dict[bool, dict[str, UserIdentity]] = {}


def identities() -> Mapping[str, UserIdentity]:
    """按形态缓存。形态在进程生命周期内不变（启动守卫负责它的成立）。"""
    from app.config import settings

    mode = bool(settings.security_enterprise_mode)
    if mode not in _CACHE:
        _CACHE[mode] = load_identities(include_demo=not mode)
    return _CACHE[mode]


def get_identity(username: str) -> UserIdentity | None:
    return identities().get(str(username))


def reset_cache() -> None:
    _CACHE.clear()


@contextmanager
def override_identities(mapping: Mapping[str, UserIdentity]) -> Iterator[None]:
    """测试接缝：替代过去"直接改 auth.USERS"的做法（规格 §16 改写的第二条）。"""
    from app.config import settings

    mode = bool(settings.security_enterprise_mode)
    saved = dict(_CACHE)
    _CACHE[mode] = dict(mapping)
    try:
        yield
    finally:
        _CACHE.clear()
        _CACHE.update(saved)
```

`_validate_records(path, payload)` 的第二个形参目前没有使用者——保留它是为了对齐 Task 5 会引入的"启动 seed 传 payload"路径；若到 Task 5 仍无人传，就在 Task 5 把它删掉，不许留成死参数。

- [ ] **Step 5: 写身份文件与 settings**

`backend/app/config.py`（放在 `jwt_secret` 之前，注明它同时驱动三件守卫）：

```python
    # SEC-A 生产形态总开关。true ⇒ 不加载 demo 身份 + 默认 JWT secret 拒启动 +
    # CORS 白名单未配拒启动（三件同生同死，规格 §8.5）。
    security_enterprise_mode: bool = False
```

`backend/config/users.json`：

```json
{
  "identities": []
}
```

`backend/config/users.demo.json`（逐字取自 `app/auth.py:71-103` 的现有记录，不改 display_name/role，口令字段**不带**）：

```json
{
  "identities": [
    { "username": "admin", "display_name": "系统管理员", "role": "ADMIN" },
    { "username": "sales01", "display_name": "销售演示账号", "role": "SALES" },
    { "username": "hr01", "display_name": "HR 演示账号", "role": "HR" },
    { "username": "user", "display_name": "普通用户演示账号", "role": "USER" },
    { "username": "viewer", "display_name": "只读访客演示账号", "role": "VIEWER" }
  ]
}
```

- [ ] **Step 6: 跑测试确认通过**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_user_directory_contract.py -q
```
Expected: `9 passed`。

- [ ] **Step 7: 迁移 `knowledge_os` 的 4 处身份读点**

`backend/app/knowledge_os.py:24` 的 import 去掉 `USERS`，改为 `from app.directory import identities as directory_identities, get_identity`；`:560` `USERS.get(...)` → `get_identity(...)`（下游 `record["role"]` 之类下标读法改成 `identity.role` / `identity.display_name` 属性读法）；`:564/:567` `len(USERS)` → `len(directory_identities())`；`:703` `for record in USERS.values()` → `for identity in directory_identities().values()`，字典构造里的 `record["username"]` → `identity.username`，其余同理。

- [ ] **Step 8: 加一枚**过渡**一致性钉（Task 5 删除）**

`backend/tests/test_user_directory_contract.py` 末尾追加：

```python
class TransitionalConsistencyPin(unittest.TestCase):
    """Task 4→5 期间 `auth.USERS` 仍在（认证腿还没切）。这枚钉防两份身份漂移。

    Task 5 删除 `USERS` 时**连这个类一起删**，不要改成"跳过"。
    """

    def test_directory_and_the_legacy_constant_table_describe_the_same_people(self):
        from app import auth

        loaded = directory.load_identities(include_demo=True)
        self.assertEqual(set(auth.USERS), set(loaded))
        for username, identity in loaded.items():
            self.assertEqual(auth.USERS[username]["display_name"], identity.display_name)
            self.assertEqual(auth.USERS[username]["role"], identity.role)
```

- [ ] **Step 9: 定向门 + 全套件**（这一步是本任务的真实风险点：4 处读点改坏不会只红安全测试）

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_user_directory_contract.py tests/test_rbac_contract.py -q
python -m pytest -q
```
Expected: 定向门绿；全套件绿且 collected 数 = Task 3 收口数 + 本任务新增测试数（记下确切数字，Task 10 要拿它对账）。若 `test_llm_egress_guard.py` 红，说明改 `knowledge_os.py` 时顺手动了出口面——回退那部分。

- [ ] **Step 10: 快照 + 台账**

```bash
cd /e/xiangmu/rag/backend
cp -r app ../.superpowers/sdd/SECURITY_A_PLAN/snap-task4-app
cp -r config ../.superpowers/sdd/SECURITY_A_PLAN/snap-task4-config
echo "- Ruling: directory 不校验 role 白名单（未知 role 已由 access_role_for→空权限 fail-closed），避免造第二个真源。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
echo "- Ruling: Task 4 结束仍保留 auth.USERS + 一枚过渡一致性钉；Task 5 删 USERS 时连钉一起删。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
```

---

## Task 5: 认证腿原子切换（删 `USERS` + 渐进重哈希 + `must_change` 门）

> **这是规格点名的不可分单元。** 身份文件禁止携带凭据 ⇒ "身份改读 directory"与"口令改读 user_store"必须同时发生；渐进重哈希与 `must_change` 门也必须同轮 ⇒ 本任务不接受拆分。评审时若发现"重哈希已落、门未落"或反之，直接判 FAIL。

**Files:**
- Modify: `backend/app/auth.py`（删 `USERS` 常量与 `_password_digest`，重写认证腿）
- Modify: `backend/app/identity/__init__.py:59-66`（`resolve_for_user` 从 dict 读法改为身份对象读法）
- Modify: `backend/app/main.py:238-255`（登录腿取 `LoginResult`）
- Create: `backend/tests/sec_a_seed.py`（demo 凭据 seed + `SEED_RECORD`）
- Modify: `backend/tests/conftest.py`（新增会话级 fixture，调用 `sec_a_seed`）
- Modify: `backend/tests/test_feishu_identity_contract.py:601,1707-1726`（→ `directory.override_identities` 接缝）
- Delete: `backend/tests/test_user_directory_contract.py::TransitionalConsistencyPin`（Task 4 的过渡钉，连类一起删）
- Create: `backend/tests/test_authentication_leg_contract.py`

**Interfaces:**
- Consumes: `directory.get_identity` / `directory.UserIdentity`；`user_store.*`；`credentials.*`
- Produces（Task 6/7/8 依赖）：
  ```python
  @dataclass(frozen=True)
  class LoginResult:
      user: CurrentUser | None
      audit_detail: str                 # "" | "invalid_credentials" | "AUTH_LOGIN_LOCKED" | "AUTH_REHASH_DEGRADED"
      password_change_required: bool
  def authenticate_with_result(username: str, password: str, *, client_ip: str = "") -> LoginResult
  def authenticate(username: str, password: str) -> CurrentUser | None   # 契约不变：仍返回 user|None
  def _user_from(identity, grant) -> CurrentUser                          # 唯一的 CurrentUser 构造点
  def record_login_event(*, username: str, detail: str) -> None           # 登录面唯一审计出口
  def require_user_pending_password(authorization) -> CurrentUser         # 白名单依赖（Task 6 接 cv）
  ```
  Task 8 会在 `auth.py` 补 `LoginThrottledError`；Task 5 不要预先造它。
  审计 `detail` 值域冻结为枚举止步：`invalid_credentials` / `AUTH_LOGIN_LOCKED` / `AUTH_REHASH_DEGRADED`，自由文本不得进入。

- [ ] **Step 1: 写失败的测试**（`backend/tests/test_authentication_leg_contract.py`）

```python
from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import auth, credentials, directory, user_store  # noqa: E402
from app import config as config_module  # noqa: E402
from sec_a_seed import SEED_RECORD, seed_demo_credentials  # noqa: E402

LEGACY_ADMIN = hashlib.sha256(b"admin123").hexdigest()


def _fresh_db(test: unittest.TestCase):
    tmp = tempfile.TemporaryDirectory()
    saved = os.environ.get("CONVERSATION_DB_PATH")
    os.environ["CONVERSATION_DB_PATH"] = str(Path(tmp.name) / "leg.db")
    importlib.reload(config_module)
    importlib.reload(user_store)
    user_store.ensure_user_credentials_schema()
    directory.reset_cache()

    def restore():
        os.environ.pop("CONVERSATION_DB_PATH", None)
        if saved is not None:
            os.environ["CONVERSATION_DB_PATH"] = saved
        importlib.reload(config_module)
        importlib.reload(user_store)
        directory.reset_cache()
        tmp.cleanup()

    test.addCleanup(restore)


class LegacyUpgradeTests(unittest.TestCase):
    """SECA-03 半边 A：升级路径不掉线，且当场收敛 + 被门挡住数据面。"""

    def setUp(self):
        _fresh_db(self)

    def test_a_legacy_digest_still_logs_in_and_is_upgraded_in_place(self):
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
        before = user_store.get_record("admin")

        result = auth.authenticate_with_result("admin", "admin123")

        self.assertIsNotNone(result.user)
        self.assertEqual("admin", result.user.username)
        self.assertTrue(result.password_change_required)
        after = user_store.get_record("admin")
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, after.algorithm)
        self.assertTrue(after.password_hash.startswith("$argon2id$"))
        self.assertTrue(after.must_change)
        # 渐进重哈希不改会话 ⇒ 版本不动（Task 2 的裁定）
        self.assertEqual(before.credentials_version, after.credentials_version)

    def test_the_upgraded_row_no_longer_holds_the_legacy_digest(self):
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
        auth.authenticate_with_result("admin", "admin123")
        self.assertNotIn(LEGACY_ADMIN, user_store.get_record("admin").password_hash)
        self.assertEqual(0, user_store.count_by_algorithm().get(credentials.ALGORITHM_LEGACY_SHA256, 0))

    def test_a_rehash_write_failure_still_logs_in_and_records_degraded(self):
        """SECA-21：UPDATE 失败是收敛延迟，不是把用户挡在门外。"""
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
        with mock.patch.object(
            user_store, "apply_rehash", side_effect=user_store.CredentialStoreError("locked db")
        ):
            result = auth.authenticate_with_result("admin", "admin123")
        self.assertIsNotNone(result.user)
        self.assertEqual("AUTH_REHASH_DEGRADED", result.audit_detail)
        self.assertTrue(result.password_change_required)
        self.assertEqual(
            credentials.ALGORITHM_LEGACY_SHA256, user_store.get_record("admin").algorithm
        )

    def test_an_argon2_row_with_drifted_params_rehashes_without_forcing_a_change(self):
        """needs_rehash 的两种来源要分开：参数漂移**不**置 must_change（规格 §8.3）。"""
        user_store.create_argon2("admin", plain_password="a-good-password 123456", must_change=False)
        stale = user_store.get_record("admin")
        with mock.patch.object(
            credentials, "needs_rehash", return_value=True
        ) as needs_rehash:
            result = auth.authenticate_with_result("admin", "a-good-password 123456")
        needs_rehash.assert_called_once()
        self.assertIsNotNone(result.user)
        self.assertFalse(result.password_change_required)
        after = user_store.get_record("admin")
        self.assertNotEqual(stale.password_hash, after.password_hash)
        self.assertFalse(after.must_change)
        self.assertEqual(stale.credentials_version, after.credentials_version)
        self.assertEqual("", result.audit_detail)


class UnifiedFailureTests(unittest.TestCase):
    """SECA-13 结构半边 + §9.1：四态在响应面上完全相同。"""

    def setUp(self):
        _fresh_db(self)

    def _results(self):
        user_store.create_argon2("admin", plain_password="a-good-password 123456", must_change=False)
        identities = dict(directory.load_identities(include_demo=True))
        disabled = directory.UserIdentity(
            username="paused", display_name="停用账号", role="VIEWER", enabled=False
        )
        identities["paused"] = disabled
        orphan = directory.UserIdentity(username="orphan", display_name="无凭据账号", role="VIEWER")
        identities["orphan"] = orphan
        with directory.override_identities(identities):
            return [
                auth.authenticate_with_result("nobody-at-all", "whatever 123456"),
                auth.authenticate_with_result("paused", "whatever 123456"),
                auth.authenticate_with_result("orphan", "whatever 123456"),
                auth.authenticate_with_result("admin", "wrong-password 123456"),
            ]

    def test_all_four_states_return_the_same_user_and_audit_detail(self):
        results = self._results()
        self.assertTrue(all(result.user is None for result in results))
        self.assertEqual({"invalid_credentials"}, {result.audit_detail for result in results})

    def test_all_four_states_consume_exactly_one_argon2_run_each(self):
        """判定用结构事实，不用毫秒阈值（规格 §7.3）。"""
        expected_profile = (
            f"m={credentials.ARGON2_MEMORY_COST},"
            f"t={credentials.ARGON2_TIME_COST},"
            f"p={credentials.ARGON2_PARALLELISM}"
        )
        with mock.patch.object(
            credentials.hasher(),
            "verify",
            side_effect=credentials.argon2.exceptions.VerifyMismatchError,
        ) as verify:
            results = self._results()
        self.assertEqual(4, len(results))
        self.assertTrue(all(result.user is None for result in results))
        # 四态各一次运算，且每次都落到当前档位上：哑校验不是"免费的早退"。
        self.assertEqual(4, verify.call_count, [call.args for call in verify.call_args_list])
        self.assertEqual(
            {expected_profile},
            {str(call.args[0]).split("$")[2] for call in verify.call_args_list},
        )

    def test_a_locked_account_reports_the_internal_detail_only(self):
        """SECA-14：对外仍是与其余三态逐字相同的中文响应面，锁定原因只进审计 token。"""
        user_store.create_argon2("admin", plain_password="a-good-password 123456", must_change=False)
        user_store.record_login_failure("admin", max_attempts=1, lock_seconds=900)
        with mock.patch.object(credentials.hasher(), "verify") as verify:
            result = auth.authenticate_with_result("admin", "a-good-password 123456")
        self.assertIsNone(result.user)
        self.assertEqual("AUTH_LOGIN_LOCKED", result.audit_detail)
        verify.assert_not_called()  # 锁定判定在昂贵运算之前（§7.1 步骤 3 早于 4）


class SourceRemovalTests(unittest.TestCase):
    def test_auth_no_longer_holds_a_user_table_or_a_password_hash(self):
        self.assertFalse(hasattr(auth, "USERS"))
        self.assertFalse(hasattr(auth, "_password_digest"))

    def test_every_demo_login_path_is_argon2_after_the_seed(self):
        """SECA-04b 的一半：全新库（无升级工件）不可能出现 legacy 行。"""
        _fresh_db(self)
        seed_demo_credentials()
        self.assertEqual(
            {},
            {
                algorithm: count
                for algorithm, count in user_store.count_by_algorithm().items()
                if algorithm != credentials.ALGORITHM_ARGON2ID
            },
        )
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_authentication_leg_contract.py -q
```
Expected: `AttributeError: module 'app.auth' has no attribute 'authenticate_with_result'`（多数用例会红在同一个点上，正常）。

- [ ] **Step 3: 写认证腿**（`backend/app/auth.py` 的口令段整体替换）

先在 `backend/app/config.py` 加两枚**账号级**参数——本任务的失败计数就要用它们（节流两枚留给 Task 8，一次性加六枚会让"哪一步真正需要什么"糊成一团）：

```python
    # 账号级持久锁定（规格 §7.2 第二层）：键只有 username，跨来源共享同一失败状态。
    account_max_failed_attempts: int = 5
    account_lock_seconds: int = 900
```

```python
from app import credentials, directory, user_store
from app.audit import record_event as _record_event
from app.config import settings

AUDIT_INVALID_CREDENTIALS = "invalid_credentials"
AUDIT_LOGIN_LOCKED = "AUTH_LOGIN_LOCKED"
AUDIT_REHASH_DEGRADED = "AUTH_REHASH_DEGRADED"


@dataclass(frozen=True)
class LoginResult:
    user: CurrentUser | None
    audit_detail: str
    password_change_required: bool


def record_login_event(*, username: str, detail: str) -> None:
    """登录面的唯一审计出口。detail 只允许三个枚举值。"""
    _record_event(
        username=username or "unknown",
        role="UNKNOWN",
        action="LOGIN",
        status="SUCCESS" if detail == "AUTH_REHASH_DEGRADED" else "DENIED",
        detail=detail,
    )


def authenticate_with_result(username: str, password: str) -> LoginResult:
    identity = directory.get_identity(username)
    record = user_store.get_record(username)
    # 未知账号 / 已停用 / 有身份无凭据：三态共用一条恒定成本路径（§7.3）。
    if identity is None or not identity.enabled or record is None:
        credentials.verify_dummy(password)
        return LoginResult(None, AUDIT_INVALID_CREDENTIALS, False)

    if _locked(record):
        # 不跑 Argon2：锁定路径显式排除在 timing 承诺之外（§7.4）。
        return LoginResult(None, AUDIT_LOGIN_LOCKED, False)

    outcome = credentials.verify_password(
        password, algorithm=record.algorithm, encoded=record.password_hash
    )
    if not outcome.ok:
        user_store.record_login_failure(
            username,
            max_attempts=settings.account_max_failed_attempts,
            lock_seconds=settings.account_lock_seconds,
        )
        return LoginResult(None, AUDIT_INVALID_CREDENTIALS, False)

    user_store.clear_login_failures(username)
    must_change = record.must_change
    detail = ""
    if outcome.needs_rehash:
        forced = record.algorithm == credentials.ALGORITHM_LEGACY_SHA256
        must_change = True if forced else must_change
        try:
            wrote = user_store.apply_rehash(
                username,
                plain_password=password,
                must_change=must_change,
                expected_version=record.credentials_version,
            )
        except Exception:
            wrote = False
        if forced and not wrote:
            detail = AUDIT_REHASH_DEGRADED

    return LoginResult(
        _user_from(identity, resolve_for_user(identity.username, identity.role, identity)),
        detail,
        must_change,
    )


def _user_from(identity: directory.UserIdentity, grant) -> CurrentUser:
    """`CurrentUser` 的唯一构造点。登录腿与令牌腿共用，避免两处的 grant 语义劈叉。"""
    return CurrentUser(
        username=identity.username,
        display_name=identity.display_name,
        role=identity.role,
        grant=grant,
    )
```

成功路径的 `audit_detail` 是空串：`main.py` 只在它非空时调 `record_login_event`，成功事件继续走既有 `_audit(user, "LOGIN")`（SEC-A-006：既有成功面一字不动）。

并在 `main.py` 的登录处理里：`detail` 非空才 `record_login_event(...)`，成功则沿用既有 `_audit(user, "LOGIN")`（`SEC-A-006`：既有成功事件面一字不动）。

`_locked(record)` 是纯函数，放 `login_throttle.py`（Task 8）；本任务先就地定义：

```python
def _locked(record: user_store.CredentialRecord) -> bool:
    until = record.locked_until
    if not until:
        return False
    try:
        return datetime.now(timezone.utc) >= datetime.fromisoformat(until)
    except ValueError:
        return True  # 时间戳坏了 ⇒ 宁可当锁定，也不给一次免费的 Argon2 运算
```

`authenticate()` 保留原签名：`return authenticate_with_result(username, password).user`。

- [ ] **Step 4: `resolve_for_user` 改读身份对象**（`backend/app/identity/__init__.py:59-66`）

```python
def resolve_for_user(username: str, role: str, record: Any) -> FeishuGrant | None:
    """授予解析。`record` 是 directory.UserIdentity（SEC-A 后不再是从 USERS 里取的 dict）。
    用 getattr 而非 isinstance：身份类型由 directory 拥有，这里不该反过来依赖它。
    """
    from app.config import settings

    open_id = str(getattr(record, "feishu_open_id", "") or "")
    if not settings.feishu_permissions_enabled or not open_id:
        return None
    return get_resolver().resolve(username, role, open_id)
```

- [ ] **Step 5: 门与白名单依赖**（`backend/app/auth.py`）

```python
def _password_change_required(username: str) -> bool:
    record = user_store.get_record(username)
    return bool(record and record.must_change)


def require_user(authorization: Annotated[str | None, Header()] = None) -> CurrentUser:
    user = _user_from_token(authorization)          # Task 6 在这里加 cv 比对
    if _password_change_required(user.username):
        # 展示面中文、审计面枚举 token，与 enforce_permission 既有的
        # AUTHORIZATION/DENIED/missing_permission=X 同构（规格 §9.1 两栏）。
        _record_event(
            username=user.username, role=user.role, action="AUTHORIZATION",
            status="DENIED", detail="password_change_required",
        )
        raise HTTPException(status_code=403, detail="当前账号需先修改口令")
    return user


def require_user_pending_password(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """`must_change=1` 期间仍可访问的两条腿的依赖：改密与 /me。"""
    return _user_from_token(authorization)
```

`main.py` 的 `GET /api/auth/me` 改用 `require_user_pending_password`；`Task 7` 的改密端点也用同一个依赖。其余已鉴权端点**不改一行**——它们继续依赖 `require_user`，门自然生效，这正是 §8.4 选择依赖注入而非中间件的原因。

- [ ] **Step 6: 删除 `USERS` 与 `_password_digest`，并改写受影响测试**

- 删 `app/auth.py:69-103`（含那句"Passwords are stored as SHA-256 digests…"注释，它描述的是将被移除的东西）与 `:173-174`。
- 删 `tests/test_user_directory_contract.py::TransitionalConsistencyPin`。
- `tests/test_feishu_identity_contract.py:601`（断言 `record is auth.USERS[username]`）改为断言 `getattr(record, "feishu_open_id", None)` 命中；`:1707-1726` 的"往字典塞 open_id"改为：

```python
        identities = dict(directory.identities())
        identities["viewer"] = directory.UserIdentity(
            username="viewer", display_name="只读访客演示账号", role="VIEWER",
            feishu_open_id="ou_contract_probe",
        )
        with directory.override_identities(identities):
            ...  # 原有断言与缩进保持不变
```

- [ ] **Step 7: 会话级 demo 凭据 seed**

新建 `backend/tests/sec_a_seed.py`。**不放 `conftest.py`、不用 `tests/helpers.py`**：`backend/tests/` 没有 `__init__.py`，`from tests.conftest import X` 这种写法根本 import 不到；而 `tests/helpers.py` 这个名字在本仓库有过一次被脚本覆写的事故（项目记忆里有记录），另起一个专用文件名比复用更便宜。

```python
"""SEC-A 测试地基：既有登录用例的口令字面量不改，脚下换成 argon2id 行。

Argon2 是内存硬哈希：每用例重算会把套件拖成分钟级，所以整个会话只算 5 次。
`SEED_RECORD` 让"只种了一次"这件事可断言（SECA-24），且计数器住在测试侧，
生产代码不为用户形状服务。
"""

from __future__ import annotations

DEMO_TEST_CREDENTIALS: dict[str, str] = {
    "admin": "admin123",
    "sales01": "sales123",
    "hr01": "hr123",
    "user": "user123",
    "viewer": "viewer123",
}

SEED_RECORD: list[str] = []


def seed_demo_credentials() -> None:
    from app import user_store

    user_store.ensure_user_credentials_schema()
    for username, password in DEMO_TEST_CREDENTIALS.items():
        if user_store.get_record(username) is None:
            user_store.create_argon2(username, plain_password=password, must_change=False)
            SEED_RECORD.append(username)
```

`backend/tests/conftest.py` 里新增一个 fixture，放在 `isolated_llm_ledger` 之后并依赖它以固定顺序（`sec_a_seed` 与 conftest 同目录，直接顶层 import）：

```python
from sec_a_seed import seed_demo_credentials
```

```python
@pytest.fixture(scope="session", autouse=True)
def seeded_demo_credentials(isolated_llm_ledger):
    seed_demo_credentials()
    yield
```

- [ ] **Step 8: 企业形态的 HTTP 面半边**（SECA-04b 另一半，追加到 `SourceRemovalTests`）

```python
    def test_enterprise_mode_with_no_credentials_fails_closed_rather_than_500(self):
        """零账号 + 零凭据 ⇒ 统一 401。500 会把"配置未就绪"泄成一条堆栈。"""
        from fastapi.testclient import TestClient

        from app.main import app

        _fresh_db(self)
        with mock.patch.object(type(auth.settings), "security_enterprise_mode", True), \
                directory.override_identities({}):
            response = TestClient(app).post(
                "/api/auth/login", json={"username": "admin", "password": "admin123"}
            )
        self.assertEqual(401, response.status_code)
        self.assertEqual("用户名或密码错误", response.json()["detail"])  # 展示面中文；审计面才是 invalid_credentials
        self.assertNotIn("traceback", response.text.lower())

    def test_the_session_seed_happened_exactly_once(self):
        """SECA-24 的性能半边：seed 次数 ≤ 身份数，不随用例数增长。"""
        from sec_a_seed import SEED_RECORD

        self.assertEqual(5, len(SEED_RECORD))
        self.assertEqual(5, len(set(SEED_RECORD)))
```

- [ ] **Step 9: 定向门 + 全套件**

```bash
cd /e/xiangmu/rag/backend
python -m pytest tests/test_authentication_leg_contract.py tests/test_credentials_contract.py tests/test_user_directory_contract.py tests/test_rbac_contract.py -q
python -m pytest -q
```
Expected: 定向门全绿；全套件绿（含 8 处既有登录调用点、`test_llm_egress_guard.py` 的 D6 豁免面不变）。记下 collected 数供 Task 10 对账。

- [ ] **Step 10: 快照 + 台账**

```bash
cd /e/xiangmu/rag/backend && cp -r app ../.superpowers/sdd/SECURITY_A_PLAN/snap-task5-app
cp tests/conftest.py ../.superpowers/sdd/SECURITY_A_PLAN/snap-task5-conftest.py
echo "- Ruling: 登录成功面不再调 record_login_event（沿用既有 _audit(user,'LOGIN')）；只有三种 detail 枚举值经 record_login_event 落 DENIED/降级事件。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
echo "- Ruling: resolve_for_user 用 getattr(record,'feishu_open_id') 读身份对象，不引入 isinstance 依赖。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
```

---

## Task 6: 令牌生命周期（`cv` claim、revocation、`must_change` 端点覆盖门）

**Files:**
- Modify: `backend/app/auth.py`（`issue_token` 加 `cv`；`_user_from_token` 加比对与 `账号不存在` 并入）
- Modify: `backend/app/main.py`（`/api/auth/login` 与 `/api/auth/me` 各加一枚 additive 键）
- Modify: `backend/tests/test_authentication_leg_contract.py`（追加令牌面）
- Test: `backend/tests/test_password_lifecycle_contract.py`（新建，先放令牌撤销用例；Task 7 续写端点用例）

**Interfaces:**
- Consumes: `user_store.get_record`；`credentials.ALGORITHM_*`
- Produces:
  ```python
  CREDENTIAL_VERSION_CLAIM = "cv"
  def issue_token(user: CurrentUser) -> str           # payload 多一枚 cv
  def _user_from_token(authorization: str | None) -> CurrentUser   # 验签 → 身份 → 凭据 → cv
  ```
  响应面 additive 键：`POST /api/auth/login` 与 `GET /api/auth/me` 各多 `password_change_required: bool`。

- [ ] **Step 1: 写失败的测试**（`backend/tests/test_password_lifecycle_contract.py`）

```python
from __future__ import annotations

import hashlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import auth, credentials, directory, user_store  # noqa: E402
from app.main import app  # noqa: E402
from sec_a_seed import seed_demo_credentials  # noqa: E402


def _identity(username: str, *, role: str = "VIEWER", enabled: bool = True,
              feishu_open_id: str | None = None) -> directory.UserIdentity:
    return directory.UserIdentity(
        username=username, display_name=username.title(), role=role,
        enabled=enabled, feishu_open_id=feishu_open_id,
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_legacy_admin(store) -> None:
    store.import_legacy_digest(
        "admin", hashlib.sha256(b"admin123").hexdigest(), must_change=True
    )


class _ClientCase(unittest.TestCase):
    """打 HTTP 面的用例共用地基：TestClient + 已被会话 seed 过的凭据表。"""

    def setUp(self):
        self.client = TestClient(app)
        user_store.ensure_user_credentials_schema()
        seed_demo_credentials()

    def _admin_headers(self) -> dict[str, str]:
        login = self.client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123"}
        )
        return _bearer(login.json()["access_token"])


class TokenRevocationTests(_ClientCase):
    def setUp(self):
        self.client = TestClient(app)
        user_store.ensure_user_credentials_schema()
        user_store.create_argon2("revoker", plain_password="a-good-password 123456", must_change=False)
        self.identity = _identity("revoker")
        with auth.directory.override_identities({"revoker": self.identity}):
            self.token = auth.issue_token(auth._user_from(self.identity, None))

    def test_a_bumped_version_invalidates_the_previously_issued_token(self):
        """SECA-09：改密即废 token，不等 exp。"""
        with auth.directory.override_identities({"revoker": self.identity}):
            self.assertIsInstance(auth.require_user(f"Bearer {self.token}"), auth.CurrentUser)
            user_store.set_password_argon2(
                "revoker", plain_password="another-good-password 123", must_change=False
            )
            with self.assertRaises(HTTPException) as raised:
                auth.require_user(f"Bearer {self.token}")
        self.assertEqual(401, raised.exception.status_code)
        self.assertEqual("无效登录凭证", raised.exception.detail)

    def test_a_pre_seca_token_without_cv_is_rejected_not_allowed(self):
        """SECA-09b：这是 M17 的靶子——"兼容旧 token"的放行分支必须撞红。"""
        import jwt as pyjwt

        from app.config import settings

        legacy = pyjwt.encode(
            {"sub": "revoker", "role": "VIEWER", "iss": "yaoke",
             "exp": 2 ** 31 - 1, "iat": 1},
            settings.jwt_secret,
            algorithm="HS256",
        )
        with auth.directory.override_identities({"revoker": self.identity}):
            with self.assertRaises(HTTPException) as raised:
                auth.require_user(f"Bearer {legacy}")
        self.assertEqual(401, raised.exception.status_code)
        self.assertEqual("无效登录凭证", raised.exception.detail)

    def test_the_removed_account_specificity_message_is_gone_from_the_token_face(self):
        """§9.1：「账号不存在」并入「无效登录凭证」，不再泄露存在性。"""
        with auth.directory.override_identities({}):
            with self.assertRaises(HTTPException) as raised:
                auth.require_user(f"Bearer {self.token}")
        self.assertEqual("无效登录凭证", raised.exception.detail)


class LoginFaceKeyTests(unittest.TestCase):
    def test_login_and_me_carry_exactly_one_new_key(self):
        """规格 §11：本版唯一一处响应面键集合变化。"""
        response = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual({"access_token", "token_type", "user", "password_change_required"}, set(body))
        self.assertIsInstance(body["password_change_required"], bool)
        me = self.client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
        )
        self.assertIn("password_change_required", me.json())
        self.assertNotIn("grant", me.json())  # 既有脱敏事实不得被顶掉
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_password_lifecycle_contract.py -q
```
Expected: 红在 `KeyError/AttributeError`（`cv` 尚未签发、`password_change_required` 尚未出现）。

- [ ] **Step 3: 写实现**（`backend/app/auth.py`）

```python
CREDENTIAL_VERSION_CLAIM = "cv"


def issue_token(user: CurrentUser) -> str:
    now = datetime.now(timezone.utc)
    record = user_store.get_record(user.username)
    payload = {
        "sub": user.username,
        "name": user.display_name,
        "role": user.role,
        "access_role": user.access_role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_expire_hours)).timestamp()),
        "iss": "yaoke",
        CREDENTIAL_VERSION_CLAIM: int(record.credentials_version) if record else 0,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _user_from_token(authorization: str | None) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        payload = jwt.decode(
            authorization[7:].strip(), settings.jwt_secret,
            algorithms=["HS256"], issuer="yaoke",
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="无效登录凭证") from exc

    username = str(payload.get("sub", ""))
    identity = directory.get_identity(username)
    record = user_store.get_record(username)
    if identity is None or not identity.enabled or record is None:
        # 「账号不存在」并入通用文案（§9.1）：原 `auth.py:230` 的单列 detail 是一条存在性指纹。
        raise HTTPException(status_code=401, detail="无效登录凭证")
    # 读表判定，不信 claim 值；缺 claim 即视为不符（SECA-09b，禁止 None 放行）。
    claimed = payload.get(CREDENTIAL_VERSION_CLAIM)
    if not isinstance(claimed, int) or claimed != record.credentials_version:
        raise HTTPException(status_code=401, detail="无效登录凭证")
    return _user_from(identity, resolve_for_user(identity.username, identity.role, identity))
```

`require_user`（Task 5 定义）改为先 `_user_from_token` 再过 must_change 门；`require_user_pending_password` 只走 `_user_from_token`。`issue_token` 里 `record is None ⇒ cv=0` 不是"随便给个值"：0 与表内任何真实版本都不等，等于"这枚 token 一签发就死"，正是无凭据身份应有的行为，同时保持 `CurrentUser` 构造面不因身份类型分裂成两条路径。

- [ ] **Step 4: `main.py` 两处 additive 键**

登录响应：`"password_change_required": result.password_change_required`（来自 Task 5 的 `LoginResult`，**不**在响应处重新查表——两处判定早晚劈叉）；`/api/auth/me`：`{**user.model_dump(), "password_change_required": _password_change_required(user.username)}`。

- [ ] **Step 5: 补 `must_change` 端点覆盖枚举门**（SECA-10，追加到 `test_password_lifecycle_contract.py`）

```python
class MustChangeGateCoverageTests(unittest.TestCase):
    """门必须由路由表自证覆盖，不靠手写清单——新增端点忘了登记就直接红。"""

    # Task 6 时改密端点还不存在，白名单只有 /me 一项；Task 7 落地改密端点时必须
    # 同时把本集合扩成两项——这条断言会在漏扩时立刻红（多一条也红）。
    WHITELIST = {"GET /api/auth/me"}
    PARAM_SAMPLES = {
        "conversation_id": "conv-nonexistent",
        "message_id": "msg-nonexistent",
        "document_id": "doc-nonexistent",
        "kb_id": "kb_public",
        "knowledge_base_id": "kb_public",
        "run_id": "run-nonexistent",
        "trace_id": "trace-nonexistent",
        "job_id": "job-nonexistent",
    }

    def test_every_authenticated_route_is_gated_or_whitelisted(self):
        authenticated = _routes_using(auth.require_user) | _routes_using(auth.require_permission)
        pending = _routes_using(auth.require_user_pending_password)
        self.assertEqual(self.WHITELIST, pending)
        unattended = {
            key for key in authenticated - pending
            if not self._gated(key)
        }
        self.assertEqual(set(), unattended)

    def _gated(self, route_key: str) -> bool:
        client = TestClient(app)
        user_store.ensure_user_credentials_schema()
        user_store.create_argon2("gated", plain_password="a-good-password 123456", must_change=True)
        identity = _identity("gated", role="ADMIN")
        with auth.directory.override_identities({"gated": identity}):
            token = auth.issue_token(auth._user_from(identity, None))
            method, path = route_key.split(" ", 1)
            url = path
            for name, sample in self.PARAM_SAMPLES.items():
                url = url.replace("{" + name + "}", sample)
            if "{" in url:
                self.fail(f"新增端点带未登记的 path 参数，请把样例加进 PARAM_SAMPLES：{route_key}")
            response = client.request(method, url, headers={"Authorization": f"Bearer {token}"})
        return (
            response.status_code == 403
            and response.json().get("detail") == "当前账号需先修改口令"
        )
```

```python
def _route_key(route) -> str:
    methods = getattr(route, "methods", set()) or set()
    return f"{sorted(methods & {'GET', 'POST', 'PUT', 'DELETE'})[0]} {route.path}"


def _uses_dependency(dependant, target) -> bool:
    for sub in dependant.dependencies:
        if sub.call is target or _uses_dependency(sub, target):
            return True
    return False


def _routes_using(target) -> set[str]:
    """递归遍历 FastAPI 依赖树，返回"这条路由经过该依赖"的端点集合。"""
    from fastapi.routing import APIRoute

    hits: set[str] = set()
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None or not isinstance(route, APIRoute):
            continue
        if _uses_dependency(dependant, target):
            hits.add(_route_key(route))
    return hits
```

判定形状：**漏一条即红，多一条也红**。命中不到任何依赖的路由（`/api/health`、`/api/ready`、静态资源）天然不进 authenticated 集合，所以不需要维护豁免清单；`PARAM_SAMPLES` 未登记的 path 参数用 `self.fail(...)` 主动要求登记，而不是猜一个值过去。这条测试会在未来任何人新增端点时自动扩大覆盖面，而不是等下一次评审手工数。

- [ ] **Step 6: 定向门 + 快照**

```bash
cd /e/xiangmu/rag/backend
python -m pytest tests/test_password_lifecycle_contract.py tests/test_authentication_leg_contract.py tests/test_typesafe_api_runtime.py tests/test_rbac_contract.py -q
python -m pytest -q
cp -r app ../.superpowers/sdd/SECURITY_A_PLAN/snap-task6-app
echo "- Ruling: issue_token 在无凭据行时签 cv=0（一签发即死），不另开第二条构造路径。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
echo "- Ruling: must_change 门覆盖面由路由表枚举生成；新端点带未登记 path 参数时用例主动 fail 并要求登记样例。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
```
Expected: 两条 `python -m pytest` 全绿，且 `test_typesafe_api_runtime.py` 的 `/api/query` 键集合钉未受影响。

---

## Task 7: 改密 / 管理员重置端点与 CLI

**Files:**
- Create: `backend/app/cli.py`
- Modify: `backend/app/main.py`（两个新端点 + 请求模型）
- Modify: `backend/app/auth.py`（`validate_new_password`、`provision_credentials`）
- Test: `backend/tests/test_password_lifecycle_contract.py`（续写）

**Interfaces:**
- Consumes: `user_store.create_argon2` / `set_password_argon2` / `get_record`；`directory.get_identity`；`auth.require_user_pending_password`；`auth._password_change_required`
- Produces:
  ```python
  # app/auth.py
  def validate_new_password(username: str, new_password: str) -> str | None   # 返回错误原因，None=通过
  def provision_credentials(username: str, *, plain_password: str, must_change: bool) -> int
      # 表内无行 → create_argon2；有行 → set_password_argon2。CLI 与管理员重置共用的一条写路径。
  # app/cli.py
  def main(argv: list[str] | None = None) -> int
  PASSWORD_ENV_VAR = "CREDENTIALS_PASSWORD"
  ```
  新端点：`POST /api/auth/password/change`、`POST /api/admin/users/{username}/password/reset`（权限 `system:operate`，**不新增权限名**）。

- [ ] **Step 1: 写失败的测试**（追加到 `test_password_lifecycle_contract.py`）

```python
from app import cli  # 追加 import（Task 7 起本文件才用得到）


class PasswordPolicyTests(_ClientCase):
    def test_short_passwords_and_username_echo_are_rejected_with_422(self):
        """§8.8：422 是输入校验，403 是权限。混用会污染既有 RBAC 语义面。"""
        body = {"current_password": "admin123", "new_password": "abc"}
        response = self.client.post(
            "/api/auth/password/change", json=body, headers=self._admin_headers()
        )
        self.assertEqual(422, response.status_code)
        for candidate in ("admin", "ADMIN", "AdMiN"):
            self.assertIsNotNone(auth.validate_new_password("admin", candidate))
        self.assertIsNone(auth.validate_new_password("admin", "a-good-new-password 123"))

    def test_policy_accepts_a_12_char_and_rejects_a_129_char_password(self):
        self.assertIsNone(auth.validate_new_password("someone", "l" * 12))
        self.assertIsNotNone(auth.validate_new_password("someone", "l" * 129))


class SelfServiceChangeTests(_ClientCase):
    def test_changing_password_logs_in_clears_the_gate_and_kills_old_tokens(self):
        """SECA-03 半边 B：升级路径的终态是"改完密就能正常用"。"""
        _seed_legacy_admin(user_store, auth)
        login = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        self.assertTrue(login.json()["password_change_required"])
        blocked = self.client.get("/api/knowledge-bases", headers=_bearer(login.json()["access_token"]))
        self.assertEqual((403, "当前账号需先修改口令"), (blocked.status_code, blocked.json()["detail"]))

        changed = self.client.post(
            "/api/auth/password/change",
            json={"current_password": "admin123", "new_password": "a-good-new-password 123"},
            headers=_bearer(login.json()["access_token"]),
        )
        self.assertEqual(200, changed.status_code)
        self.assertEqual({"changed": True}, changed.json())
        self.assertEqual(
            credentials.ALGORITHM_ARGON2ID, user_store.get_record("admin").algorithm
        )
        self.assertFalse(user_store.get_record("admin").must_change)
        self.assertEqual(
            200,
            self.client.get(
                "/api/knowledge-bases", headers=_bearer(login.json()["access_token"])
            ).status_code,
        )

    def test_changing_requires_the_current_password(self):
        login = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        response = self.client.post(
            "/api/auth/password/change",
            json={"current_password": "not-my-password 123", "new_password": "a-good-new-password 123"},
            headers=_bearer(login.json()["access_token"]),
        )
        self.assertEqual(401, response.status_code)
        self.assertEqual("用户名或密码错误", response.json()["detail"])
        # 展示面是中文文案，审计面是枚举 token（规格 §9.1 的两栏模型）。
        from app.audit import recent_events

        self.assertEqual("invalid_credentials", recent_events(limit=1)[0]["detail"])


class AdminResetTests(_ClientCase):
    def test_reset_requires_the_operate_capability(self):
        viewer = self.client.post("/api/auth/login", json={"username": "viewer", "password": "viewer123"})
        response = self.client.post(
            "/api/admin/users/hr01/password/reset",
            json={"new_password": "a-good-new-password 123"},
            headers=_bearer(viewer.json()["access_token"]),
        )
        self.assertEqual(403, response.status_code)
        self.assertIn("system:operate", response.json()["detail"])

    def test_admin_reset_clears_a_stale_lock_in_the_same_transaction(self):
        """SECA-12：reset 之后用户仍被旧 lock 挡住，是一条必被观测到的事故形态。"""
        user_store.create_argon2("hr01", plain_password="hr123", must_change=False)
        user_store.record_login_failure("hr01", max_attempts=1, lock_seconds=900)
        self.assertIsNotNone(user_store.get_record("hr01").locked_until)
        admin = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        response = self.client.post(
            "/api/admin/users/hr01/password/reset",
            json={"new_password": "a-good-new-password 123"},
            headers=_bearer(admin.json()["access_token"]),
        )
        self.assertEqual(200, response.status_code)
        record = user_store.get_record("hr01")
        self.assertIsNone(record.locked_until)
        self.assertEqual(0, record.failed_attempts)
        self.assertTrue(record.must_change)
        self.assertEqual(2, record.credentials_version)
        login = self.client.post("/api/auth/login", json={"username": "hr01", "password": "a-good-new-password 123"})
        self.assertEqual(200, login.status_code)
        self.assertTrue(login.json()["password_change_required"])


class CliTests(_ClientCase):
    def test_bootstrap_requires_a_preexisting_identity_and_never_creates_one(self):
        """SEC-A-010：bootstrap 只写凭据，身份文件不因 CLI 而改变。"""
        before = directory.ENTERPRISE_IDENTITIES_FILE.read_text(encoding="utf-8")
        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: "a-good-new-password 123"}):
            self.assertEqual(2, cli.main(["credentials", "bootstrap-admin", "--username", "ghost"]))
        self.assertIsNone(user_store.get_record("ghost"))
        self.assertEqual(before, directory.ENTERPRISE_IDENTITIES_FILE.read_text(encoding="utf-8"))

    def test_the_cli_never_accepts_a_password_on_argv(self):
        """SECA-02：argv 会被 ps 与 shell history 观察到。"""
        parser = cli.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                ["credentials", "bootstrap-admin", "--username", "admin", "--password", "x"]
            )

    def test_migration_status_reports_the_legacy_count(self):
        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: "a-good-new-password 123"}):
            self.assertEqual(0, cli.main(["credentials", "migration-status"]))
```

`test_the_cli_never_accepts_a_password_on_argv` 用 `assertRaises(SystemExit)` 而不是翻 `--help` 文本：argparse 对未定义选项正是 `SystemExit`，而 help 文本会随描述措辞漂移（V2.3 里"用文本钉行为"放过一次真缺陷，不再重复）。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_password_lifecycle_contract.py -q
```
Expected: `ModuleNotFoundError: No module named 'app.cli'` + 两条 404（端点不存在）。

- [ ] **Step 3: 实现策略与写路径**（`backend/app/auth.py`）

```python
_MIN_PASSWORD_LENGTH = 12
_MAX_PASSWORD_LENGTH = 128   # 与 LoginRequest 的上限同值：一处事实，两处引用会漂


def validate_new_password(username: str, new_password: str) -> str | None:
    if not _MIN_PASSWORD_LENGTH <= len(new_password) <= _MAX_PASSWORD_LENGTH:
        return "新口令长度需在 12 到 128 个字符之间"
    if new_password.casefold() == str(username).casefold():
        return "新口令不得与账号名相同"
    return None


def provision_credentials(username: str, *, plain_password: str, must_change: bool) -> int:
    """唯一一条"把一个新口令落成可用凭据"的路径（CLI / 管理员重置 / fixture 共用）。

    只产 argon2id：这里没有任何参数能让它产出别的算法（SEC-A-001）。
    """
    if user_store.get_record(username) is None:
        return user_store.create_argon2(username, plain_password=plain_password, must_change=must_change)
    return user_store.set_password_argon2(username, plain_password=plain_password, must_change=must_change)
```

- [ ] **Step 4: 两个端点**（`backend/app/main.py`）

```python
class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class AdminPasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=12, max_length=128)


@app.post("/api/auth/password/change")
def change_password(
    request: PasswordChangeRequest,
    user: CurrentUser = Depends(require_user_pending_password),
):
    reason = validate_new_password(user.username, request.new_password)
    if reason:
        raise HTTPException(status_code=422, detail=reason)
    result = authenticate_with_result(user.username, request.current_password)
    if result.user is None:
        # 改密端点带旧口令校验 ⇒ 它与登录是同一个爆破面，共用同一份 throttle/lock 状态。
        record_login_event(username=user.username, detail=result.audit_detail)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    provision_credentials(
        user.username, plain_password=request.new_password, must_change=False
    )
    record_event(username=user.username, role=user.role, action="PASSWORD",
                 status="SUCCESS", detail="password_changed")
    return {"changed": True}


@app.post("/api/admin/users/{username}/password/reset")
def admin_reset_password(
    username: str,
    request: AdminPasswordResetRequest,
    user: CurrentUser = Depends(require_permission("system:operate")),
):
    reason = validate_new_password(username, request.new_password)
    if reason:
        raise HTTPException(status_code=422, detail=reason)
    if directory.get_identity(username) is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    provision_credentials(username, plain_password=request.new_password, must_change=True)
    record_event(username=user.username, role=user.role, action="PASSWORD",
                 status="SUCCESS", detail="password_reset_by_admin")
    return {"reset": True, "must_change": True}
```

两处刻意形状：① 重置端点的 404 用「账号不存在」——那是**已鉴权管理员**面对的资源不存在，不构成对外的枚举面（登录腿才是），所以不改；② 两个响应都**不回显口令**，也不回显 hash 或长度。

同一改动里必须把 Task 6 的 `MustChangeGateCoverageTests.WHITELIST` 扩成 `{"POST /api/auth/password/change", "GET /api/auth/me"}`——那枚门的设计就是"多一条也红"，端点加了而白名单不加会立刻红，这是特性不是回归。

- [ ] **Step 5: 写 CLI**（`backend/app/cli.py`）

```python
"""凭据运维面（规格 §8.6/§8.7）。口令只从环境变量读，绝不进 argv。"""

from __future__ import annotations

import argparse
import os
import sys

from app import auth, credentials_migration, directory, user_store

PASSWORD_ENV_VAR = "CREDENTIALS_PASSWORD"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    credentials_group = parser.add_subparsers(dest="command", required=True)
    actions = credentials_group.add_parser("credentials").add_subparsers(
        dest="action", required=True
    )
    bootstrap = actions.add_parser("bootstrap-admin")
    bootstrap.add_argument("--username", required=True)
    reset = actions.add_parser("reset")
    reset.add_argument("--username", required=True)
    actions.add_parser("migration-status")
    return parser


def _password_from_env() -> str:
    value = os.environ.get(PASSWORD_ENV_VAR, "")
    if len(value) < 12:
        raise SystemExit(f"{PASSWORD_ENV_VAR} 未设置或不满足 12 字符下限（口令不得出现在命令行参数上）")
    return value


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    user_store.ensure_user_credentials_schema()
    if args.action == "migration-status":
        status = credentials_migration.status()
        print(f"legacy_count={status.legacy_count} argon2id_count={status.argon2id_count}")
        for row in status.accounts:
            print(
                f"{row.username}\t{row.algorithm}\tv{row.credentials_version}"
                f"\tmust_change={int(row.must_change)}\tlocked={row.locked_until or '-'}"
            )
        return 0

    identity = directory.get_identity(args.username)
    if identity is None:
        # bootstrap 不创建身份：身份唯一真源是配置文件，CLI 顺手建号会造出第二个真源。
        print(f"身份不存在：{args.username}（请先写入 config/users.json）", file=sys.stderr)
        return 2
    reason = auth.validate_new_password(args.username, (os.environ.get(PASSWORD_ENV_VAR) or ""))
    if reason:
        print(reason, file=sys.stderr)
        return 2
    password = _password_from_env()
    must_change = args.action == "reset"
    version = auth.provision_credentials(
        args.username, plain_password=password, must_change=must_change
    )
    os.environ.pop(PASSWORD_ENV_VAR, None)
    auth.record_event(
        username=args.username,
        role=identity.role,
        action="PASSWORD",
        status="SUCCESS",
        detail="credential_bootstrap" if args.action == "bootstrap-admin" else "password_reset_by_admin",
    )
    print(f"{args.username}: algorithm={credentials.ALGORITHM_ARGON2ID} version={version}")
    return 0


if __name__ == "__main__":
    main()
```

`_password_from_env()` 在 `main()` 里被绕过的写法（`reason` 校验先读 env 再调 `_password_from_env`）不是笔误留给实现者：先校验长度上限以下的最短门槛、再取值，是为了让"env 没设"和"env 太短"给出同一句可执行提示，且不在错误分支里打印口令。若实现时觉得绕，改成"`_password_from_env` 内部做长度校验并 `SystemExit`"——但**不许**把口令写进异常消息或日志。

- [ ] **Step 6: 跑测试 + 手动过一遍 CLI**

```bash
cd /e/xiangmu/rag/backend
python -m pytest tests/test_password_lifecycle_contract.py -q
CONVERSATION_DB_PATH=/tmp/sec-a-cli.db CREDENTIALS_PASSWORD='an-operator-password 123' python -m app.cli credentials migration-status
```
Expected: 测试绿；CLI 打印 `legacy_count=0 argon2id_count=0`。

- [ ] **Step 7: 全套件 + 快照**

```bash
cd /e/xiangmu/rag/backend && python -m pytest -q
cp -r app ../.superpowers/sdd/SECURITY_A_PLAN/snap-task7-app
echo "- Ruling: 管理员重置端点对不存在身份保留 404「账号不存在」（已鉴权管理员面，非枚举面）。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
echo "- Ruling: CLI 口令只读 CREDENTIALS_PASSWORD，用完立即从 environ 弹出。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
```

---

## Task 8: 两层节流与容量护栏（`login_throttle.py` + 429 / 503）

**Files:**
- Create: `backend/app/login_throttle.py`
- Modify: `backend/app/auth.py`（`_locked` 迁出；登录腿接入 pre-hash 节流与容量翻译）
- Modify: `backend/app/main.py`（把 `PasswordCapacityError` 翻成 503、节流命中翻成 429）
- Modify: `backend/app/config.py`（四枚运维参数）
- Test: `backend/tests/test_authentication_leg_contract.py`（追加节流面）

**Interfaces:**
- Consumes: `credentials.argon2_slot` / `PasswordCapacityError`；`user_store.record_login_failure` / `clear_login_failures`
- Produces:
  ```python
  # app/login_throttle.py
  def client_ip_of(request) -> str                       # 只认 request.client.host
  def throttle_bucket(username: str, client_ip: str) -> str
  class PreHashThrottle:
      def allow(self, bucket: str, *, now: float | None = None) -> bool
      def reset(self) -> None
  pre_hash_throttle: PreHashThrottle                     # 进程内单例
  def is_locked(locked_until: str | None, *, now: datetime | None = None) -> bool
  ```

- [ ] **Step 1: 写失败的测试**（追加 `ThrottleLayerTests`）

```python
class ThrottleLayerTests(unittest.TestCase):
    def setUp(self):
        _fresh_db(self)
        user_store.create_argon2("admin", plain_password="a-good-password 123456", must_change=False)
        self.throttle = login_throttle.PreHashThrottle(window_seconds=60, max_attempts=3)

    def test_expensive_work_is_skipped_once_the_bucket_is_exhausted(self):
        """SECA-15：闸门在 Argon2 之前，否则认证面自己就是 DoS 面。"""
        bucket = login_throttle.throttle_bucket("admin", "10.0.0.9")
        for _ in range(3):
            self.assertTrue(self.throttle.allow(bucket))
        self.assertFalse(self.throttle.allow(bucket))
        with mock.patch.object(auth, "pre_hash_throttle", self.throttle):
            with mock.patch.object(credentials.hasher(), "verify") as verify:
                with self.assertRaises(auth.LoginThrottledError):
                    auth.authenticate_with_result("admin", "a-good-password 123456")
        verify.assert_not_called()

    def test_two_source_addresses_on_the_same_username_have_independent_buckets(self):
        """SECA-16a：M6（throttle 键去掉 ip）只能被这条直接断言杀掉。"""
        first = login_throttle.throttle_bucket("admin", "10.0.0.1")
        second = login_throttle.throttle_bucket("admin", "10.0.0.2")
        self.assertNotEqual(first, second)
        for _ in range(3):
            self.throttle.allow(first)
        self.assertFalse(self.throttle.allow(first))
        self.assertTrue(self.throttle.allow(second))

    def test_many_source_addresses_on_one_username_share_the_account_lock(self):
        """SECA-16b：账号级持久计数按 username，与 throttle 层正交。"""
        for ip in ("10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"):
            result = auth.authenticate_with_result("admin", "wrong-password 123456")
            self.assertIsNone(result.user)
        record = user_store.get_record("admin")
        self.assertGreaterEqual(record.failed_attempts, 4)
        self.assertIsNotNone(record.locked_until)
        self.assertFalse(login_throttle.is_locked(None))
        self.assertTrue(login_throttle.is_locked(record.locked_until))

    def test_a_successful_login_clears_the_persistent_counter(self):
        user_store.record_login_failure("admin", max_attempts=9, lock_seconds=900)
        self.assertTrue(auth.authenticate_with_result("admin", "a-good-password 123456").user)
        record = user_store.get_record("admin")
        self.assertEqual(0, record.failed_attempts)
        self.assertIsNone(record.locked_until)

    def test_the_capacity_gate_surfaces_as_a_capacity_error_not_a_denial(self):
        """503 ≠ 401：可用性事实不能被伪装成凭据结论。"""
        with mock.patch.object(
            credentials, "_SLOTS", threading.BoundedSemaphore(0)
        ):
            user_store.import_legacy_digest("gate", LEGACY_ADMIN, must_change=True)
            with self.assertRaises(credentials.PasswordCapacityError):
                auth.authenticate_with_result("gate", "admin123")


class LockedHttpFaceTests(unittest.TestCase):
    """M5 的靶子：锁定原因一旦渗到 HTTP 面，就是账号存在性枚举面（SECA-14 的 HTTP 半边）。"""

    def setUp(self):
        _fresh_db(self)
        user_store.create_argon2("admin", plain_password="a-good-password 123456", must_change=False)
        self.client = TestClient(app)

    def _login(self, username: str, password: str):
        return self.client.post("/api/auth/login", json={"username": username, "password": password})

    def test_locked_wrong_password_and_unknown_account_are_the_same_http_face(self):
        for _ in range(settings.account_max_failed_attempts):
            self._login("admin", "definitely-wrong 123456")
        locked = self._login("admin", "a-good-password 123456")   # 口令对，但账号已锁
        wrong = self._login("admin", "still-wrong 123456")
        unknown = self._login("nosuchaccount", "still-wrong 123456")
        faces = {(r.status_code, json.dumps(r.json(), sort_keys=True)) for r in (locked, wrong, unknown)}
        self.assertEqual(1, len(faces), faces)
        self.assertEqual(401, locked.status_code)
        self.assertNotIn("锁", json.dumps(locked.json(), ensure_ascii=False))

    def test_the_lock_reason_reaches_the_audit_face_only(self):
        for _ in range(settings.account_max_failed_attempts):
            self._login("admin", "definitely-wrong 123456")
        self._login("admin", "a-good-password 123456")
        from app.audit import recent_events

        details = [event["detail"] for event in recent_events(limit=3)]
        self.assertIn("AUTH_LOGIN_LOCKED", details)
```

`test_authentication_leg_contract.py` 的 import 段需要补 `import json`、`import threading` 与 `from fastapi.testclient import TestClient`、`from app.config import settings`（Task 8 起才用得到）。M5 之所以能被抓，全靠 `LockedHttpFaceTests` 这一条——腿级用例看不见 `main.py` 的文案分叉。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_authentication_leg_contract.py -q -k ThrottleLayer
```
Expected: `ModuleNotFoundError: No module named 'app.login_throttle'`。

- [ ] **Step 3: 写实现**（`backend/app/login_throttle.py`）

```python
"""pre-hash 节流（规格 §7.1/§7.2 的第一层）。

进程内、按 (username, client_ip) 分桶，只回答一件事：这次请求配不配消耗一次
内存硬哈希。账号级持久锁定是 user_store 的 failed_attempts/locked_until，两层
键不同、职责不同，合并成一枚必然丢掉两种保护之一。
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone


def client_ip_of(request) -> str:
    # 不信任 X-Forwarded-For：当前 compose 前置无 nginx，信任转发头等于白送伪装源。
    client = getattr(request, "client", None)
    return str(getattr(client, "host", "") or "unknown")


def throttle_bucket(username: str, client_ip: str) -> str:
    return f"{str(username).casefold()}|{client_ip}"


class LoginThrottled(Exception):
    """节流命中。调用方翻成 429，不是 401（还没做凭据判断）。"""


class PreHashThrottle:
    def __init__(self, *, window_seconds: int, max_attempts: int) -> None:
        self._window = float(window_seconds)
        self._max = int(max_attempts)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, bucket: str, *, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            hits = self._hits[bucket]
            while hits and moment - hits[0] > self._window:
                hits.popleft()
            if len(hits) >= self._max:
                return False
            hits.append(moment)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def is_locked(locked_until: str | None, *, now: datetime | None = None) -> bool:
    if not locked_until:
        return False
    try:
        moment = datetime.fromisoformat(str(locked_until))
    except ValueError:
        return True  # 时间戳坏了 ⇒ 宁可当锁定，也不白送一次昂贵运算
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) >= moment


pre_hash_throttle: PreHashThrottle | None = None


def configured_throttle() -> PreHashThrottle:
    global pre_hash_throttle
    from app.config import settings

    if pre_hash_throttle is None:
        pre_hash_throttle = PreHashThrottle(
            window_seconds=settings.login_throttle_window_seconds,
            max_attempts=settings.login_throttle_max_attempts,
        )
    return pre_hash_throttle
```

`config.py` 再补两枚**节流级**参数（另两枚账号级的已在 Task 5 落地；四枚都是可用性旋钮，**不含** m/t/p）：

```python
    login_throttle_window_seconds: int = 60
    login_throttle_max_attempts: int = 10
```

- [ ] **Step 4: 接进登录腿**（`backend/app/auth.py`）

在 `authenticate_with_result` 最前面加：

```python
class LoginThrottledError(RuntimeError):
    """配翻译；不是凭据结论（main.py 翻成 429）。"""


def authenticate_with_result(username: str, password: str, *, client_ip: str = "") -> LoginResult:
    bucket = login_throttle.throttle_bucket(username, client_ip)
    if not login_throttle.configured_throttle().allow(bucket):
        raise LoginThrottledError(bucket)
    ...  # 其余保持 Task 5 的顺序；_locked(...) 换成 login_throttle.is_locked(record.locked_until)
```

`main.py`：登录端点传 `client_ip=login_throttle.client_ip_of(request)`（因此需要 `request: Request` 形参），并把 `LoginThrottledError → 429`、`PasswordCapacityError → 503` 各加一枚 `except`；两条 detail 文案都不得提到账号是否存在。

- [ ] **Step 5: 跑测试 + 全套件 + 快照**

```bash
cd /e/xiangmu/rag/backend
python -m pytest tests/test_authentication_leg_contract.py -q
python -m pytest -q
cp -r app ../.superpowers/sdd/SECURITY_A_PLAN/snap-task8-app
echo "- Ruling: 429（节流）与 503（容量）都在身份查找之前判定，因此不构成账号存在性枚举面。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
```

---

## Task 9: secret 卫生（脱敏两域 + 启动守卫 + 扫描门）

**Files:**
- Create: `backend/app/security_startup.py`
- Modify: `backend/app/security.py`（新增 `redact_for_persistence`，**不动** `redact_secrets`）
- Modify: `backend/app/audit.py:43,59`、`backend/app/agent_trace.py:73,91`（落盘面切换）
- Modify: `backend/app/config.py`（`cors_allow_origins`）
- Modify: `backend/app/main.py:77-83`（CORS env 化）、`main.py:53-68`（lifespan 第三道守卫）
- Modify: `backend/.env.example`
- Modify: `backend/tests/test_branding_contract.py:32`
- Test: `backend/tests/test_secret_hygiene_contract.py`（新建）

**Interfaces:**
- Produces:
  ```python
  # app/security.py
  PERSISTENCE_SENSITIVE_KEYS: frozenset[str]
  def redact_for_persistence(value: Any) -> Any
  # app/security_startup.py
  DEFAULT_JWT_SECRET = "change-me-before-production-yaoke-demo-secret"
  class SecurityStartupError(RuntimeError): ...
  def evaluate_startup_guards(*, enterprise_mode: bool, jwt_secret: str, cors_allow_origins: str) -> list[str]
  def assert_startup_safe() -> None      # violations 非空 ⇒ raise SecurityStartupError
  ```
- Consumes: `settings.security_enterprise_mode`（Task 4）、`settings.cors_allow_origins`（本任务）

- [ ] **Step 1: 写失败的测试**（`backend/tests/test_secret_hygiene_contract.py`）

```python
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import security, security_startup  # noqa: E402

NOT_SECRETS = ("input_tokens", "output_tokens", "num_sources", "total_tokens", "token_type")
SECRETS = ("password", "password_hash", "access_token", "refresh_token",
           "authorization", "api_key", "app_secret", "tenant_access_token")


def test_persistence_redaction_kills_sensitive_keys_by_exact_name():
    payload = {key: "sensitive-value" for key in SECRETS}
    redacted = security.redact_for_persistence(payload)
    assert all(redacted[key] == security.REDACTED for key in SECRETS), redacted


def test_persistence_redaction_does_not_collateral_damage_observability_keys():
    """SECA-17 的反方向：子串匹配 `token` 会顺手抹掉 usage 计数，那等于砸掉 observability 契约。"""
    payload = {"input_tokens": 12, "output_tokens": 34, "num_sources": 5,
               "total_tokens": 46, "token_type": "bearer"}
    assert payload == security.redact_for_persistence(payload)


def redact_secrets_semantics_are_unchanged():
    """既有 28 处调用点的响应面语义一字不动（SEC-A-006）。"""
    assert security.redact_secrets({"access_token": "keep-me"}) == {"access_token": "keep-me"}
    assert "Bearer [REDACTED]" in security.redact_secrets("header: Bearer abc.def.ghi")


def test_user_store_is_never_passed_through_a_redactor():
    """授权凭据库 ≠ 遥测面：把 redactor 罩到写凭据那一层，写进去的 hash 会被抹成占位符，
    下一次登录必失败（M9 就是这条）。判据是"持久层 import 里没有它"。"""
    source = (BACKEND_DIR / "app" / "user_store.py").read_text(encoding="utf-8")
    assert "redact_for_persistence" not in source
    assert "from app.security import" not in source


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        (dict(enterprise_mode=True, jwt_secret=security_startup.DEFAULT_JWT_SECRET,
              cors_allow_origins="http://localhost:3000"), 2),
        (dict(enterprise_mode=True, jwt_secret="x" * 48, cors_allow_origins="https://kb.example"), 0),
        (dict(enterprise_mode=False, jwt_secret=security_startup.DEFAULT_JWT_SECRET,
              cors_allow_origins=""), 0),
        (dict(enterprise_mode=True, jwt_secret=security_startup.DEFAULT_JWT_SECRET,
              cors_allow_origins=""), 2),
    ],
)
def test_the_three_guards_live_or_die_together(kwargs, expected):
    """SECA-18：企业形态下三件守卫同生同死，不允许"只落了 seed 半件"。"""
    violations = security_startup.evaluate_startup_guards(**kwargs)
    assert expected == len(violations), violations


def test_env_example_never_carries_a_credential_env_var():
    """SEC-A-002 的配置面半边：CREDENTIALS_PASSWORD 是一次性 CLI 变量。

    `.env` 由服务进程加载，把它写进模板等于让明文口令常驻配置面。
    """
    text = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8")
    keys = {line.split("=", 1)[0].strip() for line in text.splitlines() if "=" in line and not line.startswith("#")}
    assert not {key for key in keys if "PASSWORD" in key.upper()}, sorted(keys)
    assert "SECURITY_ENTERPRISE_MODE" in keys
    assert "CORS_ALLOW_ORIGINS" in keys


def test_repository_tracked_files_hold_no_credential_material():
    """SECA-20：扫描是普通 pytest 用例，本地与既有 CI job 同一道门。"""
    listing = subprocess.run(
        ["git", "ls-files", "-z"], cwd=BACKEND_DIR.parent, capture_output=True, check=True
    )
    offenders: list[str] = []
    exempt = EXEMPT_HITS  # 豁免表 == 命中表，见下
    for raw in listing.stdout.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8", "replace")
        path = BACKEND_DIR.parent / relative
        if not path.is_file() or path.suffix in {".png", ".webp", ".ico", ".woff", ".woff2", ".pyc"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in CREDENTIAL_PATTERN.finditer(text):
            site = f"{relative}:{text[:match.start()].count(chr(10)) + 1}"
            if site in exempt:
                continue
            offenders.append(f"{site} {match.group(0)[:24]}")
    assert [] == offenders, f"tracked 文件出现凭据形态取值，请加豁免前先确认它不是真凭据：{offenders}"


CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(?:api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{16,}"
)

# 豁免表逐项必须写成"文件:行 + 为什么它不是凭据"，且必须与命中集相等——
# 只增不减的豁免表等于没有豁免表（与 test_llm_egress_guard.py 同一族做法）。
EXEMPT_HITS: frozenset[str] = frozenset()


def test_the_exemption_table_matches_the_hit_set():
    hits = _scan_hits()  # 与上一用例共用的纯函数，返回同样的 site 字符串集合
    assert {str(item) for item in EXEMPT_HITS} == hits
```

最后一条要求把扫描逻辑抽成 `_scan_hits()` 供两条用例共用——**不许**两处各写一份正则，那样豁免表与命中表会各自漂移。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_secret_hygiene_contract.py -q
```
Expected: `ModuleNotFoundError: No module named 'app.security_startup'`（以及 `security` 无 `redact_for_persistence`）。

- [ ] **Step 3: 写实现**

`backend/app/security.py` 追加（**不改** `redact_text` / `redact_secrets`）：

```python
PERSISTENCE_SENSITIVE_KEYS = frozenset(
    {
        "password", "password_hash", "plaintext_password", "current_password", "new_password",
        "access_token", "refresh_token", "authorization", "api_key", "app_secret",
        "tenant_access_token", "secret", "credentials",
    }
)


def redact_for_persistence(value: Any) -> Any:
    """落盘面（审计 / trace / 日志 / 遥测表）脱敏：形态匹配 + **精确键名**匹配。

    刻意不做子串匹配：`token` 命中 tenant_access_token 也命中 input_tokens，
    后者是观测数据不是秘密。授权凭据库（user_store）不经过这里（SEC-A-009）。
    """
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            redact_text(key): (
                REDACTED if str(key).lower() in PERSISTENCE_SENSITIVE_KEYS
                else redact_for_persistence(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_for_persistence(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_for_persistence(item) for item in value)
    return value
```

`backend/app/audit.py`：`:9` 的 import 与 `:43`、`:59` 两处从 `redact_secrets` 换成 `redact_for_persistence`。`backend/app/agent_trace.py`：`:73`、`:91` 同理。**其余 24 处调用点不动**（含 8 处响应面 return）。

`backend/app/security_startup.py`：

```python
"""生产形态的启动守卫（规格 §8.5）。三件守卫由一枚开关共同驱动，不存在矛盾组合。"""

from __future__ import annotations

DEFAULT_JWT_SECRET = "change-me-before-production-yaoke-demo-secret"


class SecurityStartupError(RuntimeError):
    """企业形态下配置不安全 ⇒ 拒绝启动。比第一个请求才炸好。"""


def evaluate_startup_guards(
    *, enterprise_mode: bool, jwt_secret: str, cors_allow_origins: str
) -> list[str]:
    if not enterprise_mode:
        return []
    violations: list[str] = []
    if not jwt_secret or jwt_secret == DEFAULT_JWT_SECRET or len(jwt_secret) < 32:
        violations.append("SECURITY_ENTERPRISE_MODE 下 JWT_SECRET 必须是 ≥32 字符的非默认值")
    origins = [item.strip() for item in (cors_allow_origins or "").split(",") if item.strip()]
    if not origins or "*" in origins:
        violations.append("SECURITY_ENTERPRISE_MODE 下 CORS_ALLOW_ORIGINS 必须是显式白名单")
    return violations


def assert_startup_safe() -> None:
    from app.config import settings

    violations = evaluate_startup_guards(
        enterprise_mode=bool(settings.security_enterprise_mode),
        jwt_secret=str(settings.jwt_secret),
        cors_allow_origins=str(settings.cors_allow_origins),
    )
    if violations:
        raise SecurityStartupError("；".join(violations))
```

`config.py`：`cors_allow_origins: str = "http://localhost:3000"`。`main.py:77-83`：

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in settings.cors_allow_origins.split(",") if item.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

`main.py` lifespan 第三道（docstring 同步改掉"默认配置下启动零额外行为"里已不成立的部分——守卫在无企业开关时确实是 no-op，但这一句要写准）：

```python
    security_startup.assert_startup_safe()
    warmup_identity_permissions()
    warmup_llm_router()
```

`.env.example` 追加（口令变量刻意**不**进这张表，理由写注释里）：

```
# SEC-A：生产形态总开关。true ⇒ 不加载 demo 身份 + 默认 JWT_SECRET 拒启动 + CORS 白名单必填。
SECURITY_ENTERPRISE_MODE=false
# 逗号分隔白名单，不是子串、不是通配。
CORS_ALLOW_ORIGINS=http://localhost:3000
LOGIN_THROTTLE_WINDOW_SECONDS=60
LOGIN_THROTTLE_MAX_ATTEMPTS=10
ACCOUNT_MAX_FAILED_ATTEMPTS=5
ACCOUNT_LOCK_SECONDS=900
ARGON2_MAX_CONCURRENT_OPS=2
# 注意：CLI 口令变量 CREDENTIALS_PASSWORD **不要**写进本文件。
# .env 由服务进程加载，明文口令进来就等于进了常驻配置面（SEC-A-002）。
# Argon2 的 m/t/p 也不在这里：能运维调的安全强度等于没有强度（SEC-A-008）。
```

`test_branding_contract.py:32` 改写（收紧，不是放松）：

```python
        self.assertIn('JWT_SECRET=change-me-before-production-yaoke-demo-secret', env_example)
        # 占位符仍须出现在 .env.example（部署模板），但它**必须**被企业形态守卫拒绝：
        # 一条"模板里有的默认值"如果能一路跑到生产，那这条 branding 断言就是在保护漏洞。
        self.assertIn(
            security_startup.DEFAULT_JWT_SECRET, env_example
        )
        self.assertIn(
            2,
            len(
                security_startup.evaluate_startup_guards(
                    enterprise_mode=True,
                    jwt_secret=security_startup.DEFAULT_JWT_SECRET,
                    cors_allow_origins="",
                )
            ),
        )
```

- [ ] **Step 4: 填豁免表并跑测试**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_secret_hygiene_contract.py -q
```
首轮会把 `.env.example:132`（占位符）、若干测试假值命中打成红。逐条判断：**确认为占位符/假值**才写进 `EXEMPT_HITS`（形如 `backend/.env.example:132`），任何真实凭据形态都必须换成占位值而不是豁免。目标：两条扫描用例同时绿，且豁免表与命中表相等。

- [ ] **Step 5: 全套件 + 快照**

```bash
cd /e/xiangmu/rag/backend && python -m pytest -q
cp -r app ../.superpowers/sdd/SECURITY_A_PLAN/snap-task9-app
echo "- Ruling: 429/503 与 redactor 分层后，既有 redact_secrets 的 28 处调用点零改动；只切 audit/trace 的 4 处落盘面。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
```

---

## Task 10: 收口（镜像重建 → 容器基准 → 变异台 → closure → 验收文档）

**Files:**
- Create: `backend/tests/test_security_a_closure.py`
- Create: `.superpowers/sdd/SECURITY_A_PLAN/mutations/sec_a_mutations.py`
- Create: `.superpowers/scripts/run_argon2_benchmark.py`
- Delete: `backend/data/legacy_credentials.json`（closure 的最后一步，且必须在 `legacy_count=0` 之后）
- Create: `docs/SECURITY_A_ACCEPTANCE_2026-09-25.md`

- [ ] **Step 1: 重建发布镜像并做双向 import 探针**（release gate 第 1、6 步）

```bash
cd /e/xiangmu/rag
docker compose build backend
docker compose up -d backend
sleep 3 && docker compose ps backend
docker exec rag-backend-1 python -c "import argon2, credentials_probe" 2>/dev/null || \
docker exec rag-backend-1 python -c "
import argon2
from argon2 import PasswordHasher
ph = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
h = ph.hash('container-probe 123')
print('argon2 import OK', ph.verify(h, 'container-probe 123'))
"
```
Expected: 打印 `argon2 import OK True`。装不上 wheel ⇒ **SECA-19 = `BLOCKED`**，不得改用宿主结果凑数、不得降档（SEC-A-008），并在验收文档记录 wheel 与镜像层的确切失败信息。

- [ ] **Step 2: 容器内 Argon2 基准**（SECA-19；写 `.superpowers/scripts/run_argon2_benchmark.py`）

```python
"""在发布容器内实测 Argon2id 档位的延迟与内存，作为 SECA-19 的判据。

预算（规格 §12 SECA-19）：串行 P95 ≤ 1500ms；ARGON2_MAX_CONCURRENT_OPS 并发 P95 ≤ 3000ms；
单次运算峰值 RSS 增量 ≤ 256 MiB。不满足 ⇒ BLOCKED，降档必须走规格修订。
"""

import json
import resource
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from argon2 import PasswordHasher

TIME_COST, MEMORY_COST, PARALLELISM = 2, 19456, 1
SERIAL_RUNS, CONCURRENT_RUNS, WORKERS = 50, 32, 2
BUDGET = {"serial_p95_ms": 1500.0, "concurrent_p95_ms": 3000.0, "rss_delta_kib": 256 * 1024}

ph = PasswordHasher(time_cost=TIME_COST, memory_cost=MEMORY_COST, parallelism=PARALLELISM)
password = f"benchmark-password {time.time_ns()}"
encoded = ph.hash(password)
baseline_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def one(_: int) -> float:
    started = time.perf_counter()
    ph.verify(encoded, password)
    return (time.perf_counter() - started) * 1000.0


def p95(samples):
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


serial = [one(i) for i in range(SERIAL_RUNS)]
with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    concurrent = list(pool.map(one, range(CONCURRENT_RUNS)))
peak_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - baseline_kib

report = {
    "profile": {"time_cost": TIME_COST, "memory_cost": MEMORY_COST, "parallelism": PARALLELISM},
    "environment": sys.platform,
    "serial": {
        "runs": SERIAL_RUNS,
        "p50_ms": round(statistics.median(serial), 1),
        "p95_ms": round(p95(serial), 1),
    },
    "concurrent": {"runs": CONCURRENT_RUNS, "workers": WORKERS, "p95_ms": round(p95(concurrent), 1)},
    "peak_rss_delta_kib": int(peak_kib),
    "budget": BUDGET,
}
report["verdict"] = "GREEN" if (
    report["serial"]["p95_ms"] <= BUDGET["serial_p95_ms"]
    and report["concurrent"]["p95_ms"] <= BUDGET["concurrent_p95_ms"]
    and report["peak_rss_delta_kib"] <= BUDGET["rss_delta_kib"]
) else "BLOCKED"
print(json.dumps(report, indent=2, ensure_ascii=False))
```

串行 50 次 + 并发 32 次/2 worker 的选择理由要写进报告注释：`ARGON2_MAX_CONCURRENT_OPS=2` 是闸门上限，基准必须在**闸门满配**下测，否则测出来的是理想值而不是最坏值。

```bash
cd /e/xiangmu/rag
docker compose cp .superpowers/scripts/run_argon2_benchmark.py backend:/tmp/bench.py
docker compose exec backend python /tmp/bench.py | tee .superpowers/sdd/SECURITY_A_PLAN/argon2-benchmark-container.json
python .superpowers/scripts/run_argon2_benchmark.py > .superpowers/sdd/SECURITY_A_PLAN/argon2-benchmark-host.json
```
Expected: 容器报告 `verdict` 字段可读。**容器数才是判据**，宿主数只作为对照（V2.3 P0 的机器依赖教训）。

- [ ] **Step 3: compose smoke 四场景**（release gate 第 6 步）

```bash
cd /e/xiangmu/rag
API=http://localhost:8001
# 场景 1：升级路径登录（容器内 DB 若为旧库，先跑迁移导入）
docker compose exec backend python -m app.cli credentials bootstrap-admin --username admin  # 期望 rc=2：企业形态或身份缺失时不得建身份
docker compose exec backend python -m app.cli credentials migration-status
curl -sS -X POST $API/api/auth/login -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | tee .superpowers/sdd/SECURITY_A_PLAN/smoke-01-login.json
# 场景 2：错口令（与场景 1 的未知账号必须同形）
curl -sS -o /dev/null -w '%{http_code}\n' -X POST $API/api/auth/login -H 'content-type: application/json' \
  -d '{"username":"admin","password":"definitely-wrong-123"}'
curl -sS -o /dev/null -w '%{http_code}\n' -X POST $API/api/auth/login -H 'content-type: application/json' \
  -d '{"username":"nosuchaccount","password":"definitely-wrong-123"}'
# 场景 3：must_change 数据面阻断（若场景 1 返回 password_change_required=true）
TOKEN=$(python -c "import json;print(json.load(open('.superpowers/sdd/SECURITY_A_PLAN/smoke-01-login.json'))['access_token'])")
curl -sS -o /dev/null -w '%{http_code}\n' $API/api/knowledge-bases -H "Authorization: Bearer $TOKEN"
# 场景 4：锁定（错口令连打到 ACCOUNT_MAX_FAILED_ATTEMPTS 次后，正确口令也必须 401）
```
Expected: 场景 2 两条都 401 且响应体逐字相同；场景 3 为 403（`password_change_required`）或 200（该账号已改过密）——两者都要在验收文档里写明当时是哪一种、为什么。

- [ ] **Step 4: 变异台 19 发**（写 `.superpowers/sdd/SECURITY_A_PLAN/mutations/sec_a_mutations.py`）

harness 骨架（**必须**字节安全：读字节 → 替换 → 写 → 跑定向测试 → 还原 → sha1 核对，`finally` 里也还原）：

```python
"""SECA 变异台：每一发都必须杀至少一条测试，否则那条测试是死代码。"""

import hashlib
import subprocess
import sys
from pathlib import Path

BACKEND = Path("E:/xiangmu/rag/backend")

# (代号, 相对路径, 原文片段, 变异后片段, 期望红的测试节点)
MUTATIONS = [
    ("M1", "app/credentials.py", "    return _HASHER.hash(plain)", "    return hashlib.sha256(plain.encode('utf-8')).hexdigest()", "test_credentials_contract.py::Argon2ProfileTests"),
    ("M2", "app/auth.py", "if _password_change_required(user.username):", "if False:", "test_password_lifecycle_contract.py::SelfServiceChangeTests"),
    ("M3", "app/auth.py", "if not isinstance(claimed, int) or claimed != record.credentials_version:", "if False:", "test_password_lifecycle_contract.py::TokenRevocationTests"),
    ("M4", "app/auth.py", "credentials.verify_dummy(password)", "pass", "test_authentication_leg_contract.py::UnifiedFailureTests"),
    ("M5", "app/main.py", 'raise HTTPException(status_code=401, detail="用户名或密码错误")', 'raise HTTPException(status_code=401, detail="用户名或密码错误" if result.audit_detail != auth.AUDIT_LOGIN_LOCKED else "账号已锁定，请稍后再试")', "test_authentication_leg_contract.py::LockedHttpFaceTests"),
    ("M6", "app/login_throttle.py", 'return f"{str(username).casefold()}|{client_ip}"', 'return str(username).casefold()', "test_authentication_leg_contract.py::ThrottleLayerTests"),
    ("M7", "app/user_store.py", "WHERE username = ?", "WHERE locked_until IS NULL AND username = ?", "test_authentication_leg_contract.py::ThrottleLayerTests"),
    ("M8", "app/security.py", "str(key).lower() in PERSISTENCE_SENSITIVE_KEYS", '"token" in str(key).lower()', "test_secret_hygiene_contract.py"),
    ("M9", "app/user_store.py", "    encoded = credentials.hash_password(plain_password)", '    encoded = "[REDACTED]"  # 模拟授权凭据库被通用 redactor 罩过（只改第一处 create_argon2）', "test_credentials_contract.py::UserStoreSchemaTests"),
    ("M10", "app/user_store.py", "def _bump_and_clear(", "def _bump_and_clear_disabled(", "test_credentials_contract.py::UserStoreTransactionTests"),
    ("M11", "app/user_store.py", " failed_attempts = 0, locked_until = NULL, updated_at = ?", " updated_at = ?", "test_password_lifecycle_contract.py::AdminResetTests"),
    ("M12", "app/directory.py", 'model_config = ConfigDict(extra="forbid")', 'model_config = ConfigDict(extra="ignore")', "test_user_directory_contract.py"),
    ("M13", "app/auth.py", "from app import credentials, directory, user_store", "import hashlib\nfrom app import credentials, directory, user_store\n\n\ndef _m13_probe(password: str) -> str:\n    return hashlib.sha256(password.encode('utf-8')).hexdigest()", "test_credentials_contract.py::CentralisationScanTests"),
    ("M14", "app/auth.py", "if forced and not wrote:\n            detail = AUDIT_REHASH_DEGRADED", "if forced and not wrote:\n            return LoginResult(None, AUDIT_INVALID_CREDENTIALS, False)", "test_authentication_leg_contract.py::LegacyUpgradeTests"),
    ("M15", "config/users.demo.json", '"username": "admin"', '"username": "admin", "password_hash": "a"', "test_user_directory_contract.py"),
    ("M16", "app/credentials.py", "ARGON2_MEMORY_COST = 19456", "ARGON2_MEMORY_COST = int(os.environ.get('ARGON2_MEMORY_COST', 19456))", "test_credentials_contract.py::Argon2ProfileTests"),
    ("M17", "app/auth.py", "if not isinstance(claimed, int) or claimed != record.credentials_version:", "if claimed is not None and claimed != record.credentials_version:", "test_password_lifecycle_contract.py::TokenRevocationTests"),
    ("M18", "app/directory.py", "            if identity.username in merged:", "            if False:", "test_user_directory_contract.py"),
    ("M19", "app/auth.py", "if identity is None or not identity.enabled or record is None:", "if identity is None or not identity.enabled:\n        if record is None:\n            user_store.import_legacy_digest(username, 'a' * 64, must_change=True)\n            record = user_store.get_record(username)", "test_authentication_leg_contract.py::SourceRemovalTests"),
]


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def run(node: str) -> int:
    return subprocess.call(
        [sys.executable, "-m", "pytest", node, "-q", "-x"], cwd=str(BACKEND)
    )


def main() -> int:
    results = []
    for code, relative, old, new, node in MUTATIONS:
        path = BACKEND / relative
        original = path.read_bytes()
        before = sha1(path)
        text = original.decode("utf-8")
        if text.count(old) < 1:
            results.append((code, "TARGET-NOT-FOUND", ""))
            continue
        try:
            path.write_bytes(text.replace(old, new, 1).encode("utf-8"))
            killed = run(node) != 0
            results.append((code, "KILLED" if killed else "SURVIVED", node))
        finally:
            path.write_bytes(original)
            assert sha1(path) == before, f"{code} 还原失败：{path}"   # 还原不了就停下，别把变异留在树上
    for row in results:
        print("\t".join(row))
    survived = [row for row in results if row[1] != "KILLED"]
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

```bash
cd /e/xiangmu/rag && python .superpowers/sdd/SECURITY_A_PLAN/mutations/sec_a_mutations.py
```
Expected: 19 行全 `KILLED`，退出码 0。任何 `SURVIVED` ⇒ 对应 SECA 行是死测试，**补测试而不是撤变异**（不得反向放宽）。`TARGET-NOT-FOUND` 说明计划里的片段与真实代码漂移，按当时代码原文修正片段，不改判据。

- [ ] **Step 5: closure 门与三处扫描**（`backend/tests/test_security_a_closure.py`）

```python
LEGACY_DIGESTS = (
    "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9",
    "6bc0a63cb29c92306020c0a6bbc358cc4628db277dc06e253535e126517ad637",
    "070a3b5e8d4bd5c46acccb91c9c54614c0cd649e78c4c4719e3a64270bae5ddf",
    "e606e38b0d8c19b24cf0ee3808183162ea7cd63ff7912dbb22b5e803286b4446",
    "65375049b9e4d7cad6c9ba286fdeb9394b28135a3e84136404cfccfdcc438894",
)
SCANNED_ROOTS = ("app", "config")


def test_steady_state_code_holds_no_legacy_digest():
    """SECA-04 的代码/配置半边：三处扫描中稳态可静态自证的两处。"""
    offenders = []
    for root in SCANNED_ROOTS:
        for path in (BACKEND_DIR / root).rglob("*"):
            if not path.is_file():
                continue
            body = path.read_text(encoding="utf-8", errors="ignore")
            offenders += [f"{path}:{digest}" for digest in LEGACY_DIGESTS if digest in body]
    assert [] == offenders


def test_running_database_holds_no_active_legacy_credential():
    """SECA-04 的库半边：这是 release gate 的硬门，未归零 ⇒ BLOCKED（不是 PENDING）。"""
    user_store.ensure_user_credentials_schema()
    counts = user_store.count_by_algorithm()
    assert 0 == counts.get(credentials.ALGORITHM_LEGACY_SHA256, 0)


def test_the_migration_artifact_is_gone_after_closure():
    assert not (BACKEND_DIR / "data" / "legacy_credentials.json").exists()
```

**上面三条测的是测试库**（conftest 把 `CONVERSATION_DB_PATH` 会话级重定向到 tmp）。生产库必须在带外单独查一次并留证——这是 `legacy_count=0` 真正的那个 0：

```bash
cd /e/xiangmu/rag/backend && python - <<'PY' | tee ../.superpowers/sdd/SECURITY_A_PLAN/closure-real-db-legacy-count.txt
import sqlite3
from pathlib import Path

db = Path("data/conversations.db")
if not db.exists():
    print("REAL_DB_MISSING: 生产库不存在，SECA-04 的库半边记 PENDING_EXTERNAL 而不是 GREEN")
    raise SystemExit(0)
connection = sqlite3.connect(db)
tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
if "user_credentials" not in tables:
    print("REAL_DB_HAS_NO_user_credentials: 生产库尚未初始化凭据表 ⇒ 稳态无 legacy 行，"
          "但必须同时确认没有 demo 行可登（企业形态）")
    raise SystemExit(0)
for algorithm, count in connection.execute(
    "SELECT algorithm, COUNT(*) FROM user_credentials GROUP BY algorithm"
):
    print(f"REAL_DB {algorithm}={count}")
legacy = connection.execute(
    "SELECT COUNT(*) FROM user_credentials WHERE algorithm='legacy-sha256'"
).fetchone()[0]
print(f"REAL_DB legacy_count={legacy}")
PY
```

`legacy_count=0` ⇒ SECA-04 记 `GREEN`；`>0` ⇒ **`BLOCKED`**（不是 `PENDING`，规格 §8.7）；容器内库（`/app/data/conversations.db`）与宿主库都要各查一次，两者是不同文件。

- [ ] **Step 6: 全套件两 cwd 对账**

```bash
cd /e/xiangmu/rag/backend && python -m pytest -q 2>&1 | tail -3
cd /e/xiangmu/rag && python -m pytest backend/tests -q 2>&1 | tail -3
```
Expected: 两行 `N passed` 数字**逐位相同**；记录到验收文档。V2.3 基线数（950 / 961）只作为历史事实引用，不作为本规格基线（规格 §17 L5）。

- [ ] **Step 7: 写验收文档**

`docs/SECURITY_A_ACCEPTANCE_2026-09-25.md` 必含段落（版式照 `MODEL_ROUTER_V23_ACCEPTANCE_2026-09-24.md`）：判据表 · 交付了什么 · 27 行矩阵与状态列（三值）· 变异台 19 行结果 · before/after 证据（schema dump、算法分布、三处扫描、Argon2 容器/宿主两份 JSON、compose smoke 原始输出）· 已知限制（L1–L6 + 一次强制重登录的 breaking change）· 后续登记（§18 清单，含弱口令字典与专用 security job）· 冻结基线（tree SHA / 镜像 ID / 套件数 / 本文档修订）。

- [ ] **Step 8: 快照与提交（提交需当轮授权）**

```bash
cd /e/xiangmu/rag
cp -r backend/app .superpowers/sdd/SECURITY_A_PLAN/snap-task10-app
cp docs/SECURITY_A_ACCEPTANCE_2026-09-25.md .superpowers/sdd/SECURITY_A_PLAN/
git status --short
```
把 `git status` 与拟提交的文件清单交给用户，**逐条确认后**再执行 `git add <显式路径>` + 一次提交（不用 `git add -A`）；tag 名建议 `security-a-rc1`。**不得**触碰 `model-router-v2.3-rc1`，不得 amend 已发布的 RC。

---

## 计划自审（writing-plans 要求的三项）

**1. 规格覆盖（§4 不变量 → 任务）**：SEC-A-001 → Task 1（原语）+ 2（写函数不可达 algorithm）；002 → Task 7（CLI 无 argv 口令）+ 9（`.env.example` 键集合无交集）；003 → Task 5（升级腿）+ 7（改密后数据面通）；004 → Task 3（受限生产者）+ 10（SQL 门与三处扫描）；005 → Task 1（AST 单点 + 豁免表相等）；006 → Task 5/6/9 的既有测试地基（含 8 处登录调用点、`/api/query` 键集合、D6 豁免面）；007 → Task 10（19 发变异台）；008 → Task 1（常量）+ 9（M16 靶子）；009 → Task 9（两域 + 授权库例外）；010 → Task 4（身份文件与合并不变量）+ 7（bootstrap 不写身份）。

**§12 的 27 行矩阵 → 任务**：01(1,2) · 02(7,9) · 03(5,7) · 04(10) · 04b(3,5) · 05(1) · 06(5,6,9) · 07(4) · 08(2) · 09(6) · 09b(6) · 10(6) · 11(2) · 12(7) · 13(5) · 14(5,8) · 15(8) · 16a(8) · 16b(8) · 17(9) · 18(9) · 19(1,8 宿主侧 / 10 容器侧) · 20(9) · 21(5) · 22(2 的 `_fresh_db` 重定向 + 10 收口复确认) · 23(4) · 24(5)。

三处值得点名的"跨任务半边"已在任务内显式收口，不是悬空：SECA-03 的"改密后数据面通"由 Task 7 的 `SelfServiceChangeTests` 完成；SECA-13 的"同档 profile"断言在 Task 5 Step 1 内已写成可执行形态；SECA-14 的 HTTP 半边在 Task 8 新增 `LockedHttpFaceTests`（腿级用例看不见 `main.py` 的文案分叉，M5 只有这条能抓）。

**2. 占位扫描**：初稿里四处"计划知道自己没想透"的粗糙点在自审中被替换为可执行代码，不再留给实现者——Task 5 的 `_fresh_db`（原本 reload 一个不存在的 `auth.config_module`）、四态 profile 断言（原本是 `for _ in []` 的空壳）、`LoginResult` 构造（原本附一段"故意写坏"的示例）、Task 7 的 bootstrap 断言（原本是条件表达式凑数）、Task 9 的形态测试（原本是 `assert A or True` 式重言）、Task 10 基准报告的 walrus。harness 的 `TARGET-NOT-FOUND` 分支是**故意保留**的机制而非占位：计划里的注入片段可能随实现漂移，漂移时报错并要求按当时代码原文修片段，比静默跳过一个变异安全。

**3. 类型一致性**：`LoginResult(user, audit_detail, password_change_required)` 的 `audit_detail` 取值域在 Task 5 定义为"空串或三枚 token"，Task 6/7/8 与 M5 均按此引用；`_user_from(identity, grant)` 在 Task 5 Step 3 定义并列入 Produces，Task 6 测试直接调用；`seed_demo_credentials` 在 Task 5 Step 7 由 conftest 提供为**普通函数**（fixture 只是它的一个调用者），Task 5/6 测试从 `tests.conftest` 导入；`credentials.ALGORITHM_*` / `CredentialRecord` 八字段 / `user_store` 全部函数签名在 Task 1/2 定义、3–10 复用；`directory.override_identities` / `reset_cache` 在 Task 4 定义，Task 5/6/8 使用；`auth.AUDIT_LOGIN_LOCKED`（M5 注入片段引用）与 Task 5 Step 3 的常量名一致；`login_throttle.PreHashThrottle(window_seconds=, max_attempts=)` 构造形态在 Task 8 测试与实现两处一致。

**规格回写**：拆任务时发现规格 §9.1 把 `invalid_credentials` / `password_change_required` 写成了 HTTP 响应 detail，照此实现会让界面第一次出现英文 token，与本项目展示层中文文案规则冲突。已按"评审发现 → 回写规格 → 计划照规格写"的时序把 §9.1 改成 **HTTP 中文文案 / 审计枚举 token 两栏**（规格 §20.2 记录来由），计划的 Task 5/7/8 断言全部按两栏写。**这是规格的一次实质变更**，需你确认后再开工。

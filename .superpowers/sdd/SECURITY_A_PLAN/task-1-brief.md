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
        except argon2.exceptions.InvalidHashError as exc:
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


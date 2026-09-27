# diff bc43ca3..worktree
## tracked
 backend/app/config.py    | 4 ++++
 backend/requirements.txt | 1 +
 2 files changed, 5 insertions(+)
## diff
diff --git a/backend/app/config.py b/backend/app/config.py
index 0d33b02..962e29c 100644
--- a/backend/app/config.py
+++ b/backend/app/config.py
@@ -148,20 +148,24 @@ class Settings(BaseSettings):
     # the real-BGE gate. Hybrid keeps the raw query because it measured better with RRF.
     retrieval_vector_query_instruction: str = "为这个句子生成表示以用于检索相关文章："
     # Prefer diverse documents in the final evidence set while still allowing a
     # document to contribute multiple sections. Deferred chunks fill any shortage.
     retrieval_max_chunks_per_document: int = Field(default=2, ge=1, le=10)
     retrieval_query_context_max_chars: int = Field(default=320, ge=80, le=1000)
 
     jwt_secret: str = "change-me-before-production-yaoke-demo-secret"
     jwt_expire_hours: int = 8
 
+    # Argon2 并发槽上限（可用性旋钮）。**密码学档位不在这里**：m/t/p 固定在
+    # app/credentials.py 的常量上，改它等于改规格（SEC-A-008）。
+    argon2_max_concurrent_ops: int = 2
+
     # Local backend cwd is normally ./backend, so ../demo-data points to repo demo data.
     # Docker overrides this to /app/demo-data via docker-compose.
     demo_data_dir: str = "../demo-data"
 
     # Feishu permission bridge (see docs/FEISHU_PERMISSION_BRIDGE_DESIGN.md).
     # Disabled by default: every behaviour stays exactly like the demo accounts.
     feishu_permissions_enabled: bool = False
     feishu_app_id: str = ""
     feishu_app_secret: SecretStr = SecretStr("")
     feishu_base_url: str = "https://open.feishu.cn"
diff --git a/backend/requirements.txt b/backend/requirements.txt
index 9c02a68..ad067b3 100644
--- a/backend/requirements.txt
+++ b/backend/requirements.txt
@@ -3,12 +3,13 @@ uvicorn[standard]>=0.30,<1
 pydantic>=2.8,<3
 pydantic-settings>=2.4,<3
 python-multipart>=0.0.9
 qdrant-client>=1.12,<2
 sentence-transformers>=3.0,<6
 rank-bm25>=0.2.2
 pymupdf>=1.24,<2
 python-docx>=1.1,<2
 httpx>=0.27,<1
 PyJWT>=2.9,<3
+argon2-cffi>=23.1.0,<26
 ddgs>=9.0,<10
 typesafe-sdk>=0.7,<1
## new file: backend/app/credentials.py
diff --git a/backend/app/credentials.py b/backend/app/credentials.py
new file mode 100644
index 0000000..be8c2a6
--- /dev/null
+++ b/backend/app/credentials.py
@@ -0,0 +1,127 @@
+"""口令哈希原语：全仓唯一允许对口令做密码学运算的模块（SEC-A-005）。
+
+只认识口令，不认识 username、不查库、不做失败语义——那些在 auth/user_store 上头。
+"""
+
+from __future__ import annotations
+
+import hashlib
+import hmac
+import re
+from contextlib import contextmanager
+from dataclasses import dataclass
+from threading import BoundedSemaphore
+
+import argon2
+
+from app.config import settings
+
+ALGORITHM_ARGON2ID = "argon2id"
+ALGORITHM_LEGACY_SHA256 = "legacy-sha256"
+
+# OWASP Password Storage Cheat Sheet 的 Argon2id 最低推荐档（19 MiB / t=2 / p=1）。
+# 出处不是 RFC 9106（它推荐 2 GiB/t=1/p=4 或 64 MiB/t=3/p=4），措辞别改回去。
+# 这三枚常量不可经 env 调整：能运维调的安全强度等于没有强度（SEC-A-008）。
+ARGON2_TIME_COST = 2
+ARGON2_MEMORY_COST = 19456
+ARGON2_PARALLELISM = 1
+
+ARGON2_HASH_PREFIX = "$argon2id$"
+_LEGACY_HEX = re.compile(r"^[0-9a-f]{64}$")
+
+
+class CredentialConfigError(RuntimeError):
+    """algorithm 列与编码串互相矛盾。不猜、不降级、不 try-both。"""
+
+
+class PasswordCapacityError(RuntimeError):
+    """并发槽已满。调用方翻译成 503，不是认证失败。"""
+
+
+@dataclass(frozen=True)
+class VerifyOutcome:
+    ok: bool
+    needs_rehash: bool
+
+
+_HASHER = argon2.PasswordHasher(
+    time_cost=ARGON2_TIME_COST,
+    memory_cost=ARGON2_MEMORY_COST,
+    parallelism=ARGON2_PARALLELISM,
+)
+
+# 与当前档位同源的常量工作单元：未知账号 / disabled / 无凭据行 三态都要消耗
+# 一次真实运算，否则"账号不存在"就是一条响应时间指纹。
+_DUMMY_HASH = _HASHER.hash("yaoke-constant-work-dummy-credential")
+
+_SLOTS = BoundedSemaphore(max(1, int(settings.argon2_max_concurrent_ops)))
+
+
+def hasher() -> argon2.PasswordHasher:
+    return _HASHER
+
+
+def dummy_hash() -> str:
+    return _DUMMY_HASH
+
+
+def hash_password(plain: str) -> str:
+    return _HASHER.hash(plain)
+
+
+def needs_rehash(encoded: str) -> bool:
+    # 参数漂移判定交给库：自行比较字符串会漏掉"改了 m/t/p 但 v=19 不变"这一类。
+    return _HASHER.check_needs_rehash(encoded)
+
+
+@contextmanager
+def argon2_slot():
+    if not _SLOTS.acquire(blocking=False):
+        raise PasswordCapacityError("password operation capacity exceeded")
+    try:
+        yield
+    finally:
+        _SLOTS.release()
+
+
+def verify_password(plain: str, *, algorithm: str, encoded: str) -> VerifyOutcome:
+    if algorithm == ALGORITHM_ARGON2ID:
+        if not encoded.startswith(ARGON2_HASH_PREFIX):
+            raise CredentialConfigError(
+                f"algorithm={algorithm!r} 与编码串前缀不符"
+            )
+        return _verify_argon2(plain, encoded)
+    if algorithm == ALGORITHM_LEGACY_SHA256:
+        if not _LEGACY_HEX.match(encoded):
+            raise CredentialConfigError(
+                f"algorithm={algorithm!r} 与编码串形态不符"
+            )
+        # 用关键字传参不是风格洁癖：SECA-05 的门是 AST 词法判定，谁把这处改回位置参数、
+        # 或把形参改名成不带口令字样的名字（例如 `plain`），那条门就静默失效。
+        return VerifyOutcome(
+            ok=hmac.compare_digest(_legacy_digest(password=plain), encoded.lower()),
+            needs_rehash=True,
+        )
+    raise CredentialConfigError(f"未知 algorithm：{algorithm!r}")
+
+
+def verify_dummy(plain: str) -> VerifyOutcome:
+    """恒定一次同档 Argon2 运算，永不成功；异常是"口令不对"的正常路径。"""
+    return _verify_argon2(plain, _DUMMY_HASH)
+
+
+def _verify_argon2(plain: str, encoded: str) -> VerifyOutcome:
+    with argon2_slot():
+        try:
+            _HASHER.verify(encoded, plain)
+        except argon2.exceptions.VerifyMismatchError:
+            return VerifyOutcome(ok=False, needs_rehash=needs_rehash(encoded))
+        except argon2.exceptions.InvalidHashError as exc:
+            raise CredentialConfigError("Argon2 编码串无法解析") from exc
+    return VerifyOutcome(ok=True, needs_rehash=needs_rehash(encoded))
+
+
+def _legacy_digest(password: str) -> str:
+    # 形参名是 SECA-05 那道 AST 扫描按词面认出"口令参与运算的 hashlib"的唯一凭据：
+    # 改回 `plain` 之类就把这处命中变成隐身，豁免表也就成了自证。
+    return hashlib.sha256(password.encode("utf-8")).hexdigest()
## new file: backend/tests/test_credentials_contract.py
diff --git a/backend/tests/test_credentials_contract.py b/backend/tests/test_credentials_contract.py
new file mode 100644
index 0000000..8f4bfdd
--- /dev/null
+++ b/backend/tests/test_credentials_contract.py
@@ -0,0 +1,153 @@
+from __future__ import annotations
+
+import ast
+import hashlib
+import re
+import sys
+import unittest
+from pathlib import Path
+
+BACKEND_DIR = Path(__file__).resolve().parents[1]
+sys.path.insert(0, str(BACKEND_DIR))
+
+from app import credentials  # noqa: E402
+
+
+class Argon2ProfileTests(unittest.TestCase):
+    def test_profile_is_the_owasp_minimum_baseline_and_is_a_code_constant(self):
+        self.assertEqual(2, credentials.ARGON2_TIME_COST)
+        self.assertEqual(19456, credentials.ARGON2_MEMORY_COST)
+        self.assertEqual(1, credentials.ARGON2_PARALLELISM)
+
+    def test_hashed_password_is_a_verifiable_argon2id_phc_string(self):
+        encoded = credentials.hash_password("correct horse battery staple 12")
+        self.assertTrue(encoded.startswith("$argon2id$"), encoded)
+        outcome = credentials.verify_password(
+            "correct horse battery staple 12",
+            algorithm=credentials.ALGORITHM_ARGON2ID,
+            encoded=encoded,
+        )
+        self.assertTrue(outcome.ok)
+        self.assertFalse(outcome.needs_rehash)  # 刚按当前档位生成
+
+    def test_a_wrong_password_does_not_verify(self):
+        encoded = credentials.hash_password("right answer 1234567890")
+        outcome = credentials.verify_password(
+            "wrong answer 1234567890",
+            algorithm=credentials.ALGORITHM_ARGON2ID,
+            encoded=encoded,
+        )
+        self.assertFalse(outcome.ok)
+
+
+class AlgorithmColumnTests(unittest.TestCase):
+    """规格 §6.2：分派权威是列，编码串前缀只做交叉校验。"""
+
+    def test_argon2_column_with_a_non_argon2_payload_is_a_hard_failure(self):
+        with self.assertRaises(credentials.CredentialConfigError):
+            credentials.verify_password(
+                "x", algorithm=credentials.ALGORITHM_ARGON2ID, encoded="deadbeef"
+            )
+
+    def test_legacy_column_with_a_non_hex_payload_is_a_hard_failure(self):
+        with self.assertRaises(credentials.CredentialConfigError):
+            credentials.verify_password(
+                "x",
+                algorithm=credentials.ALGORITHM_LEGACY_SHA256,
+                encoded="zz" * 32,
+            )
+
+    def test_a_legacy_digest_still_authenticates_under_the_legacy_column(self):
+        plain = "legacy-demo-password"
+        encoded = hashlib.sha256(plain.encode("utf-8")).hexdigest()
+        outcome = credentials.verify_password(
+            plain, algorithm=credentials.ALGORITHM_LEGACY_SHA256, encoded=encoded
+        )
+        self.assertTrue(outcome.ok)
+        self.assertTrue(outcome.needs_rehash)  # legacy 永远要收敛
+
+
+class DummyVerifyTests(unittest.TestCase):
+    def test_dummy_verification_costs_one_argon2_run_and_never_succeeds(self):
+        outcome = credentials.verify_dummy("anything at all 1234567890")
+        self.assertFalse(outcome.ok)
+
+    def test_dummy_string_is_generated_with_the_current_profile(self):
+        # 若 dummy 串档位与当前 profile 不一致，§7.3 的"工作量可比"就是空话。
+        self.assertTrue(
+            credentials.dummy_hash().startswith(
+                f"{credentials.ARGON2_HASH_PREFIX}v=19$"
+                f"m={credentials.ARGON2_MEMORY_COST},"
+                f"t={credentials.ARGON2_TIME_COST},"
+                f"p={credentials.ARGON2_PARALLELISM}$"
+            )
+        )
+
+
+class CentralisationScanTests(unittest.TestCase):
+    """SECA-05：口令参与运算的 hashlib 命中面 == 豁免表，且豁免表只有一个常任成员。"""
+
+    HASHES = re.compile(r"sha256|sha512|md5|blake2|pbkdf2")
+    # 词面判定天然会被改名绕过（`plain` / 一个不带口令字样的 str 变量），所以词表按"最可能被
+    # 用来命名口令原料的字样"放宽：口令本字族、裸 plain/digest/hash、以及明文的常见变体。
+    # (?<![a-z])…(?![a-z]) 这两道边界是防合成词误伤——实测 `hashlib.sha256(...).hexdigest()`
+    # 的 unparse 文本里 digest 只以 `hexdigest` 的形态出现，加了边界就不会把非口令站点带进来。
+    PASSWORD_WORDS = re.compile(
+        r"(?i)password|passwd|secret"
+        r"|(?<![a-z])(?:plain|digest|hash)(?![a-z])"
+        r"|plain[-_]?(?:text|hash|pw)"
+    )
+    #: `app/auth.py` 是**过渡**豁免：它的口令摘要与登录腿切换是同一个原子动作（计划 Task 5
+    #: Step 6 删 `auth._password_digest`），在那一轮之前把期望写成"只剩 credentials.py"只会
+    #: 让这道门从落地第一天就红着、然后被人跳过。Task 5 收口时必须清空本表，并把两条断言的
+    #: 期望集收紧成 `{app/credentials.py}`——本表若空转（还豁免着已经不存在命中点的文件），
+    #: `test_the_exemption_table_is_equal_to_the_hit_set` 会直接判红，不需要谁去记得它。
+    TRANSITIONAL_EXEMPT = frozenset({"app/auth.py"})
+
+    def _hashlib_password_sites(self) -> list[str]:
+        hits: list[str] = []
+        for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
+            tree = ast.parse(path.read_text(encoding="utf-8"))
+            imported = {
+                alias.name.split(".")[0]
+                for node in ast.walk(tree)
+                if isinstance(node, ast.Import)
+                for alias in node.names
+            }
+            if "hashlib" not in imported:
+                continue
+            for node in ast.walk(tree):
+                if not isinstance(node, ast.Call):
+                    continue
+                func = node.func
+                if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
+                    continue
+                if func.value.id != "hashlib":
+                    continue
+                text = ast.unparse(node)
+                if self.HASHES.search(func.attr) and self.PASSWORD_WORDS.search(text):
+                    hits.append(f"{path.relative_to(BACKEND_DIR)}:{node.lineno} {text}")
+        return hits
+
+    def _exemption_table(self) -> frozenset[str]:
+        return frozenset({"app/credentials.py"}) | self.TRANSITIONAL_EXEMPT
+
+    @staticmethod
+    def _relative_dir(site: str) -> str:
+        return site.split(":")[0].replace("\\", "/")
+
+    def test_only_credentials_module_hashes_passwords(self):
+        exempt = self._exemption_table()
+        self.assertEqual(
+            [],
+            [
+                site
+                for site in self._hashlib_password_sites()
+                if self._relative_dir(site) not in exempt
+            ],
+        )
+
+    def test_the_exemption_table_is_equal_to_the_hit_set(self):
+        # 上一钉管"表外不许有命中"，这一钉管反向"表里不许有表外用不上的豁免"。
+        hits = {self._relative_dir(site) for site in self._hashlib_password_sites()}
+        self.assertEqual(set(self._exemption_table()), hits)

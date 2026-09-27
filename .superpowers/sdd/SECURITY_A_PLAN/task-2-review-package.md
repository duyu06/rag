# Task 2 diff (pre-Task2 snapshot -> worktree); Task 1 content excluded
## stat
  Files .superpowers/sdd/SECURITY_A_PLAN/snap-task1-r2-app/__pycache__/config.cpython-313.pyc and backend/app/__pycache__/config.cpython-313.pyc differ
  Files .superpowers/sdd/SECURITY_A_PLAN/snap-task1-r2-app/__pycache__/user_store.cpython-313.pyc and backend/app/__pycache__/user_store.cpython-313.pyc differ
  Files .superpowers/sdd/SECURITY_A_PLAN/snap-task1-r2-app/config.py and backend/app/config.py differ
  Files .superpowers/sdd/SECURITY_A_PLAN/snap-task1-r2-app/user_store.py and backend/app/user_store.py differ
## app diff
Binary files .superpowers/sdd/SECURITY_A_PLAN/snap-task1-r2-app/__pycache__/config.cpython-313.pyc and backend/app/__pycache__/config.cpython-313.pyc differ
Binary files .superpowers/sdd/SECURITY_A_PLAN/snap-task1-r2-app/__pycache__/user_store.cpython-313.pyc and backend/app/__pycache__/user_store.cpython-313.pyc differ
diff -ruN -U10 .superpowers/sdd/SECURITY_A_PLAN/snap-task1-r2-app/config.py backend/app/config.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task1-r2-app/config.py	2026-09-25 16:52:52.062239300 +0800
+++ backend/app/config.py	2026-09-25 17:08:30.829660600 +0800
@@ -152,20 +152,25 @@
     retrieval_max_chunks_per_document: int = Field(default=2, ge=1, le=10)
     retrieval_query_context_max_chars: int = Field(default=320, ge=80, le=1000)
 
     jwt_secret: str = "change-me-before-production-yaoke-demo-secret"
     jwt_expire_hours: int = 8
 
     # Argon2 并发槽上限（可用性旋钮）。**密码学档位不在这里**：m/t/p 固定在
     # app/credentials.py 的常量上，改它等于改规格（SEC-A-008）。
     argon2_max_concurrent_ops: int = 2
 
+    # 凭据表与会话面同库（规格 §6.1），所以路径的 env 键也同一个：`CONVERSATION_DB_PATH`。
+    # 这里放的只是「env 未设时的默认值」——生效路径由调用方在**每次连接时**读 env，
+    # 与 `conversation_store` / `llm.usage` 一个口径（测试护栏的会话级重定向靠这一点）。
+    conversation_db_path: str = "data/conversations.db"
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
diff -ruN -U10 .superpowers/sdd/SECURITY_A_PLAN/snap-task1-r2-app/user_store.py backend/app/user_store.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task1-r2-app/user_store.py	1970-01-01 08:00:00.000000000 +0800
+++ backend/app/user_store.py	2026-09-25 17:48:02.439145300 +0800
@@ -0,0 +1,302 @@
+"""凭据状态持久层（规格 §6.1）。
+
+这里只放**凭据状态**。身份（role / display_name / feishu_open_id）在 directory.py，
+口令原语在 credentials.py。三处不得混，否则 SEC-A-010 的两个真源开始互相覆写。
+"""
+
+from __future__ import annotations
+
+import os
+import sqlite3
+from contextlib import closing
+from dataclasses import dataclass
+from datetime import datetime, timedelta, timezone
+from pathlib import Path
+
+from app import credentials
+from app.config import settings
+
+TABLE_NAME = "user_credentials"
+
+# 与会话面同库 ⇒ 写锁是真会撞上的，超时口径照 `ConversationStore`（默认 5s 会把
+# 一次正常的登录写变成 "database is locked"）。
+_WRITE_TIMEOUT_SECONDS = 30.0
+
+_SCHEMA = f"""
+CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
+  username            TEXT PRIMARY KEY,
+  algorithm           TEXT NOT NULL CHECK (algorithm IN ('{credentials.ALGORITHM_ARGON2ID}','{credentials.ALGORITHM_LEGACY_SHA256}')),
+  password_hash       TEXT NOT NULL,
+  credentials_version INTEGER NOT NULL DEFAULT 1,
+  must_change         INTEGER NOT NULL DEFAULT 0,
+  failed_attempts     INTEGER NOT NULL DEFAULT 0,
+  locked_until        TEXT,
+  updated_at          TEXT NOT NULL
+);
+"""
+
+_COLUMNS = (
+    "username",
+    "algorithm",
+    "password_hash",
+    "credentials_version",
+    "must_change",
+    "failed_attempts",
+    "locked_until",
+    "updated_at",
+)
+
+
+class CredentialStoreError(RuntimeError):
+    """存储层事故（连接、约束、版本冲突）。调用方不得把它当"口令错了"。"""
+
+
+@dataclass(frozen=True)
+class CredentialRecord:
+    username: str
+    algorithm: str
+    password_hash: str
+    credentials_version: int
+    must_change: bool
+    failed_attempts: int
+    locked_until: str | None
+    updated_at: str
+
+
+#: 已经建过表的文件。按**路径**比对而不是布尔旗标：换库（测试夹具、CLI 指到别的
+#: 数据目录）不依赖"有人记得 reload 本模块"来重置状态。
+_schema_ready_path: str | None = None
+
+
+def _database_path() -> Path:
+    """生效路径在**每次连接时**解析，绝不在 import 期钉死。
+
+    `settings.conversation_db_path` 给的是"env 未设"时的默认值；env 必须在调用点读，
+    因为测试护栏的会话级重定向发生在用例开始时（`tests/conftest.py` 的 session
+    fixture 设 `CONVERSATION_DB_PATH`），而 import 发生在更早的收集期——那时取到的
+    默认值恰好就是 `backend/data/conversations.db` 那份真库（V2.3 的污染事故形态）。
+    """
+    configured = os.getenv("CONVERSATION_DB_PATH") or settings.conversation_db_path
+    return Path(configured).expanduser()
+
+
+def _connect() -> sqlite3.Connection:
+    target = _database_path()
+    target.parent.mkdir(parents=True, exist_ok=True)
+    connection = sqlite3.connect(str(target), timeout=_WRITE_TIMEOUT_SECONDS)
+    connection.row_factory = sqlite3.Row
+    global _schema_ready_path
+    if _schema_ready_path != str(target):
+        # 建表是一次独立的提交单位：留在调用方那条事务里，一旦业务写入回滚就会连
+        # 表一起消失（下一句又变成"no such table"）。并发下两条线程都跑到这里也无害
+        # ——`IF NOT EXISTS` 幂等，不值得为它加锁。
+        connection.executescript(_SCHEMA)
+        connection.commit()
+        _schema_ready_path = str(target)
+    return connection
+
+
+def ensure_user_credentials_schema() -> None:
+    with closing(_connect()) as connection, connection:
+        connection.executescript(_SCHEMA)
+
+
+def column_names() -> list[str]:
+    with closing(_connect()) as connection:
+        rows = connection.execute(f"PRAGMA table_info({TABLE_NAME})").fetchall()
+    return [str(row["name"]) for row in rows]
+
+
+def _now() -> str:
+    return datetime.now(timezone.utc).isoformat()
+
+
+def _record_from(row: sqlite3.Row) -> CredentialRecord:
+    return CredentialRecord(
+        username=str(row["username"]),
+        algorithm=str(row["algorithm"]),
+        password_hash=str(row["password_hash"]),
+        credentials_version=int(row["credentials_version"]),
+        must_change=bool(int(row["must_change"])),
+        failed_attempts=int(row["failed_attempts"]),
+        locked_until=None if row["locked_until"] is None else str(row["locked_until"]),
+        updated_at=str(row["updated_at"]),
+    )
+
+
+def get_record(username: str) -> CredentialRecord | None:
+    with closing(_connect()) as connection:
+        row = connection.execute(
+            f"SELECT * FROM {TABLE_NAME} WHERE username = ?", (str(username),)
+        ).fetchone()
+    return None if row is None else _record_from(row)
+
+
+def list_records() -> list[CredentialRecord]:
+    with closing(_connect()) as connection:
+        rows = connection.execute(f"SELECT * FROM {TABLE_NAME} ORDER BY username").fetchall()
+    return [_record_from(row) for row in rows]
+
+
+def count_by_algorithm() -> dict[str, int]:
+    with closing(_connect()) as connection:
+        rows = connection.execute(
+            f"SELECT algorithm, COUNT(*) AS n FROM {TABLE_NAME} GROUP BY algorithm"
+        ).fetchall()
+    return {str(row["algorithm"]): int(row["n"]) for row in rows}
+
+
+def create_argon2(username: str, *, plain_password: str, must_change: bool) -> int:
+    """唯一的新建口令入口。没有 algorithm 参数——legacy 因此不可达（SECA-01）。"""
+    encoded = credentials.hash_password(plain_password)
+    with closing(_connect()) as connection, connection:
+        connection.execute(
+            f"INSERT INTO {TABLE_NAME} (username, algorithm, password_hash,"
+            " credentials_version, must_change, failed_attempts, locked_until, updated_at)"
+            " VALUES (?, ?, ?, 1, ?, 0, NULL, ?)",
+            (
+                str(username),
+                credentials.ALGORITHM_ARGON2ID,
+                encoded,
+                1 if must_change else 0,
+                _now(),
+            ),
+        )
+    # 返回的不是占位：刚落库的就是版本 1，Task 7 的 CLI 要把它打印出来。
+    return 1
+
+
+def import_legacy_digest(username: str, digest_hex: str, *, must_change: bool) -> bool:
+    """**受限迁移路径**：全仓唯一能写出 legacy 行的函数（SEC-A-004）。
+
+    命名里带 legacy、且只被 credentials_migration 调用；SECA-05 的 AST 扫描与
+    Task 3 的调用方扫描共同钉住这一点。
+    """
+    encoded = str(digest_hex).strip().lower()
+    with closing(_connect()) as connection, connection:
+        cursor = connection.execute(
+            f"INSERT INTO {TABLE_NAME} (username, algorithm, password_hash,"
+            " credentials_version, must_change, failed_attempts, locked_until, updated_at)"
+            " VALUES (?, ?, ?, 1, ?, 0, NULL, ?)"
+            " ON CONFLICT(username) DO NOTHING",
+            (
+                str(username),
+                credentials.ALGORITHM_LEGACY_SHA256,
+                encoded,
+                1 if must_change else 0,
+                _now(),
+            ),
+        )
+    return cursor.rowcount > 0
+
+
+def set_password_argon2(username: str, *, plain_password: str, must_change: bool) -> int:
+    """改密 / 管理员重置共用的一条事务。
+
+    新 hash + credentials_version bump + 清锁 + updated_at 在**一个** connection
+    事务里提交：跨事务会留下"口令已换、旧 token 仍有效"的提交窗口（SECA-11），
+    不清锁会让管理员 reset 之后用户仍被旧 lock 挡住（SECA-12）。
+    """
+    encoded = credentials.hash_password(plain_password)
+    with closing(_connect()) as connection, connection:
+        _bump_and_clear(
+            connection,
+            username=str(username),
+            algorithm=credentials.ALGORITHM_ARGON2ID,
+            encoded=encoded,
+            must_change=must_change,
+        )
+        row = connection.execute(
+            f"SELECT credentials_version FROM {TABLE_NAME} WHERE username = ?",
+            (str(username),),
+        ).fetchone()
+        if row is None:
+            raise CredentialStoreError(f"账号不存在：{username}")
+        return int(row["credentials_version"])
+
+
+def _bump_and_clear(
+    connection: sqlite3.Connection,
+    *,
+    username: str,
+    algorithm: str,
+    encoded: str,
+    must_change: bool,
+) -> None:
+    connection.execute(
+        f"UPDATE {TABLE_NAME} SET algorithm = ?, password_hash = ?,"
+        " credentials_version = credentials_version + 1, must_change = ?,"
+        " failed_attempts = 0, locked_until = NULL, updated_at = ?"
+        " WHERE username = ?",
+        (algorithm, encoded, 1 if must_change else 0, _now(), username),
+    )
+
+
+def apply_rehash(
+    username: str,
+    *,
+    plain_password: str,
+    must_change: bool,
+    expected_version: int,
+) -> bool:
+    """渐进重哈希。**不** bump 版本：登录不改会话，只改强度。
+
+    版本作为乐观锁参与 WHERE，并发改密时这条 UPDATE 会落空并返回 False，
+    由调用方（登录腿）当作"已放弃收敛，不算失败"处理。
+    """
+    encoded = credentials.hash_password(plain_password)
+    with closing(_connect()) as connection, connection:
+        cursor = connection.execute(
+            f"UPDATE {TABLE_NAME} SET algorithm = ?, password_hash = ?, must_change = ?,"
+            " updated_at = ? WHERE username = ? AND credentials_version = ?",
+            (
+                credentials.ALGORITHM_ARGON2ID,
+                encoded,
+                1 if must_change else 0,
+                _now(),
+                str(username),
+                int(expected_version),
+            ),
+        )
+    return cursor.rowcount > 0
+
+
+def record_login_failure(username: str, *, max_attempts: int, lock_seconds: int) -> bool:
+    """账号级持久失败计数（规格 §7.2 第二层），键只有 username。"""
+    with closing(_connect()) as connection, connection:
+        cursor = connection.execute(
+            f"UPDATE {TABLE_NAME} SET failed_attempts = failed_attempts + 1,"
+            " updated_at = ? WHERE username = ?",
+            (_now(), str(username)),
+        )
+        if cursor.rowcount == 0:
+            return False
+        row = connection.execute(
+            f"SELECT failed_attempts FROM {TABLE_NAME} WHERE username = ?",
+            (str(username),),
+        ).fetchone()
+        locked_now = int(row["failed_attempts"]) >= int(max_attempts)
+        if locked_now:
+            until = (datetime.now(timezone.utc) + timedelta(seconds=int(lock_seconds))).isoformat()
+            connection.execute(
+                f"UPDATE {TABLE_NAME} SET locked_until = ? WHERE username = ?",
+                (until, str(username)),
+            )
+    return locked_now
+
+
+def clear_login_failures(username: str) -> None:
+    with closing(_connect()) as connection, connection:
+        connection.execute(
+            f"UPDATE {TABLE_NAME} SET failed_attempts = 0, locked_until = NULL"
+            " WHERE username = ?",
+            (str(username),),
+        )
+
+
+def delete_record(username: str) -> bool:
+    with closing(_connect()) as connection, connection:
+        cursor = connection.execute(
+            f"DELETE FROM {TABLE_NAME} WHERE username = ?", (str(username),)
+        )
+    return cursor.rowcount > 0
## test diff
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task1-r2-test.py	2026-09-25 16:52:52.503210500 +0800
+++ backend/tests/test_credentials_contract.py	2026-09-25 17:24:29.318074300 +0800
@@ -1,25 +1,29 @@
 from __future__ import annotations
 
 import ast
 import hashlib
+import importlib
+import inspect
+import os
 import re
 import sys
+import tempfile
 import threading
 import unittest
 from pathlib import Path
 from unittest import mock
 
 BACKEND_DIR = Path(__file__).resolve().parents[1]
 sys.path.insert(0, str(BACKEND_DIR))
 
-from app import credentials  # noqa: E402
+from app import credentials, user_store  # noqa: E402
 
 
 class Argon2ProfileTests(unittest.TestCase):
     def test_profile_is_the_owasp_minimum_baseline_and_is_a_code_constant(self):
         self.assertEqual(2, credentials.ARGON2_TIME_COST)
         self.assertEqual(19456, credentials.ARGON2_MEMORY_COST)
         self.assertEqual(1, credentials.ARGON2_PARALLELISM)
 
     def test_hasher_exposes_one_shared_instance_at_that_profile(self):
         # 上游登录腿的测试会把 `credentials.hasher()` 返回对象的 verify 打桩：hasher() 每
@@ -313,10 +317,137 @@
         for source in self.PASSWORD_SITE_SHAPES:
             with self.subTest(binding=source.splitlines()[0]):
                 self.assertEqual(
                     1, len(self._hashlib_password_calls(ast.parse(source)))
                 )
 
     def test_a_non_password_digest_stays_out_of_the_hit_set_under_every_binding(self):
         for source in self.NON_PASSWORD_SHAPES:
             with self.subTest(binding=source.splitlines()[0]):
                 self.assertEqual([], self._hashlib_password_calls(ast.parse(source)))
+
+
+class _CredentialDbPerTest(unittest.TestCase):
+    """每例一份临时库：`CONVERSATION_DB_PATH` 指到 tmp，收尾还原 env。
+
+    三件事一起办：
+    ① 凭据表与会话面**同库**，用例不各占一份文件就会互相撞
+    `user_credentials.username` 这条主键（同名账号在这些用例里是常态）。
+    ② 出厂默认是**相对**路径 `data/conversations.db` ⇒ 不重定向的用例等于往仓库里
+    那份真库写假凭据行。
+    ③ **不动 `app.config`**：`settings` 是进程级单例，`app.main` / `app.llm.*` 在
+    import 期就把那个对象绑进了自己的命名空间。reload 换掉的只是
+    `app.config.settings` 这个模块属性，后面跑的用例（真起 lifespan、按 settings 覆盖
+    cwd 敏感键）改的是再没人读的那一份，症状是一份不相干的 FileNotFoundError。
+    换库只靠 env 就够：生效路径由 `user_store._database_path()` 在每次连接时解析。
+    """
+
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self._saved_db_path = os.environ.get("CONVERSATION_DB_PATH")
+        os.environ["CONVERSATION_DB_PATH"] = str(Path(self._tmp.name) / "creds.db")
+        importlib.reload(user_store)
+        user_store.ensure_user_credentials_schema()
+
+    def tearDown(self):
+        if self._saved_db_path is None:
+            os.environ.pop("CONVERSATION_DB_PATH", None)
+        else:
+            os.environ["CONVERSATION_DB_PATH"] = self._saved_db_path
+        importlib.reload(user_store)
+        self._tmp.cleanup()
+
+
+class UserStoreSchemaTests(_CredentialDbPerTest):
+    def test_column_set_may_hold_a_hash_but_never_a_plaintext_field(self):
+        """SECA-08：明文字段不是"没人写"，是"不存在可写的地方"。"""
+        columns = set(user_store.column_names())
+        self.assertIn("password_hash", columns)
+        self.assertTrue({"password", "plaintext_password", "raw_password"}.isdisjoint(columns))
+        self.assertNotIn(
+            "algorithm",
+            inspect.signature(user_store.create_argon2).parameters,
+        )
+        self.assertNotIn(
+            "algorithm",
+            inspect.signature(user_store.set_password_argon2).parameters,
+        )
+
+    def test_created_rows_are_always_argon2id(self):
+        """SECA-01 的持久层半边：普通写路径拿不到 legacy 这个取值。"""
+        user_store.create_argon2("admin", plain_password="a-good-password 123", must_change=False)
+        record = user_store.get_record("admin")
+        self.assertEqual(credentials.ALGORITHM_ARGON2ID, record.algorithm)
+        self.assertTrue(record.password_hash.startswith("$argon2id$"))
+        self.assertEqual(1, record.credentials_version)
+
+    def test_only_the_restricted_importer_can_create_a_legacy_row(self):
+        self.assertTrue(
+            user_store.import_legacy_digest(
+                "sales01", hashlib.sha256(b"sales123").hexdigest(), must_change=True
+            )
+        )
+        record = user_store.get_record("sales01")
+        self.assertEqual(credentials.ALGORITHM_LEGACY_SHA256, record.algorithm)
+        self.assertTrue(record.must_change)
+        self.assertEqual(
+            {credentials.ALGORITHM_LEGACY_SHA256: 1},
+            {k: v for k, v in user_store.count_by_algorithm().items() if v},
+        )
+
+
+class UserStoreTransactionTests(_CredentialDbPerTest):
+    """SECA-11 / SECA-12：新 hash、bump、清锁必须是一个提交单位。"""
+
+    def test_password_change_bumps_version_and_clears_lock_state_together(self):
+        user_store.create_argon2("admin", plain_password="old-password 123456", must_change=True)
+        user_store.record_login_failure(
+            "admin", max_attempts=1, lock_seconds=900
+        )
+        self.assertIsNotNone(user_store.get_record("admin").locked_until)
+
+        new_version = user_store.set_password_argon2(
+            "admin", plain_password="new-password 123456", must_change=False
+        )
+        record = user_store.get_record("admin")
+        self.assertEqual(new_version, record.credentials_version)
+        self.assertEqual(2, record.credentials_version)
+        self.assertFalse(record.must_change)
+        self.assertEqual(0, record.failed_attempts)
+        self.assertIsNone(record.locked_until)
+
+    def test_a_failing_version_bump_rolls_back_the_new_hash(self):
+        user_store.create_argon2("admin", plain_password="old-password 123456", must_change=False)
+        before = user_store.get_record("admin")
+        with mock.patch.object(
+            user_store, "_bump_and_clear", side_effect=user_store.CredentialStoreError("boom")
+        ):
+            with self.assertRaises(user_store.CredentialStoreError):
+                user_store.set_password_argon2(
+                    "admin", plain_password="new-password 123456", must_change=False
+                )
+        after = user_store.get_record("admin")
+        self.assertEqual(before.password_hash, after.password_hash)
+        self.assertEqual(before.credentials_version, after.credentials_version)
+
+    def test_rehash_is_guarded_by_the_version_it_was_computed_for(self):
+        user_store.create_argon2("admin", plain_password="old-password 123456", must_change=True)
+        self.assertTrue(
+            user_store.apply_rehash(
+                "admin",
+                plain_password="old-password 123456",
+                must_change=True,
+                expected_version=user_store.get_record("admin").credentials_version,
+            )
+        )
+        record = user_store.get_record("admin")
+        self.assertEqual(credentials.ALGORITHM_ARGON2ID, record.algorithm)
+        # 陈旧版本（并发下别人已经改过密）⇒ 整条 UPDATE 不落地
+        self.assertFalse(
+            user_store.apply_rehash(
+                "admin",
+                plain_password="old-password 123456",
+                must_change=False,
+                expected_version=record.credentials_version + 5,
+            )
+        )
+        self.assertTrue(user_store.get_record("admin").must_change)

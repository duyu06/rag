## Task 2: 凭据状态持久层（`user_store.py`）

**Files:**
- Create: `backend/app/user_store.py`
- Test: `backend/tests/test_credentials_contract.py`（追加两个 TestCase）

**Interfaces:**
- Consumes: `credentials.hash_password` / `verify_password` / `ALGORITHM_*` / `CredentialConfigError`；`app.conversation_store` 的连接获取方式（同库 `data/conversations.db`，沿用 `settings.conversation_db_path` 与其环境覆盖，Task 里叫 `_connect()`）
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


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(str(settings.conversation_db_path))
    connection.row_factory = sqlite3.Row
    return connection


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


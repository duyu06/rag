"""凭据状态持久层（规格 §6.1）。

这里只放**凭据状态**。身份（role / display_name / feishu_open_id）在 directory.py，
口令原语在 credentials.py。三处不得混，否则 SEC-A-010 的两个真源开始互相覆写。
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import credentials

TABLE_NAME = "user_credentials"

# 与会话面同库 ⇒ 写锁是真会撞上的，超时口径照 `ConversationStore`（默认 5s 会把
# 一次正常的登录写变成 "database is locked"）。
_WRITE_TIMEOUT_SECONDS = 30.0

#: 凭据表落在哪个文件，取值口径与两个同库读者**逐字相同**：
#: `conversation_store.ConversationStore.__init__`（`os.getenv("CONVERSATION_DB_PATH",
#: "data/conversations.db")`）与 `llm.usage.database_path`。规格 §6.1 要求本表与
#: `conversations` 同一个文件，所以只能有一个真源。
_DB_PATH_ENV_VAR = "CONVERSATION_DB_PATH"
_DB_PATH_DEFAULT = "data/conversations.db"

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

#: 列清单的**唯一**声明处：两条 INSERT 的列名段由它生成（`_insert_sql`），"它确实是表的
#: 列序"由用例钉（`_COLUMNS == tuple(column_names())`）。往 `_SCHEMA` 加一列时这里必须
#: 跟着改，否则那枚等值钉直接红——列序从此不再需要人记。
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

#: 两条消息都是**固定文案**（公开常量），但**分派形状不同**，别照同一写法用：
#: `ACCOUNT_MISSING_MESSAGE` 是整条消息（抛的就是这个常量本身）⇒ 可以 `==` 等值分派；
#: `ACCOUNT_EXISTS_MESSAGE` 只到"："为止（抛出的是 `f"{常量}：{username}"`，见 `create_argon2`）
#: ⇒ 只能 `startswith` 分派，等值比较它永远不成立。两枚都不必去 match 驱动文案。
#: 分类型：都是"存储层事故"，都不是"口令错了"。
#:
#: `ACCOUNT_MISSING_MESSAGE` 刻意**不含账号名**：§9.1 把「有身份无凭据行」折成与口令错
#: 同一条 401（`用户名或密码错误` / `invalid_credentials`），而这条异常在登录/改密腿上被
#: 捕获——消息一旦含账号名，任何把 `str(exc)` 往响应面或审计 detail 送的写法都会变成
#: "这个用户名存在吗"的探针，且自由文本进审计字段本身违 §9.1 末段。
#: `ACCOUNT_EXISTS_MESSAGE` 只在启动期（种子 / bootstrap）出现，那里账号名本就是配置项，
#: 带上它才有法定位；两者都不含驱动文案，也不含任何口令材料。
ACCOUNT_MISSING_MESSAGE = "凭据行缺失（目标账号在本表没有记录）"
ACCOUNT_EXISTS_MESSAGE = "凭据行已存在（目标账号在本表已有记录）"


class CredentialStoreError(RuntimeError):
    """存储层事故（连接、约束、版本冲突）。调用方不得把它当"口令错了"。"""


@dataclass(frozen=True)
class CredentialRecord:
    username: str
    algorithm: str
    password_hash: str = field(repr=False)
    credentials_version: int
    must_change: bool
    failed_attempts: int
    locked_until: str | None
    updated_at: str


def database_path() -> Path:
    """凭据表落在哪个文件：env `CONVERSATION_DB_PATH`，默认 `data/conversations.db`。

    口径与两个同库读者一致，且**不读 `app.config.settings`**：`settings` 会加载 `.env`
    （dotenv），而 `conversation_store` 与 `llm.usage` 只看 `os.environ`。这里一旦改读
    `settings`，运维把该键在 `.env` 里挪成绝对路径时就只搬走凭据表，会话表留在原文件
    ——备份/轮转跟着错文件走，正是规格 §6.1 要防的分叉。

    每次连接时解析、且只有这一个解析点：会话级测试护栏（`tests/conftest.py`）改道
    `usage` 的手法就是换掉模块级的 `database_path`，本模块要能被同一个手法包走。
    import 期钉死更不行——护栏的重定向发生在用例开始时，比 import 晚。
    """
    return Path(os.getenv(_DB_PATH_ENV_VAR, _DB_PATH_DEFAULT)).expanduser()


def _connect() -> sqlite3.Connection:
    target = database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(target), timeout=_WRITE_TIMEOUT_SECONDS)
    connection.row_factory = sqlite3.Row
    # 这里**不建表**：`ensure_user_credentials_schema()` 是全模块唯一的建表者。读函数
    # 每次都顺手建表，等于在"env 被清掉 ⇒ 路径退回默认值"的任何一次调用里往那个文件
    # 提交一次 DDL —— 落点可能是生产库，而生产库长出半张凭据表是无人报警的事。
    # 没建过表就报错（`no such table`）才是想要的症状：它指向漏调初始化的人。
    return connection


def ensure_user_credentials_schema() -> None:
    """建表（`IF NOT EXISTS`，幂等）——本模块唯一的 schema 出处。"""
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


#: 新建语句共用的取值段：`credentials_version` / `failed_attempts` / `locked_until` 写成
#: 字面量（首版恒 1、无失败计数、未锁定），其余 5 列由实参供值 ⇒ 恰好 5 个 `?`。
_INSERT_VALUES = " VALUES (?, ?, ?, 1, ?, 0, NULL, ?)"


def _insert_sql(*, ignore_conflicts: bool) -> str:
    """两条新建路径共用的 INSERT 文本，列名段由 `_COLUMNS` 生成。

    收拢前这两条语句是逐字抄了两遍的 8 个列名；现在列序的真源只有两处（`_SCHEMA`
    与 `_COLUMNS`），并由用例钉成相等。文本与收拢前逐字节相同——不带 `ON CONFLICT`
    的那条与字面量等值钉在一起，所以这次收拢不是语义改动。
    """
    statement = f"INSERT INTO {TABLE_NAME} ({', '.join(_COLUMNS)}){_INSERT_VALUES}"
    if ignore_conflicts:
        return f"{statement} ON CONFLICT(username) DO NOTHING"
    return statement


def create_argon2(username: str, *, plain_password: str, must_change: bool) -> int:
    """唯一的新建口令入口。没有 algorithm 参数——legacy 因此不可达（SECA-01）。"""
    encoded = credentials.hash_password(plain_password)
    with closing(_connect()) as connection, connection:
        try:
            connection.execute(
                _insert_sql(ignore_conflicts=False),
                (
                    str(username),
                    credentials.ALGORITHM_ARGON2ID,
                    encoded,
                    1 if must_change else 0,
                    _now(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            # 这条语句只有主键可能撞（其余列全由实参或字面量供值，非空与 CHECK 恒满足）。
            # 调用方（种子 / bootstrap）都是先查后写，撞上意味着并发或查漏了——那是一条
            # 存储层事故，得说本模块的话：裸驱动文案（`UNIQUE constraint failed:
            # user_credentials.username`）会原样进服务端日志和运维控制台。原文留在
            # `__cause__` 里，定位能力一点没丢。
            raise CredentialStoreError(
                f"{ACCOUNT_EXISTS_MESSAGE}：{username}"
            ) from exc
    # 返回的不是占位：新建行的 credentials_version 恒为 1（列默认值与 INSERT 里那枚字面量
    # 是同一个取值），而调用方（bootstrap CLI / 启动种子）要打印的正是"刚落库的版本号"——
    # 改成 None 就把这条事实从输出里丢了。
    return 1


def import_legacy_digest(username: str, digest_hex: str, *, must_change: bool) -> bool:
    """**受限迁移路径**：全仓唯一能写出 legacy 行的函数（SEC-A-004）。

    命名里带 legacy、且只被迁移器（`credentials_migration`）调用；SECA-05 的 AST 扫描与
    对调用方的扫描共同钉住这一点——所以"谁能写出 legacy"是机器判据，不是约定。
    """
    encoded = str(digest_hex).strip().lower()
    with closing(_connect()) as connection, connection:
        cursor = connection.execute(
            _insert_sql(ignore_conflicts=True),
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
            # 固定文案、零账号名：见 `ACCOUNT_MISSING_MESSAGE` 的由来（§9.1 把这一态与
            # 口令错折成同一条 401，消息本身必须可以直接过响应面而不泄露账号存在性）。
            raise CredentialStoreError(ACCOUNT_MISSING_MESSAGE)
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

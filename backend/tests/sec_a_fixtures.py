"""SEC-A 契约用例的公共地基：换库、审计临时落点、够长的 JWT secret。

这三件事各自都是**安全机制**，不是省代码：

- `fresh_db`：每例一份 SQLite 文件。会反复 bump / 删除凭据行的用例共用一份库，就是在共享
  状态里互相踩对方的 token 生命周期。只换 env、不 reload 模块——`importlib.reload(user_store)`
  会把会话护栏挂在它上面的两道闸换回裸函数，reload `app.config` 则把 `settings` 这个进程级
  单例从 `app.main` / `app.llm.*` 的命名空间里换走，之后跑的用例改的是再没人读的那一份。
- `AuditToTempFileMixin`：审计写到临时文件。仓库里的 `data/audit.jsonl` 一旦混进测试笔迹，
  既污染运维读物，也让"这套件没碰真数据"失去可核对性。
- `LongJwtSecretMixin`：用例自带一枚 ≥32 字节的 JWT secret。默认 dev secret 短于 PyJWT 的建议
  下限，每次签发/校验都喊一句 `InsecureKeyLengthWarning`；那是 secret 卫生自己的账，不该跟着
  用例数漂移——"整套件警告数不变"是本仓的回归信号。所以选配的写法是换 `settings.jwt_secret`，
  不静音警告（静音会把别的来源的同一枚警告一起藏掉）。

同一个机制在两个契约文件里各抄一份，等着的就是下一次只改其中一份；所以这里只留一份实现，
两边都从这里导入。文件名与 secret 字面量仍由调用方给：不同文件的 token 不共用一把钥匙，
警告与撤销的归因才分得开。`app` 侧的三枚模块都在函数里取——本模块不许假设调用方已经排好
`sys.path`（`sec_a_seed` 同此），import 期炸掉的栈也比运行期难读。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

#: 凭据表落在哪个文件由这枚 env 决定（唯一真源是 `user_store.database_path()`，它只看
#: `os.environ`、默认 `data/conversations.db`）。换库 = 换这枚变量，没有第二条路。
DB_PATH_ENV_VAR = "CONVERSATION_DB_PATH"


def fresh_db(test: unittest.TestCase, *, filename: str = "sec-a.db") -> Path:
    """把**当前生效库**换成一份临时文件并建好凭据表，返回那个文件的路径。

    建表在换 env **之后**：`user_store` 的读路径刻意不建表（没初始化就报 `no such table`，
    指向漏调初始化的人），而落点跟着 env 走。
    """
    from app import login_throttle, user_store

    # 换库的同时清节流表：本文件的用例逐例重建世界，第一层的桶不属于"这个世界"的上一份。
    login_throttle.pre_hash_throttle.reset()

    holder = tempfile.TemporaryDirectory()
    target = Path(holder.name) / filename
    saved = os.environ.get(DB_PATH_ENV_VAR)
    os.environ[DB_PATH_ENV_VAR] = str(target)
    user_store.ensure_user_credentials_schema()

    def restore() -> None:
        if saved is None:
            os.environ.pop(DB_PATH_ENV_VAR, None)
        else:
            os.environ[DB_PATH_ENV_VAR] = saved
        holder.cleanup()

    test.addCleanup(restore)
    return target


class AuditToTempFileMixin:
    """审计落到临时文件：既取到证，又不往仓库的 `data/audit.jsonl` 里写测试笔迹。

    接缝打在 `app.audit.AUDIT_PATH` 上而不是 env：那是写手每次调用都取用的那一个名字。
    """

    audit_path: Path

    def setUp(self) -> None:
        from app import audit as audit_module

        super().setUp()  # type: ignore[misc]
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)  # type: ignore[attr-defined]
        self.audit_path = Path(holder.name) / "audit.jsonl"
        patcher = mock.patch.object(audit_module, "AUDIT_PATH", self.audit_path)
        patcher.start()
        self.addCleanup(patcher.stop)  # type: ignore[attr-defined]

    def events(self) -> list[dict]:
        if not self.audit_path.is_file():
            return []
        return [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


class LongJwtSecretMixin:
    """给用例配一枚够长的 JWT secret（≥32 字节），取值由子类的 `SECRET` 给出。

    `SECRET` 空着就跑不起来：那正好是"警告计数会漂"的形状，宁可当场报错，也不让一个忘了
    配钥匙的文件安静地把整套件的基线挪走。
    """

    SECRET: str = ""

    def setUp(self) -> None:
        from app import config as config_module

        super().setUp()  # type: ignore[misc]
        if len(self.SECRET.encode("utf-8")) < 32:
            raise AssertionError(
                "子类必须给一枚 ≥32 字节的 JWT secret：短于 PyJWT 建议下限会让每次签发都"
                "多一句警告，套件警告计数就不再是回归信号"
            )
        patcher = mock.patch.object(config_module.settings, "jwt_secret", self.SECRET)
        patcher.start()
        self.addCleanup(patcher.stop)  # type: ignore[attr-defined]

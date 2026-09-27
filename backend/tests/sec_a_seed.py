"""SEC-A 测试地基：既有登录用例的口令字面量不改，脚下换成 argon2id 行。

Argon2 是内存硬哈希：每用例重算会把套件拖成分钟级，所以整个会话只算 5 次。
换库的夹具要「自己库里就有行」时走 `install_demo_credentials()`——那是**整份复制**进程内
算好的模板文件，不额外付 Argon2；`ensure_demo_credentials()` 才是真的写行。
`SEED_RECORD` 让"只种了一次"这件事可断言（SECA-24），且计数器住在测试侧，
生产代码不为用户形状服务。

规格 §8.2 把这条路径钉成"全新安装的凭据来源"：生产代码不 seed legacy，缺凭据行也
不自动导入升级工件（那是升级腿唯一的事），所以测试面必须自己把行种出来。
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

DEMO_TEST_CREDENTIALS: dict[str, str] = {
    "admin": "admin123",
    "sales01": "sales123",
    "hr01": "hr123",
    "user": "user123",
    "viewer": "viewer123",
}

#: 凭据表落在哪个文件由这枚 env 决定（唯一真源是 `user_store.database_path()`，它只看
#: `os.environ`、默认 `data/conversations.db`）。"这一份文件里要有那五行"这类义务要能指名
#: 落点，靠的就是把当前生效路径换成目标文件，所以这里给它一个名字而不是散落字面量。
_DB_PATH_ENV_VAR = "CONVERSATION_DB_PATH"

#: 会话级 seed 的台账：只有 `seed_demo_credentials()` 往里写。用例自建的临时库里补种
#: 账号走 `ensure_demo_credentials()`，那是"这一例的夹具需要一行凭据"，不是"会话又种了一遍"，
#: 混进这本台账就会让 SECA-24 的计数随用例数漂移（而这正是它要判红的那件事）。
SEED_RECORD: list[str] = []


def ensure_demo_credentials(*usernames: str) -> list[str]:
    """把 demo 凭据行种进**当前生效**的库，返回本次真的新建的账号名（幂等）。

    自带建表：`user_store` 的读路径刻意不建表（没初始化就报 `no such table`，指向漏调
    初始化的人），所以换库的夹具必须先过这一道。口令全是本模块里的测试字面量，
    账号名与 `config/users.demo.json` 一一对上。
    """
    from app import user_store

    user_store.ensure_user_credentials_schema()
    targets = DEMO_TEST_CREDENTIALS if not usernames else {
        name: DEMO_TEST_CREDENTIALS[name] for name in usernames
    }
    created: list[str] = []
    for username, password in targets.items():
        if user_store.get_record(username) is None:
            user_store.create_argon2(username, plain_password=password, must_change=False)
            created.append(username)
    return created


def seed_demo_credentials() -> None:
    """会话级 seed：整套套件该被叫**一次**，5 次 Argon2 运算就是这个上限。"""
    SEED_RECORD.extend(ensure_demo_credentials())


#: 进程级凭据模板：一份**只含** `user_credentials`（5 行 argon2id，零别的）的库文件。
#: 换库的夹具需要"自己库里就有行"，但那不等于"每例再付 5 次 Argon2"——上面那句预算
#: 说的正是这件事。模板由第一次用到它的夹具惰性建出来，整个进程只建一次、只付一次
#: 运算；此后**新建**落点都是整份文件复制（没有 SQL、没有列清单，也就没有和 schema 漂移的
#: 第二份真源：模板里的行本身是 `create_argon2` 写的，和会话 seed 走的是同一条腿），
#: 落点已在场时只朝那一个文件补缺的行，已有行一根手指都不碰。
_TEMPLATE_HOLDER: "tempfile.TemporaryDirectory | None" = None


def _ensure_credentials_at(target: Path) -> None:
    """把 demo 凭据行种进**指定那一个**文件，而不是"当前 env 恰好解析到的那一个"。

    `ensure_demo_credentials()` 的落点是 env 的函数，而"这个文件里要有那五行"这个义务的对象
    是 `target`：两者不一致时补种种到了别人家，目标文件还是没行，症状却仍是登录面上的 401。
    """
    saved = os.environ.get(_DB_PATH_ENV_VAR)
    os.environ[_DB_PATH_ENV_VAR] = str(target)
    try:
        ensure_demo_credentials()
    finally:
        if saved is None:
            os.environ.pop(_DB_PATH_ENV_VAR, None)
        else:
            os.environ[_DB_PATH_ENV_VAR] = saved


def credential_template() -> Path:
    """本进程为模板付的那一次运算，返回那份库文件的路径（幂等）。"""
    global _TEMPLATE_HOLDER
    if _TEMPLATE_HOLDER is None:
        _TEMPLATE_HOLDER = tempfile.TemporaryDirectory()
    template = Path(_TEMPLATE_HOLDER.name) / "credentials.db"
    _ensure_credentials_at(template)
    return template


def install_demo_credentials(target: Path) -> None:
    """把凭据行弄到 `target` 上：文件不在场时整份复制模板，已在场时**只朝那一个文件**补种。

    这条路上的义务和 `ensure_demo_credentials()` 一样（"本例的库里要有那五行"），区别只在
    代价。两个分支各挡一种事故：复制快、但它是文件级动作，护栏看不见语句；补种走真写腿，
    可它的落点默认跟着 env 走。所以保护集这一关**两条分支进门前先过一次**——往
    `backend/data/` 下那份真库上盖凭据行，正是整套护栏最想拦的形状，而它只会以"会话结束时
    行数涨了"的形式被发现，太晚了。
    """
    target = Path(target)
    import conftest as ledger_guard

    if ledger_guard.path_is_protected(target):
        raise AssertionError(
            "凭据行不许落在保护集下的真实库里（护栏看不见文件级复制，所以这一关在动手前"
            f"自己把）：{target}")
    if target.exists():
        _ensure_credentials_at(target)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(credential_template(), target)

"""会话级测试护栏：**测试永不许写 `backend/data/`（及仓库根 `data/`）下的真实库**。

出处 = Model Router V2.3 Task 6 独立评审的 I-2 + 本轮（Task 7 开工前的步骤 0）复审的
N1/N3 两枚缺陷：

- **I-2**：`app/llm/usage.py` 的账本与 `app/conversation_store.py` 的会话面**共享同一个
  env 源**（`CONVERSATION_DB_PATH`，默认 `data/conversations.db`，见 `usage.database_path`
  与 `ConversationStore.__init__`）。观测面与业务面同库不同表，所以「某条测试忘了关
  usage sink」不是日志噪声，而是往 `llm_request_logs` 灌假样本——那张表是 §8 全部聚合
  （`requests_5m` / `success_rate` / `fallback_rate` / `p95_latency_ms`）的**唯一数据源**，
  `fallback_index=0` 的假成功行还会直接压低 `fallback_rate`。开发与验收阶段在同一个工作
  树里跑，被写脏的恰好是那份真数据。
- **N1（本轮修）**：`database_path()` 被**读写两条路**共同调用（`_query → _connect(None)`
  与 `_execute → _connect(None)`），所以只看「谁解析了这个路径」无法区分「写了一行假账」
  与「读了一次聚合」。旧护栏把两者都判成「写进真实库」⇒ 纯 `aggregate_status()` 的用例
  被记一笔并在 teardown 打红，失败信息还一口咬定是「写」。**写法的唯一收口是
  `usage._execute`**（`log_usage` 的 INSERT 只能从那里出去），所以「写」的判定挂在这道闸
  的调用栈上：栈内解析到的路径 = `write`（逐例判红），栈外 = `read`（只出 warning）。
- **N3（本轮修）**：默认值是**相对**路径 `data/conversations.db` ⇒ 它按「当前工作目录」
  落地。旧护栏只认 `backend/data`，于是从非 `backend/` 目录跑套件时整层失效（行落在
  `<cwd>/data/`：10 passed 全绿而真库恒 0 行，即「护栏没兜住」而不是「没人写」），且仓库
  根那份历史 `data/conversations.db` 根本不在保护集。现在相对路径按 `Path.cwd()/path`、
  `BACKEND_DIR/path`、`BACKEND_DIR.parent/path` **三候选**判定，保护集是
  `{backend/data, 仓库根/data, <cwd>/data}`，行哨兵也逐份真库各查一次。

本文件做三件事，按「便宜 → 兜底」排：

1. **env 层**：会话开始时，若调用方**没有**显式设置 `CONVERSATION_DB_PATH`，就把它指到
   会话临时目录。已经设了的（例如 CI 里指到内存/临时库）一律不动——护栏不改别人的期望。
2. **路径层（真正的护栏）**：包住 `app.llm.usage.database_path` 与 `usage._execute`，凡是
   解析到保护集底下的生效路径，一律改道到会话临时库并**按读/写归类记一笔**。这一层现在包两个
   模块：`app.llm.usage` 三道闸、`app.user_store` 两道闸，理由见文末「第二张表」。
   为什么不能只做第 1 步：契约测试的公共夹具（`_EgressFixture`）用
   `mock.patch.dict(os.environ, {}, clear=True)` 关宿主 env（Task 1 就在用的隔离手法，
   不该为了护栏去改它），那会把第 1 步设的 env 一并清掉 ⇒ 默认路径在测试里又变回
   `data/conversations.db`。拦在 `database_path()` 这一层，env 怎么被清都拦得住。
3. **归责层**：每个用例收尾时，只要本例期间记过一笔 **write** 改道，就让**这一例自己**红，
   并把肇事路径写进失败信息（read 只出 warning：它是观测面正常读，不是事故）。等式形式的
   防回潮钉在 `tests/test_model_router_v23_contract.py::LedgerIsolationGuardTests`
   （护栏在场 + 全程零 write 改道 + **两份**真库的 `llm_request_logs` 仍是 0 行），
   读写归类本身另钉在 `LedgerGuardClassificationTests`。

刻意**不**做的事：不改 `log_usage` 的 fail-open 语义、不给 `usage.py` 加测试专用分支、
不吞任何写入错误。护栏只改「落到哪个文件」+「怎么归类这一笔」，不改「写不写」——否则一次
真实的落库事故会被护栏读成成功。

已知边界（如实写在脸上）：`usage.init_usage_db()` 的建表走 `_execute(显式路径, ...)`，
显式路径不经过 `database_path()`，所以那一步不会被记成 write；它能做的只有
`CREATE TABLE IF NOT EXISTS`（0 行），而本护栏的**数据**义务是「不许有测试写的行」。

**Task 7 评审 Minor-1 收的那道缝**：`_execute` 栈外还有一条能写保护集的路 = 直连
`usage._connect()`（它的 `ensure_schema` 默认为真 ⇒ `executescript(_SCHEMA)` 建表），
旧口径会把这一笔记成 read 而不判红。现在 `install()` 挂**三道**闸（`database_path` /
`_execute` / `_connect`），`_connect(ensure_schema=True)` 也进 write 作用域，
`ensure_schema=False`（= `_query` 的读路径）照旧记 read。归类钉 =
`test_model_router_v23_contract.py::LedgerGuardClassificationTests`
::`test_a_direct_schema_connect_is_classified_write_too`（两向：直连建表判 write、
`ensure_schema=False` 判 read ⇒ 这一道闸做成恒 write 也会红）。

## 第二张表：`user_credentials`（凭据面）

`app/user_store.py` 读写的是**同一个 env 源、同一个文件**（规格 §6.1 要求凭据表与
`conversations` 同库），所以第 1、2 两层对它的失效形状与账本一模一样，而后果更重一档：
那张表里放的是能登录的凭据行。Task 2 把 `database_path()` 做成与 `usage` 同名同语义的接缝
就是为了今天能被这里包走（`install_credential_store()`，两道闸：`database_path` +
`_connect`；**会话那一个实例**再多挂一道 `ensure_user_credentials_schema` 的作用域闸，
因为 §8.5 增补段（§20.6）之后 app 的 lifespan 每次冷启动都会提交一次建表 DDL——改道照旧、
真库照旧不碰，只是那一笔不再被算成"某条 clear 过 env 的用例写了凭据行"，见
`_is_funnel_schema_ddl` 的三条理由）。三点与账本面的差异，都是那张表的形状决定的：

1. **归类只能在语句执行时补**。`usage` 的写收口在 `_execute` ⇒ "解析到真库路径"发生在写
   作用域**之内**；`user_store` 的读腿（`get_record` / `list_records` / `count_by_algorithm`
   / `column_names`）与写腿都直接 `_connect()`，路径先解析、语句后执行 ⇒ 解析那一刻根本
   分不清读写。所以先按 read 记一笔，再由 sqlite 的 trace 回调把那一笔**升**成 write。
   写证据取自 sqlite 回传的语句文本（含 DDL），不取函数名清单：以后给 `user_store` 加一条
   写腿，清单那套要有人记得回到本文件加名字，忘了的那一次是静默的。
   同一句话也解释了为什么这一面**不发**中途的 read warning（`warn_on_read=False`）：warning
   得当场发，而归类当场还没定——一条写改道会先收到一句"只读"的提醒。提醒没有丢，它搬到了
   收尾的 `[credential-guard]` 汇总与 `credential_read_redirects()`，那里拿的是定过型的记录。
2. **另开一个 `LedgerGuard` 实例**，不与账本共用 records。共享 list 才能让会话钩子逐例判红
   这件事"同形"，但两枚 list 各记各的，失败信息与终端汇总才说得出**是哪张表**被写——共用
   一枚 tuple 装不下这个事实，硬塞进 `kind` 会撞 `LedgerIsolationGuardTests` 的取值等式。
   改道目标仍是同一份临时库（§6.1 的同库要求由测试面兑现）。
3. **0 字节落点**（Task 2 移交的残余）：`user_store._connect()` 每次都会 `mkdir` 父目录并
   打开文件，env 被清掉时那个落点是 `data/conversations.db`。改道之后它落到临时库里 ⇒
   "凭空在生产数据目录造出一份空库"这条路径整体消失。钉子 =
   `test_credentials_contract.py::CredentialStoreGuardTests`（假真库在场外仍不存在）与
   `::CredentialGuardWiringTests`（真库的表清单与在场性在改道读之后逐项不变）。

另一件事与那张表的形状无关，但只在这张表上做：**收尾复验排在拆闸之前**。两道闸是"换模块属性"
装上去的 ⇒ 夹具里一次 `importlib.reload(user_store)` 就把它们静默换回裸函数，而本文件的哨兵跑
在会话早期，之后一个被解除的面能往真库里写任意多行而整场仍然全绿。所以会话 fixture 的
`finally` 在 `uninstall()` 之前复验两件事：闸**还**挂在 `user_store` 上、真库凭据行数比
**会话起点**没涨。起点取快照而不是 0：dev 形态的 `credentials bootstrap-admin` 就是往
`backend/data/conversations.db` 写 argon2id 行的那条 documented 路径（compose 挂载同一份
文件），"必须为 0"会把跑过它的那台机器判成永久红。
"""
from __future__ import annotations

import contextlib
import os
import re
import sqlite3
import sys
import threading
import warnings
from pathlib import Path
from typing import Any, Callable

import pytest

from sec_a_seed import seed_demo_credentials

TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
for _entry in (str(BACKEND_DIR), str(TESTS_DIR)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

#: 护栏保护的对象：**相对路径可能落地的每一个数据目录**（N3）。
REPO_DATA_DIR = BACKEND_DIR / "data"
REPO_ROOT_DATA_DIR = BACKEND_DIR.parent / "data"
CWD_DATA_DIR = Path.cwd() / "data"
#: 保护集（去重后）：`backend/data`、仓库根 `data`、以及当前工作目录下的 `data`。
PROTECTED_DATA_DIRS: tuple[Path, ...] = tuple(
    dict.fromkeys((REPO_DATA_DIR, REPO_ROOT_DATA_DIR, CWD_DATA_DIR))
)
#: 被哨兵逐份点数行的真库（`backend/data` 与仓库根那份历史库）。
REAL_DB_PATH = REPO_DATA_DIR / "conversations.db"
REAL_DB_PATHS: tuple[Path, ...] = (
    REAL_DB_PATH,
    REPO_ROOT_DATA_DIR / "conversations.db",
)
#: 观测面与会话面共用的 env 源（唯一出处 = `usage.database_path`）。
LEDGER_ENV_VAR = "CONVERSATION_DB_PATH"

#: 一笔改道的归类（N1）：只有 `write` 逐例判红，`read` 只出 warning。
REDIRECT_WRITE = "write"
REDIRECT_READ = "read"

#: 一句 SQL 是不是写。**含 DDL**：`user_store.ensure_user_credentials_schema()` 的那次
#: `executescript(CREATE TABLE ...)` 正是 Task 2「读路径不许建表」要盯的形状，只认 DML 会把
#: 它读成静默。`PRAGMA x=y` 一并算写（它改的是库的属性）。裸 `BEGIN` / `COMMIT` **不算**：
#: 前者只是事务标记，后者由 `executescript` 在进入时无条件回放过一次，拿它判写会把一次
#: 纯读的建库动作误判成事故（N1 的病灶换了个名字回来）。
#: 反过来说，判据取自 sqlite 回传的语句文本而不是"函数名清单"，是为了让以后新加的那条写腿
#: **不需要有人记得回来加名字**——清单漏一项的那一次是静默的，而这张表里放的是凭据行。
_WRITE_STATEMENT = re.compile(
    r"^\s*(?:INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|VACUUM|REINDEX|ATTACH"
    r"|PRAGMA\s+\w+\s*=)",
    re.IGNORECASE,
)

#: 每次改道记一笔：``(被改道的原始路径, 本会话登记的生效临时路径, "read"|"write")``。
_REDIRECTS: list[tuple[str, str, str]] = []
_SESSION_TMP_DB: Path | None = None
_GUARDED = False
_SESSION_GUARD: "LedgerGuard | None" = None
#: 凭据面（`app/user_store.py`）的护栏实例：与账本面**同目标、不同 records**。
_CREDENTIAL_GUARD: "LedgerGuard | None" = None
#: **与账本面同一条别名手法**（下面的 `_REDIRECTS`）：会话守卫在 teardown 里会被摘掉
#: （`_CREDENTIAL_GUARD = None`），而 `pytest_terminal_summary` 恰恰跑在会话夹具收尾**之后** ⇒
#: 只持守卫引用的话，`[credential-guard]` 那一段收尾汇总永远打印不出来（复评以插件探针实测：
#: 守卫存活期确有记录，收尾时读不到对象）。这个模块级 list 与守卫的 `records` 是同一个对象——
#: **靠的是 `isolated_llm_ledger` 里那一次显式重绑**（`credential_guard.records = _CREDENTIAL_REDIRECTS`，
#: 与账本面 `_REDIRECTS` 那条同一手法），不是靠构造：`LedgerGuard.__init__` 给每个实例造的是**新
#: list**，没有那次重绑这个模块级 list 就恒空，而它唯一的读者是收尾的 `else` 分支（终审的结构性
#: 判定：那时别名是死代码）。重绑在 ⇒ 守卫摘掉之后记录仍读得到。
_CREDENTIAL_REDIRECTS: list[tuple[str, str, str]] = []
#: 会话启动那一刻各份真库里的 `user_credentials` 行数 —— "会话期间不增长"这条义务的基线。
_SESSION_START_CREDENTIAL_ROWS: dict[str, int | None] = {}


class _PendingRedirect:
    """一条已经改道、但**归类还没定型**的连接（凭据面专用）。

    为什么这张表不能像账本那样在解析路径那一刻就定归类：`usage` 的写收口在 `_execute`，
    解析发生在写作用域之内；`user_store` 的读腿与写腿都直接 `_connect()`，路径先解析、语句
    后执行。于是只能先按 read 记下这一笔，等 sqlite 把真正执行过的语句回传上来再升成 write。

    `done` 是必需的：一条连接会执行多条写语句（`record_login_failure` 就是 UPDATE + UPDATE），
    每次都升一次会让"这一例写了几笔"变成"它执行了几条写语句"，判红信息跟着虚高。
    """

    __slots__ = ("index", "source", "target", "done")

    def __init__(self, index: int, source: str, target: str) -> None:
        self.index = index
        self.source = source
        self.target = target
        self.done = False


# --------------------------------------------------------------------------
# 路径判定（N3：相对路径的三候选）
# --------------------------------------------------------------------------
def path_candidates(path: Path | str) -> tuple[Path, ...]:
    """一个 `database_path()` 的返回值**可能真正落地**的全部绝对路径。

    相对路径在这里是三重的：`Path("data/conversations.db")` 打开的是
    `<cwd>/data/conversations.db`，而 `BACKEND_DIR/path` 与 `BACKEND_DIR.parent/path`
    是仓库里那两份**已经存在**的历史库。三候选都算——只要有任何一候选撞上保护集，
    这一次解析就可能写到真库，就必须改道。
    """
    raw = Path(str(path)).expanduser()
    found: list[Path] = []
    for candidate in ((raw, ) if raw.is_absolute() else
                      (raw, BACKEND_DIR / raw, BACKEND_DIR.parent / raw,
                       Path.cwd() / raw)):
        try:
            found.append(candidate.resolve())
        except OSError:                                   # 非法/不可解析的名字：原样跳过
            continue
    return tuple(dict.fromkeys(found))


def path_is_protected(path: Path | str) -> bool:
    """这次解析是否可能落到保护集底下的真实数据目录。"""
    for candidate in path_candidates(path):
        for directory in PROTECTED_DATA_DIRS:
            try:
                candidate.relative_to(directory.resolve())
            except (ValueError, OSError):
                continue
            return True
    return False


# --------------------------------------------------------------------------
# 护栏本体（会话 fixture 与契约用例**共用同一份实现**）
# --------------------------------------------------------------------------
class LedgerGuard:
    """一条数据流的改道闸 + 读写归类：`install()` 包账本面，`install_credential_store()` 包凭据面。

    为什么读写要分开（N1）：`_query` 与 `_execute` 都会调 `_connect(None)`，而
    `_connect` 内部就是 `database_path()` ⇒ 「解析到真库路径」这件事本身分不清读还是写。
    分得清的唯一位置是**调用栈**：`_execute` 是写路径的收口（`log_usage` 的 INSERT 只能
    从它出去），所以在它的动态范围内解析到的路径记 `write`，其余记 `read`。

    凭据面没有那个收口（读腿与写腿都直接 `_connect()`），归类因此改成"先记 read、由 sqlite
    回传的语句把那一笔升成 write"。两条路共用同一份 records 结构与同一枚 `violations()` 判据，
    所以会话钩子的归责口径对两张表是同形的。

    本类不碰任何测试全局，因此契约用例可以另开一个实例（保护集指向临时目录）来**直接
    驱动真的 `usage._query` / `usage._execute` / `user_store` 的读写腿**，验证归类本身没被写歪。
    """

    def __init__(self, *, original_path: Callable[[], Path], target: Path,
                 protected_dirs: tuple[Path, ...] = PROTECTED_DATA_DIRS,
                 label: str = "[ledger-guard]",
                 subject: str = "真实账本",
                 warn_on_read: bool = True) -> None:
        self.original_path = original_path
        self.target = Path(target)
        self.protected_dirs = tuple(protected_dirs)
        #: 这条流打在终端/warning 上的名字。两张表共用同一份改道逻辑，但**出事的是哪张表**
        #: 必须分得清：凭据面沿用"账本"字样会让人先去查 usage sink。默认值就是账本面的原文，
        #: 所以 `install(usage)` 那条老路径上的输出一个字节都没变。
        self.label = label
        self.subject = subject
        #: 凭据面的归类要到语句执行时才定型（见 `guarded_store_database_path` 的理由块），而
        #: warning 必须当场发——于是一条**写**改道会先收到一句"只读"的提醒。所以凭据面把中途
        #: warning 关掉，同一份提醒改由收尾的 `[credential-guard]` 汇总承担（那时归类已定型）。
        #: 账本面保持原样：它的归类在解析那一刻就是真的，输出一个字节都没动。
        self.warn_on_read = warn_on_read
        #: `(原始路径, 改道后的临时路径, kind)`，按发生顺序。
        self.records: list[tuple[str, str, str]] = []
        self._local = threading.local()
        self._warned: set[str] = set()
        self._restore: list[Callable[[], None]] = []
        #: 安装时抓下来的**真** `usage._execute`（可能已是上一层护栏的包装）。
        self._real_execute: Callable[[Any, Callable[[Any], Any]], Any] | None = None
        #: 同上，装的是**真** `usage._connect`（第三道闸，Task 7 评审 Minor-1）。
        self._real_connect: Callable[..., Any] | None = None
        #: 凭据面的**真** `user_store._connect`（写证据挂在这条连接上，见 `_PendingRedirect`）。
        self._real_store_connect: Callable[..., Any] | None = None
        #: **唯一建表者**的真函数；只有会话那一个实例会抓它（`watch_schema_funnel=True`），
        #: 探针自建的实例恒为 None ⇒ 它那几条归类钉一个字节都没被这次改动软化。见
        #: `install_credential_store` 的第三道闸。
        self._real_ensure_schema: Callable[..., Any] | None = None
        #: 与上面同生同灭：`CREATE TABLE IF NOT EXISTS <凭据表>` 的形状（表名取自产品侧）。
        self._schema_ddl: re.Pattern[str] | None = None

    # --- 安装 / 卸载 ------------------------------------------------------
    def install(self, usage_module: Any) -> "LedgerGuard":
        """把三道闸挂到 `app.llm.usage` 上（记录原值，`uninstall()` 逐条还原）。"""
        for name, replacement in (("database_path", self.guarded_database_path),
                                  ("_execute", self.guarded_execute),
                                  ("_connect", self.guarded_connect)):
            previous = getattr(usage_module, name)
            if name == "_execute":
                self._real_execute = previous
            if name == "_connect":
                self._real_connect = previous
            setattr(usage_module, name, replacement)
            self._restore.append(
                lambda module=usage_module, key=name, value=previous: setattr(
                    module, key, value))
        return self

    def install_credential_store(self, store_module: Any, *,
                                watch_schema_funnel: bool = False) -> "LedgerGuard":
        """把闸挂到 `app.user_store` 上：`database_path`（改道）+ `_connect`（定归类）。

        接缝的名字与 `usage` 同形不是巧合：Task 2 就是照"`tests/conftest.py` 包 `usage` 的
        手法必须也能把本模块包走"这个要求做出 `database_path()` 的（那份注释还钉着"每次连接
        时解析、只有这一个解析点"）。这里没有 `_execute` 那道闸——那张表没有写收口函数，
        写证据改由 sqlite 的 trace 回调提供，见 `guarded_store_connect`。

        `watch_schema_funnel=True` 时**再多挂一道**：`ensure_user_credentials_schema()`（全模块
        唯一建表者）。只有会话 fixture 传这个参数，理由有三层：

        1. §8.5 增补段（§20.6）之后，**应用 lifespan 本身就是一次合法的建表 DDL**。它落在
           哪份文件仍由第 1 道闸决定（保护集 ⇒ 改道到会话临时库，真库一个字节都不动），
           但"某条用例把 OS env clear 掉之后起了真 app"不再是事故，而是每次冷启动的形状，
           不该由会话归责钩子判红那一例。
        2. 放宽只给**这一条语句、从这一个名字进来**的那一次：`_is_funnel_schema_ddl` 要同时
           满足"栈在唯一建表者之内"与"语句是 `CREATE TABLE IF NOT EXISTS <凭据表>`"。
           同一条连接里的任何 DML（INSERT/UPDATE/…）照旧升成 write ⇒ "启动顺手造凭据行"
           （M19）仍然当场红；**从漏斗外面**提交的同一枚 DDL 也照旧红 ⇒ §8.5 冻结的那半句
           「读路径不建表」在这一层仍然有牙：DDL 一旦搬进 `_connect()`，`get_record` 那条读腿
           就会在保护集上被判成写事故。
        3. 契约用例自建的护栏实例（`test_credentials_contract.py::_GuardProbe.install_guard`）
           **不**传这个参数 ⇒ `_schema_ddl is None` ⇒ 那里"DDL 也必须判 write"的三条归类钉
           一字未动。默认套件里没人能靠"多挂一道闸"把判据调松。
        """
        gates: list[tuple[str, Any]] = [
            ("database_path", self.guarded_store_database_path),
            ("_connect", self.guarded_store_connect),
        ]
        if watch_schema_funnel:
            self._real_ensure_schema = store_module.ensure_user_credentials_schema
            self._schema_ddl = re.compile(
                r"^\s*CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(?:main\.)?"
                + re.escape(str(store_module.TABLE_NAME)) + r"\b",
                re.IGNORECASE)
            gates.append(("ensure_user_credentials_schema", self.guarded_ensure_schema))
        for name, replacement in gates:
            previous = getattr(store_module, name)
            if name == "_connect":
                self._real_store_connect = previous
            setattr(store_module, name, replacement)
            self._restore.append(
                lambda module=store_module, key=name, value=previous: setattr(
                    module, key, value))
        return self

    def uninstall(self) -> None:
        for restore in reversed(self._restore):
            restore()
        self._restore.clear()

    # --- 写路径标记（判定来源） -------------------------------------------
    @contextlib.contextmanager
    def _write_scope(self):
        self._local.depth = getattr(self._local, "depth", 0) + 1
        try:
            yield
        finally:
            self._local.depth -= 1

    def current_kind(self) -> str:
        return REDIRECT_WRITE if getattr(self._local, "depth", 0) > 0 else REDIRECT_READ

    # --- 账本面：`database_path` / `_execute` / `_connect` -----------------
    def guarded_database_path(self) -> Path:
        path = Path(self.original_path())
        if not self.is_protected(path):
            return path
        kind = self.current_kind()
        self.records.append((str(path), str(self.target), kind))
        if kind == REDIRECT_READ and self.warn_on_read:
            # 读不是事故，但也不能完全静默：它说明这条用例的账本 env 没设上，
            # 下一次有人把读改成写就没有这道提醒了。
            key = f"{path}|{self.target}"
            if key not in self._warned:
                self._warned.add(key)
                warnings.warn(
                    f"{self.label} 测试**只读**了仓库{self.subject} {path} ⇒ 已改道到"
                    f" {self.target}（读不判红；写才判红，见 tests/conftest.py N1）",
                    RuntimeWarning, stacklevel=3)
        return self.target

    def guarded_execute(self, path: Any, action: Callable[[Any], Any]) -> Any:
        if self._real_execute is None:
            raise RuntimeError("LedgerGuard 没 install() 就被调用（写路径判定闸未装上）")
        with self._write_scope():
            return self._real_execute(path, action)

    def guarded_connect(self, *args: Any, **kwargs: Any) -> Any:
        """**第三道闸**（Task 7 评审 Minor-1）：`_connect(ensure_schema=True)` 本身就是一次写。

        N1 的判定挂在 `_execute` 的调用栈上，缝隙是「有人**直连** `usage._connect()`」：
        `ensure_schema` 默认为真 ⇒ `_connect` 里那句 `connection.executescript(_SCHEMA)`
        会在保护集下的真实库上建表（旧归类把它记成 read、不判红，而旧旧护栏反而判红）。
        今天 `usage.py` 里只有两个调用点（`_execute` 默认建表 / `_query` 显式 `ensure_schema=
        False`），所以这道闸对**现有归类是空操作**——它挡的是以后绕过 `_execute` 的那只手。
        `ensure_schema=False` 保持原样：那是 `_query` 的读路径，判成 write 就会把状态页/聚合
        类用例成批误诊（N1 的病灶，`test_a_pure_read_…` 立刻红）。
        """
        if self._real_connect is None:
            raise RuntimeError("LedgerGuard 没 install() 就被调用（建表闸未装上）")
        if not kwargs.get("ensure_schema", True):
            return self._real_connect(*args, **kwargs)
        with self._write_scope():
            return self._real_connect(*args, **kwargs)

    # --- 凭据面（`app/user_store.py`）的两道闸 ----------------------------
    def guarded_store_database_path(self) -> Path:
        """改道与归类复用账本面那一套，只多留一条"这次落到了哪儿"的待定型记录。

        先清后设是必需的：`user_store.database_path()` 也会被用例**直接**调用（`usage` 那边
        同理），那次调用没有连接跟着，留下的待定型记录会把归类挂到**下一条**无关的连接上。

        这条路上的 read warning 被 `warn_on_read=False` 关掉了：归类此刻还没定型，等它升到
        write 时那句"只读"已经发出去了。提醒本身没丢——收尾的 `[credential-guard]` 汇总与
        `credential_read_redirects()` 拿着的是定过型的记录。
        """
        before = len(self.records)
        path = self.guarded_database_path()
        if len(self.records) > before:
            source, target, _kind = self.records[before]
            self._local.pending = _PendingRedirect(before, source, target)
        else:
            self._local.pending = None
        return path

    def guarded_store_connect(self, *args: Any, **kwargs: Any) -> Any:
        """真 `_connect()` 之后再挂写证据：路径已解析、连接已打开，语句还没跑。

        `user_store._connect()` 自己会 `mkdir` 父目录并打开文件——这正是 Task 2 移交的"0 字节
        落点"。改道发生在它前面（`guarded_store_database_path`），所以那个落点整体落在临时库里。

        开头那行预清**按今天的执行顺序够不到**（变异验证：删掉它，本文件与会话护栏那三套仍全绿）。
        理由是接缝 normally 就在那条路上：真 `_connect()` 内部必过一次 `database_path()`
        （`test_a_guard_can_redirect_this_module_through_the_same_seam` 钉的就是这条），pending 总
        会在同一次调用里被重新设上。它挡的是接缝换形的那一天——`database_path` 被桩成非护栏的
        函数、或路径改成 import 期常量——那时上一条用例留下的待定型会挂到本条连接上，把一笔
        已经定过型的读升成本例的写。刻意不为它造用例（那要先造一个"绕过护栏解析点"的连接，
        只会把钉子写成对实现的复述）；也不许反过来把它当成死码删掉。
        """
        if self._real_store_connect is None:
            raise RuntimeError("LedgerGuard 没 install_credential_store() 就被调用（凭据写闸未装上）")
        self._local.pending = None
        connection = self._real_store_connect(*args, **kwargs)
        pending = getattr(self._local, "pending", None)
        self._local.pending = None
        if pending is not None:
            connection.set_trace_callback(self._write_marker(pending))
        return connection

    def guarded_ensure_schema(self, *args: Any, **kwargs: Any) -> Any:
        """**第三道闸**（只挂在会话实例上）：进唯一建表者的那一刻起，本线程算 schema 作用域。

        为什么把"是不是那次合法建表"判在**调用栈**上而不是语句文本上：`_SCHEMA` 那段文本谁
        都可能抄去执行（今天抄它的是 lifespan，明天可能是某条读腿），文本判据分不开这两种人。
        漏斗名字却是产品自己声明的那枚唯一建表者，`user_store.py:110` 的理由块与 §8.5 增补段
        指的都是它。作用域跟着线程走、出栈即减，所以只有 `ensure_user_credentials_schema()`
        自己那一次 `executescript` 在作用域里。
        """
        if self._real_ensure_schema is None:
            raise RuntimeError("LedgerGuard 没带 watch_schema_funnel 就被调用（建表漏斗闸未装上）")
        self._local.schema_depth = getattr(self._local, "schema_depth", 0) + 1
        try:
            return self._real_ensure_schema(*args, **kwargs)
        finally:
            self._local.schema_depth -= 1

    def _is_funnel_schema_ddl(self, statement: str) -> bool:
        """这一笔是不是「唯一建表者在自己的漏斗里建凭据表」——**只有它**不算事故。

        两个条件缺一个都判红：漏斗之外提交的同一枚 DDL 正是「读路径建表」那个形状（§8.5 冻结
        的另一半），而漏斗之内的任何 DML（启动顺手造凭据行 = M19）压根不被这条匹配。没装第三
        道闸的实例（契约用例自建的探针）这里恒 False ⇒ 那三条"DDL 也必须判 write"的归类钉
        一字未动。留在 read 不等于静默：那一笔仍在 `credential_redirects()` /
        `credential_read_redirects()` 与收尾的 `[credential-guard]` 汇总里数得到。
        """
        pattern = self._schema_ddl
        if pattern is None or getattr(self._local, "schema_depth", 0) <= 0:
            return False
        return bool(pattern.match(statement))

    def _write_marker(self, pending: _PendingRedirect) -> Callable[[str], None]:
        def mark(statement: str) -> None:
            text = str(statement or "")
            if pending.done or not _WRITE_STATEMENT.match(text):
                return
            if self._is_funnel_schema_ddl(text):
                # **不置 done**：同一条连接里如果还跟着一条 DML（那是"启动顺手造行"，不是建表），
                # 它仍要把这一笔升成 write。
                return
            pending.done = True
            self._upgrade_record_to_write(pending)
        return mark

    def _upgrade_record_to_write(self, pending: _PendingRedirect) -> None:
        """把那一笔从 read 升成 write —— 会话钩子判红的输入就是这一笔。

        位置校验不是多余的小心：`records` 是会被上层换手的 list（会话 fixture 就把账本面的
        `records` 换成了模块级 `_REDIRECTS`），照着索引去改别人位置上的笔之前得先验货。
        对不上时的出路是**另记一笔 write**，不是静默返回：漏判一次凭据写的代价比多判一笔高。

        那一支按构造够不到（这一笔的记录人到升档时还没被任何人动过），因此**刻意不设用例**，
        也不许有人拿覆盖率当理由把它改成静默 `return`：它的存在意义正是"哪天构造得到了，
        宁可多判一笔红"。
        """
        current = (pending.source, pending.target, REDIRECT_READ)
        if 0 <= pending.index < len(self.records) and self.records[pending.index] == current:
            self.records[pending.index] = (pending.source, pending.target, REDIRECT_WRITE)
            return
        self.records.append((pending.source, pending.target, REDIRECT_WRITE))

    # --- 归类查询 ---------------------------------------------------------
    def is_protected(self, path: Path | str) -> bool:
        for candidate in path_candidates(path):
            for directory in self.protected_dirs:
                try:
                    candidate.relative_to(Path(directory).resolve())
                except (ValueError, OSError):
                    continue
                return True
        return False

    def violations(self) -> tuple[tuple[str, str, str], ...]:
        """判红的那一类：写路径解析到真库。"""
        return tuple(record for record in self.records if record[2] == REDIRECT_WRITE)

    def read_redirects(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(record for record in self.records if record[2] == REDIRECT_READ)


# --------------------------------------------------------------------------
# 对外口径（给防回潮钉读，不给产品代码读）
# --------------------------------------------------------------------------
def guard_is_active() -> bool:
    """护栏是否已经装上（会话 fixture 跑过才是 True；单独 import 本文件时是 False）。"""
    return _GUARDED


def effective_ledger_path() -> Path:
    """`usage.database_path()` 现在真正解析到的路径（护栏改道**之后**的值）。"""
    from app.llm import usage as usage_module

    return Path(usage_module.database_path())


def ledger_redirects() -> tuple[tuple[str, str, str], ...]:
    """本会话内被护栏拦下的**全部**改道（读 + 写），逐笔 `(src, dst, kind)`。

    正常应为空。判红只看 `violations()`（kind=="write"），N1。
    """
    return tuple(_REDIRECTS)


def write_redirects() -> tuple[tuple[str, str, str], ...]:
    """本会话内**写**路径上的改道——这些才是一例判红的东西。"""
    return _SESSION_GUARD.violations() if _SESSION_GUARD is not None else ()


def read_redirects() -> tuple[tuple[str, str, str], ...]:
    """本会话内**读**路径上的改道（warning，不判红）。"""
    return _SESSION_GUARD.read_redirects() if _SESSION_GUARD is not None else ()


def real_ledger_row_count(path: Path = REAL_DB_PATH) -> int | None:
    """指定真库里 `llm_request_logs` 的行数；文件/表不在场时返回 ``None``（0 行等价）。

    以 **只读** URI 打开：这条断言的交付物是「没人写过」，它自己更不该去写。
    """
    if not path.is_file():
        return None
    connection = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='llm_request_logs'"
        ).fetchone()
        if table is None:
            return None
        return int(connection.execute("SELECT COUNT(*) FROM llm_request_logs").fetchone()[0])
    finally:
        connection.close()


def real_ledger_row_counts() -> dict[str, int | None]:
    """N3：保护集里的**每一份**真库都要点数（仓库根那份历史库同样不许被写脏）。"""
    return {str(path): real_ledger_row_count(path) for path in REAL_DB_PATHS}


# --------------------------------------------------------------------------
# 凭据面（`app/user_store.py` 的 `user_credentials`）的对外口径
# --------------------------------------------------------------------------
def credential_guard_is_active() -> bool:
    """凭据面的**改道闸与归类闸**是不是真挂在 `user_store` 上（而且是会话那一个实例）。

    只问"fixture 跑过没"不够：接线是一行 `install_credential_store()`，删掉它 `guard_is_active()`
    照旧为真、`test_llm_egress_guard.py` 的账本钉照旧绿，而这张表已经没人盯了。属性相等才是
    "挂在这个实例上"的证据。
    第三道闸（`ensure_user_credentials_schema` 的作用域）**不在**这里的等式内：它的缺席不是
    静默的——少了它，lifespan 那次建表就会被归责钩子判红（本轮实测过一次），所以这一枚函数
    继续只钉那两枚"没了就没人看这张表"的闸。
    """
    guard = _CREDENTIAL_GUARD
    if guard is None:
        return False
    from app import user_store as store_module

    return (store_module.database_path == guard.guarded_store_database_path
            and store_module._connect == guard.guarded_store_connect)


def effective_credential_path() -> Path:
    """`user_store.database_path()` 现在真正解析到的路径（护栏改道**之后**的值）。"""
    from app import user_store as store_module

    return Path(store_module.database_path())


def credential_redirects() -> tuple[tuple[str, str, str], ...]:
    """本会话内**凭据面**被拦下的全部改道，逐笔 `(src, dst, kind)`。正常应为空。"""
    return tuple(_CREDENTIAL_GUARD.records) if _CREDENTIAL_GUARD is not None else ()


def credential_write_redirects() -> tuple[tuple[str, str, str], ...]:
    """凭据面上的**写**改道——这些才是一例判红的东西（与 `write_redirects()` 同形）。"""
    return _CREDENTIAL_GUARD.violations() if _CREDENTIAL_GUARD is not None else ()


def credential_read_redirects() -> tuple[tuple[str, str, str], ...]:
    """凭据面上的**读**改道（不判红；提醒走收尾的 `[credential-guard]` 汇总）。"""
    guard = _CREDENTIAL_GUARD
    return guard.read_redirects() if guard is not None else ()


def real_db_tables(path: Path = REAL_DB_PATH) -> tuple[str, ...] | None:
    """真库里的表清单；**文件不在场**时返回 ``None``（与"有一份空库"区分开）。

    取"表清单"而不是"字节数/时间戳"当快照：本仓库的 dev 后端可能正往同一份库里写会话行，
    拿 mtime 判据会把那种正常活动读成测试事故。这张表的义务只是"不许凭测试多出来"。
    """
    if not path.is_file():
        return None
    connection = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        return tuple(str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
    finally:
        connection.close()


def real_user_credential_row_count(path: Path = REAL_DB_PATH) -> int | None:
    """指定真库里 `user_credentials` 的行数；文件/表不在场时 ``None``（0 行等价）。

    表名从 `user_store.TABLE_NAME` 读，不在这里再抄一遍字面量：那张表叫什么由产品代码说。
    """
    from app import user_store as store_module

    if not path.is_file():
        return None
    connection = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (store_module.TABLE_NAME,),
        ).fetchone()
        if table is None:
            return None
        return int(connection.execute(
            f"SELECT COUNT(*) FROM {store_module.TABLE_NAME}").fetchone()[0])
    finally:
        connection.close()


def real_user_credential_row_counts() -> dict[str, int | None]:
    """保护集里每一份真库的凭据行数（与 `real_ledger_row_counts()` 同一份库清单）。"""
    return {str(path): real_user_credential_row_count(path) for path in REAL_DB_PATHS}


def credential_row_counts_at_session_start() -> dict[str, int | None]:
    """会话启动时那份快照（哨兵基线）。护栏没跑起来时是空 dict ⇒ 基线退化成 0。"""
    return dict(_SESSION_START_CREDENTIAL_ROWS)


def credential_row_growth() -> dict[str, int]:
    """会话期间各份真库里 `user_credentials` **多出来**的行数（只报涨了的库）。

    判增长而不是判 0：dev 那条 bootstrap 路径本来就把 argon2id 行写进
    `backend/data/conversations.db`（compose 挂载同一份文件），那是会话开始前的事实。
    文件或表不在场按 0 计；没取到起点快照（护栏 fixture 没跑）也按 0 起算，即退化成
    "多一行都不许"——两个方向都是过判红而不是静默放过。
    """
    growth: dict[str, int] = {}
    for path, rows in real_user_credential_row_counts().items():
        start = _SESSION_START_CREDENTIAL_ROWS.get(path) or 0
        now = rows or 0
        if now > start:
            growth[path] = now - start
    return growth


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def isolated_llm_ledger(tmp_path_factory):
    """会话级：env 默认值 + 账本面三道闸 + 凭据面两道闸的兜底改道闸。"""
    global _SESSION_TMP_DB, _GUARDED, _SESSION_GUARD, _CREDENTIAL_GUARD
    global _SESSION_START_CREDENTIAL_ROWS

    from app import user_store as store_module
    from app.llm import usage as usage_module

    directory = tmp_path_factory.mktemp("llm-ledger-isolation")
    _SESSION_TMP_DB = directory / "conversations.db"
    _REDIRECTS.clear()
    # 凭据面哨兵的基线在**装闸之前**取：那之后任何一次涨行都是本会话干的事。
    _SESSION_START_CREDENTIAL_ROWS = real_user_credential_row_counts()

    previous_env = os.environ.get(LEDGER_ENV_VAR)
    if previous_env is None:                                     # 调用方设过 ⇒ 不动它
        os.environ[LEDGER_ENV_VAR] = str(_SESSION_TMP_DB)

    guard = LedgerGuard(original_path=usage_module.database_path,
                        target=_SESSION_TMP_DB)
    guard.install(usage_module)
    _SESSION_GUARD = guard
    # `records` 与 `_REDIRECTS` 是同一个 list：既给本文件的 fixture/汇总用，也给
    # `ledger_redirects()` 给防回潮钉读。
    _REDIRECTS.extend(guard.records)
    guard.records = _REDIRECTS
    _GUARDED = True
    # 凭据面：**同一个目标文件**（规格 §6.1 要求 `user_credentials` 与 `conversations` 同库，
    # 测试面也不许把它改到第二个文件去），但是**另一个实例**——两枚 records 各记各的，判红的
    # 消息才说得出是哪张表被写。`original_path` 必须在 install 之前取，取的是真函数。
    credential_guard = LedgerGuard(original_path=store_module.database_path,
                                   target=_SESSION_TMP_DB,
                                   label="[credential-guard]",
                                   subject="真实凭据表",
                                   warn_on_read=False)
    # `watch_schema_funnel=True`：全仓只有会话这一个实例盯那枚唯一建表者。理由是 §8.5 增补段
    # （§20.6）之后 app 的 lifespan 每次冷启动都要在那里提交一次 `CREATE TABLE IF NOT EXISTS`，
    # 而某些用例的夹具会 `patch.dict(os.environ, {}, clear=True)`（那份隔离手法是 Task 1 就在用
    # 的、不该为护栏去改）⇒ 落点退回默认值 ⇒ 改道照旧发生、真库照旧一个字节不动，只是这一笔
    # 不再被算成"那一例写了凭据行"。判据的收紧处见 `_is_funnel_schema_ddl`。
    credential_guard.install_credential_store(store_module, watch_schema_funnel=True)
    _CREDENTIAL_GUARD = credential_guard
    # 终审判定 C1 的处置：上面那两行只保证"闸装上了"，不保证"收尾读得到"。`LedgerGuard.__init__`
    # 给每枚实例造的是**新 list**，所以这句重绑才是让别名生效的那一步——照账本面（上面
    # `guard.records = _REDIRECTS`）把守卫的 records 换成模块级那一枚 ⇒ 守卫在 teardown 摘掉之后，
    # `pytest_terminal_summary` 的 `else` 分支读的还是同一份记录，`[credential-guard]` 才打得出来。
    credential_guard.records = _CREDENTIAL_REDIRECTS
    try:
        yield _SESSION_TMP_DB
    finally:
        # 复验排在拆闸之前：闸一拆，"闸还在不在"就再也问不出来了。会话里那两枚哨兵跑得早，
        # 这一步是"中途被 reload 解除 / 解除之后真库被写"这两件事在整场结束时的最后一道闸——
        # 会话级 autouse teardown 里抛异常会把整场运行判成 error（退出码非 0），不会静默。
        if not credential_guard_is_active():
            raise AssertionError(
                "会话结束时凭据面的那两道闸（`database_path` / `_connect`）已不在"
                "`app.user_store` 上：中途有夹具 reload 过这个"
                "模块（`importlib.reload` 把 `database_path`/`_connect` 换回裸函数 = 护栏静默"
                "解除，之后写多少行都没人看）。换库请只改 `CONVERSATION_DB_PATH`。")
        growth = credential_row_growth()
        if growth:
            raise AssertionError(
                "会话期间真实库里的凭据行变多了（SECA-04 的台账会被这几行污染）："
                f"{growth}；会话起点快照 {credential_row_counts_at_session_start()}，"
                "现在的行数 "
                f"{real_user_credential_row_counts()}。修法照 `_CredentialDbPerTest`。")
        credential_guard.uninstall()
        _CREDENTIAL_GUARD = None
        guard.uninstall()
        _SESSION_GUARD = None
        _GUARDED = False
        if previous_env is None:
            os.environ.pop(LEDGER_ENV_VAR, None)
        else:
            os.environ[LEDGER_ENV_VAR] = previous_env


@pytest.fixture(scope="session", autouse=True)
def isolated_audit_sink(tmp_path_factory):
    """会话级：审计落盘面改道到 tmp，测试事件不再写进 `backend/data/audit.jsonl`。

    `app/audit.py:11` 的 `AUDIT_PATH` 是相对常量（`data/audit.jsonl`），而 compose 把 `backend/data`
    整个挂进容器 ⇒ 一次全套件跑动会往**运维正在读的那本审计账**后面追加内容（实测单枚焦点文件
    +337 字节，全量到 2 MB 量级）。那本账还是 §14 的证据面之一（`credentials migration-status`
    的"最后成功登录"就读它的尾巴），掺进测试事件就是污染验收证据。

    接缝打在模块属性上而不是 env：`record_event` 每次调用都现取这一个名字（`sec_a_fixtures`
    的用例级 mixin 是同一手法，两者可叠加——mixin 覆盖期间会话值被完整保留，结束时还原）。
    """
    from app import audit as audit_module

    original = audit_module.AUDIT_PATH
    target = tmp_path_factory.mktemp("audit-sink-isolation") / "audit.jsonl"
    audit_module.AUDIT_PATH = target
    try:
        yield target
    finally:
        audit_module.AUDIT_PATH = original


@pytest.fixture(scope="session", autouse=True)
def shipped_identity_files():
    """身份文件按 `backend/` 锚定：运行目录不再决定"读不读得到出厂身份"，常量本身一字不动。

    `directory` 的两枚路径常量是**相对**路径，那是部署口径（镜像 WORKDIR 就是 `backend/`，
    `test_user_directory_contract.py` 钉着这个字面值），不许改成绝对。但本套件按两种 cwd 跑
    （`backend/` 与仓库根），从仓库根起那条相对路径指向不存在的位置——而认证腿现在每个请求
    都要读身份，于是"运行目录"会变成登录能不能通的前提。收口在**读文件那一步**：与
    `test_llm_usage_contract.py` 对 `llm_registry_file` 的 cwd 收口同一手法——把配置指到出厂
    文件，不动默认值、不放宽任何断言。
    """
    from app import directory as directory_module

    original = directory_module._read_document

    def anchored(path: Path):
        return original(path if path.is_absolute() else BACKEND_DIR / path)

    directory_module._read_document = anchored
    try:
        yield
    finally:
        directory_module._read_document = original


@pytest.fixture(scope="session", autouse=True)
def seeded_demo_credentials(isolated_llm_ledger):
    """会话级 demo 凭据 seed（规格 §8.2）：口令字面量住在测试侧，脚下是 argon2id 行。

    依赖 `isolated_llm_ledger` 有两层：一是顺序——那枚 fixture 才是把
    `CONVERSATION_DB_PATH` 指到会话临时库的人，先它 seed 就是往仓库里的真库写凭据行；
    二是这里必须落在**护栏改道之后**的那份文件上，否则会话结束时的"真库凭据行不增长"
    哨兵会被这笔正常写判红。
    """
    seed_demo_credentials()
    yield


@pytest.fixture(scope="session", autouse=True)
def p0_login_credential_seam(seeded_demo_credentials):
    """REAL-LLM-FAILOVER-001 的登录腿：把凭据来源垫在**它自己那枚临时库**脚下（Task 10f）。

    为什么触发点在这里、实现却在 `real_llm_failover_kit.py`：P0 用例（sealed V2.3 产物，
    一字不许改）的 `setUp` 自己造库、自己在 `:686` 打 `/api/auth/login` 并断言 200，而它
    绕过会话临时库 ⇒ 拿不到上面那枚 `seeded_demo_credentials`。规格 §16 对这一枚的裁决是
    「调用形式与口令字面量都不改，改的是它们脚下的凭据来源（§8.2 与 SECA-24）」，
    能在它的 `setUp` 之前动手的只有会话级夹具——所以本处只**调用** kit，不复制任何判定、
    不写第二份 seed 逻辑。

    对默认套件是惰性的：`install_login_credential_seam()` 里唯一的门是
    `kit.acceptance_enabled()`（`REAL_LLM_ACCEPTANCE=1`），不合则 `app.llm.usage`
    的 `init_usage_db` 属性一字未动。这条惰性由 `test_security_a_closure.py` 钉住，
    不是靠本 docstring 自称。顺序前提：依赖 `seeded_demo_credentials` ⇒ 三道账本闸与两道
    凭据闸都已装上、会话 seed 也已发生，接缝只会碰**它自己指名**的那份文件。
    """
    import real_llm_failover_kit as kit

    installed = kit.install_login_credential_seam()
    yield installed
    if installed:
        kit.uninstall_login_credential_seam()


@pytest.fixture(autouse=True)
def fail_the_offending_test_on_repo_ledger_write():
    """每个用例单独归责：本例期间发生过**写**改道 ⇒ 本例红（N1：读只 warning）。

    两张表各查各的、各说各的话：账本面那条消息里的修法是"关 usage sink"，凭据面那条是
    "把 `CONVERSATION_DB_PATH` 指到临时目录"——把两条捏成一句通用文案，等于给肇事者一张
    错地图（这正是 N1 之前那版护栏被诟病的形状）。
    """
    guard = _SESSION_GUARD
    store_guard = _CREDENTIAL_GUARD
    before = len(guard.records) if guard is not None else len(_REDIRECTS)
    store_before = len(store_guard.records) if store_guard is not None else 0
    yield
    source = guard.records if guard is not None else _REDIRECTS
    offenders = [record for record in source[before:] if record[2] == REDIRECT_WRITE]
    store_source = store_guard.records if store_guard is not None else []
    store_offenders = [record for record in store_source[store_before:]
                       if record[2] == REDIRECT_WRITE]
    if offenders:
        detail = "；".join(f"写 {src} ⇒ 被护栏改道到 {dst}" for src, dst, _ in offenders)
        raise AssertionError(
            "测试把 LLM usage 账本**写**进了保护集下的真实库（评审 I-2 同类事故）。"
            f"本例要么没关 usage sink、要么没把 `CONVERSATION_DB_PATH`/`init_usage_db` 指到"
            f"临时目录：{detail}。修法照 `PackageEntryPointTests`（显式内存 sink）或 "
            f"`_RagMigrationFixture`（临时库 + `set_usage_sink(None)`）。")
    if store_offenders:
        detail = "；".join(f"写 {src} ⇒ 被护栏改道到 {dst}" for src, dst, _ in store_offenders)
        raise AssertionError(
            "测试往保护集下的真实库里**写**了凭据行（`user_credentials`——那张表里放的是能"
            "登录的凭据，不是一行观测数据）。"
            f"本例要么没把 `CONVERSATION_DB_PATH` 指到临时目录、要么在 env 被 clear 的窗口里"
            f"调了 `user_store` 的写腿：{detail}。修法照 `_CredentialDbPerTest`（每例一份临时"
            f"库 + `ensure_user_credentials_schema()`）。")


@pytest.fixture(autouse=True)
def reset_login_throttle():
    """每个用例一份干净的节流表：第一层是**进程内**状态，而整套件跑在同一个进程里。

    桶按 `(username, client_ip)` 分、窗口 60 秒，跨用例累加的症状是"第 11 次登录的用例收到
    429"——那既不是被测事实，也不该由用例自己清。生产侧的清零只发生在窗口过期或进程重启上，
    这两件事都不是测试之间可以借用的通道（`login_throttle.PreHashThrottle.reset` 正是为此存在）。
    """
    from app import login_throttle

    login_throttle.pre_hash_throttle.reset()
    yield
    login_throttle.pre_hash_throttle.reset()


def pytest_terminal_summary(terminalreporter):
    """收尾把改道计数打在终端上：跑一次全套件就是一份同类隔离漏洞清单。

    读/写分开打：写 = 事故（已经逐例判红过），读 = 提醒（护栏兜住了，但那条用例的
    账本 env 其实没设上）。
    """
    guard = _SESSION_GUARD
    records = guard.records if guard is not None else _REDIRECTS
    _report_redirects(terminalreporter, "[ledger-guard]", "真实账本**写**账", "真实账本",
                      records)
    # 账本面同一个手法：守卫对象在会话夹具收尾时摘掉，而这段汇总可能跑在那之后 ⇒ 读别名 list。
    credential_records = (_CREDENTIAL_GUARD.records if _CREDENTIAL_GUARD is not None
                          else _CREDENTIAL_REDIRECTS)
    if credential_records:
        _report_redirects(terminalreporter, "[credential-guard]",
                          "真实凭据表**写**行", "真实凭据表", credential_records)


def _report_redirects(terminalreporter, label: str, write_subject: str, read_subject: str,
                      records: tuple[tuple[str, str, str], ...]
                      | list[tuple[str, str, str]]) -> None:
    """一张表的改道清单（两张表共用同一份口径，只差被点名的那张表——账本面的文案原样保留）。"""
    if not records:
        return
    writes = [record for record in records if record[2] == REDIRECT_WRITE]
    reads = [record for record in records if record[2] == REDIRECT_READ]
    if writes:
        terminalreporter.write_line(
            f"{label} {len(writes)} 次「往保护集下的{write_subject}」被护栏拦下：")
        for source, target, _kind in writes:
            terminalreporter.write_line(f"{label}   {source} ⇒ {target}")
    if reads:
        terminalreporter.write_line(
            f"{label} {len(reads)} 次「读保护集下的{read_subject}」被改道（N1：读不判红）：")
        for source, target, _kind in reads[:10]:
            terminalreporter.write_line(f"{label}   {source} ⇒ {target}")
        if len(reads) > 10:
            terminalreporter.write_line(
                f"{label}   ……另有 {len(reads) - 10} 次同类读改道")

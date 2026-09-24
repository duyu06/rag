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
   解析到保护集底下的生效路径，一律改道到会话临时库并**按读/写归类记一笔**。为什么不能
   只做第 1 步：契约测试的公共夹具（`_EgressFixture`）用
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
"""
from __future__ import annotations

import contextlib
import os
import sqlite3
import sys
import threading
import warnings
from pathlib import Path
from typing import Any, Callable

import pytest

TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

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

#: 每次改道记一笔：``(被改道的原始路径, 本会话登记的生效临时路径, "read"|"write")``。
_REDIRECTS: list[tuple[str, str, str]] = []
_SESSION_TMP_DB: Path | None = None
_GUARDED = False
_SESSION_GUARD: "LedgerGuard | None" = None


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
    """`usage.database_path` / `usage._execute` 的改道闸 + 读写归类。

    为什么读写要分开（N1）：`_query` 与 `_execute` 都会调 `_connect(None)`，而
    `_connect` 内部就是 `database_path()` ⇒ 「解析到真库路径」这件事本身分不清读还是写。
    分得清的唯一位置是**调用栈**：`_execute` 是写路径的收口（`log_usage` 的 INSERT 只能
    从它出去），所以在它的动态范围内解析到的路径记 `write`，其余记 `read`。

    本类不碰任何测试全局，因此契约用例可以另开一个实例（保护集指向临时目录）来**直接
    驱动真的 `usage._query` / `usage._execute`**，验证这道归类本身没有被写歪。
    """

    def __init__(self, *, original_path: Callable[[], Path], target: Path,
                 protected_dirs: tuple[Path, ...] = PROTECTED_DATA_DIRS) -> None:
        self.original_path = original_path
        self.target = Path(target)
        self.protected_dirs = tuple(protected_dirs)
        #: `(原始路径, 改道后的临时路径, kind)`，按发生顺序。
        self.records: list[tuple[str, str, str]] = []
        self._local = threading.local()
        self._warned: set[str] = set()
        self._restore: list[Callable[[], None]] = []
        #: 安装时抓下来的**真** `usage._execute`（可能已是上一层护栏的包装）。
        self._real_execute: Callable[[Any, Callable[[Any], Any]], Any] | None = None
        #: 同上，装的是**真** `usage._connect`（第三道闸，Task 7 评审 Minor-1）。
        self._real_connect: Callable[..., Any] | None = None

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

    # --- 两道闸 -----------------------------------------------------------
    def guarded_database_path(self) -> Path:
        path = Path(self.original_path())
        if not self.is_protected(path):
            return path
        kind = self.current_kind()
        self.records.append((str(path), str(self.target), kind))
        if kind == REDIRECT_READ:
            # 读不是事故，但也不能完全静默：它说明这条用例的账本 env 没设上，
            # 下一次有人把读改成写就没有这道提醒了。
            key = f"{path}|{self.target}"
            if key not in self._warned:
                self._warned.add(key)
                warnings.warn(
                    f"[ledger-guard] 测试**只读**了仓库真实账本 {path} ⇒ 已改道到"
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
# fixtures
# --------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def isolated_llm_ledger(tmp_path_factory):
    """会话级：env 默认值 + `usage.database_path` / `usage._execute` 的兜底改道闸。"""
    global _SESSION_TMP_DB, _GUARDED, _SESSION_GUARD

    from app.llm import usage as usage_module

    directory = tmp_path_factory.mktemp("llm-ledger-isolation")
    _SESSION_TMP_DB = directory / "conversations.db"
    _REDIRECTS.clear()

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
    try:
        yield _SESSION_TMP_DB
    finally:
        guard.uninstall()
        _SESSION_GUARD = None
        _GUARDED = False
        if previous_env is None:
            os.environ.pop(LEDGER_ENV_VAR, None)
        else:
            os.environ[LEDGER_ENV_VAR] = previous_env


@pytest.fixture(autouse=True)
def fail_the_offending_test_on_repo_ledger_write():
    """每个用例单独归责：本例期间发生过**写**改道 ⇒ 本例红（N1：读只 warning）。"""
    guard = _SESSION_GUARD
    before = len(guard.records) if guard is not None else len(_REDIRECTS)
    yield
    source = guard.records if guard is not None else _REDIRECTS
    offenders = [record for record in source[before:] if record[2] == REDIRECT_WRITE]
    if not offenders:
        return
    detail = "；".join(f"写 {src} ⇒ 被护栏改道到 {dst}" for src, dst, _ in offenders)
    raise AssertionError(
        "测试把 LLM usage 账本**写**进了保护集下的真实库（评审 I-2 同类事故）。"
        f"本例要么没关 usage sink、要么没把 `CONVERSATION_DB_PATH`/`init_usage_db` 指到"
        f"临时目录：{detail}。修法照 `PackageEntryPointTests`（显式内存 sink）或 "
        f"`_RagMigrationFixture`（临时库 + `set_usage_sink(None)`）。")


def pytest_terminal_summary(terminalreporter):
    """收尾把改道计数打在终端上：跑一次全套件就是一份同类隔离漏洞清单。

    读/写分开打：写 = 事故（已经逐例判红过），读 = 提醒（护栏兜住了，但那条用例的
    账本 env 其实没设上）。
    """
    guard = _SESSION_GUARD
    records = guard.records if guard is not None else _REDIRECTS
    if not records:
        return
    writes = [record for record in records if record[2] == REDIRECT_WRITE]
    reads = [record for record in records if record[2] == REDIRECT_READ]
    if writes:
        terminalreporter.write_line(
            f"[ledger-guard] {len(writes)} 次「往保护集下的真实账本**写**账」被护栏拦下：")
        for source, target, _kind in writes:
            terminalreporter.write_line(f"[ledger-guard]   {source} ⇒ {target}")
    if reads:
        terminalreporter.write_line(
            f"[ledger-guard] {len(reads)} 次「读保护集下的真实账本」被改道（N1：读不判红）：")
        for source, target, _kind in reads[:10]:
            terminalreporter.write_line(f"[ledger-guard]   {source} ⇒ {target}")
        if len(reads) > 10:
            terminalreporter.write_line(
                f"[ledger-guard]   ……另有 {len(reads) - 10} 次同类读改道")

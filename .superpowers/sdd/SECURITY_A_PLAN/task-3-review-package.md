# Task 3 review package (conftest diff + full new files)

## A. conftest.py diff vs bc43ca3 (only Task 3 touched this file)
warning: in the working copy of 'backend/tests/conftest.py', LF will be replaced by CRLF the next time Git touches it
diff --git a/backend/tests/conftest.py b/backend/tests/conftest.py
index 46db99c..7e0bcc1 100644
--- a/backend/tests/conftest.py
+++ b/backend/tests/conftest.py
@@ -21,22 +21,23 @@ N1/N3 两枚缺陷：
   `<cwd>/data/`：10 passed 全绿而真库恒 0 行，即「护栏没兜住」而不是「没人写」），且仓库
   根那份历史 `data/conversations.db` 根本不在保护集。现在相对路径按 `Path.cwd()/path`、
   `BACKEND_DIR/path`、`BACKEND_DIR.parent/path` **三候选**判定，保护集是
   `{backend/data, 仓库根/data, <cwd>/data}`，行哨兵也逐份真库各查一次。
 
 本文件做三件事，按「便宜 → 兜底」排：
 
 1. **env 层**：会话开始时，若调用方**没有**显式设置 `CONVERSATION_DB_PATH`，就把它指到
    会话临时目录。已经设了的（例如 CI 里指到内存/临时库）一律不动——护栏不改别人的期望。
 2. **路径层（真正的护栏）**：包住 `app.llm.usage.database_path` 与 `usage._execute`，凡是
-   解析到保护集底下的生效路径，一律改道到会话临时库并**按读/写归类记一笔**。为什么不能
-   只做第 1 步：契约测试的公共夹具（`_EgressFixture`）用
+   解析到保护集底下的生效路径，一律改道到会话临时库并**按读/写归类记一笔**。这一层现在包两个
+   模块：`app.llm.usage` 三道闸、`app.user_store` 两道闸，理由见文末「第二张表」。
+   为什么不能只做第 1 步：契约测试的公共夹具（`_EgressFixture`）用
    `mock.patch.dict(os.environ, {}, clear=True)` 关宿主 env（Task 1 就在用的隔离手法，
    不该为了护栏去改它），那会把第 1 步设的 env 一并清掉 ⇒ 默认路径在测试里又变回
    `data/conversations.db`。拦在 `database_path()` 这一层，env 怎么被清都拦得住。
 3. **归责层**：每个用例收尾时，只要本例期间记过一笔 **write** 改道，就让**这一例自己**红，
    并把肇事路径写进失败信息（read 只出 warning：它是观测面正常读，不是事故）。等式形式的
    防回潮钉在 `tests/test_model_router_v23_contract.py::LedgerIsolationGuardTests`
    （护栏在场 + 全程零 write 改道 + **两份**真库的 `llm_request_logs` 仍是 0 行），
    读写归类本身另钉在 `LedgerGuardClassificationTests`。
 
 刻意**不**做的事：不改 `log_usage` 的 fail-open 语义、不给 `usage.py` 加测试专用分支、
@@ -48,25 +49,53 @@ N1/N3 两枚缺陷：
 `CREATE TABLE IF NOT EXISTS`（0 行），而本护栏的**数据**义务是「不许有测试写的行」。
 
 **Task 7 评审 Minor-1 收的那道缝**：`_execute` 栈外还有一条能写保护集的路 = 直连
 `usage._connect()`（它的 `ensure_schema` 默认为真 ⇒ `executescript(_SCHEMA)` 建表），
 旧口径会把这一笔记成 read 而不判红。现在 `install()` 挂**三道**闸（`database_path` /
 `_execute` / `_connect`），`_connect(ensure_schema=True)` 也进 write 作用域，
 `ensure_schema=False`（= `_query` 的读路径）照旧记 read。归类钉 =
 `test_model_router_v23_contract.py::LedgerGuardClassificationTests`
 ::`test_a_direct_schema_connect_is_classified_write_too`（两向：直连建表判 write、
 `ensure_schema=False` 判 read ⇒ 这一道闸做成恒 write 也会红）。
+
+## 第二张表：`user_credentials`（凭据面）
+
+`app/user_store.py` 读写的是**同一个 env 源、同一个文件**（规格 §6.1 要求凭据表与
+`conversations` 同库），所以第 1、2 两层对它的失效形状与账本一模一样，而后果更重一档：
+那张表里放的是能登录的凭据行。Task 2 把 `database_path()` 做成与 `usage` 同名同语义的接缝
+就是为了今天能被这里包走（`install_credential_store()`，两道闸：`database_path` +
+`_connect`）。三点与账本面的差异，都是那张表的形状决定的：
+
+1. **归类只能在语句执行时补**。`usage` 的写收口在 `_execute` ⇒ "解析到真库路径"发生在写
+   作用域**之内**；`user_store` 的读腿（`get_record` / `list_records` / `count_by_algorithm`
+   / `column_names`）与写腿都直接 `_connect()`，路径先解析、语句后执行 ⇒ 解析那一刻根本
+   分不清读写。所以先按 read 记一笔，再由 sqlite 的 trace 回调把那一笔**升**成 write。
+   写证据取自 sqlite 回传的语句文本（含 DDL），不取函数名清单：以后给 `user_store` 加一条
+   写腿，清单那套要有人记得回到本文件加名字，忘了的那一次是静默的。
+   同一句话也解释了为什么这一面**不发**中途的 read warning（`warn_on_read=False`）：warning
+   得当场发，而归类当场还没定——一条写改道会先收到一句"只读"的提醒。提醒没有丢，它搬到了
+   收尾的 `[credential-guard]` 汇总与 `credential_read_redirects()`，那里拿的是定过型的记录。
+2. **另开一个 `LedgerGuard` 实例**，不与账本共用 records。共享 list 才能让会话钩子逐例判红
+   这件事"同形"，但两枚 list 各记各的，失败信息与终端汇总才说得出**是哪张表**被写——共用
+   一枚 tuple 装不下这个事实，硬塞进 `kind` 会撞 `LedgerIsolationGuardTests` 的取值等式。
+   改道目标仍是同一份临时库（§6.1 的同库要求由测试面兑现）。
+3. **0 字节落点**（Task 2 移交的残余）：`user_store._connect()` 每次都会 `mkdir` 父目录并
+   打开文件，env 被清掉时那个落点是 `data/conversations.db`。改道之后它落到临时库里 ⇒
+   "凭空在生产数据目录造出一份空库"这条路径整体消失。钉子 =
+   `test_credentials_contract.py::CredentialStoreGuardTests`（假真库在场外仍不存在）与
+   `::CredentialGuardWiringTests`（真库的表清单与在场性在改道读之后逐项不变）。
 """
 from __future__ import annotations
 
 import contextlib
 import os
+import re
 import sqlite3
 import sys
 import threading
 import warnings
 from pathlib import Path
 from typing import Any, Callable
 
 import pytest
 
 TESTS_DIR = Path(__file__).resolve().parent
@@ -88,25 +117,60 @@ REAL_DB_PATHS: tuple[Path, ...] = (
     REAL_DB_PATH,
     REPO_ROOT_DATA_DIR / "conversations.db",
 )
 #: 观测面与会话面共用的 env 源（唯一出处 = `usage.database_path`）。
 LEDGER_ENV_VAR = "CONVERSATION_DB_PATH"
 
 #: 一笔改道的归类（N1）：只有 `write` 逐例判红，`read` 只出 warning。
 REDIRECT_WRITE = "write"
 REDIRECT_READ = "read"
 
+#: 一句 SQL 是不是写。**含 DDL**：`user_store.ensure_user_credentials_schema()` 的那次
+#: `executescript(CREATE TABLE ...)` 正是 Task 2「读路径不许建表」要盯的形状，只认 DML 会把
+#: 它读成静默。`PRAGMA x=y` 一并算写（它改的是库的属性）。裸 `BEGIN` / `COMMIT` **不算**：
+#: 前者只是事务标记，后者由 `executescript` 在进入时无条件回放过一次，拿它判写会把一次
+#: 纯读的建库动作误判成事故（N1 的病灶换了个名字回来）。
+#: 反过来说，判据取自 sqlite 回传的语句文本而不是"函数名清单"，是为了让以后新加的那条写腿
+#: **不需要有人记得回来加名字**——清单漏一项的那一次是静默的，而这张表里放的是凭据行。
+_WRITE_STATEMENT = re.compile(
+    r"^\s*(?:INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|VACUUM|REINDEX|ATTACH"
+    r"|PRAGMA\s+\w+\s*=)",
+    re.IGNORECASE,
+)
+
 #: 每次改道记一笔：``(被改道的原始路径, 本会话登记的生效临时路径, "read"|"write")``。
 _REDIRECTS: list[tuple[str, str, str]] = []
 _SESSION_TMP_DB: Path | None = None
 _GUARDED = False
 _SESSION_GUARD: "LedgerGuard | None" = None
+#: 凭据面（`app/user_store.py`）的护栏实例：与账本面**同目标、不同 records**。
+_CREDENTIAL_GUARD: "LedgerGuard | None" = None
+
+
+class _PendingRedirect:
+    """一条已经改道、但**归类还没定型**的连接（凭据面专用）。
+
+    为什么这张表不能像账本那样在解析路径那一刻就定归类：`usage` 的写收口在 `_execute`，
+    解析发生在写作用域之内；`user_store` 的读腿与写腿都直接 `_connect()`，路径先解析、语句
+    后执行。于是只能先按 read 记下这一笔，等 sqlite 把真正执行过的语句回传上来再升成 write。
+
+    `done` 是必需的：一条连接会执行多条写语句（`record_login_failure` 就是 UPDATE + UPDATE），
+    每次都升一次会让"这一例写了几笔"变成"它执行了几条写语句"，判红信息跟着虚高。
+    """
+
+    __slots__ = ("index", "source", "target", "done")
+
+    def __init__(self, index: int, source: str, target: str) -> None:
+        self.index = index
+        self.source = source
+        self.target = target
+        self.done = False
 
 
 # --------------------------------------------------------------------------
 # 路径判定（N3：相对路径的三候选）
 # --------------------------------------------------------------------------
 def path_candidates(path: Path | str) -> tuple[Path, ...]:
     """一个 `database_path()` 的返回值**可能真正落地**的全部绝对路径。
 
     相对路径在这里是三重的：`Path("data/conversations.db")` 打开的是
     `<cwd>/data/conversations.db`，而 `BACKEND_DIR/path` 与 `BACKEND_DIR.parent/path`
@@ -134,95 +198,133 @@ def path_is_protected(path: Path | str) -> bool:
             except (ValueError, OSError):
                 continue
             return True
     return False
 
 
 # --------------------------------------------------------------------------
 # 护栏本体（会话 fixture 与契约用例**共用同一份实现**）
 # --------------------------------------------------------------------------
 class LedgerGuard:
-    """`usage.database_path` / `usage._execute` 的改道闸 + 读写归类。
+    """一条数据流的改道闸 + 读写归类：`install()` 包账本面，`install_credential_store()` 包凭据面。
 
     为什么读写要分开（N1）：`_query` 与 `_execute` 都会调 `_connect(None)`，而
     `_connect` 内部就是 `database_path()` ⇒ 「解析到真库路径」这件事本身分不清读还是写。
     分得清的唯一位置是**调用栈**：`_execute` 是写路径的收口（`log_usage` 的 INSERT 只能
     从它出去），所以在它的动态范围内解析到的路径记 `write`，其余记 `read`。
 
+    凭据面没有那个收口（读腿与写腿都直接 `_connect()`），归类因此改成"先记 read、由 sqlite
+    回传的语句把那一笔升成 write"。两条路共用同一份 records 结构与同一枚 `violations()` 判据，
+    所以会话钩子的归责口径对两张表是同形的。
+
     本类不碰任何测试全局，因此契约用例可以另开一个实例（保护集指向临时目录）来**直接
-    驱动真的 `usage._query` / `usage._execute`**，验证这道归类本身没有被写歪。
+    驱动真的 `usage._query` / `usage._execute` / `user_store` 的读写腿**，验证归类本身没被写歪。
     """
 
     def __init__(self, *, original_path: Callable[[], Path], target: Path,
-                 protected_dirs: tuple[Path, ...] = PROTECTED_DATA_DIRS) -> None:
+                 protected_dirs: tuple[Path, ...] = PROTECTED_DATA_DIRS,
+                 label: str = "[ledger-guard]",
+                 subject: str = "真实账本",
+                 warn_on_read: bool = True) -> None:
         self.original_path = original_path
         self.target = Path(target)
         self.protected_dirs = tuple(protected_dirs)
+        #: 这条流打在终端/warning 上的名字。两张表共用同一份改道逻辑，但**出事的是哪张表**
+        #: 必须分得清：凭据面沿用"账本"字样会让人先去查 usage sink。默认值就是账本面的原文，
+        #: 所以 `install(usage)` 那条老路径上的输出一个字节都没变。
+        self.label = label
+        self.subject = subject
+        #: 凭据面的归类要到语句执行时才定型（见 `guarded_store_database_path` 的理由块），而
+        #: warning 必须当场发——于是一条**写**改道会先收到一句"只读"的提醒。所以凭据面把中途
+        #: warning 关掉，同一份提醒改由收尾的 `[credential-guard]` 汇总承担（那时归类已定型）。
+        #: 账本面保持原样：它的归类在解析那一刻就是真的，输出一个字节都没动。
+        self.warn_on_read = warn_on_read
         #: `(原始路径, 改道后的临时路径, kind)`，按发生顺序。
         self.records: list[tuple[str, str, str]] = []
         self._local = threading.local()
         self._warned: set[str] = set()
         self._restore: list[Callable[[], None]] = []
         #: 安装时抓下来的**真** `usage._execute`（可能已是上一层护栏的包装）。
         self._real_execute: Callable[[Any, Callable[[Any], Any]], Any] | None = None
         #: 同上，装的是**真** `usage._connect`（第三道闸，Task 7 评审 Minor-1）。
         self._real_connect: Callable[..., Any] | None = None
+        #: 凭据面的**真** `user_store._connect`（写证据挂在这条连接上，见 `_PendingRedirect`）。
+        self._real_store_connect: Callable[..., Any] | None = None
 
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
 
+    def install_credential_store(self, store_module: Any) -> "LedgerGuard":
+        """把两道闸挂到 `app.user_store` 上：`database_path`（改道）+ `_connect`（定归类）。
+
+        接缝的名字与 `usage` 同形不是巧合：Task 2 就是照"`tests/conftest.py` 包 `usage` 的
+        手法必须也能把本模块包走"这个要求做出 `database_path()` 的（那份注释还钉着"每次连接
+        时解析、只有这一个解析点"）。这里没有 `_execute` 那道闸——那张表没有写收口函数，
+        写证据改由 sqlite 的 trace 回调提供，见 `guarded_store_connect`。
+        """
+        for name, replacement in (("database_path", self.guarded_store_database_path),
+                                  ("_connect", self.guarded_store_connect)):
+            previous = getattr(store_module, name)
+            if name == "_connect":
+                self._real_store_connect = previous
+            setattr(store_module, name, replacement)
+            self._restore.append(
+                lambda module=store_module, key=name, value=previous: setattr(
+                    module, key, value))
+        return self
+
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
 
-    # --- 两道闸 -----------------------------------------------------------
+    # --- 账本面：`database_path` / `_execute` / `_connect` -----------------
     def guarded_database_path(self) -> Path:
         path = Path(self.original_path())
         if not self.is_protected(path):
             return path
         kind = self.current_kind()
         self.records.append((str(path), str(self.target), kind))
-        if kind == REDIRECT_READ:
+        if kind == REDIRECT_READ and self.warn_on_read:
             # 读不是事故，但也不能完全静默：它说明这条用例的账本 env 没设上，
             # 下一次有人把读改成写就没有这道提醒了。
             key = f"{path}|{self.target}"
             if key not in self._warned:
                 self._warned.add(key)
                 warnings.warn(
-                    f"[ledger-guard] 测试**只读**了仓库真实账本 {path} ⇒ 已改道到"
+                    f"{self.label} 测试**只读**了仓库{self.subject} {path} ⇒ 已改道到"
                     f" {self.target}（读不判红；写才判红，见 tests/conftest.py N1）",
                     RuntimeWarning, stacklevel=3)
         return self.target
 
     def guarded_execute(self, path: Any, action: Callable[[Any], Any]) -> Any:
         if self._real_execute is None:
             raise RuntimeError("LedgerGuard 没 install() 就被调用（写路径判定闸未装上）")
         with self._write_scope():
             return self._real_execute(path, action)
 
@@ -237,20 +339,77 @@ class LedgerGuard:
         `ensure_schema=False` 保持原样：那是 `_query` 的读路径，判成 write 就会把状态页/聚合
         类用例成批误诊（N1 的病灶，`test_a_pure_read_…` 立刻红）。
         """
         if self._real_connect is None:
             raise RuntimeError("LedgerGuard 没 install() 就被调用（建表闸未装上）")
         if not kwargs.get("ensure_schema", True):
             return self._real_connect(*args, **kwargs)
         with self._write_scope():
             return self._real_connect(*args, **kwargs)
 
+    # --- 凭据面（`app/user_store.py`）的两道闸 ----------------------------
+    def guarded_store_database_path(self) -> Path:
+        """改道与归类复用账本面那一套，只多留一条"这次落到了哪儿"的待定型记录。
+
+        先清后设是必需的：`user_store.database_path()` 也会被用例**直接**调用（`usage` 那边
+        同理），那次调用没有连接跟着，留下的待定型记录会把归类挂到**下一条**无关的连接上。
+
+        这条路上的 read warning 被 `warn_on_read=False` 关掉了：归类此刻还没定型，等它升到
+        write 时那句"只读"已经发出去了。提醒本身没丢——收尾的 `[credential-guard]` 汇总与
+        `credential_read_redirects()` 拿着的是定过型的记录。
+        """
+        before = len(self.records)
+        path = self.guarded_database_path()
+        if len(self.records) > before:
+            source, target, _kind = self.records[before]
+            self._local.pending = _PendingRedirect(before, source, target)
+        else:
+            self._local.pending = None
+        return path
+
+    def guarded_store_connect(self, *args: Any, **kwargs: Any) -> Any:
+        """真 `_connect()` 之后再挂写证据：路径已解析、连接已打开，语句还没跑。
+
+        `user_store._connect()` 自己会 `mkdir` 父目录并打开文件——这正是 Task 2 移交的"0 字节
+        落点"。改道发生在它前面（`guarded_store_database_path`），所以那个落点整体落在临时库里。
+        """
+        if self._real_store_connect is None:
+            raise RuntimeError("LedgerGuard 没 install_credential_store() 就被调用（凭据写闸未装上）")
+        self._local.pending = None
+        connection = self._real_store_connect(*args, **kwargs)
+        pending = getattr(self._local, "pending", None)
+        self._local.pending = None
+        if pending is not None:
+            connection.set_trace_callback(self._write_marker(pending))
+        return connection
+
+    def _write_marker(self, pending: _PendingRedirect) -> Callable[[str], None]:
+        def mark(statement: str) -> None:
+            if pending.done or not _WRITE_STATEMENT.match(str(statement or "")):
+                return
+            pending.done = True
+            self._upgrade_record_to_write(pending)
+        return mark
+
+    def _upgrade_record_to_write(self, pending: _PendingRedirect) -> None:
+        """把那一笔从 read 升成 write —— 会话钩子判红的输入就是这一笔。
+
+        位置校验不是多余的小心：`records` 是会被上层换手的 list（会话 fixture 就把账本面的
+        `records` 换成了模块级 `_REDIRECTS`），照着索引去改别人位置上的笔之前得先验货。
+        对不上时的出路是**另记一笔 write**，不是静默返回：漏判一次凭据写的代价比多判一笔高。
+        """
+        current = (pending.source, pending.target, REDIRECT_READ)
+        if 0 <= pending.index < len(self.records) and self.records[pending.index] == current:
+            self.records[pending.index] = (pending.source, pending.target, REDIRECT_WRITE)
+            return
+        self.records.append((pending.source, pending.target, REDIRECT_WRITE))
+
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
@@ -313,92 +472,218 @@ def real_ledger_row_count(path: Path = REAL_DB_PATH) -> int | None:
         return int(connection.execute("SELECT COUNT(*) FROM llm_request_logs").fetchone()[0])
     finally:
         connection.close()
 
 
 def real_ledger_row_counts() -> dict[str, int | None]:
     """N3：保护集里的**每一份**真库都要点数（仓库根那份历史库同样不许被写脏）。"""
     return {str(path): real_ledger_row_count(path) for path in REAL_DB_PATHS}
 
 
+# --------------------------------------------------------------------------
+# 凭据面（`app/user_store.py` 的 `user_credentials`）的对外口径
+# --------------------------------------------------------------------------
+def credential_guard_is_active() -> bool:
+    """凭据面的两道闸是不是真挂在 `user_store` 上（而且是会话那一个实例）。
+
+    只问"fixture 跑过没"不够：接线是一行 `install_credential_store()`，删掉它 `guard_is_active()`
+    照旧为真、`test_llm_egress_guard.py` 的账本钉照旧绿，而这张表已经没人盯了。属性相等才是
+    "挂在这个实例上"的证据。
+    """
+    guard = _CREDENTIAL_GUARD
+    if guard is None:
+        return False
+    from app import user_store as store_module
+
+    return (store_module.database_path == guard.guarded_store_database_path
+            and store_module._connect == guard.guarded_store_connect)
+
+
+def effective_credential_path() -> Path:
+    """`user_store.database_path()` 现在真正解析到的路径（护栏改道**之后**的值）。"""
+    from app import user_store as store_module
+
+    return Path(store_module.database_path())
+
+
+def credential_redirects() -> tuple[tuple[str, str, str], ...]:
+    """本会话内**凭据面**被拦下的全部改道，逐笔 `(src, dst, kind)`。正常应为空。"""
+    return tuple(_CREDENTIAL_GUARD.records) if _CREDENTIAL_GUARD is not None else ()
+
+
+def credential_write_redirects() -> tuple[tuple[str, str, str], ...]:
+    """凭据面上的**写**改道——这些才是一例判红的东西（与 `write_redirects()` 同形）。"""
+    return _CREDENTIAL_GUARD.violations() if _CREDENTIAL_GUARD is not None else ()
+
+
+def credential_read_redirects() -> tuple[tuple[str, str, str], ...]:
+    """凭据面上的**读**改道（不判红；提醒走收尾的 `[credential-guard]` 汇总）。"""
+    guard = _CREDENTIAL_GUARD
+    return guard.read_redirects() if guard is not None else ()
+
+
+def real_db_tables(path: Path = REAL_DB_PATH) -> tuple[str, ...] | None:
+    """真库里的表清单；**文件不在场**时返回 ``None``（与"有一份空库"区分开）。
+
+    取"表清单"而不是"字节数/时间戳"当快照：本仓库的 dev 后端可能正往同一份库里写会话行，
+    拿 mtime 判据会把那种正常活动读成测试事故。这张表的义务只是"不许凭测试多出来"。
+    """
+    if not path.is_file():
+        return None
+    connection = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
+    try:
+        return tuple(str(row[0]) for row in connection.execute(
+            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
+    finally:
+        connection.close()
+
+
+def real_user_credential_row_count(path: Path = REAL_DB_PATH) -> int | None:
+    """指定真库里 `user_credentials` 的行数；文件/表不在场时 ``None``（0 行等价）。
+
+    表名从 `user_store.TABLE_NAME` 读，不在这里再抄一遍字面量：那张表叫什么由产品代码说。
+    """
+    from app import user_store as store_module
+
+    if not path.is_file():
+        return None
+    connection = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
+    try:
+        table = connection.execute(
+            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
+            (store_module.TABLE_NAME,),
+        ).fetchone()
+        if table is None:
+            return None
+        return int(connection.execute(
+            f"SELECT COUNT(*) FROM {store_module.TABLE_NAME}").fetchone()[0])
+    finally:
+        connection.close()
+
+
+def real_user_credential_row_counts() -> dict[str, int | None]:
+    """保护集里每一份真库的凭据行数（与 `real_ledger_row_counts()` 同一份库清单）。"""
+    return {str(path): real_user_credential_row_count(path) for path in REAL_DB_PATHS}
+
+
 # --------------------------------------------------------------------------
 # fixtures
 # --------------------------------------------------------------------------
 @pytest.fixture(scope="session", autouse=True)
 def isolated_llm_ledger(tmp_path_factory):
-    """会话级：env 默认值 + `usage.database_path` / `usage._execute` 的兜底改道闸。"""
-    global _SESSION_TMP_DB, _GUARDED, _SESSION_GUARD
+    """会话级：env 默认值 + 账本面三道闸 + 凭据面两道闸的兜底改道闸。"""
+    global _SESSION_TMP_DB, _GUARDED, _SESSION_GUARD, _CREDENTIAL_GUARD
 
+    from app import user_store as store_module
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
+    # 凭据面：**同一个目标文件**（规格 §6.1 要求 `user_credentials` 与 `conversations` 同库，
+    # 测试面也不许把它改到第二个文件去），但是**另一个实例**——两枚 records 各记各的，判红的
+    # 消息才说得出是哪张表被写。`original_path` 必须在 install 之前取，取的是真函数。
+    credential_guard = LedgerGuard(original_path=store_module.database_path,
+                                   target=_SESSION_TMP_DB,
+                                   label="[credential-guard]",
+                                   subject="真实凭据表",
+                                   warn_on_read=False)
+    credential_guard.install_credential_store(store_module)
+    _CREDENTIAL_GUARD = credential_guard
     try:
         yield _SESSION_TMP_DB
     finally:
+        credential_guard.uninstall()
+        _CREDENTIAL_GUARD = None
         guard.uninstall()
         _SESSION_GUARD = None
         _GUARDED = False
         if previous_env is None:
             os.environ.pop(LEDGER_ENV_VAR, None)
         else:
             os.environ[LEDGER_ENV_VAR] = previous_env
 
 
 @pytest.fixture(autouse=True)
 def fail_the_offending_test_on_repo_ledger_write():
-    """每个用例单独归责：本例期间发生过**写**改道 ⇒ 本例红（N1：读只 warning）。"""
+    """每个用例单独归责：本例期间发生过**写**改道 ⇒ 本例红（N1：读只 warning）。
+
+    两张表各查各的、各说各的话：账本面那条消息里的修法是"关 usage sink"，凭据面那条是
+    "把 `CONVERSATION_DB_PATH` 指到临时目录"——把两条捏成一句通用文案，等于给肇事者一张
+    错地图（这正是 N1 之前那版护栏被诟病的形状）。
+    """
     guard = _SESSION_GUARD
+    store_guard = _CREDENTIAL_GUARD
     before = len(guard.records) if guard is not None else len(_REDIRECTS)
+    store_before = len(store_guard.records) if store_guard is not None else 0
     yield
     source = guard.records if guard is not None else _REDIRECTS
     offenders = [record for record in source[before:] if record[2] == REDIRECT_WRITE]
-    if not offenders:
-        return
-    detail = "；".join(f"写 {src} ⇒ 被护栏改道到 {dst}" for src, dst, _ in offenders)
-    raise AssertionError(
-        "测试把 LLM usage 账本**写**进了保护集下的真实库（评审 I-2 同类事故）。"
-        f"本例要么没关 usage sink、要么没把 `CONVERSATION_DB_PATH`/`init_usage_db` 指到"
-        f"临时目录：{detail}。修法照 `PackageEntryPointTests`（显式内存 sink）或 "
-        f"`_RagMigrationFixture`（临时库 + `set_usage_sink(None)`）。")
+    store_source = store_guard.records if store_guard is not None else []
+    store_offenders = [record for record in store_source[store_before:]
+                       if record[2] == REDIRECT_WRITE]
+    if offenders:
+        detail = "；".join(f"写 {src} ⇒ 被护栏改道到 {dst}" for src, dst, _ in offenders)
+        raise AssertionError(
+            "测试把 LLM usage 账本**写**进了保护集下的真实库（评审 I-2 同类事故）。"
+            f"本例要么没关 usage sink、要么没把 `CONVERSATION_DB_PATH`/`init_usage_db` 指到"
+            f"临时目录：{detail}。修法照 `PackageEntryPointTests`（显式内存 sink）或 "
+            f"`_RagMigrationFixture`（临时库 + `set_usage_sink(None)`）。")
+    if store_offenders:
+        detail = "；".join(f"写 {src} ⇒ 被护栏改道到 {dst}" for src, dst, _ in store_offenders)
+        raise AssertionError(
+            "测试往保护集下的真实库里**写**了凭据行（`user_credentials`，Task 2 移交的盲区）。"
+            f"本例要么没把 `CONVERSATION_DB_PATH` 指到临时目录、要么在 env 被 clear 的窗口里"
+            f"调了 `user_store` 的写腿：{detail}。修法照 `_CredentialDbPerTest`（每例一份临时"
+            f"库 + `ensure_user_credentials_schema()`）。")
 
 
 def pytest_terminal_summary(terminalreporter):
     """收尾把改道计数打在终端上：跑一次全套件就是一份同类隔离漏洞清单。
 
     读/写分开打：写 = 事故（已经逐例判红过），读 = 提醒（护栏兜住了，但那条用例的
     账本 env 其实没设上）。
     """
     guard = _SESSION_GUARD
     records = guard.records if guard is not None else _REDIRECTS
+    _report_redirects(terminalreporter, "[ledger-guard]", "真实账本**写**账", "真实账本",
+                      records)
+    if _CREDENTIAL_GUARD is not None:
+        _report_redirects(terminalreporter, "[credential-guard]",
+                          "真实凭据表**写**行", "真实凭据表", _CREDENTIAL_GUARD.records)
+
+
+def _report_redirects(terminalreporter, label: str, write_subject: str, read_subject: str,
+                      records: tuple[tuple[str, str, str], ...]
+                      | list[tuple[str, str, str]]) -> None:
+    """一张表的改道清单（两张表共用同一份口径，只差被点名的那张表——账本面的文案原样保留）。"""
     if not records:
         return
     writes = [record for record in records if record[2] == REDIRECT_WRITE]
     reads = [record for record in records if record[2] == REDIRECT_READ]
     if writes:
         terminalreporter.write_line(
-            f"[ledger-guard] {len(writes)} 次「往保护集下的真实账本**写**账」被护栏拦下：")
+            f"{label} {len(writes)} 次「往保护集下的{write_subject}」被护栏拦下：")
         for source, target, _kind in writes:
-            terminalreporter.write_line(f"[ledger-guard]   {source} ⇒ {target}")
+            terminalreporter.write_line(f"{label}   {source} ⇒ {target}")
     if reads:
         terminalreporter.write_line(
-            f"[ledger-guard] {len(reads)} 次「读保护集下的真实账本」被改道（N1：读不判红）：")
+            f"{label} {len(reads)} 次「读保护集下的{read_subject}」被改道（N1：读不判红）：")
         for source, target, _kind in reads[:10]:
-            terminalreporter.write_line(f"[ledger-guard]   {source} ⇒ {target}")
+            terminalreporter.write_line(f"{label}   {source} ⇒ {target}")
         if len(reads) > 10:
             terminalreporter.write_line(
-                f"[ledger-guard]   ……另有 {len(reads) - 10} 次同类读改道")
+                f"{label}   ……另有 {len(reads) - 10} 次同类读改道")

## B. NEW backend/app/credentials_migration.py (full)
     1	"""受限迁移路径（规格 §8.2）。全仓唯一能生产 legacy 凭据行的地方。
     2	
     3	它**只**服务"从 SEC-A 之前的版本升级"这一条路径：没有升级工件 ⇒ 没有 legacy 行。
     4	把"缺凭据行"当成"那就自动造 legacy"是把升级输入当成了全新安装的凭据来源（M19），
     5	SECA-04b 按"全新安装产出的行全为 argon2id、`legacy_count=0`"判它。
     6	"""
     7	
     8	from __future__ import annotations
     9	
    10	import json
    11	import re
    12	from dataclasses import dataclass
    13	from pathlib import Path
    14	from typing import Any
    15	
    16	from app import credentials, user_store
    17	
    18	#: 工件的默认位置在 `data/`：§4 SEC-A-004 的 closure 扫描按 `app/` 与 `config/` 数 0 命中，
    19	#: 一份**注定要被删除**的升级输入放在那两个地方会自相矛盾，也更早变成第二处凭据材料真源。
    20	#: 相对路径与 `user_store` 的库默认值同口径（都按进程 cwd 解析），部署脚本换工作目录时两件事
    21	#: 一起换，不存在"库搬走了、工件还在原地"这种半截形态。
    22	LEGACY_INPUT_PATH = Path("data/legacy_credentials.json")
    23	
    24	#: 顶层键**封闭**：多一个键就是有人往这份工件里塞了本规格不认识的东西，整份拒读。
    25	ARTIFACT_KEYS = frozenset({"generated_at", "source", "credentials"})
    26	
    27	#: 出处两键是"升级工件"与"随手放着的凭据文件"之间唯一可机器辨别的差别。§8.2 的整节立论
    28	#: 就靠这条区分，所以它不能只写在文档里。
    29	_PROVENANCE_KEYS = frozenset({"generated_at", "source"})
    30	
    31	_LEGACY_HEX = re.compile(r"^[0-9a-f]{64}$")
    32	
    33	
    34	class MigrationArtifactError(RuntimeError):
    35	    """升级工件形态不对。整体拒绝，绝不"跳过坏条目继续导几个"。"""
    36	
    37	
    38	@dataclass(frozen=True)
    39	class MigrationReport:
    40	    """导入这一腿的结果。三个字段只到**用户名**粒度：digest 是凭据材料，不进可打印面。
    41	
    42	    `reason` 说的是"为什么没导"，永远不说"口令对不对"——写失败根本不走这条道（见
    43	    `import_from_artifact` 对 `user_store.CredentialStoreError` 的态度）。
    44	    """
    45	
    46	    artifact_present: bool
    47	    imported: tuple[str, ...]
    48	    skipped: tuple[str, ...]
    49	    reason: str = ""
    50	
    51	
    52	@dataclass(frozen=True)
    53	class AccountStatus:
    54	    """一个账号的凭据状态。没有 `password_hash` 这一格：状态面要被 `migration-status` 整行
    55	    打印，密文材料进日志是 §6.1/§8.8 一致禁止的事（口径同 `CredentialRecord` 的 `repr=False`）。
    56	    """
    57	
    58	    username: str
    59	    algorithm: str
    60	    credentials_version: int
    61	    must_change: bool
    62	    locked_until: str | None
    63	    updated_at: str
    64	
    65	
    66	@dataclass(frozen=True)
    67	class MigrationStatus:
    68	    legacy_count: int
    69	    argon2id_count: int
    70	    accounts: tuple[AccountStatus, ...]
    71	
    72	
    73	def read_artifact(path: Path = LEGACY_INPUT_PATH) -> dict[str, str]:
    74	    """把工件读成 `username -> 64 位小写 hex`。任何一处形态错 ⇒ 整份拒绝。
    75	
    76	    校验做在这里而不是 `user_store.import_legacy_digest` 里，是因为脏值的症状位置不对：写手
    77	    只落一行，脏 digest 要等到那个人**第一次登录**才被 `verify_password` 认出来，而登录面的
    78	    分类里没有"这条凭据永远验不过"这一项——它会被读成"用户记错了口令"，且没人报警。
    79	    导入即拒才是运维一次能修完的失败。
    80	    """
    81	    if not path.exists():
    82	        return {}
    83	    try:
    84	        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    85	    except json.JSONDecodeError as exc:
    86	        # `JSONDecodeError` 的文案只有"第几行第几列"，不回显文档内容 ⇒ 异常链可以照留：
    87	        # 定位能力一点不丢，而 digest 一个字节也不会进任何日志面。
    88	        raise MigrationArtifactError("迁移输入不是合法 JSON") from exc
    89	    if not isinstance(payload, dict):
    90	        raise MigrationArtifactError("迁移输入顶层必须是对象")
    91	    unknown = set(payload) - ARTIFACT_KEYS
    92	    if unknown:
    93	        raise MigrationArtifactError(f"迁移输入含未知字段：{sorted(unknown)}")
    94	    missing = _PROVENANCE_KEYS - set(payload)
    95	    if missing:
    96	        raise MigrationArtifactError(f"迁移输入缺少出处字段：{sorted(missing)}")
    97	    for key in sorted(_PROVENANCE_KEYS):
    98	        value = payload[key]
    99	        if not isinstance(value, str) or not value.strip():
   100	            raise MigrationArtifactError(f"出处字段 {key!r} 必须是非空字符串")
   101	    block = payload.get("credentials")
   102	    if block is None:
   103	        raise MigrationArtifactError("迁移输入缺少 credentials")
   104	    if not isinstance(block, dict):
   105	        raise MigrationArtifactError("credentials 必须是 username→digest 的对象")
   106	    if not block:
   107	        # 空 credentials 报出去，而不是当成"没有工件"：`artifact_present` 说的是文件在不在场，
   108	        # 一份在场但导 0 个人的输入被读成全新安装，等于把升级失败伪装成不需要升级。
   109	        raise MigrationArtifactError("credentials 为空：这份输入不导任何人，不是升级工件")
   110	    normalized: dict[str, str] = {}
   111	    for username, digest in block.items():
   112	        # `json.loads` 的对象键必为 str，所以这里只判"是不是一个能当主键用的名字"。
   113	        if not username.strip():
   114	            # 空主键的行写得进去、查不出来，最后只能靠一次没人知道是谁的 DELETE 收掉。
   115	            raise MigrationArtifactError("credentials 含空白用户名")
   116	        if username != username.strip():
   117	            # 带首尾空白的名字不做静默 trim：那等于把 digest 发给另一个账号。
   118	            raise MigrationArtifactError(f"用户名 {username!r} 带首尾空白")
   119	        if not isinstance(digest, str) or not _LEGACY_HEX.match(digest.strip().lower()):
   120	            # 消息里只出现用户名，不出现那串值：它进异常消息就等于进服务端日志与运维控制台。
   121	            raise MigrationArtifactError(f"{username} 的迁移输入不是 64 位 hex")
   122	        normalized[username] = digest.strip().lower()
   123	    return normalized
   124	
   125	
   126	def import_from_artifact(
   127	    path: Path = LEGACY_INPUT_PATH, *, only_missing: bool = True
   128	) -> MigrationReport:
   129	    """读工件 → 逐行交给受限写手 `import_legacy_digest`。
   130	
   131	    三件事是刻意的：
   132	
   133	    1. **不建表**。schema 的唯一出处是 `user_store.ensure_user_credentials_schema()`，由启动
   134	       编排 / CLI 调（Task 2 的裁定：读路径顺手建表等于让"env 被清掉"的每次调用往真库提交
   135	       一次 DDL）。表不在场时这里就抛 `no such table`，指向漏掉初始化的人。
   136	    2. **已存在的行只跳过，绝不覆写**。重跑导入把一条已升级的 argon2id 行降回 legacy，是
   137	       `legacy_count` 永远闭不上的最直接形状；写手用的是 `INSERT ... DO NOTHING`，而这里连
   138	       "尝试覆写"这个动作都不出现，读代码的人不必先去推那段 SQL 的语义。
   139	    3. **`user_store.CredentialStoreError` 原样逃出去**。那是存储事故（锁、盘满、约束），
   140	       既不是"这个人的口令错了"，也不是一次可以记进 `skipped` 的冲突：咽掉它，SECA-04 的
   141	       `legacy_count` 会在一个没人知道的数上停住，而登录面继续对同一个人报"用户名或密码错误"。
   142	    """
   143	    block = read_artifact(path)
   144	    if not block:
   145	        return MigrationReport(
   146	            artifact_present=False,
   147	            imported=(),
   148	            skipped=(),
   149	            reason="迁移输入不存在：全新安装不生产 legacy 行",
   150	        )
   151	    imported: list[str] = []
   152	    skipped: list[str] = []
   153	    declined: list[str] = []
   154	    for username, digest in sorted(block.items()):
   155	        if only_missing and user_store.get_record(username) is not None:
   156	            skipped.append(username)
   157	            continue
   158	        # 写手的返回值就是"这一行落地了没有"。False 只可能是撞了主键（`only_missing=False`
   159	        # 或并发），那时把它报成"导入成功"就是台账与实际行数分叉——SECA-04 判闭合用的正是
   160	        # 这个数。
   161	        if user_store.import_legacy_digest(username, digest, must_change=True):
   162	            imported.append(username)
   163	        else:
   164	            declined.append(username)
   165	    reason = ""
   166	    if declined:
   167	        reason = f"落行被拒（目标账号已有凭据行）：{sorted(declined)}"
   168	    return MigrationReport(True, tuple(imported), tuple(sorted([*skipped, *declined])), reason)
   169	
   170	
   171	def status() -> MigrationStatus:
   172	    """`migration-status` 的事实采集（Task 7 的 CLI 直接打印它）。
   173	
   174	    计数读 `count_by_algorithm()`（一次 GROUP BY），逐行读 `list_records()`：两处都走
   175	    `user_store`，本模块不自己开连接，免得这张表的第二个读口径从这里长出来。
   176	    """
   177	    counts = user_store.count_by_algorithm()
   178	    rows = tuple(
   179	        AccountStatus(
   180	            username=record.username,
   181	            algorithm=record.algorithm,
   182	            credentials_version=record.credentials_version,
   183	            must_change=record.must_change,
   184	            locked_until=record.locked_until,
   185	            updated_at=record.updated_at,
   186	        )
   187	        for record in user_store.list_records()
   188	    )
   189	    return MigrationStatus(
   190	        legacy_count=int(counts.get(credentials.ALGORITHM_LEGACY_SHA256, 0)),
   191	        argon2id_count=int(counts.get(credentials.ALGORITHM_ARGON2ID, 0)),
   192	        accounts=rows,
   193	    )

## C. backend/data/legacy_credentials.json (full; digests only, no plaintext)
     1	{
     2	  "generated_at": "2026-09-25T11:20:34.813211+00:00",
     3	  "source": "app/auth.py@pre-SEC-A",
     4	  "credentials": {
     5	    "admin": "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9",
     6	    "sales01": "6bc0a63cb29c92306020c0a6bbc358cc4628db277dc06e253535e126517ad637",
     7	    "hr01": "070a3b5e8d4bd5c46acccb91c9c54614c0cd649e78c4c4719e3a64270bae5ddf",
     8	    "user": "e606e38b0d8c19b24cf0ee3808183162ea7cd63ff7912dbb22b5e803286b4446",
     9	    "viewer": "65375049b9e4d7cad6c9ba286fdeb9394b28135a3e84136404cfccfdcc438894"
    10	  }
    11	}

## D. backend/tests/test_credentials_contract.py (full; Tasks 1-2 classes already reviewed, focus on migration/guard additions)
     1	from __future__ import annotations
     2	
     3	import ast
     4	import dataclasses
     5	import hashlib
     6	import inspect
     7	import json
     8	import os
     9	import re
    10	import sqlite3
    11	import sys
    12	import tempfile
    13	import threading
    14	import unittest
    15	from pathlib import Path
    16	from unittest import mock
    17	
    18	BACKEND_DIR = Path(__file__).resolve().parents[1]
    19	sys.path.insert(0, str(BACKEND_DIR))
    20	
    21	from app import credentials, credentials_migration, user_store  # noqa: E402
    22	
    23	#: `user_store.database_path` 在 **import 期**（会话护栏还没装上）的那一枚函数。
    24	#: 收集期早于会话 fixture（conftest 自己的理由："护栏的重定向发生在用例开始时，比 import
    25	#: 晚"），所以这里拿到的必然是产品代码那一份。护栏装上去之后再叫 `user_store.database_path()`，
    26	#: 返回的是**改道之后**的路径——那是测试面的事实，拿它去钉"本模块读哪个 env 键"等于让护栏
    27	#: 自证。只有钉 env 口径的用例用这一枚；钉"护栏在场"的用例走 `ledger_guard` 的公开口径。
    28	RAW_DATABASE_PATH = user_store.database_path
    29	
    30	#: 会话级护栏（`tests/conftest.py`）的对外口径。凭据表与账本同库同 env，所以"这张表有
    31	#: 没有人盯"只能从护栏自己问出来；import 失败 = 护栏文件被删 = 全套件 collection error。
    32	TESTS_DIR = BACKEND_DIR / "tests"
    33	if str(TESTS_DIR) not in sys.path:
    34	    sys.path.insert(0, str(TESTS_DIR))
    35	import conftest as ledger_guard  # noqa: E402
    36	
    37	
    38	class Argon2ProfileTests(unittest.TestCase):
    39	    def test_profile_is_the_owasp_minimum_baseline_and_is_a_code_constant(self):
    40	        self.assertEqual(2, credentials.ARGON2_TIME_COST)
    41	        self.assertEqual(19456, credentials.ARGON2_MEMORY_COST)
    42	        self.assertEqual(1, credentials.ARGON2_PARALLELISM)
    43	
    44	    def test_hasher_exposes_one_shared_instance_at_that_profile(self):
    45	        # 上游登录腿的测试会把 `credentials.hasher()` 返回对象的 verify 打桩：hasher() 每
    46	        # 次新建实例的话，被换掉的就不是真正参与校验的那一个，桩会静默空转。
    47	        shared = credentials.hasher()
    48	        self.assertIs(shared, credentials.hasher())
    49	        self.assertEqual(credentials.ARGON2_TIME_COST, shared.time_cost)
    50	        self.assertEqual(credentials.ARGON2_MEMORY_COST, shared.memory_cost)
    51	        self.assertEqual(credentials.ARGON2_PARALLELISM, shared.parallelism)
    52	
    53	    def test_hashed_password_is_a_verifiable_argon2id_phc_string(self):
    54	        encoded = credentials.hash_password("correct horse battery staple 12")
    55	        self.assertTrue(encoded.startswith("$argon2id$"), encoded)
    56	        outcome = credentials.verify_password(
    57	            "correct horse battery staple 12",
    58	            algorithm=credentials.ALGORITHM_ARGON2ID,
    59	            encoded=encoded,
    60	        )
    61	        self.assertTrue(outcome.ok)
    62	        self.assertFalse(outcome.needs_rehash)  # 刚按当前档位生成
    63	
    64	    def test_a_wrong_password_does_not_verify(self):
    65	        encoded = credentials.hash_password("right answer 1234567890")
    66	        outcome = credentials.verify_password(
    67	            "wrong answer 1234567890",
    68	            algorithm=credentials.ALGORITHM_ARGON2ID,
    69	            encoded=encoded,
    70	        )
    71	        self.assertFalse(outcome.ok)
    72	
    73	
    74	class AlgorithmColumnTests(unittest.TestCase):
    75	    """规格 §6.2：分派权威是列，编码串前缀只做交叉校验。"""
    76	
    77	    def test_argon2_column_with_a_non_argon2_payload_is_a_hard_failure(self):
    78	        with self.assertRaises(credentials.CredentialConfigError):
    79	            credentials.verify_password(
    80	                "x", algorithm=credentials.ALGORITHM_ARGON2ID, encoded="deadbeef"
    81	            )
    82	
    83	    def test_legacy_column_with_a_non_hex_payload_is_a_hard_failure(self):
    84	        with self.assertRaises(credentials.CredentialConfigError):
    85	            credentials.verify_password(
    86	                "x",
    87	                algorithm=credentials.ALGORITHM_LEGACY_SHA256,
    88	                encoded="zz" * 32,
    89	            )
    90	
    91	    def test_argon2_column_with_a_right_prefix_and_an_unparseable_body_is_a_hard_failure(self):
    92	        # "列说 argon2id、载荷是垃圾"这一类只有硬失败一种出口：库自己解不开 PHC 串时抛的是
    93	        # VerificationError("Decoding failed")，让它裸逃出去上游就是 500，咽进 ok=False 就是
    94	        # 静默的"口令错了"——后者会把一条脏数据变成永久登录不上且无人报错。
    95	        with self.assertRaises(credentials.CredentialConfigError):
    96	            credentials.verify_password(
    97	                "p",
    98	                algorithm=credentials.ALGORITHM_ARGON2ID,
    99	                encoded="$argon2id$v=19$m=1,t=1,p=1$aaa$bbb",
   100	            )
   101	
   102	    def test_an_unregistered_algorithm_value_is_a_hard_failure_not_a_try_both(self):
   103	        # 载荷故意用一条能对上 legacy 摘要的值：分派权威只有 algorithm 列这两枚取值，
   104	        # 列写错时"猜一个算法试试"会让它悄悄按另一种算法放行。
   105	        plain = "legacy-demo-password"
   106	        with self.assertRaises(credentials.CredentialConfigError):
   107	            credentials.verify_password(
   108	                plain,
   109	                algorithm="sha256",
   110	                encoded=hashlib.sha256(plain.encode("utf-8")).hexdigest(),
   111	            )
   112	
   113	    def test_a_legacy_digest_still_authenticates_under_the_legacy_column(self):
   114	        plain = "legacy-demo-password"
   115	        encoded = hashlib.sha256(plain.encode("utf-8")).hexdigest()
   116	        outcome = credentials.verify_password(
   117	            plain, algorithm=credentials.ALGORITHM_LEGACY_SHA256, encoded=encoded
   118	        )
   119	        self.assertTrue(outcome.ok)
   120	        self.assertTrue(outcome.needs_rehash)  # legacy 永远要收敛
   121	
   122	
   123	class DummyVerifyTests(unittest.TestCase):
   124	    def test_dummy_verification_costs_one_argon2_run_and_never_succeeds(self):
   125	        outcome = credentials.verify_dummy("anything at all 1234567890")
   126	        self.assertFalse(outcome.ok)
   127	
   128	    def test_the_dummy_payloads_own_plaintext_still_does_not_verify(self):
   129	        # 这条腿的哈希和明文都是本模块自己造的，底层 verify 对那串明文返回"匹配"。把它喂
   130	        # 进去必须照样 ok=False：调用方（未知账号 / 已停用 / 无凭据行）拿这个返回值当认证结论。
   131	        outcome = credentials.verify_dummy(credentials._DUMMY_PLAINTEXT)
   132	        self.assertIs(False, outcome.ok)
   133	        # needs_rehash 仍取底层判定，不许顺手写成常量——它说的是档位漂移，与成败无关。
   134	        self.assertEqual(
   135	            credentials.needs_rehash(credentials.dummy_hash()), outcome.needs_rehash
   136	        )
   137	
   138	    def test_dummy_string_is_generated_with_the_current_profile(self):
   139	        # 若 dummy 串档位与当前 profile 不一致，§7.3 的"工作量可比"就是空话。
   140	        self.assertTrue(
   141	            credentials.dummy_hash().startswith(
   142	                f"{credentials.ARGON2_HASH_PREFIX}v=19$"
   143	                f"m={credentials.ARGON2_MEMORY_COST},"
   144	                f"t={credentials.ARGON2_TIME_COST},"
   145	                f"p={credentials.ARGON2_PARALLELISM}$"
   146	            )
   147	        )
   148	
   149	
   150	class CapacityGateTests(unittest.TestCase):
   151	    """并发槽是可用性事实：耗尽只能以 PasswordCapacityError 出现，不许伪装成认证结论。"""
   152	
   153	    def test_a_full_slot_pool_turns_an_argon2_verify_into_a_capacity_error(self):
   154	        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
   155	            with self.assertRaises(credentials.PasswordCapacityError):
   156	                credentials.verify_password(
   157	                    "x",
   158	                    algorithm=credentials.ALGORITHM_ARGON2ID,
   159	                    encoded=credentials.dummy_hash(),
   160	                )
   161	
   162	    def test_a_full_slot_pool_turns_the_dummy_path_into_a_capacity_error(self):
   163	        # 哑校验若不占同一道闸，"账号不存在"那条腿就是绕过容量门的后门：攻击者拿不存在的
   164	        # 账号刷，闸门一次都不拦。
   165	        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
   166	            with self.assertRaises(credentials.PasswordCapacityError):
   167	                credentials.verify_dummy("x")
   168	
   169	    def test_the_slot_is_given_back_even_when_the_body_raises(self):
   170	        # 漏还一次槽 = 容量永久缩一格，跑几轮就把整道门焊死（形同拒绝服务）。
   171	        slots = threading.BoundedSemaphore(1)
   172	        with mock.patch.object(credentials, "_SLOTS", slots):
   173	            with self.assertRaises(ZeroDivisionError):
   174	                with credentials.argon2_slot():
   175	                    raise ZeroDivisionError
   176	            self.assertTrue(
   177	                slots.acquire(blocking=False), "异常路径必须归还槽位，且只归还一次"
   178	            )
   179	
   180	    def test_capacity_exhaustion_is_a_distinct_family_from_a_config_error(self):
   181	        # 这两类在上游翻译成不同的 HTTP 语义；谁成了谁的子类，一条 except 就会顺带吃掉另一类。
   182	        self.assertFalse(
   183	            issubclass(
   184	                credentials.PasswordCapacityError, credentials.CredentialConfigError
   185	            )
   186	        )
   187	        self.assertFalse(
   188	            issubclass(
   189	                credentials.CredentialConfigError, credentials.PasswordCapacityError
   190	            )
   191	        )
   192	
   193	
   194	class CentralisationScanTests(unittest.TestCase):
   195	    """SECA-05：口令参与运算的 hashlib 命中面 == 豁免表，且豁免表只有一个常任成员。"""
   196	
   197	    HASHES = re.compile(r"sha256|sha512|md5|blake2|pbkdf2")
   198	    # 词面判定天然会被改名绕过（`pwd` / 一个不带口令字样的 str 变量），所以词表按"最可能被
   199	    # 用来命名口令原料的字样"放宽：口令本字族、裸 plain/digest/hash、以及明文的常见变体。
   200	    # (?<![a-z])…(?![a-z]) 这两道边界是防合成词误伤——实测 `hashlib.sha256(...).hexdigest()`
   201	    # 的 unparse 文本里 digest 只以 `hexdigest` 的形态出现，加了边界就不会把非口令站点带进来。
   202	    PASSWORD_WORDS = re.compile(
   203	        r"(?i)password|passwd|secret"
   204	        r"|(?<![a-z])(?:plain|digest|hash)(?![a-z])"
   205	        r"|plain[-_]?(?:text|hash|pw)"
   206	    )
   207	    #: `app/auth.py` 的豁免只在"它还在自己算口令摘要"这段时间里有效：口令哈希收进本模块是
   208	    #: 一个原子动作，删掉那处站点与清空本表必须同轮发生，否则登录面会同时存在两种口令形态。
   209	    #: 不需要谁去记得这件事——那处命中一旦消失，下面的等值钉就把空转的豁免直接判红。
   210	    TRANSITIONAL_EXEMPT = frozenset({"app/auth.py"})
   211	
   212	    #: 同一个口令站点写成 hashlib 的五种绑法。只认 `import hashlib` + `hashlib.<algo>(...)`
   213	    #: 那一种的话，其余四种是"整份文件从扫描面上消失"，连判红都不会有——漏判比误判贵。
   214	    PASSWORD_SITE_SHAPES = (
   215	        "import hashlib\n\n\ndef f(password):\n"
   216	        "    return hashlib.sha256(password.encode('utf-8')).hexdigest()\n",
   217	        "import hashlib as hl\n\n\ndef f(password):\n"
   218	        "    return hl.sha256(password.encode('utf-8')).hexdigest()\n",
   219	        "from hashlib import sha256\n\n\ndef f(password):\n"
   220	        "    return sha256(password.encode('utf-8')).hexdigest()\n",
   221	        "from hashlib import sha256 as s\n\n\ndef f(password):\n"
   222	        "    return s(password.encode('utf-8')).hexdigest()\n",
   223	        "from hashlib import *\n\n\ndef f(password):\n"
   224	        "    return sha256(password.encode('utf-8')).hexdigest()\n",
   225	    )
   226	    #: 反向样本：缓存键一类的非口令摘要，形态与上面逐一对应，一条都不许进命中集。
   227	    NON_PASSWORD_SHAPES = (
   228	        "import hashlib\n\n\ndef f(payload):\n"
   229	        "    return hashlib.sha256(payload.encode('utf-8')).hexdigest()\n",
   230	        "import hashlib as hl\n\n\ndef f(payload):\n"
   231	        "    return hl.sha256(payload.encode('utf-8')).hexdigest()\n",
   232	        "from hashlib import sha256\n\n\ndef f(payload):\n"
   233	        "    return sha256(payload.encode('utf-8')).hexdigest()\n",
   234	        "from hashlib import sha256 as s\n\n\ndef f(payload):\n"
   235	        "    return s(payload.encode('utf-8')).hexdigest()\n",
   236	    )
   237	    _STAR = "*"
   238	
   239	    @classmethod
   240	    def _hashlib_bindings(cls, tree: ast.AST) -> dict[str, str]:
   241	        """本文件里由 hashlib 绑定的名字 -> 它实际指向的算法名（模块本身记作 `hashlib`）。
   242	
   243	        三种绑法都要认：`import hashlib`（含 `import hashlib.blake2b`，它绑的还是 hashlib）、
   244	        `import hashlib as hl`、`from hashlib import sha256 [as s]`。别名要记回原算法名，
   245	        否则 `from hashlib import sha256 as s` 换个名字就把算法名本身从判据里抹掉了。
   246	        """
   247	        bindings: dict[str, str] = {}
   248	        for node in ast.walk(tree):
   249	            if isinstance(node, ast.Import):
   250	                for alias in node.names:
   251	                    if alias.name.split(".")[0] == "hashlib":
   252	                        bindings[alias.asname or "hashlib"] = "hashlib"
   253	            elif isinstance(node, ast.ImportFrom):
   254	                if (node.module or "").split(".")[0] != "hashlib":
   255	                    continue
   256	                for alias in node.names:
   257	                    if alias.name == cls._STAR:
   258	                        # 星号导入绑定了哪些名字静态不知道，只能记下"这文件里有这回事"。
   259	                        bindings[cls._STAR] = cls._STAR
   260	                    else:
   261	                        bindings[alias.asname or alias.name] = alias.name
   262	        return bindings
   263	
   264	    @classmethod
   265	    def _hashlib_password_calls(cls, tree: ast.AST) -> list[tuple[int, str]]:
   266	        """一棵 AST 里"口令参与运算的 hashlib 调用点"，返回 (行号, 调用文本)。"""
   267	        bindings = cls._hashlib_bindings(tree)
   268	        sites: list[tuple[int, str]] = []
   269	        for node in ast.walk(tree):
   270	            if not isinstance(node, ast.Call):
   271	                continue
   272	            func = node.func
   273	            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
   274	                if bindings.get(func.value.id) != "hashlib":
   275	                    continue
   276	                algorithm = func.attr
   277	            elif isinstance(func, ast.Name):
   278	                algorithm = bindings.get(func.id)
   279	                if algorithm is None and cls._STAR in bindings:
   280	                    algorithm = func.id
   281	                if algorithm is None:
   282	                    continue
   283	            else:
   284	                continue
   285	            text = ast.unparse(node)
   286	            if cls.HASHES.search(algorithm) and cls.PASSWORD_WORDS.search(text):
   287	                sites.append((node.lineno, text))
   288	        return sites
   289	
   290	    def _hashlib_password_sites(self) -> list[str]:
   291	        hits: list[str] = []
   292	        for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
   293	            tree = ast.parse(path.read_text(encoding="utf-8"))
   294	            for lineno, text in self._hashlib_password_calls(tree):
   295	                hits.append(f"{path.relative_to(BACKEND_DIR)}:{lineno} {text}")
   296	        return hits
   297	
   298	    def _exemption_table(self) -> frozenset[str]:
   299	        return frozenset({"app/credentials.py"}) | self.TRANSITIONAL_EXEMPT
   300	
   301	    @staticmethod
   302	    def _relative_dir(site: str) -> str:
   303	        return site.split(":")[0].replace("\\", "/")
   304	
   305	    def test_only_credentials_module_hashes_passwords(self):
   306	        exempt = self._exemption_table()
   307	        self.assertEqual(
   308	            [],
   309	            [
   310	                site
   311	                for site in self._hashlib_password_sites()
   312	                if self._relative_dir(site) not in exempt
   313	            ],
   314	        )
   315	
   316	    def test_the_exemption_table_is_equal_to_the_hit_set(self):
   317	        # 上一钉管"表外不许有命中"，这一钉管反向"表里不许有表外用不上的豁免"。
   318	        hits = {self._relative_dir(site) for site in self._hashlib_password_sites()}
   319	        self.assertEqual(set(self._exemption_table()), hits)
   320	
   321	    def test_the_credentials_exemption_is_earned_by_an_actual_hit(self):
   322	        # 豁免表是"这里允许出现口令哈希"的声明，声明必须由真命中兑现。本模块的口令运算是
   323	        # 按词面认出来的（词表见上），所以形参一旦改成不带信号的名字，这处站点会静默消失，
   324	        # 豁免就变成自证；恰等于 1 也防住"复制出一份第二个口令摘要点"。
   325	        sites = [
   326	            site
   327	            for site in self._hashlib_password_sites()
   328	            if self._relative_dir(site) == "app/credentials.py"
   329	        ]
   330	        self.assertEqual(1, len(sites), sites)
   331	
   332	    def test_every_hashlib_binding_shape_reaches_the_same_password_site(self):
   333	        for source in self.PASSWORD_SITE_SHAPES:
   334	            with self.subTest(binding=source.splitlines()[0]):
   335	                self.assertEqual(
   336	                    1, len(self._hashlib_password_calls(ast.parse(source)))
   337	                )
   338	
   339	    def test_a_non_password_digest_stays_out_of_the_hit_set_under_every_binding(self):
   340	        for source in self.NON_PASSWORD_SHAPES:
   341	            with self.subTest(binding=source.splitlines()[0]):
   342	                self.assertEqual([], self._hashlib_password_calls(ast.parse(source)))
   343	
   344	
   345	class _CredentialDbPerTest(unittest.TestCase):
   346	    """每例一份临时库：`CONVERSATION_DB_PATH` 指到 tmp，收尾还原 env。
   347	
   348	    三件事一起办：
   349	    ① 凭据表与会话面**同库**，用例不各占一份文件就会互相撞
   350	    `user_credentials.username` 这条主键（同名账号在这些用例里是常态）。
   351	    ② 出厂默认是**相对**路径 `data/conversations.db` ⇒ 不重定向的用例等于往仓库里
   352	    那份真库写假凭据行。
   353	    ③ **只换 env，不 reload、不碰 `app.config`**：`user_store` 没有 import 期状态
   354	    （路径每次连接时现读 env，schema 只有 `ensure_user_credentials_schema()` 才建），
   355	    所以换 env 就已经换完了库；reload 换来的模块对象反而会让 `mock.patch.object` 之类
   356	    "先拿属性再打桩"的写法打在旧对象上。`settings` 更碰不得——它是进程级单例，
   357	    `app.main` / `app.llm.*` 在 import 期就把那个对象绑进了自己的命名空间，reload 换掉
   358	    的只是 `app.config.settings` 这个模块属性，后面跑的用例改的是再没人读的那一份，
   359	    症状是一份不相干的 FileNotFoundError。
   360	    """
   361	
   362	    def setUp(self):
   363	        self._tmp = tempfile.TemporaryDirectory()
   364	        self._saved_db_path = os.environ.get("CONVERSATION_DB_PATH")
   365	        os.environ["CONVERSATION_DB_PATH"] = str(Path(self._tmp.name) / "creds.db")
   366	        user_store.ensure_user_credentials_schema()
   367	
   368	    def tearDown(self):
   369	        if self._saved_db_path is None:
   370	            os.environ.pop("CONVERSATION_DB_PATH", None)
   371	        else:
   372	            os.environ["CONVERSATION_DB_PATH"] = self._saved_db_path
   373	        self._tmp.cleanup()
   374	
   375	
   376	class UserStoreSchemaTests(_CredentialDbPerTest):
   377	    def test_column_set_may_hold_a_hash_but_never_a_plaintext_field(self):
   378	        """SECA-08：明文字段不是"没人写"，是"不存在可写的地方"。"""
   379	        columns = set(user_store.column_names())
   380	        self.assertIn("password_hash", columns)
   381	        self.assertTrue({"password", "plaintext_password", "raw_password"}.isdisjoint(columns))
   382	        self.assertNotIn(
   383	            "algorithm",
   384	            inspect.signature(user_store.create_argon2).parameters,
   385	        )
   386	        self.assertNotIn(
   387	            "algorithm",
   388	            inspect.signature(user_store.set_password_argon2).parameters,
   389	        )
   390	
   391	    def test_created_rows_are_always_argon2id(self):
   392	        """SECA-01 的持久层半边：普通写路径拿不到 legacy 这个取值。"""
   393	        user_store.create_argon2("admin", plain_password="a-good-password 123", must_change=False)
   394	        record = user_store.get_record("admin")
   395	        self.assertEqual(credentials.ALGORITHM_ARGON2ID, record.algorithm)
   396	        self.assertTrue(record.password_hash.startswith("$argon2id$"))
   397	        self.assertEqual(1, record.credentials_version)
   398	
   399	    def test_only_the_restricted_importer_can_create_a_legacy_row(self):
   400	        self.assertTrue(
   401	            user_store.import_legacy_digest(
   402	                "sales01", hashlib.sha256(b"sales123").hexdigest(), must_change=True
   403	            )
   404	        )
   405	        record = user_store.get_record("sales01")
   406	        self.assertEqual(credentials.ALGORITHM_LEGACY_SHA256, record.algorithm)
   407	        self.assertTrue(record.must_change)
   408	        self.assertEqual(
   409	            {credentials.ALGORITHM_LEGACY_SHA256: 1},
   410	            {k: v for k, v in user_store.count_by_algorithm().items() if v},
   411	        )
   412	
   413	    def test_the_column_list_authority_is_the_table_and_the_insert(self):
   414	        """列序不需要人记：`_COLUMNS` 由表验货，INSERT 由 `_COLUMNS` 生成。
   415	
   416	        三条钉连成一链：往 `_SCHEMA` 加一列而忘了 `_COLUMNS` ⇒ 第一条红；改了
   417	        `_COLUMNS` 而忘了表 ⇒ 同一条红；列名段被人手改歪（收拢前的写法复辟）⇒ 第二条红；
   418	        加了列忘了给 VALUES 补一个占位 ⇒ 第三条红。SQL 文本本身与收拢前两处手写语句逐字
   419	        相同，所以这不是一次语义改动。
   420	        """
   421	        self.assertEqual(tuple(user_store.column_names()), user_store._COLUMNS)
   422	        statement = user_store._insert_sql(ignore_conflicts=False)
   423	        self.assertEqual(
   424	            "INSERT INTO user_credentials (username, algorithm, password_hash,"
   425	            " credentials_version, must_change, failed_attempts, locked_until, updated_at)"
   426	            " VALUES (?, ?, ?, 1, ?, 0, NULL, ?)",
   427	            statement,
   428	        )
   429	        self.assertEqual(
   430	            statement + " ON CONFLICT(username) DO NOTHING",
   431	            user_store._insert_sql(ignore_conflicts=True),
   432	        )
   433	        # 每一列都要有归属：5 个 `?` 之外那 3 列是字面量（1 / 0 / NULL）。
   434	        self.assertEqual(len(user_store._COLUMNS), statement.count("?") + 3)
   435	
   436	
   437	class UserStoreIsolationTests(_CredentialDbPerTest):
   438	    """规格 §6.1 的"同库"半边：一个真源、一条解析路径、读路径不建表。"""
   439	
   440	    def test_the_effective_path_is_the_siblings_own_env_key(self):
   441	        # 默认值与覆盖取值都是 `conversation_store` / `llm.usage` 用的那一枚 env 键。分叉
   442	        # 的代价不是理论：`settings` 会读 `.env`（dotenv），两个兄弟不读——运维把该键在
   443	        # `.env` 里挪成绝对路径时，只有凭据表跟着搬，备份与轮转就跟着错文件走。
   444	        # 走 `RAW_DATABASE_PATH`（import 期那一份）而不是 `user_store.database_path`：后者在
   445	        # 会话里已被护栏包走，env 清空时它给的是改道目标，那样这条钉测的就是护栏而不是口径。
   446	        with mock.patch.dict(os.environ, {}, clear=True):
   447	            self.assertEqual(Path("data/conversations.db"), RAW_DATABASE_PATH())
   448	        with mock.patch.dict(
   449	            os.environ, {"CONVERSATION_DB_PATH": "elsewhere/creds.db"}, clear=True
   450	        ):
   451	            self.assertEqual(Path("elsewhere/creds.db"), RAW_DATABASE_PATH())
   452	
   453	    def test_the_module_never_resolves_the_shared_file_through_settings(self):
   454	        # 上一条管"取值口径"，这一条管"不许有第二个口径"：import `app.config` 就等于给
   455	        # `CONVERSATION_DB_PATH` 长出一个 dotenv 侧的真源（env 与 `.env` 谁赢取决于谁先读）。
   456	        tree = ast.parse(Path(user_store.__file__).read_text(encoding="utf-8"))
   457	        imported: list[str] = []
   458	        for node in ast.walk(tree):
   459	            if isinstance(node, ast.Import):
   460	                imported.extend(alias.name for alias in node.names)
   461	            elif isinstance(node, ast.ImportFrom) and node.module:
   462	                imported.append(node.module)
   463	        self.assertEqual([], [name for name in imported if "config" in name.split(".")[-1]],
   464	                         f"user_store 的 import 面混进了配置模块：{sorted(imported)}")
   465	
   466	    def test_read_paths_never_create_the_schema(self):
   467	        # 读函数顺手建表 = 在任何一次"env 被 clear 掉 ⇒ 路径退回默认值"的调用里往那个
   468	        # 文件提交一次 DDL，落点可能是生产库，而且护栏看不见（它只包 usage）。0 字节就是
   469	        # "一条 DDL 都没提交"的证据。
   470	        with tempfile.TemporaryDirectory() as directory:
   471	            target = Path(directory) / "unseeded.db"
   472	            with mock.patch.object(user_store, "database_path", return_value=target):
   473	                with self.assertRaises(sqlite3.OperationalError):
   474	                    user_store.get_record("admin")
   475	                with self.assertRaises(sqlite3.OperationalError):
   476	                    user_store.list_records()
   477	                # PRAGMA 认不出表只给空结果，不建表也不报错。
   478	                self.assertEqual([], user_store.column_names())
   479	            self.assertEqual(0, target.stat().st_size)
   480	
   481	    def test_a_guard_can_redirect_this_module_through_the_same_seam(self):
   482	        # `tests/conftest.py` 包 `usage` 的手法就是换掉模块级 `database_path`
   483	        # （`LedgerGuard.install`）。本模块必须能被同一个手法包走——那是凭据表在 env 被清掉
   484	        # 时仍不落生产库的唯一兜底，也是本文件不 reload 的前提。
   485	        wrapped = Path(self._tmp.name) / "redirected.db"
   486	        env_db = Path(os.environ["CONVERSATION_DB_PATH"])
   487	
   488	        def rows(path: Path) -> int:
   489	            connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
   490	            try:
   491	                table = connection.execute(
   492	                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
   493	                    (user_store.TABLE_NAME,),
   494	                ).fetchone()
   495	                if table is None:
   496	                    return -1
   497	                count = connection.execute(
   498	                    f"SELECT COUNT(*) FROM {user_store.TABLE_NAME}"
   499	                ).fetchone()[0]
   500	                return int(count)
   501	            finally:
   502	                connection.close()
   503	
   504	        with mock.patch.object(user_store, "database_path", return_value=wrapped):
   505	            user_store.ensure_user_credentials_schema()
   506	            user_store.create_argon2(
   507	                "admin", plain_password="a-good-password 123", must_change=False
   508	            )
   509	        self.assertEqual(1, rows(wrapped))
   510	        self.assertEqual(0, rows(env_db))
   511	
   512	
   513	class UserStoreTransactionTests(_CredentialDbPerTest):
   514	    """SECA-11 / SECA-12：新 hash、bump、清锁必须是一个提交单位。"""
   515	
   516	    def test_password_change_bumps_version_and_clears_lock_state_together(self):
   517	        user_store.create_argon2("admin", plain_password="old-password 123456", must_change=True)
   518	        user_store.record_login_failure(
   519	            "admin", max_attempts=1, lock_seconds=900
   520	        )
   521	        self.assertIsNotNone(user_store.get_record("admin").locked_until)
   522	
   523	        new_version = user_store.set_password_argon2(
   524	            "admin", plain_password="new-password 123456", must_change=False
   525	        )
   526	        record = user_store.get_record("admin")
   527	        self.assertEqual(new_version, record.credentials_version)
   528	        self.assertEqual(2, record.credentials_version)
   529	        self.assertFalse(record.must_change)
   530	        self.assertEqual(0, record.failed_attempts)
   531	        self.assertIsNone(record.locked_until)
   532	
   533	    def test_a_failing_version_bump_rolls_back_the_new_hash(self):
   534	        user_store.create_argon2("admin", plain_password="old-password 123456", must_change=False)
   535	        before = user_store.get_record("admin")
   536	        with mock.patch.object(
   537	            user_store, "_bump_and_clear", side_effect=user_store.CredentialStoreError("boom")
   538	        ):
   539	            with self.assertRaises(user_store.CredentialStoreError):
   540	                user_store.set_password_argon2(
   541	                    "admin", plain_password="new-password 123456", must_change=False
   542	                )
   543	        after = user_store.get_record("admin")
   544	        self.assertEqual(before.password_hash, after.password_hash)
   545	        self.assertEqual(before.credentials_version, after.credentials_version)
   546	
   547	    def test_rehash_is_guarded_by_the_version_it_was_computed_for(self):
   548	        user_store.create_argon2("admin", plain_password="old-password 123456", must_change=True)
   549	        # 版本快照取在**重哈希之前**：下面两条钉子都由它推出来，这样"实现顺手 bump 了版本"
   550	        # 这一类变异体既过不了第二条，也过不了第三条（陈旧版本号恰好命中当前行）。
   551	        version_before = user_store.get_record("admin").credentials_version
   552	        self.assertTrue(
   553	            user_store.apply_rehash(
   554	                "admin",
   555	                plain_password="old-password 123456",
   556	                must_change=True,
   557	                expected_version=version_before,
   558	            )
   559	        )
   560	        record = user_store.get_record("admin")
   561	        self.assertEqual(credentials.ALGORITHM_ARGON2ID, record.algorithm)
   562	        # 渐进重哈希**不 bump 版本**（SECA-01 之外的另一条独立不变量：登录只改强度，
   563	        # 不改会话）——版本一涨，§6.3 的 token 失效判定就把一次正常登录变成了强制重登。
   564	        self.assertEqual(version_before, record.credentials_version)
   565	        # 陈旧版本（并发下别人已经改过密）⇒ 整条 UPDATE 不落地。+1 是从上面那枚**重哈希
   566	        # 前**的快照推出来、从没落进库里的版本号：一旦 rehash 意外 bump 了版本，这条就会
   567	        # 反过来落地并返回 True（旧写法 `record.credentials_version + 5` 在两种实现下都
   568	        # 返回 False，等于没钉）。
   569	        self.assertFalse(
   570	            user_store.apply_rehash(
   571	                "admin",
   572	                plain_password="old-password 123456",
   573	                must_change=False,
   574	                expected_version=version_before + 1,
   575	            )
   576	        )
   577	        after = user_store.get_record("admin")
   578	        self.assertTrue(after.must_change)
   579	        self.assertEqual(version_before, after.credentials_version)
   580	        self.assertEqual(record.password_hash, after.password_hash)
   581	
   582	
   583	class CredentialStoreErrorSurfaceTests(_CredentialDbPerTest):
   584	    """存储层的三条出口：异常消息、异常链、dataclass repr——都不许带驱动文案或口令材料。"""
   585	
   586	    def test_a_duplicate_username_raises_a_store_error_with_the_cause_kept(self):
   587	        user_store.create_argon2("admin", plain_password="a-good-password 123", must_change=False)
   588	        first_hash = user_store.get_record("admin").password_hash
   589	        with self.assertRaises(user_store.CredentialStoreError) as caught:
   590	            user_store.create_argon2(
   591	                "admin", plain_password="another-good-password 456", must_change=False
   592	            )
   593	        message = str(caught.exception)
   594	        # 裸 `sqlite3.IntegrityError` 会把驱动文案原样送进服务端日志与运维控制台；
   595	        # `CredentialStoreError` 才是本模块对外的分类。原文仍在 `__cause__` 上。
   596	        self.assertNotIn("UNIQUE constraint", message)
   597	        self.assertNotIn("user_credentials.username", message)
   598	        self.assertIsInstance(caught.exception.__cause__, sqlite3.IntegrityError)
   599	        self.assertIn("admin", message)
   600	        self.assertNotIn("another-good-password 456", f"{message}{caught.exception.__cause__!r}")
   601	        # 撞键那条 INSERT 回滚，已有行原样不动。
   602	        self.assertEqual(first_hash, user_store.get_record("admin").password_hash)
   603	
   604	    def test_the_missing_account_message_names_nothing_the_response_face_could_leak(self):
   605	        # §9.1 把「有身份无凭据行」折成与口令错同一条 401（`用户名或密码错误` /
   606	        # `invalid_credentials`）。这条异常正是在登录/改密腿上被抓的，消息里带账号名就
   607	        # 等于给响应面或审计 detail 递了一枚"这个用户名存在吗"的探针。
   608	        with self.assertRaises(user_store.CredentialStoreError) as caught:
   609	            user_store.set_password_argon2(
   610	                "nobody-here", plain_password="a-good-password 123", must_change=False
   611	            )
   612	        self.assertEqual(user_store.ACCOUNT_MISSING_MESSAGE, str(caught.exception))
   613	        self.assertNotIn("nobody-here", str(caught.exception))
   614	
   615	    def test_a_record_repr_does_not_carry_the_password_hash(self):
   616	        # 本模块没有 logging，repr 就是密文材料进日志的唯一通道（口径同 `SecretStr`）。
   617	        user_store.create_argon2("admin", plain_password="a-good-password 123", must_change=False)
   618	        record = user_store.get_record("admin")
   619	        self.assertTrue(record.password_hash.startswith("$argon2id$"))
   620	        self.assertNotIn(record.password_hash, repr(record))
   621	        self.assertNotIn("$argon2id$", repr(record))
   622	        # repr=False 只关掉打印面：比较与字段本身都还在（等值钉仍按全部列判）。
   623	        self.assertEqual(record, user_store.get_record("admin"))
   624	
   625	
   626	class MigrationPathTests(_CredentialDbPerTest):
   627	    """规格 §8.2 的升级腿：`data/legacy_credentials.json` → legacy 行。
   628	
   629	    夹具用 `_CredentialDbPerTest`（换 env、不 reload）。简报里的 `importlib.reload` 写法
   630	    已由 Task 2 的台账否掉：换库只需 env，reload 换掉的是进程级 `settings` 单例，代价是
   631	    后面跑的用例改再没人读的那一份。
   632	    """
   633	
   634	    def _artifact(self, payload: dict) -> Path:
   635	        path = Path(self._tmp.name) / "artifact.json"
   636	        path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
   637	        return path
   638	
   639	    def _valid(self, block: dict[str, str]) -> dict:
   640	        """一份形态合法的工件（三枚顶层键都在）：只改 credentials 的用例用它，免得每处重抄。"""
   641	        return {
   642	            "generated_at": "2026-09-25T00:00:00+00:00",
   643	            "source": "app/auth.py@pre-SEC-A",
   644	            "credentials": block,
   645	        }
   646	
   647	    def test_a_fresh_install_without_an_artifact_imports_nothing(self):
   648	        """SECA-04b：全新安装不生产 legacy 行，这是 §8.2 分家的落点。"""
   649	        report = credentials_migration.import_from_artifact(
   650	            Path(self._tmp.name) / "does-not-exist.json"
   651	        )
   652	        self.assertFalse(report.artifact_present)
   653	        self.assertEqual((), report.imported)
   654	        self.assertEqual(0, credentials_migration.status().legacy_count)
   655	
   656	    def test_imported_rows_are_legacy_and_flagged_for_forced_change(self):
   657	        path = self._artifact(
   658	            {
   659	                "generated_at": "2026-09-25T00:00:00+00:00",
   660	                "source": "app/auth.py@pre-SEC-A",
   661	                "credentials": {"admin": "a" * 64},
   662	            }
   663	        )
   664	        report = credentials_migration.import_from_artifact(path)
   665	        self.assertEqual(("admin",), report.imported)
   666	        record = user_store.get_record("admin")
   667	        self.assertEqual(credentials.ALGORITHM_LEGACY_SHA256, record.algorithm)
   668	        self.assertTrue(record.must_change)
   669	        self.assertEqual(1, credentials_migration.status().legacy_count)
   670	
   671	    def test_reimporting_does_not_downgrade_an_already_upgraded_row(self):
   672	        user_store.create_argon2("admin", plain_password="already-migrated 123456", must_change=False)
   673	        path = self._artifact({"generated_at": "x", "source": "y", "credentials": {"admin": "a" * 64}})
   674	        # 数一下写手被叫了几次：今天"不降级"是 `INSERT ... DO NOTHING` 兜住的，所以只钉结果
   675	        # 的话，"根本不试"与"试一次靠 SQL 吞掉"两种实现同形。`import_legacy_digest` 哪天改成
   676	        # UPSERT（改密/reset 那条腿迟早有人想复用），前者仍然安全、后者当场把 argon2id 行写回
   677	        # legacy——那枚 `call_count == 0` 就是留给那一天的门。
   678	        with mock.patch.object(
   679	            user_store, "import_legacy_digest", wraps=user_store.import_legacy_digest
   680	        ) as writer:
   681	            report = credentials_migration.import_from_artifact(path)
   682	        self.assertEqual((), report.imported)
   683	        self.assertEqual(("admin",), report.skipped)
   684	        self.assertEqual(credentials.ALGORITHM_ARGON2ID, user_store.get_record("admin").algorithm)
   685	        self.assertEqual(0, writer.call_count, "已存在行被跳过的意思是**不去写它**")
   686	
   687	    def test_a_malformed_artifact_is_rejected_as_a_whole(self):
   688	        for payload in (
   689	            {"generated_at": "x", "source": "y", "credentials": {"admin": "not-hex"}},
   690	            {"generated_at": "x", "source": "y", "credentials": ["admin"]},
   691	            {"generated_at": "x", "source": "y", "credentials": {}, "oops": 1},
   692	        ):
   693	            with self.subTest(keys=sorted(payload)):
   694	                with self.assertRaises(credentials_migration.MigrationArtifactError):
   695	                    credentials_migration.import_from_artifact(self._artifact(payload))
   696	        self.assertEqual(0, credentials_migration.status().legacy_count)
   697	
   698	    def test_only_the_migration_module_may_call_the_legacy_writer(self):
   699	        """SEC-A-004：受限路径必须真的受限——按调用方扫描，不按函数名信任。"""
   700	        callers: set[str] = set()
   701	        for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
   702	            tree = ast.parse(path.read_text(encoding="utf-8"))
   703	            for node in ast.walk(tree):
   704	                if (
   705	                    isinstance(node, ast.Call)
   706	                    and isinstance(node.func, ast.Attribute)
   707	                    and node.func.attr == "import_legacy_digest"
   708	                ):
   709	                    callers.add(path.name)
   710	        self.assertEqual({"credentials_migration.py"}, callers)
   711	
   712	    def test_an_unreadable_shape_is_rejected_before_any_row_is_written(self):
   713	        """脏 digest 的正确症状是**导入即拒**，不是那个人的第一次登录。
   714	
   715	        `import_legacy_digest` 刻意不校验 64-hex（形态校验归迁移器），所以少一道前置校验
   716	        的后果是把 `"not-hex"` 一路写进表里：`verify_password` 到那时抛的
   717	        `CredentialConfigError` 会落在登录面上，而登录面的分类只有"口令错 / 503 / 存储事故"
   718	        三种——一条永远不会成功的凭据行就这么被读成"用户记错了口令"。
   719	        """
   720	        path = self._artifact(self._valid({"admin": "a" * 63, "sales01": "zz" * 32}))
   721	        with self.assertRaises(credentials_migration.MigrationArtifactError):
   722	            credentials_migration.import_from_artifact(path)
   723	        self.assertEqual({}, user_store.count_by_algorithm())
   724	        self.assertIsNone(user_store.get_record("admin"))
   725	        # 大写形态：`import_legacy_digest` 自己会 lower()，但表里存的必须是它能验的形态。
   726	        upper = self._artifact(self._valid({"hr01": "A" * 64}))
   727	        self.assertEqual({"hr01": "a" * 64}, credentials_migration.read_artifact(upper))
   728	
   729	    def test_provenance_fields_are_required(self):
   730	        """`source`/`generated_at` 是"升级工件"与"随手放的凭据文件"之间唯一的机器可辨差别。
   731	
   732	        §8.2 把这条区分写成整节的立论根据（closure 删的是工件，不是凭据真源），所以它不能
   733	        只靠文档：一份没有出处的 digest 集一律拒读，宁可让运维重跑一次导出。
   734	        """
   735	        for payload in (
   736	            {"credentials": {"admin": "a" * 64}},
   737	            {"generated_at": "  ", "source": "app/auth.py@pre-SEC-A",
   738	             "credentials": {"admin": "a" * 64}},
   739	            {"generated_at": "2026-09-25T00:00:00+00:00",
   740	             "credentials": {"admin": "a" * 64}},
   741	        ):
   742	            with self.subTest(keys=sorted(payload)):
   743	                with self.assertRaises(credentials_migration.MigrationArtifactError):
   744	                    credentials_migration.import_from_artifact(self._artifact(payload))
   745	        self.assertEqual(0, credentials_migration.status().legacy_count)
   746	
   747	    def test_an_empty_artifact_is_not_reported_as_a_missing_one(self):
   748	        """空 credentials ⇒ 报错，不是"当成没有工件"。
   749	
   750	        后者会把"升级只导了 0 个人"读成"这是全新安装"，两种状态在 `MigrationReport` 上必须
   751	        可分：`artifact_present` 说的是**文件在不在场**，导入条数说的是另一件事。
   752	        """
   753	        path = self._artifact(self._valid({}))
   754	        with self.assertRaises(credentials_migration.MigrationArtifactError):
   755	            credentials_migration.import_from_artifact(path)
   756	
   757	    def test_a_writers_declination_is_never_reported_as_an_import(self):
   758	        """`import_legacy_digest` 返回 False = 那行没落地 ⇒ 不许进 `imported`。
   759	
   760	        写手用的是 `ON CONFLICT(username) DO NOTHING`：`only_missing=False` 时它会对已存在
   761	        的行回 False。把它记成"导入成功"就是报告说导了 5 个人、库里其实只有 3 个——而
   762	        `legacy_count` 正是 SECA-04 判闭合的那个数字，台账错一位比少导一人更难查。
   763	        """
   764	        user_store.create_argon2("admin", plain_password="already-migrated 123456",
   765	                                 must_change=False)
   766	        path = self._artifact(self._valid({"admin": "a" * 64, "sales01": "b" * 64}))
   767	        report = credentials_migration.import_from_artifact(path, only_missing=False)
   768	        self.assertEqual(("sales01",), report.imported)
   769	        self.assertEqual(("admin",), report.skipped)
   770	        self.assertTrue(report.reason)
   771	        self.assertTrue(report.artifact_present)
   772	        self.assertEqual(credentials.ALGORITHM_ARGON2ID, user_store.get_record("admin").algorithm)
   773	        self.assertEqual(credentials.ALGORITHM_LEGACY_SHA256,
   774	                         user_store.get_record("sales01").algorithm)
   775	
   776	    def test_a_store_incident_stays_a_store_incident(self):
   777	        """写失败是存储事故：不许被翻成"口令错了"，也不许咽成一次跳过。"""
   778	        path = self._artifact(self._valid({"admin": "a" * 64, "sales01": "b" * 64}))
   779	        with mock.patch.object(
   780	            user_store,
   781	            "import_legacy_digest",
   782	            side_effect=user_store.CredentialStoreError("disk full"),
   783	        ):
   784	            with self.assertRaises(user_store.CredentialStoreError) as caught:
   785	                credentials_migration.import_from_artifact(path)
   786	        # 分类没被改写：它既不是"工件形态错"，也不是认证结论。
   787	        self.assertNotIsInstance(caught.exception, credentials_migration.MigrationArtifactError)
   788	        self.assertNotIsInstance(caught.exception, credentials.CredentialConfigError)
   789	        # 报错面不带口令材料（digest 也算：它进了异常消息就等于进了服务端日志）。
   790	        self.assertNotIn("a" * 64, str(caught.exception))
   791	        self.assertEqual(0, credentials_migration.status().legacy_count)
   792	
   793	    def test_a_blank_username_is_rejected_with_the_rest_of_the_artifact(self):
   794	        """主键为空/纯空白的行能写进表里，但永远查不出来——它该在导入这一步就被拒。"""
   795	        for payload in (
   796	            self._valid({"": "a" * 64}),
   797	            self._valid({"   ": "a" * 64}),
   798	        ):
   799	            with self.subTest(usernames=sorted(payload["credentials"])):
   800	                with self.assertRaises(credentials_migration.MigrationArtifactError):
   801	                    credentials_migration.import_from_artifact(self._artifact(payload))
   802	        self.assertEqual(0, credentials_migration.status().legacy_count)
   803	
   804	    def test_neither_the_report_nor_a_rejection_echoes_a_digest(self):
   805	        """报告与异常消息都是会被打印/审计的面：那里只许出现用户名。"""
   806	        digest = "abcdef0123456789" * 4
   807	        report = credentials_migration.import_from_artifact(
   808	            self._artifact(self._valid({"admin": digest}))
   809	        )
   810	        self.assertNotIn(digest, repr(report))
   811	        bad = digest[:-1] + "z"
   812	        with self.assertRaises(credentials_migration.MigrationArtifactError) as caught:
   813	            credentials_migration.import_from_artifact(
   814	                self._artifact(self._valid({"admin": bad}))
   815	            )
   816	        self.assertNotIn(bad, str(caught.exception))
   817	        self.assertIn("admin", str(caught.exception))
   818	
   819	    def test_status_separates_the_two_algorithm_families(self):
   820	        """`migration-status` 是 SECA-04 的硬门读数：两族分开数，且逐行可点名。"""
   821	        user_store.create_argon2("admin", plain_password="already-migrated 123456",
   822	                                 must_change=False)
   823	        credentials_migration.import_from_artifact(
   824	            self._artifact(self._valid({"sales01": "b" * 64, "viewer": "c" * 64}))
   825	        )
   826	        status = credentials_migration.status()
   827	        self.assertEqual(2, status.legacy_count)
   828	        self.assertEqual(1, status.argon2id_count)
   829	        self.assertEqual(("admin", "sales01", "viewer"), tuple(a.username for a in status.accounts))
   830	        self.assertEqual(
   831	            {"admin": credentials.ALGORITHM_ARGON2ID,
   832	             "sales01": credentials.ALGORITHM_LEGACY_SHA256,
   833	             "viewer": credentials.ALGORITHM_LEGACY_SHA256},
   834	            {a.username: a.algorithm for a in status.accounts},
   835	        )
   836	        self.assertEqual((1, 1, 1), tuple(a.credentials_version for a in status.accounts))
   837	        self.assertEqual((False, True, True), tuple(a.must_change for a in status.accounts))
   838	        self.assertEqual((None, None, None), tuple(a.locked_until for a in status.accounts))
   839	        for row in status.accounts:
   840	            self.assertIsInstance(row.updated_at, str)
   841	            self.assertTrue(row.updated_at)
   842	        # 状态面也不许带出口令材料：`AccountStatus` 里压根没有 `password_hash` 这一格
   843	        # （口径同 `UserStoreSchemaTests`：不是"没人写"，是"没有可写的地方"）。
   844	        self.assertNotIn(
   845	            "password_hash", {field.name for field in dataclasses.fields(status.accounts[0])}
   846	        )
   847	
   848	
   849	class _GuardProbe(unittest.TestCase):
   850	    """自建一份「假真库」+ 一个只盯它的护栏实例，用来驱动**真的** `user_store` 函数。
   851	
   852	    与会话级护栏同手法（`test_model_router_v23_contract.py::LedgerGuardClassificationTests`
   853	    就是这个形状），刻意不在真库上演练：本类的每一笔"写"都记在自己那个 `LedgerGuard` 实例
   854	    的 list 上，所以既不会污染会话统计，也不会被会话归责钩子读成事故——归责钩子读的仍是
   855	    `credential_write_redirects()` 那条真通道，由 `CredentialGuardWiringTests` 点数。
   856	    """
   857	
   858	    def setUp(self) -> None:
   859	        directory = tempfile.TemporaryDirectory()
   860	        self.addCleanup(directory.cleanup)
   861	        root = Path(directory.name)
   862	        self.protected_dir = root / "data"                      # 模拟「保护集里的真库」目录
   863	        self.protected_dir.mkdir()
   864	        self.protected_db = self.protected_dir / "conversations.db"
   865	        self.isolated_dir = root / "isolated"
   866	        self.isolated_dir.mkdir()
   867	        self.artifact_dir = root
   868	
   869	    def seed_offline(self, target: Path) -> None:
   870	        """在护栏**不在场**时把表建到目标库里：建表本身是一笔 write，不能混进被驱动的样本。"""
   871	        with mock.patch.object(user_store, "database_path", return_value=target):
   872	            user_store.ensure_user_credentials_schema()
   873	
   874	    def install_guard(self, target: Path) -> "ledger_guard.LedgerGuard":
   875	        """自建一份与**会话那份同配置**的护栏：同一个 label/subject/`warn_on_read`。
   876	
   877	        配置要照抄，否则本类演练的是另一个形状的护栏。抄得齐不齐由会话那枚哨兵管
   878	        （`CredentialGuardWiringTests` 盯的是真接线的存在性与改道目标）。
   879	        """
   880	        guard = ledger_guard.LedgerGuard(
   881	            original_path=lambda: self.protected_db,
   882	            target=target,
   883	            protected_dirs=(self.protected_dir,),
   884	            label="[credential-guard]",
   885	            subject="真实凭据表",
   886	            warn_on_read=False,
   887	        )
   888	        guard.install_credential_store(user_store)
   889	        self.addCleanup(guard.uninstall)
   890	        return guard
   891	
   892	    def table_rows(self, path: Path) -> int:
   893	        """目标库里 `user_credentials` 的行数（表不在场时 -1）。"""
   894	        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
   895	        try:
   896	            found = connection.execute(
   897	                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
   898	                (user_store.TABLE_NAME,),
   899	            ).fetchone()
   900	            if found is None:
   901	                return -1
   902	            return int(connection.execute(
   903	                f"SELECT COUNT(*) FROM {user_store.TABLE_NAME}").fetchone()[0])
   904	        finally:
   905	            connection.close()
   906	
   907	
   908	class CredentialStoreGuardTests(_GuardProbe):
   909	    """护栏对凭据面的三道事实：改道、读写归类、以及"改道是真改道"。
   910	
   911	    两枚方向相反的钉子（缺一道就是漏判）：纯读必须**留**在 read（把读也判红是 N1 的病灶），
   912	    真写必须**升**到 write（判成 read 就是这张表上没有任何人在看）。归类不靠函数名清单：
   913	    写证据取自 sqlite 自己回传的语句，所以以后新加一条写腿不需要谁记得回到 conftest 加名字。
   914	    """
   915	
   916	    def test_a_pure_read_stays_read_and_lands_nothing_on_the_protected_path(self):
   917	        target = self.isolated_dir / "conversations.db"
   918	        self.seed_offline(target)
   919	        guard = self.install_guard(target)
   920	        self.assertIsNone(user_store.get_record("admin"))
   921	        self.assertEqual(list(user_store._COLUMNS), user_store.column_names())
   922	        self.assertEqual({}, user_store.count_by_algorithm())
   923	        kinds = [kind for _src, _dst, kind in guard.records]
   924	        self.assertEqual([ledger_guard.REDIRECT_READ] * 3, kinds,
   925	                         "读被记成写 ⇒ 每条正常读用例都会被会话钩子判红（N1 的病灶）")
   926	        self.assertEqual((), guard.violations())
   927	        self.assertFalse(self.protected_db.exists(),
   928	                         "读路径在保护集下留下了一份 0 字节库：mkdir + connect 的落点没被改道")
   929	
   930	    def test_a_credential_write_is_classified_write_and_lands_in_the_target(self):
   931	        target = self.isolated_dir / "conversations.db"
   932	        self.seed_offline(target)
   933	        guard = self.install_guard(target)
   934	        user_store.create_argon2("admin", plain_password="a-good-password 123",
   935	                                 must_change=False)
   936	        self.assertEqual([(str(self.protected_db), str(target), ledger_guard.REDIRECT_WRITE)],
   937	                         list(guard.records),
   938	                         "写没被记成 write ⇒ 这张表上没人盯（会话钩子的输入就是这一笔）")
   939	        self.assertEqual(1, len(guard.violations()))
   940	        self.assertEqual(1, self.table_rows(target), "改道是真改道：行要落在目标库")
   941	        self.assertFalse(self.protected_db.exists(), "真写路径碰到了保护集下的文件")
   942	
   943	    def test_a_schema_creation_on_the_redirected_path_is_a_write_too(self):
   944	        """`ensure_user_credentials_schema()` 走的是一条 DDL，不是 DML：它也必须是 write。
   945	
   946	        这条钉子管的是 Task 2 留的那个形状——读路径**不**建表，建表只有一次真 DDL 提交；
   947	        如果归类只认 INSERT/UPDATE/DELETE，那"谁在启动期往真库建了半张表"就正好看不见。
   948	        """
   949	        target = self.isolated_dir / "fresh.db"
   950	        guard = self.install_guard(target)
   951	        user_store.ensure_user_credentials_schema()
   952	        self.assertEqual([ledger_guard.REDIRECT_WRITE],
   953	                         [kind for _src, _dst, kind in guard.records],
   954	                         "建表（executescript 的 CREATE TABLE）没被记成写")
   955	        self.assertEqual(list(user_store._COLUMNS), user_store.column_names())
   956	        self.assertEqual(
   957	            [ledger_guard.REDIRECT_WRITE, ledger_guard.REDIRECT_READ],
   958	            [kind for _src, _dst, kind in guard.records],
   959	        )
   960	        self.assertFalse(self.protected_db.exists())
   961	
   962	    def test_the_write_mark_is_per_connection_not_a_latch(self):
   963	        """读→写→读 ⇒ 归类必须是 read / write / read，且**一条连接只升一次**。
   964	
   965	        写证据挂在**这一条连接**上。做成"第一次写之后整条会话都算写"的实现（latch）会让后面
   966	        每一条只读用例被判红，做成"第一次写之后不再记"的实现会把第二笔事故读成静默——两个方向
   967	        在这里各有一枚断言。最后那步 `record_login_failure` 是故意的：`max_attempts=1` 让它
   968	        在**同一条连接**里跑两条 UPDATE（涨计数 + 落 lock），是唯一能暴露"每条写语句各升一次
   969	        ⇒ 一笔事故记成两笔"的形状。
   970	        """
   971	        target = self.isolated_dir / "conversations.db"
   972	        self.seed_offline(target)
   973	        guard = self.install_guard(target)
   974	        user_store.list_records()
   975	        user_store.create_argon2("admin", plain_password="a-good-password 123",
   976	                                 must_change=False)
   977	        user_store.list_records()
   978	        self.assertEqual(
   979	            [ledger_guard.REDIRECT_READ, ledger_guard.REDIRECT_WRITE,
   980	             ledger_guard.REDIRECT_READ],
   981	            [kind for _src, _dst, kind in guard.records],
   982	        )
   983	        self.assertEqual(1, len(guard.violations()))
   984	        user_store.record_login_failure("admin", max_attempts=1, lock_seconds=900)
   985	        self.assertEqual(
   986	            [ledger_guard.REDIRECT_READ, ledger_guard.REDIRECT_WRITE,
   987	             ledger_guard.REDIRECT_READ, ledger_guard.REDIRECT_WRITE],
   988	            [kind for _src, _dst, kind in guard.records],
   989	            "多条写语句的同一条连接被记成了多笔事故 ⇒ 判红信息里的条数不再等于碰真库的连接数",
   990	        )
   991	        self.assertEqual(2, len(guard.violations()))
   992	        # 前提本身也要成立：第二条 UPDATE 真的跑过（`max_attempts=1` 没生效的话，上面那步
   993	        # 退化成"一条连接一次写"，这一枚钉子就空转了）。读放在所有 records 断言之后：它自己
   994	        # 也是一笔改道，只是归类是 read。
   995	        self.assertIsNotNone(user_store.get_record("admin").locked_until)
   996	
   997	    def test_the_restricted_legacy_writer_goes_through_the_same_seam(self):
   998	        """Task 3 是这张表的第一个真实消费者：迁移器写下的那一行同样要落在改道后的库里。
   999	
  1000	        这一条把两件事接上：`import_from_artifact` 的读（`get_record`）留在 read，它的写
  1001	        （`import_legacy_digest`）升到 write。少了后一半，"受限路径"就成了护栏的盲区——而
  1002	        它恰好是唯一能造出 legacy 行的那条路径。
  1003	        """
  1004	        target = self.isolated_dir / "conversations.db"
  1005	        self.seed_offline(target)
  1006	        artifact = self.artifact_dir / "artifact.json"
  1007	        artifact.write_text(
  1008	            json.dumps(
  1009	                {
  1010	                    "generated_at": "2026-09-25T00:00:00+00:00",
  1011	                    "source": "app/auth.py@pre-SEC-A",
  1012	                    "credentials": {"admin": "a" * 64},
  1013	                }
  1014	            ),
  1015	            encoding="utf-8",
  1016	            newline="\n",
  1017	        )
  1018	        guard = self.install_guard(target)
  1019	        report = credentials_migration.import_from_artifact(artifact)
  1020	        self.assertEqual(("admin",), report.imported)
  1021	        self.assertEqual(
  1022	            [ledger_guard.REDIRECT_READ, ledger_guard.REDIRECT_WRITE],
  1023	            [kind for _src, _dst, kind in guard.records],
  1024	        )
  1025	        self.assertEqual(1, self.table_rows(target))
  1026	        self.assertFalse(self.protected_db.exists())
  1027	
  1028	
  1029	class CredentialGuardWiringTests(unittest.TestCase):
  1030	    """接线本身要有钉子：`install()` 只包 `usage` 的那一行改掉之后，谁保证 `user_store` 也被包。"""
  1031	
  1032	    def test_the_session_guard_watches_the_credential_table_too(self):
  1033	        self.assertTrue(ledger_guard.guard_is_active(),
  1034	                        "会话护栏没跑起来 ⇒ 本类的三枚钉全是空的")
  1035	        self.assertTrue(ledger_guard.credential_guard_is_active(),
  1036	                        "`user_store` 的 seams 没挂在会话护栏上 ⇒ 凭据写无人盯")
  1037	
  1038	    def test_the_credential_table_resolves_to_the_same_file_as_the_ledger(self):
  1039	        """规格 §6.1 的"同库"由同一个改道目标兑现：两张表解析到同一个文件。
  1040	
  1041	        env 被清空时 `database_path()` 会退回相对默认值，那正是护栏存在的理由；这里同时钉
  1042	        "退回来的路径不在保护集底下"（改道生效）与"两张表落在同一份文件"（真源只有一个）。
  1043	        """
  1044	        with mock.patch.dict(os.environ, {}, clear=True):
  1045	            credential_path = ledger_guard.effective_credential_path()
  1046	            self.assertFalse(ledger_guard.path_is_protected(credential_path),
  1047	                             f"env 清空后凭据表仍指向保护集：{credential_path}")
  1048	            self.assertEqual(ledger_guard.effective_ledger_path().resolve(),
  1049	                             credential_path.resolve())
  1050	
  1051	    def test_a_credential_connect_under_a_cleared_env_cannot_touch_the_real_databases(self):
  1052	        """Task 2 移交的残余：`_connect()` 会 mkdir + 打开文件，落点在 env 被清掉时是生产库。
  1053	
  1054	        快照取的是「在不在场 + 表清单」而不是字节数/时间戳：本仓库的 dev 后端可能正往同一份
  1055	        库里写会话行，拿 mtime 判据会把那种正常写读成事故。凭据面的义务只有两条——不许凭空多出
  1056	        一份 0 字节库，也不许多出 `user_credentials` 这半张表。
  1057	        """
  1058	        def snapshot() -> dict[str, tuple[bool, tuple[str, ...] | None]]:
  1059	            return {
  1060	                str(path): (path.is_file(), ledger_guard.real_db_tables(path))
  1061	                for path in ledger_guard.REAL_DB_PATHS
  1062	            }
  1063	
  1064	        before = snapshot()
  1065	        with mock.patch.dict(os.environ, {}, clear=True):
  1066	            columns = user_store.column_names()
  1067	        self.assertIn(columns, ([], list(user_store._COLUMNS)),
  1068	                      "读到的既不是改道库的『无表』也不是完整表结构 ⇒ 读的是别的文件")
  1069	        self.assertEqual(before, snapshot(),
  1070	                         "一次改道读让真库多出了文件或表 ⇒ 落点没被护栏接走")
  1071	
  1072	    def test_no_test_in_this_session_wrote_a_credential_row_into_a_real_database(self):
  1073	        """会话级哨兵（与账本那枚同形）：本会话零凭据**写**改道，且真库里数不出行。"""
  1074	        self.assertEqual([], list(ledger_guard.credential_write_redirects()),
  1075	                         "有用例的凭据写落到了保护集下的真实库 ⇒ 见 conftest 的凭据面说明")
  1076	        counts = ledger_guard.real_user_credential_row_counts()
  1077	        self.assertIn(str(ledger_guard.REAL_DB_PATH), counts, "哨兵没数 `backend/data` 那份真库")
  1078	        for path, rows in counts.items():
  1079	            self.assertIn(rows, (0, None),
  1080	                          f"真实库里被测试写出了 {rows} 行凭据（SECA-04 的台账会被它污染）："
  1081	                          f"{path}")

## E. line-ending + size facts
backend/app/credentials_migration.py LF 193 lines
backend/tests/conftest.py LF 689 lines
backend/tests/test_credentials_contract.py LF 1081 lines
backend/app/user_store.py LF 345 lines
backend/app/credentials.py LF 131 lines

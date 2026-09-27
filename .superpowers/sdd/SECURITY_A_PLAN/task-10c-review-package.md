# Task 10c review package (snapshot diff, no commits)
Base = snap-task10c-pre-* (state before the implementer started). Head = current worktree.
Brief: .superpowers/sdd/SECURITY_A_PLAN/task-10c-brief.md ; Report: task-10c-report.md

## backend\app\cli.py
sha1 base daf6b1380e3cc34f44d371906e4fe2ae389aac8f  sha1 head 69073df9aca56fc43e1575d3f38961eb14311c54
  base: bytes=8217 CRLF=0 loneLF=172
  head: bytes=12960 CRLF=0 loneLF=239
--- base/cli.py
+++ head/cli.py
@@ -1,59 +1,81 @@
-"""凭据运维面（规格 §8.6 / §8.7）。口令只从环境变量读，绝不进 argv。
+"""凭据运维面（规格 §8.6 / §8.7 / §11）。口令只从环境变量读，绝不进 argv。
 
 argv 是**可观察**的：`ps`、shell history、CI 的日志抓取都会把口令抄走，所以这里没有
 `--password` 这一项，也不接受任何位置参数形式的口令。判据在契约用例里是按 argparse 的
 **行为**钉的（未定义选项 ⇒ `SystemExit`），不是翻 `--help` 文本——文本会随措辞漂移。
 
 `must_change` 由动作决定，而不是由写路径决定：`bootstrap-admin` 造的是"这个账号从此能登录"
 （门关上），`reset` 造的是"这口令不是你选的"（门开着）。两个动作走的是 `auth.provision_credentials`
 同一条写路径，因此清锁与版本 bump 不可能只在其中一支发生（SECA-12 / §7.5）。
 
 本模块**不**创建、**不**修改、也**不**启用或停用任何身份：身份的唯一真源是配置文件
 （SEC-A-010），CLI 顺手建号会造出第二个真源，而"停用一个账号"这件事在这里根本没有对应动作。
+
+`credentials migrate` 是这条运维面上唯一的**读入**动作（规格 §11 / §20.5）：升级工件
+`data/legacy_credentials.json` 只有被运维点名执行时才会被消费，启动路径绝不自动导入。理由不是
+"自动不方便"，而是自动导入会把 §8.5 那半句「生产代码不再自动导入 legacy」吃掉——M19 那发变异
+（缺行就顺手导）与全新安装的 `legacy_count=0` 判据都靠这半句活着。显式动作换来三样东西：退出码、
+可归档的逐字段输出、一个明确的 actor。它**不读任何明文口令**（写的就是工件里已有的摘要），
+所以 `CREDENTIALS_PASSWORD` 这一格规则与它无关。
 """
 
 from __future__ import annotations
 
 import argparse
 import os
 import sys
 
 from app import auth, credentials, credentials_migration, directory, user_store
 from app.audit import recent_events, record_event
+from app.config import settings
 from app.user_store import CredentialStoreError
 
 #: 口令的唯一来路。名字是运维接口的一部分（部署文档与 `.env` 模板都写它）。
 PASSWORD_ENV_VAR = "CREDENTIALS_PASSWORD"
 
 #: 动作 → 落库后的 `must_change`。缺这一格的动作在下面就被 argparse 拒了。
 _MUST_CHANGE_BY_ACTION = {"bootstrap-admin": False, "reset": True}
 
 _COPY_NO_ENV_PASSWORD = (
     f"{PASSWORD_ENV_VAR} 未设置或不足 12 字符：口令只能放在这个环境变量里，"
     "不接受任何命令行参数形式"
 )
 
+#: 企业形态那一格的拒绝文案。点名动作与"一行未写"是同一句话的两半：运维看完要知道文件该
+#: 留在原地（不是"导了 0 个人"），也要知道下一步是拨开关而不是重跑。文案里没有 digest。
+_COPY_ENTERPRISE_REFUSES_MIGRATION = (
+    "企业形态（SECURITY_ENTERPRISE_MODE=true）不导入任何 legacy："
+    "`credentials migrate` 已拒绝，未写入任何一行。升级工件留在原地，"
+    "把开关拨回 false 再执行这一步"
+)
+
 
 def build_parser() -> argparse.ArgumentParser:
     parser = argparse.ArgumentParser(
         prog="python -m app.cli", description="凭据运维面（口令只从环境变量读）"
     )
     commands = parser.add_subparsers(dest="command", required=True)
     actions = commands.add_parser("credentials").add_subparsers(
         dest="action", required=True
     )
     bootstrap = actions.add_parser(
         "bootstrap-admin", help="为**已存在的**身份写入 argon2id 凭据"
     )
     bootstrap.add_argument("--username", required=True)
     reset = actions.add_parser("reset", help="重置口令并强制下次登录改密")
     reset.add_argument("--username", required=True)
     actions.add_parser("migration-status", help="打印各算法行数与逐账号状态")
+    # 没有 `--path`、没有 `--password`、没有 `--force`：`migrate` 的输入位置由 §8.2 钉死在
+    # `credentials_migration.LEGACY_INPUT_PATH`，"导多少次"由 `only_missing` 决定（幂等），
+    # 每多一枚开关就是多一条能把已收敛账号写回 legacy 的路。
+    actions.add_parser(
+        "migrate", help="导入升级工件 data/legacy_credentials.json（运维显式，启动不自动做）"
+    )
     return parser
 
 
 def _password_from_env() -> str | None:
     """读出口令；缺失或不足下界时返回 None，由调用方给出**同一句**提示。
 
     两条输入形状（没设 / 太短）必须汇成一句可执行的话：分成两句就会有一句在讲"你给的
     值太短"——那等于把值本身的存在性说出去了。这里任何分支都不打印取值。
@@ -93,18 +115,62 @@
             f"{row.username}\t{row.algorithm}\tv{row.credentials_version}"
             f"\tmust_change={int(row.must_change)}\tlocked={row.locked_until or '-'}"
             f"\tlast_login={last_login.get(row.username) or '-'}"
             f"\tupdated_at={row.updated_at or '-'}"
         )
     return 0
 
 
+def _migrate_legacy_artifact() -> int:
+    """legacy 导入的唯一生产入口（§11 规则四条各自落在这里）。
+
+    - **企业形态先拒**，连一次 DDL 都不发：§8.5 企业列写的就是「不导入任何 legacy」，"开关一拨、
+      文件还在"不能变成绕过 fail-closed 的通道。
+    - **工件不在场 ⇒ rc 0 且 `artifact_present=False`**：那是全新安装的合法稳态，不是失败。把一次
+      正常收工判成事故，运维下一步就是去找 `--skip-missing` 之类的开关，而那类开关才是真危险。
+    - **`import_from_artifact()` 用它的默认 `only_missing=True`**：已存在的行连试都不试。改成覆写的
+      那一刻，重跑导入就会把已收敛的 argon2id 行降回 legacy，`legacy_count` 永远闭不上——那正是
+      SEC-A-004 判红的那个形状。
+    - **不接触口令**：本函数里没有一行读 `PASSWORD_ENV_VAR` 的代码，`_password_from_env` 那条路
+      与它无关（§11 规则 4）。
+
+    退出码沿用本模块既有分类：0 成功（含"没有工件"）、1 存储事故、2 运维形态/权限类拒绝。
+    异常消息原样转 stderr，不再包一层：`user_store` 与 `credentials_migration` 的消息本身就只
+    带用户名与路径、不带任何 digest（口径同两条写腿的 `print(str(exc))`）。
+    """
+    if settings.security_enterprise_mode:
+        print(_COPY_ENTERPRISE_REFUSES_MIGRATION, file=sys.stderr)
+        return 2
+    user_store.ensure_user_credentials_schema()
+    try:
+        report = credentials_migration.import_from_artifact()
+    except CredentialStoreError as exc:
+        print(str(exc), file=sys.stderr)
+        return 1
+    except credentials_migration.MigrationArtifactError as exc:
+        # 整份拒是运维一次能修完的失败（导出那一步的事），不是存储事故：给 2，与"身份不存在"
+        # "口令不合格"同一类。库里一行都没有——`read_artifact` 在任何写之前就把整份判掉了。
+        print(str(exc), file=sys.stderr)
+        return 2
+    # 逐字段打印（`-` = 该格无值，口径同 `_print_status`）：四个字段各自一行，跑一次留一份台账。
+    print(f"artifact_present={report.artifact_present}")
+    print(f"imported={len(report.imported)} {','.join(report.imported) or '-'}")
+    print(f"skipped={len(report.skipped)} {','.join(report.skipped) or '-'}")
+    print(f"reason={report.reason or '-'}")
+    return 0
+
+
 def main(argv: list[str] | None = None) -> int:
     args = build_parser().parse_args(argv)
+    if args.action == "migrate":
+        # 分派放在建表**之前**：企业形态那一格要求"一行不写"，而 `ensure_user_credentials_schema()`
+        # 自己也是一次写（DDL + 把库文件建出来）。下面那条注释讲的"各动作都要过这一道"对
+        # `migrate` 依然成立，只是改由 `_migrate_legacy_artifact()` 在拒绝判定之后自己过。
+        return _migrate_legacy_artifact()
     # 建表是 `credentials_migration` 的调用方前置条件（它的读路径不建表），放在这里
     # 而不是各动作内部：`migration-status` 与两条写腿都要过这一道。
     user_store.ensure_user_credentials_schema()
     if args.action == "migration-status":
         return _print_status()
 
     identity = directory.get_identity(args.username)
     if identity is None:
@@ -125,17 +191,18 @@
             action="PASSWORD",
             status="DENIED",
             detail=auth.AUDIT_PASSWORD_POLICY_REJECTED,
         )
         print(reason, file=sys.stderr)
         return 2
 
     if args.action not in _MUST_CHANGE_BY_ACTION:
-        # 走到这里只可能是 parser 添了第四个动作却忘了进这张意图表——那是开发期缺陷。宁可点名
+        # 走到这里只可能是 parser 添了**第三条口令腿**却忘了进这张意图表——那是开发期缺陷
+        # （`migrate` 不落在这里：它在建表之前就分派掉了，压根不写 argon2id 行）。宁可点名
         # 退出，也不让 `_MUST_CHANGE_BY_ACTION[args.action]` 崩一个 `KeyError` 栈；更不静默取
         # 某个默认值，因为"重置却忘了置门"这类事故正是从静默 fallback 里漏出来的。
         print(
             f"未预期的 credentials 动作：{args.action}（`_MUST_CHANGE_BY_ACTION` 未同步）",
             file=sys.stderr,
         )
         return 3
     must_change = _MUST_CHANGE_BY_ACTION[args.action]

## backend\tests\test_credentials_contract.py
sha1 base 82d2f0f2c88e63d390a7efc02c9cdc26f6a13501  sha1 head 16db53480ba5986585a72affa13393954d429be9
  base: bytes=84860 CRLF=0 loneLF=1479
  head: bytes=101449 CRLF=0 loneLF=1739
--- base/test_credentials_contract.py
+++ head/test_credentials_contract.py
@@ -1,31 +1,33 @@
 from __future__ import annotations
 
 import ast
+import contextlib
 import dataclasses
 import hashlib
 import inspect
+import io
 import json
 import os
 import re
 import sqlite3
 import sys
 import tempfile
 import threading
 import unittest
 import warnings
 from pathlib import Path
-from typing import Any
+from typing import Any, Iterator
 from unittest import mock
 
 BACKEND_DIR = Path(__file__).resolve().parents[1]
 sys.path.insert(0, str(BACKEND_DIR))
 
-from app import credentials, credentials_migration, user_store  # noqa: E402
+from app import cli, credentials, credentials_migration, user_store  # noqa: E402
 
 #: `user_store.database_path` 在 **import 期**（会话护栏还没装上）的那一枚函数。
 #: 收集期早于会话 fixture（conftest 自己的理由："护栏的重定向发生在用例开始时，比 import
 #: 晚"），所以这里拿到的必然是产品代码那一份。护栏装上去之后再叫 `user_store.database_path()`，
 #: 返回的是**改道之后**的路径——那是测试面的事实，拿它去钉"本模块读哪个 env 键"等于让护栏
 #: 自证。只有钉 env 口径的用例用这一枚；钉"护栏在场"的用例走 `ledger_guard` 的公开口径。
 RAW_DATABASE_PATH = user_store.database_path
 
@@ -657,35 +659,79 @@
         record = user_store.get_record("admin")
         self.assertTrue(record.password_hash.startswith("$argon2id$"))
         self.assertNotIn(record.password_hash, repr(record))
         self.assertNotIn("$argon2id$", repr(record))
         # repr=False 只关掉打印面：比较与字段本身都还在（等值钉仍按全部列判）。
         self.assertEqual(record, user_store.get_record("admin"))
 
 
-class MigrationPathTests(_CredentialDbPerTest):
-    """规格 §8.2 的升级腿：`data/legacy_credentials.json` → legacy 行。
-
-    夹具用 `_CredentialDbPerTest`——换 env 而不 reload 的理由写在那份夹具的文档字符串里
-    （本类的用例同样依赖"模块对象不被换掉"：`mock.patch.object` 打在旧对象上是静默空转）。
+class _ArtifactFixtures(_CredentialDbPerTest):
+    """`_CredentialDbPerTest` + 升级工件的形状真源（一份，两处用例共读）。
+
+    为什么提上来而不是在新类里再抄一遍：§8.2 的模块级用例与 §11 的 CLI 用例判的是**同一份
+    输入**（"什么算一份合法工件"由 `read_artifact` 那三枚顶层键说了算）。抄第二份 `_valid()`
+    就等于让"合法工件"长出一个测试侧真源，将来收紧顶层键时只改一处、另一处继续喂脏值还判绿。
+
+    默认路径（`data/legacy_credentials.json`，按**进程 cwd** 解析）那格另给一枚上下文管理器：
+    它必须落在临时目录里，否则"让默认路径真的命中一份工件"这件事等于往 `backend/data/` 写
+    凭据材料（§8.2 明令禁止的位置）。`CONVERSATION_DB_PATH` 给的是绝对路径，所以换 cwd 不
+    跟着换库——两件事各走各的口径，正是 `LEGACY_INPUT_PATH` 那段理由里说的分叉形状。
     """
 
     def _artifact(self, payload: dict) -> Path:
         path = Path(self._tmp.name) / "artifact.json"
         path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
         return path
 
     def _valid(self, block: dict[str, str]) -> dict:
         """一份形态合法的工件（三枚顶层键都在）：只改 credentials 的用例用它，免得每处重抄。"""
         return {
             "generated_at": "2026-09-25T00:00:00+00:00",
             "source": "app/auth.py@pre-SEC-A",
             "credentials": block,
         }
+
+    @contextlib.contextmanager
+    def _with_artifact_at_default_path(self, payload: dict) -> Iterator[Path]:
+        """把 `payload` 放到**默认路径**上并站在临时目录里：交出那份文件的绝对路径。
+
+        序列化发生在 chdir 之前（`json.dumps` 不碰 cwd，写文件才碰），yield 出去的绝对路径
+        在退出上下文之后仍然可用于 `exists()` 断言——"工件没被谁吃掉"正是调用方要问的话。
+        """
+        document = json.dumps(payload)
+        original = os.getcwd()
+        os.chdir(self._tmp.name)
+        try:
+            (Path("data")).mkdir(parents=True, exist_ok=True)
+            (Path("data") / "legacy_credentials.json").write_text(
+                document, encoding="utf-8", newline="\n")
+            yield Path(self._tmp.name) / "data" / "legacy_credentials.json"
+        finally:
+            # 必须回位：`tearDown` 删临时目录时进程还站在里面的话，Windows 上删不掉。
+            os.chdir(original)
+
+    @contextlib.contextmanager
+    def _standing_where_the_default_path_is_empty(self) -> Iterator[None]:
+        """站在一份**没有**工件的临时目录里（默认路径按 cwd 解析 ⇒ 这就是全新安装）。"""
+        original = os.getcwd()
+        os.chdir(self._tmp.name)
+        try:
+            yield
+        finally:
+            os.chdir(original)
+
+
+class MigrationPathTests(_ArtifactFixtures):
+    """规格 §8.2 的升级腿：`data/legacy_credentials.json` → legacy 行。
+
+    夹具用 `_ArtifactFixtures`（底下就是 `_CredentialDbPerTest`）——换 env 而不 reload 的理由
+    写在那份夹具的文档字符串里（本类的用例同样依赖"模块对象不被换掉"：`mock.patch.object`
+    打在旧对象上是静默空转）。
+    """
 
     def test_a_fresh_install_without_an_artifact_imports_nothing(self):
         """SECA-04b：全新安装不生产 legacy 行，这是 §8.2 分家的落点。"""
         report = credentials_migration.import_from_artifact(
             Path(self._tmp.name) / "does-not-exist.json"
         )
         self.assertFalse(report.artifact_present)
         self.assertEqual((), report.imported)
@@ -1066,16 +1112,230 @@
             self.assertTrue(row.updated_at)
         # 状态面也不许带出口令材料：`AccountStatus` 里压根没有 `password_hash` 这一格
         # （口径同 `UserStoreSchemaTests`：不是"没人写"，是"没有可写的地方"）。
         self.assertNotIn(
             "password_hash", {field.name for field in dataclasses.fields(status.accounts[0])}
         )
 
 
+class LegacyImportCliTests(_ArtifactFixtures):
+    """规格 §11：`python -m app.cli credentials migrate` 是 legacy 导入的**唯一生产入口**。
+
+    §20.5 的裁定有两半，本类的用例一一对上，缺一半就有一条测不到的路：
+    - 「导入是运维显式动作」⇒ 四条退出码全部按 CLI 的**行为**判（真进程、真临时库、真工件），
+      不给 `cli` 本身打桩——桩掉被测对象等于把契约换成对自己写法的复述。
+    - 「启动仍然绝不自动导入」⇒ `test_starting_the_app_...` 真起一次 lifespan。`TestClient(app)`
+      不进上下文管理器根本不跑 lifespan（`test_secret_hygiene_contract.py::
+      StartupGuardLifespanTests` 就是为此存在），所以那一条既要点真上下文、又要留下"lifespan
+      确实跑过"的证据，否则"零行"可能只是因为压根没启动。
+    """
+
+    #: 工件里的合成摘要：形状合法（64 位小写 hex），取值沿用本文件既有用例的口径（`"a" * 64`），
+    #  不是 §4 那 5 枚真值——它们不许出现在任何写进仓库的文件里。
+    DIGESTS = {"admin": "a" * 64, "sales01": "b" * 64}
+
+    def _cli(self, argv: list[str]) -> tuple[int, str, str]:
+        """跑一次 CLI，把 `(rc, stdout, stderr)` 一起交回来：三格都是判据面。"""
+        out, err = io.StringIO(), io.StringIO()
+        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
+            code = cli.main(argv)
+        return code, out.getvalue(), err.getvalue()
+
+    def test_dev_import_lands_legacy_rows_and_prints_the_four_fields(self):
+        """§11 规则 1：有工件 ⇒ rc 0、四字段逐格可归档，行本身由 `migration-status` 自证。"""
+        with self._with_artifact_at_default_path(self._valid(self.DIGESTS)):
+            code, out, err = self._cli(["credentials", "migrate"])
+        self.assertEqual(0, code, f"out={out!r} err={err!r}")
+        self.assertIn("artifact_present=True", out)
+        self.assertIn("imported=2 admin,sales01", out)
+        self.assertIn("skipped=0 -", out)
+        self.assertIn("reason=-", out)
+        self.assertEqual("", err)
+        records = {record.username: record for record in user_store.list_records()}
+        self.assertEqual({"admin", "sales01"}, set(records))
+        for record in records.values():
+            self.assertEqual(credentials.ALGORITHM_LEGACY_SHA256, record.algorithm)
+            self.assertTrue(record.must_change, "导入的行必须带着强制改密门（§8.2 升级路径）")
+        # 观测面闭环：SECA-04 判闭合用的是 `migration-status` 那行读数，不是报告字段。
+        status_code, status_out, status_err = self._cli(["credentials", "migration-status"])
+        self.assertEqual(0, status_code, f"out={status_out!r} err={status_err!r}")
+        self.assertIn("legacy_count=2", status_out)
+        self.assertIn("must_change=1", status_out)
+
+    def test_an_absent_artifact_is_a_legal_steady_state_and_still_exits_zero(self):
+        """§11 规则 1 的那一格：`artifact_present=False, imported=0` 是**成功**。
+
+        这条用例的全部价值在它判红的方向：把"没有工件"实现成非零退出、或往 stderr 说一句
+        "导入失败"，全新安装就永远收不掉 `migrate` 这一格。合法缺席的输入被判成事故，这件事
+        本项目在别的门上已经被咬过一次。
+        """
+        with self._standing_where_the_default_path_is_empty():
+            code, out, err = self._cli(["credentials", "migrate"])
+        self.assertEqual(0, code, f"out={out!r} err={err!r}")
+        self.assertIn("artifact_present=False", out)
+        self.assertIn("imported=0 -", out)
+        self.assertEqual("", err, "合法稳态不该往 stderr 说话")
+        self.assertNotIn("Traceback", out + err)
+        status = credentials_migration.status()
+        self.assertEqual((0, 0), (status.legacy_count, status.argon2id_count))
+
+    def test_enterprise_mode_refuses_the_import_and_writes_not_a_single_row(self):
+        """§11 规则 2 + §8.5 企业列：`SECURITY_ENTERPRISE_MODE=true` ⇒ 拒、零行、非零退出。
+
+        企业形态下"文件还在所以顺手导"是 §8.5 fail-closed 被绕过的最直接形状。既有那行只比
+        三格取值、不比整条记录：失败信息里因此永远不会出现 `password_hash` 那一段。
+        """
+        user_store.create_argon2("admin", plain_password="already-migrated 123456",
+                                 must_change=False)
+        before = user_store.get_record("admin")
+        with self._with_artifact_at_default_path(
+                self._valid({"admin": "a" * 64, "sales01": "b" * 64, "viewer": "c" * 64})):
+            with mock.patch.object(cli.settings, "security_enterprise_mode", True):
+                code, out, err = self._cli(["credentials", "migrate"])
+            self.assertEqual(2, code, f"out={out!r} err={err!r}")
+            self.assertEqual("", out, "拒绝那一格没有可打印的字段")
+            self.assertIn("企业形态", err)
+            self.assertIn("migrate", err)
+            # 一行不写：既有 argon2id 行没被降级，也没有任何 legacy 行长出来。
+            after = user_store.get_record("admin")
+            self.assertEqual(
+                (before.algorithm, before.credentials_version, before.must_change),
+                (after.algorithm, after.credentials_version, after.must_change))
+            status = credentials_migration.status()
+            self.assertEqual((0, 1), (status.legacy_count, status.argon2id_count))
+
+    def test_the_enterprise_refusal_does_not_even_create_the_database_file(self):
+        """"一行不写"要连 DDL 一起算：`ensure_user_credentials_schema()` 自己也是一次写。
+
+        判据是**那份文件根本不存在**（`_connect()` 一被叫到就 mkdir + 建库）。把企业检查挪到
+        建表之后，上一条仍然绿、这一条立刻红——它们测的不是同一件事。
+        """
+        untouched = Path(self._tmp.name) / "untouched.db"
+        with self._with_artifact_at_default_path(self._valid(self.DIGESTS)):
+            with mock.patch.object(cli.settings, "security_enterprise_mode", True), \
+                    mock.patch.dict(os.environ, {"CONVERSATION_DB_PATH": str(untouched)}):
+                code, out, err = self._cli(["credentials", "migrate"])
+        self.assertEqual(2, code, f"out={out!r} err={err!r}")
+        self.assertFalse(untouched.exists(), f"企业形态的拒绝路上把库建出来了：{untouched}")
+
+    def test_running_it_twice_imports_nothing_and_never_downgrades_a_converged_row(self):
+        """§11 规则 3：`only_missing=True` ⇒ 第二次只补真缺的行，已收敛的一行都不许回写。
+
+        `writer.call_count == 0` 是这条用例的重心：只看结果的话，"根本不试"与"试一次靠
+        `INSERT ... DO NOTHING` 吞掉"同形（口径同 `MigrationPathTests` 里那枚模块级钉）。
+        今天它由 `only_missing` 兜住，写手哪天被改成 UPSERT 就当场红。
+        """
+        user_store.create_argon2("admin", plain_password="already-migrated 123456",
+                                 must_change=False)
+        with self._with_artifact_at_default_path(
+                self._valid({"admin": "a" * 64, "sales01": "b" * 64, "viewer": "c" * 64})):
+            first, first_out, first_err = self._cli(["credentials", "migrate"])
+            self.assertEqual(0, first, f"out={first_out!r} err={first_err!r}")
+            self.assertIn("imported=2 sales01,viewer", first_out)
+            self.assertIn("skipped=1 admin", first_out)
+            with mock.patch.object(user_store, "import_legacy_digest",
+                                   wraps=user_store.import_legacy_digest) as writer:
+                second, second_out, second_err = self._cli(["credentials", "migrate"])
+        self.assertEqual(0, second, f"out={second_out!r} err={second_err!r}")
+        self.assertIn("artifact_present=True", second_out)
+        self.assertIn("imported=0 -", second_out)
+        self.assertIn("skipped=3 admin,sales01,viewer", second_out)
+        self.assertEqual(0, writer.call_count, "已存在行的意思是**不去写它**")
+        self.assertEqual(credentials.ALGORITHM_ARGON2ID, user_store.get_record("admin").algorithm)
+        status = credentials_migration.status()
+        self.assertEqual((2, 1), (status.legacy_count, status.argon2id_count))
+
+    def test_starting_the_app_never_consumes_the_upgrade_artifact(self):
+        """§11 规则 1 的另一半 / §20.5：启动路径**不**新增自动导入。
+
+        真起一次 lifespan（`with TestClient(app)` 才跑）：工件在场、库里一行都没有 ⇒ 起来之后
+        仍然一行都没有、工件仍在原地。两个 warmup 换成 `MagicMock` 不是装饰，`called` 就是
+        "lifespan 真的跑过"的证据——缺了它，"零行"可能只是压根没启动。哪天有人把
+        `import_from_artifact()` 接进 lifespan，这一条是唯一会红的那个地方。
+        """
+        from fastapi.testclient import TestClient
+
+        from app.main import app as fastapi_app
+
+        rows_before = len(user_store.list_records())
+        with mock.patch("app.main.warmup_identity_permissions") as identity_warmup, \
+                mock.patch("app.main.warmup_llm_router") as router_warmup:
+            with self._with_artifact_at_default_path(self._valid(self.DIGESTS)) as artifact:
+                with TestClient(fastapi_app):
+                    pass
+            self.assertTrue(identity_warmup.called, "lifespan 没跑：这条钉是空的")
+            self.assertTrue(router_warmup.called, "lifespan 没跑：这条钉是空的")
+        self.assertEqual(rows_before, len(user_store.list_records()))
+        self.assertEqual(0, credentials_migration.status().legacy_count)
+        self.assertTrue(artifact.exists(), "启动路径把升级工件消费掉了")
+
+    def test_the_migrate_face_carries_no_credential_material_and_reads_no_password(self):
+        """§11 规则 4 + SEC-A-002：`migrate` 写的就是工件里已有的摘要，明文与摘要都不许见面。
+
+        三面同判：env（它不需要口令，也没资格弹掉别人的口令）、argv（命名空间里没有能装口令的
+        槽位）、stdout/stderr（既不含那两枚合成摘要、也不含它们的前缀，更不含**任何**一段
+        ≥16 位连续 hex——这条比"逐枚点名 5 枚真值"更强，而且不需要把真值抄进仓库文件）。
+        """
+        sentinel = "unused-by-this-action-" + "x" * 8
+        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: sentinel}):
+            with self._with_artifact_at_default_path(self._valid(self.DIGESTS)):
+                code, out, err = self._cli(["credentials", "migrate"])
+            self.assertEqual(0, code, f"out={out!r} err={err!r}")
+            # 用完不弹：`bootstrap-admin`/`reset` 那条腿弹的是它自己取到的口令，本动作没取过。
+            self.assertIn(cli.PASSWORD_ENV_VAR, os.environ,
+                          "migrate 读走（并弹掉）了它根本不该碰的口令 env")
+        face = out + err
+        self.assertNotIn(sentinel, face)
+        self.assertNotIn(cli.PASSWORD_ENV_VAR, face)
+        args = cli.build_parser().parse_args(["credentials", "migrate"])
+        self.assertEqual({"command", "action"}, set(vars(args)),
+                         "`migrate` 多出了一枚能装凭据材料的参数")
+        for digest in self.DIGESTS.values():
+            self.assertNotIn(digest, face)
+            self.assertNotIn(digest[:8], face, "输出面里出现了摘要前缀")
+        self.assertIsNone(re.search(r"[0-9a-f]{16,}", face), "输出面里出现了一段长 hex")
+        self.assertNotIn("$argon2", face)
+
+    def test_a_store_incident_exits_nonzero_without_becoming_a_digest_face(self):
+        """§11 规则 3：底层存储事故 ⇒ 非零退出，且两格输出里不许出现口令或摘要。
+
+        `CredentialStoreError` 不许被咽成一次"跳过"（那会把 `legacy_count` 停在一个没人知道
+        的数上），也不许翻成"这个人的口令错了"——原样转出去即可，口径同 `bootstrap-admin`
+        那条腿的 `print(str(exc))`。
+        """
+        with self._with_artifact_at_default_path(self._valid(self.DIGESTS)):
+            with mock.patch.object(user_store, "import_legacy_digest",
+                                   side_effect=user_store.CredentialStoreError("disk full")):
+                code, out, err = self._cli(["credentials", "migrate"])
+        self.assertEqual(1, code, f"out={out!r} err={err!r}")
+        self.assertEqual("", out)
+        self.assertIn("disk full", err)
+        self.assertNotIn("Traceback", out + err)
+        for digest in self.DIGESTS.values():
+            self.assertNotIn(digest, out + err)
+        self.assertIsNone(re.search(r"[0-9a-f]{16,}", out + err))
+        self.assertEqual(0, credentials_migration.status().legacy_count)
+
+    def test_a_malformed_artifact_is_refused_as_a_whole_before_any_row_lands(self):
+        """整份拒这条出路在 CLI 面上的形状：非零、说人话、库里一行没有、摘要不外泄。
+
+        这一格规格没有点名（§11 四条规则里讲的是"工件不在场"，不是"工件读不得"），实现取
+        rc=2：与"身份不存在""env 口令不合格"同一类**运维一次能修完**的拒绝。见报告 §5 记录。
+        """
+        with self._with_artifact_at_default_path(self._valid({"admin": "not-hex"})):
+            code, out, err = self._cli(["credentials", "migrate"])
+        self.assertEqual(2, code, f"out={out!r} err={err!r}")
+        self.assertEqual("", out, "被拒的工件没有可打印的字段")
+        self.assertIn("admin", err)
+        self.assertNotIn("not-hex", err)
+        self.assertNotIn("Traceback", out + err)
+        self.assertEqual(0, credentials_migration.status().legacy_count)
+
+
 class _GuardProbe(unittest.TestCase):
     """自建一份「假真库」+ 一个只盯它的护栏实例，用来驱动**真的** `user_store` 函数。
 
     与会话级护栏同手法（`test_model_router_v23_contract.py::LedgerGuardClassificationTests`
     就是这个形状），刻意不在真库上演练：本类的每一笔"写"都记在自己那个 `LedgerGuard` 实例
     的 list 上，所以既不会污染会话统计，也不会被会话归责钩子读成事故——归责钩子读的仍是
     `credential_write_redirects()` 那条真通道，由 `CredentialGuardWiringTests` 点数。
     """

## Unchanged-by-attestation (implementer claims; verify if you need to)
credentials_migration.py / user_store.py / auth.py / main.py / config.py / directory.py  --  controller re-measures these below

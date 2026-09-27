## Task 3: 受限迁移路径（`credentials_migration.py` + 升级工件）

**Files:**
- Create: `backend/app/credentials_migration.py`
- Create: `backend/data/legacy_credentials.json`（升级工件；**closure 时删除**，Task 10）
- Test: `backend/tests/test_credentials_contract.py`（追加 `MigrationPathTests`）

**Interfaces:**
- Consumes: `user_store.import_legacy_digest` / `get_record` / `count_by_algorithm` / `CredentialRecord`
- Produces（Task 5/7/10 依赖）：
  ```python
  LEGACY_INPUT_PATH: Path                       # Path("data/legacy_credentials.json")
  class MigrationArtifactError(RuntimeError): ...
  @dataclass(frozen=True)
  class MigrationReport: artifact_present: bool; imported: tuple[str,...]; skipped: tuple[str,...]; reason: str
  @dataclass(frozen=True)
  class AccountStatus: username: str; algorithm: str; credentials_version: int
                       must_change: bool; locked_until: str | None; updated_at: str
  @dataclass(frozen=True)
  class MigrationStatus: legacy_count: int; argon2id_count: int; accounts: tuple[AccountStatus, ...]
  def read_artifact(path: Path = LEGACY_INPUT_PATH) -> dict[str, str]
  def import_from_artifact(path: Path = LEGACY_INPUT_PATH, *, only_missing: bool = True) -> MigrationReport
  def status() -> MigrationStatus
  ```

**工件格式**（顶层键封闭，形态错 = 拒绝导入而不是部分导入）：

```json
{
  "generated_at": "2026-09-25T00:00:00+00:00",
  "source": "app/auth.py@pre-SEC-A",
  "credentials": {
    "admin": "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9",
    "sales01": "6bc0a63cb29c92306020c0a6bbc358cc4628db277dc06e253535e126517ad637",
    "hr01": "070a3b5e8d4bd5c46acccb91c9c54614c0cd649e78c4c4719e3a64270bae5ddf",
    "user": "e606e38b0d8c19b24cf0ee3808183162ea7cd63ff7912dbb22b5e803286b4446",
    "viewer": "65375049b9e4d7cad6c9ba286fdeb9394b28135a3e84136404cfccfdcc438894"
  }
}
```

`source` 字段值来自 Task 5 删除 `auth.USERS` 之前的抄录（本任务 Step 1 先从 `app/auth.py:71-103` 逐字取 digest，不手写、不凭记忆）。

- [ ] **Step 1: 从现有源码生成升级工件**（不手抄）

```bash
cd /e/xiangmu/rag/backend
python - <<'PY'
import json, re
from datetime import datetime, timezone
from pathlib import Path
source = Path("app/auth.py").read_text(encoding="utf-8")
pairs = re.findall(r'"username":\s*"([^"]+)",.*?"password_hash":\s*"([0-9a-f]{64})"', source, re.S)
artifact = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "source": "app/auth.py@pre-SEC-A",
    "credentials": {username: digest for username, digest in pairs},
}
Path("data").mkdir(exist_ok=True)
Path("data/legacy_credentials.json").write_text(
    json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
print(len(artifact["credentials"]), sorted(artifact["credentials"]))
PY
```
Expected: `5 ['admin', 'hr01', 'sales01', 'user', 'viewer']`。少于 5 就说明正则没对上，必须先修正则——**不许**照本计划里的字面量手抄（抄错=迁移后没人能登录，且 SECA-04 的"0 命中"扫描仍然绿，因为它只数 digest 是否存在）。

- [ ] **Step 2: 写失败的测试**（追加 `MigrationPathTests`）

```python
class MigrationPathTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = os.environ.get("CONVERSATION_DB_PATH")
        os.environ["CONVERSATION_DB_PATH"] = str(Path(self._tmp.name) / "migrate.db")
        importlib.reload(config_module)
        importlib.reload(user_store)
        user_store.ensure_user_credentials_schema()

    def tearDown(self):
        os.environ.pop("CONVERSATION_DB_PATH", None)
        if self._saved is not None:
            os.environ["CONVERSATION_DB_PATH"] = self._saved
        importlib.reload(config_module)
        importlib.reload(user_store)
        self._tmp.cleanup()

    def _artifact(self, payload: dict) -> Path:
        path = Path(self._tmp.name) / "artifact.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_a_fresh_install_without_an_artifact_imports_nothing(self):
        """SECA-04b：全新安装不生产 legacy 行，这是 §8.2 分家的落点。"""
        report = credentials_migration.import_from_artifact(
            Path(self._tmp.name) / "does-not-exist.json"
        )
        self.assertFalse(report.artifact_present)
        self.assertEqual((), report.imported)
        self.assertEqual(0, credentials_migration.status().legacy_count)

    def test_imported_rows_are_legacy_and_flagged_for_forced_change(self):
        path = self._artifact(
            {
                "generated_at": "2026-09-25T00:00:00+00:00",
                "source": "app/auth.py@pre-SEC-A",
                "credentials": {"admin": "a" * 64},
            }
        )
        report = credentials_migration.import_from_artifact(path)
        self.assertEqual(("admin",), report.imported)
        record = user_store.get_record("admin")
        self.assertEqual(credentials.ALGORITHM_LEGACY_SHA256, record.algorithm)
        self.assertTrue(record.must_change)
        self.assertEqual(1, credentials_migration.status().legacy_count)

    def test_reimporting_does_not_downgrade_an_already_upgraded_row(self):
        user_store.create_argon2("admin", plain_password="already-migrated 123456", must_change=False)
        path = self._artifact({"generated_at": "x", "source": "y", "credentials": {"admin": "a" * 64}})
        report = credentials_migration.import_from_artifact(path)
        self.assertEqual((), report.imported)
        self.assertEqual(("admin",), report.skipped)
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, user_store.get_record("admin").algorithm)

    def test_a_malformed_artifact_is_rejected_as_a_whole(self):
        for payload in (
            {"generated_at": "x", "source": "y", "credentials": {"admin": "not-hex"}},
            {"generated_at": "x", "source": "y", "credentials": ["admin"]},
            {"generated_at": "x", "source": "y", "credentials": {}, "oops": 1},
        ):
            with self.subTest(keys=sorted(payload)):
                with self.assertRaises(credentials_migration.MigrationArtifactError):
                    credentials_migration.import_from_artifact(self._artifact(payload))
        self.assertEqual(0, credentials_migration.status().legacy_count)

    def test_only_the_migration_module_may_call_the_legacy_writer(self):
        """SEC-A-004：受限路径必须真的受限——按调用方扫描，不按函数名信任。"""
        callers: set[str] = set()
        for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_legacy_digest"
                ):
                    callers.add(path.name)
        self.assertEqual({"credentials_migration.py"}, callers)
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q -k MigrationPath
```
Expected: `ModuleNotFoundError: No module named 'app.credentials_migration'`（同时补上测试文件 import 段的 `from app import credentials_migration` 与 `import json`）。

- [ ] **Step 4: 写实现**（`backend/app/credentials_migration.py`）

```python
"""受限迁移路径（规格 §8.2）。全仓唯一能生产 legacy 凭据行的地方。

它**只**服务"从 SEC-A 之前的版本升级"：全新安装没有工件 ⇒ 没有 legacy 行。
把这两件事混在一起（"缺凭据行就自动造 legacy"）是本规格在复核里被否掉的写法。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import credentials, user_store

LEGACY_INPUT_PATH = Path("data/legacy_credentials.json")
ARTIFACT_KEYS = frozenset({"generated_at", "source", "credentials"})
_LEGACY_HEX = re.compile(r"^[0-9a-f]{64}$")


class MigrationArtifactError(RuntimeError):
    """升级工件形态不对。整体拒绝，绝不"跳过坏条目继续导几个"。"""


@dataclass(frozen=True)
class MigrationReport:
    artifact_present: bool
    imported: tuple[str, ...]
    skipped: tuple[str, ...]
    reason: str = ""


@dataclass(frozen=True)
class AccountStatus:
    username: str
    algorithm: str
    credentials_version: int
    must_change: bool
    locked_until: str | None
    updated_at: str


@dataclass(frozen=True)
class MigrationStatus:
    legacy_count: int
    argon2id_count: int
    accounts: tuple[AccountStatus, ...]


def read_artifact(path: Path = LEGACY_INPUT_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MigrationArtifactError("迁移输入不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise MigrationArtifactError("迁移输入顶层必须是对象")
    unknown = set(payload) - ARTIFACT_KEYS
    if unknown:
        raise MigrationArtifactError(f"迁移输入含未知字段：{sorted(unknown)}")
    block = payload.get("credentials")
    if block is None:
        raise MigrationArtifactError("迁移输入缺少 credentials")
    if not isinstance(block, dict):
        raise MigrationArtifactError("credentials 必须是 username→digest 的对象")
    normalized: dict[str, str] = {}
    for username, digest in block.items():
        if not isinstance(digest, str) or not _LEGACY_HEX.match(digest.strip().lower()):
            raise MigrationArtifactError(f"{username} 的迁移输入不是 64 位 hex")
        normalized[str(username)] = digest.strip().lower()
    return normalized


def import_from_artifact(
    path: Path = LEGACY_INPUT_PATH, *, only_missing: bool = True
) -> MigrationReport:
    block = read_artifact(path)
    if not block:
        return MigrationReport(
            artifact_present=False,
            imported=(),
            skipped=(),
            reason="迁移输入不存在：全新安装不生产 legacy 行",
        )
    imported: list[str] = []
    skipped: list[str] = []
    for username, digest in sorted(block.items()):
        if only_missing and user_store.get_record(username) is not None:
            skipped.append(username)
            continue
        user_store.import_legacy_digest(username, digest, must_change=True)
        imported.append(username)
    return MigrationReport(True, tuple(imported), tuple(skipped), "")


def status() -> MigrationStatus:
    counts = user_store.count_by_algorithm()
    rows = tuple(
        AccountStatus(
            username=record.username,
            algorithm=record.algorithm,
            credentials_version=record.credentials_version,
            must_change=record.must_change,
            locked_until=record.locked_until,
            updated_at=record.updated_at,
        )
        for record in user_store.list_records()
    )
    return MigrationStatus(
        legacy_count=int(counts.get(credentials.ALGORITHM_LEGACY_SHA256, 0)),
        argon2id_count=int(counts.get(credentials.ALGORITHM_ARGON2ID, 0)),
        accounts=rows,
    )
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_credentials_contract.py -q
```
Expected: `24 passed`。

- [ ] **Step 6: 快照 + 台账**

```bash
cd /e/xiangmu/rag/backend
cp -r app ../.superpowers/sdd/SECURITY_A_PLAN/snap-task3-app
cp data/legacy_credentials.json ../.superpowers/sdd/SECURITY_A_PLAN/snap-task3-legacy-artifact.json
echo "- Ruling: 迁移器只校验凭据形态（64-hex / 顶层键封闭）；身份交叉校验留到 Task 5 的启动 seed 编排，因为身份层 Task 4 才存在。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
echo "- Ruling: 重跑导入对已存在行只跳过，绝不把已升级的 argon2id 行降回 legacy。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
```

---


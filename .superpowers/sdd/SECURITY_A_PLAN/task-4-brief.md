## Task 4: 身份声明层（`directory.py` + `users.json` / `users.demo.json`）

**Files:**
- Create: `backend/app/directory.py`
- Create: `backend/config/users.json`、`backend/config/users.demo.json`
- Modify: `backend/app/config.py`（加 `security_enterprise_mode`）
- Modify: `backend/app/knowledge_os.py:24,560,564,567,703`（`USERS` 读点 → directory）
- Test: `backend/tests/test_user_directory_contract.py`（新建）

**Interfaces:**
- Consumes: `settings.security_enterprise_mode`（本任务新增，默认 `False`）
- Produces（Task 5/7/9 依赖）：
  ```python
  ENTERPRISE_IDENTITIES_FILE: Path              # Path("config/users.json")
  DEMO_IDENTITIES_FILE: Path                    # Path("config/users.demo.json")
  FORBIDDEN_IDENTITY_KEYS: frozenset[str]
  class IdentityConfigError(RuntimeError): ...
  class UserIdentity(BaseModel):                # extra="forbid"
      username: str; display_name: str; role: str
      feishu_open_id: str | None = None; enabled: bool = True
  def load_identities(*, include_demo: bool) -> dict[str, UserIdentity]
  def identities() -> Mapping[str, UserIdentity]        # 按当前形态缓存
  def get_identity(username: str) -> UserIdentity | None
  def reset_cache() -> None
  @contextmanager def override_identities(mapping: Mapping[str, UserIdentity])
  ```

- [ ] **Step 1: 先确认 `config/` 在镜像里，且路径基准是 `backend/`**

```bash
cd /e/xiangmu/rag/backend && ls config && grep -n "COPY config" Dockerfile
```
Expected: `config/` 存在（V2.3 的模型注册表就在这里）且 Dockerfile 有 `COPY config ./config`。若第二条不成立，本任务额外要在 Dockerfile 补该行——**先测再写，不要假设**。

- [ ] **Step 2: 写失败的测试**（`backend/tests/test_user_directory_contract.py`）

```python
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import config as config_module  # noqa: E402
from app import directory  # noqa: E402


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text(json.dumps({"identities": records}, ensure_ascii=False), encoding="utf-8")
    return path


class IdentityFileTests(unittest.TestCase):
    """SECA-07 / SECA-23：身份文件是**结构上**无口令，不是"约定不写"。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.enterprise = _write(
            self.root / "users.json",
            [{"username": "admin", "display_name": "管理员", "role": "ADMIN"}],
        )
        self.demo = _write(
            self.root / "users.demo.json",
            [{"username": "viewer", "display_name": "只读", "role": "VIEWER"}],
        )
        self._saved = (directory.ENTERPRISE_IDENTITIES_FILE, directory.DEMO_IDENTITIES_FILE)
        directory.ENTERPRISE_IDENTITIES_FILE = self.enterprise
        directory.DEMO_IDENTITIES_FILE = self.demo

    def tearDown(self):
        (directory.ENTERPRISE_IDENTITIES_FILE, directory.DEMO_IDENTITIES_FILE) = self._saved
        self._tmp.cleanup()

    def _load(self, *, include_demo: bool):
        return directory.load_identities(include_demo=include_demo)

    def test_enterprise_mode_does_not_read_the_demo_file_at_all(self):
        self.assertEqual({"admin", "viewer"}, set(self._load(include_demo=True)))
        self.assertEqual({"admin"}, set(self._load(include_demo=False)))

    def test_a_credential_shaped_key_fails_startup_in_either_file(self):
        for key in ("password", "password_hash", "hash", "secret", "token", "api_key"):
            with self.subTest(key=key):
                _write(self.demo, [{"username": "viewer", "display_name": "只读",
                                    "role": "VIEWER", key: "x"}])
                with self.assertRaises(directory.IdentityConfigError):
                    self._load(include_demo=True)
        _write(self.enterprise, [{"username": "admin", "display_name": "管理员",
                                 "role": "ADMIN", "password": "hunter2"}])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)

    def test_a_legacy_digest_value_is_rejected_even_under_an_allowed_key(self):
        _write(self.enterprise, [{"username": "admin", "display_name": "a" * 40,
                                 "role": "ADMIN"}])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)

    def test_unknown_extra_fields_are_rejected_not_ignored(self):
        _write(self.enterprise, [{"username": "admin", "display_name": "管理员",
                                 "role": "ADMIN", "is_superuser": True}])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)

    def test_duplicate_username_across_files_fails_instead_of_letting_demo_override(self):
        """M18 的目标形态：`{**enterprise, **demo}` 必须被这条挡下。"""
        _write(self.demo, [{"username": "admin", "display_name": "假冒管理员", "role": "VIEWER"}])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=True)

    def test_duplicate_feishu_open_id_across_files_fails(self):
        _write(self.enterprise, [{"username": "admin", "display_name": "管理员",
                                 "role": "ADMIN", "feishu_open_id": "ou_shared"}])
        _write(self.demo, [{"username": "viewer", "display_name": "只读",
                           "role": "VIEWER", "feishu_open_id": "ou_shared"}])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=True)

    def test_disabled_is_a_first_class_identity_flag(self):
        _write(self.enterprise, [{"username": "admin", "display_name": "管理员",
                                 "role": "ADMIN", "enabled": False}])
        self.assertFalse(self._load(include_demo=False)["admin"].enabled)

    def test_default_is_enabled(self):
        self.assertTrue(self._load(include_demo=False)["admin"].enabled)

    def test_missing_enterprise_file_is_a_hard_failure_not_an_empty_directory(self):
        self.enterprise.unlink()
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_user_directory_contract.py -q
```
Expected: `ModuleNotFoundError: No module named 'app.directory'`。

- [ ] **Step 4: 写实现**（`backend/app/directory.py`）

```python
"""身份声明层（规格 §6.4）。身份的唯一真源是文件，凭据状态在 user_store，两边不得互串。

role 的取值**不在这里**校验：`access_role_for()` 对未知角色返回 None、权限表退化为空集，
那已经是 fail-closed。在这里再抄一份角色白名单只会造出第二个真源（RBAC 改了这里没改 = 静默失配）。
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ENTERPRISE_IDENTITIES_FILE = Path("config/users.json")
DEMO_IDENTITIES_FILE = Path("config/users.demo.json")

# 敏感键与"看起来像凭据"的形态。extra="forbid" 挡不住 display_name 里塞 digest，
# 所以两重都要有。
FORBIDDEN_IDENTITY_KEYS = frozenset(
    {"password", "password_hash", "hash", "secret", "token", "api_key", "credentials", "legacy"}
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class IdentityConfigError(RuntimeError):
    """身份文件不合法 ⇒ 启动失败。不是告警，不是忽略该条目。"""


class UserIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=32)
    feishu_open_id: str | None = None
    enabled: bool = True


def _validate_records(path: Path, payload: Any) -> list[UserIdentity]:
    if not path.exists():
        raise IdentityConfigError(f"身份文件不存在：{path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IdentityConfigError(f"身份文件不是合法 JSON：{path}") from exc
    if not isinstance(document, dict) or set(document) - {"identities"}:
        raise IdentityConfigError(f"身份文件顶层键必须是唯一的 identities：{path}")
    records = document.get("identities")
    if not isinstance(records, list):
        raise IdentityConfigError(f"{path}: identities 必须是数组")
    identities: list[UserIdentity] = []
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            raise IdentityConfigError(f"{path}: identities[{index}] 必须是对象")
        offending = FORBIDDEN_IDENTITY_KEYS & {str(key).lower() for key in raw}
        if offending:
            raise IdentityConfigError(f"{path}: identities[{index}] 含凭据字段 {sorted(offending)}")
        for value in raw.values():
            if isinstance(value, str) and _HEX64.match(value.strip().lower()):
                raise IdentityConfigError(f"{path}: identities[{index}] 含疑似口令摘要的取值")
        try:
            identities.append(UserIdentity(**raw))
        except ValidationError as exc:
            raise IdentityConfigError(f"{path}: identities[{index}] 不合法：{exc}") from exc
    return identities


def load_identities(*, include_demo: bool) -> dict[str, UserIdentity]:
    """enterprise 先、demo 后；重名一律拒，**不做**字典覆盖式合并。"""
    sources: list[Path] = [ENTERPRISE_IDENTITIES_FILE]
    if include_demo:
        sources.append(DEMO_IDENTITIES_FILE)
    merged: dict[str, UserIdentity] = {}
    seen_open_ids: dict[str, str] = {}
    for source in sources:
        for identity in _validate_records(source, None):
            if identity.username in merged:
                raise IdentityConfigError(
                    f"username 重复：{identity.username}（{source}）——demo 身份不得覆盖企业身份"
                )
            if identity.feishu_open_id is not None:
                if identity.feishu_open_id in seen_open_ids:
                    raise IdentityConfigError(
                        "feishu_open_id 重复："
                        f"{identity.feishu_open_id} 同时属于 {seen_open_ids[identity.feishu_open_id]}"
                        f" 与 {identity.username}"
                    )
                seen_open_ids[identity.feishu_open_id] = identity.username
            merged[identity.username] = identity
    return merged


_CACHE: dict[bool, dict[str, UserIdentity]] = {}


def identities() -> Mapping[str, UserIdentity]:
    """按形态缓存。形态在进程生命周期内不变（启动守卫负责它的成立）。"""
    from app.config import settings

    mode = bool(settings.security_enterprise_mode)
    if mode not in _CACHE:
        _CACHE[mode] = load_identities(include_demo=not mode)
    return _CACHE[mode]


def get_identity(username: str) -> UserIdentity | None:
    return identities().get(str(username))


def reset_cache() -> None:
    _CACHE.clear()


@contextmanager
def override_identities(mapping: Mapping[str, UserIdentity]) -> Iterator[None]:
    """测试接缝：替代过去"直接改 auth.USERS"的做法（规格 §16 改写的第二条）。"""
    from app.config import settings

    mode = bool(settings.security_enterprise_mode)
    saved = dict(_CACHE)
    _CACHE[mode] = dict(mapping)
    try:
        yield
    finally:
        _CACHE.clear()
        _CACHE.update(saved)
```

`_validate_records(path, payload)` 的第二个形参目前没有使用者——保留它是为了对齐 Task 5 会引入的"启动 seed 传 payload"路径；若到 Task 5 仍无人传，就在 Task 5 把它删掉，不许留成死参数。

- [ ] **Step 5: 写身份文件与 settings**

`backend/app/config.py`（放在 `jwt_secret` 之前，注明它同时驱动三件守卫）：

```python
    # SEC-A 生产形态总开关。true ⇒ 不加载 demo 身份 + 默认 JWT secret 拒启动 +
    # CORS 白名单未配拒启动（三件同生同死，规格 §8.5）。
    security_enterprise_mode: bool = False
```

`backend/config/users.json`：

```json
{
  "identities": []
}
```

`backend/config/users.demo.json`（逐字取自 `app/auth.py:71-103` 的现有记录，不改 display_name/role，口令字段**不带**）：

```json
{
  "identities": [
    { "username": "admin", "display_name": "系统管理员", "role": "ADMIN" },
    { "username": "sales01", "display_name": "销售演示账号", "role": "SALES" },
    { "username": "hr01", "display_name": "HR 演示账号", "role": "HR" },
    { "username": "user", "display_name": "普通用户演示账号", "role": "USER" },
    { "username": "viewer", "display_name": "只读访客演示账号", "role": "VIEWER" }
  ]
}
```

- [ ] **Step 6: 跑测试确认通过**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_user_directory_contract.py -q
```
Expected: `9 passed`。

- [ ] **Step 7: 迁移 `knowledge_os` 的 4 处身份读点**

`backend/app/knowledge_os.py:24` 的 import 去掉 `USERS`，改为 `from app.directory import identities as directory_identities, get_identity`；`:560` `USERS.get(...)` → `get_identity(...)`（下游 `record["role"]` 之类下标读法改成 `identity.role` / `identity.display_name` 属性读法）；`:564/:567` `len(USERS)` → `len(directory_identities())`；`:703` `for record in USERS.values()` → `for identity in directory_identities().values()`，字典构造里的 `record["username"]` → `identity.username`，其余同理。

- [ ] **Step 8: 加一枚**过渡**一致性钉（Task 5 删除）**

`backend/tests/test_user_directory_contract.py` 末尾追加：

```python
class TransitionalConsistencyPin(unittest.TestCase):
    """Task 4→5 期间 `auth.USERS` 仍在（认证腿还没切）。这枚钉防两份身份漂移。

    Task 5 删除 `USERS` 时**连这个类一起删**，不要改成"跳过"。
    """

    def test_directory_and_the_legacy_constant_table_describe_the_same_people(self):
        from app import auth

        loaded = directory.load_identities(include_demo=True)
        self.assertEqual(set(auth.USERS), set(loaded))
        for username, identity in loaded.items():
            self.assertEqual(auth.USERS[username]["display_name"], identity.display_name)
            self.assertEqual(auth.USERS[username]["role"], identity.role)
```

- [ ] **Step 9: 定向门 + 全套件**（这一步是本任务的真实风险点：4 处读点改坏不会只红安全测试）

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_user_directory_contract.py tests/test_rbac_contract.py -q
python -m pytest -q
```
Expected: 定向门绿；全套件绿且 collected 数 = Task 3 收口数 + 本任务新增测试数（记下确切数字，Task 10 要拿它对账）。若 `test_llm_egress_guard.py` 红，说明改 `knowledge_os.py` 时顺手动了出口面——回退那部分。

- [ ] **Step 10: 快照 + 台账**

```bash
cd /e/xiangmu/rag/backend
cp -r app ../.superpowers/sdd/SECURITY_A_PLAN/snap-task4-app
cp -r config ../.superpowers/sdd/SECURITY_A_PLAN/snap-task4-config
echo "- Ruling: directory 不校验 role 白名单（未知 role 已由 access_role_for→空权限 fail-closed），避免造第二个真源。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
echo "- Ruling: Task 4 结束仍保留 auth.USERS + 一枚过渡一致性钉；Task 5 删 USERS 时连钉一起删。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
```

---


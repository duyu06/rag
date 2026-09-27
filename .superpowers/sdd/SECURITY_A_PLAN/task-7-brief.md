## Task 7: 改密 / 管理员重置端点与 CLI

**Files:**
- Create: `backend/app/cli.py`
- Modify: `backend/app/main.py`（两个新端点 + 请求模型）
- Modify: `backend/app/auth.py`（`validate_new_password`、`provision_credentials`）
- Test: `backend/tests/test_password_lifecycle_contract.py`（续写）

**Interfaces:**
- Consumes: `user_store.create_argon2` / `set_password_argon2` / `get_record`；`directory.get_identity`；`auth.require_user_pending_password`；`auth._password_change_required`
- Produces:
  ```python
  # app/auth.py
  def validate_new_password(username: str, new_password: str) -> str | None   # 返回错误原因，None=通过
  def provision_credentials(username: str, *, plain_password: str, must_change: bool) -> int
      # 表内无行 → create_argon2；有行 → set_password_argon2。CLI 与管理员重置共用的一条写路径。
  # app/cli.py
  def main(argv: list[str] | None = None) -> int
  PASSWORD_ENV_VAR = "CREDENTIALS_PASSWORD"
  ```
  新端点：`POST /api/auth/password/change`、`POST /api/admin/users/{username}/password/reset`（权限 `system:operate`，**不新增权限名**）。

- [ ] **Step 1: 写失败的测试**（追加到 `test_password_lifecycle_contract.py`）

```python
from app import cli  # 追加 import（Task 7 起本文件才用得到）


class PasswordPolicyTests(_ClientCase):
    def test_short_passwords_and_username_echo_are_rejected_with_422(self):
        """§8.8：422 是输入校验，403 是权限。混用会污染既有 RBAC 语义面。"""
        body = {"current_password": "admin123", "new_password": "abc"}
        response = self.client.post(
            "/api/auth/password/change", json=body, headers=self._admin_headers()
        )
        self.assertEqual(422, response.status_code)
        for candidate in ("admin", "ADMIN", "AdMiN"):
            self.assertIsNotNone(auth.validate_new_password("admin", candidate))
        self.assertIsNone(auth.validate_new_password("admin", "a-good-new-password 123"))

    def test_policy_accepts_a_12_char_and_rejects_a_129_char_password(self):
        self.assertIsNone(auth.validate_new_password("someone", "l" * 12))
        self.assertIsNotNone(auth.validate_new_password("someone", "l" * 129))


class SelfServiceChangeTests(_ClientCase):
    def test_changing_password_logs_in_clears_the_gate_and_kills_old_tokens(self):
        """SECA-03 半边 B：升级路径的终态是"改完密就能正常用"。"""
        _seed_legacy_admin(user_store, auth)
        login = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        self.assertTrue(login.json()["password_change_required"])
        blocked = self.client.get("/api/knowledge-bases", headers=_bearer(login.json()["access_token"]))
        self.assertEqual((403, "当前账号需先修改口令"), (blocked.status_code, blocked.json()["detail"]))

        changed = self.client.post(
            "/api/auth/password/change",
            json={"current_password": "admin123", "new_password": "a-good-new-password 123"},
            headers=_bearer(login.json()["access_token"]),
        )
        self.assertEqual(200, changed.status_code)
        self.assertEqual({"changed": True}, changed.json())
        self.assertEqual(
            credentials.ALGORITHM_ARGON2ID, user_store.get_record("admin").algorithm
        )
        self.assertFalse(user_store.get_record("admin").must_change)
        self.assertEqual(
            200,
            self.client.get(
                "/api/knowledge-bases", headers=_bearer(login.json()["access_token"])
            ).status_code,
        )

    def test_changing_requires_the_current_password(self):
        login = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        response = self.client.post(
            "/api/auth/password/change",
            json={"current_password": "not-my-password 123", "new_password": "a-good-new-password 123"},
            headers=_bearer(login.json()["access_token"]),
        )
        self.assertEqual(401, response.status_code)
        self.assertEqual("用户名或密码错误", response.json()["detail"])
        # 展示面是中文文案，审计面是枚举 token（规格 §9.1 的两栏模型）。
        from app.audit import recent_events

        self.assertEqual("invalid_credentials", recent_events(limit=1)[0]["detail"])


class AdminResetTests(_ClientCase):
    def test_reset_requires_the_operate_capability(self):
        viewer = self.client.post("/api/auth/login", json={"username": "viewer", "password": "viewer123"})
        response = self.client.post(
            "/api/admin/users/hr01/password/reset",
            json={"new_password": "a-good-new-password 123"},
            headers=_bearer(viewer.json()["access_token"]),
        )
        self.assertEqual(403, response.status_code)
        self.assertIn("system:operate", response.json()["detail"])

    def test_admin_reset_clears_a_stale_lock_in_the_same_transaction(self):
        """SECA-12：reset 之后用户仍被旧 lock 挡住，是一条必被观测到的事故形态。"""
        user_store.create_argon2("hr01", plain_password="hr123", must_change=False)
        user_store.record_login_failure("hr01", max_attempts=1, lock_seconds=900)
        self.assertIsNotNone(user_store.get_record("hr01").locked_until)
        admin = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        response = self.client.post(
            "/api/admin/users/hr01/password/reset",
            json={"new_password": "a-good-new-password 123"},
            headers=_bearer(admin.json()["access_token"]),
        )
        self.assertEqual(200, response.status_code)
        record = user_store.get_record("hr01")
        self.assertIsNone(record.locked_until)
        self.assertEqual(0, record.failed_attempts)
        self.assertTrue(record.must_change)
        self.assertEqual(2, record.credentials_version)
        login = self.client.post("/api/auth/login", json={"username": "hr01", "password": "a-good-new-password 123"})
        self.assertEqual(200, login.status_code)
        self.assertTrue(login.json()["password_change_required"])


class CliTests(_ClientCase):
    def test_bootstrap_requires_a_preexisting_identity_and_never_creates_one(self):
        """SEC-A-010：bootstrap 只写凭据，身份文件不因 CLI 而改变。"""
        before = directory.ENTERPRISE_IDENTITIES_FILE.read_text(encoding="utf-8")
        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: "a-good-new-password 123"}):
            self.assertEqual(2, cli.main(["credentials", "bootstrap-admin", "--username", "ghost"]))
        self.assertIsNone(user_store.get_record("ghost"))
        self.assertEqual(before, directory.ENTERPRISE_IDENTITIES_FILE.read_text(encoding="utf-8"))

    def test_the_cli_never_accepts_a_password_on_argv(self):
        """SECA-02：argv 会被 ps 与 shell history 观察到。"""
        parser = cli.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                ["credentials", "bootstrap-admin", "--username", "admin", "--password", "x"]
            )

    def test_migration_status_reports_the_legacy_count(self):
        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: "a-good-new-password 123"}):
            self.assertEqual(0, cli.main(["credentials", "migration-status"]))
```

`test_the_cli_never_accepts_a_password_on_argv` 用 `assertRaises(SystemExit)` 而不是翻 `--help` 文本：argparse 对未定义选项正是 `SystemExit`，而 help 文本会随描述措辞漂移（V2.3 里"用文本钉行为"放过一次真缺陷，不再重复）。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_password_lifecycle_contract.py -q
```
Expected: `ModuleNotFoundError: No module named 'app.cli'` + 两条 404（端点不存在）。

- [ ] **Step 3: 实现策略与写路径**（`backend/app/auth.py`）

```python
_MIN_PASSWORD_LENGTH = 12
_MAX_PASSWORD_LENGTH = 128   # 与 LoginRequest 的上限同值：一处事实，两处引用会漂


def validate_new_password(username: str, new_password: str) -> str | None:
    if not _MIN_PASSWORD_LENGTH <= len(new_password) <= _MAX_PASSWORD_LENGTH:
        return "新口令长度需在 12 到 128 个字符之间"
    if new_password.casefold() == str(username).casefold():
        return "新口令不得与账号名相同"
    return None


def provision_credentials(username: str, *, plain_password: str, must_change: bool) -> int:
    """唯一一条"把一个新口令落成可用凭据"的路径（CLI / 管理员重置 / fixture 共用）。

    只产 argon2id：这里没有任何参数能让它产出别的算法（SEC-A-001）。
    """
    if user_store.get_record(username) is None:
        return user_store.create_argon2(username, plain_password=plain_password, must_change=must_change)
    return user_store.set_password_argon2(username, plain_password=plain_password, must_change=must_change)
```

- [ ] **Step 4: 两个端点**（`backend/app/main.py`）

```python
class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class AdminPasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=12, max_length=128)


@app.post("/api/auth/password/change")
def change_password(
    request: PasswordChangeRequest,
    user: CurrentUser = Depends(require_user_pending_password),
):
    reason = validate_new_password(user.username, request.new_password)
    if reason:
        raise HTTPException(status_code=422, detail=reason)
    result = authenticate_with_result(user.username, request.current_password)
    if result.user is None:
        # 改密端点带旧口令校验 ⇒ 它与登录是同一个爆破面，共用同一份 throttle/lock 状态。
        record_login_event(username=user.username, detail=result.audit_detail)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    provision_credentials(
        user.username, plain_password=request.new_password, must_change=False
    )
    record_event(username=user.username, role=user.role, action="PASSWORD",
                 status="SUCCESS", detail="password_changed")
    return {"changed": True}


@app.post("/api/admin/users/{username}/password/reset")
def admin_reset_password(
    username: str,
    request: AdminPasswordResetRequest,
    user: CurrentUser = Depends(require_permission("system:operate")),
):
    reason = validate_new_password(username, request.new_password)
    if reason:
        raise HTTPException(status_code=422, detail=reason)
    if directory.get_identity(username) is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    provision_credentials(username, plain_password=request.new_password, must_change=True)
    record_event(username=user.username, role=user.role, action="PASSWORD",
                 status="SUCCESS", detail="password_reset_by_admin")
    return {"reset": True, "must_change": True}
```

两处刻意形状：① 重置端点的 404 用「账号不存在」——那是**已鉴权管理员**面对的资源不存在，不构成对外的枚举面（登录腿才是），所以不改；② 两个响应都**不回显口令**，也不回显 hash 或长度。

同一改动里必须把 Task 6 的 `MustChangeGateCoverageTests.WHITELIST` 扩成 `{"POST /api/auth/password/change", "GET /api/auth/me"}`——那枚门的设计就是"多一条也红"，端点加了而白名单不加会立刻红，这是特性不是回归。

- [ ] **Step 5: 写 CLI**（`backend/app/cli.py`）

```python
"""凭据运维面（规格 §8.6/§8.7）。口令只从环境变量读，绝不进 argv。"""

from __future__ import annotations

import argparse
import os
import sys

from app import auth, credentials_migration, directory, user_store

PASSWORD_ENV_VAR = "CREDENTIALS_PASSWORD"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    credentials_group = parser.add_subparsers(dest="command", required=True)
    actions = credentials_group.add_parser("credentials").add_subparsers(
        dest="action", required=True
    )
    bootstrap = actions.add_parser("bootstrap-admin")
    bootstrap.add_argument("--username", required=True)
    reset = actions.add_parser("reset")
    reset.add_argument("--username", required=True)
    actions.add_parser("migration-status")
    return parser


def _password_from_env() -> str:
    value = os.environ.get(PASSWORD_ENV_VAR, "")
    if len(value) < 12:
        raise SystemExit(f"{PASSWORD_ENV_VAR} 未设置或不满足 12 字符下限（口令不得出现在命令行参数上）")
    return value


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    user_store.ensure_user_credentials_schema()
    if args.action == "migration-status":
        status = credentials_migration.status()
        print(f"legacy_count={status.legacy_count} argon2id_count={status.argon2id_count}")
        for row in status.accounts:
            print(
                f"{row.username}\t{row.algorithm}\tv{row.credentials_version}"
                f"\tmust_change={int(row.must_change)}\tlocked={row.locked_until or '-'}"
            )
        return 0

    identity = directory.get_identity(args.username)
    if identity is None:
        # bootstrap 不创建身份：身份唯一真源是配置文件，CLI 顺手建号会造出第二个真源。
        print(f"身份不存在：{args.username}（请先写入 config/users.json）", file=sys.stderr)
        return 2
    reason = auth.validate_new_password(args.username, (os.environ.get(PASSWORD_ENV_VAR) or ""))
    if reason:
        print(reason, file=sys.stderr)
        return 2
    password = _password_from_env()
    must_change = args.action == "reset"
    version = auth.provision_credentials(
        args.username, plain_password=password, must_change=must_change
    )
    os.environ.pop(PASSWORD_ENV_VAR, None)
    auth.record_event(
        username=args.username,
        role=identity.role,
        action="PASSWORD",
        status="SUCCESS",
        detail="credential_bootstrap" if args.action == "bootstrap-admin" else "password_reset_by_admin",
    )
    print(f"{args.username}: algorithm={credentials.ALGORITHM_ARGON2ID} version={version}")
    return 0


if __name__ == "__main__":
    main()
```

`_password_from_env()` 在 `main()` 里被绕过的写法（`reason` 校验先读 env 再调 `_password_from_env`）不是笔误留给实现者：先校验长度上限以下的最短门槛、再取值，是为了让"env 没设"和"env 太短"给出同一句可执行提示，且不在错误分支里打印口令。若实现时觉得绕，改成"`_password_from_env` 内部做长度校验并 `SystemExit`"——但**不许**把口令写进异常消息或日志。

- [ ] **Step 6: 跑测试 + 手动过一遍 CLI**

```bash
cd /e/xiangmu/rag/backend
python -m pytest tests/test_password_lifecycle_contract.py -q
CONVERSATION_DB_PATH=/tmp/sec-a-cli.db CREDENTIALS_PASSWORD='an-operator-password 123' python -m app.cli credentials migration-status
```
Expected: 测试绿；CLI 打印 `legacy_count=0 argon2id_count=0`。

- [ ] **Step 7: 全套件 + 快照**

```bash
cd /e/xiangmu/rag/backend && python -m pytest -q
cp -r app ../.superpowers/sdd/SECURITY_A_PLAN/snap-task7-app
echo "- Ruling: 管理员重置端点对不存在身份保留 404「账号不存在」（已鉴权管理员面，非枚举面）。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
echo "- Ruling: CLI 口令只读 CREDENTIALS_PASSWORD，用完立即从 environ 弹出。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
```

---


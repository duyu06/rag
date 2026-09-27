## Task 6: 令牌生命周期（`cv` claim、revocation、`must_change` 端点覆盖门）

**Files:**
- Modify: `backend/app/auth.py`（`issue_token` 加 `cv`；`_user_from_token` 加比对与 `账号不存在` 并入）
- Modify: `backend/app/main.py`（`/api/auth/login` 与 `/api/auth/me` 各加一枚 additive 键）
- Modify: `backend/tests/test_authentication_leg_contract.py`（追加令牌面）
- Test: `backend/tests/test_password_lifecycle_contract.py`（新建，先放令牌撤销用例；Task 7 续写端点用例）

**Interfaces:**
- Consumes: `user_store.get_record`；`credentials.ALGORITHM_*`
- Produces:
  ```python
  CREDENTIAL_VERSION_CLAIM = "cv"
  def issue_token(user: CurrentUser) -> str           # payload 多一枚 cv
  def _user_from_token(authorization: str | None) -> CurrentUser   # 验签 → 身份 → 凭据 → cv
  ```
  响应面 additive 键：`POST /api/auth/login` 与 `GET /api/auth/me` 各多 `password_change_required: bool`。

- [ ] **Step 1: 写失败的测试**（`backend/tests/test_password_lifecycle_contract.py`）

```python
from __future__ import annotations

import hashlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import auth, credentials, directory, user_store  # noqa: E402
from app.main import app  # noqa: E402
from sec_a_seed import seed_demo_credentials  # noqa: E402


def _identity(username: str, *, role: str = "VIEWER", enabled: bool = True,
              feishu_open_id: str | None = None) -> directory.UserIdentity:
    return directory.UserIdentity(
        username=username, display_name=username.title(), role=role,
        enabled=enabled, feishu_open_id=feishu_open_id,
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_legacy_admin(store) -> None:
    store.import_legacy_digest(
        "admin", hashlib.sha256(b"admin123").hexdigest(), must_change=True
    )


class _ClientCase(unittest.TestCase):
    """打 HTTP 面的用例共用地基：TestClient + 已被会话 seed 过的凭据表。"""

    def setUp(self):
        self.client = TestClient(app)
        user_store.ensure_user_credentials_schema()
        seed_demo_credentials()

    def _admin_headers(self) -> dict[str, str]:
        login = self.client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123"}
        )
        return _bearer(login.json()["access_token"])


class TokenRevocationTests(_ClientCase):
    def setUp(self):
        self.client = TestClient(app)
        user_store.ensure_user_credentials_schema()
        user_store.create_argon2("revoker", plain_password="a-good-password 123456", must_change=False)
        self.identity = _identity("revoker")
        with auth.directory.override_identities({"revoker": self.identity}):
            self.token = auth.issue_token(auth._user_from(self.identity, None))

    def test_a_bumped_version_invalidates_the_previously_issued_token(self):
        """SECA-09：改密即废 token，不等 exp。"""
        with auth.directory.override_identities({"revoker": self.identity}):
            self.assertIsInstance(auth.require_user(f"Bearer {self.token}"), auth.CurrentUser)
            user_store.set_password_argon2(
                "revoker", plain_password="another-good-password 123", must_change=False
            )
            with self.assertRaises(HTTPException) as raised:
                auth.require_user(f"Bearer {self.token}")
        self.assertEqual(401, raised.exception.status_code)
        self.assertEqual("无效登录凭证", raised.exception.detail)

    def test_a_pre_seca_token_without_cv_is_rejected_not_allowed(self):
        """SECA-09b：这是 M17 的靶子——"兼容旧 token"的放行分支必须撞红。"""
        import jwt as pyjwt

        from app.config import settings

        legacy = pyjwt.encode(
            {"sub": "revoker", "role": "VIEWER", "iss": "yaoke",
             "exp": 2 ** 31 - 1, "iat": 1},
            settings.jwt_secret,
            algorithm="HS256",
        )
        with auth.directory.override_identities({"revoker": self.identity}):
            with self.assertRaises(HTTPException) as raised:
                auth.require_user(f"Bearer {legacy}")
        self.assertEqual(401, raised.exception.status_code)
        self.assertEqual("无效登录凭证", raised.exception.detail)

    def test_the_removed_account_specificity_message_is_gone_from_the_token_face(self):
        """§9.1：「账号不存在」并入「无效登录凭证」，不再泄露存在性。"""
        with auth.directory.override_identities({}):
            with self.assertRaises(HTTPException) as raised:
                auth.require_user(f"Bearer {self.token}")
        self.assertEqual("无效登录凭证", raised.exception.detail)


class LoginFaceKeyTests(unittest.TestCase):
    def test_login_and_me_carry_exactly_one_new_key(self):
        """规格 §11：本版唯一一处响应面键集合变化。"""
        response = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual({"access_token", "token_type", "user", "password_change_required"}, set(body))
        self.assertIsInstance(body["password_change_required"], bool)
        me = self.client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
        )
        self.assertIn("password_change_required", me.json())
        self.assertNotIn("grant", me.json())  # 既有脱敏事实不得被顶掉
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_password_lifecycle_contract.py -q
```
Expected: 红在 `KeyError/AttributeError`（`cv` 尚未签发、`password_change_required` 尚未出现）。

- [ ] **Step 3: 写实现**（`backend/app/auth.py`）

```python
CREDENTIAL_VERSION_CLAIM = "cv"


def issue_token(user: CurrentUser) -> str:
    now = datetime.now(timezone.utc)
    record = user_store.get_record(user.username)
    payload = {
        "sub": user.username,
        "name": user.display_name,
        "role": user.role,
        "access_role": user.access_role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_expire_hours)).timestamp()),
        "iss": "yaoke",
        CREDENTIAL_VERSION_CLAIM: int(record.credentials_version) if record else 0,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _user_from_token(authorization: str | None) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        payload = jwt.decode(
            authorization[7:].strip(), settings.jwt_secret,
            algorithms=["HS256"], issuer="yaoke",
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="无效登录凭证") from exc

    username = str(payload.get("sub", ""))
    identity = directory.get_identity(username)
    record = user_store.get_record(username)
    if identity is None or not identity.enabled or record is None:
        # 「账号不存在」并入通用文案（§9.1）：原 `auth.py:230` 的单列 detail 是一条存在性指纹。
        raise HTTPException(status_code=401, detail="无效登录凭证")
    # 读表判定，不信 claim 值；缺 claim 即视为不符（SECA-09b，禁止 None 放行）。
    claimed = payload.get(CREDENTIAL_VERSION_CLAIM)
    if not isinstance(claimed, int) or claimed != record.credentials_version:
        raise HTTPException(status_code=401, detail="无效登录凭证")
    return _user_from(identity, resolve_for_user(identity.username, identity.role, identity))
```

`require_user`（Task 5 定义）改为先 `_user_from_token` 再过 must_change 门；`require_user_pending_password` 只走 `_user_from_token`。`issue_token` 里 `record is None ⇒ cv=0` 不是"随便给个值"：0 与表内任何真实版本都不等，等于"这枚 token 一签发就死"，正是无凭据身份应有的行为，同时保持 `CurrentUser` 构造面不因身份类型分裂成两条路径。

- [ ] **Step 4: `main.py` 两处 additive 键**

登录响应：`"password_change_required": result.password_change_required`（来自 Task 5 的 `LoginResult`，**不**在响应处重新查表——两处判定早晚劈叉）；`/api/auth/me`：`{**user.model_dump(), "password_change_required": _password_change_required(user.username)}`。

- [ ] **Step 5: 补 `must_change` 端点覆盖枚举门**（SECA-10，追加到 `test_password_lifecycle_contract.py`）

```python
class MustChangeGateCoverageTests(unittest.TestCase):
    """门必须由路由表自证覆盖，不靠手写清单——新增端点忘了登记就直接红。"""

    # Task 6 时改密端点还不存在，白名单只有 /me 一项；Task 7 落地改密端点时必须
    # 同时把本集合扩成两项——这条断言会在漏扩时立刻红（多一条也红）。
    WHITELIST = {"GET /api/auth/me"}
    PARAM_SAMPLES = {
        "conversation_id": "conv-nonexistent",
        "message_id": "msg-nonexistent",
        "document_id": "doc-nonexistent",
        "kb_id": "kb_public",
        "knowledge_base_id": "kb_public",
        "run_id": "run-nonexistent",
        "trace_id": "trace-nonexistent",
        "job_id": "job-nonexistent",
    }

    def test_every_authenticated_route_is_gated_or_whitelisted(self):
        authenticated = _routes_using(auth.require_user) | _routes_using(auth.require_permission)
        pending = _routes_using(auth.require_user_pending_password)
        self.assertEqual(self.WHITELIST, pending)
        unattended = {
            key for key in authenticated - pending
            if not self._gated(key)
        }
        self.assertEqual(set(), unattended)

    def _gated(self, route_key: str) -> bool:
        client = TestClient(app)
        user_store.ensure_user_credentials_schema()
        user_store.create_argon2("gated", plain_password="a-good-password 123456", must_change=True)
        identity = _identity("gated", role="ADMIN")
        with auth.directory.override_identities({"gated": identity}):
            token = auth.issue_token(auth._user_from(identity, None))
            method, path = route_key.split(" ", 1)
            url = path
            for name, sample in self.PARAM_SAMPLES.items():
                url = url.replace("{" + name + "}", sample)
            if "{" in url:
                self.fail(f"新增端点带未登记的 path 参数，请把样例加进 PARAM_SAMPLES：{route_key}")
            response = client.request(method, url, headers={"Authorization": f"Bearer {token}"})
        return (
            response.status_code == 403
            and response.json().get("detail") == "当前账号需先修改口令"
        )
```

```python
def _route_key(route) -> str:
    methods = getattr(route, "methods", set()) or set()
    return f"{sorted(methods & {'GET', 'POST', 'PUT', 'DELETE'})[0]} {route.path}"


def _uses_dependency(dependant, target) -> bool:
    for sub in dependant.dependencies:
        if sub.call is target or _uses_dependency(sub, target):
            return True
    return False


def _routes_using(target) -> set[str]:
    """递归遍历 FastAPI 依赖树，返回"这条路由经过该依赖"的端点集合。"""
    from fastapi.routing import APIRoute

    hits: set[str] = set()
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None or not isinstance(route, APIRoute):
            continue
        if _uses_dependency(dependant, target):
            hits.add(_route_key(route))
    return hits
```

判定形状：**漏一条即红，多一条也红**。命中不到任何依赖的路由（`/api/health`、`/api/ready`、静态资源）天然不进 authenticated 集合，所以不需要维护豁免清单；`PARAM_SAMPLES` 未登记的 path 参数用 `self.fail(...)` 主动要求登记，而不是猜一个值过去。这条测试会在未来任何人新增端点时自动扩大覆盖面，而不是等下一次评审手工数。

- [ ] **Step 6: 定向门 + 快照**

```bash
cd /e/xiangmu/rag/backend
python -m pytest tests/test_password_lifecycle_contract.py tests/test_authentication_leg_contract.py tests/test_typesafe_api_runtime.py tests/test_rbac_contract.py -q
python -m pytest -q
cp -r app ../.superpowers/sdd/SECURITY_A_PLAN/snap-task6-app
echo "- Ruling: issue_token 在无凭据行时签 cv=0（一签发即死），不另开第二条构造路径。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
echo "- Ruling: must_change 门覆盖面由路由表枚举生成；新端点带未登记 path 参数时用例主动 fail 并要求登记样例。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
```
Expected: 两条 `python -m pytest` 全绿，且 `test_typesafe_api_runtime.py` 的 `/api/query` 键集合钉未受影响。

---


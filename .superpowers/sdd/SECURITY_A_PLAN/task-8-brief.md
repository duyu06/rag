## Task 8: 两层节流与容量护栏（`login_throttle.py` + 429 / 503）

**Files:**
- Create: `backend/app/login_throttle.py`
- Modify: `backend/app/auth.py`（`_locked` 迁出；登录腿接入 pre-hash 节流与容量翻译）
- Modify: `backend/app/main.py`（把 `PasswordCapacityError` 翻成 503、节流命中翻成 429）
- Modify: `backend/app/config.py`（四枚运维参数）
- Test: `backend/tests/test_authentication_leg_contract.py`（追加节流面）

**Interfaces:**
- Consumes: `credentials.argon2_slot` / `PasswordCapacityError`；`user_store.record_login_failure` / `clear_login_failures`
- Produces:
  ```python
  # app/login_throttle.py
  def client_ip_of(request) -> str                       # 只认 request.client.host
  def throttle_bucket(username: str, client_ip: str) -> str
  class PreHashThrottle:
      def allow(self, bucket: str, *, now: float | None = None) -> bool
      def reset(self) -> None
  pre_hash_throttle: PreHashThrottle                     # 进程内单例
  def is_locked(locked_until: str | None, *, now: datetime | None = None) -> bool
  ```

- [ ] **Step 1: 写失败的测试**（追加 `ThrottleLayerTests`）

```python
class ThrottleLayerTests(unittest.TestCase):
    def setUp(self):
        _fresh_db(self)
        user_store.create_argon2("admin", plain_password="a-good-password 123456", must_change=False)
        self.throttle = login_throttle.PreHashThrottle(window_seconds=60, max_attempts=3)

    def test_expensive_work_is_skipped_once_the_bucket_is_exhausted(self):
        """SECA-15：闸门在 Argon2 之前，否则认证面自己就是 DoS 面。"""
        bucket = login_throttle.throttle_bucket("admin", "10.0.0.9")
        for _ in range(3):
            self.assertTrue(self.throttle.allow(bucket))
        self.assertFalse(self.throttle.allow(bucket))
        with mock.patch.object(auth, "pre_hash_throttle", self.throttle):
            with mock.patch.object(credentials.hasher(), "verify") as verify:
                with self.assertRaises(auth.LoginThrottledError):
                    auth.authenticate_with_result("admin", "a-good-password 123456")
        verify.assert_not_called()

    def test_two_source_addresses_on_the_same_username_have_independent_buckets(self):
        """SECA-16a：M6（throttle 键去掉 ip）只能被这条直接断言杀掉。"""
        first = login_throttle.throttle_bucket("admin", "10.0.0.1")
        second = login_throttle.throttle_bucket("admin", "10.0.0.2")
        self.assertNotEqual(first, second)
        for _ in range(3):
            self.throttle.allow(first)
        self.assertFalse(self.throttle.allow(first))
        self.assertTrue(self.throttle.allow(second))

    def test_many_source_addresses_on_one_username_share_the_account_lock(self):
        """SECA-16b：账号级持久计数按 username，与 throttle 层正交。"""
        for ip in ("10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"):
            result = auth.authenticate_with_result("admin", "wrong-password 123456")
            self.assertIsNone(result.user)
        record = user_store.get_record("admin")
        self.assertGreaterEqual(record.failed_attempts, 4)
        self.assertIsNotNone(record.locked_until)
        self.assertFalse(login_throttle.is_locked(None))
        self.assertTrue(login_throttle.is_locked(record.locked_until))

    def test_a_successful_login_clears_the_persistent_counter(self):
        user_store.record_login_failure("admin", max_attempts=9, lock_seconds=900)
        self.assertTrue(auth.authenticate_with_result("admin", "a-good-password 123456").user)
        record = user_store.get_record("admin")
        self.assertEqual(0, record.failed_attempts)
        self.assertIsNone(record.locked_until)

    def test_the_capacity_gate_surfaces_as_a_capacity_error_not_a_denial(self):
        """503 ≠ 401：可用性事实不能被伪装成凭据结论。"""
        with mock.patch.object(
            credentials, "_SLOTS", threading.BoundedSemaphore(0)
        ):
            user_store.import_legacy_digest("gate", LEGACY_ADMIN, must_change=True)
            with self.assertRaises(credentials.PasswordCapacityError):
                auth.authenticate_with_result("gate", "admin123")


class LockedHttpFaceTests(unittest.TestCase):
    """M5 的靶子：锁定原因一旦渗到 HTTP 面，就是账号存在性枚举面（SECA-14 的 HTTP 半边）。"""

    def setUp(self):
        _fresh_db(self)
        user_store.create_argon2("admin", plain_password="a-good-password 123456", must_change=False)
        self.client = TestClient(app)

    def _login(self, username: str, password: str):
        return self.client.post("/api/auth/login", json={"username": username, "password": password})

    def test_locked_wrong_password_and_unknown_account_are_the_same_http_face(self):
        for _ in range(settings.account_max_failed_attempts):
            self._login("admin", "definitely-wrong 123456")
        locked = self._login("admin", "a-good-password 123456")   # 口令对，但账号已锁
        wrong = self._login("admin", "still-wrong 123456")
        unknown = self._login("nosuchaccount", "still-wrong 123456")
        faces = {(r.status_code, json.dumps(r.json(), sort_keys=True)) for r in (locked, wrong, unknown)}
        self.assertEqual(1, len(faces), faces)
        self.assertEqual(401, locked.status_code)
        self.assertNotIn("锁", json.dumps(locked.json(), ensure_ascii=False))

    def test_the_lock_reason_reaches_the_audit_face_only(self):
        for _ in range(settings.account_max_failed_attempts):
            self._login("admin", "definitely-wrong 123456")
        self._login("admin", "a-good-password 123456")
        from app.audit import recent_events

        details = [event["detail"] for event in recent_events(limit=3)]
        self.assertIn("AUTH_LOGIN_LOCKED", details)
```

`test_authentication_leg_contract.py` 的 import 段需要补 `import json`、`import threading` 与 `from fastapi.testclient import TestClient`、`from app.config import settings`（Task 8 起才用得到）。M5 之所以能被抓，全靠 `LockedHttpFaceTests` 这一条——腿级用例看不见 `main.py` 的文案分叉。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_authentication_leg_contract.py -q -k ThrottleLayer
```
Expected: `ModuleNotFoundError: No module named 'app.login_throttle'`。

- [ ] **Step 3: 写实现**（`backend/app/login_throttle.py`）

```python
"""pre-hash 节流（规格 §7.1/§7.2 的第一层）。

进程内、按 (username, client_ip) 分桶，只回答一件事：这次请求配不配消耗一次
内存硬哈希。账号级持久锁定是 user_store 的 failed_attempts/locked_until，两层
键不同、职责不同，合并成一枚必然丢掉两种保护之一。
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone


def client_ip_of(request) -> str:
    # 不信任 X-Forwarded-For：当前 compose 前置无 nginx，信任转发头等于白送伪装源。
    client = getattr(request, "client", None)
    return str(getattr(client, "host", "") or "unknown")


def throttle_bucket(username: str, client_ip: str) -> str:
    return f"{str(username).casefold()}|{client_ip}"


class LoginThrottled(Exception):
    """节流命中。调用方翻成 429，不是 401（还没做凭据判断）。"""


class PreHashThrottle:
    def __init__(self, *, window_seconds: int, max_attempts: int) -> None:
        self._window = float(window_seconds)
        self._max = int(max_attempts)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, bucket: str, *, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            hits = self._hits[bucket]
            while hits and moment - hits[0] > self._window:
                hits.popleft()
            if len(hits) >= self._max:
                return False
            hits.append(moment)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def is_locked(locked_until: str | None, *, now: datetime | None = None) -> bool:
    if not locked_until:
        return False
    try:
        moment = datetime.fromisoformat(str(locked_until))
    except ValueError:
        return True  # 时间戳坏了 ⇒ 宁可当锁定，也不白送一次昂贵运算
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) >= moment


pre_hash_throttle: PreHashThrottle | None = None


def configured_throttle() -> PreHashThrottle:
    global pre_hash_throttle
    from app.config import settings

    if pre_hash_throttle is None:
        pre_hash_throttle = PreHashThrottle(
            window_seconds=settings.login_throttle_window_seconds,
            max_attempts=settings.login_throttle_max_attempts,
        )
    return pre_hash_throttle
```

`config.py` 再补两枚**节流级**参数（另两枚账号级的已在 Task 5 落地；四枚都是可用性旋钮，**不含** m/t/p）：

```python
    login_throttle_window_seconds: int = 60
    login_throttle_max_attempts: int = 10
```

- [ ] **Step 4: 接进登录腿**（`backend/app/auth.py`）

在 `authenticate_with_result` 最前面加：

```python
class LoginThrottledError(RuntimeError):
    """配翻译；不是凭据结论（main.py 翻成 429）。"""


def authenticate_with_result(username: str, password: str, *, client_ip: str = "") -> LoginResult:
    bucket = login_throttle.throttle_bucket(username, client_ip)
    if not login_throttle.configured_throttle().allow(bucket):
        raise LoginThrottledError(bucket)
    ...  # 其余保持 Task 5 的顺序；_locked(...) 换成 login_throttle.is_locked(record.locked_until)
```

`main.py`：登录端点传 `client_ip=login_throttle.client_ip_of(request)`（因此需要 `request: Request` 形参），并把 `LoginThrottledError → 429`、`PasswordCapacityError → 503` 各加一枚 `except`；两条 detail 文案都不得提到账号是否存在。

- [ ] **Step 5: 跑测试 + 全套件 + 快照**

```bash
cd /e/xiangmu/rag/backend
python -m pytest tests/test_authentication_leg_contract.py -q
python -m pytest -q
cp -r app ../.superpowers/sdd/SECURITY_A_PLAN/snap-task8-app
echo "- Ruling: 429（节流）与 503（容量）都在身份查找之前判定，因此不构成账号存在性枚举面。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
```

---


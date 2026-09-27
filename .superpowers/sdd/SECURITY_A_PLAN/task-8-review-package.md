# Task 8 review package (base = snap-task8-pre-app / snap-task8-pre-*)
## stat
Files .superpowers/sdd/SECURITY_A_PLAN/snap-task8-pre-app/auth.py and backend/app/auth.py differ
Files .superpowers/sdd/SECURITY_A_PLAN/snap-task8-pre-app/config.py and backend/app/config.py differ
Only in backend/app: login_throttle.py
Files .superpowers/sdd/SECURITY_A_PLAN/snap-task8-pre-app/main.py and backend/app/main.py differ
## app diff
diff -ruN -U12 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task8-pre-app/auth.py backend/app/auth.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task8-pre-app/auth.py	2026-09-26 09:52:28.766888200 +0800
+++ backend/app/auth.py	2026-09-26 10:21:28.996470400 +0800
@@ -1,27 +1,28 @@
 from __future__ import annotations
 
 from dataclasses import dataclass
 from datetime import datetime, timedelta, timezone
 from typing import Annotated, Callable, Literal
 
 import jwt
 from fastapi import Depends, Header, HTTPException
 from pydantic import BaseModel, Field, computed_field
 
-from app import credentials, directory, user_store
+from app import credentials, directory, login_throttle, user_store
 from app.audit import record_event as _record_event
 from app.config import settings
 from app.identity import resolve_for_user
 from app.identity.base import FeishuGrant
+from app.login_throttle import LoginThrottledError, pre_hash_throttle
 
 Role = Literal["ADMIN", "SALES", "HR", "USER", "VIEWER"]
 AccessRole = Literal["admin", "user", "viewer"]
 Permission = Literal[
     "knowledge:read",
     "knowledge:query",
     "knowledge:manage",
     "conversation:read",
     "conversation:write",
     "agent:run",
     "trace:read",
     "trace:read:any",
@@ -188,39 +189,52 @@
 
 
 # ---------------------------------------------------------------------------
 # 登录腿（规格 §7.1 的顺序即契约）
 #
 # 身份读 `directory`、凭据状态读 `user_store`、口令运算只在 `credentials`——三处各自有
 # 唯一真源（SEC-A-010），这一层只是把它们按 §7.1 串起来，不在这里存任何用户材料。
 # ---------------------------------------------------------------------------
 
 #: 登录面 `detail` 的**全部**合法取值（§9.1 末段：自由文本不得进入该字段）。
 #: 成功面是空串——`main.py` 只在非空时叫 `record_login_event`，成功事件继续走既有
 #: `_audit(user, "LOGIN")`，那是 SEC-A-006 不许动的既有面。
+#: 最后两枚是**可用性**事实（节流命中 / 容量溢出），不是凭据结论；它们之所以仍从这同一个
+#: 出口走，是因为审计值域只该有一处真源——多开一个"可用性专用" writer 就等于允许自由文本。
 AUDIT_INVALID_CREDENTIALS = "invalid_credentials"
 AUDIT_LOGIN_LOCKED = "AUTH_LOGIN_LOCKED"
 AUDIT_REHASH_DEGRADED = "AUTH_REHASH_DEGRADED"
+AUDIT_LOGIN_THROTTLED = "login_throttled"
+AUDIT_PASSWORD_CAPACITY = "password_capacity"
+
+#: §9.1 展示面里 429 / 503 那两行的中文文案。与 `用户名或密码错误` 同一条纪律：**不提账号**
+#: ——两格都是在身份查找之前判出来的，文案一旦说"该账号被限制"，可用性的事实就变成了
+#: 存在性的证据。住在这一层（而不是 `main.py` 的字面量里）是因为它就是登录腿契约的一部分，
+#: 契约测试与 HTTP 面读的是同一枚常量。
+COPY_LOGIN_THROTTLED = "登录尝试过于频繁，请稍后重试"
+COPY_PASSWORD_CAPACITY = "服务繁忙，请稍后重试"
 
 #: 策略拒绝（422）的审计 token（§9.1 表）。改密 / 管理员重置 / CLI 三条腿共用这一枚常量，
 #: 而不是各抄一遍字符串——抄三处就有第四处会漏。它是 `PASSWORD` 动作下的 DENIED 事件，
 #: 与登录枚举 `LOGIN_AUDIT_DETAILS` 不是一族（后者由 `record_login_event` 单独把关）。
 AUDIT_PASSWORD_POLICY_REJECTED = "password_policy_rejected"
 
-#: 上面三枚的**值域容器**：`record_login_event` 用它自己判成员，而不是靠调用方各抄一遍
+#: 上面五枚的**值域容器**：`record_login_event` 用它自己判成员，而不是靠调用方各抄一遍
 #: 字符串——抄一次就多一处会漏的复制品，而这条枚举的存在意义正是"审计字段里只有这几枚"。
 LOGIN_AUDIT_DETAILS: tuple[str, ...] = (
     AUDIT_INVALID_CREDENTIALS,
     AUDIT_LOGIN_LOCKED,
     AUDIT_REHASH_DEGRADED,
+    AUDIT_LOGIN_THROTTLED,
+    AUDIT_PASSWORD_CAPACITY,
 )
 
 
 @dataclass(frozen=True)
 class LoginResult:
     """登录腿的完整结论。HTTP 面（`main.py`）与契约测试读的是同一份，不分两条腿。"""
 
     user: CurrentUser | None
     audit_detail: str
     password_change_required: bool
 
 
@@ -236,67 +250,58 @@
         return
     if detail not in LOGIN_AUDIT_DETAILS:
         raise ValueError("登录审计 detail 不在枚举值域内")
     _record_event(
         username=username or "unknown",
         role="UNKNOWN",
         action="LOGIN",
         status="SUCCESS" if detail == AUDIT_REHASH_DEGRADED else "DENIED",
         detail=detail,
     )
 
 
-def _locked(record: user_store.CredentialRecord) -> bool:
-    """账号此刻是否处于锁定期：`locked_until` 是**锁到的那个时刻**，还没到就是锁着。
-
-    方向别写反：`record_login_failure` 写进去的是 `now + lock_seconds`（未来），所以
-    "还锁着" 对应 `until > now`。写反的症状是"永远锁不住"——阈值一到就把它当成过期，
-    下一次口令猜测照旧跑一次 Argon2，§7.2 第二层直接失效（本模块的用例钉住这个方向）。
-    """
-    until = record.locked_until
-    if not until:
-        return False
-    try:
-        return datetime.fromisoformat(until) > datetime.now(timezone.utc)
-    except (ValueError, TypeError):
-        # 时间戳坏了 ⇒ 宁可当锁定，也不给一次免费的 Argon2 运算。两种坏法都归这一臂：
-        # 压根解析不出（ValueError），和**解析得出但没有偏移**（naive datetime 与 aware 的
-        # now 一比就是 TypeError）。后一条不是假想：运维手改、从另一个写入方恢复来的备份、
-        # SQLite 的 `CURRENT_TIMESTAMP` 惯用法都会给出 `2099-01-01 00:00:00` 这种能解析却
-        # 无时区的值——它同样属于"这一行不再可信"，而不是"这一行说没锁"。
-        return True
-
-
 def _user_from(identity: directory.UserIdentity, grant: FeishuGrant | None) -> CurrentUser:
     """`CurrentUser` 的唯一构造点。登录腿与令牌腿共用，避免两处的 grant 语义劈叉。"""
     return CurrentUser(
         username=identity.username,
         display_name=identity.display_name,
         role=identity.role,
         grant=grant,
     )
 
 
-def authenticate_with_result(username: str, password: str) -> LoginResult:
+def authenticate_with_result(
+    username: str, password: str, *, client_ip: str = ""
+) -> LoginResult:
+    # §7.1 步骤 0：闸门在任何身份查找、任何口令运算**之前**。它判的是"这次请求配不配消耗
+    # 一次内存硬运算"，答案只来自 (归一化账号, 来源地址) 这一对客户端自己给出的事实，因此
+    # 命中即抛也不构成存在性证据。键里两枚都算：去掉 client_ip ⇒ 换 IP 绕过第一层；
+    # 把 client_ip 也塞进账号锁定键 ⇒ 分布式猜测一人一份计数，第二层永不触发。
+    # `client_ip` 默认空串是给 CLI 与既有调用方的（它们没有 HTTP 请求可问）；那一格与
+    # `main.py` 传来的真实地址落在**不同**的桶里，两条腿互不清零。
+    bucket = login_throttle.throttle_bucket(username, client_ip)
+    if not pre_hash_throttle.allow(bucket):
+        raise LoginThrottledError(bucket)
     identity = directory.get_identity(username)
     record = user_store.get_record(username)
     # 未知账号 / 已停用 / 有身份无凭据：三态共用一条恒定成本路径（§7.3）。停用账号在此
     # 归入"无可校验凭据"，既不是第四态，也不去看它那一行凭据——`enabled=false` 因此
     # 在响应面上完全不可见（名册那一面另有它自己的口径，两处读的都是同一个字段）。
     if identity is None or not identity.enabled or record is None:
         credentials.verify_dummy(password)
         return LoginResult(None, AUDIT_INVALID_CREDENTIALS, False)
 
-    if _locked(record):
-        # 不跑 Argon2：锁定路径显式排除在 timing 承诺之外（§7.4）。
+    if login_throttle.is_locked(record.locked_until):
+        # 不跑 Argon2：锁定路径显式排除在 timing 承诺之外（§7.4）。判定住在
+        # `login_throttle.is_locked`——两层节流与锁定共读同一个谓词，这里不留第二份实现。
         return LoginResult(None, AUDIT_LOGIN_LOCKED, False)
 
     outcome = credentials.verify_password(
         password, algorithm=record.algorithm, encoded=record.password_hash
     )
     if not outcome.ok:
         # 第四态（口令错）在 algorithm 列上有两种形态，成本天然不等：argon2 行走真 verify，
         # legacy 行只走一次 `hmac.compare_digest`。不补一次同档运算，收敛窗口里就有两件事
         # 同时成立——猜错未升级账号的口令几乎免费，且响应时间本身指纹出"这个账号还没升级"，
         # 而那正是 §7.3 要关上的那张枚举面（账号级失败计数只滞后拦，拦不住时间差）。
         if record.algorithm == credentials.ALGORITHM_LEGACY_SHA256:
             credentials.verify_dummy(password)
@@ -327,31 +332,34 @@
         if forced and not wrote:
             # 写盘失败 = 收敛延迟，不是安全放行：人已经进来了，legacy 行留着等下一次登录，
             # 但这条事实必须以 token 出现（SECA-21）。
             detail = AUDIT_REHASH_DEGRADED
 
     return LoginResult(
         _user_from(identity, resolve_for_user(identity.username, identity.role, identity)),
         detail,
         must_change,
     )
 
 
-def authenticate(username: str, password: str) -> CurrentUser | None:
+def authenticate(
+    username: str, password: str, *, client_ip: str = ""
+) -> CurrentUser | None:
     """既有契约：仍然只回答"这个口令能不能换到一个会话主体"。
 
     HTTP 面要的是 `LoginResult`（审计 token 与门状态），这里保留 `user | None` 是给
     CLI 与既有调用方——两条腿走的是同一个 `authenticate_with_result`，不存在第二套判定。
+    `client_ip` 与上面同一条理由：不传就是 CLI 那一格，不与 HTTP 面的桶互相清零。
     """
-    return authenticate_with_result(username, password).user
+    return authenticate_with_result(username, password, client_ip=client_ip).user
 
 
 #: 令牌生命周期 claim 的名字（§7.5）。签发与鉴权两侧都从这里取值：字面量抄两遍就是
 #: 留给"两侧拼写劈叉"的那条缝，而真劈了的症状是每次请求都 401「无效登录凭证」，
 #: 排查方向会被带到口令上而不是 claim 名上。
 CREDENTIAL_VERSION_CLAIM = "cv"
 
 
 def issue_token(user: CurrentUser) -> str:
     now = datetime.now(timezone.utc)
     record = user_store.get_record(user.username)
     payload = {
diff -ruN -U12 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task8-pre-app/config.py backend/app/config.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task8-pre-app/config.py	2026-09-26 09:52:28.914601700 +0800
+++ backend/app/config.py	2026-09-26 09:57:12.510866600 +0800
@@ -158,24 +158,30 @@
 
     jwt_secret: str = "change-me-before-production-yaoke-demo-secret"
     jwt_expire_hours: int = 8
 
     # Argon2 并发槽上限（可用性旋钮）。**密码学档位不在这里**：m/t/p 固定在
     # app/credentials.py 的常量上，改它等于改规格（SEC-A-008）。
     argon2_max_concurrent_ops: int = 2
 
     # 账号级持久锁定（规格 §7.2 第二层）：键只有 username，跨来源共享同一失败状态。
     account_max_failed_attempts: int = 5
     account_lock_seconds: int = 900
 
+    # pre-hash 节流（规格 §7.2 第一层）：键是 (username, client_ip)，进程内、重启即清。
+    # 它挡的是"认证面自己被当成 DoS 面"，与上面的账号锁定正交；两枚都是可用性旋钮，
+    # 依旧**不含** m/t/p —— 能运维调的安全强度等于没有强度（SEC-A-008）。
+    login_throttle_window_seconds: int = 60
+    login_throttle_max_attempts: int = 10
+
     # Local backend cwd is normally ./backend, so ../demo-data points to repo demo data.
     # Docker overrides this to /app/demo-data via docker-compose.
     demo_data_dir: str = "../demo-data"
 
     # Feishu permission bridge (see docs/FEISHU_PERMISSION_BRIDGE_DESIGN.md).
     # Disabled by default: every behaviour stays exactly like the demo accounts.
     feishu_permissions_enabled: bool = False
     feishu_app_id: str = ""
     feishu_app_secret: SecretStr = SecretStr("")
     feishu_base_url: str = "https://open.feishu.cn"
     feishu_timeout_seconds: float = Field(default=3.0, ge=0.5, le=30.0)
     feishu_cache_ttl_seconds: int = Field(default=900, ge=30, le=86400)
diff -ruN -U12 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task8-pre-app/login_throttle.py backend/app/login_throttle.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task8-pre-app/login_throttle.py	1970-01-01 08:00:00.000000000 +0800
+++ backend/app/login_throttle.py	2026-09-26 10:19:28.558540700 +0800
@@ -0,0 +1,126 @@
+"""pre-hash 节流（规格 §7.1 步骤 0 / §7.2 第一层）与锁定判定的唯一真源。
+
+两层键不同、职责不同，合并成一枚必然丢掉两种保护之一：
+
+- 本模块的桶是**进程内**的，按 `(归一化 username, client_ip)` 分，重启即清。它回答的
+  唯一问题是"这次请求配不配消耗一次内存硬运算"，所以判定必须排在任何身份查找之前——
+  闸门排在运算之后，认证面自己就成了 DoS 面。
+- `user_store` 的 `failed_attempts`/`locked_until` 是**落库**的，只按 username 分，跨重启、
+  跨来源地址共享。第一层少一枚 `client_ip` 键 ⇒ 换个来源地址即可绕过节流；给第二层也
+  加上 `client_ip` ⇒ 分布式猜测一人一份计数，锁定永不触发。两枚键都必须有直接断言。
+
+本模块不做 sleep：§7.4 的收敛靠"锁定路径不跑 Argon2"，人工延迟本身是攻击面。
+"""
+
+from __future__ import annotations
+
+import threading
+import time
+from collections import defaultdict, deque
+from datetime import datetime, timezone
+
+from app.config import settings
+
+
+def client_ip_of(request) -> str:
+    """本次请求的**可信**来源地址。
+
+    只认 `request.client.host`，**不读** `X-Forwarded-For`：当前部署形态里 compose 直接
+    把 8001 映射出去、前面没有反代，于是那个头是客户端自述的字符串。信任它等于把
+    节流键交给攻击者挑——换一枚伪造头就是一个新桶，第一层当场归零。将来真要前置 nginx，
+    改的是这里（并且必须同时约束跳数），而不是调用方。
+    """
+    client = getattr(request, "client", None)
+    return str(getattr(client, "host", "") or "unknown")
+
+
+def throttle_bucket(username: str, client_ip: str) -> str:
+    """节流键：归一化的账号名 + 来源地址。两枚都参与，缺一层的保护就少一半。"""
+    return f"{str(username).casefold()}|{client_ip}"
+
+
+class LoginThrottledError(RuntimeError):
+    """节流命中。它**不是**凭据结论：还没做身份查找、还没碰口令，所以 HTTP 面是 429 不是 401。
+
+    住在这一层而不是 `auth`，因为判定与异常同源；`auth` 与 `main` 都 import 同一个类，
+    两枚同义异常早晚出现"catch 错那一枚"的缝。
+    """
+
+
+class PreHashThrottle:
+    """固定窗口内的滑动计数（每桶一个单调时钟时间戳队列）。"""
+
+    def __init__(self, *, window_seconds: int, max_attempts: int) -> None:
+        self._window = float(window_seconds)
+        self._max = int(max_attempts)
+        self._hits: dict[str, deque[float]] = defaultdict(deque)
+        self._lock = threading.Lock()
+        self._last_sweep = time.monotonic()
+
+    def allow(self, bucket: str, *, now: float | None = None) -> bool:
+        moment = time.monotonic() if now is None else float(now)
+        with self._lock:
+            self._sweep_stale(moment)
+            hits = self._hits[bucket]
+            while hits and moment - hits[0] > self._window:
+                hits.popleft()
+            if len(hits) >= self._max:
+                return False
+            hits.append(moment)
+            return True
+
+    def _sweep_stale(self, moment: float) -> None:
+        """整表回收，每个窗口至多一次；调用方持锁。
+
+        单桶判据（`allow` 里那条）只清空**被再次命中**的桶：来源地址打不停时，桶的个数
+        就是攻击者的请求数，节流表自己会长成一条内存增长面。这里按"最近一次命中已出窗"
+        整片丢弃，语义与逐桶剪枝完全一致（丢掉的桶再命中一次也会重新计入），只是把上限
+        从'见过的地址数'收到'一个窗口内在场的地址数'。
+        """
+        if moment - self._last_sweep <= self._window:
+            return
+        self._last_sweep = moment
+        for key in [k for k, dq in self._hits.items() if not dq or moment - dq[-1] > self._window]:
+            self._hits.pop(key, None)
+
+    def reset(self) -> None:
+        with self._lock:
+            self._hits.clear()
+            self._last_sweep = time.monotonic()
+
+
+def is_locked(locked_until: str | None, *, now: datetime | None = None) -> bool:
+    """账号此刻是否处于锁定期：`locked_until` 是**锁到的那个时刻**，还没到就是锁着。
+
+    方向别写反：`record_login_failure` 写进去的是 `now + lock_seconds`（未来），所以"还锁着"
+    对应 `until > now`。写反的症状是"永远锁不住"——阈值一到就把它当成过期，下一次口令猜测
+    照旧跑一次 Argon2，§7.2 第二层直接失效。
+
+    坏值一律 fail closed 当锁定，两种坏法同臂：压根解析不出（ValueError），以及**解析得出
+    但没有偏移**（naive）。后者不是假想——运维手改、从另一个写入方恢复来的备份、SQLite 的
+    `CURRENT_TIMESTAMP` 惯用法都会给出 `2099-01-01 00:00:00` 这种能解析却无时区的值。
+    这里**不**替它补 UTC：猜出来的偏移会把一行不再可信的数据读成"这一行说没锁"，
+    而白送一次昂贵运算正是这条门要挡的事。
+    """
+    if not locked_until:
+        return False
+    try:
+        moment = datetime.fromisoformat(str(locked_until))
+    except (ValueError, TypeError):
+        return True
+    if moment.tzinfo is None:
+        return True
+    return moment > (now or datetime.now(timezone.utc))
+
+
+#: 进程内单例。窗口与阈值都是**可用性旋钮**（`login_throttle_*`），不含 m/t/p：
+#: 口令强度固定在 `credentials` 的常量上，不可在运行时调（SEC-A-008）。
+pre_hash_throttle = PreHashThrottle(
+    window_seconds=settings.login_throttle_window_seconds,
+    max_attempts=settings.login_throttle_max_attempts,
+)
+
+
+def configured_throttle() -> PreHashThrottle:
+    """单例的读取点。构造在 import 期完成，与 `credentials._SLOTS` 同一口径。"""
+    return pre_hash_throttle
diff -ruN -U12 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task8-pre-app/main.py backend/app/main.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task8-pre-app/main.py	2026-09-26 09:52:28.909080700 +0800
+++ backend/app/main.py	2026-09-26 10:23:37.420264000 +0800
@@ -10,52 +10,58 @@
 from pathlib import Path
 from typing import Any, Literal
 
 from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
 from fastapi.exception_handlers import request_validation_exception_handler
 from fastapi.exceptions import RequestValidationError
 from fastapi.middleware.cors import CORSMiddleware
 from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
 from pydantic import BaseModel, Field
 
 from app.audit import recent_events, record_event, today_summary
 from app.auth import (
+    AUDIT_LOGIN_THROTTLED,
+    AUDIT_PASSWORD_CAPACITY,
     AUDIT_PASSWORD_POLICY_REJECTED,
+    COPY_LOGIN_THROTTLED,
+    COPY_PASSWORD_CAPACITY,
     CurrentUser,
     _MAX_PASSWORD_LENGTH,
     _password_change_required,
     authenticate_with_result,
     has_permission,
     issue_token,
     provision_credentials,
     record_login_event,
     require_permission,
     require_user_pending_password,
     validate_new_password,
 )
 from app.config import settings
+from app.credentials import PasswordCapacityError
 from app.demo import demo_status, initialize_demo, reset_demo
 from app.directory import get_identity as get_user_identity
 from app.identity import warmup as warmup_identity_permissions
 from app.ingestion import DOC_DIR, SUPPORTED_SUFFIXES, document_path
 from app.knowledge import get_base, resolve_for, visible_for
 from app.knowledge_os import (
     is_document_excluded,
     persist_eval_run,
     registry_entry,
     registry_remove,
     run_ingest_job,
 )
 from app.llm.health import probe_llm
 from app.llm.usage import warmup as warmup_llm_router
+from app.login_throttle import LoginThrottledError, client_ip_of
 from app.rag import MODEL_USED_KEY, current_model_name, generate_answer
 from app.retrieval import retrieval_service
 from app.security import (
     public_exception_detail,
     public_typesafe_metrics,
     redact_secrets,
     redact_text,
 )
 from app.store import vector_store
 from app.user_store import CredentialStoreError
 
 
@@ -280,28 +286,52 @@
     provider = "openai-compatible" if settings.openai_api_key else "ollama"
     return {
         "status": "healthy" if (qdrant_ok and llm_ok) else "degraded",
         "vector_db_connected": qdrant_ok,
         "llm_connected": llm_ok,
         "llm_detail": llm_detail,
         "ollama_connected": llm_ok if provider == "ollama" else False,
         "llm_provider": provider,
         "llm_model": current_model_name(),
     }
 
 
+def _auth_availability_denial(username: str, exc: Exception) -> HTTPException:
+    """把两格**可用性**事实翻成 HTTPException：429（pre-hash 节流命中）/ 503（Argon2 槽溢出）。
+
+    两格都不是凭据结论：判定发生在身份查找与昂贵运算的两侧，客户端材料一个都没被读过，
+    所以响应面只说"现在不行"，绝不提账号存在与否——那才会把可用性事实变成存在性证据。
+    审计走 `record_login_event` 那唯一的出口（token 已在 `LOGIN_AUDIT_DETAILS` 里），
+    不在这里另开 writer。异常识别按类型、不按消息，且**只**认这两枚：别的异常一律原样上抛，
+    免得多年以后有人往这条 try 里塞进一枚凭据异常而它被静默翻成 503。
+    """
+    if isinstance(exc, LoginThrottledError):
+        record_login_event(username=username, detail=AUDIT_LOGIN_THROTTLED)
+        return HTTPException(status_code=429, detail=COPY_LOGIN_THROTTLED)
+    if isinstance(exc, PasswordCapacityError):
+        record_login_event(username=username, detail=AUDIT_PASSWORD_CAPACITY)
+        return HTTPException(status_code=503, detail=COPY_PASSWORD_CAPACITY)
+    raise exc
+
+
 @app.post("/api/auth/login")
-def login(request: LoginRequest):
+def login(http_request: Request, request: LoginRequest):
     username = request.username.strip()
-    result = authenticate_with_result(username, request.password)
+    # 来源地址只认 `request.client.host`（当前 compose 前面没有反代，`X-Forwarded-For`
+    # 是客户端自述的字符串，信任它等于把节流键交给攻击者挑）。
+    client_ip = client_ip_of(http_request)
+    try:
+        result = authenticate_with_result(username, request.password, client_ip=client_ip)
+    except (LoginThrottledError, PasswordCapacityError) as exc:
+        raise _auth_availability_denial(username, exc) from exc
     if result.user is None:
         # 四种失败态（未知账号 / 停用 / 有身份无凭据 / 口令错）到这里已经塌成同一条
         # 状态码 + 同一段中文文案；它们唯一的区别是审计 token，而那个只进审计面（§9.1）。
         record_login_event(username=username, detail=result.audit_detail)
         raise HTTPException(status_code=401, detail="用户名或密码错误")
     if result.audit_detail:
         # 成功面上多出来的那一格只有 AUTH_REHASH_DEGRADED（重哈希没写进去，人已经进来了）。
         # 成功事件本身仍是下面那条既有 _audit，不在这里另起一笔。
         record_login_event(username=username, detail=result.audit_detail)
     user = result.user
     _audit(user, "LOGIN")
     return {
@@ -314,46 +344,55 @@
     }
 
 
 @app.get("/api/auth/me")
 def me(user: CurrentUser = Depends(require_user_pending_password)):
     # 同一个布尔键在这里必须**读表**：`/me` 拿到的是任意时刻的既有 token，签发那一刻的门状态
     # 早就不是当前事实了（改密页与前端引导都靠这一格判断要不要留在改密流程里）。
     return {**user.model_dump(), "password_change_required": _password_change_required(user.username)}
 
 
 @app.post("/api/auth/password/change")
 def change_password(
+    http_request: Request,
     request: PasswordChangeRequest,
     user: CurrentUser = Depends(require_user_pending_password),
 ):
     """自助改密：带着旧口令来，带着**新的一枚** token 走（§8.7 / §7.5）。
 
     顺序即契约：策略 422 → 旧口令 401 → 写库 → 签新 token。
     - 422 排在口令校验之前：`new_password` 太短或与账号名同形都不涉及任何凭据事实，
       而口令校验要付一次 Argon2。
     - 旧口令走 `authenticate_with_result`：它带旧口令校验，所以这一条腿与登录是**同一个**
       爆破面，共用同一份账号级失败/锁定状态（`failed_attempts` 与 `locked_until` 就在这一跳
       被写被读）。这里不自造第二把计数器——两把计数器等于给攻击者一条不被记录的通道。
     - 版本 bump 会废掉**包括来路那一枚在内**的全部已发 token（§7.5）。因此响应必须交出一枚
       新签的：否则走完强制改密流程的人会在下一跳被弹回登录页，而"改密腿在 must_change 期间
       可达"这件事就只剩一半。新 token 在写库**之后**签，`issue_token` 读到的才是新一代纪元。
     """
     reason = validate_new_password(user.username, request.new_password)
     if reason:
         # 策略拒绝是一枚安全事实，不是一句被丢弃的返回值：脚本化地批量提交不合格新口令若
         # 不留痕，§9.1 的 `password_policy_rejected` 审计面就是空的（422 只到展示面）。
         _audit(user, "PASSWORD", status="DENIED", detail=AUDIT_PASSWORD_POLICY_REJECTED)
         raise HTTPException(status_code=422, detail=reason)
-    result = authenticate_with_result(user.username, request.current_password)
+    try:
+        # 这一跳带旧口令校验，所以它与登录是**同一个**猜测面：同一个 (username, client_ip)
+        # 桶、同一份账号级锁定，不自造第二把计数器。异常翻译与登录腿共用同一个 helper——
+        # 两条腿各抄一遍 except 就是留给"其中一条忘了 503"的那条缝。
+        result = authenticate_with_result(
+            user.username, request.current_password, client_ip=client_ip_of(http_request)
+        )
+    except (LoginThrottledError, PasswordCapacityError) as exc:
+        raise _auth_availability_denial(user.username, exc) from exc
     if result.user is None:
         # 四种失败态（含锁定期）到这里已经塌成同一条 401 + 同一段中文，与登录面一字不差；
         # 区别只在审计 token，而那个只进审计面。
         record_login_event(username=user.username, detail=result.audit_detail)
         raise HTTPException(status_code=401, detail="用户名或密码错误")
     try:
         provision_credentials(
             user.username, plain_password=request.new_password, must_change=False
         )
     except CredentialStoreError as exc:
         # 存储事故（锁 / 盘满 / 约束）不是认证结论：翻成中文 500 + FAILED 审计，与既有
         # `文档处理失败` / `Demo 初始化失败` 两条腿同一形状；`public_exception_detail` 负责脱敏，

## test diff (conftest.py)
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task8-pre-conftest.py	2026-09-26 09:52:29.351028300 +0800
+++ backend/tests/conftest.py	2026-09-26 10:00:40.969828200 +0800
@@ -748,20 +748,35 @@
     if store_offenders:
         detail = "；".join(f"写 {src} ⇒ 被护栏改道到 {dst}" for src, dst, _ in store_offenders)
         raise AssertionError(
             "测试往保护集下的真实库里**写**了凭据行（`user_credentials`——那张表里放的是能"
             "登录的凭据，不是一行观测数据）。"
             f"本例要么没把 `CONVERSATION_DB_PATH` 指到临时目录、要么在 env 被 clear 的窗口里"
             f"调了 `user_store` 的写腿：{detail}。修法照 `_CredentialDbPerTest`（每例一份临时"
             f"库 + `ensure_user_credentials_schema()`）。")
 
 
+@pytest.fixture(autouse=True)
+def reset_login_throttle():
+    """每个用例一份干净的节流表：第一层是**进程内**状态，而整套件跑在同一个进程里。
+
+    桶按 `(username, client_ip)` 分、窗口 60 秒，跨用例累加的症状是"第 11 次登录的用例收到
+    429"——那既不是被测事实，也不该由用例自己清。生产侧的清零只发生在窗口过期或进程重启上，
+    这两件事都不是测试之间可以借用的通道（`login_throttle.PreHashThrottle.reset` 正是为此存在）。
+    """
+    from app import login_throttle
+
+    login_throttle.pre_hash_throttle.reset()
+    yield
+    login_throttle.pre_hash_throttle.reset()
+
+
 def pytest_terminal_summary(terminalreporter):
     """收尾把改道计数打在终端上：跑一次全套件就是一份同类隔离漏洞清单。
 
     读/写分开打：写 = 事故（已经逐例判红过），读 = 提醒（护栏兜住了，但那条用例的
     账本 env 其实没设上）。
     """
     guard = _SESSION_GUARD
     records = guard.records if guard is not None else _REDIRECTS
     _report_redirects(terminalreporter, "[ledger-guard]", "真实账本**写**账", "真实账本",
                       records)

## test diff (test_authentication_leg_contract.py)
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task8-pre-test_authentication_leg_contract.py	2026-09-26 09:52:29.151910400 +0800
+++ backend/tests/test_authentication_leg_contract.py	2026-09-26 10:08:07.088430200 +0800
@@ -12,50 +12,60 @@
 3. **渐进重哈希不改会话**（版本不 bump）；写盘失败只记降级、不拒登录（§8.3 冻结裁定），
    而那一格降级必须在真 HTTP 面上落成审计事件——"不静默"判的是审计里有这笔，不是返回值里
    有那个 token。
 4. **`must_change` 门住在依赖层**：白名单只有 `/api/auth/me` 与改密腿，其余 403 + 中文文案，
    机器可读信号是审计 token（§9.1 的两栏分工）。门测的是一枚**活着**的 token——换代在前、
    签发在后；顺序反了撞上的就是 §7.5 那条凭据纪元 401，那不是门的判据（`TokenClaimFaceTests`
    与 `test_password_lifecycle_contract.py` 钉的正是那条腿）。
 5. **审计值域由出口自己把**：`record_login_event` 认 tuple 常量里的三枚取值，空串（成功面）
    根本进不了写手，值域外的文本直接抛——判定不住在调用方的字符串抄写里。
 
-另有一枚**反向钉**（`PasswordCapacitySurfaceTests`）：并发闸门溢出今天在登录腿上还没有人
-翻译，于是它断言的是"未处理的 500 + 零审计"这个**当下缺口**，等的是 503 + 中文文案 +
-`password_capacity` 那一步落地——落地时改断言，而不是删掉它。
+另有一枚**反向钉**（`PasswordCapacitySurfaceTests`）：它原本是 Task 6 埋的"并发闸门溢出在
+登录腿上没人翻译"的缺口哨兵，断的是未处理 500 + 零审计。翻译落地（503 + 中文文案 +
+`password_capacity`）之后它**改了断言、用例保留**——旧断言留在原地等于把门反着钉：下一次
+"翻译又被删掉"它会照样喊绿。
+
+两层保护各有自己的键与自己的哨兵（`ThrottleLayerTests` / `ThrottleHttpFaceTests`）：
+pre-hash 节流按 `(归一化 username, client_ip)` 分桶、进程内、排在任何身份查找之前；
+账号锁定按 username、落库、跨来源地址共享。合并成一枚就必然丢掉一种保护，而两枚键各自
+只有一条用例能杀掉对应的计划突变（M6 去掉 `client_ip` ⇒ SECA-16a；把锁定也按 IP 键 ⇒ SECA-16b）。
+429 与 503 都是**可用性**事实：它们在凭据结论之前判出，因此两栏文案（展示面中文 / 审计面
+token）里都不许出现任何关于账号存在与否的话——这条不写成一句注释，写成逐字节的面对比。
 """
 
 from __future__ import annotations
 
 import ast
 import contextlib
 import hashlib
+import json
 import re
 import sys
 import threading
 import unittest
 from pathlib import Path
 from unittest import mock
 
 import jwt
 from fastapi import HTTPException
 from fastapi.testclient import TestClient
 
 BACKEND_DIR = Path(__file__).resolve().parents[1]
 TESTS_DIR = BACKEND_DIR / "tests"
 for _path in (str(BACKEND_DIR), str(TESTS_DIR)):
     if _path not in sys.path:
         sys.path.insert(0, _path)
 
-from app import auth, credentials, directory, user_store  # noqa: E402
+from app import auth, credentials, directory, login_throttle, user_store  # noqa: E402
 from app import config as config_module  # noqa: E402
 from app import credentials_migration  # noqa: E402
+from app.config import settings  # noqa: E402
 from app.main import app as fastapi_app  # noqa: E402
 import sec_a_fixtures  # noqa: E402  —— 换库 / 审计落点 / JWT secret 三件地基只留一份实现
 from sec_a_seed import (  # noqa: E402
     SEED_RECORD,
     ensure_demo_credentials,
     seed_demo_credentials,
 )
 
 LEGACY_ADMIN = hashlib.sha256(b"admin123").hexdigest()
 GOOD_PASSWORD = "a-good-password 123456"
@@ -464,55 +474,105 @@
     def test_a_denied_login_carries_neither_a_token_nor_the_password(self):
         response = self._post("admin", "wrong-password 123456")
         self.assertNotIn("access_token", response.text)
         self.assertNotIn("wrong-password 123456", response.text)
         self.assertNotIn(
             "wrong-password 123456", self.audit_path.read_text(encoding="utf-8")
         )
 
 
 class PasswordCapacitySurfaceTests(_LongJwtSecret, _AuditToTempFile):
-    """并发闸门的**今天**的形状：容量溢出在登录腿上没人翻译，所以它是未处理的 500。
+    """容量溢出在两条 HTTP 腿上的形状：503 + 中文文案 + `password_capacity`，一格不多一格不少。
 
-    这枚钉子要等的改动是：`PasswordCapacityError` 在 HTTP 面翻成 `503` +
-    「服务繁忙，请稍后重试」+ 审计 token `password_capacity`（§9.1 表的最后一行），并且
-    判定排在身份查找之前。那一刻这一枚必须跟着改成断言那三件事，**不是删掉**——它存在的
-    全部意义就是"翻译没落地时这里必须有人喊一声"。
-
-    为什么要喊：认证腿切换之后，每一次登录（含未知账号那条哑校验）都要过一次
-    `settings.argon2_max_concurrent_ops` 那么宽的槽；而异常目前只从
-    `credentials.argon2_slot()` 抛出，`app/` 里没有任何一层接它。几枚并发的口令猜测就能
-    把登录面打成 500——可用性事实本身不泄露账号存在性，但一条没有审计、没有中文文案的
-    未处理异常既不可诊断，也不是规格承诺的那个形状。
+    这枚钉子原本是 Task 6 埋的**反向钉**（那时没人翻译 ⇒ 断的是"未处理 500 + 零审计"这个
+    当下缺口）。翻译落地后它**改了断言、用例保留**：留着旧断言等于把门反着钉——下一次
+    "翻译又被删掉"它会照样喊绿。
+
+    为什么这条值得单独有脸：认证腿切换之后，每一次登录（含未知账号那条哑校验）都要过一次
+    `settings.argon2_max_concurrent_ops` 那么宽的槽。几枚并发的口令猜测就能把登录面打成
+    不可用，而"不可用"必须以它自己的状态码出现，不能被伪装成凭据结论（401 会把一次服务过载
+    说成"你的口令不对"，用户据此改口令、运维据此查凭据，两头都得到错地图）。
     """
 
     def setUp(self):
         super().setUp()
         _fresh_db(self)
         ensure_demo_credentials()
 
-    def test_capacity_exhaustion_still_escapes_the_login_leg_as_an_unhandled_500(self):
+    def _login(self, username: str, password: str = "admin123"):
+        return TestClient(fastapi_app, raise_server_exceptions=False).post(
+            "/api/auth/login", json={"username": username, "password": password}
+        )
+
+    def test_capacity_exhaustion_surfaces_as_a_translated_503_on_the_login_leg(self):
+        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
+            response = self._login("admin")
+        self.assertEqual(503, response.status_code, response.text)
+        # 展示面只有中文那一句（字面量钉死，不比"常量 vs 常量"），审计面只有 token。
+        self.assertEqual({"detail": "服务繁忙，请稍后重试"}, response.json())
+        self.assertEqual(
+            [auth.AUDIT_PASSWORD_CAPACITY], [event["detail"] for event in self.events()]
+        )
+        # 堆栈不外泄、口令不上响应面（§9.3 的脱敏作用域与这条可用性路径无关，照样成立）。
+        self.assertNotIn("admin123", response.text)
+        self.assertNotIn("Traceback", response.text)
+        # 英文 token 不许渗进 body：两栏一旦互换，展示面就成了机器可读性的抄本。
+        self.assertNotIn("password_capacity", response.text)
+
+    def test_the_capacity_face_says_the_same_thing_about_an_unknown_account(self):
+        """503 不构成账号存在性枚举面——**为什么**：未知账号那条腿过的是同一道槽。
+
+        §7.3 让四种失败态各消耗一次同档运算，容量这道闸 therefore 对"有这一行凭据"和
+        "根本没有这个账号"同样会关；两脸逐字节相同 ⇒ 这一格可用性事实里读不出任何身份结论。
+        这也是把 429/503 排在凭据结论之前的全部意义：先说"现在不行"，后说"你是谁"。
+        """
+        faces = set()
+        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
+            for username in ("admin", "nobody-at-all"):
+                response = self._login(username)
+                faces.add((response.status_code, response.text))
+        self.assertEqual(1, len(faces), faces)
+        self.assertEqual(503, next(iter(faces))[0])
+
+    def test_the_change_leg_is_the_second_capacity_face_and_gets_the_same_503(self):
+        """/api/auth/password/change 校验旧口令 ⇒ 它是第二个容量面，不是凭据结论的第二张脸。
+
+        两条腿都跑 `authenticate_with_result`，因此都从同一道闸门里过；只翻译登录那一腿的
+        话，攻击者就把改密面当成免费的 DoS 放大器（同一枚槽、无人接异常、裸栈上 500）。
+        """
+        user = auth.authenticate("admin", "admin123")
+        self.assertIsNotNone(user)
+        headers = {"Authorization": f"Bearer {auth.issue_token(user)}"}
         with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
             response = TestClient(fastapi_app, raise_server_exceptions=False).post(
-                "/api/auth/login", json={"username": "admin", "password": "admin123"}
+                "/api/auth/password/change",
+                json={
+                    "current_password": "admin123",
+                    "new_password": "a-brand-new-password 4242",
+                },
+                headers=headers,
             )
-        self.assertEqual(500, response.status_code, response.text)
-        # 今天没有任何翻译 ⇒ 连"该落下的那一笔审计"都没有：容量溢出对审计面是完全静默的。
-        self.assertEqual([], self.events())
-        # 堆栈不外泄，口令不上响应面（§9.3 的脱敏作用域与这条可用性路径无关，照样成立）。
+        self.assertEqual(503, response.status_code, response.text)
+        self.assertEqual({"detail": "服务繁忙，请稍后重试"}, response.json())
+        self.assertEqual(
+            [auth.AUDIT_PASSWORD_CAPACITY], [event["detail"] for event in self.events()]
+        )
         self.assertNotIn("admin123", response.text)
-        self.assertNotIn("Traceback", response.text)
+        self.assertNotIn("a-brand-new-password", response.text)
+        # 新口令没改进去：容量结论不产生任何写副作用（这一腿的写路径在校验之后）。
+        self.assertIsNone(user_store.get_record("admin").locked_until)
 
     def test_capacity_exhaustion_is_the_same_on_the_dummy_leg_as_on_a_real_verify(self):
         """哑校验与真 verify 共用同一道闸：不存在"拿不存在的账号绕过容量门"那条腿。
 
-        这条也只钉"没人接住它"——上游拿到的是同一个未翻译的异常，而不是一个认证结论。
+        这条钉的是**腿级**事实：上游拿到的是同一个 `PasswordCapacityError`，而不是一个认证
+        结论——HTTP 面那两枚 503 钉子翻译的就是它，翻译没落地时这里也还剩一条红。
         """
         for username in ("admin", "nobody-at-all"):
             with self.subTest(username=username):
                 with mock.patch.object(
                     credentials, "_SLOTS", threading.BoundedSemaphore(0)
                 ):
                     with self.assertRaises(credentials.PasswordCapacityError):
                         auth.authenticate_with_result(username, "whatever 123456")
 
 
@@ -700,21 +760,21 @@
 
     def test_no_artificial_delay_on_the_login_leg(self):
         """§7.4：统一靠"锁定路径不跑 Argon2"，不靠 sleep 修平（人工延迟本身是攻击面）。
 
         判据是 AST，而且扫的是登录腿的**调用图**（编排层 `auth` + 运算层 `credentials` +
         两条被叫到的状态腿 `user_store`/`directory`）：单子串判据只盯一枚文件、别处一个字
         都不说，而延迟最可能被加到的正是运算层那一侧。这里认的是调用点上的**函数名**——
         裸 `sleep()` 与 `time.sleep()` / `gevent.sleep()` / `asyncio.sleep()` 这类属性调用
         同形命中，判的是源码结构而不是某一段文本有没有出现过。
         """
-        call_graph = (auth, credentials, user_store, directory)
+        call_graph = (auth, credentials, user_store, directory, login_throttle)
         offenders: list[str] = []
         for module in call_graph:
             tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
             for node in ast.walk(tree):
                 if not isinstance(node, ast.Call):
                     continue
                 callee = node.func
                 name = getattr(callee, "id", None) or getattr(callee, "attr", None)
                 if name == "sleep":
                     offenders.append(f"{module.__name__}:{node.lineno}")
@@ -765,37 +825,52 @@
 
         再叫一次 `seed_demo_credentials()` 也必须原地不动（每行都已在会话库里）——
         这一句同时钉住"台账只由会话级 seed 写"和"重复调用不重算 Argon2"两件事。
         """
         seed_demo_credentials()
         self.assertEqual(5, len(SEED_RECORD))
         self.assertEqual(5, len(set(SEED_RECORD)))
 
 
 class AuditVocabularyTests(unittest.TestCase):
-    """登录面的 `detail` 是封闭枚举：三枚取值 + 成功面的空串，自由文本不得进入。"""
+    """登录面的 `detail` 是封闭枚举：五枚取值 + 成功面的空串，自由文本不得进入。"""
 
     def test_the_three_tokens_keep_their_frozen_spellings(self):
         self.assertEqual("invalid_credentials", auth.AUDIT_INVALID_CREDENTIALS)
         self.assertEqual("AUTH_LOGIN_LOCKED", auth.AUDIT_LOGIN_LOCKED)
         self.assertEqual("AUTH_REHASH_DEGRADED", auth.AUDIT_REHASH_DEGRADED)
 
+    def test_the_two_availability_tokens_keep_their_frozen_spellings(self):
+        """两格可用性事实也是枚举成员，不是绕过值域的第二条审计腿。
+
+        拼写进枚举、枚举由 writer 自己判成员——加一枚 token 的正确做法只有这一种：
+        扩 `LOGIN_AUDIT_DETAILS`，而不是在 `main.py` 里直接叫 `_record_event`。
+        """
+        self.assertEqual("login_throttled", auth.AUDIT_LOGIN_THROTTLED)
+        self.assertEqual("password_capacity", auth.AUDIT_PASSWORD_CAPACITY)
+        self.assertEqual("登录尝试过于频繁，请稍后重试", auth.COPY_LOGIN_THROTTLED)
+        self.assertEqual("服务繁忙，请稍后重试", auth.COPY_PASSWORD_CAPACITY)
+        # 展示面与审计面永不互换（§9.1 两栏）：中文文案不是枚举成员，token 不上响应体。
+        self.assertNotIn(auth.COPY_LOGIN_THROTTLED, auth.LOGIN_AUDIT_DETAILS)
+        self.assertNotIn(auth.COPY_PASSWORD_CAPACITY, auth.LOGIN_AUDIT_DETAILS)
+
     def test_the_enum_lives_in_one_tuple_and_the_writer_is_the_one_that_checks_it(self):
         """值域由 `record_login_event` 自己把：判定用同一枚 tuple 常量，不靠调用方抄字符串。
 
         只比"三个常量字面量 vs 三个常量字面量"的那种钉子是同一份东西跟自己比——把值域换成
         两枚、或往审计出口塞第四枚取值，它都照样绿。这里钉的是**出口处的成员判定**：
         tuple 是唯一的值域出处，而值域外的文本必须在写手面前抛，不是被洗成合法 token。
         """
         self.assertEqual(
             (auth.AUDIT_INVALID_CREDENTIALS, auth.AUDIT_LOGIN_LOCKED,
-             auth.AUDIT_REHASH_DEGRADED),
+             auth.AUDIT_REHASH_DEGRADED, auth.AUDIT_LOGIN_THROTTLED,
+             auth.AUDIT_PASSWORD_CAPACITY),

## new module (full)
     1	"""pre-hash 节流（规格 §7.1 步骤 0 / §7.2 第一层）与锁定判定的唯一真源。
     2	
     3	两层键不同、职责不同，合并成一枚必然丢掉两种保护之一：
     4	
     5	- 本模块的桶是**进程内**的，按 `(归一化 username, client_ip)` 分，重启即清。它回答的
     6	  唯一问题是"这次请求配不配消耗一次内存硬运算"，所以判定必须排在任何身份查找之前——
     7	  闸门排在运算之后，认证面自己就成了 DoS 面。
     8	- `user_store` 的 `failed_attempts`/`locked_until` 是**落库**的，只按 username 分，跨重启、
     9	  跨来源地址共享。第一层少一枚 `client_ip` 键 ⇒ 换个来源地址即可绕过节流；给第二层也
    10	  加上 `client_ip` ⇒ 分布式猜测一人一份计数，锁定永不触发。两枚键都必须有直接断言。
    11	
    12	本模块不做 sleep：§7.4 的收敛靠"锁定路径不跑 Argon2"，人工延迟本身是攻击面。
    13	"""
    14	
    15	from __future__ import annotations
    16	
    17	import threading
    18	import time
    19	from collections import defaultdict, deque
    20	from datetime import datetime, timezone
    21	
    22	from app.config import settings
    23	
    24	
    25	def client_ip_of(request) -> str:
    26	    """本次请求的**可信**来源地址。
    27	
    28	    只认 `request.client.host`，**不读** `X-Forwarded-For`：当前部署形态里 compose 直接
    29	    把 8001 映射出去、前面没有反代，于是那个头是客户端自述的字符串。信任它等于把
    30	    节流键交给攻击者挑——换一枚伪造头就是一个新桶，第一层当场归零。将来真要前置 nginx，
    31	    改的是这里（并且必须同时约束跳数），而不是调用方。
    32	    """
    33	    client = getattr(request, "client", None)
    34	    return str(getattr(client, "host", "") or "unknown")
    35	
    36	
    37	def throttle_bucket(username: str, client_ip: str) -> str:
    38	    """节流键：归一化的账号名 + 来源地址。两枚都参与，缺一层的保护就少一半。"""
    39	    return f"{str(username).casefold()}|{client_ip}"
    40	
    41	
    42	class LoginThrottledError(RuntimeError):
    43	    """节流命中。它**不是**凭据结论：还没做身份查找、还没碰口令，所以 HTTP 面是 429 不是 401。
    44	
    45	    住在这一层而不是 `auth`，因为判定与异常同源；`auth` 与 `main` 都 import 同一个类，
    46	    两枚同义异常早晚出现"catch 错那一枚"的缝。
    47	    """
    48	
    49	
    50	class PreHashThrottle:
    51	    """固定窗口内的滑动计数（每桶一个单调时钟时间戳队列）。"""
    52	
    53	    def __init__(self, *, window_seconds: int, max_attempts: int) -> None:
    54	        self._window = float(window_seconds)
    55	        self._max = int(max_attempts)
    56	        self._hits: dict[str, deque[float]] = defaultdict(deque)
    57	        self._lock = threading.Lock()
    58	        self._last_sweep = time.monotonic()
    59	
    60	    def allow(self, bucket: str, *, now: float | None = None) -> bool:
    61	        moment = time.monotonic() if now is None else float(now)
    62	        with self._lock:
    63	            self._sweep_stale(moment)
    64	            hits = self._hits[bucket]
    65	            while hits and moment - hits[0] > self._window:
    66	                hits.popleft()
    67	            if len(hits) >= self._max:
    68	                return False
    69	            hits.append(moment)
    70	            return True
    71	
    72	    def _sweep_stale(self, moment: float) -> None:
    73	        """整表回收，每个窗口至多一次；调用方持锁。
    74	
    75	        单桶判据（`allow` 里那条）只清空**被再次命中**的桶：来源地址打不停时，桶的个数
    76	        就是攻击者的请求数，节流表自己会长成一条内存增长面。这里按"最近一次命中已出窗"
    77	        整片丢弃，语义与逐桶剪枝完全一致（丢掉的桶再命中一次也会重新计入），只是把上限
    78	        从'见过的地址数'收到'一个窗口内在场的地址数'。
    79	        """
    80	        if moment - self._last_sweep <= self._window:
    81	            return
    82	        self._last_sweep = moment
    83	        for key in [k for k, dq in self._hits.items() if not dq or moment - dq[-1] > self._window]:
    84	            self._hits.pop(key, None)
    85	
    86	    def reset(self) -> None:
    87	        with self._lock:
    88	            self._hits.clear()
    89	            self._last_sweep = time.monotonic()
    90	
    91	
    92	def is_locked(locked_until: str | None, *, now: datetime | None = None) -> bool:
    93	    """账号此刻是否处于锁定期：`locked_until` 是**锁到的那个时刻**，还没到就是锁着。
    94	
    95	    方向别写反：`record_login_failure` 写进去的是 `now + lock_seconds`（未来），所以"还锁着"
    96	    对应 `until > now`。写反的症状是"永远锁不住"——阈值一到就把它当成过期，下一次口令猜测
    97	    照旧跑一次 Argon2，§7.2 第二层直接失效。
    98	
    99	    坏值一律 fail closed 当锁定，两种坏法同臂：压根解析不出（ValueError），以及**解析得出
   100	    但没有偏移**（naive）。后者不是假想——运维手改、从另一个写入方恢复来的备份、SQLite 的
   101	    `CURRENT_TIMESTAMP` 惯用法都会给出 `2099-01-01 00:00:00` 这种能解析却无时区的值。
   102	    这里**不**替它补 UTC：猜出来的偏移会把一行不再可信的数据读成"这一行说没锁"，
   103	    而白送一次昂贵运算正是这条门要挡的事。
   104	    """
   105	    if not locked_until:
   106	        return False
   107	    try:
   108	        moment = datetime.fromisoformat(str(locked_until))
   109	    except (ValueError, TypeError):
   110	        return True
   111	    if moment.tzinfo is None:
   112	        return True
   113	    return moment > (now or datetime.now(timezone.utc))
   114	
   115	
   116	#: 进程内单例。窗口与阈值都是**可用性旋钮**（`login_throttle_*`），不含 m/t/p：
   117	#: 口令强度固定在 `credentials` 的常量上，不可在运行时调（SEC-A-008）。
   118	pre_hash_throttle = PreHashThrottle(
   119	    window_seconds=settings.login_throttle_window_seconds,
   120	    max_attempts=settings.login_throttle_max_attempts,
   121	)
   122	
   123	
   124	def configured_throttle() -> PreHashThrottle:
   125	    """单例的读取点。构造在 import 期完成，与 `credentials._SLOTS` 同一口径。"""
   126	    return pre_hash_throttle

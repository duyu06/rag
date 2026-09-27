# Task 9 review package (base = snap-task9-pre-app)
## stat
Files .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/agent_trace.py and backend/app/agent_trace.py differ
Files .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/audit.py and backend/app/audit.py differ
Files .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/auth.py and backend/app/auth.py differ
Files .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/config.py and backend/app/config.py differ
Files .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/main.py and backend/app/main.py differ
Files .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/security.py and backend/app/security.py differ
Only in backend/app: security_startup.py
## app diff
diff -ruN -U12 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/agent_trace.py backend/app/agent_trace.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/agent_trace.py	2026-09-26 12:38:34.240079400 +0800
+++ backend/app/agent_trace.py	2026-09-26 12:47:31.292514500 +0800
@@ -1,23 +1,23 @@
 from __future__ import annotations
 
 import json
 import logging
 from datetime import datetime, timezone
 from pathlib import Path
 from threading import Lock
 from typing import Any
 from uuid import uuid4
 
-from app.security import redact_secrets, redact_text
+from app.security import redact_for_persistence, redact_text
 
 TRACE_PATH = Path("data/agent_traces.jsonl")
 _LOCK = Lock()
 logger = logging.getLogger("app.agent_trace")
 
 #: §8 里 trace 新增的那个对象的键名。**唯一出处**：三条链写、TraceView 读，都引这个常量。
 MODEL_ROUTE_KEY = "model_route"
 
 
 def new_trace_id() -> str:
     return uuid4().hex
 
@@ -61,32 +61,32 @@
     """Keep debugger useful without persisting full potentially-sensitive prompts."""
     allowed: dict[str, Any] = {}
     for key in ("knowledge_base_id", "top_k", "max_results"):
         if key in arguments:
             allowed[key] = arguments[key]
     if "query" in arguments:
         allowed["query_preview"] = redact_text(arguments["query"])[:180]
     return allowed
 
 
 def save_trace(trace: dict[str, Any]) -> None:
     TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
-    line = json.dumps(redact_secrets(trace), ensure_ascii=False)
+    line = json.dumps(redact_for_persistence(trace), ensure_ascii=False)
     with _LOCK:
         with TRACE_PATH.open("a", encoding="utf-8") as handle:
             handle.write(line + "\n")
 
 
 def get_trace(trace_id: str) -> dict[str, Any] | None:
     if not TRACE_PATH.exists():
         return None
     with _LOCK:
         lines = TRACE_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
     for line in reversed(lines):
         try:
             item = json.loads(line)
         except json.JSONDecodeError:
             continue
         if item.get("trace_id") == trace_id:
             # Keep legacy trace rows safe when served through the debugger.
-            return redact_secrets(item)
+            return redact_for_persistence(item)
     return None
diff -ruN -U12 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/audit.py backend/app/audit.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/audit.py	2026-09-26 12:38:34.116164900 +0800
+++ backend/app/audit.py	2026-09-26 12:47:12.313061300 +0800
@@ -1,21 +1,21 @@
 from __future__ import annotations
 
 import json
 from datetime import datetime, timezone
 from pathlib import Path
 from threading import Lock
 from typing import Any
 
-from app.security import redact_secrets
+from app.security import redact_for_persistence
 
 AUDIT_PATH = Path("data/audit.jsonl")
 _LOCK = Lock()
 
 
 def record_event(
     *,
     username: str,
     role: str,
     action: str,
     status: str = "SUCCESS",
     knowledge_base_id: str | None = None,
@@ -35,41 +35,44 @@
     }
     optional = {
         "knowledge_base_id": knowledge_base_id,
         "query": query,
         "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
         "num_sources": num_sources,
         "detail": detail,
         # 受体的账号名（管理员重置这类"主体≠客体"的动作才有值）。缺省 None ⇒ 不进下面的
         # `if value is not None` 过滤，也就**不给任何既有事件多一个键**：这条参数是纯增量。
         "target": target,
     }
     event.update({key: value for key, value in optional.items() if value is not None})
-    line = json.dumps(redact_secrets(event), ensure_ascii=False)
+    # 落盘面（审计）走持久化域 redactor：形态匹配 + 精确键名黑名单（SEC-A-009）。审计面从
+    # 不含响应体的 access_token，切到这里只多抹敏感键名，不改既有事件的键集合（SEC-A-006）。
+    line = json.dumps(redact_for_persistence(event), ensure_ascii=False)
     with _LOCK:
         with AUDIT_PATH.open("a", encoding="utf-8") as handle:
             handle.write(line + "\n")
 
 
 def recent_events(limit: int = 100) -> list[dict[str, Any]]:
     if not AUDIT_PATH.exists():
         return []
     with _LOCK:
         lines = AUDIT_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
     events: list[dict[str, Any]] = []
     for line in reversed(lines[-max(limit * 3, limit) :]):
         try:
             # Redact on read as well so historical rows written before this
-            # boundary was introduced cannot leak through the admin API.
-            events.append(redact_secrets(json.loads(line)))
+            # boundary was introduced cannot leak through the admin API. Read-side
+            # re-redaction is the same persistence domain as the write above.
+            events.append(redact_for_persistence(json.loads(line)))
         except json.JSONDecodeError:
             continue
         if len(events) >= limit:
             break
     return events
 
 
 def today_summary(*, username: str | None = None) -> dict[str, Any]:
     today = datetime.now(timezone.utc).date().isoformat()
     events = [item for item in recent_events(5000) if str(item.get("timestamp", "")).startswith(today)]
     if username is not None:
         events = [item for item in events if item.get("username") == username]
diff -ruN -U12 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/auth.py backend/app/auth.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/auth.py	2026-09-26 12:38:34.216470900 +0800
+++ backend/app/auth.py	2026-09-26 12:50:59.583675000 +0800
@@ -229,40 +229,46 @@
 )
 
 
 @dataclass(frozen=True)
 class LoginResult:
     """登录腿的完整结论。HTTP 面（`main.py`）与契约测试读的是同一份，不分两条腿。"""
 
     user: CurrentUser | None
     audit_detail: str
     password_change_required: bool
 
 
-def record_login_event(*, username: str, detail: str) -> None:
-    """登录面的唯一审计出口。`detail` 必须落在 `LOGIN_AUDIT_DETAILS` 里。
+def record_login_event(*, username: str, detail: str, action: str = "LOGIN") -> None:
+    """登录/认证面的唯一审计出口。`detail` 必须落在 `LOGIN_AUDIT_DETAILS` 里。
 
     空串是**成功面**的取值，而成功事件属于既有 `_audit(user, "LOGIN")` 那一条腿：空值根本
     不该走到这里，否则落下的是一条 status=DENIED、detail 空白的伪拒绝事件（它既不是拒绝，
     也没说出任何事）。值域外的文本直接抛，不"洗成"某个枚举值——把自由文本降级成合法 token
     等于把这条门想钉的东西擦掉。
+
+    `action` 默认 `LOGIN`（登录腿的事实）。但同一道可用性闸也守在改密/管理员重置两条**口令
+    操作腿**上（它们带旧口令校验、共用这唯一的 detail 值域）。那两条腿上的 429/503 若仍记成
+    `LOGIN`，审计里"一次被容量挡下的重置"就和"一次失败的登录"混成一件事——所以调用方把本腿
+    的动作名传进来（`PASSWORD`）。detail 值域**一字不动**（§9.1 冻结的是取值集合，不是动作轴），
+    只是让可用性拒绝带上它真正发生的那张脸。
     """
     if not detail:
         return
     if detail not in LOGIN_AUDIT_DETAILS:
         raise ValueError("登录审计 detail 不在枚举值域内")
     _record_event(
         username=username or "unknown",
         role="UNKNOWN",
-        action="LOGIN",
+        action=action,
         status="SUCCESS" if detail == AUDIT_REHASH_DEGRADED else "DENIED",
         detail=detail,
     )
 
 
 def _user_from(identity: directory.UserIdentity, grant: FeishuGrant | None) -> CurrentUser:
     """`CurrentUser` 的唯一构造点。登录腿与令牌腿共用，避免两处的 grant 语义劈叉。"""
     return CurrentUser(
         username=identity.username,
         display_name=identity.display_name,
         role=identity.role,
         grant=grant,
diff -ruN -U12 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/config.py backend/app/config.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/config.py	2026-09-26 12:38:34.107911500 +0800
+++ backend/app/config.py	2026-09-26 12:48:03.281733300 +0800
@@ -146,24 +146,29 @@
     retrieval_rerank_candidates: int = Field(default=6, ge=5, le=50)
     # BGE's short-query retrieval instruction improves pure dense Top-3 recall on
     # the real-BGE gate. Hybrid keeps the raw query because it measured better with RRF.
     retrieval_vector_query_instruction: str = "为这个句子生成表示以用于检索相关文章："
     # Prefer diverse documents in the final evidence set while still allowing a
     # document to contribute multiple sections. Deferred chunks fill any shortage.
     retrieval_max_chunks_per_document: int = Field(default=2, ge=1, le=10)
     retrieval_query_context_max_chars: int = Field(default=320, ge=80, le=1000)
 
     # SEC-A 生产形态总开关。true ⇒ 不加载 demo 身份 + 默认 JWT secret 拒启动 +
     # CORS 白名单未配拒启动（三件同生同死，规格 §8.5）。
     security_enterprise_mode: bool = False
+    # CORS 白名单（逗号分隔，既不是子串也不是通配）。默认值是 dev / 测试形态的本地
+    # 前端来源；SECURITY_ENTERPRISE_MODE=true 且这一格为空或含 * 即拒启动
+    # （§8.5 三守卫之一，判定在 app/security_startup.py）。allow_credentials 恒 False
+    # ——token 走 header，收紧 origin 才是有效项（§10）。
+    cors_allow_origins: str = "http://localhost:3000"
 
     jwt_secret: str = "change-me-before-production-yaoke-demo-secret"
     jwt_expire_hours: int = 8
 
     # Argon2 并发槽上限（可用性旋钮）。**密码学档位不在这里**：m/t/p 固定在
     # app/credentials.py 的常量上，改它等于改规格（SEC-A-008）。
     # 槽与节流桶都住在进程内，因此横向扩到 `uvicorn --workers N` 时第一层的天花板一并乘 N
     # （现网 `backend/Dockerfile` 的 CMD 没有 `--workers`）；只有落库的账号锁定不受进程数影响。
     argon2_max_concurrent_ops: int = 2
 
     # 账号级持久锁定（规格 §7.2 第二层）：键只有 username，跨来源共享同一失败状态。
     account_max_failed_attempts: int = 5
diff -ruN -U12 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/main.py backend/app/main.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/main.py	2026-09-26 12:38:34.238080500 +0800
+++ backend/app/main.py	2026-09-26 13:10:43.464759400 +0800
@@ -7,44 +7,46 @@
 from collections import Counter
 from contextlib import asynccontextmanager
 from datetime import datetime
 from pathlib import Path
 from typing import Any, Literal
 
 from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
 from fastapi.exception_handlers import request_validation_exception_handler
 from fastapi.exceptions import RequestValidationError
 from fastapi.middleware.cors import CORSMiddleware
 from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
 from pydantic import BaseModel, Field
+from starlette.routing import get_route_path
 
 from app.audit import recent_events, record_event, today_summary
 from app.auth import (
     AUDIT_LOGIN_THROTTLED,
     AUDIT_PASSWORD_CAPACITY,
     AUDIT_PASSWORD_POLICY_REJECTED,
     COPY_LOGIN_THROTTLED,
     COPY_PASSWORD_CAPACITY,
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
+from app import security_startup
 from app.config import settings
 from app.credentials import PasswordCapacityError
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
@@ -62,71 +64,81 @@
     redact_text,
 )
 from app.store import vector_store
 from app.user_store import CredentialStoreError
 
 
 @asynccontextmanager
 async def lifespan(_app: FastAPI):
     """启动门闸：坏配置让进程起不来，而不是第一个请求才炸。
 
     放在 lifespan 而不是模块顶层，是因为顶层 import 的副作用会波及所有导入方
     （测试、脚本、`python -c "import app.main"`）；lifespan 只在服务真正启动时跑一次。
-    两个 warmup 各自的前置条件都在**函数内部**判，所以默认配置下启动零额外行为：
+    启动守卫与两个 warmup 的前置条件都在**函数内部**判，所以默认配置下启动零额外行为：
+    - `security_startup.assert_startup_safe()`（§8.5 三守卫，本任务第一道）：
+      `SECURITY_ENTERPRISE_MODE=false`（默认）时整体 no-op；打到 true 才把默认/过短的
+      JWT secret 与缺失或含 * 的 CORS 白名单判成拒启动。异常穿出启动阶段 = fail-fast。
     - `warmup_identity_permissions()`：`FEISHU_PERMISSIONS_ENABLED=false` 直接 return。
     - `warmup_llm_router()`（Model Router V2.3 §8）：`LLM_ROUTER_ENABLED=false` 整链 no-op；
       开启时跑注册表 fail-fast + 建 `llm_request_logs` 表 + 接 usage sink（观测面自身
       fail-open，只有注册表错误才是启动事故）。
     异常不上抛成 500 而是穿出启动阶段——uvicorn 会因此退出（fail-fast）。
     `main_agent.py` 复用同一个 app 实例，门闸一并生效。
     """
+    security_startup.assert_startup_safe()
     warmup_identity_permissions()
     warmup_llm_router()
     yield
 
 
 app = FastAPI(
     title="yaoke 企业 AI 知识中台 API",
     version="0.4.0",
     description="Enterprise RAG demo: RBAC + multi-KB + Hybrid Retrieval + Rerank + Citation + Audit",
     lifespan=lifespan,
 )
 app.add_middleware(
     CORSMiddleware,
-    allow_origins=["*"],
+    # CORS 白名单来自 config（§10）：默认 http://localhost:3000；企业形态下这一格缺失或含 *
+    # 已由 lifespan 第一道的启动守卫拒启动，中间件这里只把逗号分隔白名单喂进去。
+    allow_origins=[item.strip() for item in settings.cors_allow_origins.split(",") if item.strip()],
     allow_credentials=False,
     allow_methods=["*"],
     allow_headers=["*"],
 )
 
 
 #: 只有这两条腿的输入校验错误需要"脱敏回显"。FastAPI 默认的 `RequestValidationError`
 #: 载荷把被拒取值原样放进 `detail[*].input`：漏填 `new_password` 那一格会把同请求里的
 #: `current_password`（用户当下有效的那枚口令）整份抄进响应体，超长口令更会把自己抄进去。
 #: §8.8 明写两端点"不回显任何口令"、SEC-A-002 禁止口令进任何响应面 ⇒ 这两条腿的校验错误
 #: 一律换成一句不含 `input` 的中文。
 #: 判据用**路径**而不是解析 body：`/api/auth/password/change` 全表唯一，`.../password/reset`
 #: 后缀也唯一（`/api/demo/reset` 不以此结尾）。其余所有路径——含 V2.3 契约与 `/api/query`
 #: 键集合钉所在的全部端点——原样交给 FastAPI 内置处理器 `request_validation_exception_handler`，
 #: 那条就是默认注册的同一枚函数，输出逐字节不变。异常处理器只能是 app 级（Starlette 无路由级
 #: 处理），故用路径分支把改动**关在这两条腿内**，不触碰任何既有端点的校验载荷。
 def _is_no_echo_auth_path(path: str) -> bool:
     return path == "/api/auth/password/change" or path.endswith("/password/reset")
 
 
 @app.exception_handler(RequestValidationError)
 async def auth_validation_error_handler(
     request: Request, exc: RequestValidationError
 ):
-    if _is_no_echo_auth_path(request.url.path):
+    # 判据用**路由真正使用的那条路径**（get_route_path 会剥掉 root_path），不是
+    # request.url.path：后者在 --root-path=/gw 部署下带着前缀（/gw/...），而 Starlette
+    # 派发前已把前缀剥掉。用后者会让改密腿的校验错误漏过脱敏、回落 FastAPI 默认处理器，
+    # 把用户刚提交的 current_password 抄进响应体（§8.8 / SEC-A-002）。
+    if _is_no_echo_auth_path(get_route_path(request.scope)):
         return JSONResponse(status_code=422, content={"detail": "请求参数不合法"})
     return await request_validation_exception_handler(request, exc)
 
 
 class LoginRequest(BaseModel):
     username: str = Field(min_length=1, max_length=64)
     # 上限引 `auth._MAX_PASSWORD_LENGTH` 而不是抄 128：登录面与改密面共用同一个字节天花板，
     # 抄两遍就会漂，漂了的症状是"登录进得来的口令改不进去"（`auth.py` 同一条理由）。
     password: str = Field(min_length=1, max_length=_MAX_PASSWORD_LENGTH)
 
 
 class PasswordChangeRequest(BaseModel):
@@ -286,38 +298,38 @@
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
 
 
-def _auth_availability_denial(username: str, exc: Exception) -> HTTPException:
+def _auth_availability_denial(username: str, exc: Exception, *, action: str = "LOGIN") -> HTTPException:
     """把两格**可用性**事实翻成 HTTPException：429（pre-hash 节流命中）/ 503（Argon2 槽溢出）。
 
     两格都不是凭据结论：判定发生在身份查找与昂贵运算的两侧，客户端材料一个都没被读过，
     所以响应面只说"现在不行"，绝不提账号存在与否——那才会把可用性事实变成存在性证据。
     审计走 `record_login_event` 那唯一的出口（token 已在 `LOGIN_AUDIT_DETAILS` 里），
     不在这里另开 writer。异常识别按类型、不按消息，且**只**认这两枚：别的异常一律原样上抛，
     免得多年以后有人往这条 try 里塞进一枚凭据异常而它被静默翻成 503。
     """
     if isinstance(exc, LoginThrottledError):
-        record_login_event(username=username, detail=AUDIT_LOGIN_THROTTLED)
+        record_login_event(username=username, detail=AUDIT_LOGIN_THROTTLED, action=action)
         return HTTPException(status_code=429, detail=COPY_LOGIN_THROTTLED)
     if isinstance(exc, PasswordCapacityError):
-        record_login_event(username=username, detail=AUDIT_PASSWORD_CAPACITY)
+        record_login_event(username=username, detail=AUDIT_PASSWORD_CAPACITY, action=action)
         return HTTPException(status_code=503, detail=COPY_PASSWORD_CAPACITY)
     raise exc
 
 
 @app.post("/api/auth/login")
 def login(http_request: Request, request: LoginRequest):
     username = request.username.strip()
     # 来源地址只认 `request.client.host`（当前 compose 前面没有反代，`X-Forwarded-For`
     # 是客户端自述的字符串，信任它等于把节流键交给攻击者挑）。
     client_ip = client_ip_of(http_request)
     try:
         result = authenticate_with_result(username, request.password, client_ip=client_ip)
@@ -374,38 +386,38 @@
         # 策略拒绝是一枚安全事实，不是一句被丢弃的返回值：脚本化地批量提交不合格新口令若
         # 不留痕，§9.1 的 `password_policy_rejected` 审计面就是空的（422 只到展示面）。
         _audit(user, "PASSWORD", status="DENIED", detail=AUDIT_PASSWORD_POLICY_REJECTED)
         raise HTTPException(status_code=422, detail=reason)
     try:
         # 这一跳带旧口令校验，所以它与登录是**同一个**猜测面：同一个 (username, client_ip)
         # 桶、同一份账号级锁定，不自造第二把计数器。异常翻译与登录腿共用同一个 helper——
         # 两条腿各抄一遍 except 就是留给"其中一条忘了 503"的那条缝。
         result = authenticate_with_result(
             user.username, request.current_password, client_ip=client_ip_of(http_request)
         )
     except (LoginThrottledError, PasswordCapacityError) as exc:
-        raise _auth_availability_denial(user.username, exc) from exc
+        raise _auth_availability_denial(user.username, exc, action="PASSWORD") from exc
     if result.user is None:
         # 四种失败态（含锁定期）到这里已经塌成同一条 401 + 同一段中文，与登录面一字不差；
         # 区别只在审计 token，而那个只进审计面。
         record_login_event(username=user.username, detail=result.audit_detail)
         raise HTTPException(status_code=401, detail="用户名或密码错误")
     try:
         provision_credentials(
             user.username, plain_password=request.new_password, must_change=False
         )
     except PasswordCapacityError as exc:
         # 写库那一次哈希也过同一道闸了（provisioning 不再在闸门外做同档运算），于是这条腿
         # 多出一格容量面。翻译仍取自那唯一一处 helper：文案与审计 token 都不许有第二份写法。
-        raise _auth_availability_denial(user.username, exc) from exc
+        raise _auth_availability_denial(user.username, exc, action="PASSWORD") from exc
     except CredentialStoreError as exc:
         # 存储事故（锁 / 盘满 / 约束）不是认证结论：翻成中文 500 + FAILED 审计，与既有
         # `文档处理失败` / `Demo 初始化失败` 两条腿同一形状；`public_exception_detail` 负责脱敏，
         # 异常消息与响应体都不带口令。CLI 腿对此映射 exit 1，两条写腿因此都不再漏裸栈。
         _audit(result.user, "PASSWORD", status="FAILED", detail=f"credential_write_failed:{public_exception_detail(exc)}")
         raise HTTPException(status_code=500, detail=f"凭据写入失败：{public_exception_detail(exc)}") from exc
     _audit(result.user, "PASSWORD", status="SUCCESS", detail="password_changed")
     return {
         "changed": True,
         "access_token": issue_token(result.user),
         "token_type": "bearer",
         # 读表而不是写死 False：这一格与 `require_user` 那道门用的是同一个谓词，两边读数一旦
@@ -440,25 +452,25 @@
         # 与自助改密腿同一枚 token、同一道理：重置腿的策略拒绝也得留痕，否则被拒的批量
         # 尝试在审计里追不到（§9.1）。展示面只有中文那句，值/长度/hash 一概不进事件。
         _audit(user, "PASSWORD", status="DENIED", detail=AUDIT_PASSWORD_POLICY_REJECTED)
         raise HTTPException(status_code=422, detail=reason)
     if get_user_identity(username) is None:
         raise HTTPException(status_code=404, detail="账号不存在")
     try:
         provision_credentials(username, plain_password=request.new_password, must_change=True)
     except PasswordCapacityError as exc:
         # 重置腿此前**够不到**容量面（写入侧不占槽），槽一进到 `hash_password` 它就是第三格：
         # 已鉴权的主体也不该被裸栈顶成 500。文案与 token 同样取自那唯一一处翻译，审计记的是
         # 拿到拒绝的那位（actor）；`target` 那一格另有它自己的登记，不在这里分叉。
-        raise _auth_availability_denial(user.username, exc) from exc
+        raise _auth_availability_denial(user.username, exc, action="PASSWORD") from exc
     except CredentialStoreError as exc:
         # 与自助改密腿同一条错误处理：存储事故翻成中文 500 + FAILED 审计，绝不漏裸栈（CLI 腿 exit 1）。
         _audit(user, "PASSWORD", status="FAILED", detail=f"credential_write_failed:{public_exception_detail(exc)}", target=username)
         raise HTTPException(status_code=500, detail=f"凭据写入失败：{public_exception_detail(exc)}") from exc
     # `username=actor` 记的是"谁干的"，`target` 记的是"对谁干的"：CLI 重置那腿 username 直接是
     # 受体，两条腿光看 username 会在 audit.jsonl 里混成一件事（detail 枚举止损又被 spec :405
     # 冻死，不许各造 per-face token）。加 `target` 才让 HTTP 重置腿与 CLI 重置腿在审计里分得开。
     _audit(user, "PASSWORD", status="SUCCESS", detail="password_reset_by_admin", target=username)
     return {"reset": True, "must_change": _password_change_required(username)}
 
 
 @app.get("/api/knowledge-bases")
diff -ruN -U12 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/security.py backend/app/security.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/security.py	2026-09-26 12:38:34.248079200 +0800
+++ backend/app/security.py	2026-09-26 13:10:29.368716800 +0800
@@ -276,12 +276,59 @@
 
 
 def _is_ratio(value: Any) -> bool:
     return isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 <= float(value) <= 1.0
 
 
 def _is_measurement(value: Any) -> bool:
     return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) >= 0.0
 
 
 def public_exception_detail(exc: BaseException) -> str:
     return f"{type(exc).__name__}: {redact_text(exc)}"
+
+
+# SEC-A-009 落盘面（持久化域）的**精确全词键名**黑名单。与响应面 `redact_secrets` 是两个
+# 作用域：这一张表只喂 `redact_for_persistence`（审计 / trace / 日志 / 遥测表），既不改
+# `redact_secrets` 的语义、也不作用于任何响应出口。刻意用整词等值匹配、绝不做子串——子串
+# `token` 会顺手抹掉 `input_tokens` / `output_tokens` / `total_tokens`（观测数据，非秘密）
+# 以及登录响应的 `token_type`，那等于砸掉 observability 契约（SECA-17 反方向）。
+# 入选理由（逐族）：口令族 `password` / `password_hash` / `plaintext_password` /
+# `current_password` / `new_password`；Bearer 令牌族 `access_token` / `refresh_token` /
+# `authorization`；provider / 集成凭据族 `api_key` / `app_secret` / `tenant_access_token` /
+# `secret`；泛用名 `credentials`。`tenant_access_token` 该抹却**不靠**子串兜——它自己进全词集。
+# 授权凭据库（`user_store` 写 hash 那一层）根本不经过这里（结构钉：它不 import `app.security`）；
+# 把这张表罩到凭据写入面上，落库的 hash 会被抹成占位符、下次登录必失败（M9）。
+PERSISTENCE_SENSITIVE_KEYS = frozenset(
+    {
+        "password", "password_hash", "plaintext_password", "current_password", "new_password",
+        "access_token", "refresh_token", "authorization", "api_key", "app_secret",
+        "tenant_access_token", "secret", "credentials",
+    }
+)
+
+
+def redact_for_persistence(value: Any) -> Any:
+    """落盘面（审计 / trace / 日志 / 遥测表）脱敏：形态匹配 + **精确键名**匹配。
+
+    刻意不做子串匹配：`token` 命中 tenant_access_token 也命中 input_tokens，
+    后者是观测数据不是秘密。授权凭据库（user_store）不经过这里（SEC-A-009）。
+
+    与 `redact_secrets` 的唯一差别就是那一步整词键名判定；形态脱敏（`redact_text`）
+    沿用同一枚函数，因此两域对"值里嵌着 apikey_/Bearer 形态"的处理一字不差。键名判定
+    只看 Mapping 的**键**（整词等值），不嗅探值内容——值里出现 "password" 这个词不会被误抹。
+    """
+    if isinstance(value, str):
+        return redact_text(value)
+    if isinstance(value, Mapping):
+        return {
+            redact_text(key): (
+                REDACTED if str(key).lower() in PERSISTENCE_SENSITIVE_KEYS
+                else redact_for_persistence(item)
+            )
+            for key, item in value.items()
+        }
+    if isinstance(value, list):
+        return [redact_for_persistence(item) for item in value]
+    if isinstance(value, tuple):
+        return tuple(redact_for_persistence(item) for item in value)
+    return value
diff -ruN -U12 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/security_startup.py backend/app/security_startup.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task9-pre-app/security_startup.py	1970-01-01 08:00:00.000000000 +0800
+++ backend/app/security_startup.py	2026-09-26 13:10:39.708771900 +0800
@@ -0,0 +1,63 @@
+"""生产形态的启动守卫（规格 §8.5）。三件守卫由一枚开关共同驱动，不存在矛盾组合。
+
+`SECURITY_ENTERPRISE_MODE=false`（默认）⇒ 本模块整体是 no-op：`evaluate_startup_guards`
+直接返回空列表，`assert_startup_safe` 因此永不抛。默认配置下启动不新增任何行为，这条
+不变量与 `warmup_identity_permissions` / `warmup_llm_router` 的前置判法同形（各自在内部
+按开关早退）。只有把总开关打到 true，下面三件才同生同死：
+
+- 默认 / 过短的 `JWT_SECRET` ⇒ 拒启动（默认值留在 `config.py` 是给测试形态的，不是给生产的）；
+- CORS 白名单缺失或含 `*` ⇒ 拒启动（收紧 origin 才是有效项，`allow_credentials` 保持 False）；
+- demo 身份 ⇒ 企业形态下 `directory` 根本不加载 `config/users.demo.json`（结构事实，
+  不在这张表里重复判，也不按用户名过滤）。
+
+守卫放在 `main.py` 的 lifespan 第一道，而不是模块顶层 import：顶层副作用会波及所有导入方
+（测试、脚本、`python -c "import app.main"`）。SECA-18 直接调用 `evaluate_startup_guards`
+断言三件同时生效，不依赖 lifespan 是否被执行。
+"""
+
+from __future__ import annotations
+
+#: 与 `app.config.Settings.jwt_secret` 的默认字面量同源。守卫靠"等于这枚值"识别出厂默认，
+#: 所以两处必须是**同一个字符串**——抄错一位就会把生产误判成不安全或把默认值放过。
+DEFAULT_JWT_SECRET = "change-me-before-production-yaoke-demo-secret"
+
+#: 企业形态下 JWT secret 的长度下限。出厂默认有 49 字符，单靠长度抓不到它，故"等于默认值"
+#: 与"短于 32"是两条独立判据：前者杀"忘了改"，后者杀"随手敲了枚短的"。
+_MIN_JWT_SECRET_LENGTH = 32
+
+
+class SecurityStartupError(RuntimeError):
+    """企业形态下配置不安全 ⇒ 拒绝启动。比第一个请求才炸好。"""
+
+
+def evaluate_startup_guards(
+    *, enterprise_mode: bool, jwt_secret: str, cors_allow_origins: str
+) -> list[str]:
+    """返回违规清单（空列表 = 通过）。三件守卫在同一枚开关下聚合，调用方据此一次报全。
+
+    非企业形态**直接早退**——dev / 测试形态允许默认 secret、允许空 CORS 白名单（走
+    `http://localhost:3000` 默认），这既是 §8.5 表的语义，也是"默认配置零额外启动行为"
+    这条不变量的来源。
+    """
+    if not enterprise_mode:
+        return []
+    violations: list[str] = []
+    if not jwt_secret or jwt_secret == DEFAULT_JWT_SECRET or len(jwt_secret) < _MIN_JWT_SECRET_LENGTH:
+        violations.append("SECURITY_ENTERPRISE_MODE 下 JWT_SECRET 必须是 ≥32 字符的非默认值")
+    origins = [item.strip() for item in (cors_allow_origins or "").split(",") if item.strip()]
+    if not origins or "*" in origins:
+        violations.append("SECURITY_ENTERPRISE_MODE 下 CORS_ALLOW_ORIGINS 必须是显式白名单")
+    return violations
+
+
+def assert_startup_safe() -> None:
+    """读 `settings` 跑一遍三守卫；有违规即抛。lifespan 第一道调它。"""
+    from app.config import settings
+
+    violations = evaluate_startup_guards(
+        enterprise_mode=bool(settings.security_enterprise_mode),
+        jwt_secret=str(settings.jwt_secret),
+        cors_allow_origins=str(settings.cors_allow_origins),
+    )
+    if violations:
+        raise SecurityStartupError("；".join(violations))
## new security_startup.py
     1	"""生产形态的启动守卫（规格 §8.5）。三件守卫由一枚开关共同驱动，不存在矛盾组合。
     2	
     3	`SECURITY_ENTERPRISE_MODE=false`（默认）⇒ 本模块整体是 no-op：`evaluate_startup_guards`
     4	直接返回空列表，`assert_startup_safe` 因此永不抛。默认配置下启动不新增任何行为，这条
     5	不变量与 `warmup_identity_permissions` / `warmup_llm_router` 的前置判法同形（各自在内部
     6	按开关早退）。只有把总开关打到 true，下面三件才同生同死：
     7	
     8	- 默认 / 过短的 `JWT_SECRET` ⇒ 拒启动（默认值留在 `config.py` 是给测试形态的，不是给生产的）；
     9	- CORS 白名单缺失或含 `*` ⇒ 拒启动（收紧 origin 才是有效项，`allow_credentials` 保持 False）；
    10	- demo 身份 ⇒ 企业形态下 `directory` 根本不加载 `config/users.demo.json`（结构事实，
    11	  不在这张表里重复判，也不按用户名过滤）。
    12	
    13	守卫放在 `main.py` 的 lifespan 第一道，而不是模块顶层 import：顶层副作用会波及所有导入方
    14	（测试、脚本、`python -c "import app.main"`）。SECA-18 直接调用 `evaluate_startup_guards`
    15	断言三件同时生效，不依赖 lifespan 是否被执行。
    16	"""
    17	
    18	from __future__ import annotations
    19	
    20	#: 与 `app.config.Settings.jwt_secret` 的默认字面量同源。守卫靠"等于这枚值"识别出厂默认，
    21	#: 所以两处必须是**同一个字符串**——抄错一位就会把生产误判成不安全或把默认值放过。
    22	DEFAULT_JWT_SECRET = "change-me-before-production-yaoke-demo-secret"
    23	
    24	#: 企业形态下 JWT secret 的长度下限。出厂默认有 49 字符，单靠长度抓不到它，故"等于默认值"
    25	#: 与"短于 32"是两条独立判据：前者杀"忘了改"，后者杀"随手敲了枚短的"。
    26	_MIN_JWT_SECRET_LENGTH = 32
    27	
    28	
    29	class SecurityStartupError(RuntimeError):
    30	    """企业形态下配置不安全 ⇒ 拒绝启动。比第一个请求才炸好。"""
    31	
    32	
    33	def evaluate_startup_guards(
    34	    *, enterprise_mode: bool, jwt_secret: str, cors_allow_origins: str
    35	) -> list[str]:
    36	    """返回违规清单（空列表 = 通过）。三件守卫在同一枚开关下聚合，调用方据此一次报全。
    37	
    38	    非企业形态**直接早退**——dev / 测试形态允许默认 secret、允许空 CORS 白名单（走
    39	    `http://localhost:3000` 默认），这既是 §8.5 表的语义，也是"默认配置零额外启动行为"
    40	    这条不变量的来源。
    41	    """
    42	    if not enterprise_mode:
    43	        return []
    44	    violations: list[str] = []
    45	    if not jwt_secret or jwt_secret == DEFAULT_JWT_SECRET or len(jwt_secret) < _MIN_JWT_SECRET_LENGTH:
    46	        violations.append("SECURITY_ENTERPRISE_MODE 下 JWT_SECRET 必须是 ≥32 字符的非默认值")
    47	    origins = [item.strip() for item in (cors_allow_origins or "").split(",") if item.strip()]
    48	    if not origins or "*" in origins:
    49	        violations.append("SECURITY_ENTERPRISE_MODE 下 CORS_ALLOW_ORIGINS 必须是显式白名单")
    50	    return violations
    51	
    52	
    53	def assert_startup_safe() -> None:
    54	    """读 `settings` 跑一遍三守卫；有违规即抛。lifespan 第一道调它。"""
    55	    from app.config import settings
    56	
    57	    violations = evaluate_startup_guards(
    58	        enterprise_mode=bool(settings.security_enterprise_mode),
    59	        jwt_secret=str(settings.jwt_secret),
    60	        cors_allow_origins=str(settings.cors_allow_origins),
    61	    )
    62	    if violations:
    63	        raise SecurityStartupError("；".join(violations))
## new scan/redaction test file
     1	"""SEC-A-009 / §8.5 / §10 / SECA-17 / SECA-18 / SECA-20 的契约（Task 9）。
     2	
     3	这个文件守的是三件事，各自都对应一次真实事故形状：
     4	
     5	1. **脱敏的两个作用域（SEC-A-009）**：响应面 `redact_secrets` 语义一字不动；落盘面
     6	   `redact_for_persistence` = 形态脱敏 + **精确全词键名**黑名单。两个方向都要有脸：敏感键
     7	   必抹（SECA-17 正向），观测键（`input_tokens` 那族）必不误伤（子串 `token` 会顺手砸掉
     8	   observability，即 M8）。授权凭据库 `user_store` 根本不经过任何 redactor（M9：结构钉）。
     9	2. **响应面 / 落盘面那条边界要用真实登录证**：同一枚 access_token，登录响应里必须是**能用**的
    10	   （客户端就靠它），落进遥测持久化面则必须被抹成占位符。一个"过宽的红actor"只有这条路能抓到。
    11	3. **三守卫同生同死（§8.5 / SECA-18）**：直接调用 `evaluate_startup_guards`，不借 lifespan。
    12	   外加启动守卫真实生效（真跑一遍 `assert_startup_safe`）与 root_path 下的无回显守卫（Task 7 移交的 P0）。
    13	
    14	扫描门（SECA-20）用一条普通 pytest 用例跑遍 tracked 文件，豁免表 == 命中表（`test_llm_egress_guard.py`
    15	同族做法）。口令变量 `CREDENTIALS_PASSWORD` 不得出现在 `.env.example`（SEC-A-002 配置半边）。
    16	"""
    17	
    18	from __future__ import annotations
    19	
    20	import asyncio
    21	import json
    22	import re
    23	import subprocess
    24	import sys
    25	import unittest
    26	from pathlib import Path
    27	from unittest import mock
    28	
    29	BACKEND_DIR = Path(__file__).resolve().parents[1]
    30	TESTS_DIR = BACKEND_DIR / "tests"
    31	for _entry in (str(BACKEND_DIR), str(TESTS_DIR)):
    32	    if _entry not in sys.path:
    33	        sys.path.insert(0, _entry)
    34	
    35	import pytest  # noqa: E402
    36	
    37	from app import agent_trace, audit, security, security_startup  # noqa: E402
    38	from app.credentials import PasswordCapacityError  # noqa: E402
    39	
    40	# --------------------------------------------------------------------------- #
    41	# SECA-17 正向：落盘面按精确全词键名抹敏感键
    42	# --------------------------------------------------------------------------- #
    43	
    44	NOT_SECRETS = ("input_tokens", "output_tokens", "num_sources", "total_tokens", "token_type")
    45	SECRETS = (
    46	    "password", "password_hash", "access_token", "refresh_token",
    47	    "authorization", "api_key", "app_secret", "tenant_access_token",
    48	)
    49	
    50	
    51	def test_persistence_redaction_kills_sensitive_keys_by_exact_name():
    52	    payload = {key: "sensitive-value" for key in SECRETS}
    53	    redacted = security.redact_for_persistence(payload)
    54	    assert all(redacted[key] == security.REDACTED for key in SECRETS), redacted
    55	
    56	
    57	def test_persistence_redaction_covers_the_full_deny_set_not_just_the_spec_sample():
    58	    """§9.3 的样本只列了几枚「等」；这张表里的每一枚都必须真的被抹（漏一枚即 M8 的另一半）。"""
    59	    for key in security.PERSISTENCE_SENSITIVE_KEYS:
    60	        assert security.redact_for_persistence({key: "v"})[key] == security.REDACTED, key
    61	
    62	
    63	def test_persistence_redaction_does_not_collateral_damage_observability_keys():
    64	    """SECA-17 的反方向：子串匹配 `token` 会顺手抹掉 usage 计数，那等于砸掉 observability 契约。
    65	
    66	    `token_type` 是**真实**的登录响应键（bearer），把它连同 `*_tokens` 一起抹掉的就是那个"过宽的
    67	    红actor"——正向能过不代表反方向能过，两向都得钉（M8 杀子串）。
    68	    """
    69	    payload = {"input_tokens": 12, "output_tokens": 34, "num_sources": 5,
    70	               "total_tokens": 46, "token_type": "bearer"}
    71	    assert payload == security.redact_for_persistence(payload)
    72	
    73	
    74	def test_persistence_redaction_recurses_and_never_sniffs_value_content():
    75	    """黑名单只看 dict 的**键**（整词），绝不嗅探值：值里出现 "password" 这个词不该被误抹。"""
    76	    nested = {"detail": "the word password appears here", "usage": {"input_tokens": 7}}
    77	    out = security.redact_for_persistence(nested)
    78	    assert out["detail"] == "the word password appears here"
    79	    assert out["usage"] == {"input_tokens": 7}
    80	
    81	
    82	def test_persistence_redaction_still_runs_shape_matching():
    83	    """落盘面 = 形态脱敏 ∪ 精确键名：值里嵌着 Bearer/apikey 形态时，形态那条腿照旧生效。"""
    84	    out = security.redact_for_persistence({"note": "header: Bearer abc.def.ghi"})
    85	    assert "Bearer [REDACTED]" in out["note"]
    86	
    87	
    88	# --------------------------------------------------------------------------- #
    89	# SEC-A-006：既有响应面 redact_secrets 语义一字不动
    90	# --------------------------------------------------------------------------- #
    91	
    92	def test_redact_secrets_semantics_are_unchanged():
    93	    """既有 28 处调用点的响应面语义一字不动（SEC-A-006）。"""
    94	    assert security.redact_secrets({"access_token": "keep-me"}) == {"access_token": "keep-me"}
    95	    assert "Bearer [REDACTED]" in security.redact_secrets("header: Bearer abc.def.ghi")
    96	
    97	
    98	def test_redact_secrets_does_not_apply_the_persistence_key_blacklist():
    99	    """两个域是**两个**函数：响应面绝不因键名抹掉 access_token（登录就发不出票了）。"""
   100	    body = {"access_token": "a-real.jwt.token", "password": "not-a-response-face"}
   101	    kept = security.redact_secrets(body)
   102	    assert kept == body, "响应面被落盘面的键名黑名单污染——登录/改密腿的 access_token 会被吃掉"
   103	
   104	
   105	def test_the_two_faces_differ_on_exactly_the_key_name_blacklist():
   106	    """两域唯一差别就是那一步整词键名判定；形态腿共用同一枚 redact_text。"""
   107	    # 同一枚 access_token 值（非 Bearer 形态）：响应面原样、落盘面抹成占位符。
   108	    fake = "eyJhbGciOiJIUzI1NiJ9.payload.sig"  # 变量名避开 token，免得测试自身撞扫描门的形态
   109	    assert security.redact_secrets({"access_token": fake})["access_token"] == fake
   110	    assert security.redact_for_persistence({"access_token": fake})["access_token"] == security.REDACTED
   111	    # 而两者对形态的腿完全一致（Bearer 值都被脱敏），证明我没往 redact_text 之外再造第二套形态匹配。
   112	    shared = security.redact_secrets({"note": "Bearer x.y.z"})["note"]
   113	    assert shared == security.redact_for_persistence({"note": "Bearer x.y.z"})["note"]
   114	
   115	
   116	# --------------------------------------------------------------------------- #
   117	# 结构钉（M9）：授权凭据库永不经过任何 redactor
   118	# --------------------------------------------------------------------------- #
   119	
   120	def test_user_store_is_never_passed_through_a_redactor():
   121	    """授权凭据库 ≠ 遥测面：把 redactor 罩到写凭据那一层，写进去的 hash 会被抹成占位符，
   122	    下一次登录必失败（M9 就是这条）。判据是"持久层 import 里没有它"。"""
   123	    source = (BACKEND_DIR / "app" / "user_store.py").read_text(encoding="utf-8")
   124	    assert "redact_for_persistence" not in source
   125	    assert "from app.security import" not in source
   126	    assert "app.security" not in source
   127	
   128	
   129	def test_the_four_persistence_faces_use_the_persistence_redactor():
   130	    """切换点钉死：只有 audit（写+读）与 agent_trace（存+取）这四张落盘面换了 redactor；
   131	    其余 24 处（含 8 处响应面 return）仍叫 redact_secrets。"""
   132	    audit_src = (BACKEND_DIR / "app" / "audit.py").read_text(encoding="utf-8")
   133	    trace_src = (BACKEND_DIR / "app" / "agent_trace.py").read_text(encoding="utf-8")
   134	    assert "redact_secrets" not in audit_src and audit_src.count("redact_for_persistence") >= 2
   135	    assert "redact_secrets" not in trace_src and trace_src.count("redact_for_persistence") >= 2
   136	
   137	
   138	# --------------------------------------------------------------------------- #
   139	# SECA-18：三件守卫同生同死（直接调用守卫函数，不借 lifespan）
   140	# --------------------------------------------------------------------------- #
   141	
   142	@pytest.mark.parametrize(
   143	    "kwargs, expected",
   144	    [
   145	        (dict(enterprise_mode=True, jwt_secret=security_startup.DEFAULT_JWT_SECRET,
   146	              cors_allow_origins="http://localhost:3000"), 1),
   147	        (dict(enterprise_mode=True, jwt_secret="x" * 48, cors_allow_origins="https://kb.example"), 0),
   148	        (dict(enterprise_mode=False, jwt_secret=security_startup.DEFAULT_JWT_SECRET,
   149	              cors_allow_origins=""), 0),
   150	        (dict(enterprise_mode=True, jwt_secret=security_startup.DEFAULT_JWT_SECRET,
   151	              cors_allow_origins=""), 2),
   152	        (dict(enterprise_mode=True, jwt_secret="short", cors_allow_origins="*"), 2),
   153	        (dict(enterprise_mode=True, jwt_secret="", cors_allow_origins=""), 2),
   154	    ],
   155	)
   156	def test_the_three_guards_live_or_die_together(kwargs, expected):
   157	    """SECA-18：企业形态下三件守卫同生同死，不允许"只落了 seed 半件"。"""
   158	    violations = security_startup.evaluate_startup_guards(**kwargs)
   159	    assert expected == len(violations), violations
   160	
   161	
   162	def test_default_config_makes_the_guard_a_total_noop():
   163	    """dev / 测试形态（默认）⇒ 启动守卫整体 no-op，兑现"默认配置零额外启动行为"。"""
   164	    assert security_startup.evaluate_startup_guards(
   165	        enterprise_mode=False,
   166	        jwt_secret=security_startup.DEFAULT_JWT_SECRET,
   167	        cors_allow_origins="",
   168	    ) == []
   169	
   170	
   171	def test_assert_startup_safe_refuses_under_enterprise_default_and_bools_clean_otherwise():
   172	    """守卫函数与真实 settings 的接线：企业开关 + 默认 secret ⇒ 抛；关 ⇒ 放行。"""
   173	    from app.config import Settings
   174	
   175	    with mock.patch("app.config.settings",
   176	                    Settings(security_enterprise_mode=True,
   177	                             jwt_secret=security_startup.DEFAULT_JWT_SECRET,
   178	                             cors_allow_origins="")):
   179	        with pytest.raises(security_startup.SecurityStartupError):
   180	            security_startup.assert_startup_safe()
   181	    with mock.patch("app.config.settings",
   182	                    Settings(security_enterprise_mode=False,
   183	                             jwt_secret=security_startup.DEFAULT_JWT_SECRET,
   184	                             cors_allow_origins="")):
   185	        security_startup.assert_startup_safe()  # 不抛
   186	
   187	
   188	# --------------------------------------------------------------------------- #
   189	# §10 / SEC-A-002 配置半边：.env.example 键集合
   190	# --------------------------------------------------------------------------- #
   191	
   192	def test_env_example_never_carries_a_credential_env_var():
   193	    """SEC-A-002 的配置面半边：CREDENTIALS_PASSWORD 是一次性 CLI 变量。
   194	
   195	    `.env` 由服务进程加载，把它写进模板等于让明文口令常驻配置面。
   196	    """
   197	    text = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8")
   198	    keys = {line.split("=", 1)[0].strip() for line in text.splitlines()
   199	            if "=" in line and not line.strip().startswith("#")}
   200	    assert not {key for key in keys if "PASSWORD" in key.upper()}, sorted(keys)
   201	    assert "SECURITY_ENTERPRISE_MODE" in keys
   202	    assert "CORS_ALLOW_ORIGINS" in keys
   203	    assert "CREDENTIALS_PASSWORD" not in keys
   204	
   205	
   206	# --------------------------------------------------------------------------- #
   207	# SECA-20：仓库扫描门（豁免表 == 命中表，与 test_llm_egress_guard.py 同族）
   208	# --------------------------------------------------------------------------- #
   209	
   210	CREDENTIAL_PATTERN = re.compile(
   211	    r"(?i)\b(?:api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{16,}"
   212	)
   213	
   214	# 豁免表逐项写成"文件:行 + 为什么它不是凭据"，且必须与命中集相等——只增不减的豁免表等于没
   215	# 有豁免表（M：命中表漂了豁免表不跟着动，下一次就漏）。这三枚都是测试内的假值，逐条点名。
   216	EXEMPT_HITS: frozenset[str] = frozenset({
   217	    # 测试内构造的假 feishu app-secret 声明值，只为占位一个 claim 面，不是任何真凭据。
   218	    "backend/tests/test_feishu_identity_contract.py:1856",
   219	    # 断言"这枚 typesafe key 绝不能被流出去"的字面量，是测试自己的诱饵值。
   220	    "backend/tests/test_typesafe_api_runtime.py:126",
   221	    # 同上：判定层"绝 persisted"的诱饵 key，测试用假值。
   222	    "backend/tests/test_typesafe_judgments.py:216",
   223	})
   224	
   225	_BINARY_SUFFIXES = {".png", ".webp", ".ico", ".woff", ".woff2", ".pyc"}
   226	
   227	
   228	def _scan_sites() -> list[tuple[str, str]]:
   229	    """遍历 tracked 文件，返回 `[(相对路径:行, 命中片段)]`。扫描逻辑只有这一份实现。"""
   230	    listing = subprocess.run(
   231	        ["git", "ls-files", "-z"], cwd=BACKEND_DIR.parent, capture_output=True, check=True
   232	    )
   233	    found: list[tuple[str, str]] = []
   234	    for raw in listing.stdout.split(b"\0"):
   235	        if not raw:
   236	            continue
   237	        relative = raw.decode("utf-8", "replace")
   238	        path = BACKEND_DIR.parent / relative
   239	        if not path.is_file() or path.suffix in _BINARY_SUFFIXES:
   240	            continue
   241	        text = path.read_text(encoding="utf-8", errors="ignore")
   242	        for match in CREDENTIAL_PATTERN.finditer(text):
   243	            site = f"{relative}:{text[:match.start()].count(chr(10)) + 1}"
   244	            found.append((site, match.group(0)[:24]))
   245	    return found
   246	
   247	
   248	def _scan_hits() -> set[str]:
   249	    return {site for site, _snippet in _scan_sites()}
   250	
   251	
   252	def test_repository_tracked_files_hold_no_credential_material():
   253	    """SECA-20：扫描是普通 pytest 用例，本地与既有 CI job 同一道门。"""
   254	    offenders: list[str] = []
   255	    for site, snippet in _scan_sites():
   256	        if site in EXEMPT_HITS:
   257	            continue
   258	        offenders.append(f"{site} {snippet}")
   259	    assert [] == offenders, (
   260	        "tracked 文件出现凭据形态取值，请加豁免前先确认它不是真凭据：" + "; ".join(offenders)
   261	    )
   262	
   263	
   264	def test_the_exemption_table_matches_the_hit_set():
   265	    """反向闸：豁免表里每一行都必须在真实命中集中——把表放大一档（多列一个不命中的行）立刻红。"""
   266	    assert {str(item) for item in EXEMPT_HITS} == _scan_hits()
   267	
   268	
   269	# --------------------------------------------------------------------------- #
   270	# 真实登录两向边界 + Task 7 移交的 root_path 无回显守卫 + 可用性事件归属
   271	# --------------------------------------------------------------------------- #
   272	
   273	import sec_a_fixtures  # noqa: E402
   274	from sec_a_seed import ensure_demo_credentials  # noqa: E402
   275	
   276	
   277	class _LoginHarness(sec_a_fixtures.LongJwtSecretMixin,
   278	                    sec_a_fixtures.AuditToTempFileMixin, unittest.TestCase):
   279	    """一份临时库 + 临时审计 + 够长 JWT secret + 真 app：真实登录用它拿真 token，而不是编一个。
   280	
   281	    `SECRET` 是 ≥32 字节：默认 dev secret（31B）会让每次签发/校验各多一句
   282	    `InsecureKeyLengthWarning`，那会把整套件的警告基线挪走——套件警告数不变是本仓的回归信号。
   283	    """
   284	
   285	    SECRET = ("sec-a-hygiene-login-harness-jwt" "-secret-key-40b")  # ≥32B；拆两段免被扫描门当凭据
   286	
   287	    def setUp(self) -> None:
   288	        from fastapi.testclient import TestClient
   289	
   290	        from app.main import app as fastapi_app
   291	
   292	        super().setUp()
   293	        sec_a_fixtures.fresh_db(self)
   294	        ensure_demo_credentials()
   295	        self.addCleanup(lambda: __import__("app.login_throttle", fromlist=["pre_hash_throttle"])
   296	                        .pre_hash_throttle.reset())
   297	        self.client = TestClient(fastapi_app)
   298	
   299	    def _login(self, username: str, password: str):
   300	        return self.client.post("/api/auth/login",
   301	                                json={"username": username, "password": password})
   302	
   303	
   304	class LoginResponseVsPersistenceBoundaryTests(_LoginHarness):
   305	    def test_real_login_token_is_usable_yet_erased_in_a_persistence_row(self):
   306	        """唯一能抓"过宽红actor"的证法：同一枚真 token，响应面能用、落盘面被抹。"""
   307	        resp = self._login("admin", "admin123")
   308	        self.assertEqual(200, resp.status_code, resp.text)
   309	        body = resp.json()
   310	        token = body["access_token"]
   311	        # 响应面：token 不但在，而且**可用**（拿它打 /api/auth/me ⇒ 200）。红actor 若罩到响应面，
   312	        # 这一步就会 401——这是"登录还能不能用"的真实回归哨兵。
   313	        self.assertIsInstance(token, str)
   314	        self.assertNotEqual(security.REDACTED, token)
   315	        me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
   316	        self.assertEqual(200, me.status_code, me.text)
   317	        self.assertEqual("admin", me.json()["username"])
   318	
   319	        # 落盘面（真实持久化面 agent_trace 的存 + 取）：同一枚值必须被抹成占位符。
   320	        trace_file = self.tmp_trace()

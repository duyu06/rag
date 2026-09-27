# Task 6 review package (base = snap-task6-pre-*)
## stat
Files .superpowers/sdd/SECURITY_A_PLAN/snap-task6-pre-app/auth.py and backend/app/auth.py differ
Files .superpowers/sdd/SECURITY_A_PLAN/snap-task6-pre-app/main.py and backend/app/main.py differ
## app diff
diff -ruN -U14 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task6-pre-app/auth.py backend/app/auth.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task6-pre-app/auth.py	2026-09-26 04:04:31.678374500 +0800
+++ backend/app/auth.py	2026-09-26 04:45:28.052255100 +0800
@@ -283,66 +283,91 @@
         detail,
         must_change,
     )
 
 
 def authenticate(username: str, password: str) -> CurrentUser | None:
     """既有契约：仍然只回答"这个口令能不能换到一个会话主体"。
 
     HTTP 面要的是 `LoginResult`（审计 token 与门状态），这里保留 `user | None` 是给
     CLI 与既有调用方——两条腿走的是同一个 `authenticate_with_result`，不存在第二套判定。
     """
     return authenticate_with_result(username, password).user
 
 
+#: 令牌生命周期 claim 的名字（§7.5）。签发与鉴权两侧都从这里取值：字面量抄两遍就是
+#: 留给"两侧拼写劈叉"的那条缝，而真劈了的症状是每次请求都 401「无效登录凭证」，
+#: 排查方向会被带到口令上而不是 claim 名上。
+CREDENTIAL_VERSION_CLAIM = "cv"
+
+
 def issue_token(user: CurrentUser) -> str:
     now = datetime.now(timezone.utc)
+    record = user_store.get_record(user.username)
     payload = {
         "sub": user.username,
         "name": user.display_name,
         "role": user.role,
         # access_role 仅为兼容展示用（旧客户端会解 JWT 拿它做角标），鉴权不读该字段：
         # require_user 每请求按身份声明文件重解析授予，token 里的 role/access_role 都不信。
         # 保留 claim 以免打断既有外部消费方；契约测试同时钉住"claim 还在"与"鉴权不读它"。
         "access_role": user.access_role,
         "iat": int(now.timestamp()),
         "exp": int((now + timedelta(hours=settings.jwt_expire_hours)).timestamp()),
         "iss": "yaoke",
+        # 凭据纪元（§7.5）：这枚 token 属于哪一代凭据。鉴权判定的权威是表里那一行，claim
+        # 只是"要比哪个版本"的提示——与上面 role/access_role 同一条不信任口径。
+        # 无凭据行 ⇒ 0，不是"随手给个值"：0 与表内任何真实版本（首版恒 1）都不等，于是这枚
+        # token 一签发即死，正是"有身份无凭据"那个主体应有的行为；同时 `CurrentUser` 的构造
+        # 面不因身份类型分裂成第二条路径（两扇门迟早会在 grant 语义上劈叉）。
+        CREDENTIAL_VERSION_CLAIM: int(record.credentials_version) if record else 0,
     }
     return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
 
 
 def _user_from_token(authorization: str | None) -> CurrentUser:
     if not authorization or not authorization.startswith("Bearer "):
         raise HTTPException(status_code=401, detail="请先登录")
     token = authorization[7:].strip()
     try:
         payload = jwt.decode(
             token,
             settings.jwt_secret,
             algorithms=["HS256"],
             issuer="yaoke",
         )
     except jwt.ExpiredSignatureError as exc:
         raise HTTPException(status_code=401, detail="登录已过期，请重新登录") from exc
     except jwt.InvalidTokenError as exc:
         raise HTTPException(status_code=401, detail="无效登录凭证") from exc
 
     username = str(payload.get("sub", ""))
     identity = directory.get_identity(username)
-    if identity is None:
-        # 「账号不存在」并入既有文案（§9.1）：过去这条单列一句中文，等于在响应面上区分
-        # "这个用户名曾经存在过"。验签已经过了，这里说的只是"这个主体我不认识"。
+    record = user_store.get_record(username)
+    if identity is None or not identity.enabled or record is None:
+        # 「账号不存在」并入通用文案（§9.1）：原 `auth.py:230` 的单列 detail 是一条存在性指纹。
+        # 三种状态（不认识主体 / 身份已停用 / 有身份无凭据行）在这里同形，与登录腿那四态合一
+        # 是一个口径：撤销这件事不许长成"我能区分你属于哪一种"的一条新枚举面。
+        raise HTTPException(status_code=401, detail="无效登录凭证")
+    # 读表判定，不信 claim 的值：claim 只回答"要比哪个版本"，权威是 `user_store` 那一行。
+    # 缺 claim **即视为不符**（SECA-09b）——"`cv` 为 None 就放行"不是向后兼容，是把 §7.5
+    # 整条撤销通道让出去；代价如实记为"SEC-A 上线时旧会话强制重新登录一次"。
+    # `bool` 单独挡掉：`True == 1`，版本号是整数，不许它经弱等值混成一次匹配。
+    claimed = payload.get(CREDENTIAL_VERSION_CLAIM)
+    if isinstance(claimed, bool) or not isinstance(claimed, int):
+        raise HTTPException(status_code=401, detail="无效登录凭证")
+    if claimed != record.credentials_version:
+        # 改密 / 重置 / 停用会 bump 版本或删除凭据行 ⇒ 全部已发 token 即刻作废，不等 `exp`。
         raise HTTPException(status_code=401, detail="无效登录凭证")
 
     # 授予每请求重解析：token 只证明身份，角色/范围不信任 JWT 里的旧值。
     grant = resolve_for_user(identity.username, identity.role, identity)
     return _user_from(identity, grant)
 
 
 def require_user(
     authorization: Annotated[str | None, Header()] = None,
 ) -> CurrentUser:
     user = _user_from_token(authorization)
     if _password_change_required(user.username):
         # 展示面中文、审计面枚举 token，与 enforce_permission 既有的
         # AUTHORIZATION/DENIED/missing_permission=X 同构（规格 §9.1 两栏）。
diff -ruN -U14 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task6-pre-app/main.py backend/app/main.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task6-pre-app/main.py	2026-09-26 04:04:31.575811000 +0800
+++ backend/app/main.py	2026-09-26 04:48:42.317382500 +0800
@@ -7,28 +7,29 @@
 from collections import Counter
 from contextlib import asynccontextmanager
 from datetime import datetime
 from pathlib import Path
 from typing import Any, Literal
 
 from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
 from fastapi.middleware.cors import CORSMiddleware
 from fastapi.responses import FileResponse, StreamingResponse
 from pydantic import BaseModel, Field
 
 from app.audit import recent_events, record_event, today_summary
 from app.auth import (
     CurrentUser,
+    _password_change_required,
     authenticate_with_result,
     has_permission,
     issue_token,
     record_login_event,
     require_permission,
     require_user_pending_password,
 )
 from app.config import settings
 from app.demo import demo_status, initialize_demo, reset_demo
 from app.identity import warmup as warmup_identity_permissions
 from app.ingestion import DOC_DIR, SUPPORTED_SUFFIXES, document_path
 from app.knowledge import get_base, resolve_for, visible_for
 from app.knowledge_os import (
     is_document_excluded,
@@ -244,34 +245,39 @@
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
         "access_token": issue_token(user),
         "token_type": "bearer",
         "user": user.model_dump(),
+        # §11 声明的本版唯一一处响应面键集合变化（additive）。值取自登录腿已经算好的那一格，
+        # 不在这里再查一次表：同一条判定有两个读数点，早晚会在"登录刚置门"这类中间态上劈叉。
+        "password_change_required": result.password_change_required,
     }
 
 
 @app.get("/api/auth/me")
 def me(user: CurrentUser = Depends(require_user_pending_password)):
-    return user.model_dump()
+    # 同一个布尔键在这里必须**读表**：`/me` 拿到的是任意时刻的既有 token，签发那一刻的门状态
+    # 早就不是当前事实了（改密页与前端引导都靠这一格判断要不要留在改密流程里）。
+    return {**user.model_dump(), "password_change_required": _password_change_required(user.username)}
 
 
 @app.get("/api/knowledge-bases")
 def knowledge_bases(user: CurrentUser = Depends(require_permission("knowledge:read"))):
     return {"knowledge_bases": visible_for(user)}
 
 
 @app.get("/api/stats")
 def stats(
     knowledge_base_id: str | None = Query(default=None),
     user: CurrentUser = Depends(require_permission("knowledge:read")),
 ):
     kb_ids = _allowed_ids(user, knowledge_base_id)
     try:

## new test file (full)
     1	"""令牌生命周期的契约（规格 §7.5 / §8.4 / §9.1 / §11，SECA-09 / SECA-09b / SECA-10）。
     2	
     3	四件事，各自的形状：
     4	
     5	1. **`cv` 说的是"这枚 token 属于哪一代凭据"**：`issue_token` 从表里读当前版本写进 payload，
     6	   `_user_from_token` 再拿它去比对**表里的当前值**。claim 只回答"要比哪个版本"，判定权在
     7	   `user_store`——与"鉴权不读 JWT 里的 role/access_role"同族：能签出这枚 token 的那把秘密
     8	   同样能签出任何版本号，所以 claim 从来不是权威，只是提示。
     9	2. **claim 缺失即不符（SECA-09b）**：签名有效但 payload 里没有 `cv`（SEC-A 之前签发的全部
    10	   会话）一律 401，与普通过期同形。"`cv is None` 就放行"那种兼容分支不是兼容，是把 §7.5
    11	   整条撤销通道让出去。代价如实记着：**上线那一刻所有旧会话强制重新登录一次**，
    12	   这是安全升级里可解释的一次性事件，不粉饰成无感升级。
    13	3. **改密 / 重置 / 停用即废全部已发 token，不等 `exp`**。停用是**成对动作**（§6.4：身份侧置
    14	   `enabled=false` + 凭据侧删行或 bump）。两半这里各自也被钉住，且理由不是"多做一遍"：
    15	   身份文件按形态缓存在进程里，改文件不改缓存 ⇒ 真正对在线会话立即生效的那一半永远是
    16	   凭据侧，只钉身份侧会把一条运维假设当成契约。
    17	4. **`must_change` 门的覆盖面由路由表自证**（SECA-10）：走 `require_user` / `require_permissions`
    18	   的每条端点都必须真 403 + 中文文案；走 `require_user_pending_password` 的端点集合
    19	   **恰好等于**白名单（漏一条即红，多一条也红）。手写清单随端点增长必然失真，所以清单由
    20	   遍历依赖树生成；带未登记 path 参数的新端点**主动 fail 并要求登记样例**，而不是猜一个值
    21	   混过去。
    22	
    23	响应面另有单独一枚钉子：本版**唯一**一处键集合变化是 `POST /api/auth/login` 与
    24	`GET /api/auth/me` 各多 `password_change_required: bool`（§11），值读表不读 claim；其余端点的
    25	键集合由既有契约钉住（`/api/query` 那三枚在本文件之外，跑到红就是本任务做错了）。
    26	
    27	已知边界（写在这里，不留给下一个人猜）：第 4 项判的是"**已被认证覆盖的**端点有没有都过门"。
    28	一条压根不挂任何认证依赖的端点、或自造第三条依赖绕开这两个门面的端点，不在本门的判定对象内
    29	（前者属"根本没鉴权"那一类缺陷，后者要靠评审看 diff）；本枚门不假装覆盖它们。
    30	"""
    31	
    32	from __future__ import annotations
    33	
    34	import contextlib
    35	import hashlib
    36	import json
    37	import os
    38	import sys
    39	import tempfile
    40	import unittest
    41	from pathlib import Path
    42	from typing import Callable
    43	from unittest import mock
    44	
    45	import jwt as pyjwt
    46	from fastapi import HTTPException
    47	from fastapi.routing import APIRoute
    48	from fastapi.testclient import TestClient
    49	
    50	BACKEND_DIR = Path(__file__).resolve().parents[1]
    51	TESTS_DIR = BACKEND_DIR / "tests"
    52	for _path in (str(BACKEND_DIR), str(TESTS_DIR)):
    53	    if _path not in sys.path:
    54	        sys.path.insert(0, _path)
    55	
    56	from app import audit as audit_module  # noqa: E402
    57	from app import auth, credentials, directory, user_store  # noqa: E402
    58	from app import config as config_module  # noqa: E402
    59	import app.main_agent  # noqa: E402,F401  —— uvicorn 跑的是 `app.main_agent:app`：三张 router 挂在同一个 app 实例上，少 import 这一行，覆盖面就只剩半张表
    60	from app.main import app  # noqa: E402
    61	from sec_a_seed import ensure_demo_credentials  # noqa: E402
    62	
    63	INVALID_TOKEN = "无效登录凭证"
    64	GATE_COPY = "当前账号需先修改口令"
    65	GOOD_PASSWORD = "a-good-password 123456"
    66	NEW_PASSWORD = "a-brand-new-password 123"
    67	LEGACY_ADMIN = hashlib.sha256(b"admin123").hexdigest()
    68	
    69	#: 本文件唯一认识的 HTTP 方法字母表。`PATCH` 必须在内——会话标题与评测失败案例两条腿就是
    70	#: PATCH，字母表漏一项等于那两条端点从枚举里静默消失（门再红也轮不到它们）。
    71	_HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
    72	
    73	
    74	def _identity(username: str, *, role: str = "VIEWER", enabled: bool = True,
    75	              feishu_open_id: str | None = None) -> directory.UserIdentity:
    76	    return directory.UserIdentity(
    77	        username=username, display_name=username.title(), role=role,
    78	        enabled=enabled, feishu_open_id=feishu_open_id,
    79	    )
    80	
    81	
    82	def _bearer(token: str) -> dict[str, str]:
    83	    return {"Authorization": f"Bearer {token}"}
    84	
    85	
    86	def _fresh_db(test: unittest.TestCase) -> Path:
    87	    """把**当前生效库**换成一份临时文件并建好凭据表。
    88	
    89	    只换 env、不 reload 模块：`user_store` 每次连接现读 env，换 env 就换完了库；
    90	    `importlib.reload(user_store)` 会把会话护栏挂在它上面的两道闸换回裸函数。
    91	    每例一份库是必需的：本文件的用例反复 bump / 删除凭据行，共用一份就是在共享状态里
    92	    互相踩对方的 token 生命周期。
    93	    """
    94	    holder = tempfile.TemporaryDirectory()
    95	    target = Path(holder.name) / "lifecycle.db"
    96	    saved = os.environ.get("CONVERSATION_DB_PATH")
    97	    os.environ["CONVERSATION_DB_PATH"] = str(target)
    98	    user_store.ensure_user_credentials_schema()
    99	
   100	    def restore():
   101	        if saved is None:
   102	            os.environ.pop("CONVERSATION_DB_PATH", None)
   103	        else:
   104	            os.environ["CONVERSATION_DB_PATH"] = saved
   105	        holder.cleanup()
   106	
   107	    test.addCleanup(restore)
   108	    return target
   109	
   110	
   111	class _LongJwtSecret:
   112	    """用例自带一枚够长的 JWT secret（≥32 字节）。
   113	
   114	    默认 dev secret 短于 PyJWT 的建议下限，每次签发/校验都喊一句 `InsecureKeyLengthWarning`；
   115	    本文件签的 token 数量比认证腿多一个量级，警告计数跟着漂的话，"套件警告数不变"这枚
   116	    回归信号就废了。选配的写法与认证腿一致：换 `settings.jwt_secret`，不静音警告。
   117	    """
   118	
   119	    SECRET = "sec-a-token-lifecycle-test-secret-0123456789abcdef"
   120	
   121	    def setUp(self):
   122	        super().setUp()
   123	        patcher = mock.patch.object(config_module.settings, "jwt_secret", self.SECRET)
   124	        patcher.start()
   125	        self.addCleanup(patcher.stop)
   126	
   127	
   128	class _AuditToTempFile:
   129	    """审计落到临时文件：既取到证，又不往仓库的 `data/audit.jsonl` 里写测试笔迹。"""
   130	
   131	    def setUp(self):
   132	        super().setUp()
   133	        holder = tempfile.TemporaryDirectory()
   134	        self.addCleanup(holder.cleanup)
   135	        self.audit_path = Path(holder.name) / "audit.jsonl"
   136	        patcher = mock.patch.object(audit_module, "AUDIT_PATH", self.audit_path)
   137	        patcher.start()
   138	        self.addCleanup(patcher.stop)
   139	
   140	    def events(self) -> list[dict]:
   141	        if not self.audit_path.is_file():
   142	            return []
   143	        return [
   144	            json.loads(line)
   145	            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
   146	            if line.strip()
   147	        ]
   148	
   149	
   150	def _decode(token: str) -> dict:
   151	    return pyjwt.decode(token, _LongJwtSecret.SECRET, algorithms=["HS256"], issuer="yaoke")
   152	
   153	
   154	# --------------------------------------------------------------------------
   155	# 依赖树枚举（SECA-10 的清单生成器）
   156	# --------------------------------------------------------------------------
   157	def _route_keys(route: APIRoute) -> tuple[str, ...]:
   158	    """一条路由拆成若干 `"METHOD path"`；挂了多个方法就逐个算，绝不折成一项。
   159	
   160	    只取第一个方法那条写法会把 `GET+POST` 同路径的第二个方法静默丢出覆盖面。今天的表里
   161	    每行都只有一个方法（`MustChangeGateCoverageTests` 另钉一条"没有多方法路由"，
   162	    长出那一天这条拆行逻辑必须跟着改判据，而不是让它继续只报第一项）。
   163	    """
   164	    methods = sorted(set(getattr(route, "methods", set()) or ()) & set(_HTTP_METHODS))
   165	    return tuple(f"{method} {route.path}" for method in methods)
   166	
   167	
   168	def _uses_dependency(dependant, predicate: Callable[[object], bool]) -> bool:
   169	    for sub in dependant.dependencies:
   170	        if predicate(sub.call) or _uses_dependency(sub, predicate):
   171	            return True
   172	    return False
   173	
   174	
   175	def _routes_where(predicate: Callable[[object], bool]) -> set[str]:
   176	    hits: set[str] = set()
   177	    for route in app.routes:
   178	        dependant = getattr(route, "dependant", None)
   179	        if not isinstance(route, APIRoute) or dependant is None:
   180	            continue
   181	        if _uses_dependency(dependant, predicate):
   182	            hits.update(_route_keys(route))
   183	    return hits
   184	
   185	
   186	def _routes_using(target: Callable[..., object]) -> set[str]:
   187	    """返回"这条路由的依赖树经过该依赖"的端点集合。
   188	
   189	    认两件事：① 依赖函数本身（按对象身份，`require_user` 这类直接依赖）；② 依赖**工厂**
   190	    造出的那个闭包——`require_permissions("x")` 交给路由的是函数体内定义的 `dependency`，
   191	    按对象身份永远比不上（每次调用都是新的一枚），于是按限定 qualname 认。
   192	    ② 认不出来也不构成漏覆盖：那枚闭包自己 `Depends(require_user)`，① 那条腿照样把它
   193	    底下整棵子树收进 `authenticated`。② 存在的意义是让"权限族"这件事在清单上**指名可见**，
   194	    而不是靠一条隐式包含关系撑着。
   195	    """
   196	    name = getattr(target, "__name__", "")
   197	    return _routes_where(
   198	        lambda call: call is target
   199	        or getattr(call, "__qualname__", "") == f"{name}.<locals>.dependency"
   200	    )
   201	
   202	
   203	class TokenClaimTests(_LongJwtSecret, unittest.TestCase):
   204	    """签发面：`cv` 从表里读，其余 claim 一字不少（SEC-A-006）。"""
   205	
   206	    def setUp(self):
   207	        super().setUp()
   208	        _fresh_db(self)
   209	        ensure_demo_credentials("admin")
   210	        self.identity = _identity("admin", role="ADMIN")
   211	
   212	    def _token(self) -> str:
   213	        with directory.override_identities({"admin": self.identity}):
   214	            return auth.issue_token(auth._user_from(self.identity, None))
   215	
   216	    def test_the_issued_token_carries_the_current_table_version(self):
   217	        claimed = _decode(self._token())[auth.CREDENTIAL_VERSION_CLAIM]
   218	        self.assertEqual(user_store.get_record("admin").credentials_version, claimed)
   219	        self.assertEqual("cv", auth.CREDENTIAL_VERSION_CLAIM)
   220	
   221	    def test_the_claim_moves_with_the_table_after_a_password_change(self):
   222	        """两枚 token 各自钉住自己那一代：改密后重签的那一枚才跟着表走。"""
   223	        before = _decode(self._token())[auth.CREDENTIAL_VERSION_CLAIM]
   224	        user_store.set_password_argon2(
   225	            "admin", plain_password=NEW_PASSWORD, must_change=False
   226	        )
   227	        after = _decode(self._token())[auth.CREDENTIAL_VERSION_CLAIM]
   228	        self.assertEqual(before + 1, after)
   229	
   230	    def test_the_progressive_rehash_does_not_move_the_claim(self):
   231	        """登录把 legacy 行原地换成 argon2id 时**不** bump 版本 ⇒ 会话不该被这次收敛打断。
   232	
   233	        这一枚钉的是 claim 的取值口径：`cv` 是"凭据换代"的纪元，不是"这一行被写过"的计数。
   234	        把它写成后者会在每次渐进重哈希时把用户踢下线，而 §8.3 明确说收敛不改会话。
   235	        """
   236	        user_store.delete_record("admin")
   237	        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
   238	        user = auth.authenticate("admin", "admin123")
   239	        self.assertIsNotNone(user)
   240	        record = user_store.get_record("admin")
   241	        self.assertEqual(credentials.ALGORITHM_ARGON2ID, record.algorithm)
   242	        with directory.override_identities({"admin": self.identity}):
   243	            token = auth.issue_token(auth._user_from(self.identity, None))
   244	        self.assertEqual(record.credentials_version,
   245	                         _decode(token)[auth.CREDENTIAL_VERSION_CLAIM])
   246	        self.assertEqual(1, record.credentials_version)
   247	
   248	    def test_the_pre_existing_claims_are_all_still_issued(self):
   249	        """加一枚 `cv` 不许顺手改掉任何一枚既有 claim：外部消费方在解这个 payload。"""
   250	        payload = _decode(self._token())
   251	        self.assertTrue(
   252	            {"sub", "name", "role", "access_role", "iat", "exp", "iss", "cv"}
   253	            <= set(payload),
   254	            sorted(payload),
   255	        )
   256	        self.assertEqual("yaoke", payload["iss"])
   257	        self.assertEqual("ADMIN", payload["role"])
   258	
   259	
   260	class TokenRevocationTests(_LongJwtSecret, unittest.TestCase):
   261	    """SECA-09 / SECA-09b：验签之后还要过身份、凭据、版本三关。"""
   262	
   263	    def setUp(self):
   264	        super().setUp()
   265	        _fresh_db(self)
   266	        user_store.create_argon2("revoker", plain_password=GOOD_PASSWORD, must_change=False)
   267	        self.identity = _identity("revoker")
   268	        with directory.override_identities({"revoker": self.identity}):
   269	            self.token = auth.issue_token(auth._user_from(self.identity, None))
   270	
   271	    @contextlib.contextmanager
   272	    def _known(self, *identities: directory.UserIdentity):
   273	        mapping = {item.username: item for item in identities}
   274	        with directory.override_identities(mapping):
   275	            yield
   276	
   277	    def _require(self, token: str):
   278	        return auth.require_user(f"Bearer {token}")
   279	
   280	    def test_a_bumped_version_invalidates_the_previously_issued_token(self):
   281	        """SECA-09：改密即废 token，不等 `exp`。"""
   282	        with self._known(self.identity):
   283	            self.assertIsInstance(self._require(self.token), auth.CurrentUser)
   284	            user_store.set_password_argon2(
   285	                "revoker", plain_password=NEW_PASSWORD, must_change=False
   286	            )
   287	            with self.assertRaises(HTTPException) as raised:
   288	                self._require(self.token)
   289	        self.assertEqual(401, raised.exception.status_code)
   290	        self.assertEqual(INVALID_TOKEN, raised.exception.detail)
   291	
   292	    def test_a_reissued_token_after_the_change_works_again(self):
   293	        """撤销的是**那一代**凭据，不是这个账号：新版本签出的 token 照常通。
   294	
   295	        少这一枚反钉，"旧 token 被拒"的实现可以顺手把整条令牌腿判成死（例如恒定 401），
   296	        而正向用例照样绿。
   297	        """
   298	        user_store.set_password_argon2("revoker", plain_password=NEW_PASSWORD, must_change=False)
   299	        with self._known(self.identity):
   300	            fresh = auth.issue_token(auth._user_from(self.identity, None))
   301	            self.assertEqual("revoker", self._require(fresh).username)
   302	
   303	    def test_a_pre_seca_token_without_cv_is_rejected_not_allowed(self):
   304	        """SECA-09b：M17 的靶子——"兼容旧 token"的放行分支必须撞红。"""
   305	        legacy = pyjwt.encode(
   306	            {"sub": "revoker", "role": "VIEWER", "iss": "yaoke",
   307	             "exp": 2 ** 31 - 1, "iat": 1},
   308	            config_module.settings.jwt_secret,
   309	            algorithm="HS256",
   310	        )
   311	        with self._known(self.identity):
   312	            with self.assertRaises(HTTPException) as raised:
   313	                self._require(legacy)
   314	        self.assertEqual(401, raised.exception.status_code)
   315	        self.assertEqual(INVALID_TOKEN, raised.exception.detail)
   316	
   317	    def test_a_forged_cv_does_not_outlive_the_table(self):
   318	        """判定读表：claim 里写多大的版本都不算数，它只是"要比哪个"的提示。"""
   319	        forged = pyjwt.encode(
   320	            {"sub": "revoker", "role": "VIEWER", "iss": "yaoke", "exp": 2 ** 31 - 1,
   321	             "iat": 1, auth.CREDENTIAL_VERSION_CLAIM: 10_000},
   322	            config_module.settings.jwt_secret,
   323	            algorithm="HS256",
   324	        )
   325	        with self._known(self.identity):
   326	            with self.assertRaises(HTTPException) as raised:
   327	                self._require(forged)
   328	        self.assertEqual(INVALID_TOKEN, raised.exception.detail)
   329	
   330	    def test_a_non_integer_cv_claim_is_rejected(self):
   331	        """`True == 1`、`"1" != 1`：版本必须按整数比，别让它经由弱等值混过去。"""
   332	        record = user_store.get_record("revoker")
   333	        for claim in (True, str(record.credentials_version), 1.0, None, [1]):
   334	            with self.subTest(cv=claim):
   335	                token = pyjwt.encode(
   336	                    {"sub": "revoker", "role": "VIEWER", "iss": "yaoke", "exp": 2 ** 31 - 1,
   337	                     "iat": 1, auth.CREDENTIAL_VERSION_CLAIM: claim},
   338	                    config_module.settings.jwt_secret,
   339	                    algorithm="HS256",
   340	                )
   341	                with self._known(self.identity):
   342	                    with self.assertRaises(HTTPException) as raised:
   343	                        self._require(token)
   344	                self.assertEqual(INVALID_TOKEN, raised.exception.detail)
   345	
   346	    def test_the_removed_account_specificity_message_is_gone_from_the_token_face(self):
   347	        """§9.1：「账号不存在」并入「无效登录凭证」，不再泄露存在性。"""
   348	        with self._known():
   349	            with self.assertRaises(HTTPException) as raised:
   350	                self._require(self.token)
   351	        self.assertEqual(401, raised.exception.status_code)
   352	        self.assertEqual(INVALID_TOKEN, raised.exception.detail)
   353	        self.assertNotIn("账号不存在", raised.exception.detail)
   354	
   355	    def test_a_deleted_credential_row_revokes_an_issued_token(self):
   356	        """有身份、无凭据行 ⇒ 与"不认识这个主体"同一格（§6.4 停用动作的凭据侧那一半）。"""
   357	        user_store.delete_record("revoker")
   358	        with self._known(self.identity):
   359	            with self.assertRaises(HTTPException) as raised:
   360	                self._require(self.token)
   361	        self.assertEqual(INVALID_TOKEN, raised.exception.detail)
   362	
   363	    def test_an_expired_token_still_reports_the_expired_copy(self):
   364	        """过期与撤销同**状态码**、不同**文案**：运维得能从审计之外的响应面分清两者。"""
   365	        stale = pyjwt.encode(
   366	            {"sub": "revoker", "role": "VIEWER", "iss": "yaoke", "iat": 1, "exp": 1,
   367	             auth.CREDENTIAL_VERSION_CLAIM: user_store.get_record("revoker").credentials_version},
   368	            config_module.settings.jwt_secret,
   369	            algorithm="HS256",
   370	        )
   371	        with self._known(self.identity):
   372	            with self.assertRaises(HTTPException) as raised:
   373	                self._require(stale)
   374	        self.assertEqual("登录已过期，请重新登录", raised.exception.detail)
   375	
   376	    def test_a_missing_header_still_reports_the_login_first_copy(self):
   377	        """三格 401 文案互不相同，而认证失败面不区分"你是谁"（§9.1 表）。"""
   378	        with self.assertRaises(HTTPException) as raised:
   379	            auth.require_user(None)
   380	        self.assertEqual("请先登录", raised.exception.detail)
   381	
   382	
   383	class TokenFaceHttpTests(_LongJwtSecret, _AuditToTempFile, unittest.TestCase):
   384	    """撤销必须在**真 HTTP 面**上落地：SECA-09 点名的判据对象是 `/api/query`。"""
   385	
   386	    def setUp(self):
   387	        super().setUp()
   388	        _fresh_db(self)
   389	        ensure_demo_credentials("admin")
   390	        self.client = TestClient(app)
   391	
   392	    def _headers(self, username: str = "admin", password: str = "admin123") -> dict[str, str]:
   393	        login = self.client.post(
   394	            "/api/auth/login", json={"username": username, "password": password}
   395	        )
   396	        self.assertEqual(200, login.status_code, login.text)
   397	        return _bearer(login.json()["access_token"])
   398	
   399	    def _query(self, headers: dict[str, str]):
   400	        return self.client.post(
   401	            "/api/query", json={"question": "撤销之后还能问吗", "k": 1}, headers=headers
   402	        )
   403	
   404	    def test_a_password_change_kicks_the_old_token_out_of_the_data_face(self):
   405	        headers = self._headers()
   406	        # 前置"此刻是活的"走 `/me` 而不是 `/api/query`：后者要真读向量库与模型，
   407	        # 把一本来只看依赖层的用例绑到外部服务上，红起来分不清是谁的锅。
   408	        self.assertEqual(200, self.client.get("/api/auth/me", headers=headers).status_code)
   409	        user_store.set_password_argon2(
   410	            "admin", plain_password=NEW_PASSWORD, must_change=False
   411	        )
   412	        blocked = self._query(headers)
   413	        self.assertEqual(401, blocked.status_code, blocked.text)
   414	        self.assertEqual(INVALID_TOKEN, blocked.json()["detail"])
   415	        # 响应面不许出现任何英文 token 或撤销原因（§9.1 两栏：机器可读性走审计）
   416	        self.assertNotIn("invalid", blocked.text.lower())
   417	        self.assertNotIn(NEW_PASSWORD, blocked.text)
   418	        self.assertNotIn("admin123", blocked.text)
   419	
   420	    def test_a_pre_seca_token_is_rejected_by_the_data_face_too(self):
   421	        """依赖层与 HTTP 层同一条腿：这一枚钉的是"兼容分支"在真请求上也不许留缝。"""
   422	        legacy = pyjwt.encode(
   423	            {"sub": "admin", "role": "ADMIN", "iss": "yaoke", "exp": 2 ** 31 - 1, "iat": 1},
   424	            config_module.settings.jwt_secret,
   425	            algorithm="HS256",
   426	        )
   427	        blocked = self._query(_bearer(legacy))
   428	        self.assertEqual(401, blocked.status_code, blocked.text)
   429	        self.assertEqual(INVALID_TOKEN, blocked.json()["detail"])
   430	
   431	    def test_the_pending_leg_compares_versions_as_well(self):
   432	        """白名单腿免的是 `must_change` 门，不免令牌生命周期：旧 token 连 `/me` 也进不去。
   433	
   434	        这一条是后面改密腿的地基：改密成功那一刻旧会话整体作废，客户端必须重新登录
   435	        才能再拿到一枚活的 token——"改完还能用旧 token 读 /me"会变成第二条撤销绕过。
   436	        """
   437	        headers = self._headers()
   438	        self.assertEqual(200, self.client.get("/api/auth/me", headers=headers).status_code)
   439	        user_store.set_password_argon2(
   440	            "admin", plain_password=NEW_PASSWORD, must_change=True
   441	        )
   442	        blocked = self.client.get("/api/auth/me", headers=headers)
   443	        self.assertEqual(401, blocked.status_code, blocked.text)
   444	        self.assertEqual(INVALID_TOKEN, blocked.json()["detail"])
   445	
   446	
   447	class AccountDisablePairingTests(_LongJwtSecret, _AuditToTempFile, unittest.TestCase):
   448	    """§6.4：停用是**成对**动作。这里把两半各自钉住，顺带钉住"为什么必须有第二半"。"""
   449	
   450	    def setUp(self):
   451	        super().setUp()
   452	        _fresh_db(self)
   453	        user_store.create_argon2("paused", plain_password=GOOD_PASSWORD, must_change=False)
   454	        self.enabled = _identity("paused", role="USER", enabled=True)
   455	        with directory.override_identities({"paused": self.enabled}):
   456	            self.token = auth.issue_token(auth._user_from(self.enabled, None))
   457	
   458	    def test_the_credential_side_alone_revokes_a_live_token_while_the_cache_is_stale(self):
   459	        """只删凭据行（身份缓存还写着 enabled=true）也必须废掉 token——这是在线的那一半。
   460	
   461	        身份文件按形态缓存在进程里（`directory.identities()`），改文件不调 `reset_cache()`
   462	        就不进进程 ⇒ 运维改完文件的那一刻，能立刻挡住旧 token 的只有凭据侧。
   463	        """
   464	        user_store.delete_record("paused")
   465	        with directory.override_identities({"paused": self.enabled}):
   466	            with self.assertRaises(HTTPException) as raised:
   467	                auth.require_user(f"Bearer {self.token}")
   468	        self.assertEqual(INVALID_TOKEN, raised.exception.detail)
   469	
   470	    def test_the_identity_side_alone_revokes_a_live_token(self):
   471	        """进程读到 `enabled=false` 之后（重启或缓存复位），身份侧那一半单独也够用。"""
   472	        disabled = _identity("paused", role="USER", enabled=False)
   473	        with directory.override_identities({"paused": disabled}):
   474	            with self.assertRaises(HTTPException) as raised:
   475	                auth.require_user(f"Bearer {self.token}")
   476	        self.assertEqual(INVALID_TOKEN, raised.exception.detail)
   477	
   478	    def test_the_pairing_revokes_it_on_the_http_face(self):
   479	        """成对动作在真请求上的合力：401、中文文案、且停用二字不上响应面。"""
   480	        user_store.set_password_argon2(
   481	            "paused", plain_password=NEW_PASSWORD, must_change=False
   482	        )
   483	        disabled = _identity("paused", role="USER", enabled=False)
   484	        client = TestClient(app)
   485	        with directory.override_identities({"paused": disabled}):
   486	            blocked = client.get("/api/auth/me", headers=_bearer(self.token))
   487	        self.assertEqual(401, blocked.status_code, blocked.text)
   488	        self.assertEqual(INVALID_TOKEN, blocked.json()["detail"])
   489	        self.assertNotIn("停用", blocked.text)
   490	
   491	
   492	class NoCredentialIdentityTokenTests(_LongJwtSecret, unittest.TestCase):
   493	    """无凭据身份签出的 token 一签发即死（`cv=0` 裁定的形状）。"""
   494	
   495	    def setUp(self):
   496	        super().setUp()
   497	        _fresh_db(self)
   498	        self.identity = _identity("ghost")
   499	
   500	    def test_a_token_for_an_identity_without_a_row_carries_version_zero(self):
   501	        with directory.override_identities({"ghost": self.identity}):
   502	            token = auth.issue_token(auth._user_from(self.identity, None))
   503	        self.assertEqual(0, _decode(token)[auth.CREDENTIAL_VERSION_CLAIM])
   504	
   505	    def test_version_zero_never_matches_a_real_row_however_later_it_appears(self):
   506	        """`0` 与表内任何真实版本都不等 ⇒ 不给"无凭据身份"另开第二条构造路径。
   507	
   508	        凭据行晚一步出现（首版恒 1）时这枚 token 仍是死的：判据不是"当时有没有行"，
   509	        而是"这一代凭据有没有换过"，两件事在 `cv=0` 上不会分叉成一个放行分支。
   510	        """
   511	        with directory.override_identities({"ghost": self.identity}):
   512	            token = auth.issue_token(auth._user_from(self.identity, None))
   513	        user_store.create_argon2("ghost", plain_password=GOOD_PASSWORD, must_change=False)
   514	        with directory.override_identities({"ghost": self.identity}):
   515	            with self.assertRaises(HTTPException) as raised:
   516	                auth.require_user(f"Bearer {token}")
   517	        self.assertEqual(INVALID_TOKEN, raised.exception.detail)
   518	
   519	    def test_the_current_user_construction_face_stays_a_single_door(self):
   520	        """有凭据与无凭据两种身份走的是**同一个**构造点，差别只在 payload 那一枚数字。
   521	
   522	        构造面一分裂，`grant` 语义就会在两扇门里劈叉（认证腿的既有裁定：`_user_from` 是
   523	        `CurrentUser` 的唯一构造点）。这里钉的是源码结构，因为行为用例对"两条路径"这件事
   524	        天生不敏感——两条路径可以各自绿很久。同一句理由也管住了被并入的旧文案：
   525	        「账号不存在」一旦回到 `detail=`，它就又是一条存在性指纹。
   526	        """
   527	        source = Path(auth.__file__).read_text(encoding="utf-8")
   528	        self.assertEqual(
   529	            1, source.count("return CurrentUser("), "CurrentUser 构造点必须只有一处"
   530	        )
   531	        self.assertNotIn('detail="账号不存在"', source)
   532	
   533	
   534	class LoginFaceKeyTests(_LongJwtSecret, _AuditToTempFile, unittest.TestCase):
   535	    """§11：本版**唯一**一处响应面键集合变化，两处 additive 键。"""
   536	
   537	    USER_KEYS = {"username", "display_name", "role", "access_role", "permissions"}
   538	
   539	    def setUp(self):
   540	        super().setUp()
   541	        _fresh_db(self)
   542	        self.client = TestClient(app)
   543	
   544	    def _login(self, username: str, password: str):
   545	        return self.client.post(
   546	            "/api/auth/login", json={"username": username, "password": password}
   547	        )
   548	
   549	    def test_the_login_body_gained_exactly_one_key(self):
   550	        ensure_demo_credentials("admin")
   551	        response = self._login("admin", "admin123")
   552	        self.assertEqual(200, response.status_code, response.text)
   553	        body = response.json()
   554	        self.assertEqual(
   555	            {"access_token", "token_type", "user", "password_change_required"}, set(body)
   556	        )
   557	        self.assertIsInstance(body["password_change_required"], bool)
   558	        self.assertFalse(body["password_change_required"])
   559	        # 既有嵌套投影一字不动：新键只加在顶层，不塞进 `user` 里改它的形状
   560	        self.assertEqual(self.USER_KEYS, set(body["user"]))
   561	        self.assertNotIn("grant", body["user"])
   562	
   563	    def test_the_me_body_gained_the_same_one_key(self):
   564	        ensure_demo_credentials("admin")
   565	        token = self._login("admin", "admin123").json()["access_token"]
   566	        body = self.client.get("/api/auth/me", headers=_bearer(token)).json()
   567	        self.assertEqual(self.USER_KEYS | {"password_change_required"}, set(body))
   568	        self.assertFalse(body["password_change_required"])
   569	        self.assertNotIn("grant", body)
   570	
   571	    def test_both_faces_say_true_for_an_account_behind_the_gate(self):
   572	        """键不是摆设：legacy 出身当场置门（§8.3），两处都得报 True。"""
   573	        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
   574	        body = self._login("admin", "admin123").json()
   575	        self.assertTrue(body["password_change_required"])
   576	        me = self.client.get(
   577	            "/api/auth/me", headers=_bearer(body["access_token"])
   578	        ).json()
   579	        self.assertTrue(me["password_change_required"])
   580	
   581	    def test_the_login_value_comes_from_the_login_leg_not_from_a_second_read(self):
   582	        """两处判定早晚劈叉：登录面读的是 `LoginResult`，不在这儿重新查表。
   583	
   584	        桩打在"另一条腿用的那个读表函数"上——登录面若改去叫它，本例立刻给出 True，
   585	        而真值（argon2 行未置门）是 False。
   586	        """
   587	        ensure_demo_credentials("admin")
   588	        with mock.patch.object(auth, "_password_change_required", return_value=True):
   589	            body = self._login("admin", "admin123").json()
   590	        self.assertFalse(body["password_change_required"])
   591	
   592	    def test_the_me_value_is_read_from_the_table_not_from_the_token(self):
   593	        """`/me` 的判定读表：把门状态写进 claim 就等于让 token 自己声明"我不必改密"。"""
   594	        ensure_demo_credentials("admin")
   595	        token = self._login("admin", "admin123").json()["access_token"]
   596	        self.assertFalse(
   597	            self.client.get("/api/auth/me", headers=_bearer(token)).json()[
   598	                "password_change_required"
   599	            ]
   600	        )
   601	        # 同一枚 token（payload 里没有任何门状态），表一置门两处读数就都翻成 True。
   602	        user_store.set_password_argon2("admin", plain_password=NEW_PASSWORD, must_change=True)
   603	        revived = self._login("admin", NEW_PASSWORD).json()["access_token"]
   604	        self.assertTrue(
   605	            self.client.get("/api/auth/me", headers=_bearer(revived)).json()[
   606	                "password_change_required"
   607	            ]
   608	        )
   609	        self.assertNotIn(
   610	            "must_change", json.dumps(pyjwt.decode(token, options={"verify_signature": False}))
   611	        )
   612	
   613	    def test_the_two_faces_carry_no_english_token_in_their_bodies(self):
   614	        """§9.1 两栏：布尔**键**叫 `password_change_required` 是协议，值域里没有自由文本。
   615	
   616	        判的是"任何一格取值都不许长成审计 token"——`must_change` 那种把内部字段名顺手
   617	        投影到响应面的写法会在这里红；键名本身不在判定对象内（它是 §11 声明的契约）。
   618	        """
   619	        ensure_demo_credentials("admin")
   620	        login = self._login("admin", "admin123").json()
   621	        me = self.client.get(
   622	            "/api/auth/me", headers=_bearer(login["access_token"])
   623	        ).json()
   624	        tokens = set(auth.LOGIN_AUDIT_DETAILS) | {
   625	            "password_change_required", "invalid_credentials", "invalid_token", "must_change",
   626	        }
   627	        for body in (login, login["user"], me):
   628	            for key, value in body.items():
   629	                if isinstance(value, str):
   630	                    # 只判字符串取值：`permissions` 那一格是 list，`in` 一枚 set 会先撞
   631	                    # unhashable 而不是给出结论。
   632	                    self.assertNotIn(value, tokens, f"{key} 的取值成了审计 token")
   633	        self.assertIsInstance(login["password_change_required"], bool)
   634	        self.assertIsInstance(me["password_change_required"], bool)
   635	
   636	
   637	class MustChangeGateCoverageTests(_LongJwtSecret, _AuditToTempFile, unittest.TestCase):
   638	    """SECA-10：门必须由路由表自证覆盖，不靠手写清单——新增端点忘了登记就直接红。"""
   639	
   640	    #: 改密端点落地时必须同时把本集合扩成两项——这条断言会在漏扩时立刻红（多一条也红）。
   641	    WHITELIST = frozenset({"GET /api/auth/me"})
   642	
   643	    #: 表里出现的每一个 path 参数都得有样例；样例只用"必然不存在"的 id，让放行分支顶多
   644	    #: 走到 404/403，不会真读到别人的数据。
   645	    PARAM_SAMPLES = {
   646	        "conversation_id": "conv-nonexistent",
   647	        "message_id": "msg-nonexistent",
   648	        "document_id": "doc-nonexistent",
   649	        "knowledge_base_id": "kb_public",
   650	        "kb_id": "kb_public",
   651	        "run_id": "run-nonexistent",
   652	        "trace_id": "trace-nonexistent",
   653	        "job_id": "job-nonexistent",
   654	        "case_id": "case-nonexistent",
   655	        "file_name": "absent.txt",
   656	        "action": "list",
   657	    }
   658	
   659	    #: 规格 §8.4 点名的三条腿 + 名册那一面：枚举机制一旦失效（依赖树读空、qualname 漂了），
   660	    #: authenticated 集合会缩水成空集，只靠"每条都 403"是判不出来的——那叫没人参加的检查。
   661	    MUST_BE_COVERED = frozenset({
   662	        "POST /api/query",
   663	        "POST /api/query/stream",
   664	        "POST /api/conversations/{conversation_id}/messages/stream",
   665	        "POST /api/agent/query",
   666	        "POST /api/agent/query/stream",
   667	        "PATCH /api/conversations/{conversation_id}",
   668	        "GET /api/auth/users",
   669	    })
   670	
   671	    #: 天然不该被认证覆盖的面：它们出现在 authenticated 里就是枚举在瞎报。
   672	    MUST_NOT_BE_COVERED = frozenset({
   673	        "GET /api/health",
   674	        "GET /api/ready",
   675	        "POST /api/auth/login",
   676	    })
   677	
   678	    def setUp(self):
   679	        super().setUp()
   680	        _fresh_db(self)
   681	        user_store.create_argon2("gated", plain_password=GOOD_PASSWORD, must_change=True)
   682	        self.identity = _identity("gated", role="ADMIN")
   683	        stack = contextlib.ExitStack()
   684	        stack.enter_context(directory.override_identities({"gated": self.identity}))
   685	        self.addCleanup(stack.close)
   686	        # 一整个用例只签一枚 token：每次签都付一次 Argon2 之外的读表，而覆盖面判据要的
   687	        # 只是"同一枚活 token 打遍全表"。
   688	        self.token = auth.issue_token(auth._user_from(self.identity, None))
   689	        self.client = TestClient(app)
   690	
   691	    # --- 覆盖面判定 -------------------------------------------------------
   692	    def test_every_authenticated_route_is_gated_or_whitelisted(self):
   693	        authenticated = _routes_using(auth.require_user) | _routes_using(auth.require_permissions)
   694	        pending = _routes_using(auth.require_user_pending_password)
   695	        self.assertEqual(set(self.WHITELIST), pending, "白名单外泄：有端点改走了免门依赖")
   696	        self.assertTrue(
   697	            self.MUST_BE_COVERED <= authenticated,
   698	            f"枚举漏腿：{sorted(self.MUST_BE_COVERED - authenticated)}",
   699	        )
   700	        self.assertEqual(
   701	            set(), self.MUST_NOT_BE_COVERED & authenticated, "枚举把公开面算成了认证面"
   702	        )
   703	        unattended = sorted(key for key in authenticated - pending if not self._gated(key))
   704	        self.assertEqual([], unattended, f"这些端点没过 must_change 门：{unattended}")
   705	
   706	    def test_no_route_is_registered_with_several_http_methods(self):
   707	        """拆行枚举的前提：今天没有一条路由同时挂多个方法。长出那一天本枚红，提醒改判据。"""
   708	        multi = [
   709	            (route.path, sorted(set(route.methods or ())))
   710	            for route in app.routes
   711	            if isinstance(route, APIRoute) and len(set(route.methods or ())) > 1
   712	        ]
   713	        self.assertEqual([], multi)
   714	
   715	    def test_the_pending_dependency_is_used_by_the_whitelist_only(self):
   716	        """白名单那一条得**真的**在免门腿上：只比集合相等会被"整表为空"骗过去。"""
   717	        for key in self.WHITELIST:
   718	            method, path = key.split(" ", 1)
   719	            response = self.client.request(method, self._url(path), headers=_bearer(self.token))
   720	            self.assertEqual(200, response.status_code, response.text)
   721	            self.assertTrue(response.json()["password_change_required"])
   722	
   723	    # --- 工具 ------------------------------------------------------------
   724	    def _url(self, path: str) -> str:
   725	        url = path
   726	        for name, sample in self.PARAM_SAMPLES.items():
   727	            url = url.replace("{" + name + "}", sample)
   728	        return url
   729	
   730	    def _gated(self, route_key: str) -> bool:
   731	        method, path = route_key.split(" ", 1)
   732	        url = self._url(path)
   733	        if "{" in url:
   734	            # 猜一个值过去 = 这一条从此不再被覆盖。让它红在这里，红在**加端点的人**身上。
   735	            self.fail(f"新增端点带未登记的 path 参数，请把样例加进 PARAM_SAMPLES：{route_key}")
   736	        request: dict[str, object] = {"headers": _bearer(self.token)}
   737	        if method in {"POST", "PUT", "PATCH"}:
   738	            # 空 body 是刻意的：403 必须先于请求体校验发生，门的顺序才没有被"先 422"顶掉的可能。
   739	            request["json"] = {}
   740	        response = self.client.request(method, url, **request)
   741	        if response.status_code != 403:
   742	            return False
   743	        try:
   744	            detail = response.json().get("detail")
   745	        except (ValueError, AttributeError):
   746	            return False
   747	        # 权限 403 与门 403 同为 403，只有文案分得开：等值判定就是这条区分。
   748	        return detail == GATE_COPY
   749	
   750	    def test_a_gate_denial_writes_the_enum_token_to_the_audit_face(self):
   751	        """覆盖面之外再钉一格**值**：门放行的是审计 token，响应面只有中文。"""
   752	        blocked = self.client.get("/api/knowledge-bases", headers=_bearer(self.token))
   753	        self.assertEqual(403, blocked.status_code, blocked.text)
   754	        self.assertEqual(GATE_COPY, blocked.json()["detail"])
   755	        self.assertEqual(
   756	            [("AUTHORIZATION", "DENIED", "password_change_required")],
   757	            [
   758	                (e["action"], e["status"], e["detail"])
   759	                for e in self.events()
   760	                if e["action"] == "AUTHORIZATION"
   761	            ],
   762	        )
   763	
   764	
   765	if __name__ == "__main__":
   766	    unittest.main()

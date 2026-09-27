# Task 4 review package (base = snap-task3-r1-app)
## stat
Files .superpowers/sdd/SECURITY_A_PLAN/snap-task3-r1-app/config.py and backend/app/config.py differ
Only in backend/app: directory.py
Files .superpowers/sdd/SECURITY_A_PLAN/snap-task3-r1-app/knowledge_os.py and backend/app/knowledge_os.py differ

## app diff (config.py, knowledge_os.py, directory.py)
diff -ruN -U10 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task3-r1-app/config.py backend/app/config.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task3-r1-app/config.py	2026-09-25 21:26:17.581483500 +0800
+++ backend/app/config.py	2026-09-25 22:20:38.156645100 +0800
@@ -145,20 +145,24 @@
     # warm CPU rerank latency versus the previous pool of twelve.
     retrieval_rerank_candidates: int = Field(default=6, ge=5, le=50)
     # BGE's short-query retrieval instruction improves pure dense Top-3 recall on
     # the real-BGE gate. Hybrid keeps the raw query because it measured better with RRF.
     retrieval_vector_query_instruction: str = "为这个句子生成表示以用于检索相关文章："
     # Prefer diverse documents in the final evidence set while still allowing a
     # document to contribute multiple sections. Deferred chunks fill any shortage.
     retrieval_max_chunks_per_document: int = Field(default=2, ge=1, le=10)
     retrieval_query_context_max_chars: int = Field(default=320, ge=80, le=1000)
 
+    # SEC-A 生产形态总开关。true ⇒ 不加载 demo 身份 + 默认 JWT secret 拒启动 +
+    # CORS 白名单未配拒启动（三件同生同死，规格 §8.5）。
+    security_enterprise_mode: bool = False
+
     jwt_secret: str = "change-me-before-production-yaoke-demo-secret"
     jwt_expire_hours: int = 8
 
     # Argon2 并发槽上限（可用性旋钮）。**密码学档位不在这里**：m/t/p 固定在
     # app/credentials.py 的常量上，改它等于改规格（SEC-A-008）。
     argon2_max_concurrent_ops: int = 2
 
     # Local backend cwd is normally ./backend, so ../demo-data points to repo demo data.
     # Docker overrides this to /app/demo-data via docker-compose.
     demo_data_dir: str = "../demo-data"
diff -ruN -U10 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task3-r1-app/directory.py backend/app/directory.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task3-r1-app/directory.py	1970-01-01 08:00:00.000000000 +0800
+++ backend/app/directory.py	2026-09-25 22:33:08.246901700 +0800
@@ -0,0 +1,216 @@
+"""身份声明层（规格 §6.4）。身份的唯一真源是文件，凭据状态在 user_store，两边不得互串。
+
+role 的取值**不在这里**校验：`access_role_for()` 对未知角色返回 None、权限表退化为空集，
+那已经是 fail-closed。在这里再抄一份角色白名单只会造出第二个真源（RBAC 改了这里没改 = 静默失配）。
+
+`enabled` 同理只被**声明**，不被消费：这个人还让不让用口令，是认证腿统一判的事（规格 §7.3
+把它折进"与口令错同一条哑校验路径、同一个 401"）。身份侧再判一次就会长出第二种
+"这个账号现在是什么状态"的说法，而那个状态本身又是一条可枚举的响应差异。
+"""
+
+from __future__ import annotations
+
+import json
+import re
+from collections.abc import Iterator, Mapping
+from contextlib import contextmanager
+from pathlib import Path
+from typing import Any
+
+from pydantic import BaseModel, ConfigDict, Field, ValidationError
+
+#: 两份文件都是**相对路径**，按进程 cwd 解析：镜像的 WORKDIR 就是 `backend/`，`config/` 整目录
+#: 随镜像 COPY，所以"身份文件在场"是部署事实而不是配置项。口径与 `config/llm_registry.json`、
+#: `config/feishu_permissions.json` 以及本目录里 `data/` 那一组常量同轨。
+ENTERPRISE_IDENTITIES_FILE = Path("config/users.json")
+DEMO_IDENTITIES_FILE = Path("config/users.demo.json")
+
+#: 敏感键黑名单。`extra="forbid"` 已经挡掉一切未知键，这张表挡的是"看起来无害的写法"：
+#: `hash` / `legacy` 这类名字既不在字段集里也不像凭据，但出现在身份文件里就是有人把两件事
+#: 写到了一起。命中即拒，不做"忽略该字段后继续"。
+FORBIDDEN_IDENTITY_KEYS = frozenset(
+    {"password", "password_hash", "hash", "secret", "token", "api_key", "credentials", "legacy"}
+)
+
+# 敏感键与"看起来像凭据"的形态是两道独立的门：`extra="forbid"` 挡不住 display_name 里塞 digest。
+# 判"纯 hex 且 ≥40 位"而不是恰好 64：摘要家族不止 SHA-256（SHA-1=40、SHA-384=96），而 64 位
+# 那一种恰恰是本项目升级前一直在用的形态。下限停在 40 而不是 32 是刻意的——32 位纯 hex 正是
+# UUID 去掉连字符的长度，把机器账号拒在启动期的代价高于"顺带拦下 MD5"的收益。
+_HEX_DIGEST = re.compile(r"^[0-9a-f]{40,}$")
+# PHC 编码（`$argon2id$…` / `$2b$…`）不是 hex，上面那道看不见它，但它是同一类材料。
+_PHC_DIGEST = re.compile(r"^\$[a-z0-9]+\$")
+
+
+class IdentityConfigError(RuntimeError):
+    """身份文件不合法 ⇒ 启动失败。不是告警，不是忽略该条目。"""
+
+
+class UserIdentity(BaseModel):
+    model_config = ConfigDict(extra="forbid")
+
+    username: str = Field(min_length=1, max_length=64)
+    display_name: str = Field(min_length=1, max_length=64)
+    role: str = Field(min_length=1, max_length=32)
+    # `min_length=1`：空串是一个"看起来没有、实际上有值"的 open_id，而 open_id 的唯一性
+    # 只判非 null 的取值——两个没接飞书的账号都会撞上这个空串，报错信息还会指着 open_id 说事。
+    feishu_open_id: str | None = Field(default=None, min_length=1)
+    enabled: bool = True
+
+
+def _credential_shape_violation(node: Any) -> str | None:
+    """递归找"凭据形状"，命中就返回一句**不回显取值**的成因描述。
+
+    递归不是为了优雅：`{"display_name": {"password": "…"}}` 这种嵌套写法会一路走到字段
+    校验器，而校验器的默认报错文本带着**输入值**——那份值可能是某人从口令表里粘过来的。
+    在这里拦下，它就不会以任何形式进启动日志。
+    """
+    if isinstance(node, Mapping):
+        offending = {str(key).lower() for key in node} & FORBIDDEN_IDENTITY_KEYS
+        if offending:
+            return f"含凭据字段 {sorted(offending)}"
+        for value in node.values():
+            reason = _credential_shape_violation(value)
+            if reason is not None:
+                return reason
+        return None
+    if isinstance(node, (list, tuple)):
+        for value in node:
+            reason = _credential_shape_violation(value)
+            if reason is not None:
+                return reason
+        return None
+    if isinstance(node, str):
+        text = node.strip()
+        if _HEX_DIGEST.match(text.lower()):
+            return "含疑似口令摘要的取值"
+        if _PHC_DIGEST.match(text):
+            return "含疑似口令散列的取值"
+    return None
+
+
+def _read_document(path: Path) -> Any:
+    if not path.exists():
+        raise IdentityConfigError(f"身份文件不存在：{path}")
+    try:
+        text = path.read_text(encoding="utf-8")
+    except (OSError, UnicodeDecodeError) as exc:
+        # "在场但读不出来"与"形态不对"是同一条出路：整份拒。让它以 `UnicodeDecodeError`
+        # 往上逃，症状就是一条与身份毫无关系的栈。消息只点名路径，不回显内容。
+        raise IdentityConfigError(f"身份文件读不出来：{path}") from exc
+    try:
+        return json.loads(text)
+    except json.JSONDecodeError as exc:
+        raise IdentityConfigError(f"身份文件不是合法 JSON：{path}") from exc
+
+
+def _validate_records(path: Path, payload: Any = None) -> list[UserIdentity]:
+    """把一份身份文件读成记录列表，任何一处不合法都从 `IdentityConfigError` 出去。
+
+    `payload` 是给"记录已经在内存里"的调用方留的位置（启动 seed 那条路迟早要从别处拿记录，
+    而不是从文件读）。今天没有这样的调用方，所以它**不静默接活**：传了就直接拒，宁可让
+    第一次误用变成一条响亮的启动失败，也不要"传了 payload、结果读的是文件"这种分叉。
+    """
+    if payload is not None:
+        raise IdentityConfigError(f"{path}: 身份记录的内存直传路径尚未实装")
+    document = _read_document(path)
+    # 顶层键封闭：多一个键就是有人往这份身份文件里放了本规格不认识的东西（凭据最容易这样进来）。
+    if not isinstance(document, dict) or set(document) - {"identities"}:
+        raise IdentityConfigError(f"身份文件顶层键必须是唯一的 identities：{path}")
+    records = document.get("identities")
+    if not isinstance(records, list):
+        raise IdentityConfigError(f"{path}: identities 必须是数组")
+    identities: list[UserIdentity] = []
+    for index, raw in enumerate(records):
+        if not isinstance(raw, dict):
+            raise IdentityConfigError(f"{path}: identities[{index}] 必须是对象")
+        reason = _credential_shape_violation(raw)
+        if reason is not None:
+            raise IdentityConfigError(f"{path}: identities[{index}] {reason}")
+        try:
+            identities.append(UserIdentity(**raw))
+        except ValidationError as exc:
+            # 只取 `loc` + `type`：字段取值一律不进消息（理由同 `_credential_shape_violation`）。
+            # 原文仍在异常链上，定位能力一点没少。
+            detail = "; ".join(
+                f"{'.'.join(str(part) for part in item['loc'])}: {item['type']}"
+                for item in exc.errors()
+            )
+            raise IdentityConfigError(f"{path}: identities[{index}] 不合法：{detail}") from exc
+    return identities
+
+
+def load_identities(*, include_demo: bool) -> dict[str, UserIdentity]:
+    """enterprise 先、demo 后；重名一律拒，**不做**字典覆盖式合并。
+
+    `{**enterprise, **demo}` 的坏处不是"会覆盖"这么抽象：demo 文件里放一个同名账号就等于
+    改掉那个人的 role，而 role 是权限的入口。合并因此只能"撞上就停"，两种形态都跑同一套
+    校验（企业形态只有一份文件，冲突面天然为空，但少跑一次就会有一次没跑过的那支）。
+    """
+    sources: list[Path] = [ENTERPRISE_IDENTITIES_FILE]
+    if include_demo:
+        sources.append(DEMO_IDENTITIES_FILE)
+    merged: dict[str, UserIdentity] = {}
+    seen_open_ids: dict[str, str] = {}
+    for source in sources:
+        for identity in _validate_records(source):
+            if identity.username in merged:
+                raise IdentityConfigError(
+                    f"username 重复：{identity.username}（{source}）"
+                    "——后加载的身份不得覆盖先加载的（demo 文件不得改写企业身份）"
+                )
+            if identity.feishu_open_id is not None:
+                if identity.feishu_open_id in seen_open_ids:
+                    # open_id 是外部身份→内部账号的查找键：两个人共用一个，授予就会串到别人身上。
+                    raise IdentityConfigError(
+                        "feishu_open_id 重复："
+                        f"{identity.feishu_open_id} 同时属于 {seen_open_ids[identity.feishu_open_id]}"
+                        f" 与 {identity.username}"
+                    )
+                seen_open_ids[identity.feishu_open_id] = identity.username
+            merged[identity.username] = identity
+    return merged
+
+
+_CACHE: dict[bool, dict[str, UserIdentity]] = {}
+
+
+def identities() -> Mapping[str, UserIdentity]:
+    """按形态缓存。形态在进程生命周期内不变（启动守卫负责它的成立）。
+
+    `settings` 在调用时取而不是 import 时钉死：本模块的形态判定必须跟着**当前**配置走
+    （测试接缝与启动守卫都靠这一点），而 import 期取值会把 `app.config` 的加载顺序变成
+    身份层的一部分。
+    """
+    from app.config import settings
+
+    mode = bool(settings.security_enterprise_mode)
+    if mode not in _CACHE:
+        _CACHE[mode] = load_identities(include_demo=not mode)
+    return _CACHE[mode]
+
+
+def get_identity(username: str) -> UserIdentity | None:
+    return identities().get(str(username))
+
+
+def reset_cache() -> None:
+    _CACHE.clear()
+
+
+@contextmanager
+def override_identities(mapping: Mapping[str, UserIdentity]) -> Iterator[None]:
+    """测试接缝：替代过去"直接改 auth.USERS"的做法（规格 §16 改写的第二条）。
+
+    只替换**当前形态**那一份缓存，退出时连同其余键一起还原——留着半份替换，下一个用例
+    就会在自己的 setUp 里读到别人的人。
+    """
+    from app.config import settings
+
+    mode = bool(settings.security_enterprise_mode)
+    saved = dict(_CACHE)
+    _CACHE[mode] = dict(mapping)
+    try:
+        yield
+    finally:
+        _CACHE.clear()
+        _CACHE.update(saved)
diff -ruN -U10 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task3-r1-app/knowledge_os.py backend/app/knowledge_os.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task3-r1-app/knowledge_os.py	2026-09-25 21:26:17.513418900 +0800
+++ backend/app/knowledge_os.py	2026-09-25 22:19:24.947113400 +0800
@@ -14,22 +14,23 @@
 from collections import Counter
 from datetime import datetime, timedelta, timezone
 from pathlib import Path
 from threading import Lock
 from typing import Any, Literal
 
 from fastapi import APIRouter, Depends, HTTPException, Query
 from pydantic import BaseModel, Field
 
 from app.audit import AUDIT_PATH, recent_events, record_event
-from app.auth import CurrentUser, USERS, require_permission, require_user
+from app.auth import CurrentUser, require_permission, require_user
 from app.config import settings
+from app.directory import identities as directory_identities, get_identity
 from app.ingestion import DOC_DIR, document_path, parse_document
 from app.knowledge import get_base, resolve_for
 from app.llm import usage as llm_usage
 from app.llm.health import probe_llm
 from app.rag import current_model_name
 from app.retrieval import retrieval_service
 from app.security import (
     public_exception_detail,
     public_llm_status,
     public_typesafe_stats,
@@ -550,28 +551,28 @@
     cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
     today = datetime.now(timezone.utc).date().isoformat()
     queries = [
         e for e in events
         if e.get("action") == "QUERY" and e.get("status") == "SUCCESS" and str(e.get("timestamp", "")) >= cutoff
     ]
     active_users = {str(e.get("username")) for e in queries if e.get("username")}
     latencies = [float(e["latency_ms"]) for e in queries if e.get("latency_ms") is not None]
     dept_counter: Counter[str] = Counter()
     for event in queries:
-        record = USERS.get(str(event.get("username")))
-        if record:
-            dept_counter[ROLE_DEPARTMENT.get(str(record.get("role")), "其他")] += 1
+        identity = get_identity(str(event.get("username")))
+        if identity:
+            dept_counter[ROLE_DEPARTMENT.get(identity.role, "其他")] += 1
     top = dept_counter.most_common(1)
-    total_users = max(len(USERS), 1)
+    total_users = max(len(directory_identities()), 1)
     return {
         "active_users": len(active_users),
-        "total_users": len(USERS),
+        "total_users": len(directory_identities()),
         "queries_30d": len(queries),
         "adoption_pct": round(len(active_users) / total_users * 100, 1),
         "top_department": {"name": top[0][0], "queries": top[0][1]} if top else None,
         "queries_today": sum(1 for e in queries if str(e.get("timestamp", "")).startswith(today)),
         "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
     }
 
 
 # ---------- System status ----------
 
@@ -684,30 +685,32 @@
 @router.get("/auth/users")
 def list_users(user: CurrentUser = Depends(require_permission("audit:read"))):
     events = recent_events(5000)
     last_login: dict[str, str] = {}
     for event in events:
         if event.get("action") == "LOGIN" and event.get("status") == "SUCCESS":
             name = str(event.get("username"))
             ts = str(event.get("timestamp", ""))
             if ts >= last_login.get(name, ""):
                 last_login[name] = ts
+    # 名册是**身份侧的投影**：在册与否来自身份文件（身份的唯一真源），最后一次登录从审计面派生。
+    # `status` 恒为 ACTIVE 是既有口径——"停用"如何被观察到由认证腿统一给，展示面不自己发明第二态。
     users = [
         {
-            "username": record["username"],
-            "display_name": record["display_name"],
-            "role": record["role"],
-            "department": ROLE_DEPARTMENT.get(str(record["role"]), "其他"),
+            "username": identity.username,
+            "display_name": identity.display_name,
+            "role": identity.role,
+            "department": ROLE_DEPARTMENT.get(identity.role, "其他"),
             "status": "ACTIVE",
-            "last_login": last_login.get(record["username"]),
+            "last_login": last_login.get(identity.username),
         }
-        for record in USERS.values()
+        for identity in directory_identities().values()
     ]
     return {"users": users}
 
 
 @router.post("/access/requests")
 def request_access(
     payload: AccessRequestPayload,
     user: CurrentUser = Depends(require_user),
 ):
     record = {

## config files
     1	{
     2	  "identities": []
     3	}
---
     1	{
     2	  "identities": [
     3	    { "username": "admin", "display_name": "系统管理员", "role": "ADMIN" },
     4	    { "username": "sales01", "display_name": "销售演示账号", "role": "SALES" },
     5	    { "username": "hr01", "display_name": "HR 演示账号", "role": "HR" },
     6	    { "username": "user", "display_name": "普通用户演示账号", "role": "USER" },
     7	    { "username": "viewer", "display_name": "只读访客演示账号", "role": "VIEWER" }
     8	  ]
     9	}

## new test file (full)
     1	"""身份声明层的契约（规格 §6.4 / SEC-A-010 / SECA-07 / SECA-23）。
     2	
     3	这些用例判的不是"文件读得出来"，而是一件更窄的事：**身份文件在结构上就没有地方放凭据**。
     4	所以重心全在拒收面上——敏感键黑名单、摘要形态、重名冲突、以及"报错面不回显取值"。
     5	"""
     6	from __future__ import annotations
     7	
     8	import ast
     9	import json
    10	import sys
    11	import tempfile
    12	import unittest
    13	from datetime import datetime, timezone
    14	from pathlib import Path
    15	from typing import Any
    16	from unittest import mock
    17	
    18	BACKEND_DIR = Path(__file__).resolve().parents[1]
    19	sys.path.insert(0, str(BACKEND_DIR))
    20	
    21	from app import config as config_module  # noqa: E402
    22	from app import directory  # noqa: E402
    23	from app import knowledge_os  # noqa: E402
    24	from app.auth import CurrentUser  # noqa: E402
    25	from app.config import Settings  # noqa: E402
    26	from app.directory import UserIdentity  # noqa: E402
    27	
    28	#: 出厂身份文件的**绝对**落点。测试一律走这一份，而不是"当前工作目录下的 config/"：
    29	#: 全套件按两种 cwd 跑（`backend/` 与仓库根），相对路径口径只属于生产形态（镜像 WORKDIR=backend）。
    30	SHIPPED_ENTERPRISE = BACKEND_DIR / "config" / "users.json"
    31	SHIPPED_DEMO = BACKEND_DIR / "config" / "users.demo.json"
    32	
    33	#: 一枚哨兵：出现在任何异常消息里就说明报错面回显了文件内容。它比最长字段还长，
    34	#: 所以"合法取值"这条路走不通它，只能从校验器的报错文本里出来。
    35	SENTINEL = "hunter2-SENTINEL-please-never-echo-this-string-is-longer-than-sixty-four"
    36	
    37	
    38	def _record(username: str, **overrides: Any) -> dict:
    39	    data: dict = {"username": username, "display_name": username, "role": "USER"}
    40	    data.update(overrides)
    41	    return data
    42	
    43	
    44	def _write(path: Path, records: list[dict]) -> Path:
    45	    path.write_text(json.dumps({"identities": records}, ensure_ascii=False), encoding="utf-8")
    46	    return path
    47	
    48	
    49	class _IdentityFiles(unittest.TestCase):
    50	    """每例一份临时身份文件对，两个模块级路径常量在用例期间被换掉。
    51	
    52	    换常量而不是换 cwd：路径常量是本模块唯一的落点出口，换它验的就是真实读路径；换 cwd 会让
    53	    同一进程里其它按相对路径解析的东西（会话库、模型注册表、审计文件）跟着漂。
    54	    """
    55	
    56	    def setUp(self):
    57	        self._tmp = tempfile.TemporaryDirectory()
    58	        self.root = Path(self._tmp.name)
    59	        self.enterprise = _write(
    60	            self.root / "users.json",
    61	            [{"username": "admin", "display_name": "管理员", "role": "ADMIN"}],
    62	        )
    63	        self.demo = _write(
    64	            self.root / "users.demo.json",
    65	            [{"username": "viewer", "display_name": "只读", "role": "VIEWER"}],
    66	        )
    67	        self._saved = (directory.ENTERPRISE_IDENTITIES_FILE, directory.DEMO_IDENTITIES_FILE)
    68	        directory.ENTERPRISE_IDENTITIES_FILE = self.enterprise
    69	        directory.DEMO_IDENTITIES_FILE = self.demo
    70	        directory.reset_cache()
    71	        self.addCleanup(directory.reset_cache)
    72	
    73	    def tearDown(self):
    74	        (directory.ENTERPRISE_IDENTITIES_FILE, directory.DEMO_IDENTITIES_FILE) = self._saved
    75	        self._tmp.cleanup()
    76	
    77	    def _load(self, *, include_demo: bool):
    78	        return directory.load_identities(include_demo=include_demo)
    79	
    80	    def _identities_at(self, *, enterprise_mode: bool):
    81	        with mock.patch.object(
    82	                config_module.settings, "security_enterprise_mode", enterprise_mode):
    83	            return dict(directory.identities())
    84	
    85	
    86	class IdentityFileTests(_IdentityFiles):
    87	    """SECA-07 / SECA-23：身份文件是**结构上**无口令，不是"约定不写"。"""
    88	
    89	    def test_enterprise_mode_does_not_read_the_demo_file_at_all(self):
    90	        self.assertEqual({"admin", "viewer"}, set(self._load(include_demo=True)))
    91	        self.assertEqual({"admin"}, set(self._load(include_demo=False)))
    92	
    93	    def test_a_credential_shaped_key_fails_startup_in_either_file(self):
    94	        for key in ("password", "password_hash", "hash", "secret", "token", "api_key"):
    95	            with self.subTest(key=key):
    96	                _write(self.demo, [{"username": "viewer", "display_name": "只读",
    97	                                    "role": "VIEWER", key: "x"}])
    98	                with self.assertRaises(directory.IdentityConfigError):
    99	                    self._load(include_demo=True)
   100	        _write(self.enterprise, [{"username": "admin", "display_name": "管理员",
   101	                                 "role": "ADMIN", "password": "hunter2"}])
   102	        with self.assertRaises(directory.IdentityConfigError):
   103	            self._load(include_demo=False)
   104	
   105	    def test_a_legacy_digest_value_is_rejected_even_under_an_allowed_key(self):
   106	        _write(self.enterprise, [{"username": "admin", "display_name": "a" * 40,
   107	                                 "role": "ADMIN"}])
   108	        with self.assertRaises(directory.IdentityConfigError):
   109	            self._load(include_demo=False)
   110	
   111	    def test_unknown_extra_fields_are_rejected_not_ignored(self):
   112	        _write(self.enterprise, [{"username": "admin", "display_name": "管理员",
   113	                                 "role": "ADMIN", "is_superuser": True}])
   114	        with self.assertRaises(directory.IdentityConfigError):
   115	            self._load(include_demo=False)
   116	
   117	    def test_duplicate_username_across_files_fails_instead_of_letting_demo_override(self):
   118	        """M18 的目标形态：`{**enterprise, **demo}` 必须被这条挡下。"""
   119	        _write(self.demo, [{"username": "admin", "display_name": "假冒管理员", "role": "VIEWER"}])
   120	        with self.assertRaises(directory.IdentityConfigError):
   121	            self._load(include_demo=True)
   122	
   123	    def test_duplicate_feishu_open_id_across_files_fails(self):
   124	        _write(self.enterprise, [{"username": "admin", "display_name": "管理员",
   125	                                 "role": "ADMIN", "feishu_open_id": "ou_shared"}])
   126	        _write(self.demo, [{"username": "viewer", "display_name": "只读",
   127	                           "role": "VIEWER", "feishu_open_id": "ou_shared"}])
   128	        with self.assertRaises(directory.IdentityConfigError):
   129	            self._load(include_demo=True)
   130	
   131	    def test_disabled_is_a_first_class_identity_flag(self):
   132	        _write(self.enterprise, [{"username": "admin", "display_name": "管理员",
   133	                                 "role": "ADMIN", "enabled": False}])
   134	        self.assertFalse(self._load(include_demo=False)["admin"].enabled)
   135	
   136	    def test_default_is_enabled(self):
   137	        self.assertTrue(self._load(include_demo=False)["admin"].enabled)
   138	
   139	    def test_missing_enterprise_file_is_a_hard_failure_not_an_empty_directory(self):
   140	        self.enterprise.unlink()
   141	        with self.assertRaises(directory.IdentityConfigError):
   142	            self._load(include_demo=False)
   143	
   144	
   145	class CredentialShapeRejectionTests(_IdentityFiles):
   146	    """黑名单键 + 摘要形态：两重都要有，因为 `extra="forbid"` 只看得见键名。"""
   147	
   148	    def test_a_sixty_four_hex_digest_is_rejected_under_every_string_field(self):
   149	        for field in ("username", "display_name", "role", "feishu_open_id"):
   150	            with self.subTest(field=field):
   151	                record = _record("admin")
   152	                record[field] = "d" * 64
   153	                _write(self.enterprise, [record])
   154	                with self.assertRaises(directory.IdentityConfigError):
   155	                    self._load(include_demo=False)
   156	
   157	    def test_uppercase_digests_and_other_digest_lengths_are_rejected_too(self):
   158	        # 摘要家族不止 SHA-256（SHA-1=40、SHA-384=96），而从别处粘过来常带大写或留首尾空白。
   159	        for value in ("A" * 64, "b" * 40, "c" * 96, f"  {'d' * 64}  "):
   160	            with self.subTest(trimmed=len(value.strip())):
   161	                _write(self.enterprise, [_record("admin", display_name=value)])
   162	                with self.assertRaises(directory.IdentityConfigError):
   163	                    self._load(include_demo=False)
   164	
   165	    def test_a_uuid_shaped_machine_username_is_not_mistaken_for_a_digest(self):
   166	        # 下限停在 40 而不是 32：32 位纯 hex 正是 UUID 去掉连字符的长度。
   167	        value = "0123456789abcdef0123456789abcdef"
   168	        _write(self.enterprise, [_record(value, display_name="机器账号")])
   169	        self.assertEqual({value}, set(self._load(include_demo=False)))
   170	
   171	    def test_a_phc_encoded_hash_is_rejected_by_shape(self):
   172	        # PHC 串（`$argon2id$…`）不是 hex，按 `{64}` 认的那道看不见它，但它是同一类材料。
   173	        for value in ("$argon2id$v=19$m=19456,t=2,p=1$c29tZXNhbHQ$abcdefghij",
   174	                      "$2b$12$C6UzMD6BusSAoTFmYyO5aeZbP"):
   175	            with self.subTest(prefix=value.split("$")[1]):
   176	                _write(self.enterprise, [_record("admin", feishu_open_id=value)])
   177	                with self.assertRaises(directory.IdentityConfigError):
   178	                    self._load(include_demo=False)
   179	
   180	    def test_a_credential_key_is_named_as_such_not_as_a_typo(self):
   181	        # `extra="forbid"` 本来也会拒这个键。黑名单独立承担的是诊断：让运维看见"这里不许放
   182	        # 凭据"，而不是"字段名拼错了"——后者会被"改个名字再来一次"修掉。
   183	        _write(self.enterprise, [_record("admin", password=SENTINEL[:10])])
   184	        with self.assertRaises(directory.IdentityConfigError) as caught:
   185	            self._load(include_demo=False)
   186	        self.assertIn("凭据字段", str(caught.exception))
   187	        self.assertIn("password", str(caught.exception))
   188	
   189	    def test_a_credential_key_nested_inside_a_value_is_still_rejected(self):
   190	        for value in ({SENTINEL: None}, [{"password": SENTINEL}], {"a": {"secret": ["x" * 64]}}):
   191	            with self.subTest(shape=type(value).__name__):
   192	                _write(self.enterprise, [_record("admin", display_name=value)])
   193	                with self.assertRaises(directory.IdentityConfigError):
   194	                    self._load(include_demo=False)
   195	
   196	    def test_an_ordinary_long_non_hex_value_is_not_mistaken_for_a_digest(self):
   197	        # 反向钉子：形态检查过宽会把合法身份拒在启动期，而操作员看到的只有"含疑似摘要"。
   198	        for value in ("产品与解决方案中心负责人张三", "a" * 30 + "zzzz", "deadbeef" * 4 + "g"):
   199	            with self.subTest(value=value[:8]):
   200	                _write(self.enterprise, [_record("admin", display_name=value[:64])])
   201	                self._load(include_demo=False)
   202	
   203	    def test_a_rejection_never_echoes_a_field_value(self):
   204	        # 异常消息会进启动日志。一份写歪了的身份文件里，那个取值完全可能是从口令表粘过来的。
   205	        for field, value in (
   206	            ("display_name", SENTINEL),      # 超长 ⇒ 字段校验器分支
   207	            ("role", SENTINEL),              # 超长 ⇒ 字段校验器分支
   208	            ("feishu_open_id", "e" * 64),    # 摘要形态 ⇒ 形态分支
   209	            ("password", SENTINEL),          # 黑名单键 ⇒ 键分支
   210	        ):
   211	            with self.subTest(field=field):
   212	                _write(self.enterprise, [_record("admin", **{field: value})])
   213	                with self.assertRaises(directory.IdentityConfigError) as caught:
   214	                    self._load(include_demo=False)
   215	                self.assertNotIn(SENTINEL, str(caught.exception))
   216	                self.assertNotIn("e" * 64, str(caught.exception))
   217	
   218	    def test_a_blank_feishu_open_id_is_rejected_instead_of_colliding_two_accounts(self):
   219	        # 唯一性只管**非 null** 的 open_id：`""` 一旦算"有值"，两个没接飞书的账号就会假冲突。
   220	        _write(self.enterprise, [_record("admin", feishu_open_id="")])
   221	        with self.assertRaises(directory.IdentityConfigError):
   222	            self._load(include_demo=False)
   223	
   224	    def test_two_accounts_without_an_open_id_are_allowed(self):
   225	        _write(self.enterprise, [_record("admin"), _record("ghost")])
   226	        self.assertEqual({"admin", "ghost"}, set(self._load(include_demo=False)))
   227	
   228	
   229	class IdentityDocumentShapeTests(_IdentityFiles):
   230	    """文件级形态：顶层键封闭、必须是数组、每元素必须是对象；读不出来与形态错同一条出路。"""
   231	
   232	    def test_the_top_level_key_set_is_closed(self):
   233	        for document in (
   234	            {"identities": [], "passwords": {}},
   235	            {"users": []},
   236	            ["admin"],
   237	            {"identities": {"admin": {}}},
   238	        ):
   239	            with self.subTest(document=str(document)[:24]):
   240	                self.enterprise.write_text(json.dumps(document), encoding="utf-8")
   241	                with self.assertRaises(directory.IdentityConfigError):
   242	                    self._load(include_demo=False)
   243	
   244	    def test_a_record_that_is_not_an_object_is_rejected(self):
   245	        _write(self.enterprise, ["admin"])
   246	        with self.assertRaises(directory.IdentityConfigError):
   247	            self._load(include_demo=False)
   248	
   249	    def test_malformed_json_is_a_hard_failure_naming_the_file(self):
   250	        self.enterprise.write_text("{not json", encoding="utf-8")
   251	        with self.assertRaises(directory.IdentityConfigError) as caught:
   252	            self._load(include_demo=False)
   253	        self.assertIn(str(self.enterprise), str(caught.exception))
   254	
   255	    def test_a_file_that_cannot_be_decoded_fails_like_a_malformed_one(self):
   256	        # Windows 上用记事本/Excel 另存为会产出 GBK 或 UTF-16。少这道拦截，症状就是一个逃出
   257	        # 启动面的 `UnicodeDecodeError`——运维拿到半截栈，而不是"这个文件有问题"。
   258	        text = json.dumps({"identities": [_record("admin", display_name="管理员")]},
   259	                          ensure_ascii=False)
   260	        for encoding in ("utf-16", "gbk"):
   261	            with self.subTest(encoding=encoding):
   262	                self.enterprise.write_bytes(text.encode(encoding))
   263	                with self.assertRaises(directory.IdentityConfigError) as caught:
   264	                    self._load(include_demo=False)
   265	                self.assertIn(str(self.enterprise), str(caught.exception))
   266	
   267	    def test_a_path_occupied_by_a_directory_fails_like_a_malformed_file(self):
   268	        self.enterprise.unlink()
   269	        self.enterprise.mkdir()
   270	        with self.assertRaises(directory.IdentityConfigError):
   271	            self._load(include_demo=False)
   272	
   273	    def test_the_in_memory_record_path_is_not_wired_up_yet_and_says_so(self):
   274	        # 占位参数不许静默接活：传了就当场说"尚未实装"，而不是转身去读文件。
   275	        with self.assertRaises(directory.IdentityConfigError):
   276	            directory._validate_records(self.enterprise, [_record("admin")])
   277	
   278	
   279	class MergeInvariantTests(_IdentityFiles):
   280	    """合并不变量：enterprise 先、demo 后、重复即拒；唯一性在**合并后的全集**上判。"""
   281	
   282	    def test_duplicates_inside_one_file_are_rejected_too(self):
   283	        _write(self.enterprise, [_record("admin", feishu_open_id="ou_a"),
   284	                                 _record("admin", feishu_open_id="ou_b")])
   285	        with self.assertRaises(directory.IdentityConfigError):
   286	            self._load(include_demo=False)
   287	        _write(self.enterprise, [_record("a", feishu_open_id="ou_same"),
   288	                                 _record("b", feishu_open_id="ou_same")])
   289	        with self.assertRaises(directory.IdentityConfigError):
   290	            self._load(include_demo=False)
   291	
   292	    def test_the_conflict_message_names_the_clashing_identity_and_who_tried(self):
   293	        _write(self.enterprise, [_record("admin", role="ADMIN")])
   294	        _write(self.demo, [_record("admin", role="VIEWER")])
   295	        with self.assertRaises(directory.IdentityConfigError) as caught:
   296	            self._load(include_demo=True)
   297	        message = str(caught.exception)
   298	        self.assertIn("admin", message)
   299	        self.assertIn("users.demo.json", message, "冲突消息要点名是哪个文件想覆盖谁")
   300	
   301	    def test_a_broken_demo_file_cannot_reach_an_enterprise_load(self):
   302	        # "企业形态不读 demo 文件"的结构事实：demo 那份文件坏掉或消失都不影响 enterprise 读。
   303	        self.demo.write_text("{garbage", encoding="utf-8")
   304	        self.assertEqual({"admin"}, set(self._load(include_demo=False)))
   305	        self.demo.unlink()
   306	        self.assertEqual({"admin"}, set(self._load(include_demo=False)))
   307	        with self.assertRaises(directory.IdentityConfigError):
   308	            self._load(include_demo=True)
   309	
   310	
   311	class DirectoryReadFaceTests(_IdentityFiles):
   312	    """`identities()` / `get_identity()` / 缓存 / 测试接缝。"""
   313	
   314	    def test_the_read_face_follows_the_mode_switch(self):
   315	        self.assertEqual({"admin", "viewer"}, set(self._identities_at(enterprise_mode=False)))
   316	        self.assertEqual({"admin"}, set(self._identities_at(enterprise_mode=True)))
   317	
   318	    def test_the_directory_is_loaded_once_per_mode(self):
   319	        with mock.patch.object(directory, "load_identities",
   320	                               wraps=directory.load_identities) as loader:
   321	            self._identities_at(enterprise_mode=False)
   322	            self._identities_at(enterprise_mode=False)
   323	            self.assertEqual(1, loader.call_count)
   324	            self._identities_at(enterprise_mode=True)
   325	            self.assertEqual(2, loader.call_count,
   326	                             "两种形态共用一份缓存 ⇒ 企业形态会看到 demo 身份")
   327	            swapped = _write(self.root / "other.json", [_record("other")])
   328	            with mock.patch.object(directory, "ENTERPRISE_IDENTITIES_FILE", swapped):
   329	                self.assertEqual(2, loader.call_count,
   330	                                 "改文件不 reload 是刻意的：形态在进程生命周期内不变")
   331	
   332	    def test_reset_cache_forces_a_reload(self):
   333	        self._identities_at(enterprise_mode=False)
   334	        directory.reset_cache()
   335	        self.assertEqual({"admin", "viewer"}, set(self._identities_at(enterprise_mode=False)))
   336	
   337	    def test_get_identity_is_none_for_an_unknown_username(self):
   338	        self._identities_at(enterprise_mode=False)
   339	        self.assertEqual("ADMIN", directory.get_identity("admin").role)
   340	        self.assertIsNone(directory.get_identity("nobody"))
   341	        self.assertIsNone(directory.get_identity(""))
   342	
   343	    def test_override_identities_is_visible_and_is_always_restored(self):
   344	        before = dict(directory._CACHE)
   345	        replacement = {"ghost": UserIdentity(username="ghost", display_name="幽灵", role="HR")}
   346	        with directory.override_identities(replacement):
   347	            self.assertEqual({"ghost"}, set(directory.identities()))
   348	            self.assertIsNone(directory.get_identity("admin"))
   349	        self.assertEqual(before, dict(directory._CACHE), "接缝退出后缓存要还原成用例前的样子")
   350	
   351	    def test_override_identities_restores_even_when_the_body_raises(self):
   352	        with self.assertRaises(ZeroDivisionError):
   353	            with directory.override_identities({}):
   354	                raise ZeroDivisionError
   355	        self.assertEqual({"admin", "viewer"}, set(self._identities_at(enterprise_mode=False)))
   356	
   357	
   358	class ShippedIdentityFilesTests(unittest.TestCase):
   359	    """随镜像打包的那两份文件本身要过同一套校验，并且**出厂形态**要钉住。"""
   360	
   361	    def _load_shipped(self, *, include_demo: bool):
   362	        with mock.patch.object(directory, "ENTERPRISE_IDENTITIES_FILE", SHIPPED_ENTERPRISE), \
   363	                mock.patch.object(directory, "DEMO_IDENTITIES_FILE", SHIPPED_DEMO):
   364	            return directory.load_identities(include_demo=include_demo)
   365	
   366	    def test_both_files_ship_and_pass_their_own_validator(self):
   367	        self.assertTrue(SHIPPED_ENTERPRISE.is_file())
   368	        self.assertTrue(SHIPPED_DEMO.is_file())
   369	        self._load_shipped(include_demo=True)
   370	
   371	    def test_the_enterprise_file_ships_empty_so_enterprise_mode_starts_with_nobody(self):
   372	        # 企业形态的默认不是"5 个能登录的演示账号"，是零：身份由运维写进 users.json 再重建镜像。
   373	        self.assertEqual({}, self._load_shipped(include_demo=False))
   374	
   375	    def test_demo_mode_ships_exactly_the_demo_accounts(self):
   376	        loaded = self._load_shipped(include_demo=True)
   377	        self.assertEqual({"admin", "sales01", "hr01", "user", "viewer"}, set(loaded))
   378	        self.assertEqual({"ADMIN", "SALES", "HR", "USER", "VIEWER"},
   379	                         {identity.role for identity in loaded.values()})
   380	        self.assertTrue(all(identity.enabled for identity in loaded.values()))
   381	        self.assertTrue(all(identity.feishu_open_id is None for identity in loaded.values()))
   382	
   383	    def test_the_shipped_files_carry_relative_paths_as_the_deployment_contract(self):
   384	        # 镜像 WORKDIR 就是 `backend/`，`config/` 整目录随镜像 COPY（Dockerfile 已核）。
   385	        # 把这两枚常量绝对化等于换掉部署口径，所以钉字面值而不是"能读到"。
   386	        self.assertEqual(Path("config/users.json"), directory.ENTERPRISE_IDENTITIES_FILE)
   387	        self.assertEqual(Path("config/users.demo.json"), directory.DEMO_IDENTITIES_FILE)
   388	
   389	    def test_no_shipped_identity_record_carries_a_key_outside_the_closed_field_set(self):
   390	        # 直接扫 JSON 文本，不走 loader：loader 哪天被改松，这一枚还站着。
   391	        allowed = set(UserIdentity.model_fields)
   392	        for path in (SHIPPED_ENTERPRISE, SHIPPED_DEMO):
   393	            document = json.loads(path.read_text(encoding="utf-8"))
   394	            for record in document["identities"]:
   395	                with self.subTest(path=path.name, username=record.get("username")):
   396	                    self.assertEqual(set(), {str(k).lower() for k in record} - allowed)
   397	
   398	
   399	class IdentityCredentialSeparationTests(unittest.TestCase):
   400	    """SEC-A-010：一个单元不得同时持有身份与凭据状态。这里验身份侧的"不越界"。"""
   401	
   402	    FORBIDDEN_HEADS = ("hashlib", "argon2", "sqlite3", "hmac", "secrets")
   403	
   404	    @classmethod
   405	    def setUpClass(cls) -> None:
   406	        cls.tree = ast.parse(Path(directory.__file__).read_text(encoding="utf-8"))
   407	        cls.imported: list[str] = []
   408	        for node in ast.walk(cls.tree):
   409	            if isinstance(node, ast.Import):
   410	                cls.imported.extend(alias.name for alias in node.names)
   411	            elif isinstance(node, ast.ImportFrom) and node.module:
   412	                cls.imported.append(node.module)
   413	
   414	    def test_the_identity_module_imports_neither_hash_nor_a_database_driver(self):
   415	        heads = {name.split(".")[0] for name in self.imported}
   416	        self.assertEqual([], sorted(heads & set(self.FORBIDDEN_HEADS)), self.imported)
   417	
   418	    def test_settings_is_the_only_app_module_the_identity_layer_touches(self):
   419	        # `user_store` / `credentials` / `credentials_migration` 一旦进这张清单，
   420	        # 就是"同一单元同时持有身份与凭据"的开始（SEC-A-010 禁的那件事）。
   421	        self.assertEqual({"app.config"}, {n for n in self.imported if n.startswith("app.")})
   422	
   423	    def test_the_identity_module_never_calls_the_restricted_legacy_writer(self):
   424	        calls = [ast.unparse(node) for node in ast.walk(self.tree) if isinstance(node, ast.Call)]
   425	        self.assertEqual([], [c for c in calls if "import_legacy_digest" in c])
   426	
   427	
   428	class EnterpriseModeSwitchTests(unittest.TestCase):
   429	    """`SECURITY_ENTERPRISE_MODE` 是总开关，默认必须关掉——否则既有 dev/test 形态当场变。"""
   430	
   431	    def test_the_switch_exists_defaults_off_and_is_a_bool(self):
   432	        field = Settings.model_fields["security_enterprise_mode"]
   433	        self.assertIs(False, field.default)
   434	        self.assertIs(bool, field.annotation)
   435	
   436	    def test_the_shipped_settings_object_is_off(self):
   437	        self.assertFalse(config_module.settings.security_enterprise_mode,
   438	                         "默认值翻了 ⇒ 企业形态守卫会在没人配置的情况下生效")
   439	
   440	
   441	class KnowledgeOsReadPointTests(_IdentityFiles):
   442	    """身份读点迁移：`knowledge_os` 只认 directory，且换真源不许改响应形状。"""
   443	
   444	    def test_the_module_no_longer_names_the_legacy_constant_table(self):
   445	        tree = ast.parse((BACKEND_DIR / "app" / "knowledge_os.py").read_text(encoding="utf-8"))
   446	        bound = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
   447	        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
   448	                    for alias in node.names}
   449	        self.assertNotIn("USERS", bound | imported)
   450	        self.assertIn("get_identity", bound)
   451	        self.assertIn("directory_identities", bound)
   452	
   453	    def _mapping(self) -> dict[str, UserIdentity]:
   454	        return {
   455	            "admin": UserIdentity(username="admin", display_name="系统管理员", role="ADMIN"),
   456	            "sales01": UserIdentity(username="sales01", display_name="销售演示账号", role="SALES"),
   457	            "ghost": UserIdentity(username="ghost", display_name="没登录过的人", role="VIEWER"),
   458	        }
   459	
   460	    def _query(self, username: str) -> dict:
   461	        return {"action": "QUERY", "status": "SUCCESS", "username": username,
   462	                "timestamp": datetime.now(timezone.utc).isoformat(), "latency_ms": 100.0}
   463	
   464	    def test_usage_summary_counts_users_and_departments_from_the_directory(self):
   465	        events = [self._query("admin"), self._query("admin"), self._query("sales01"),
   466	                  self._query("someone-not-in-the-directory"),
   467	                  {"action": "QUERY", "status": "FAILED",
   468	                   "username": "admin", "timestamp": datetime.now(timezone.utc).isoformat()}]
   469	        admin = CurrentUser(username="admin", display_name="系统管理员", role="ADMIN")
   470	        with mock.patch.object(knowledge_os, "recent_events", return_value=events), \
   471	                directory.override_identities(self._mapping()):
   472	            payload = knowledge_os.usage_summary(admin)
   473	        self.assertEqual(3, payload["total_users"], "总数来自目录，不是常量表也不是凭据表")
   474	        self.assertEqual(3, payload["active_users"])
   475	        self.assertEqual(4, payload["queries_30d"])
   476	        self.assertEqual(100.0, payload["adoption_pct"])
   477	        self.assertEqual({"name": "平台管理", "queries": 2}, payload["top_department"])
   478	        self.assertEqual(4, payload["queries_today"])
   479	        self.assertEqual(100.0, payload["avg_latency_ms"])
   480	
   481	    def test_list_users_projects_identity_fields_and_keeps_the_response_shape(self):
   482	        login = {"action": "LOGIN", "status": "SUCCESS", "username": "admin",
   483	                 "timestamp": datetime.now(timezone.utc).isoformat()}
   484	        admin = CurrentUser(username="admin", display_name="系统管理员", role="ADMIN")
   485	        with mock.patch.object(knowledge_os, "recent_events", return_value=[login]), \
   486	                directory.override_identities(self._mapping()):
   487	            users = knowledge_os.list_users(admin)["users"]
   488	        order = {"admin": 0, "sales01": 1, "ghost": 2}
   489	        self.assertEqual(
   490	            [{"username": "admin", "display_name": "系统管理员", "role": "ADMIN",
   491	              "department": "平台管理", "status": "ACTIVE", "last_login": login["timestamp"]},
   492	             {"username": "sales01", "display_name": "销售演示账号", "role": "SALES",
   493	              "department": "销售", "status": "ACTIVE", "last_login": None},
   494	             {"username": "ghost", "display_name": "没登录过的人", "role": "VIEWER",
   495	              "department": "外部访客", "status": "ACTIVE", "last_login": None}],
   496	            sorted(users, key=lambda user: order[user["username"]]))
   497	
   498	    def test_an_unreadable_directory_cannot_be_papered_over_by_a_second_source(self):
   499	        # 目录读失败 ⇒ 端点报错，不许退回任何常量表。这是"唯一真源"的可观察面。
   500	        directory.reset_cache()
   501	        with mock.patch.object(directory, "load_identities",
   502	                               side_effect=directory.IdentityConfigError("坏文件")):
   503	            with self.assertRaises(directory.IdentityConfigError):
   504	                knowledge_os.usage_summary(
   505	                    CurrentUser(username="admin", display_name="系统管理员", role="ADMIN"))
   506	
   507	
   508	class TransitionalConsistencyPin(unittest.TestCase):
   509	    """Task 4→5 期间 `auth.USERS` 仍在（认证腿还没切）。这枚钉防两份身份漂移。
   510	
   511	    Task 5 删除 `USERS` 时**连这个类一起删**，不要改成"跳过"。
   512	    """
   513	
   514	    def test_directory_and_the_legacy_constant_table_describe_the_same_people(self):
   515	        from app import auth
   516	
   517	        with mock.patch.object(directory, "ENTERPRISE_IDENTITIES_FILE", SHIPPED_ENTERPRISE), \
   518	                mock.patch.object(directory, "DEMO_IDENTITIES_FILE", SHIPPED_DEMO):
   519	            loaded = directory.load_identities(include_demo=True)
   520	        self.assertEqual(set(auth.USERS), set(loaded))
   521	        for username, identity in loaded.items():
   522	            self.assertEqual(auth.USERS[username]["display_name"], identity.display_name)
   523	            self.assertEqual(auth.USERS[username]["role"], identity.role)

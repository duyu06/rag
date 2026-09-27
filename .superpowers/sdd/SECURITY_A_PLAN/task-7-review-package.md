# Task 7 review package (base = snap-task7-pre-*)
## stat
Files .superpowers/sdd/SECURITY_A_PLAN/snap-task7-pre-app/auth.py and backend/app/auth.py differ
Only in backend/app: cli.py
Files .superpowers/sdd/SECURITY_A_PLAN/snap-task7-pre-app/main.py and backend/app/main.py differ
## app diff
diff -ruN -U14 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task7-pre-app/auth.py backend/app/auth.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task7-pre-app/auth.py	2026-09-26 07:30:00.125297500 +0800
+++ backend/app/auth.py	2026-09-26 07:40:33.380388100 +0800
@@ -130,28 +130,74 @@
                 detail=f"missing_permission={permission}",
             )
         except Exception:
             pass
         raise HTTPException(status_code=403, detail=f"当前账号缺少权限：{permission}")
     return user
 
 
 def _password_change_required(username: str) -> bool:
     """门只读表：`must_change` 不是 claim 里的声明，是当前凭据状态（§8.4 末段）。"""
     record = user_store.get_record(username)
     return bool(record and record.must_change)
 
 
+#: 新口令规则的两枚边界（§8.8）。上限与 `LoginRequest.password` 的 `max_length` 同值：
+#: 一处事实抄两遍就会漂，漂了的症状是"登录进得来的口令改不进去"。
+_MIN_PASSWORD_LENGTH = 12
+_MAX_PASSWORD_LENGTH = 128
+
+COPY_PASSWORD_LENGTH = "新口令长度需在 12 到 128 个字符之间"
+COPY_PASSWORD_SAME_AS_USERNAME = "新口令不得与账号名相同"
+
+
+def validate_new_password(username: str, new_password: str) -> str | None:
+    """新口令的两条规则：长度带 + 不得回声账号名。返回中文理由，`None` = 通过。
+
+    这里**没有**弱口令词典——SEC-A 把它移出了范围。理由不是"词典难写"：同一个"太弱"在
+    登录腿与改密腿会给出两句不同的话，而 §9.1 要展示面可枚举、可翻译。长度下界挡的是零成本
+    爆破（Argon2 已经把在线慢验兜住），词典挡的是字典攻击却顺带挡掉合法口令，两者代价不同，
+    不该由同一个函数一起判。
+
+    返回值是**给用户看的那一句**（§9.1 展示面），机器可读性由调用方的状态码 422 承担；
+    函数不抛异常，因为它同时被 CLI 用在那里——CLI 要把这句话原样打到 stderr 上。
+    """
+    if not _MIN_PASSWORD_LENGTH <= len(str(new_password)) <= _MAX_PASSWORD_LENGTH:
+        return COPY_PASSWORD_LENGTH
+    if str(new_password).casefold() == str(username).casefold():
+        return COPY_PASSWORD_SAME_AS_USERNAME
+    return None
+
+
+def provision_credentials(username: str, *, plain_password: str, must_change: bool) -> int:
+    """唯一一条"把一个新口令落成可用凭据"的路径（自助改密 / 管理员重置 / CLI 共用）。
+
+    只产 argon2id：这里没有任何参数能让它产出别的算法（SEC-A-001），legacy 行也只有迁移器
+    写得出来（SEC-A-004）。两个分支的差别只在"表里有没有行"，写路径本身是同一条事务，
+    所以 bump 版本 + 清锁 + 置门这些副作用**不可能**只发生在其中一支。
+    `must_change` 由调用方给（改密传 False、重置传 True），这是两条腿共用一条写路径、
+    却不共用意图的唯一写法。返回落库后的 `credentials_version`：调用方要打印或签发的
+    正是"这一刻的凭据纪元"。
+    """
+    if user_store.get_record(username) is None:
+        return user_store.create_argon2(
+            username, plain_password=plain_password, must_change=must_change
+        )
+    return user_store.set_password_argon2(
+        username, plain_password=plain_password, must_change=must_change
+    )
+
+
 # ---------------------------------------------------------------------------
 # 登录腿（规格 §7.1 的顺序即契约）
 #
 # 身份读 `directory`、凭据状态读 `user_store`、口令运算只在 `credentials`——三处各自有
 # 唯一真源（SEC-A-010），这一层只是把它们按 §7.1 串起来，不在这里存任何用户材料。
 # ---------------------------------------------------------------------------
 
 #: 登录面 `detail` 的**全部**合法取值（§9.1 末段：自由文本不得进入该字段）。
 #: 成功面是空串——`main.py` 只在非空时叫 `record_login_event`，成功事件继续走既有
 #: `_audit(user, "LOGIN")`，那是 SEC-A-006 不许动的既有面。
 AUDIT_INVALID_CREDENTIALS = "invalid_credentials"
 AUDIT_LOGIN_LOCKED = "AUTH_LOGIN_LOCKED"
 AUDIT_REHASH_DEGRADED = "AUTH_REHASH_DEGRADED"
 
diff -ruN -U14 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task7-pre-app/cli.py backend/app/cli.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task7-pre-app/cli.py	1970-01-01 08:00:00.000000000 +0800
+++ backend/app/cli.py	2026-09-26 08:05:48.604080300 +0800
@@ -0,0 +1,127 @@
+"""凭据运维面（规格 §8.6 / §8.7）。口令只从环境变量读，绝不进 argv。
+
+argv 是**可观察**的：`ps`、shell history、CI 的日志抓取都会把口令抄走，所以这里没有
+`--password` 这一项，也不接受任何位置参数形式的口令。判据在契约用例里是按 argparse 的
+**行为**钉的（未定义选项 ⇒ `SystemExit`），不是翻 `--help` 文本——文本会随措辞漂移。
+
+`must_change` 由动作决定，而不是由写路径决定：`bootstrap-admin` 造的是"这个账号从此能登录"
+（门关上），`reset` 造的是"这口令不是你选的"（门开着）。两个动作走的是 `auth.provision_credentials`
+同一条写路径，因此清锁与版本 bump 不可能只在其中一支发生（SECA-12 / §7.5）。
+
+本模块**不**创建、**不**修改、也**不**启用或停用任何身份：身份的唯一真源是配置文件
+（SEC-A-010），CLI 顺手建号会造出第二个真源，而"停用一个账号"这件事在这里根本没有对应动作。
+"""
+
+from __future__ import annotations
+
+import argparse
+import os
+import sys
+
+from app import auth, credentials, credentials_migration, directory, user_store
+from app.audit import record_event
+from app.user_store import CredentialStoreError
+
+#: 口令的唯一来路。名字是运维接口的一部分（部署文档与 `.env` 模板都写它）。
+PASSWORD_ENV_VAR = "CREDENTIALS_PASSWORD"
+
+#: 动作 → 落库后的 `must_change`。缺这一格的动作在下面就被 argparse 拒了。
+_MUST_CHANGE_BY_ACTION = {"bootstrap-admin": False, "reset": True}
+
+_COPY_NO_ENV_PASSWORD = (
+    f"{PASSWORD_ENV_VAR} 未设置或不足 12 字符：口令只能放在这个环境变量里，"
+    "不接受任何命令行参数形式"
+)
+
+
+def build_parser() -> argparse.ArgumentParser:
+    parser = argparse.ArgumentParser(
+        prog="python -m app.cli", description="凭据运维面（口令只从环境变量读）"
+    )
+    commands = parser.add_subparsers(dest="command", required=True)
+    actions = commands.add_parser("credentials").add_subparsers(
+        dest="action", required=True
+    )
+    bootstrap = actions.add_parser(
+        "bootstrap-admin", help="为**已存在的**身份写入 argon2id 凭据"
+    )
+    bootstrap.add_argument("--username", required=True)
+    reset = actions.add_parser("reset", help="重置口令并强制下次登录改密")
+    reset.add_argument("--username", required=True)
+    actions.add_parser("migration-status", help="打印各算法行数与逐账号状态")
+    return parser
+
+
+def _password_from_env() -> str | None:
+    """读出口令；缺失或不足下界时返回 None，由调用方给出**同一句**提示。
+
+    两条输入形状（没设 / 太短）必须汇成一句可执行的话：分成两句就会有一句在讲"你给的
+    值太短"——那等于把值本身的存在性说出去了。这里任何分支都不打印取值。
+    """
+    value = os.environ.get(PASSWORD_ENV_VAR)
+    if value is None or len(value) < auth._MIN_PASSWORD_LENGTH:
+        return None
+    return value
+
+
+def _print_status() -> int:
+    status = credentials_migration.status()
+    print(f"legacy_count={status.legacy_count} argon2id_count={status.argon2id_count}")
+    for row in status.accounts:
+        print(
+            f"{row.username}\t{row.algorithm}\tv{row.credentials_version}"
+            f"\tmust_change={int(row.must_change)}\tlocked={row.locked_until or '-'}"
+        )
+    return 0
+
+
+def main(argv: list[str] | None = None) -> int:
+    args = build_parser().parse_args(argv)
+    # 建表是 `credentials_migration` 的调用方前置条件（它的读路径不建表），放在这里
+    # 而不是各动作内部：`migration-status` 与两条写腿都要过这一道。
+    user_store.ensure_user_credentials_schema()
+    if args.action == "migration-status":
+        return _print_status()
+
+    identity = directory.get_identity(args.username)
+    if identity is None:
+        print(f"身份不存在：{args.username}（请先写入 config/users.json）", file=sys.stderr)
+        return 2
+    password = _password_from_env()
+    if password is None:
+        print(_COPY_NO_ENV_PASSWORD, file=sys.stderr)
+        return 2
+    reason = auth.validate_new_password(args.username, password)
+    if reason:
+        print(reason, file=sys.stderr)
+        return 2
+
+    must_change = _MUST_CHANGE_BY_ACTION[args.action]
+    try:
+        version = auth.provision_credentials(
+            args.username, plain_password=password, must_change=must_change
+        )
+    except CredentialStoreError as exc:
+        # 固定文案、零口令：`user_store` 的异常消息本身就不带凭据材料，原样转出去即可。
+        print(str(exc), file=sys.stderr)
+        return 1
+    finally:
+        # 用完立刻从本进程的环境里抹掉：后面任何一次 print、异常或子进程继承都不该再拿到它。
+        os.environ.pop(PASSWORD_ENV_VAR, None)
+
+    record_event(
+        username=args.username,
+        role=identity.role,
+        action="PASSWORD",
+        status="SUCCESS",
+        detail="credential_bootstrap" if args.action == "bootstrap-admin" else "password_reset_by_admin",
+    )
+    print(
+        f"{args.username}: algorithm={credentials.ALGORITHM_ARGON2ID}"
+        f" version={version} must_change={int(must_change)}"
+    )
+    return 0
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())
diff -ruN -U14 -x __pycache__ .superpowers/sdd/SECURITY_A_PLAN/snap-task7-pre-app/main.py backend/app/main.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task7-pre-app/main.py	2026-09-26 07:30:00.181919000 +0800
+++ backend/app/main.py	2026-09-26 08:07:01.984431900 +0800
@@ -7,38 +7,42 @@
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
+    _MAX_PASSWORD_LENGTH,
     _password_change_required,
     authenticate_with_result,
     has_permission,
     issue_token,
+    provision_credentials,
     record_login_event,
     require_permission,
     require_user_pending_password,
+    validate_new_password,
 )
 from app.config import settings
 from app.demo import demo_status, initialize_demo, reset_demo
+from app.directory import get_identity as get_user_identity
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
 from app.rag import MODEL_USED_KEY, current_model_name, generate_answer
 from app.retrieval import retrieval_service
@@ -79,28 +83,41 @@
 app.add_middleware(
     CORSMiddleware,
     allow_origins=["*"],
     allow_credentials=False,
     allow_methods=["*"],
     allow_headers=["*"],
 )
 
 
 class LoginRequest(BaseModel):
     username: str = Field(min_length=1, max_length=64)
     password: str = Field(min_length=1, max_length=128)
 
 
+class PasswordChangeRequest(BaseModel):
+    # 两个字段的 `min_length` 都是 1，不是笔误：短口令的"不合格"必须由 `validate_new_password`
+    # 用中文说（§9.1 展示面），而不是由 pydantic 用英文结构错误说；旧口令这一侧更要如此——
+    # 一个 legacy 出身的账号旧口令本来就可以只有 8 位，先 422 就把 401 那条正确文案挡住了。
+    # 上限引 `auth._MAX_PASSWORD_LENGTH`：与登录面同值，抄字面量就会漂。
+    current_password: str = Field(min_length=1, max_length=_MAX_PASSWORD_LENGTH)
+    new_password: str = Field(min_length=1, max_length=_MAX_PASSWORD_LENGTH)
+
+
+class AdminPasswordResetRequest(BaseModel):
+    new_password: str = Field(min_length=1, max_length=_MAX_PASSWORD_LENGTH)
+
+
 class QueryRequest(BaseModel):
     question: str = Field(min_length=1, max_length=1000)
     k: int = Field(default=5, ge=1, le=20)
     include_sources: bool = True
     use_hybrid_search: bool = True
     use_reranking: bool = False
     knowledge_base_id: str | None = None
 
 
 class DebugRequest(BaseModel):
     query: str = Field(min_length=1, max_length=1000)
     mode: Literal["vector", "bm25", "hybrid"] = "hybrid"
     top_k: int = Field(default=8, ge=1, le=30)
     rerank: bool = False
@@ -258,28 +275,93 @@
         "user": user.model_dump(),
         # §11 声明的本版唯一一处响应面键集合变化（additive）。值取自登录腿已经算好的那一格，
         # 不在这里再查一次表：同一条判定有两个读数点，早晚会在"登录刚置门"这类中间态上劈叉。
         "password_change_required": result.password_change_required,
     }
 
 
 @app.get("/api/auth/me")
 def me(user: CurrentUser = Depends(require_user_pending_password)):
     # 同一个布尔键在这里必须**读表**：`/me` 拿到的是任意时刻的既有 token，签发那一刻的门状态
     # 早就不是当前事实了（改密页与前端引导都靠这一格判断要不要留在改密流程里）。
     return {**user.model_dump(), "password_change_required": _password_change_required(user.username)}
 
 
+@app.post("/api/auth/password/change")
+def change_password(
+    request: PasswordChangeRequest,
+    user: CurrentUser = Depends(require_user_pending_password),
+):
+    """自助改密：带着旧口令来，带着**新的一枚** token 走（§8.7 / §7.5）。
+
+    顺序即契约：策略 422 → 旧口令 401 → 写库 → 签新 token。
+    - 422 排在口令校验之前：`new_password` 太短或与账号名同形都不涉及任何凭据事实，
+      而口令校验要付一次 Argon2。
+    - 旧口令走 `authenticate_with_result`：它带旧口令校验，所以这一条腿与登录是**同一个**
+      爆破面，共用同一份账号级失败/锁定状态（`failed_attempts` 与 `locked_until` 就在这一跳
+      被写被读）。这里不自造第二把计数器——两把计数器等于给攻击者一条不被记录的通道。
+    - 版本 bump 会废掉**包括来路那一枚在内**的全部已发 token（§7.5）。因此响应必须交出一枚
+      新签的：否则走完强制改密流程的人会在下一跳被弹回登录页，而"改密腿在 must_change 期间
+      可达"这件事就只剩一半。新 token 在写库**之后**签，`issue_token` 读到的才是新一代纪元。
+    """
+    reason = validate_new_password(user.username, request.new_password)
+    if reason:
+        raise HTTPException(status_code=422, detail=reason)
+    result = authenticate_with_result(user.username, request.current_password)
+    if result.user is None:
+        # 四种失败态（含锁定期）到这里已经塌成同一条 401 + 同一段中文，与登录面一字不差；
+        # 区别只在审计 token，而那个只进审计面。
+        record_login_event(username=user.username, detail=result.audit_detail)
+        raise HTTPException(status_code=401, detail="用户名或密码错误")
+    provision_credentials(
+        user.username, plain_password=request.new_password, must_change=False
+    )
+    _audit(result.user, "PASSWORD", status="SUCCESS", detail="password_changed")
+    return {
+        "changed": True,
+        "access_token": issue_token(result.user),
+        "token_type": "bearer",
+        # 读表而不是写死 False：这一格与 `require_user` 那道门用的是同一个谓词，两边读数一旦
+        # 劈叉，症状就是"界面说改完了、下一跳还是 403"。
+        "password_change_required": _password_change_required(result.user.username),
+    }
+
+
+@app.post("/api/admin/users/{username}/password/reset")
+def admin_reset_password(
+    username: str,
+    request: AdminPasswordResetRequest,
+    user: CurrentUser = Depends(require_permission("system:operate")),
+):
+    """管理员重置：设一个管理员知道的口令，并把门开给下一次登录（§8.6）。
+
+    用的是**既有**能力 `system:operate`，不新增权限名——角色权限矩阵是冻结契约。
+    `must_change=True` 是这条腿的语义本身：不置门等于把"这个账号从此用别人给的口令"留成静默。
+    口令、hash、长度一概不上响应面；`must_change` 那一格读表，理由与上面同一条。
+
+    未知身份给 404「账号不存在」不构成枚举面：能走到这一格的主体已经过 `system:operate` 鉴权，
+    对外那张脸是登录腿的四态合一（§9.1）。
+    """
+    reason = validate_new_password(username, request.new_password)
+    if reason:
+        raise HTTPException(status_code=422, detail=reason)
+    if get_user_identity(username) is None:
+        raise HTTPException(status_code=404, detail="账号不存在")
+    provision_credentials(username, plain_password=request.new_password, must_change=True)
+    _audit(user, "PASSWORD", status="SUCCESS", detail="password_reset_by_admin")
+    return {"reset": True, "must_change": _password_change_required(username)}
+
+
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
         chunks = vector_store.all_chunks(knowledge_base_ids=kb_ids)
         store_stats = vector_store.stats(knowledge_base_ids=kb_ids)

## test diff (test_password_lifecycle_contract.py)
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task7-pre-test_password_lifecycle_contract.py	2026-09-26 07:30:00.412192400 +0800
+++ backend/tests/test_password_lifecycle_contract.py	2026-09-26 07:46:08.300344900 +0800
@@ -31,44 +31,47 @@
 已知边界（写在这里，不留给下一个人猜）：第 4 项判的是"**已被认证覆盖的**端点有没有都过门"。
 一条压根不挂任何认证依赖的端点、或自造第三条依赖绕开这两个门面的端点，不在本门的判定对象内
 （前者属"根本没鉴权"那一类缺陷，后者要靠评审看 diff）；本枚门不假装覆盖它们。但**枚举自己
 看得见的边界**是断言而不是假设：挂载点、非 `APIRoute` 的服务面、表上出现未知 HTTP 动词，
 都会先红在前提那一枚用例上，而不是让覆盖面从此静默变窄。
 """
 
 from __future__ import annotations
 
 import ast
 import contextlib
 import hashlib
+import io
 import json
+import os
 import sys
 import unittest
 from pathlib import Path
 from typing import Callable
 from unittest import mock
 
 import jwt as pyjwt
 from fastapi import HTTPException
 from fastapi.routing import APIRoute
 from fastapi.testclient import TestClient
 from starlette.routing import Match, Mount
 
 BACKEND_DIR = Path(__file__).resolve().parents[1]
 TESTS_DIR = BACKEND_DIR / "tests"
 for _path in (str(BACKEND_DIR), str(TESTS_DIR)):
     if _path not in sys.path:
         sys.path.insert(0, _path)
 
 from app import auth, credentials, directory, user_store  # noqa: E402
+from app import cli  # noqa: E402  —— 凭据运维面（本文件是它唯一的契约读者）
 from app import config as config_module  # noqa: E402
 from app import main as main_module  # noqa: E402  —— 桩要打在这份命名空间里的绑定上，见 `LoginFaceKeyTests`
 import app.main_agent  # noqa: E402,F401  —— uvicorn 跑的是 `app.main_agent:app`：三张 router 挂在同一个 app 实例上，少 import 这一行，覆盖面就只剩半张表
 from app.main import app  # noqa: E402
 import sec_a_fixtures  # noqa: E402  —— 换库 / 审计落点 / JWT secret 三件地基只留一份实现
 from sec_a_seed import ensure_demo_credentials  # noqa: E402
 
 INVALID_TOKEN = "无效登录凭证"
 GATE_COPY = "当前账号需先修改口令"
 GOOD_PASSWORD = "a-good-password 123456"
 NEW_PASSWORD = "a-brand-new-password 123"
 LEGACY_ADMIN = hashlib.sha256(b"admin123").hexdigest()
@@ -777,40 +780,57 @@
                 if isinstance(value, str):
                     # 只判字符串取值：`permissions` 那一格是 list，`in` 一枚 set 会先撞
                     # unhashable 而不是给出结论。
                     self.assertNotIn(value, tokens, f"{key} 的取值成了审计 token")
         self.assertIsInstance(login["password_change_required"], bool)
         self.assertIsInstance(me["password_change_required"], bool)
 
 
 class MustChangeGateCoverageTests(_LongJwtSecret, _AuditToTempFile, unittest.TestCase):
     """SECA-10：门必须由路由表自证覆盖，不靠手写清单——新增端点忘了登记就直接红。"""
 
     #: 改密端点落地时必须同时把本集合扩成两项——这条断言会在漏扩时立刻红（多一条也红）。
-    WHITELIST = frozenset({"GET /api/auth/me"})
+    WHITELIST = frozenset({"POST /api/auth/password/change", "GET /api/auth/me"})
+
+    #: 白名单两条腿各自的"合法请求"与"放行后必须看到的那一格"。只比集合相等会被"整表为空"
+    #: 骗过去（见 `test_the_pending_dependency_is_used_by_the_whitelist_only`）：改密这条腿
+    #: 免的是门，不免请求体，所以它得带着**合法** body 进来才算真到了处理器。
+    PENDING_PROBE = {
+        "GET /api/auth/me": (
+            None,
+            lambda body: body["password_change_required"] is True,
+        ),
+        "POST /api/auth/password/change": (
+            {"current_password": GOOD_PASSWORD, "new_password": NEW_PASSWORD},
+            lambda body: body["changed"] is True and isinstance(body["access_token"], str),
+        ),
+    }
 
     #: 表里出现的每一个 path 参数都得有样例；样例只用"必然不存在"的 id，让放行分支顶多
     #: 走到 404/403，不会真读到别人的数据。这条规则不是洁癖：处理器可达恰恰发生在"门退化"
     #: 那一次运行里，用真 KB id 就等于把那次跑测试变成一次真读。
     PARAM_SAMPLES = {
         "conversation_id": "conv-nonexistent",
         "message_id": "msg-nonexistent",
         "document_id": "doc-nonexistent",
         "knowledge_base_id": "kb-nonexistent",
         "kb_id": "kb-nonexistent",
         "run_id": "run-nonexistent",
         "trace_id": "trace-nonexistent",
         "job_id": "job-nonexistent",
         "case_id": "case-nonexistent",
         "file_name": "absent.txt",
+        #: 管理员重置腿的账号名。样例取"必然不存在"的名字：可达时它顶多走到 404「账号不存在」，
+        #: 不会真改掉任何一个活账号的凭据。
+        "username": "user-nonexistent",
         #: `action` 不是 id，是一条枚举：`list` 落在 `document_action` 的白名单**之外**，
         #: 于是可达时它先 400/422 而不会真去重建索引或移动文件。
         "action": "list",
     }
 
     #: 规格 §8.4 点名的三条腿 + 名册那一面：枚举机制一旦失效（依赖树读空、qualname 漂了），
     #: authenticated 集合会缩水成空集，只靠"每条都 403"是判不出来的——那叫没人参加的检查。
     #: `POST /api/demo/reset` 也在内：它是这条扫描唯一一处"门没了就会真删数据"的端点，
     #: 扫描的安全论证要求它**必须**在覆盖面里被上桩，而不是靠运气不在清单上。
     MUST_BE_COVERED = frozenset({
         "POST /api/query",
         "POST /api/query/stream",
@@ -1004,30 +1024,41 @@
             getattr(route, "path", type(route).__name__)
             for route in app.routes
             if not isinstance(route, APIRoute)
             and (
                 str(getattr(route, "path", "")).startswith("/api")
                 or getattr(route, "dependant", None) is not None
                 or getattr(route, "methods", None) is None
             )
         ]
         self.assertEqual([], off_enumeration, "非 APIRoute 的条目带着服务面：枚举不覆盖它")
 
     def test_the_pending_dependency_is_used_by_the_whitelist_only(self):
-        """白名单那一条得**真的**在免门腿上：只比集合相等会被"整表为空"骗过去。"""
-        for key in self.WHITELIST:
+        """白名单那两条得**真的**在免门腿上：只比集合相等会被"整表为空"骗过去。
+
+        两条腿各有各的"到得了"形状：`/me` 无 body，改密腿要带合法 body（少这一格，改密腿
+        会因为"空 body 先 422"而被误判成"门没挡 = 白名单生效"）。判据用 `PENDING_PROBE` 里
+        那一格**值**，不是状态码——200 而键值不对同样是没走到真处理器。
+        """
+        for key in sorted(self.WHITELIST):
             method, path = key.split(" ", 1)
-            response = self.client.request(method, self._url(path), headers=_bearer(self.token))
-            self.assertEqual(200, response.status_code, response.text)
-            self.assertTrue(response.json()["password_change_required"])
+            body, observes = self.PENDING_PROBE[key]
+            request: dict[str, object] = {"headers": _bearer(self.token)}
+            if body is not None:
+                request["json"] = body
+            response = self.client.request(method, self._url(path), **request)
+            self.assertEqual(200, response.status_code, f"{key}: {response.text}")
+            payload = response.json()
+            self.assertTrue(observes(payload), f"{key} 到了处理器，但那一格不对：{payload}")
+            self.assertNotEqual(GATE_COPY, payload.get("detail"))
 
     # --- 工具 ------------------------------------------------------------
     def _url(self, path: str) -> str:
         url = path
         for name, sample in self.PARAM_SAMPLES.items():
             url = url.replace("{" + name + "}", sample)
         return url
 
     def _arm(self, route: APIRoute, route_key: str) -> None:
         """给这条路由上绊线桩（实现见 `_arm_tripwire`），并记下桩本身用于派发核对。"""
         self.stub_of[id(route)] = _arm_tripwire(self, route, route_key, self.tripped)
 
@@ -1091,14 +1122,476 @@
         self.assertEqual(GATE_COPY, blocked.json()["detail"])
         self.assertEqual([], self.tripped, "处理器可达：本例不必叫到业务层就能判")
         self.assertEqual(
             [("AUTHORIZATION", "DENIED", "password_change_required")],
             [
                 (e["action"], e["status"], e["detail"])
                 for e in self.events()
                 if e["action"] == "AUTHORIZATION"
             ],
         )
 
 
+# ---------------------------------------------------------------------------
+# 口令策略 / 自助改密 / 管理员重置 / 凭据运维面（§8.6 / §8.7 / §8.8）
+# ---------------------------------------------------------------------------
+
+#: §8.8 的三条长度/回声判据在 HTTP 面上的那一句中文（422 的展示面）。
+COPY_TOO_SHORT = "新口令长度需在 12 到 128 个字符之间"
+COPY_SAME_AS_USERNAME = "新口令不得与账号名相同"
+COPY_BAD_CREDENTIALS = "用户名或密码错误"
+COPY_NO_ACCOUNT = "账号不存在"
+AUDIT_PASSWORD_CHANGED = "password_changed"
+AUDIT_RESET_BY_ADMIN = "password_reset_by_admin"
+AUDIT_BOOTSTRAP = "credential_bootstrap"
+
+
+def _seed_legacy_admin(user_store_module: object, auth_module: object) -> None:
+    """把 admin 的那一行换成 legacy(sha256) 出身并置门——升级路径的**起点**形状。
+
+    先删后种是必须的：`import_legacy_digest` 带 `ON CONFLICT DO NOTHING`，行已在场时它一根
+    手指都不碰（那是迁移器 `only_missing` 口径的下半），于是"种成 legacy"会静默变成"留着
+    argon2 行"，这条用例从此永远绿。
+    两个模块参数按调用形状留着并当场核对：本例判的是登录腿会不会把 legacy 行升上去，种行的
+    人与读行的人必须是同一对模块对象——reload 把两边劈开时，红要红在夹具上而不是红在断言上。
+    """
+    if auth_module is not auth or user_store_module is not user_store:
+        raise AssertionError("_seed_legacy_admin 只认本文件导入的那一对模块对象")
+    user_store.delete_record("admin")
+    user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
+
+
+def _identity_file_bytes() -> dict[str, bytes | None]:
+    """两份身份文件的当前字节（不在场 ⇒ None）。
+
+    `directory` 的路径常量是**相对**的（部署口径，镜像 WORKDIR 就是 `backend/`，不许改绝对），
+    而本套件按两种 cwd 跑：从仓库根起那条相对路径指向不存在的位置。这里按
+    `conftest.shipped_identity_files` 的同一手法锚到 `BACKEND_DIR` 上再读，否则"CLI 不改身份
+    文件"这条判据会在其中一种 cwd 下先把用例自己判死。
+    """
+    snapshot: dict[str, bytes | None] = {}
+    for path in (directory.ENTERPRISE_IDENTITIES_FILE, directory.DEMO_IDENTITIES_FILE):
+        target = path if path.is_absolute() else BACKEND_DIR / path
+        snapshot[str(path)] = target.read_bytes() if target.exists() else None
+    return snapshot
+
+
+def _run_cli(argv: list[str]) -> tuple[int, str, str]:
+    """跑一次 CLI，把 `(exit_code, stdout, stderr)` 一起交回来。
+
+    口令的正确性判据全都落在这三格里：口令**不许**出现在任何一格，所以捕获必须是原文而不是
+    "只看退出码"。
+    """
+    out, err = io.StringIO(), io.StringIO()
+    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
+        code = cli.main(argv)
+    return code, out.getvalue(), err.getvalue()
+
+
+class _ClientCase(_LongJwtSecret, _AuditToTempFile, unittest.TestCase):
+    """HTTP 腿与 CLI 腿的共同地基：每例一份临时库、三行 demo 凭据、一个 client。
+
+    只种 admin / viewer / hr01：`sales01` 与 `user` 刻意**留空**——它们是"有身份无凭据行"
+    那条腿的判据对象，bootstrap 与管理员重置要在它们身上**新建**（`create_argon2` 那一支），
+    而不是撞进一次 `CredentialStoreError`。
+    """
+
+    def setUp(self):
+        super().setUp()
+        _fresh_db(self)
+        ensure_demo_credentials("admin", "viewer", "hr01")
+        self.client = TestClient(app)
+
+    def _login(self, username: str, password: str):
+        return self.client.post(
+            "/api/auth/login", json={"username": username, "password": password}
+        )
+
+    def _headers(self, username: str, password: str) -> dict[str, str]:
+        response = self._login(username, password)
+        self.assertEqual(200, response.status_code, response.text)
+        return _bearer(response.json()["access_token"])
+
+    def _admin_headers(self) -> dict[str, str]:
+        return self._headers("admin", "admin123")
+
+    def _post(self, path: str, body: dict[str, str], headers: dict[str, str]):
+        return self.client.post(path, json=body, headers=headers)
+
+
+class PasswordPolicyTests(_ClientCase):
+    #: 长度下界的两侧（11/12）与上界的两侧（128/129）都在这里，判据是**函数**而不是文案：
+    #: 文案归 §9.1 的展示面管，边界归策略管，两处混判就会出现"改了字就以为改了规则"。
+    POLICY_CASES: tuple[tuple[str, str, bool], ...] = (
+        ("someone", "l" * 11, False),
+        ("someone", "l" * 12, True),
+        ("someone", "l" * 128, True),
+        ("someone", "l" * 129, False),
+        ("admin", "ADMIN", False),
+        ("admin", "AdMiN", False),
+        ("admin", "admin", False),
+    )
+
+    def test_short_passwords_and_username_echo_are_rejected_with_422(self):
+        """§8.8：422 是输入校验，403 是权限。混用会污染既有 RBAC 语义面。"""
+        body = {"current_password": "admin123", "new_password": "abc"}
+        response = self._post(
+            "/api/auth/password/change", body, self._admin_headers()
+        )
+        self.assertEqual(422, response.status_code, response.text)
+        # 展示面是中文：422 由策略判出，不是 pydantic 那句英文（见 `PasswordChangeRequest`）。
+        self.assertEqual(COPY_TOO_SHORT, response.json()["detail"])
+        for candidate in ("admin", "ADMIN", "AdMiN"):
+            self.assertIsNotNone(auth.validate_new_password("admin", candidate))
+        self.assertIsNone(auth.validate_new_password("admin", "a-good-new-password 123"))
+
+    def test_policy_accepts_a_12_char_and_rejects_a_129_char_password(self):
+        self.assertIsNone(auth.validate_new_password("someone", "l" * 12))
+        self.assertIsNotNone(auth.validate_new_password("someone", "l" * 129))
+
+    def test_the_policy_boundaries_are_exactly_the_ones_the_spec_names(self):
+        for username, password, accepted in self.POLICY_CASES:
+            with self.subTest(length=len(password), username=username):
+                reason = auth.validate_new_password(username, password)
+                if accepted:
+                    self.assertIsNone(reason)
+                else:
+                    self.assertIsNotNone(reason)
+
+    def test_a_new_password_that_echoes_a_long_username_is_rejected_with_422_copy(self):
+        """回声规则在 HTTP 面上的形状：它排在长度**之后**，所以判据账号名得够 12 字符。
+
+        取一个长账号名不是绕路：`admin` 的任何 casefold 等值串都短于下界，那条规则在短名账号
+        上永远轮不到发言——只看函数级判据会把它当成"已经生效"，而它在真请求上先被长度挡掉。
+        """
+        name = "operations-lead-01"
+        identity = _identity(name, role="ADMIN")
+        user_store.create_argon2(name, plain_password=GOOD_PASSWORD, must_change=False)
+        with directory.override_identities({**dict(directory.identities()), name: identity}):
+            headers = self._headers(name, GOOD_PASSWORD)
+            response = self._post(
+                "/api/auth/password/change",
+                {"current_password": GOOD_PASSWORD, "new_password": name.upper()},
+                headers,
+            )
+        self.assertEqual(422, response.status_code, response.text)
+        self.assertEqual(COPY_SAME_AS_USERNAME, response.json()["detail"])
+        # 被拒的那一次**不写任何凭据**：策略排在写路径之前，否则"先落库再判"就把旧口令换掉了。
+        self.assertEqual(1, user_store.get_record(name).credentials_version)
+
+    def test_no_weak_password_dictionary_exists_on_the_policy_face(self):
+        """SEC-A 把弱口令词典**移出**了范围：字典会在两条腿上给出不同的拒绝理由。"""
+        self.assertIsNone(auth.validate_new_password("someone", "Password1!abc"))
+        self.assertNotIn("弱", COPY_TOO_SHORT + COPY_SAME_AS_USERNAME)
+
+
+class SelfServiceChangeTests(_ClientCase):
+    CHANGE_PATH = "/api/auth/password/change"
+
+    def _change(self, headers: dict[str, str], *, current: str, new: str):
+        return self._post(
+            self.CHANGE_PATH,
+            {"current_password": current, "new_password": new},
+            headers,
+        )
+
+    def test_changing_password_logs_in_clears_the_gate_and_kills_old_tokens(self):
+        """SECA-03 半边 B：升级路径的终态是"改完密就能正常用"。"""
+        _seed_legacy_admin(user_store, auth)
+        login = self._login("admin", "admin123")
+        self.assertTrue(login.json()["password_change_required"])
+        old = _bearer(login.json()["access_token"])
+        blocked = self.client.get("/api/knowledge-bases", headers=old)
+        self.assertEqual((403, GATE_COPY), (blocked.status_code, blocked.json()["detail"]))
+
+        changed = self._change(old, current="admin123", new=NEW_PASSWORD)
+        self.assertEqual(200, changed.status_code, changed.text)
+        self.assertEqual(credentials.ALGORITHM_ARGON2ID, user_store.get_record("admin").algorithm)
+        self.assertFalse(user_store.get_record("admin").must_change)
+        # 旧 token 已经随着版本 bump 出局（§7.5，Task 6 钉过），"改完密就能用"这一句只能由
+        # 响应里那枚**新** token 兑现——少了它，走完强制改密流程的人被弹回登录页。
+        self.assertEqual(
+            (401, INVALID_TOKEN),
+            (
+                self.client.get("/api/knowledge-bases", headers=old).status_code,
+                self.client.get("/api/knowledge-bases", headers=old).json()["detail"],
+            ),
+        )
+        fresh = _bearer(changed.json()["access_token"])
+        self.assertEqual(200, self.client.get("/api/knowledge-bases", headers=fresh).status_code)
+        self.assertFalse(self.client.get("/api/auth/me", headers=fresh).json()["password_change_required"])
+
+    def test_the_change_response_shape_is_pinned_and_carries_no_password(self):
+        """响应面：一枚活 token + 两枚机器可读布尔键，零口令、零 hash、零长度。"""
+        token = self._login("admin", "admin123").json()["access_token"]
+        changed = self._change(_bearer(token), current="admin123", new=NEW_PASSWORD)
+        body = changed.json()
+        self.assertEqual(
+            {"changed", "access_token", "token_type", "password_change_required"}, set(body)
+        )
+        self.assertIs(True, body["changed"])
+        self.assertIs(False, body["password_change_required"], "改完密还报 True = 门与表劈叉")
+        self.assertIsInstance(body["access_token"], str)
+        self.assertNotEqual(token, body["access_token"], "回手交出旧 token：撤销没生效")
+        self.assertEqual("bearer", body["token_type"])
+        self.assertNotIn("admin123", changed.text)
+        self.assertNotIn(NEW_PASSWORD, changed.text)
+        self.assertNotIn("$argon2", changed.text)
+        # 新 token 的版本号必须与表一致（旧 token 的 cv 已经死了，靠的是这一格）。
+        self.assertEqual(
+            user_store.get_record("admin").credentials_version,
+            _decode(body["access_token"])[auth.CREDENTIAL_VERSION_CLAIM],
+        )
+
+    def test_changing_requires_the_current_password(self):
+        headers = self._admin_headers()
+        response = self._change(
+            headers, current="not-my-password 123", new=NEW_PASSWORD
+        )
+        self.assertEqual(401, response.status_code, response.text)
+        self.assertEqual(COPY_BAD_CREDENTIALS, response.json()["detail"])
+        # 展示面是中文文案，审计面是枚举 token（规格 §9.1 的两栏模型）。
+        from app.audit import recent_events
+
+        self.assertEqual("invalid_credentials", recent_events(limit=1)[0]["detail"])
+        self.assertEqual(1, user_store.get_record("admin").credentials_version)
+        self.assertEqual(1, user_store.get_record("admin").failed_attempts)
+
+    def test_the_change_leg_shares_the_login_lockout_state_rather_than_a_second_counter(self):
+        """改密腿带旧口令校验 ⇒ 它与登录是**同一个**爆破面（SECA-07 的键只有 username）。
+
+        这一枚只钉"共用"这件事本身：把账号锁住之后改密腿给出的必须是登录腿那一条 401 文案 +
+        `AUTH_LOGIN_LOCKED` token，而不是自造的第二套状态。节流算法本体在下一期。
+        """
+        headers = self._admin_headers()
+        user_store.record_login_failure("admin", max_attempts=1, lock_seconds=900)
+        response = self._change(headers, current="admin123", new=NEW_PASSWORD)
+        self.assertEqual(401, response.status_code, response.text)
+        self.assertEqual(COPY_BAD_CREDENTIALS, response.json()["detail"])
+        from app.audit import recent_events
+
+        self.assertEqual("AUTH_LOGIN_LOCKED", recent_events(limit=1)[0]["detail"])
+        record = user_store.get_record("admin")
+        self.assertEqual(1, record.credentials_version, "锁定期里口令被换掉了")
+        self.assertIsNotNone(record.locked_until)
+
+    def test_the_change_leg_needs_a_token_and_sits_on_the_pending_side(self):
+        """免门**不免身份**：没有 token 进来就是 401，与 `/me` 同一条腿。"""
+        anonymous = self.client.post(
+            self.CHANGE_PATH,
+            json={"current_password": "admin123", "new_password": NEW_PASSWORD},
+        )
+        self.assertEqual(401, anonymous.status_code, anonymous.text)
+        self.assertEqual("请先登录", anonymous.json()["detail"])
+        # 门后的账号改得了自己的密（这正是它在白名单里的理由）。
+        user_store.set_password_argon2("admin", plain_password=NEW_PASSWORD, must_change=True)
+        gate = self._login("admin", NEW_PASSWORD).json()["access_token"]
+        changed = self._change(_bearer(gate), current=NEW_PASSWORD, new=GOOD_PASSWORD)
+        self.assertEqual(200, changed.status_code, changed.text)
+        self.assertFalse(user_store.get_record("admin").must_change)
+
+    def test_a_successful_change_leaves_the_enum_audit_token_and_no_password(self):
+        headers = self._admin_headers()
+        self.assertEqual(200, self._change(headers, current="admin123", new=NEW_PASSWORD).status_code)
+        events = self.events()
+        self.assertEqual(
+            [("PASSWORD", "SUCCESS", AUDIT_PASSWORD_CHANGED)],
+            [
+                (e["action"], e["status"], e["detail"])
+                for e in events
+                if e["action"] == "PASSWORD"
+            ],
+        )
+        self.assertNotIn(NEW_PASSWORD, json.dumps(events, ensure_ascii=False))
+        self.assertNotIn("admin123", json.dumps(events, ensure_ascii=False))
+
+
+class AdminResetTests(_ClientCase):
+    def _reset(self, username: str, headers: dict[str, str], *, new: str):
+        return self._post(f"/api/admin/users/{username}/password/reset", {"new_password": new}, headers)
+
+    def test_reset_requires_the_operate_capability(self):
+        viewer = self._headers("viewer", "viewer123")
+        response = self._reset("hr01", viewer, new=NEW_PASSWORD)
+        self.assertEqual(403, response.status_code, response.text)
+        self.assertIn("system:operate", response.json()["detail"])
+        self.assertEqual(1, user_store.get_record("hr01").credentials_version, "被拒的 reset 动了凭据")
+
+    def test_admin_reset_clears_a_stale_lock_in_the_same_transaction(self):
+        """SECA-12：reset 之后用户仍被旧 lock 挡住，是一条必被观测到的事故形态。"""
+        user_store.record_login_failure("hr01", max_attempts=1, lock_seconds=900)
+        self.assertIsNotNone(user_store.get_record("hr01").locked_until)
+        response = self._reset("hr01", self._admin_headers(), new=NEW_PASSWORD)
+        self.assertEqual(200, response.status_code, response.text)
+        record = user_store.get_record("hr01")
+        self.assertIsNone(record.locked_until)
+        self.assertEqual(0, record.failed_attempts)
+        self.assertTrue(record.must_change)
+        self.assertEqual(2, record.credentials_version)
+        login = self._login("hr01", NEW_PASSWORD)
+        self.assertEqual(200, login.status_code, login.text)
+        self.assertTrue(login.json()["password_change_required"])
+
+    def test_reset_forces_the_gate_while_a_self_change_clears_it(self):
+        """两个方向同场对照：管理员交出去的是"这口令不是你的"，自助交出去的是"改完了"。
+
+        把两处的 `must_change` 实参写成同一个值，本例的两格各红一次——这是这一版唯一一处
+        "同一个写路径、两种意图"的地方，所以判据必须成对出现在同一个用例里。
+        """
+        headers = self._admin_headers()
+        self.assertEqual(
+            200, self._reset("hr01", headers, new=NEW_PASSWORD).status_code
+        )
+        self.assertTrue(user_store.get_record("hr01").must_change, "reset 没置门")
+        login = self._login("hr01", NEW_PASSWORD).json()
+        self.assertTrue(login["password_change_required"])
+        changed = self.client.post(
+            "/api/auth/password/change",
+            json={"current_password": NEW_PASSWORD, "new_password": GOOD_PASSWORD},
+            headers=_bearer(login["access_token"]),
+        )
+        self.assertEqual(200, changed.status_code, changed.text)
+        self.assertFalse(user_store.get_record("hr01").must_change, "自助改密没关门")
+
+    def test_reset_never_echoes_the_password_and_404s_an_unknown_identity(self):
+        """404 留给已鉴权管理员的资源面：登录腿才是枚举面，这里不构成新的一条（§9.1 裁定）。"""
+        response = self._reset("ghost", self._admin_headers(), new=NEW_PASSWORD)
+        self.assertEqual(404, response.status_code, response.text)
+        self.assertEqual(COPY_NO_ACCOUNT, response.json()["detail"])
+        self.assertIsNone(user_store.get_record("ghost"))
+        ok = self._reset("hr01", self._admin_headers(), new=NEW_PASSWORD)
+        self.assertEqual({"reset", "must_change"}, set(ok.json()))
+        self.assertNotIn(NEW_PASSWORD, ok.text)
+        self.assertNotIn("$argon2", ok.text)
+
+    def test_reset_of_an_identity_without_a_row_creates_one_at_version_one(self):
+        """`provision_credentials` 是一条腿：无行新建、有行 bump，两个分支共用一个入口。"""
+        self.assertIsNone(user_store.get_record("sales01"))
+        response = self._reset("sales01", self._admin_headers(), new=NEW_PASSWORD)
+        self.assertEqual(200, response.status_code, response.text)
+        record = user_store.get_record("sales01")
+        self.assertEqual(1, record.credentials_version)
+        self.assertEqual(credentials.ALGORITHM_ARGON2ID, record.algorithm)
+        self.assertTrue(record.must_change)
+        login = self._login("sales01", NEW_PASSWORD)
+        self.assertTrue(login.json()["password_change_required"])
+
+    def test_reset_rejects_a_weak_new_password_before_touching_the_target(self):
+        response = self._reset("hr01", self._admin_headers(), new="abc")
+        self.assertEqual(422, response.status_code, response.text)
+        self.assertEqual(COPY_TOO_SHORT, response.json()["detail"])
+        self.assertEqual(1, user_store.get_record("hr01").credentials_version)
+
+
+class CliTests(_ClientCase):
+    def test_bootstrap_requires_a_preexisting_identity_and_never_creates_one(self):
+        """SEC-A-010：bootstrap 只写凭据，身份文件不因 CLI 而改变。"""
+        before = _identity_file_bytes()
+        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: NEW_PASSWORD}):
+            code, out, err = _run_cli(["credentials", "bootstrap-admin", "--username", "ghost"])
+        self.assertEqual(2, code, f"out={out!r} err={err!r}")
+        self.assertIsNone(user_store.get_record("ghost"))
+        self.assertEqual(before, _identity_file_bytes())
+        self.assertNotIn(NEW_PASSWORD, out + err)
+
+    def test_the_cli_never_accepts_a_password_on_argv(self):
+        """SECA-02：argv 会被 ps 与 shell history 观察到。"""
+        parser = cli.build_parser()
+        with self.assertRaises(SystemExit):
+            parser.parse_args(
+                ["credentials", "bootstrap-admin", "--username", "admin", "--password", "x"]
+            )
+        # 翻 `--help` 文本只会被措辞漂移骗过去，这里判的是 argparse 的**行为**：未定义选项即拒。
+        with self.assertRaises(SystemExit):
+            parser.parse_args(["credentials", "reset", "--username", "admin", "--pwd", "x"])
+        # 行为之外再钉一格结构：命名空间里连一个能装口令的槽位都不该有。`--password` 一旦
+        # 被加回来，这一格先红——它不依赖任何帮助文本的措辞。
+        args = parser.parse_args(["credentials", "reset", "--username", "admin"])
+        self.assertEqual("reset", args.action)
+        self.assertFalse(hasattr(args, "password"), "命名空间里多了一枚口令槽位")
+
+    def test_migration_status_reports_the_legacy_count(self):
+        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: NEW_PASSWORD}):
+            code, out, err = _run_cli(["credentials", "migration-status"])
+        self.assertEqual(0, code, f"out={out!r} err={err!r}")
+        self.assertIn("legacy_count=0", out)
+        self.assertIn("argon2id_count=3", out)
+        user_store.delete_record("sales01")
+        user_store.import_legacy_digest("sales01", LEGACY_ADMIN, must_change=True)
+        code, out, err = _run_cli(["credentials", "migration-status"])
+        self.assertEqual(0, code, f"out={out!r} err={err!r}")
+        self.assertIn("legacy_count=1", out)
+        self.assertIn("sales01", out)
+        self.assertNotIn(LEGACY_ADMIN, out, "digest 被打印出来了")
+
+    def test_bootstrap_writes_an_argon2_row_for_the_identity_that_has_none(self):
+        """新建分支：`sales01` 有身份无凭据行 ⇒ bootstrap 产出 v1 的 argon2id 行。"""
+        self.assertIsNone(user_store.get_record("sales01"))
+        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: NEW_PASSWORD}):
+            code, out, err = _run_cli(["credentials", "bootstrap-admin", "--username", "sales01"])
+        self.assertEqual(0, code, f"out={out!r} err={err!r}")
+        record = user_store.get_record("sales01")
+        self.assertEqual(credentials.ALGORITHM_ARGON2ID, record.algorithm)
+        self.assertEqual(1, record.credentials_version)
+        self.assertFalse(record.must_change, "bootstrap 造的是一个可用账号，不是待改密账号")
+        self.assertNotIn(NEW_PASSWORD, out + err)
+        self.assertNotIn("$argon2", out + err)
+
+    def test_cli_reset_clears_a_stale_lock_and_leaves_the_gate_open(self):
+        """SECA-12 的 CLI 半边：走的是同一条写路径，判据也必须在真进程面上重做一遍。"""
+        user_store.record_login_failure("hr01", max_attempts=1, lock_seconds=900)
+        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: NEW_PASSWORD}):
+            code, out, err = _run_cli(["credentials", "reset", "--username", "hr01"])
+        self.assertEqual(0, code, f"out={out!r} err={err!r}")
+        record = user_store.get_record("hr01")
+        self.assertIsNone(record.locked_until)
+        self.assertEqual(0, record.failed_attempts)
+        self.assertTrue(record.must_change)
+        self.assertEqual(2, record.credentials_version)
+        self.assertNotIn(NEW_PASSWORD, out + err)
+        login = self._login("hr01", NEW_PASSWORD)
+        self.assertEqual(200, login.status_code, login.text)
+        self.assertTrue(login.json()["password_change_required"])
+
+    def test_an_absent_or_too_short_env_password_is_refused_without_echoing_the_value(self):
+        """"env 没设" 与 "env 太短" 给同一句可执行提示，且两句里都没有口令本体。"""
+        with mock.patch.dict(os.environ):
+            os.environ.pop(cli.PASSWORD_ENV_VAR, None)
+            absent = _run_cli(["credentials", "bootstrap-admin", "--username", "admin"])
+        too_short = "abc"
+        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: too_short}):
+            short = _run_cli(["credentials", "bootstrap-admin", "--username", "admin"])
+        self.assertEqual(2, absent[0], absent)
+        self.assertEqual(2, short[0], short)
+        self.assertEqual(absent[2], short[2], "两种输入形状给了两句不同的话：运维读不出该做什么")
+        self.assertIn(cli.PASSWORD_ENV_VAR, absent[2])
+        self.assertNotIn(too_short, short[1] + short[2])
+        self.assertEqual(1, user_store.get_record("admin").credentials_version)
+
+    def test_the_cli_writes_the_enum_audit_token_and_no_password(self):
+        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: NEW_PASSWORD}):
+            self.assertEqual(0, _run_cli(["credentials", "bootstrap-admin", "--username", "admin"])[0])
+            # 用完即弹：这一格之后本进程的环境里不该再有那枚变量（后续 print、异常栈、
+            # 任何被 exec 的子进程都不该拿到它）。也正因为它被弹掉了，第二条命令必须重新给 env——
+            # 少给一次这里就红，"弹"这件事因此不是只写在注释里的承诺。
+            self.assertNotIn(cli.PASSWORD_ENV_VAR, os.environ, "口令还留在 environ 里")
+        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: NEW_PASSWORD}):
+            self.assertEqual(0, _run_cli(["credentials", "reset", "--username", "hr01"])[0])
+        events = self.events()
+        self.assertEqual(
+            [("PASSWORD", "SUCCESS", AUDIT_BOOTSTRAP), ("PASSWORD", "SUCCESS", AUDIT_RESET_BY_ADMIN)],
+            [(e["action"], e["status"], e["detail"]) for e in events if e["action"] == "PASSWORD"],
+        )
+        self.assertNotIn(NEW_PASSWORD, json.dumps(events, ensure_ascii=False))
+        self.assertEqual("ADMIN", [e["role"] for e in events if e["action"] == "PASSWORD"][0])
+
+    def test_the_cli_prints_nothing_that_claims_an_enable_or_disable_action(self):
+        """bootstrap 与 reset 都**不**碰 `enabled`：输出里出现"启用/停用"就是在暗示一件没做的事。"""
+        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: NEW_PASSWORD}):
+            code, out, err = _run_cli(["credentials", "reset", "--username", "hr01"])
+        self.assertEqual(0, code, f"out={out!r} err={err!r}")
+        for word in ("启用", "停用", "enabled"):
+            self.assertNotIn(word, out + err)
+
+
 if __name__ == "__main__":
     unittest.main()

## new CLI (full)
     1	"""凭据运维面（规格 §8.6 / §8.7）。口令只从环境变量读，绝不进 argv。
     2	
     3	argv 是**可观察**的：`ps`、shell history、CI 的日志抓取都会把口令抄走，所以这里没有
     4	`--password` 这一项，也不接受任何位置参数形式的口令。判据在契约用例里是按 argparse 的
     5	**行为**钉的（未定义选项 ⇒ `SystemExit`），不是翻 `--help` 文本——文本会随措辞漂移。
     6	
     7	`must_change` 由动作决定，而不是由写路径决定：`bootstrap-admin` 造的是"这个账号从此能登录"
     8	（门关上），`reset` 造的是"这口令不是你选的"（门开着）。两个动作走的是 `auth.provision_credentials`
     9	同一条写路径，因此清锁与版本 bump 不可能只在其中一支发生（SECA-12 / §7.5）。
    10	
    11	本模块**不**创建、**不**修改、也**不**启用或停用任何身份：身份的唯一真源是配置文件
    12	（SEC-A-010），CLI 顺手建号会造出第二个真源，而"停用一个账号"这件事在这里根本没有对应动作。
    13	"""
    14	
    15	from __future__ import annotations
    16	
    17	import argparse
    18	import os
    19	import sys
    20	
    21	from app import auth, credentials, credentials_migration, directory, user_store
    22	from app.audit import record_event
    23	from app.user_store import CredentialStoreError
    24	
    25	#: 口令的唯一来路。名字是运维接口的一部分（部署文档与 `.env` 模板都写它）。
    26	PASSWORD_ENV_VAR = "CREDENTIALS_PASSWORD"
    27	
    28	#: 动作 → 落库后的 `must_change`。缺这一格的动作在下面就被 argparse 拒了。
    29	_MUST_CHANGE_BY_ACTION = {"bootstrap-admin": False, "reset": True}
    30	
    31	_COPY_NO_ENV_PASSWORD = (
    32	    f"{PASSWORD_ENV_VAR} 未设置或不足 12 字符：口令只能放在这个环境变量里，"
    33	    "不接受任何命令行参数形式"
    34	)
    35	
    36	
    37	def build_parser() -> argparse.ArgumentParser:
    38	    parser = argparse.ArgumentParser(
    39	        prog="python -m app.cli", description="凭据运维面（口令只从环境变量读）"
    40	    )
    41	    commands = parser.add_subparsers(dest="command", required=True)
    42	    actions = commands.add_parser("credentials").add_subparsers(
    43	        dest="action", required=True
    44	    )
    45	    bootstrap = actions.add_parser(
    46	        "bootstrap-admin", help="为**已存在的**身份写入 argon2id 凭据"
    47	    )
    48	    bootstrap.add_argument("--username", required=True)
    49	    reset = actions.add_parser("reset", help="重置口令并强制下次登录改密")
    50	    reset.add_argument("--username", required=True)
    51	    actions.add_parser("migration-status", help="打印各算法行数与逐账号状态")
    52	    return parser
    53	
    54	
    55	def _password_from_env() -> str | None:
    56	    """读出口令；缺失或不足下界时返回 None，由调用方给出**同一句**提示。
    57	
    58	    两条输入形状（没设 / 太短）必须汇成一句可执行的话：分成两句就会有一句在讲"你给的
    59	    值太短"——那等于把值本身的存在性说出去了。这里任何分支都不打印取值。
    60	    """
    61	    value = os.environ.get(PASSWORD_ENV_VAR)
    62	    if value is None or len(value) < auth._MIN_PASSWORD_LENGTH:
    63	        return None
    64	    return value
    65	
    66	
    67	def _print_status() -> int:
    68	    status = credentials_migration.status()
    69	    print(f"legacy_count={status.legacy_count} argon2id_count={status.argon2id_count}")
    70	    for row in status.accounts:
    71	        print(
    72	            f"{row.username}\t{row.algorithm}\tv{row.credentials_version}"
    73	            f"\tmust_change={int(row.must_change)}\tlocked={row.locked_until or '-'}"
    74	        )
    75	    return 0
    76	
    77	
    78	def main(argv: list[str] | None = None) -> int:
    79	    args = build_parser().parse_args(argv)
    80	    # 建表是 `credentials_migration` 的调用方前置条件（它的读路径不建表），放在这里
    81	    # 而不是各动作内部：`migration-status` 与两条写腿都要过这一道。
    82	    user_store.ensure_user_credentials_schema()
    83	    if args.action == "migration-status":
    84	        return _print_status()
    85	
    86	    identity = directory.get_identity(args.username)
    87	    if identity is None:
    88	        print(f"身份不存在：{args.username}（请先写入 config/users.json）", file=sys.stderr)
    89	        return 2
    90	    password = _password_from_env()
    91	    if password is None:
    92	        print(_COPY_NO_ENV_PASSWORD, file=sys.stderr)
    93	        return 2
    94	    reason = auth.validate_new_password(args.username, password)
    95	    if reason:
    96	        print(reason, file=sys.stderr)
    97	        return 2
    98	
    99	    must_change = _MUST_CHANGE_BY_ACTION[args.action]
   100	    try:
   101	        version = auth.provision_credentials(
   102	            args.username, plain_password=password, must_change=must_change
   103	        )
   104	    except CredentialStoreError as exc:
   105	        # 固定文案、零口令：`user_store` 的异常消息本身就不带凭据材料，原样转出去即可。
   106	        print(str(exc), file=sys.stderr)
   107	        return 1
   108	    finally:
   109	        # 用完立刻从本进程的环境里抹掉：后面任何一次 print、异常或子进程继承都不该再拿到它。
   110	        os.environ.pop(PASSWORD_ENV_VAR, None)
   111	
   112	    record_event(
   113	        username=args.username,
   114	        role=identity.role,
   115	        action="PASSWORD",
   116	        status="SUCCESS",
   117	        detail="credential_bootstrap" if args.action == "bootstrap-admin" else "password_reset_by_admin",
   118	    )
   119	    print(
   120	        f"{args.username}: algorithm={credentials.ALGORITHM_ARGON2ID}"
   121	        f" version={version} must_change={int(must_change)}"
   122	    )
   123	    return 0
   124	
   125	
   126	if __name__ == "__main__":
   127	    raise SystemExit(main())


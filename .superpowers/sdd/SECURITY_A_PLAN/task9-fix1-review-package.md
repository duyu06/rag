# Task 9 fix round 1 — review package (no-commit tree; snapshot diff)

Base: snap-task9-fix-pre-app + snap-task9-fix-pre-test_secret_hygiene_contract.py (the head round-1 review saw)
Head: current worktree

## backend/app (excluding __pycache__)
diff -ruN '--exclude=__pycache__' .superpowers/sdd/SECURITY_A_PLAN/snap-task9-fix-pre-app/conversation_agent.py backend/app/conversation_agent.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task9-fix-pre-app/conversation_agent.py	2026-09-26 13:47:47.887444700 +0800
+++ backend/app/conversation_agent.py	2026-09-26 14:16:24.319675300 +0800
@@ -475,8 +475,9 @@
     # detail——现成的字符串例子是 `fusion`（`str(data.get("fusion") or "rrf")`），而 detail 顺着
     # trace 与 SSE 一路到前端 TraceView；判定层的四枚子观测（触发/缓存/熔断/跳过）在这条路上
     # 同样是**未过白名单的原始值**，这也是本地快路径仍能在重排行里显示它们的原因。
-    # 唯一的兜底是 `save_trace`/`get_trace` 的 `redact_secrets()`，它按"密钥形态"（apikey_、
-    # Bearer）脱敏，挡不住"看着不像密钥"的内部字符串。
+    # 唯一的兜底是 `save_trace`/`get_trace` 的 `redact_for_persistence()`（形态脱敏 + 精确键名
+    # 黑名单），它按"密钥形态"（apikey_、Bearer）与敏感**键名**抹，挡不住"看着不像密钥、键名也
+    # 不像密钥"的内部字符串。
     # ⇒ 检索层给 breakdown 新增**字符串型键**时：先过 `public_timings()` 的白名单口径
     #   （`PUBLIC_TIMING_KEYS` 逐条枚举）再进这里，或让它只进 `timings`。
     stage_timings = dict(retrieval_breakdown or {})
diff -ruN '--exclude=__pycache__' .superpowers/sdd/SECURITY_A_PLAN/snap-task9-fix-pre-app/main.py backend/app/main.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task9-fix-pre-app/main.py	2026-09-26 13:47:47.883448100 +0800
+++ backend/app/main.py	2026-09-26 15:49:36.625226000 +0800
@@ -399,7 +399,11 @@
     if result.user is None:
         # 四种失败态（含锁定期）到这里已经塌成同一条 401 + 同一段中文，与登录面一字不差；
         # 区别只在审计 token，而那个只进审计面。
-        record_login_event(username=user.username, detail=result.audit_detail)
+        # 事件归属由路由决定：改密腿上的**每一格**拒绝都记 PASSWORD（与上面 429/503 同属一条腿），
+        # 只有 `/api/auth/login` 的拒绝才记 LOGIN。混着记的话，运维面就再也分不出"爆破改密接口"
+        # 与"爆破登录接口"——判定与计数器共用，事件归属却严格按路由分。
+        record_login_event(username=user.username, detail=result.audit_detail,
+                           action="PASSWORD")
         raise HTTPException(status_code=401, detail="用户名或密码错误")
     try:
         provision_credentials(
## backend/tests/test_secret_hygiene_contract.py
--- .superpowers/sdd/SECURITY_A_PLAN/snap-task9-fix-pre-test_secret_hygiene_contract.py	2026-09-26 13:47:48.071481800 +0800
+++ backend/tests/test_secret_hygiene_contract.py	2026-09-26 16:02:40.887415100 +0800
@@ -9,24 +9,33 @@
 2. **响应面 / 落盘面那条边界要用真实登录证**：同一枚 access_token，登录响应里必须是**能用**的
    （客户端就靠它），落进遥测持久化面则必须被抹成占位符。一个"过宽的红actor"只有这条路能抓到。
 3. **三守卫同生同死（§8.5 / SECA-18）**：直接调用 `evaluate_startup_guards`，不借 lifespan。
-   外加启动守卫真实生效（真跑一遍 `assert_startup_safe`）与 root_path 下的无回显守卫（Task 7 移交的 P0）。
-
-扫描门（SECA-20）用一条普通 pytest 用例跑遍 tracked 文件，豁免表 == 命中表（`test_llm_egress_guard.py`
-同族做法）。口令变量 `CREDENTIALS_PASSWORD` 不得出现在 `.env.example`（SEC-A-002 配置半边）。
+   另有一条**走真实 lifespan** 的钉子（`with TestClient(app)` 起一次进程）：`main.py` 里那句
+   `assert_startup_safe()` 是全仓唯一的执行点，而 `TestClient(app)` 不进上下文管理器就不会跑
+   lifespan——只钉函数本身时，把那一行删掉整套件照样绿。外加 root_path 下的无回显守卫（Task 7 移交的 P0）。
+4. **审计事件归属由路由决定**：`/api/auth/login` 的拒绝记 `LOGIN`，`/api/auth/password/change`
+   的**每一格**拒绝都记 `PASSWORD`。判据逐腿打真路由，不打 helper。
+
+扫描门（SECA-20）用一条普通 pytest 用例跑遍交付面（tracked ∪ 未忽略的 untracked），豁免表与命中表
+按 **(文件, 处数)** 互等（`test_llm_egress_guard.py` 同族做法）——键不是行号。口令变量
+`CREDENTIALS_PASSWORD` 不得出现在 `.env.example`（SEC-A-002 配置半边）。
 """
 
 from __future__ import annotations
 
+import ast
 import asyncio
 import json
 import re
 import subprocess
 import sys
+import threading
 import unittest
-from pathlib import Path
+from collections.abc import Iterable, Mapping
+from pathlib import Path, PurePosixPath
 from unittest import mock
 
 BACKEND_DIR = Path(__file__).resolve().parents[1]
+REPO_ROOT = BACKEND_DIR.parent
 TESTS_DIR = BACKEND_DIR / "tests"
 for _entry in (str(BACKEND_DIR), str(TESTS_DIR)):
     if _entry not in sys.path:
@@ -34,7 +43,7 @@
 
 import pytest  # noqa: E402
 
-from app import agent_trace, audit, security, security_startup  # noqa: E402
+from app import agent_trace, audit, credentials, security, security_startup  # noqa: E402
 from app.credentials import PasswordCapacityError  # noqa: E402
 
 # --------------------------------------------------------------------------- #
@@ -47,6 +56,33 @@
     "authorization", "api_key", "app_secret", "tenant_access_token",
 )
 
+#: 黑名单的**内容**本身就是契约，所以要逐枚点名，而不是"遍历它自己"：只遍历表的用例对
+#: 删表里的任何一枚都无感（表少一枚，循环跟着少一圈，照样绿）。`current_password` /
+#: `new_password`（改密两条腿的入参键）、`secret` / `credentials`（泛键）都在这一格里。
+EXPECTED_PERSISTENCE_DENY_SET = frozenset({
+    "password", "password_hash", "plaintext_password", "current_password", "new_password",
+    "access_token", "refresh_token", "authorization", "api_key", "app_secret",
+    "tenant_access_token", "secret", "credentials",
+})
+
+
+def test_the_persistence_deny_set_is_exactly_the_intended_key_set():
+    """删一枚、加一枚都红：等式两边是**清单**，不是自指遍历。"""
+    assert EXPECTED_PERSISTENCE_DENY_SET == security.PERSISTENCE_SENSITIVE_KEYS
+
+
+def test_the_persistence_deny_set_matches_case_insensitively():
+    """判定读的是 `str(key).lower()`（`security.py` 里那一格）⇒ 大小写写法一律同判。
+
+    反向也要有脸：观测键无论怎么写都不在黑名单里（`INPUT_TOKENS` 不许因为"整词等值"的
+    大小写变体被抹），否则这条等值判定就退化成了又一次子串匹配。
+    """
+    for key in ("PASSWORD", "Current_Password", "ACCESS_TOKEN", "Api_Key", "SECRET", "Credentials"):
+        assert security.redact_for_persistence({key: "v"})[key] == security.REDACTED, key
+    for key in NOT_SECRETS:
+        upper = {key.upper(): 1}
+        assert security.redact_for_persistence(upper) == upper, key
+
 
 def test_persistence_redaction_kills_sensitive_keys_by_exact_name():
     payload = {key: "sensitive-value" for key in SECRETS}
@@ -68,6 +104,10 @@
     """
     payload = {"input_tokens": 12, "output_tokens": 34, "num_sources": 5,
                "total_tokens": 46, "token_type": "bearer"}
+    # 清单与用例指的是同一张表，且这张表与黑名单**互不相交**：相交就意味着"观测键被列进了
+    # 敏感键"，那正是 M8 反方向的形状。
+    assert set(payload) == set(NOT_SECRETS)
+    assert not set(NOT_SECRETS) & security.PERSISTENCE_SENSITIVE_KEYS
     assert payload == security.redact_for_persistence(payload)
 
 
@@ -126,13 +166,48 @@
     assert "app.security" not in source
 
 
+def _app_python_files(*, exclude_definition: bool = False) -> tuple[str, ...]:
+    """`app/**/*.py` 相对 `app/` 的路径（结构钉的读法口径，与扫描门的键同形）。"""
+    return tuple(sorted(
+        str(path.relative_to(BACKEND_DIR / "app"))
+        for path in (BACKEND_DIR / "app").rglob("*.py")
+        if not (exclude_definition and path.name == "security.py")))
+
+
+def _call_sites(name: str, *, files: Iterable[str] | None = None) -> int:
+    """数**真调用**（AST）：`count("redact_for_persistence")` 会把 import 行与 docstring 里的
+    名字一起算进来，那种数法对"多 import 一次"或"注释里提一句"都过敏，而对"把调用挪进
+    f-string"完全无感。判据只能是语法树上的 Call 节点。"""
+    total = 0
+    for relative in (files if files is not None else _app_python_files()):
+        source = (BACKEND_DIR / "app" / relative).read_text(encoding="utf-8")
+        for node in ast.walk(ast.parse(source)):
+            if isinstance(node, ast.Call):
+                func = node.func
+                called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
+                total += called == name
+    return total
+
+
 def test_the_four_persistence_faces_use_the_persistence_redactor():
-    """切换点钉死：只有 audit（写+读）与 agent_trace（存+取）这四张落盘面换了 redactor；
-    其余 24 处（含 8 处响应面 return）仍叫 redact_secrets。"""
-    audit_src = (BACKEND_DIR / "app" / "audit.py").read_text(encoding="utf-8")
-    trace_src = (BACKEND_DIR / "app" / "agent_trace.py").read_text(encoding="utf-8")
-    assert "redact_secrets" not in audit_src and audit_src.count("redact_for_persistence") >= 2
-    assert "redact_secrets" not in trace_src and trace_src.count("redact_for_persistence") >= 2
+    """切换点钉死：只有 audit（写+读）与 agent_trace（存+取）这四张落盘面换了 redactor，
+    每张面**恰好两处**调用；其余落点一概仍叫 `redact_secrets`。
+
+    等式而不是 `>= 2`：写面或读面任何一张被换回去 ⇒ 1 ≠ 2 红；多出一张（有人把 redactor 罩到
+    别的面上，M9 的形状）⇒ 同样红。响应面那侧给的是同一把尺子的总数钉，它保证"有人把某张
+    响应面偷偷换成落盘面"不会被这张表的等式放过去。
+    """
+    for module in ("audit.py", "agent_trace.py"):
+        source = (BACKEND_DIR / "app" / module).read_text(encoding="utf-8")
+        assert "redact_secrets" not in source, module
+        assert 2 == _call_sites("redact_for_persistence", files=(module,)), module
+    # `security.py` 是两枚 redactor 的定义所在，它内部的自递归调用不属于任何作用盘面。
+    faces = _app_python_files(exclude_definition=True)
+    # 落盘面总共就这四处（audit 2 + agent_trace 2）；多一处 = 有人扩大了切换面。
+    assert 4 == _call_sites("redact_for_persistence", files=faces)
+    # 响应面：app/ 里 17 处调用一处都不许被换成落盘面 redactor（换一枚登录响应的 access_token
+    # 就会被抹掉，客户端当场拿不到票）。
+    assert 17 == _call_sites("redact_secrets", files=faces)
 
 
 # --------------------------------------------------------------------------- #
@@ -185,6 +260,70 @@
         security_startup.assert_startup_safe()  # 不抛
 
 
+class StartupGuardLifespanTests(unittest.TestCase):
+    """守卫的**唯一执行点**是 `main.py` lifespan 里那一句 `assert_startup_safe()`。
+
+    上面那些直接调用守卫函数的钉子（SECA-18 要求的正是"不依赖 lifespan"）杀不掉"执行点被删"
+    这一档：`TestClient(app)` 不进上下文管理器根本不跑 lifespan，于是删掉那一行、函数与全部
+    调用者测试都还绿。这里补的正是那一格——真起一次进程。
+
+    同一条 lifespan 里另外两步（identity / llm router 的 warmup）被换成 no-op：它们各有自己的
+    契约与 cwd 假设（`warmup_llm_router` 默认开启且按 **当前目录**解析 `config/llm_registry.json`），
+    本类的主题只有守卫那一句。打点的位置是 `app.main` 里那两个名字——lifespan 读的就是它们。
+    """
+
+    def _client(self):
+        from fastapi.testclient import TestClient
+
+        from app.main import app as fastapi_app
+
+        return TestClient(fastapi_app)
+
+    def _guard_only(self):
+        return (mock.patch("app.main.warmup_identity_permissions"),
+                mock.patch("app.main.warmup_llm_router"))
+
+    def _patched(self, **kwargs):
+        from app.config import Settings
+
+        return mock.patch("app.config.settings", Settings(**kwargs))
+
+    def test_enterprise_default_secret_refuses_during_real_startup(self):
+        """企业形态 + 出厂默认 secret ⇒ 起进程就抛（fail-fast，不是第一个请求才炸）。
+
+        三件守卫里这两格同时违规，正是 §8.5 "同生同死"在**执行点**上的形状：如果 lifespan
+        里那句守卫被删/被包进 try 里静音，这一条就是唯一会红的地方。
+        """
+        first, second = self._guard_only()
+        with first, second, self._patched(security_enterprise_mode=True,
+                                          jwt_secret=security_startup.DEFAULT_JWT_SECRET,
+                                          cors_allow_origins=""):
+            with pytest.raises(security_startup.SecurityStartupError):
+                with self._client():
+                    pass  # pragma: no cover —— 到不了这里
+
+    def test_dev_default_starts_clean_with_the_guard_in_place(self):
+        """dev / 测试形态（默认）⇒ 同一条 lifespan 干净启动：守卫在场但不是障碍。
+
+        只钉"企业形态会抛"是不够的：把 `assert_startup_safe()` 换成一句无条件抛的桩，上面
+        那条照样绿。这一条把"默认配置零额外启动行为"钉到**真实启动路径**上。
+        """
+        first, second = self._guard_only()
+        with first, second, self._patched(security_enterprise_mode=False,
+                                          jwt_secret=security_startup.DEFAULT_JWT_SECRET,
+                                          cors_allow_origins=""):
+            with self._client() as client:
+                assert 401 == client.get("/api/auth/me").status_code
+
+    def test_enterprise_fully_configured_starts_clean(self):
+        """企业形态 + ≥32 非默认 secret + 显式 CORS ⇒ 起得来（三守卫都不是"永远拒"）。"""
+        first, second = self._guard_only()
+        with first, second, self._patched(security_enterprise_mode=True, jwt_secret="x" * 48,
+                                          cors_allow_origins="https://kb.example"):
+            with self._client() as client:
+                assert 401 == client.get("/api/auth/me").status_code
+
+
 # --------------------------------------------------------------------------- #
 # §10 / SEC-A-002 配置半边：.env.example 键集合
 # --------------------------------------------------------------------------- #
@@ -204,66 +343,284 @@
 
 
 # --------------------------------------------------------------------------- #
-# SECA-20：仓库扫描门（豁免表 == 命中表，与 test_llm_egress_guard.py 同族）
+# SECA-20：仓库扫描门（豁免表与命中表按 (文件, 处数) 互等，同 test_llm_egress_guard.py）
 # --------------------------------------------------------------------------- #
 
-CREDENTIAL_PATTERN = re.compile(
-    r"(?i)\b(?:api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{16,}"
+#: 凭据材料的 native 语法有两种，各开一枚面，谁也替代不了谁。
+#:
+#: **字面量面**（代码 / 配置 / 前端）：键名词干（`api_key` / `secret` / `token` / `password` /
+#: `passwd`，允许 `JWT_SECRET`、`tenant_access_token` 这类前后缀）+ `:` 或 `=` + **成对引号包住、
+#: 内部无空白**的 ≥16 字符串。三处细节都是刻意的：
+#: ① 键名**不再要求词首 `\b`**——`_` 是词字符，`\bsecret` 在 `JWT_SECRET=` 上永远匹配不到，
+#:    那等于把整类 env 形状的泄漏做成隐形（旧门的全部问题都在这里）；
+#: ② 值必须是**字面量**：`password = _password_from_env` 取的是变量/调用而不是材料，散文里引用
+#:    这条语句也不构成凭据；
+#: ③ 注解写法（`jwt_secret: str = "…"`）同样在面上，否则配置默认值那一格就是盲区。
+#:
+#: **env 面**（`.env*` / compose / `scripts/`）：这三处的 native 语法是**不带引号**的 `KEY=value`，
+#: 字面量面在结构上抓不到它 ⇒ 另开一条无引号面（值仍要 ≥16 且无空白）。范围收在这三处，是因为
+#: 不做范围限定的"大写名=value"在代码与正则会撞出遍地噪声。
+#:
+#: **材料形状面**：不依赖任何赋值形态的现网密钥形状（`sk-…` / `ghp_…` / `AKIA…` / `eyJ…` /
+#: 私钥 PEM 头）——"贴进代码的一段裸密钥"（没有 `key =` 外壳）也红。
+#:
+#: **范围决策（两档，不是 15 条豁免）。**
+#: - `*.md`（交付文档：`docs/**` 与 README）只上**材料形状面**。散文按定义就要引用代码与测试夹具
+#:   的字面量（单是 `docs/SECURITY_A_PLAN.md` 就有 32 处合法引用），逐条进豁免表等于把门换成一张
+#:   永远补不完的清单，所以赋值形态那两枚面在散文里不作数；但"贴进文档的一段现网密钥"（`sk-…` /
+#:   `eyJ…` / PEM 头）照样红。实测交付文档在这一枚上今天 **0 命中** ⇒ 这一档不收豁免、不给未来留
+#:   漂移债，只把"真凭据只出现在 markdown 里"那条残余风险关掉。
+#: - `.superpowers/**`（SDD 过程件：plan / report / 历轮 baseline 快照）整目录不在面上。理由更强
+#:   一档：那里躺着**故意**写下的 canary 字面量（`sk-CANARY-<16位哈希>-not-in-any-message`），还有被
+#:   逐字复制进来的 `app/` 源码副本（同一枚已豁免材料会再出现一遍）；它是过程**证据**，按
+#:   `.gitignore` 的口径默认不入库、只在终审时精选 `-f`。把豁免表绑在这种目录上更糟：下一轮快照
+#:   一入库门就红，而那次红与"有没有真凭据"毫无关系。
+#: 命名的残余风险：只在过程件里出现的凭据材料本门够不到——那是 §18 已登记的第三方扫描器
+#: （gitleaks，带 git 历史）后续项的职责，SEC-A 明确不引入第三方扫描器、不新增 security job。
+_UNSCANNED_PREFIXES = (".superpowers/",)
+_LITERAL_FACE = re.compile(
+    r"""
+    ["']?
+    (?:api[_-]?key|secret|token|pass(?:word|wd))
+    [\w-]*
+    ["']?
+    (?:\s*:\s*[A-Za-z0-9_\[\], .|]*)?
+    \s*[:=]\s*
+    (?P<quote>["'])
+    [^"'\\ \t]{16,}
+    (?P=quote)
+    """,
+    re.X | re.I,
+)
+_ENV_FACE = re.compile(
+    r"""
+    [A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_KEY|APIKEY)[A-Z0-9_]*
+    [ \t]*[:=][ \t]*
+    ["']?[A-Za-z0-9_.\-/+~]{16,}
+    """,
+    re.X,
 )
+_MATERIAL_FACE = re.compile(
+    r"sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{12,}"
+    r"|eyJ[A-Za-z0-9_\-]{16,}|BEGIN [A-Z ]*PRIVATE KEY"
+)
+_ALL_FACES = (_LITERAL_FACE, _ENV_FACE, _MATERIAL_FACE)
+_CODE_FACES = (_LITERAL_FACE, _MATERIAL_FACE)
+_BINARY_SUFFIXES = {".png", ".webp", ".ico", ".woff", ".woff2", ".pyc"}
 
-# 豁免表逐项写成"文件:行 + 为什么它不是凭据"，且必须与命中集相等——只增不减的豁免表等于没
-# 有豁免表（M：命中表漂了豁免表不跟着动，下一次就漏）。这三枚都是测试内的假值，逐条点名。
-EXEMPT_HITS: frozenset[str] = frozenset({
-    # 测试内构造的假 feishu app-secret 声明值，只为占位一个 claim 面，不是任何真凭据。
-    "backend/tests/test_feishu_identity_contract.py:1856",
-    # 断言"这枚 typesafe key 绝不能被流出去"的字面量，是测试自己的诱饵值。
-    "backend/tests/test_typesafe_api_runtime.py:126",
-    # 同上：判定层"绝 persisted"的诱饵 key，测试用假值。
-    "backend/tests/test_typesafe_judgments.py:216",
-})
+#: 豁免表的键是 **(相对路径 → (命中处数, 为什么它不是凭据材料))**，不是 `文件:行号`。
+#: 行号会洗白这道门：①已经豁免的那一行上再放第二枚真凭据 = 同一个键 = 静音；②行号在上方
+#: 任何一次编辑后整体漂移，表跟着漂就等于门废了。处数是**计数**，多一枚必红、少一枚（死行）也红
+#: ——与 `test_llm_egress_guard.py` 的 `EXEMPTIONS` 同一形状。
+#: 每一行的"为什么"必须落到**这一处材料本身**（出厂默认 / 审计枚举 token / env 变量名 / 测试诱饵 /
+#: localStorage 键名 / 本地脚本自用的一次性夹具），只写"这是测试文件"的那张表就是洗白过的门。
+EXEMPTIONS: dict[str, tuple[int, str]] = {
+    # 出厂默认占位符：值就是 `security_startup.DEFAULT_JWT_SECRET` 那一枚，企业形态下启动守卫
+    # 正因为"等于它"才拒启动（§10 明写默认值要留在模板里）。真凭据不许出现在这一格。
+    "backend/.env.example": (1, "JWT_SECRET 的出厂默认占位符，与守卫用来识别「忘了改」的那枚常量同源"),
+    # §9.1 审计面的枚举 token（`password_capacity` / `password_policy_rejected`）：那是给机器读的
+    # 状态名，值本身不对应任何密钥材料。
+    "backend/app/auth.py": (2, "审计 detail 的枚举 token 常量，展示面另有中文文案（§9.1 两栏）"),
+    # CLI 读的**变量名**（`CREDENTIALS_PASSWORD`）：值是指针，明文口令由运维在一次性调用时注入。
+    "backend/app/cli.py": (1, "一次性 CLI 的 env 变量名字面量，不是口令值（SEC-A-002）"),
+    # 同 `.env.example`：守卫识别"默认没换"的比对基准，抄错一位就会把生产误判成安全。
+    "backend/app/config.py": (1, "Settings.jwt_secret 的出厂默认值，与启动守卫的比对基准同源"),
+    "backend/app/security_startup.py": (1, "DEFAULT_JWT_SECRET 常量本体，三守卫靠它识别「忘了改」"),
+    # 以下三枚是同族：SEC-A 契约用例各配一枚 ≥32 字节的假 JWT secret，理由见 `sec_a_fixtures`
+    # 的 `LongJwtSecretMixin`——换掉它会把套件警告计数挪走。值不指向任何环境，签名验不过。
+    "backend/tests/test_authentication_leg_contract.py": (
+        1, "测试自带的假 JWT secret 夹具（只为躲过 PyJWT 短密钥警告），不指向任何环境"),
+    "backend/tests/test_feishu_identity_contract.py": (
+        1, "测试内构造的假 feishu app-secret 声明值，只为占位一个 claim 面"),
+    "backend/tests/test_password_lifecycle_contract.py": (
+        2, "假 JWT secret 夹具 + 一枚审计枚举 token（`password_changed`），都不是凭据材料"),
+    # V2.3 出口守卫的诱饵面：D6 要证明"provider 之外的 key 绝不出网"，手里就得有可识别的 key 值。
+    # 计数 10 覆盖 `sk-*` canary 与 `api_key="…"` 诱饵两种形态；多一枚就得重新过评审。
+    "backend/tests/test_model_router_v23_contract.py": (
+        10, "出口/路由契约的诱饵 key 与 canary 字面量，断言的正是它们绝不外发、绝不落盘"),
+    "backend/tests/test_typesafe_api_runtime.py": (
+        1, "断言「这枚 key 绝不能被流出去」的诱饵值，是测试自己的诱饵"),
+    "backend/tests/test_typesafe_judgments.py": (
+        1, "判定层「绝 persisted」的诱饵 key，测试用假值"),
+    # 本文件：两枚"响应面 vs 落盘面"的字面量样本 + 两枚假 JWT 头（无签名段，验不过）。
+    # 扫描门自己的正/反例夹具按拼接构造，因此不在此表内计数。
+    "backend/tests/test_secret_hygiene_contract.py": (
+        4, "两域对比的字面量样本与两枚假 JWT 头（`eyJ…` 无签名段），全为构造值"),
+    # 前端存的是 localStorage 的**键名**（票值运行时才存在）：两处同一个键名常量。
+    "frontend/src/lib/api.ts": (1, "localStorage 键名字面量，值是运行时才签发的 token"),
+    "frontend/src/lib/conversations.ts": (1, "同上：会话面复用同一枚 localStorage 键名"),
+    # 本地集成脚本：服务由脚本自己起、口令由脚本自己写死，任何环境都不复用这一枚。
+    "scripts/conversation_p1_integration.py": (
+        1, "本地一次性集成夹具的假 secret（脚本自己起的服务），不被任何环境复用"),
+    # deploy.ps1 要检测"`.env` 里仍是出厂默认"才生成随机值，两处（匹配 + 替换模式）都必须逐字
+    # 引用那一枚默认值；替换写进去的是随机数，不是这里的字面量。
+    "scripts/deploy.ps1": (2, "检测/替换出厂默认 JWT_SECRET 的正则字面量，与守卫比对基准同源"),
+}
 
-_BINARY_SUFFIXES = {".png", ".webp", ".ico", ".woff", ".woff2", ".pyc"}
 
+def _faces_for(relative: str) -> tuple[re.Pattern[str], ...]:
+    """每类文件上哪几枚面。
 
-def _scan_sites() -> list[tuple[str, str]]:
-    """遍历 tracked 文件，返回 `[(相对路径:行, 命中片段)]`。扫描逻辑只有这一份实现。"""
-    listing = subprocess.run(
-        ["git", "ls-files", "-z"], cwd=BACKEND_DIR.parent, capture_output=True, check=True
-    )
-    found: list[tuple[str, str]] = []
-    for raw in listing.stdout.split(b"\0"):
-        if not raw:
-            continue
-        relative = raw.decode("utf-8", "replace")
-        path = BACKEND_DIR.parent / relative
-        if not path.is_file() or path.suffix in _BINARY_SUFFIXES:
+    markdown 只上材料形状面（散文里的 `KEY=value` 是引用不是材料）；`.env*`、compose、`scripts/`
+    三处 native 语法真是 `KEY=value`，所以上全三枚；其余（代码 / 配置 / 前端）上字面量 + 材料两枚。
+    """
+    name = PurePosixPath(relative).name.lower()
+    if relative.endswith(".md"):
+        return (_MATERIAL_FACE,)
+    if name.startswith(".env") or relative.startswith("scripts/") or "compose" in name:
+        return _ALL_FACES
+    return _CODE_FACES
+
+
+def _occurrence_lines(text: str, *, relative: str) -> list[int]:
+    """去重叠后的命中行号（行号只给人读，不进豁免键）。
+
+    同一枚泄漏被两枚面各抓一次 ⇒ 区间重叠 ⇒ 合并成**一处**，所以"处数"数的是泄漏而不是正则
+    匹配次数；同一行上的两处不重叠泄漏 ⇒ 两处，豁免表就会因为多一枚而红。
+    """
+    spans: list[list[int]] = []
+    for face in _faces_for(relative):
+        spans += [[match.start(), match.end()] for match in face.finditer(text)]
+    spans.sort()
+    merged: list[list[int]] = []
+    for start, end in spans:
+        if merged and start < merged[-1][1]:
+            merged[-1][1] = max(merged[-1][1], end)
+        else:
+            merged.append([start, end])
+    return [text[:start].count("\n") + 1 for start, _end in merged]
+
+
+def _in_scan_scope(relative: str) -> bool:
+    """范围决策落地的地方：只有 SDD 过程件整目录不在面上（markdown 仍上材料形状面，见上面那段）。"""
+    return not relative.startswith(_UNSCANNED_PREFIXES)
+
+
+def _hit_counts(names: Iterable[str], *, root: Path = REPO_ROOT) -> dict[str, int]:
+    """文件集（相对 `root` 的 posix 路径）→ 命中处数。扫描逻辑只有这一份实现。"""
+    counts: dict[str, int] = {}
+    for relative in names:
+        path = root / relative
+        if (not _in_scan_scope(relative) or not path.is_file()
+                or path.suffix in _BINARY_SUFFIXES):
             continue
-        text = path.read_text(encoding="utf-8", errors="ignore")
-        for match in CREDENTIAL_PATTERN.finditer(text):
-            site = f"{relative}:{text[:match.start()].count(chr(10)) + 1}"
-            found.append((site, match.group(0)[:24]))
-    return found
+        found = len(_occurrence_lines(path.read_text(encoding="utf-8", errors="ignore"),
+                                      relative=relative))
+        if found:
+            counts[relative] = found
+    return counts
 
 
-def _scan_hits() -> set[str]:
-    return {site for site, _snippet in _scan_sites()}
+def _delivery_surface_names(*, root: Path = REPO_ROOT) -> list[str]:
+    """扫描面 = 会进仓库的那一面：tracked（`--cached`）∪ 未被忽略的 untracked（`--others`）。
+
+    只读 `git ls-files`（cached）的话，SEC-A 的新文件在 `git add` 之前不在面上 ⇒ 门在提交前绿、
+    提交后红（reviewer 量到的 3→7 就是这个）。`-c -o --exclude-standard` 让它扫的是**同一批文件**，
+    与索引状态无关；`--exclude-standard` 是必须的：不带它 `--others` 会把 `.gitignore` 挡掉的
+    东西（`node_modules/`、`backend/data/`）也列进来，那既是噪声也不是交付面。忽略规则由 git
+    自己解释，本门不另起一套。
+    """
+    listing = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
+                             cwd=root, capture_output=True, check=True)
+    return sorted({raw.decode("utf-8", "replace") for raw in listing.stdout.split(b"\0") if raw})
+
+
+def _gate_offenders(measured: Mapping[str, int]) -> list[str]:
+    """命中集与豁免表对账，三个方向都算违规：未豁免的文件、处数不等、表里的死行。
+
+    失败信息只报**路径与处数**：把命中片段抄进断言消息等于在 CI 日志里再复制一次凭据。
+    """
+    offenders: list[str] = []
+    for relative, count in sorted(measured.items()):
+        row = EXEMPTIONS.get(relative)
+        if row is None:
+            offenders.append(f"{relative} ×{count} 未豁免")
+        elif count != row[0]:
+            offenders.append(f"{relative} ×{count} ≠ 豁免表 {row[0]} 处")
+    offenders += [f"{relative} 是豁免表死行（当前 0 命中）"
+                  for relative in sorted(set(EXEMPTIONS) - set(measured))]
+    return offenders
 
 
 def test_repository_tracked_files_hold_no_credential_material():
     """SECA-20：扫描是普通 pytest 用例，本地与既有 CI job 同一道门。"""
-    offenders: list[str] = []
-    for site, snippet in _scan_sites():
-        if site in EXEMPT_HITS:
-            continue
-        offenders.append(f"{site} {snippet}")
+    offenders = _gate_offenders(_hit_counts(_delivery_surface_names()))
     assert [] == offenders, (
-        "tracked 文件出现凭据形态取值，请加豁免前先确认它不是真凭据：" + "; ".join(offenders)
+        "交付面出现凭据形态的字面量：先确认它不是真凭据，再按 (文件, 处数) 过评审进豁免表；"
+        + "; ".join(offenders)
     )
 
 
 def test_the_exemption_table_matches_the_hit_set():
-    """反向闸：豁免表里每一行都必须在真实命中集中——把表放大一档（多列一个不命中的行）立刻红。"""
-    assert {str(item) for item in EXEMPT_HITS} == _scan_hits()
+    """反向闸：豁免表与命中集互等——多一档（死行）、少一档、处数漂一位，都立刻红。"""
+    assert {relative: row[0] for relative, row in EXEMPTIONS.items()} == _hit_counts(
+        _delivery_surface_names())
+
+
+def test_every_exemption_states_why_it_is_not_material():
+    """豁免表的每一行都得有"为什么不是材料"，且指向的文件必须真实在场。
+
+    一张只写"测试文件"的表就是洗白过的门：判据是每一行的理由**写得出来**（不空、短不到能
+    复述成一句标签、也不止是在重复文件名），文件本身存在（死文件行由互等那条兜，这里兜的是
+    空理由与养闲条目）。
+    """
+    for relative, (count, why) in EXEMPTIONS.items():
+        assert count >= 1, relative
+        text = why.strip()
+        assert len(text) >= 16, f"{relative} 的理由不够具体：{text!r}"
+        assert Path(PurePosixPath(relative).name).stem not in text, (
+            f"{relative} 的理由只是在重复文件名")
+        assert (REPO_ROOT / relative).is_file(), f"{relative} 豁免了不存在的文件"
+
+
+def test_a_planted_credential_turns_the_gate_red(tmp_path):
+    """SECA-20 的证伪：门必须真的能红。往"tracked 样子"的文件里植一枚假凭据 ⇒ 未豁免 ⇒ 红。
+
+    只在 tmp 里落盘，不碰仓库索引与工作树；被植的字面量按**拼接**构造，所以本文件自己
+    不会因为这条测试而多出一处命中（那会把豁免表的计数拖成移动靶）。
+    """
+    planted_relative = "backend/app/planted_secret_holder.py"
+    planted = tmp_path / planted_relative
+    planted.parent.mkdir(parents=True, exist_ok=True)
+    planted.write_text(f"{_ENV_KEY_NAME}=\"{_PLANTED_VALUE}\"\n", encoding="utf-8")
+
+    measured = _hit_counts([planted_relative], root=tmp_path)
+    assert 1 == measured[planted_relative], "植入的凭据形态没被抓到 ⇒ 面本身就是瞎的"
+    offenders = [item for item in _gate_offenders(measured) if item.startswith(planted_relative)]
+    assert offenders, "植进去的凭据没有让门红"
+
+
+def test_a_second_credential_on_an_exempt_line_is_not_silenced(tmp_path):
+    """豁免键含**处数**而不是行号 ⇒ 已豁免那一行上再放第二枚凭据，处数 +1 ⇒ 门红。
+
+    这条是 Fix 的靶心：按 `文件:行` 建键的门会把它静音（同一行 = 同一个键）。这里取表里真实
+    存在的一行命中（`security_startup.py` 的默认常量），在同一行尾部再植一枚，然后按同一份
+    扫描实现读数。
+    """
+    relative = "backend/app/security_startup.py"
+    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
+    exempt_line_number = _occurrence_lines(source, relative=relative)[0]
+    lines = source.splitlines(keepends=True)
+    lines[exempt_line_number - 1] = (
+        lines[exempt_line_number - 1].rstrip("\r\n")
+        + f"  # {_ENV_KEY_NAME}=\"{_SECOND_PLANTED_VALUE}\"\n"
+    )
+    planted = tmp_path / relative
+    planted.parent.mkdir(parents=True, exist_ok=True)
+    planted.write_text("".join(lines), encoding="utf-8")
+
+    measured = _hit_counts([relative], root=tmp_path)
+    assert EXEMPTIONS[relative][0] + 1 == measured[relative], (
+        "第二枚凭据没有让处数变化 ⇒ 键退化成了行号，豁免会吞掉同一行上的任何新泄漏")
+    offenders = [item for item in _gate_offenders(measured) if item.startswith(relative)]
+    assert offenders, "处数已经漂了却仍然对账通过 ⇒ 豁免把第二枚吞了"
+
+
+# 植入用的字面量按拼接构造：本文件在扫描面上，任何"键 + = + 引号 + ≥16 无空白值"的写法都会
+# 让豁免表的计数变成移动靶。
+_ENV_KEY_NAME = "JWT_" + "SECRET"
+_PLANTED_VALUE = "planted-" + "credential-material-32-bytes"
+_SECOND_PLANTED_VALUE = "second-" + "credential-on-exempt-line"
 
 
 # --------------------------------------------------------------------------- #
@@ -413,15 +770,21 @@
 
 
 class AvailabilityEventAttributionTests(unittest.TestCase):
-    """Task 8 移交（503 fidelity）：改密/重置腿的容量拒绝不再冒充 LOGIN 事件，detail 值域不动。"""
+    """helper 层：`_auth_availability_denial` 把 action 透传给唯一的 writer，detail 值域不动。
+
+    这一层**只**证明"传了就写对"；它在 call site 把 `action="PASSWORD"` 删掉时照样绿（用例是
+    直接调 helper 的）。路由层的归属钉子在下面的 `PasswordLegActionAttributionTests`。
+    """
 
     def test_login_leg_capacity_denial_is_still_a_login_event(self):
+        from app import auth
+
         with mock.patch("app.main.record_login_event") as rec:
             from app.main import _auth_availability_denial
 
             _auth_availability_denial("admin", PasswordCapacityError("x"))
         self.assertEqual("LOGIN", rec.call_args.kwargs["action"])
-        self.assertEqual(audit_module_detail_capacity(), rec.call_args.kwargs["detail"])
+        self.assertEqual(auth.AUDIT_PASSWORD_CAPACITY, rec.call_args.kwargs["detail"])
 
     def test_password_leg_capacity_denial_is_labelled_password_not_login(self):
         with mock.patch("app.main.record_login_event") as rec:
@@ -444,7 +807,86 @@
         self.assertEqual("LOGIN", record.call_args.kwargs["action"])
 
 
-def audit_module_detail_capacity() -> str:
-    from app import auth
+class PasswordLegActionAttributionTests(_LoginHarness):
+    """路由归属不变量：**一条路由上的事件只属于一种 action**，归属由路由决定而不是 helper 默认值。
+
+    - `/api/auth/login` 的每一格拒绝 ⇒ `LOGIN`；
+    - `/api/auth/password/change` 的每一格拒绝（策略 422 / 可用性 429·503 / 旧口令 401）⇒ `PASSWORD`。
+
+    改密腿的旧口令校验与登录腿共用同一个判定与同一把计数器（§7.1），但**事件归属**跟着路由走：
+    一条腿里三格拒登记成 `PASSWORD`、一格登记成 `LOGIN`，运维面就再也分不出"有人在爆破改密接口"
+    与"有人在爆破登录接口"。判据必须逐腿打真路由——直接调 helper 时删掉 call site 的
+    `action="PASSWORD"`，helper 层钉子全绿（那正是上一类测不到的那一格）。
+    """
+
+    CHANGE_PATH = "/api/auth/password/change"
 
-    return auth.AUDIT_PASSWORD_CAPACITY
+    def _admin_headers(self) -> dict[str, str]:
+        token = self._login("admin", "admin123").json()["access_token"]
+        return {"Authorization": f"Bearer {token}"}
+
+    def _change(self, headers: dict[str, str], *, current: str, new: str):
+        return self.client.post(self.CHANGE_PATH,
+                                json={"current_password": current, "new_password": new},
+                                headers=headers)
+
+    def _last_event(self) -> dict:
+        events = self.events()
+        self.assertTrue(events, "这一腿没写下任何审计事件")
+        return events[-1]
+
+    def test_wrong_current_password_on_the_change_route_is_a_password_event(self):
+        """401 那一格：旧口令错发生在改密路由上 ⇒ PASSWORD，不是 LOGIN。"""
+        headers = self._admin_headers()
+        response = self._change(headers, current="not-my-password 123", new="a-brand-new-pw 123456")
+        self.assertEqual(401, response.status_code, response.text)
+        event = self._last_event()
+        self.assertEqual("invalid_credentials", event["detail"])
+        self.assertEqual("PASSWORD", event["action"],
+                         "同一条路由上 503/429 记 PASSWORD、401 记 LOGIN = 归属劈叉")
+
+    def test_capacity_denial_on_the_change_route_is_a_password_event(self):
+        """503 那一格（第一跳撞容量闸）：翻译点在路由上，action 由路由给。"""
+        headers = self._admin_headers()
+        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
+            response = self._change(headers, current="admin123", new="a-brand-new-pw 123456")
+        self.assertEqual(503, response.status_code, response.text)
+        event = self._last_event()
+        self.assertEqual("password_capacity", event["detail"])
+        self.assertEqual("PASSWORD", event["action"])
+
+    def test_throttle_denial_on_the_change_route_is_a_password_event(self):
+        """429 那一格：桶耗尽后由 `_auth_availability_denial` 翻译，归属同样在路由上。"""
+        from app import login_throttle
+
+        headers = self._admin_headers()
+        bucket = login_throttle.PreHashThrottle(window_seconds=60, max_attempts=2)
+        with mock.patch.object(login_throttle, "pre_hash_throttle", bucket):
+            for _ in range(2):
+                self.assertEqual(401, self._change(headers, current="wrong-old-pw 123",
+                                                   new="a-brand-new-pw 123456").status_code)
+            throttled = self._change(headers, current="wrong-old-pw 123",
+                                     new="a-brand-new-pw 123456")
+        self.assertEqual(429, throttled.status_code, throttled.text)
+        event = self._last_event()
+        self.assertEqual("login_throttled", event["detail"])
+        self.assertEqual("PASSWORD", event["action"])
+
+    def test_policy_denial_on_the_change_route_stays_a_password_event(self):
+        """422 那一格（Task 7 就记 PASSWORD）：它是这条不变量的另一头，缺席就说明归属被改过。"""
+        headers = self._admin_headers()
+        response = self._change(headers, current="admin123", new="abc")
+        self.assertEqual(422, response.status_code, response.text)
+        event = self._last_event()
+        self.assertEqual("password_policy_rejected", event["detail"])
+        self.assertEqual("PASSWORD", event["action"])
+
+    def test_the_login_route_keeps_every_denial_a_login_event(self):
+        """反向：登录腿一格都不改 ⇒ 归属不变量不是"把 PASSWORD 铺开"，而是按路由分。"""
+        self.assertEqual(401, self._login("admin", "not-my-password 123").status_code)
+        self.assertEqual(("LOGIN", "invalid_credentials"),
+                         (self._last_event()["action"], self._last_event()["detail"]))
+        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
+            self.assertEqual(503, self._login("admin", "admin123").status_code)
+        self.assertEqual(("LOGIN", "password_capacity"),
+                         (self._last_event()["action"], self._last_event()["detail"]))
## files changed with NO pre-fix snapshot (controller attests the delta)
- backend/.env.example: duplicate Argon2 m/t/p rationale collapsed (200 -> 199 lines, CRLF preserved)
- frontend/src/views/OperationsView.tsx: logTypes += "PASSWORD" (fix round) ; ACTION_LABELS += PASSWORD:口令变更 (controller)
- frontend/src/views/GovernanceView.tsx: ACTION_LABELS += PASSWORD:口令变更 (controller)
- docs/SECURITY_A_SPECIFICATION.md: 28 -> 17/7 measurement write-back + new 20.4 (controller)
- docs/UI: none
## current line-ending + size facts
backend/app/main.py: bytes=46436 CRLF=987 loneLF=0 loneCR=0
backend/app/security.py: bytes=14011 CRLF=0 loneLF=334 loneCR=0
backend/tests/test_secret_hygiene_contract.py: bytes=51222 CRLF=0 loneLF=892 loneCR=0
frontend/src/views/OperationsView.tsx: bytes=8480 CRLF=0 loneLF=187 loneCR=0
frontend/src/views/GovernanceView.tsx: bytes=13022 CRLF=0 loneLF=295 loneCR=0
backend/.env.example: bytes=10945 CRLF=199 loneLF=0 loneCR=0

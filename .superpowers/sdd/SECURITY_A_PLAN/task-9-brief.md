## Task 9: secret 卫生（脱敏两域 + 启动守卫 + 扫描门）

**Files:**
- Create: `backend/app/security_startup.py`
- Modify: `backend/app/security.py`（新增 `redact_for_persistence`，**不动** `redact_secrets`）
- Modify: `backend/app/audit.py:43,59`、`backend/app/agent_trace.py:73,91`（落盘面切换）
- Modify: `backend/app/config.py`（`cors_allow_origins`）
- Modify: `backend/app/main.py:77-83`（CORS env 化）、`main.py:53-68`（lifespan 第三道守卫）
- Modify: `backend/.env.example`
- Modify: `backend/tests/test_branding_contract.py:32`
- Test: `backend/tests/test_secret_hygiene_contract.py`（新建）

**Interfaces:**
- Produces:
  ```python
  # app/security.py
  PERSISTENCE_SENSITIVE_KEYS: frozenset[str]
  def redact_for_persistence(value: Any) -> Any
  # app/security_startup.py
  DEFAULT_JWT_SECRET = "change-me-before-production-yaoke-demo-secret"
  class SecurityStartupError(RuntimeError): ...
  def evaluate_startup_guards(*, enterprise_mode: bool, jwt_secret: str, cors_allow_origins: str) -> list[str]
  def assert_startup_safe() -> None      # violations 非空 ⇒ raise SecurityStartupError
  ```
- Consumes: `settings.security_enterprise_mode`（Task 4）、`settings.cors_allow_origins`（本任务）

- [ ] **Step 1: 写失败的测试**（`backend/tests/test_secret_hygiene_contract.py`）

```python
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import security, security_startup  # noqa: E402

NOT_SECRETS = ("input_tokens", "output_tokens", "num_sources", "total_tokens", "token_type")
SECRETS = ("password", "password_hash", "access_token", "refresh_token",
           "authorization", "api_key", "app_secret", "tenant_access_token")


def test_persistence_redaction_kills_sensitive_keys_by_exact_name():
    payload = {key: "sensitive-value" for key in SECRETS}
    redacted = security.redact_for_persistence(payload)
    assert all(redacted[key] == security.REDACTED for key in SECRETS), redacted


def test_persistence_redaction_does_not_collateral_damage_observability_keys():
    """SECA-17 的反方向：子串匹配 `token` 会顺手抹掉 usage 计数，那等于砸掉 observability 契约。"""
    payload = {"input_tokens": 12, "output_tokens": 34, "num_sources": 5,
               "total_tokens": 46, "token_type": "bearer"}
    assert payload == security.redact_for_persistence(payload)


def redact_secrets_semantics_are_unchanged():
    """既有 28 处调用点的响应面语义一字不动（SEC-A-006）。"""
    assert security.redact_secrets({"access_token": "keep-me"}) == {"access_token": "keep-me"}
    assert "Bearer [REDACTED]" in security.redact_secrets("header: Bearer abc.def.ghi")


def test_user_store_is_never_passed_through_a_redactor():
    """授权凭据库 ≠ 遥测面：把 redactor 罩到写凭据那一层，写进去的 hash 会被抹成占位符，
    下一次登录必失败（M9 就是这条）。判据是"持久层 import 里没有它"。"""
    source = (BACKEND_DIR / "app" / "user_store.py").read_text(encoding="utf-8")
    assert "redact_for_persistence" not in source
    assert "from app.security import" not in source


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        (dict(enterprise_mode=True, jwt_secret=security_startup.DEFAULT_JWT_SECRET,
              cors_allow_origins="http://localhost:3000"), 2),
        (dict(enterprise_mode=True, jwt_secret="x" * 48, cors_allow_origins="https://kb.example"), 0),
        (dict(enterprise_mode=False, jwt_secret=security_startup.DEFAULT_JWT_SECRET,
              cors_allow_origins=""), 0),
        (dict(enterprise_mode=True, jwt_secret=security_startup.DEFAULT_JWT_SECRET,
              cors_allow_origins=""), 2),
    ],
)
def test_the_three_guards_live_or_die_together(kwargs, expected):
    """SECA-18：企业形态下三件守卫同生同死，不允许"只落了 seed 半件"。"""
    violations = security_startup.evaluate_startup_guards(**kwargs)
    assert expected == len(violations), violations


def test_env_example_never_carries_a_credential_env_var():
    """SEC-A-002 的配置面半边：CREDENTIALS_PASSWORD 是一次性 CLI 变量。

    `.env` 由服务进程加载，把它写进模板等于让明文口令常驻配置面。
    """
    text = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8")
    keys = {line.split("=", 1)[0].strip() for line in text.splitlines() if "=" in line and not line.startswith("#")}
    assert not {key for key in keys if "PASSWORD" in key.upper()}, sorted(keys)
    assert "SECURITY_ENTERPRISE_MODE" in keys
    assert "CORS_ALLOW_ORIGINS" in keys


def test_repository_tracked_files_hold_no_credential_material():
    """SECA-20：扫描是普通 pytest 用例，本地与既有 CI job 同一道门。"""
    listing = subprocess.run(
        ["git", "ls-files", "-z"], cwd=BACKEND_DIR.parent, capture_output=True, check=True
    )
    offenders: list[str] = []
    exempt = EXEMPT_HITS  # 豁免表 == 命中表，见下
    for raw in listing.stdout.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8", "replace")
        path = BACKEND_DIR.parent / relative
        if not path.is_file() or path.suffix in {".png", ".webp", ".ico", ".woff", ".woff2", ".pyc"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in CREDENTIAL_PATTERN.finditer(text):
            site = f"{relative}:{text[:match.start()].count(chr(10)) + 1}"
            if site in exempt:
                continue
            offenders.append(f"{site} {match.group(0)[:24]}")
    assert [] == offenders, f"tracked 文件出现凭据形态取值，请加豁免前先确认它不是真凭据：{offenders}"


CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(?:api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{16,}"
)

# 豁免表逐项必须写成"文件:行 + 为什么它不是凭据"，且必须与命中集相等——
# 只增不减的豁免表等于没有豁免表（与 test_llm_egress_guard.py 同一族做法）。
EXEMPT_HITS: frozenset[str] = frozenset()


def test_the_exemption_table_matches_the_hit_set():
    hits = _scan_hits()  # 与上一用例共用的纯函数，返回同样的 site 字符串集合
    assert {str(item) for item in EXEMPT_HITS} == hits
```

最后一条要求把扫描逻辑抽成 `_scan_hits()` 供两条用例共用——**不许**两处各写一份正则，那样豁免表与命中表会各自漂移。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_secret_hygiene_contract.py -q
```
Expected: `ModuleNotFoundError: No module named 'app.security_startup'`（以及 `security` 无 `redact_for_persistence`）。

- [ ] **Step 3: 写实现**

`backend/app/security.py` 追加（**不改** `redact_text` / `redact_secrets`）：

```python
PERSISTENCE_SENSITIVE_KEYS = frozenset(
    {
        "password", "password_hash", "plaintext_password", "current_password", "new_password",
        "access_token", "refresh_token", "authorization", "api_key", "app_secret",
        "tenant_access_token", "secret", "credentials",
    }
)


def redact_for_persistence(value: Any) -> Any:
    """落盘面（审计 / trace / 日志 / 遥测表）脱敏：形态匹配 + **精确键名**匹配。

    刻意不做子串匹配：`token` 命中 tenant_access_token 也命中 input_tokens，
    后者是观测数据不是秘密。授权凭据库（user_store）不经过这里（SEC-A-009）。
    """
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            redact_text(key): (
                REDACTED if str(key).lower() in PERSISTENCE_SENSITIVE_KEYS
                else redact_for_persistence(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_for_persistence(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_for_persistence(item) for item in value)
    return value
```

`backend/app/audit.py`：`:9` 的 import 与 `:43`、`:59` 两处从 `redact_secrets` 换成 `redact_for_persistence`。`backend/app/agent_trace.py`：`:73`、`:91` 同理。**其余 24 处调用点不动**（含 8 处响应面 return）。

`backend/app/security_startup.py`：

```python
"""生产形态的启动守卫（规格 §8.5）。三件守卫由一枚开关共同驱动，不存在矛盾组合。"""

from __future__ import annotations

DEFAULT_JWT_SECRET = "change-me-before-production-yaoke-demo-secret"


class SecurityStartupError(RuntimeError):
    """企业形态下配置不安全 ⇒ 拒绝启动。比第一个请求才炸好。"""


def evaluate_startup_guards(
    *, enterprise_mode: bool, jwt_secret: str, cors_allow_origins: str
) -> list[str]:
    if not enterprise_mode:
        return []
    violations: list[str] = []
    if not jwt_secret or jwt_secret == DEFAULT_JWT_SECRET or len(jwt_secret) < 32:
        violations.append("SECURITY_ENTERPRISE_MODE 下 JWT_SECRET 必须是 ≥32 字符的非默认值")
    origins = [item.strip() for item in (cors_allow_origins or "").split(",") if item.strip()]
    if not origins or "*" in origins:
        violations.append("SECURITY_ENTERPRISE_MODE 下 CORS_ALLOW_ORIGINS 必须是显式白名单")
    return violations


def assert_startup_safe() -> None:
    from app.config import settings

    violations = evaluate_startup_guards(
        enterprise_mode=bool(settings.security_enterprise_mode),
        jwt_secret=str(settings.jwt_secret),
        cors_allow_origins=str(settings.cors_allow_origins),
    )
    if violations:
        raise SecurityStartupError("；".join(violations))
```

`config.py`：`cors_allow_origins: str = "http://localhost:3000"`。`main.py:77-83`：

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in settings.cors_allow_origins.split(",") if item.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

`main.py` lifespan 第三道（docstring 同步改掉"默认配置下启动零额外行为"里已不成立的部分——守卫在无企业开关时确实是 no-op，但这一句要写准）：

```python
    security_startup.assert_startup_safe()
    warmup_identity_permissions()
    warmup_llm_router()
```

`.env.example` 追加（口令变量刻意**不**进这张表，理由写注释里）：

```
# SEC-A：生产形态总开关。true ⇒ 不加载 demo 身份 + 默认 JWT_SECRET 拒启动 + CORS 白名单必填。
SECURITY_ENTERPRISE_MODE=false
# 逗号分隔白名单，不是子串、不是通配。
CORS_ALLOW_ORIGINS=http://localhost:3000
LOGIN_THROTTLE_WINDOW_SECONDS=60
LOGIN_THROTTLE_MAX_ATTEMPTS=10
ACCOUNT_MAX_FAILED_ATTEMPTS=5
ACCOUNT_LOCK_SECONDS=900
ARGON2_MAX_CONCURRENT_OPS=2
# 注意：CLI 口令变量 CREDENTIALS_PASSWORD **不要**写进本文件。
# .env 由服务进程加载，明文口令进来就等于进了常驻配置面（SEC-A-002）。
# Argon2 的 m/t/p 也不在这里：能运维调的安全强度等于没有强度（SEC-A-008）。
```

`test_branding_contract.py:32` 改写（收紧，不是放松）：

```python
        self.assertIn('JWT_SECRET=change-me-before-production-yaoke-demo-secret', env_example)
        # 占位符仍须出现在 .env.example（部署模板），但它**必须**被企业形态守卫拒绝：
        # 一条"模板里有的默认值"如果能一路跑到生产，那这条 branding 断言就是在保护漏洞。
        self.assertIn(
            security_startup.DEFAULT_JWT_SECRET, env_example
        )
        self.assertIn(
            2,
            len(
                security_startup.evaluate_startup_guards(
                    enterprise_mode=True,
                    jwt_secret=security_startup.DEFAULT_JWT_SECRET,
                    cors_allow_origins="",
                )
            ),
        )
```

- [ ] **Step 4: 填豁免表并跑测试**

```bash
cd /e/xiangmu/rag/backend && python -m pytest tests/test_secret_hygiene_contract.py -q
```
首轮会把 `.env.example:132`（占位符）、若干测试假值命中打成红。逐条判断：**确认为占位符/假值**才写进 `EXEMPT_HITS`（形如 `backend/.env.example:132`），任何真实凭据形态都必须换成占位值而不是豁免。目标：两条扫描用例同时绿，且豁免表与命中表相等。

- [ ] **Step 5: 全套件 + 快照**

```bash
cd /e/xiangmu/rag/backend && python -m pytest -q
cp -r app ../.superpowers/sdd/SECURITY_A_PLAN/snap-task9-app
echo "- Ruling: 429/503 与 redactor 分层后，既有 redact_secrets 的 28 处调用点零改动；只切 audit/trace 的 4 处落盘面。" >> ../.superpowers/sdd/SECURITY_A_PLAN/progress.md
```

---


# 飞书权限桥接（Permission Bridge）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **本仓库不是 git 仓库**：所有"提交"步骤替换为"运行完整后端测试套件并保持全绿"。禁止任何破坏性回滚操作；每完成一个任务先跑套件再继续。

**Goal:** 按已批准规格实现飞书部门/群 → 本地角色 + 知识库范围的权限桥接，默认关闭、失败收紧、可 mock 全量验证。

**Architecture:** 新建 `backend/app/identity/` 包（base 数据模型 / mapper 纯函数 / feishu_client 真实客户端 / resolver 缓存与降级编排）；`auth.py`、`knowledge.py`、`main.py` 各加最小接缝消费 resolver 产出的 `FeishuGrant`。

**Tech Stack:** FastAPI + pydantic v2 + pydantic-settings + httpx（已在 requirements.txt）+ unittest 风格契约测试（`backend/tests/`）。

**Spec:** `E:\xiangmu\rag\docs\FEISHU_PERMISSION_BRIDGE_DESIGN.md`（本计划逐段实现它，执行时两份一起读）

## Global Constraints

- `feishu_permissions_enabled` 默认 `False`；关闭时全部行为与今日完全一致（回归护栏是硬验收）。
- 不新增第三方依赖（httpx、pyjwt、pydantic 已具备）。
- 不改前端任何文件；不改后端既有 API 路径与响应结构。
- app_secret / token 不写日志、不进响应；审计 detail 一律经 `app.security.redact_text`。
- 失败语义只收紧不提权：飞书不可用且无缓存时 = 本地角色 + 仅公共知识库 + `FEISHU_PERMISSION/DEGRADED` 审计。
- 测试从 `E:\xiangmu\rag\backend` 目录运行：`python -m pytest tests/<file> -v`；全套件 `python -m pytest tests -q`。
- 展示文案约定见 `docs/UI_COPY_GLOSSary.md` 不适用本计划（纯后端）。错误消息用中文（与 auth.py 现风格一致）。

## 文件结构（新建 ★ / 修改 ✎）

| 文件 | 职责 |
| --- | --- |
| ★ `backend/app/identity/__init__.py` | 对外入口 `resolve_for_user()`，开关与身份映射判断，单例装配 |
| ★ `backend/app/identity/base.py` | `ExternalIdentity`/`FeishuGrant`/规则模型，无 IO |
| ★ `backend/app/identity/mapper.py` | 规则文件加载校验 + 纯函数匹配 |
| ★ `backend/app/identity/feishu_client.py` | 飞书开放平台客户端，httpx transport 注入 |
| ★ `backend/app/identity/resolver.py` | TTL 缓存 + 失败收紧链 + 审计 |
| ★ `backend/config/feishu_permissions.json` | 映射规则样例（部门→HR 库、群→管理员） |
| ✎ `backend/app/config.py` | 追加 8 个 `feishu_*` 设置 |
| ✎ `backend/app/knowledge.py` | `public_kb_ids()`、`visible_bases_by_ids()`、`resolve_requested(..., allowed=None)` |
| ✎ `backend/app/auth.py` | `CurrentUser.grant`、grant 感知的 permissions/enforce、require_user 接线、USERS `feishu_open_id` |
| ✎ `backend/app/main.py` | `_allowed_ids` 与 `visible_bases` 端点消费 grant |
| ★ `backend/tests/test_feishu_identity_contract.py` | 全部新测试（单文件，unittest 风格） |
| ★ `backend/app/identity/README.md` | provider 扩展接入文档（Task 6） |

---

### Task 1: 数据模型 + 设置 + 规则加载与匹配（纯函数）

**Files:**
- Create: `backend/app/identity/base.py`, `backend/app/identity/mapper.py`, `backend/config/feishu_permissions.json`
- Modify: `backend/app/config.py`（文件末尾 `settings = Settings()` 之前追加字段）
- Test: `backend/tests/test_feishu_identity_contract.py`（新建，本任务只写模型/匹配部分）

**Interfaces:**
- Produces: `ExternalIdentity(username, open_id, department_ids, department_names, chat_ids, chat_names)`；`FeishuGrant(access_role: "admin"|"user"|"viewer"|None, knowledge_base_ids: list[str], all_knowledge_bases: bool, degraded: bool)`；`FeishuRuleSet`；`load_rule_set(path: str) -> FeishuRuleSet`（坏文件抛 `ValueError`）；`match_identity(identity, rule_set) -> FeishuGrant | None`；`ROLE_RANK = {"viewer": 0, "user": 1, "admin": 2}`；设置字段 `feishu_permissions_enabled, feishu_app_id, feishu_app_secret, feishu_base_url, feishu_timeout_seconds, feishu_cache_ttl_seconds, feishu_cache_stale_seconds, feishu_rules_file`。

- [ ] **Step 1: 写失败测试**（新建测试文件，内容如下）

```python
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.identity.base import ExternalIdentity, FeishuGrant  # noqa: E402
from app.identity.mapper import load_rule_set, match_identity  # noqa: E402


def write_rules(payload: dict) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, handle, ensure_ascii=False)
    handle.close()
    return handle.name


class RuleLoadingTests(unittest.TestCase):
    def test_loads_valid_rules(self):
        path = write_rules({"rules": [{"match": {"department_ids": ["od-hr"]},
                                       "grant": {"access_role": "user",
                                                 "knowledge_base_ids": ["kb_hr"]}}]})
        rule_set = load_rule_set(path)
        self.assertEqual(len(rule_set.rules), 1)

    def test_empty_match_rule_rejected(self):
        # 空 match 会命中所有人，属于配置事故，必须在加载期拒绝。
        path = write_rules({"rules": [{"match": {}, "grant": {"access_role": "admin"}}]})
        with self.assertRaises(ValueError):
            load_rule_set(path)

    def test_missing_file_raises(self):
        with self.assertRaises(ValueError):
            load_rule_set("no-such-rules.json")


class MatchingTests(unittest.TestCase):
    identity = ExternalIdentity(username="zhang", open_id="ou_1",
                                department_ids=["od-hr"], department_names=["人事部"],
                                chat_ids=[], chat_names=[])

    def test_hit_grants_role_and_kb(self):
        path = write_rules({"rules": [
            {"match": {"department_names": ["人事部"]},
             "grant": {"access_role": "user", "knowledge_base_ids": ["kb_hr"]}}]})
        grant = match_identity(self.identity, load_rule_set(path))
        self.assertIsNotNone(grant)
        self.assertEqual(grant.access_role, "user")
        self.assertEqual(grant.knowledge_base_ids, ["kb_hr"])
        self.assertFalse(grant.all_knowledge_bases)

    def test_multi_hit_takes_highest_role_and_union(self):
        path = write_rules({"rules": [
            {"match": {"department_ids": ["od-hr"]},
             "grant": {"access_role": "user", "knowledge_base_ids": ["kb_hr"]}},
            {"match": {"department_names": ["人事部"]},
             "grant": {"access_role": "admin", "knowledge_base_ids": ["kb_sales", "*"]}},
        ]})
        grant = match_identity(self.identity, load_rule_set(path))
        self.assertEqual(grant.access_role, "admin")
        self.assertTrue(grant.all_knowledge_bases)
        self.assertEqual(grant.knowledge_base_ids, ["kb_hr", "kb_sales"])

    def test_no_hit_returns_none(self):
        path = write_rules({"rules": [{"match": {"chat_ids": ["oc_x"]},
                                       "grant": {"access_role": "admin"}}]})
        self.assertIsNone(match_identity(self.identity, load_rule_set(path)))

    def test_fields_within_one_rule_are_and(self):
        path = write_rules({"rules": [
            {"match": {"department_ids": ["od-hr"], "chat_ids": ["oc_missing"]},
             "grant": {"access_role": "admin"}}]})
        self.assertIsNone(match_identity(self.identity, load_rule_set(path)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败** — Run: `python -m pytest tests/test_feishu_identity_contract.py -v`；Expected: collection error（`app.identity` 不存在）。
- [ ] **Step 3: 实现 `identity/base.py`**

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AccessLevel = Literal["viewer", "user", "admin"]
ROLE_RANK: dict[str, int] = {"viewer": 0, "user": 1, "admin": 2}


class ExternalIdentity(BaseModel):
    username: str
    open_id: str
    department_ids: list[str] = Field(default_factory=list)
    department_names: list[str] = Field(default_factory=list)
    chat_ids: list[str] = Field(default_factory=list)
    chat_names: list[str] = Field(default_factory=list)


class RuleMatch(BaseModel):
    department_ids: list[str] = Field(default_factory=list)
    department_names: list[str] = Field(default_factory=list)
    chat_ids: list[str] = Field(default_factory=list)
    chat_names: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.department_ids or self.department_names or self.chat_ids or self.chat_names)


class RuleGrant(BaseModel):
    access_role: AccessLevel | None = None
    knowledge_base_ids: list[str] = Field(default_factory=list)


class FeishuRule(BaseModel):
    match: RuleMatch = Field(default_factory=RuleMatch)
    grant: RuleGrant


class FeishuRuleSet(BaseModel):
    rules: list[FeishuRule] = Field(default_factory=list)


class FeishuGrant(BaseModel):
    access_role: AccessLevel | None = None
    knowledge_base_ids: list[str] = Field(default_factory=list)
    all_knowledge_bases: bool = False
    degraded: bool = False
```

- [ ] **Step 4: 实现 `identity/mapper.py`**

```python
from __future__ import annotations

import json
from pathlib import Path

from app.identity.base import ExternalIdentity, FeishuGrant, FeishuRuleSet


def load_rule_set(path: str) -> FeishuRuleSet:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"飞书权限规则文件不可用：{path}") from exc
    rule_set = FeishuRuleSet.model_validate(raw)
    for index, rule in enumerate(rule_set.rules):
        # 空 match 等于向全员授予，是配置事故而不是宽松规则。
        if rule.match.is_empty():
            raise ValueError(f"飞书权限规则 #{index} 缺少匹配条件")
    return rule_set


def _rule_hits(identity: ExternalIdentity, rule) -> bool:
    match = rule.match
    checks = (
        (match.department_ids, identity.department_ids),
        (match.department_names, identity.department_names),
        (match.chat_ids, identity.chat_ids),
        (match.chat_names, identity.chat_names),
    )
    for wanted, owned in checks:
        if wanted and not (set(wanted) & set(owned)):
            return False
    return True


def match_identity(identity: ExternalIdentity, rule_set: FeishuRuleSet) -> FeishuGrant | None:
    from app.identity.base import ROLE_RANK

    best_role = None
    kb_ids: set[str] = set()
    all_kb = False
    hit = False
    for rule in rule_set.rules:
        if not _rule_hits(identity, rule):
            continue
        hit = True
        if rule.grant.access_role and (
            best_role is None or ROLE_RANK[rule.grant.access_role] > ROLE_RANK[best_role]
        ):
            best_role = rule.grant.access_role
        if "*" in rule.grant.knowledge_base_ids:
            all_kb = True
        kb_ids.update(k for k in rule.grant.knowledge_base_ids if k != "*")
    if not hit:
        return None
    return FeishuGrant(access_role=best_role, knowledge_base_ids=sorted(kb_ids),
                       all_knowledge_bases=all_kb)
```

- [ ] **Step 5: `config.py` 追加设置**（放在 `demo_data_dir` 之后、`settings = Settings()` 之前）

```python
    # Feishu permission bridge (see docs/FEISHU_PERMISSION_BRIDGE_DESIGN.md).
    # Disabled by default: every behaviour stays exactly like the demo accounts.
    feishu_permissions_enabled: bool = False
    feishu_app_id: str = ""
    feishu_app_secret: SecretStr = SecretStr("")
    feishu_base_url: str = "https://open.feishu.cn"
    feishu_timeout_seconds: float = Field(default=3.0, ge=0.5, le=30.0)
    feishu_cache_ttl_seconds: int = Field(default=900, ge=30, le=86400)
    feishu_cache_stale_seconds: int = Field(default=86400, ge=60, le=604800)
    feishu_rules_file: str = "config/feishu_permissions.json"
```

并在文件首行 import 处确保 `SecretStr` 已导入（现有 `from pydantic import Field, SecretStr` 已包含则不动）。
- [ ] **Step 6: 创建样例规则** `backend/config/feishu_permissions.json`

```json
{
  "rules": [
    {
      "match": { "department_names": ["人力资源"] },
      "grant": { "access_role": "user", "knowledge_base_ids": ["kb_public", "kb_hr"] }
    },
    {
      "match": { "chat_names": ["知识库管理员群"] },
      "grant": { "access_role": "admin", "knowledge_base_ids": ["*"] }
    }
  ]
}
```

- [ ] **Step 7: 运行测试通过** — Run: `python -m pytest tests/test_feishu_identity_contract.py -v`；Expected: 全部 PASS。
- [ ] **Step 8: 全套件保持绿** — Run: `python -m pytest tests -q`；Expected: 与改动前一致通过。

---

### Task 2: 飞书客户端（transport 注入 + MockTransport 测试）

**Files:**
- Create: `backend/app/identity/feishu_client.py`
- Test: `backend/tests/test_feishu_identity_contract.py`（追加 `FeishuClientTests`）

**Interfaces:**
- Consumes: Task 1 的设置字段。
- Produces: `FeishuAPIError(RuntimeError)`；`ChatInfo(chat_id, name)`；`class FeishuClient(app_id, app_secret, base_url, timeout_seconds, client: httpx.Client | None = None)`，方法 `tenant_access_token() -> str`（按 expire 缓存、提前 60s 刷新）、`fetch_user(open_id) -> dict`（含 `department_ids`）、`department_name(department_id) -> str`、`list_chats() -> list[ChatInfo]`（自动翻页）、`chat_member_ids(chat_id) -> list[str]`。

- [ ] **Step 1: 追加失败测试**（`httpx.MockTransport` 路由假响应；断言鉴权头、翻页聚合、token 缓存命中、`code!=0` 抛错）

```python
import httpx

from app.identity.feishu_client import ChatInfo, FeishuAPIError, FeishuClient  # noqa: E402


def make_client(handler) -> FeishuClient:
    return FeishuClient("cli_x", "secret_x", "https://feishu.test", 3.0,
                        client=httpx.Client(transport=httpx.MockTransport(handler)))


class FeishuClientTests(unittest.TestCase):
    def test_token_cached_and_headers(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.url.path, request.headers.get("Authorization")))
            if request.url.path.endswith("tenant_access_token/internal"):
                return httpx.Response(200, json={"code": 0, "tenant_access_token": "t-1", "expire": 7200})
            return httpx.Response(200, json={"code": 0, "data": {"user": {"department_ids": ["od-1"]}}})

        client = make_client(handler)
        self.assertEqual(client.fetch_user("ou_1")["department_ids"], ["od-1"])
        self.assertEqual(client.fetch_user("ou_2")["department_ids"], ["od-1"])
        token_calls = [c for c in calls if c[0].endswith("internal")]
        self.assertEqual(len(token_calls), 1)  # 第二次走缓存
        self.assertTrue(any(h == "Bearer t-1" for _, h in calls))

    def test_error_code_raises(self):
        def handler(request):
            return httpx.Response(200, json={"code": 99991663, "msg": "invalid token"})

        with self.assertRaises(FeishuAPIError):
            make_client(handler).list_chats()

    def test_chat_pagination(self):
        def handler(request):
            if "auth" in request.url.path:
                return httpx.Response(200, json={"code": 0, "tenant_access_token": "t", "expire": 7200})
            if request.url.params.get("page_token"):
                return httpx.Response(200, json={"code": 0, "data": {"items": [{"chat_id": "oc_2", "name": "库2群"}], "has_more": False}})
            return httpx.Response(200, json={"code": 0, "data": {"items": [{"chat_id": "oc_1", "name": "库1群"}], "has_more": True, "page_token": "p"}})

        self.assertEqual(make_client(handler).list_chats(),
                         [ChatInfo("oc_1", "库1群"), ChatInfo("oc_2", "库2群")])
```

- [ ] **Step 2: 运行确认失败**（ImportError）— Run: `python -m pytest tests/test_feishu_identity_contract.py -v -k FeishuClient`。
- [ ] **Step 3: 实现 `identity/feishu_client.py`**

```python
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx


class FeishuAPIError(RuntimeError):
    """Any non-zero Feishu business code or transport failure."""


@dataclass(frozen=True)
class ChatInfo:
    chat_id: str
    name: str


class FeishuClient:
    """Tenant-token server-side client. Only the bot-visible chat universe is
    queryable, so membership is confirmed per chat via the members endpoint."""

    def __init__(self, app_id: str, app_secret: str, base_url: str,
                 timeout_seconds: float, client: httpx.Client | None = None) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._base_url = base_url.rstrip("/")
        self._http = client or httpx.Client(timeout=timeout_seconds)
        self._token = ""
        self._token_expire_at = 0.0

    def tenant_access_token(self) -> str:
        now = time.monotonic()
        if self._token and now < self._token_expire_at - 60:
            return self._token
        data = self._request("POST", "/open-apis/auth/v3/tenant_access_token/internal",
                             json={"app_id": self._app_id, "app_secret": self._app_secret}, auth=False)
        self._token = str(data["tenant_access_token"])
        self._token_expire_at = now + float(data.get("expire", 7200))
        return self._token

    def fetch_user(self, open_id: str) -> dict:
        data = self._request("GET", f"/open-apis/contact/v3/users/{open_id}",
                             params={"user_id_type": "open_id"})
        return dict(data.get("user") or {})

    def department_name(self, department_id: str) -> str:
        data = self._request("GET", f"/open-apis/contact/v3/departments/{department_id}",
                             params={"department_id_type": "open_department_id"})
        return str((data.get("department") or {}).get("name", ""))

    def list_chats(self) -> list[ChatInfo]:
        chats: list[ChatInfo] = []
        page_token = ""
        while True:
            params = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            data = self._request("GET", "/open-apis/im/v1/chats", params=params)
            chats.extend(ChatInfo(str(i.get("chat_id", "")), str(i.get("name", "")))
                         for i in data.get("items") or [])
            if not data.get("has_more"):
                return chats
            page_token = str(data.get("page_token", ""))
            if not page_token:
                return chats

    def chat_member_ids(self, chat_id: str) -> list[str]:
        data = self._request("GET", f"/open-apis/im/v1/chats/{chat_id}/members",
                             params={"member_id_type": "open_id"})
        return [str(i.get("member_id", "")) for i in data.get("members") or []]

    def _request(self, method: str, path: str, *, json=None, params=None, auth: bool = True) -> dict:
        headers = {"Authorization": f"Bearer {self.tenant_access_token()}"} if auth else {}
        try:
            response = self._http.request(method, f"{self._base_url}{path}",
                                          json=json, params=params, headers=headers)
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise FeishuAPIError(f"飞书接口请求失败：{path}") from exc
        if payload.get("code", 0) != 0:
            raise FeishuAPIError(f"飞书接口返回错误：{path}（业务码 {payload.get('code')}）")
        return dict(payload.get("data") or payload)
```

注意 token 接口响应无 `data` 包裹（`tenant_access_token` 在顶层），`_request` 末行 `payload.get("data") or payload` 已兼容。超时/网络异常统一 `FeishuAPIError`，不重试。
- [ ] **Step 4: 运行通过** — Run: `python -m pytest tests/test_feishu_identity_contract.py -v`；随后 `python -m pytest tests -q` 全绿。

---

### Task 3: resolver（缓存 + 失败收紧 + 审计）与包入口

**Files:**
- Create: `backend/app/identity/resolver.py`, `backend/app/identity/__init__.py`
- Modify: `backend/app/knowledge.py`（新增两个函数，见 Step 3）
- Test: `backend/tests/test_feishu_identity_contract.py`（追加 `ResolverTests`）

**Interfaces:**
- Consumes: Task 1 `match_identity`/`load_rule_set`/`FeishuGrant`；Task 2 `FeishuClient`/`FeishuAPIError`；`app.audit.record_event`（关键字参数 `username, role, action, status, knowledge_base_id, detail`）。
- Produces: `IdentityResolver(client, rule_set, *, ttl_seconds, stale_seconds, clock=time.monotonic)`，方法 `resolve(username: str, role: str, open_id: str) -> FeishuGrant`；`app.identity.resolve_for_user(username: str, role: str, record: dict) -> FeishuGrant | None`（开关关 / 无 `feishu_open_id` 时返回 None）；`knowledge.public_kb_ids() -> list[str]`；`knowledge.visible_bases_by_ids(ids) -> list[dict]`。

- [ ] **Step 1: 追加失败测试**（FakeClient 覆盖：新鲜缓存不重复外呼、零命中→None 语义的本地授予、API 异常→stale 缓存标 degraded、无缓存→本地角色+公共库且写 DEGRADED 审计）

```python
from app.identity.resolver import IdentityResolver  # noqa: E402
from app.identity.base import FeishuGrant  # noqa: E402（文件顶部已有则不重复）


class FakeClient:
    def __init__(self, *, departments=None, chats=None, fail=False):
        self.departments = departments or {}
        self.chats = chats or []
        self.fail = fail
        self.calls = 0

    def _guard(self):
        self.calls += 1
        if self.fail:
            raise FeishuAP_INote = None  # placeholder removed below

```

以真实代码为准的完整测试（书写时直接使用）：

```python
class FakeClient:
    def __init__(self, *, departments=None, chats=None, members=None, fail=False):
        self.departments = departments or {}
        self.chats = chats or []
        self.members = members or {}
        self.fail = fail
        self.fetch_calls = 0

    def fetch_user(self, open_id):
        self.fetch_calls += 1
        if self.fail:
            from app.identity.feishu_client import FeishuAPIError
            raise FeishuAPIError("down")
        return {"department_ids": self.departments}

    def department_name(self, department_id):
        return {"od-hr": "人力资源"}.get(department_id, department_id)

    def list_chats(self):
        return self.chats

    def chat_member_ids(self, chat_id):
        return self.members.get(chat_id, [])


class _AuditRecorder:
    def __enter__(self):
        from app import audit
        self.module = audit
        self.saved = audit.record_event
        self.events = []
        audit.record_event = lambda **kwargs: self.events.append(kwargs)
        return self

    def __exit__(self, *exc):
        self.module.record_event = self.saved


def build_resolver(client, rules_payload, *, ttl=900, stale=86400, clock=None):
    from app.identity.mapper import load_rule_set
    path = write_rules(rules_payload)
    return IdentityResolver(client, load_rule_set(path),
                            ttl_seconds=ttl, stale_seconds=stale,
                            clock=clock or _Clock()), clock


class _Clock:
    def __init__(self):
        self.now = 1000.0
    def __call__(self):
        return self.now


class ResolverTests(unittest.TestCase):
    RULES = {"rules": [{"match": {"department_names": ["人力资源"]},
                         "grant": {"access_role": "user", "knowledge_base_ids": ["kb_hr"]}}]}

    def test_match_and_cache_hit(self):
        client = FakeClient(departments=["od-hr"])
        resolver, clock = build_resolver(client, self.RULES)
        grant = resolver.resolve("u1", "USER", "ou_1")
        self.assertEqual(grant.access_role, "user")
        first = client.fetch_calls
        resolver.resolve("u1", "USER", "ou_1")
        self.assertEqual(client.fetch_calls, first)  # 缓存命中不再外呼

    def test_zero_hit_stays_local(self):
        client = FakeClient(departments=["od-other"])
        resolver, _ = build_resolver(client, self.RULES)
        grant = resolver.resolve("u2", "USER", "ou_2")
        self.assertIsNone(grant.access_role)
        self.assertEqual(grant.knowledge_base_ids, [])
        self.assertFalse(grant.degraded)

    def test_failure_uses_stale_cache_marked_degraded(self):
        client = FakeClient(departments=["od-hr"])
        resolver, clock = build_resolver(client, self.RULES, ttl=100, stale=200)
        resolver.resolve("u3", "USER", "ou_3")
        client.fail = True
        clock.now += 150  # 超过 TTL、未超 stale
        with _AuditRecorder() as audit:
            grant = resolver.resolve("u3", "USER", "ou_3")
        self.assertEqual(grant.access_role, "user")
        self.assertTrue(grant.degraded)
        self.assertTrue(any(e["action"] == "FEISHU_PERMISSION" and e["status"] == "DEGRADED"
                            for e in audit.events))

    def test_failure_without_cache_tightens_to_public_only(self):
        from app.knowledge import public_kb_ids
        client = FakeClient(fail=True)
        resolver, _ = build_resolver(client, self.RULES)
        with _AuditRecorder():
            grant = resolver.resolve("u4", "ADMIN", "ou_4")
        self.assertIsNone(grant.access_role)          # 角色回本地，绝不放大
        self.assertEqual(grant.knowledge_base_ids, public_kb_ids())
        self.assertTrue(grant.all_knowledge_bases is False)
        self.assertTrue(grant.degraded)
```

- [ ] **Step 2: 运行确认失败**（`app.identity.resolver` 不存在）。
- [ ] **Step 3: `knowledge.py` 追加**（放在 `visible_bases` 之后）

```python
def public_kb_ids() -> list[str]:
    return [base["id"] for base in KNOWLEDGE_BASES.values() if base["department"] == "ALL"]


def visible_bases_by_ids(knowledge_base_ids: list[str]) -> list[dict[str, Any]]:
    return [dict(KNOWLEDGE_BASES[kb_id]) for kb_id in knowledge_base_ids if kb_id in KNOWLEDGE_BASES]
```

- [ ] **Step 4: 实现 `identity/resolver.py`**

```python
from __future__ import annotations

import time
from dataclasses import dataclass

from app.identity.base import ExternalIdentity, FeishuGrant, FeishuRuleSet
from app.identity.feishu_client import FeishuAPIError, FeishuClient
from app.identity.mapper import match_identity


@dataclass
class _CacheEntry:
    grant: FeishuGrant | None
    fetched_at: float


class IdentityResolver:
    def __init__(self, client: FeishuClient, rule_set: FeishuRuleSet, *,
                 ttl_seconds: int, stale_seconds: int, clock=time.monotonic) -> None:
        self._client = client
        self._rule_set = rule_set
        self._ttl = ttl_seconds
        self._stale = stale_seconds
        self._clock = clock
        self._cache: dict[str, _CacheEntry] = {}

    def resolve(self, username: str, role: str, open_id: str) -> FeishuGrant:
        entry = self._cache.get(username)
        now = self._clock()
        if entry and now - entry.fetched_at <= self._ttl:
            return _copy(entry.grant)
        try:
            grant = self._fetch_and_match(username, open_id)
        except (FeishuAPIError, RuntimeError) as exc:
            grant = self._tighten(username, role, entry, exc)
        self._cache[username] = _CacheEntry(grant, now)
        return _copy(grant)

    def _fetch_and_match(self, username: str, open_id: str) -> FeishuGrant | None:
        user = self._client.fetch_user(open_id)
        department_ids = [str(i) for i in user.get("department_ids") or []]
        names = [self._client.department_name(i) for i in department_ids]
        chat_ids, chat_names = self._visible_chats(open_id)
        identity = ExternalIdentity(username=username, open_id=open_id,
                                    department_ids=department_ids, department_names=[n for n in names if n],
                                    chat_ids=chat_ids, chat_names=chat_names)
        return match_identity(identity, self._rule_set)

    def _visible_chats(self, open_id: str) -> tuple[list[str], list[str]]:
        # tenant 身份只能枚举机器人所在群，因此按规则白名单逐群确认成员，
        # 避免全量扫群。
        wanted_ids = {v for rule in self._rule_set.rules for v in rule.match.chat_ids}
        wanted_names = {v for rule in self._rule_set.rules for v in rule.match.chat_names}
        if not wanted_ids and not wanted_names:
            return [], []
        hit_ids, hit_names = [], []
        for chat in self._client.list_chats():
            if chat.chat_id not in wanted_ids and chat.name not in wanted_names:
                continue
            if open_id in self._client.chat_member_ids(chat.chat_id):
                hit_ids.append(chat.chat_id)
                hit_names.append(chat.name)
        return hit_ids, hit_names

    def _tighten(self, username: str, role: str, entry: _CacheEntry | None,
                 exc: Exception) -> FeishuGrant | None:
        from app.audit import record_event
        from app.knowledge import public_kb_ids
        from app.security import redact_text

        now = self._clock()
        if entry and now - entry.fetched_at <= self._stale and entry.grant is not None:
            degraded = _copy(entry.grant, degraded=True)
        else:
            # 无可用缓存：本地角色（access_role=None）+ 仅公共知识库。
            degraded = FeishuGrant(access_role=None, knowledge_base_ids=public_kb_ids(),
                                   all_knowledge_bases=False, degraded=True)
        record_event(username=username, role=role, action="FEISHU_PERMISSION",
                     status="DEGRADED", detail=redact_text(exc))
        return degraded


def _copy(grant: FeishuGrant | None, degraded: bool | None = None) -> FeishuGrant | None:
    if grant is None:
        return None
    clone = grant.model_copy()
    if degraded is not None:
        clone.degraded = degraded
    return clone
```

- [ ] **Step 5: 实现 `identity/__init__.py` 入口**（装配单例 + 开关判断；auth 只调它）

```python
from __future__ import annotations

from app.identity.base import FeishuGrant

_resolver = None


def get_resolver():
    global _resolver
    if _resolver is None:
        from app.config import settings
        from app.identity.feishu_client import FeishuClient
        from app.identity.mapper import load_rule_set
        from app.identity.resolver import IdentityResolver

        client = FeishuClient(settings.feishu_app_id,
                              settings.feishu_app_secret.get_secret_value(),
                              settings.feishu_base_url, settings.feishu_timeout_seconds)
        _resolver = IdentityResolver(client, load_rule_set(settings.feishu_rules_file),
                                     ttl_seconds=settings.feishu_cache_ttl_seconds,
                                     stale_seconds=settings.feishu_cache_stale_seconds)
    return _resolver


def reset_resolver() -> None:
    global _resolver
    _resolver = None


def resolve_for_user(username: str, role: str, record: dict) -> FeishuGrant | None:
    """Grant for one local account. None keeps today's local-only semantics."""
    from app.config import settings

    open_id = str(record.get("feishu_open_id") or "")
    if not settings.feishu_permissions_enabled or not open_id:
        return None
    return get_resolver().resolve(username, role, open_id)
```

- [ ] **Step 6: 运行通过** — `python -m pytest tests/test_feishu_identity_contract.py -v`；全套件绿。

**注**：Step 1 测试里的 `build_resolver` 返回 `(resolver, clock)` 但 `test_match_and_cache_hit` 解包两个值，`_AuditRecorder` 里 `audit.record_event` 猴子补丁必须成对还原；resolver 内 `record_event` 采用**调用时**从 `app.audit` 取（函数内 import），测试补丁才生效——上面实现已满足。

---

### Task 4: auth 接线（grant 感知的角色/权限，默认关闭零影响）

**Files:**
- Modify: `backend/app/auth.py`（CurrentUser、has_permission、require_user、USERS 注释示例）
- Modify: `backend/tests/test_feishu_identity_contract.py`（追加 `AuthWiringTests`）

**Interfaces:**
- Consumes: `app.identity.resolve_for_user`；现有 `ACCESS_ROLE_PERMISSIONS`、`require_user`。
- Produces: `CurrentUser(..., grant: FeishuGrant | None = None)`；`user.permissions`/`user.access_role` grant 优先；`has_permission(user, p)` 基于 `user.permissions`。

- [ ] **Step 1: 追加失败测试**

```python
class AuthWiringTests(unittest.TestCase):
    def _user(self, role, grant=None):
        from app.auth import CurrentUser
        return CurrentUser(username="u", display_name="U", role=role, grant=grant)

    def test_disabled_path_is_current_behaviour(self):
        user = self._user("VIEWER")
        self.assertEqual(user.access_role, "viewer")
        self.assertIn("knowledge:read", user.permissions)
        self.assertNotIn("knowledge:query", user.permissions)

    def test_grant_overrides_role_levels(self):
        from app.identity.base import FeishuGrant
        user = self._user("VIEWER", FeishuGrant(access_role="admin"))
        self.assertEqual(user.access_role, "admin")
        self.assertIn("system:operate", user.permissions)

    def test_enforce_permission_follows_grant(self):
        from app.auth import CurrentUser, enforce_permission
        from app.identity.base import FeishuGrant
        admin_granted = self._user("VIEWER", FeishuGrant(access_role="admin"))
        self.assertIs(enforce_permission(admin_granted, "system:operate"), admin_granted)
        with self.assertRaises(HTTPException):
            from fastapi import HTTPException  # noqa: F401（文件顶部统一导入）
```

（`from fastapi import HTTPException` 移到文件顶部 import 区。）
- [ ] **Step 2: 运行确认失败**（`grant` 字段未知）。
- [ ] **Step 3: 修改 `auth.py`**
  - 顶部加 `from app.identity.base import FeishuGrant`（identity 不反向 import auth，无环）。
  - `CurrentUser` 追加字段 `grant: FeishuGrant | None = None`；`access_role` 属性改为 `return self.grant.access_role if self.grant and self.grant.access_role else access_role_for(self.role)`；`permissions` 改为 `ACCESS_ROLE_PERMISSIONS[self.access_role]`（access_role 为 None 时返回 `()`）。
  - `has_permission(user, permission)` 改为 `permission in user.permissions`。
  - `require_user` 与 `authenticate` 构造 `CurrentUser` 前加 `grant = resolve_for_user(record["username"], record["role"], record)` 并传入。（`import jwt` 区加 `from app.identity import resolve_for_user`。）
  - USERS 的 viewer 记录旁加演示注释：`# 预留 "feishu_open_id": "ou_xxx" 即接入飞书匹配（需 feishu_permissions_enabled=true）`，不改任何现有演示账号数据。
- [ ] **Step 4: 运行通过 + 既有 RBAC 契约不破** — `python -m pytest tests/test_feishu_identity_contract.py tests/test_rbac_contract.py -v`；全套件绿。

---

### Task 5: 知识库范围接缝（resolve_requested / _allowed_ids / visible_bases）

**Files:**
- Modify: `backend/app/knowledge.py:58-69`（`resolve_requested` 加 `allowed` 参数）
- Modify: `backend/app/main.py`（`_allowed_ids`、`/knowledge-bases` 端点）
- Test: 追加 `ScopeTests`

**Interfaces:**
- Consumes: `user.grant`；Task 3 `public_kb_ids`/`visible_bases_by_ids`。
- Produces: `resolve_requested(role, knowledge_base_id, allowed: list[str] | None = None)` — `allowed` 提供时跳过 ROLE_ACCESS 直接以其为白名单（`None` 保持旧行为）。

- [ ] **Step 1: 追加失败测试**

```python
class ScopeTests(unittest.TestCase):
    def test_allowed_override_wins_over_role(self):
        from app.knowledge import resolve_requested
        self.assertEqual(resolve_requested("VIEWER", None, allowed=["kb_hr"]), ["kb_hr"])
        with self.assertRaises(PermissionError):
            resolve_requested("VIEWER", "kb_product", allowed=["kb_hr"])

    def test_none_allowed_keeps_legacy(self):
        from app.knowledge import resolve_requested
        self.assertEqual(set(resolve_requested("HR", None)), {"kb_public", "kb_hr"})


class MainWiringTests(unittest.TestCase):
    def test_allowed_ids_uses_grant_scope(self):
        from app.auth import CurrentUser
        from app.identity.base import FeishuGrant
        from app.main import _allowed_ids
        user = CurrentUser(username="u", display_name="U", role="VIEWER",
                           grant=FeishuGrant(access_role="user", knowledge_base_ids=["*"],
                                             all_knowledge_bases=True))
        self.assertIn("kb_hr", _allowed_ids(user, None))

    def test_denied_grant_scope_is_audited_403(self):
        from app.auth import CurrentUser
        from app.identity.base import FeishuGrant
        from app.main import _allowed_ids
        user = CurrentUser(username="u", display_name="U", role="ADMIN",
                           grant=FeishuGrant(knowledge_base_ids=["kb_public"]))
        with self.assertRaises(HTTPException) as box:
            _allowed_ids(user, "kb_hr")
        self.assertEqual(box.exception.status_code, 403)
```

- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现**
  - `knowledge.py`：`resolve_requested(role, knowledge_base_id, allowed=None)`——`allowed is None` 时函数体现有逻辑原样保留；否则以 `allowed` 为白名单执行 same `all`/单库/拒绝分支（错误文案不变）。
  - `main.py` `_allowed_ids`：开头解析有效白名单：

```python
    allowed: list[str] | None = None
    if user.grant is not None:
        if user.grant.all_knowledge_bases:
            allowed = list(KNOWLEDGE_BASES.keys())
        elif user.grant.knowledge_base_ids:
            allowed = list(user.grant.knowledge_base_ids)
```

  再 `return resolve_requested(user.role, knowledge_base_id, allowed=allowed)`。（`KNOWLEDGE_BASES` 需从 `app.knowledge` 导入；main.py 现有 import 行扩展。）注意：grant 为空授予（`access_role=None, kb_ids=[]`，零命中）时 `allowed=None` → 落回本地规则，符合规格 §2.2"零命中走本地语义"。
  - `/knowledge-bases` 端点（main.py:231）：`user.grant` 存在时改用 `visible_bases_by_ids(有效 id 列表)`（all→全部；空授予→ `visible_bases(user.role)`）。
- [ ] **Step 4: 运行通过** + `python -m pytest tests -q` 全绿（`test_rbac_contract.py` 必须一题不破）。

---

### Task 6: 端到端护栏 + provider 接入文档

**Files:**
- Modify: `backend/tests/test_feishu_identity_contract.py`（追加 `EndToEndGuardTests`）
- Create: `backend/app/identity/README.md`

**Interfaces:**
- Consumes: 全部前序任务。
- Produces: 文档：新增 OIDC/企微 provider 的 4 步接入说明 + 启用飞书的配置样例。

- [ ] **Step 1: 追加护栏测试**（开关关闭：monkeypatch `settings.feishu_permissions_enabled=False`，TestClient 或直接 `resolve_for_user` 断言返回 None；开关开启 + FakeClient 注入 `identity._resolver`：`resolve_for_user` 对带 `feishu_open_id` 的记录产出 grant，`all_knowledge_bases` 全见、降级时 DEGRADED 审计可查）

```python
class EndToEndGuardTests(unittest.TestCase):
    def test_disabled_returns_none_without_network(self):
        import app.identity as identity
        from app.config import settings
        identity.reset_resolver()
        saved = settings.feishu_permissions_enabled
        settings.feishu_permissions_enabled = False
        try:
            self.assertIsNone(identity.resolve_for_user("viewer", "VIEWER",
                                                         {"feishu_open_id": "ou_x"}))
        finally:
            settings.feishu_permissions_enabled = saved

    def test_enabled_uses_injected_resolver(self):
        import app.identity as identity
        from app.config import settings
        from app.identity.base import FeishuGrant

        class Stub:
            def resolve(self, username, role, open_id):
                return FeishuGrant(access_role="user", knowledge_base_ids=["kb_hr"])

        saved = (settings.feishu_permissions_enabled, identity._resolver)
        settings.feishu_permissions_enabled = True
        identity._resolver = Stub()
        try:
            grant = identity.resolve_for_user("staff", "VIEWER", {"feishu_open_id": "ou_9"})
            self.assertEqual(grant.access_role, "user")
            self.assertIsNone(identity.resolve_for_user("staff", "VIEWER", {}))  # 无 open_id
        finally:
            settings.feishu_permissions_enabled = saved
            identity._resolver = saved[1]
```

- [ ] **Step 2: 运行通过**（先失败后实现如常）。
- [ ] **Step 3: 写 `backend/app/identity/README.md`**：启用步骤（env 五个键 + 规则文件 + 用户表 `feishu_open_id`）、当前规则语义（角色取高/库并集/`"*"`/失败收紧链）、**新增 provider 四步**（实现 fetch 同构方法返回 `ExternalIdentity`；`resolve_for_user` 内按 settings 选择 provider；规则模型加 provider 判别字段；补同类 contract 测试）。
- [ ] **Step 4: 全量回归** — `python -m pytest tests -q` 全绿；手动 `curl /api/knowledge-bases`（未开启状态）确认响应与改造前一致。

---

## Self-Review 结论

- 规格覆盖：§2.1 四端点→Task 2；§2.2 规则语义→Task 1/3；§2.3 缓存/收紧→Task 3；§3 接缝→Task 4/5；§5 错误表→Task 3 测试 + Task 6 护栏；§6 文档→Task 6。规格 §2.1 的"群成员逐群确认"细化在 Task 3 `_visible_chats`（规则白名单限定），与规格修订一致。
- 无占位符；`Task 3 Step 1` 中的示意片段已用"以真实代码为准"的完整块替代，执行者只抄完整块。
- 类型一致性：`FeishuGrant` 全计划同名；`resolve_requested(..., allowed=)` 与 `_allowed_ids` 使用一致；`resolve_for_user(username, role, record)` 三参一致。

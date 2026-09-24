from __future__ import annotations

import ast
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi import HTTPException

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.identity.base import ExternalIdentity, FeishuGrant  # noqa: E402
from app.identity.feishu_client import ChatInfo, FeishuAPIError, FeishuClient  # noqa: E402
from app.identity.mapper import load_rule_set, match_identity  # noqa: E402
from app.identity.resolver import IdentityResolver  # noqa: E402


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


def make_client(handler) -> FeishuClient:
    return FeishuClient("cli_x", "secret_x", "https://feishu.test", 3.0,
                        client=httpx.Client(transport=httpx.MockTransport(handler)))


# 有界 handler 的天花板：真出现"无上限无限翻页"时，让飞书侧在 200 页后不可达，
# 客户端必然抛 FeishuAPIError → 测试失败而不是挂死。护栏本身在 50 页，取不到这个数。
_PAGING_HARD_STOP = 200


def _paging_handler(sink: list[str], page_token: object, page: dict):
    """对任意分页接口恒返回 `has_more=True` + 给定 `page_token`，并把分页请求记进 `sink`。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if "auth" in request.url.path:
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t", "expire": 7200})
        sink.append(request.url.path)
        if len(sink) > _PAGING_HARD_STOP:
            return httpx.Response(503, json={"code": 1, "msg": "test is spinning"})
        return httpx.Response(200, json={"code": 0, "data": {**page, "has_more": True,
                                                             "page_token": page_token}})

    return handler


def _run_paging(method: str, handler) -> tuple[object, list[str]]:
    """跑一次分页方法，返回 `(结果或 None, 异常)`；分页请求计数在 handler 的 sink 里。"""
    client = make_client(handler)
    call = client.list_chats if method == "list_chats" else lambda: client.chat_member_ids("oc_1")
    try:
        return call(), None
    except FeishuAPIError as exc:
        return None, exc


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

    def test_missing_tenant_token_raises_api_error(self):
        # code==0 但缺 tenant_access_token / expire 非数字：都必须在客户端边界收口，
        # 不能以 KeyError、ValueError 穿透 resolver 的 except (FeishuAPIError, RuntimeError)。
        def no_token(request):
            return httpx.Response(200, json={"code": 0, "expire": 7200})

        with self.assertRaises(FeishuAPIError):
            make_client(no_token).fetch_user("ou_1")

        def bad_expire(request):
            if "auth" in request.url.path:
                return httpx.Response(200, json={"code": 0, "tenant_access_token": "t-1",
                                                  "expire": "not-a-number"})
            return httpx.Response(200, json={"code": 0, "data": {"user": {"department_ids": ["od-1"]}}})

        client = make_client(bad_expire)
        self.assertEqual(client.tenant_access_token(), "t-1")  # 回退默认 7200
        self.assertEqual(client.fetch_user("ou_1")["department_ids"], ["od-1"])

    def test_bad_status_or_body_shape_raises_api_error(self):
        # 5xx（即使 body 是 code:0）不得当成功；body 为数组 / data 为数组不得抛 AttributeError。
        def service_unavailable(request):
            if "auth" in request.url.path:
                return httpx.Response(200, json={"code": 0, "tenant_access_token": "t", "expire": 7200})
            return httpx.Response(503, json={"code": 0, "data": {"items": []}})

        with self.assertRaises(FeishuAPIError):
            make_client(service_unavailable).list_chats()

        def array_body(request):
            return httpx.Response(200, json=[{"code": 0}])

        with self.assertRaises(FeishuAPIError):
            make_client(array_body).list_chats()

        def list_data(request):
            if "auth" in request.url.path:
                return httpx.Response(200, json={"code": 0, "tenant_access_token": "t", "expire": 7200})
            return httpx.Response(200, json={"code": 0, "data": ["unexpected"]})

        self.assertEqual(make_client(list_data).fetch_user("ou_1"), {})

    def test_chat_member_pagination(self):
        # 成员超过首页时，第 2 页的 open_id 也必须命中（否则恒判"不在群"）。
        seen = []

        def handler(request):
            if "auth" in request.url.path:
                return httpx.Response(200, json={"code": 0, "tenant_access_token": "t", "expire": 7200})
            seen.append(dict(request.url.params))
            if request.url.params.get("page_token"):
                return httpx.Response(200, json={"code": 0, "data": {
                    "members": [{"member_id": "ou_3"}], "has_more": False}})
            return httpx.Response(200, json={"code": 0, "data": {
                "members": [{"member_id": "ou_1"}, {"member_id": "ou_2"}],
                "has_more": True, "page_token": "p"}})

        self.assertEqual(make_client(handler).chat_member_ids("oc_1"), ["ou_1", "ou_2", "ou_3"])
        self.assertTrue(all(p.get("member_id_type") == "open_id" for p in seen))
        self.assertTrue(all(p.get("page_size") == "100" for p in seen))
        self.assertEqual(len(seen), 2)

    PAGES = {"list_chats": {"items": [{"chat_id": "oc_1", "name": "群"}]},
             "chat_member_ids": {"members": [{"member_id": "ou_1"}]}}

    def test_null_page_token_with_has_more_terminates_at_once(self):
        # C1 回归：飞书显式返回 `"page_token": null` 却 `has_more: true` 时，
        # `str(data.get("page_token", ""))` 得到字符串 "None"（真值）→ 下一页照发 → 无限翻页
        # （实测 1.5s 内 11076 个请求）。现在两处都写 `or ""`：拿不到游标就当场收敛返回，
        # 且分页另有 50 页硬上限兜底，任何情况都不会无限打飞书。
        for method, page in self.PAGES.items():
            with self.subTest(method=method):
                calls: list[str] = []
                result, error = _run_paging(method, _paging_handler(calls, None, page))
                self.assertIsNone(error)                        # 不进降级链：一页就收敛
                self.assertEqual(len(calls), 1)                 # 老写法这里是 50 页 + 抛错
                self.assertTrue(result)                         # 返回首页已取到的数据，不丢

    def test_pagination_stops_at_the_safety_cap(self):
        # 上限本身也要有回归锚：游标一直非空（飞书反复返回同一个 page_token 的坏情况）时，
        # 第 50 页之后必须抛 `FeishuAPIError` 落进降级链，而不是继续外呼。
        for method, page in self.PAGES.items():
            with self.subTest(method=method):
                calls: list[str] = []
                result, error = _run_paging(method, _paging_handler(calls, "same-token", page))
                self.assertIsNone(result)
                self.assertIsInstance(error, FeishuAPIError)
                self.assertEqual(len(calls), 50)
                self.assertIn("飞书分页超过安全上限", str(error))
                self.assertIn(calls[0], str(error))              # 报错指名是哪个接口在翻页


class FakeClient:
    def __init__(self, *, departments=None, chats=None, members=None, fail=False):
        self.departments = departments or {}
        self.chats = chats or []
        self.members = members or {}
        self.fail = fail
        self.fetch_calls = 0
        self.list_chats_calls = 0
        self.probed_chats: list[str] = []

    def fetch_user(self, open_id):
        self.fetch_calls += 1
        if self.fail:
            raise FeishuAPIError("down")
        return {"department_ids": self.departments}

    def department_name(self, department_id):
        return {"od-hr": "人力资源"}.get(department_id, department_id)

    def list_chats(self):
        self.list_chats_calls += 1
        return self.chats

    def chat_member_ids(self, chat_id):
        if self.fail:
            raise FeishuAPIError("down")
        self.probed_chats.append(chat_id)
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


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class _CountingClock:
    """记录被采样次数：一次 `resolve` 只允许读一次时钟，缓存与 stale 判定共用同一基准。"""

    def __init__(self):
        self.now = 1000.0
        self.samples = 0

    def __call__(self):
        self.samples += 1
        return self.now


def build_resolver(client, rules_payload, *, ttl=900, stale=86400, failure_ttl=60, clock=None):
    the_clock = clock or _Clock()
    path = write_rules(rules_payload)
    return IdentityResolver(client, load_rule_set(path), ttl_seconds=ttl, stale_seconds=stale,
                            failure_cache_seconds=failure_ttl, clock=the_clock), the_clock


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
        # 零命中的三条口径：授予为空（= 本地语义）、不写一行审计、也不许被当失败写进短 TTL 降级缓存。
        client = FakeClient(departments=["od-other"])
        resolver, clock = build_resolver(client, self.RULES)  # ttl=900 / failure=60
        with _AuditRecorder() as audit:
            grant = resolver.resolve("u2", "USER", "ou_2")
        self.assertIsNone(grant.access_role)
        self.assertEqual(grant.knowledge_base_ids, [])
        self.assertFalse(grant.degraded)
        self.assertEqual(audit.events, [])            # 零命中是正常答案，不是降级，不该有审计

        calls = client.fetch_calls
        clock.now += 120                              # 越过 60s 故障窗口、仍在 900s 成功 TTL 内
        with _AuditRecorder() as later:
            again = resolver.resolve("u2", "USER", "ou_2")
        self.assertEqual(client.fetch_calls, calls)   # 命中的是全量 TTL 条目，不是"失败窗口已过→再试"
        self.assertFalse(again.degraded)
        self.assertEqual(later.events, [])

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

    def test_failure_degraded_result_is_cached_and_audited_once_per_window(self):
        # 裁决C：降级产物也写缓存，但只活 failure_cache_seconds（默认 60s）——
        # 故障期窗口内复用降级结果（仍 degraded、不外呼），审计每周期一行而非每请求。
        client = FakeClient(departments=["od-hr"])
        resolver, clock = build_resolver(client, self.RULES, ttl=100, stale=86400)
        resolver.resolve("u6", "USER", "ou_6")  # 先有一次成功，降级走 stale 复用分支
        client.fail = True
        clock.now += 150                        # 超成功 TTL → 外呼并失败
        with _AuditRecorder() as audit:
            first = resolver.resolve("u6", "USER", "ou_6")
            calls = client.fetch_calls
            clock.now += 30                     # 仍在 60s 故障窗口内
            second = resolver.resolve("u6", "USER", "ou_6")
            self.assertEqual(client.fetch_calls, calls)   # 复用降级产物，不再外呼
            clock.now += 31                     # 越过 60s → 允许再试一次
            third = resolver.resolve("u6", "USER", "ou_6")
            self.assertGreater(client.fetch_calls, calls)
            self.assertEqual(len(audit.events), 2)        # 每降级周期一行，不是每请求一行
        for grant in (first, second, third):
            self.assertTrue(grant.degraded)
            self.assertEqual(grant.access_role, "user")    # 只收紧不提权：仍是旧授予
            self.assertEqual(grant.knowledge_base_ids, ["kb_hr"])

    def test_failure_window_expiry_recovers_and_restores_full_ttl(self):
        client = FakeClient(departments=["od-hr"], fail=True)
        resolver, clock = build_resolver(client, self.RULES, ttl=900, stale=86400)
        with _AuditRecorder():
            degraded = resolver.resolve("u7", "USER", "ou_7")  # 无缓存 + 故障 → 本地 + 公共库
        self.assertTrue(degraded.degraded)
        self.assertIsNone(degraded.access_role)
        client.fail = False
        clock.now += 61                                       # 越过 60s 故障窗口
        grant = resolver.resolve("u7", "USER", "ou_7")
        self.assertFalse(grant.degraded)                      # 恢复即清降级
        self.assertEqual(grant.access_role, "user")
        self.assertEqual(grant.knowledge_base_ids, ["kb_hr"])
        calls = client.fetch_calls
        clock.now += 120                                      # 超 60s、仍在 900s 成功 TTL 内
        resolver.resolve("u7", "USER", "ou_7")
        self.assertEqual(client.fetch_calls, calls)           # 成功路径回到全量 TTL

    def test_prolonged_outage_still_tightens_once_stale_window_passes(self):
        # 降级续期不得刷新 stale 基准，否则"超 stale 收口到本地 + 公共库"永远走不到。
        from app.knowledge import public_kb_ids
        client = FakeClient(departments=["od-hr"])
        resolver, clock = build_resolver(client, self.RULES, ttl=100, stale=200)
        resolver.resolve("u8", "USER", "ou_8")
        client.fail = True
        with _AuditRecorder():
            clock.now += 150          # 故障期第 1 个周期：150s < stale → 复用旧授予
            near = resolver.resolve("u8", "USER", "ou_8")
            clock.now += 65           # 第 2 个周期：距成功抓取 215s > stale → 收口
            far = resolver.resolve("u8", "USER", "ou_8")
        self.assertEqual(near.knowledge_base_ids, ["kb_hr"])
        self.assertTrue(near.degraded)
        self.assertEqual(far.knowledge_base_ids, public_kb_ids())
        self.assertIsNone(far.access_role)
        self.assertTrue(far.degraded)

    def test_chat_membership_hits_and_never_scans_unlisted_chats(self):
        # 规则按 chat_ids 命中：只对规则白名单里的群做成员确认，其余群不发请求。
        rules = {"rules": [{"match": {"chat_ids": ["oc_hr"]},
                            "grant": {"access_role": "admin", "knowledge_base_ids": ["kb_hr"]}}]}
        client = FakeClient(chats=[ChatInfo("oc_hr", "HR群"), ChatInfo("oc_other", "无关群")],
                            members={"oc_hr": ["ou_5"], "oc_other": ["ou_5"]})
        resolver, _ = build_resolver(client, rules)
        grant = resolver.resolve("u5", "USER", "ou_5")
        self.assertEqual(grant.access_role, "admin")
        self.assertEqual(grant.knowledge_base_ids, ["kb_hr"])
        self.assertEqual(client.probed_chats, ["oc_hr"])

    def test_rules_without_chat_conditions_make_zero_chat_calls(self):
        # 空白名单零外呼：规则里一个 chat 条件都没有时，连"机器人有哪些群"都不该问。
        # 给客户端塞满群，确保漏掉早退分支时 `list_chats` 一定被计数。
        client = FakeClient(departments=["od-hr"],
                            chats=[ChatInfo("oc_hr", "HR群"), ChatInfo("oc_other", "无关群")])
        resolver, _ = build_resolver(client, self.RULES)
        grant = resolver.resolve("u9", "USER", "ou_9")
        self.assertEqual(grant.access_role, "user")   # 部门路径不受影响
        self.assertEqual(client.list_chats_calls, 0)
        self.assertEqual(client.probed_chats, [])

    def test_resolve_samples_the_clock_once(self):
        # 一次解析只读一次时钟：`resolve` 顶部采样后传给 `_tighten`，
        # 否则 stale 判定与缓存写入用的是两个时刻，故障窗口会被时钟漂移放大或吃掉。
        clock = _CountingClock()
        client = FakeClient(fail=True)
        resolver, _ = build_resolver(client, self.RULES, clock=clock)
        with _AuditRecorder():
            resolver.resolve("u10", "USER", "ou_10")   # 失败路径
        self.assertEqual(clock.samples, 1)
        clock.samples = 0
        client.fail = False
        clock.now += 61
        resolver.resolve("u10", "USER", "ou_10")       # 成功路径
        self.assertEqual(clock.samples, 1)


class ResolveForUserTests(unittest.TestCase):
    """包入口的三态：开关关 / 无 open_id → None（本地语义）；有 open_id → 委派 resolver。"""

    def setUp(self):
        import app.identity as identity
        from app.config import settings

        self.identity = identity
        self.settings = settings
        self.saved = (settings.feishu_permissions_enabled, identity._resolver, identity.get_resolver)
        self.resolver_built = 0
        identity.get_resolver = self._no_resolver
        identity._resolver = None

    def tearDown(self):
        self.settings.feishu_permissions_enabled = self.saved[0]
        self.identity._resolver = self.saved[1]
        self.identity.get_resolver = self.saved[2]

    def _no_resolver(self):
        self.resolver_built += 1
        raise AssertionError("本地语义下不得装配/触碰 resolver（会真实外呼飞书）")

    def test_disabled_returns_none_without_touching_resolver(self):
        self.settings.feishu_permissions_enabled = False
        grant = self.identity.resolve_for_user("viewer", "USER", {"feishu_open_id": "ou_x"})
        self.assertIsNone(grant)                      # 即使记录里有 open_id
        self.assertEqual(self.resolver_built, 0)

    def test_missing_or_blank_open_id_returns_none_without_touching_resolver(self):
        self.settings.feishu_permissions_enabled = True
        for record in ({}, {"feishu_open_id": ""}, {"feishu_open_id": None}):
            with self.subTest(record=record):
                self.assertIsNone(self.identity.resolve_for_user("staff", "USER", record))
        self.assertEqual(self.resolver_built, 0)

    def test_open_id_delegates_to_resolver(self):
        class Stub:
            def __init__(self):
                self.calls = []

            def resolve(self, username, role, open_id):
                self.calls.append((username, role, open_id))
                return FeishuGrant(access_role="user", knowledge_base_ids=["kb_hr"])

        self.settings.feishu_permissions_enabled = True
        stub = Stub()
        self.identity._resolver = stub
        real_get_resolver = self.saved[2]

        def spy():                        # 委派必须走 `get_resolver()` 这条唯一装配缝
            self.resolver_built += 1
            return real_get_resolver()

        self.identity.get_resolver = spy
        grant = self.identity.resolve_for_user("staff", "ADMIN", {"feishu_open_id": "ou_9"})
        self.assertEqual(self.resolver_built, 1)      # 且只装配一次
        self.assertIs(self.identity._resolver, stub)  # 用的是注入的单例，没另起真客户端
        self.assertEqual(stub.calls, [("staff", "ADMIN", "ou_9")])   # 三参原样透传，不换序
        self.assertIsNotNone(grant)
        self.assertEqual(grant.access_role, "user")
        self.assertEqual(grant.knowledge_base_ids, ["kb_hr"])


class AuthWiringTests(unittest.TestCase):
    """Task 4：`CurrentUser` 消费 grant —— 开关关闭时与今日逐字一致，有授予时角色/权限以 grant 为准。"""

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
        from app.auth import enforce_permission
        from app.identity.base import FeishuGrant
        admin_granted = self._user("VIEWER", FeishuGrant(access_role="admin"))
        self.assertIs(enforce_permission(admin_granted, "system:operate"), admin_granted)
        # 同角色、无授予：仍是今日语义的 403，判定口径不因接线而放宽。
        denied = self._user("VIEWER")
        with self.assertRaises(HTTPException) as raised:
            enforce_permission(denied, "system:operate")
        self.assertEqual(raised.exception.status_code, 403)

    def test_empty_grant_keeps_local_semantics(self):
        # 裁决A：零命中返回的是"空授予"而不是 None —— 角色/权限必须原样落回本地，既不收紧也不放大。
        from app.identity.base import FeishuGrant
        user = self._user("USER", FeishuGrant())
        self.assertEqual(user.access_role, "user")
        self.assertIn("knowledge:query", user.permissions)
        self.assertNotIn("system:operate", user.permissions)

    def test_grant_admitted_request_writes_no_denied_audit(self):
        from app.auth import enforce_permission
        from app.identity.base import FeishuGrant
        granted = self._user("VIEWER", FeishuGrant(access_role="admin"))
        with _AuditRecorder() as audit:
            enforce_permission(granted, "system:operate")
        self.assertEqual(audit.events, [])          # 放行不是安全事件，不该留 DENIED 痕迹

        with _AuditRecorder() as audit:
            with self.assertRaises(HTTPException):
                enforce_permission(self._user("VIEWER"), "system:operate")
        self.assertEqual([(e["action"], e["status"]) for e in audit.events],
                         [("AUTHORIZATION", "DENIED")])

    def test_authenticate_and_require_user_inject_resolved_grant(self):
        # 接线本身才是 Task 4 的交付物：两处构造点都必须把 `resolve_for_user` 的结果传进去，
        # 且每请求重解析——token 里的角色只用于回查账号，权限判定不信任它。
        import app.auth as auth
        from app.identity.base import FeishuGrant

        calls = []
        saved = auth.resolve_for_user

        def spy(username, role, record):
            # 第三参必须是账号记录本身：`feishu_open_id` 就住在里面，传别的等于断线。
            calls.append((username, role, record is auth.USERS[username]))
            return FeishuGrant(access_role="admin")

        auth.resolve_for_user = spy
        try:
            viewer = auth.authenticate("viewer", "viewer123")
            self.assertIsNotNone(viewer)
            self.assertEqual(viewer.access_role, "admin")
            self.assertIn("system:operate", viewer.permissions)
            online = auth.require_user(f"Bearer {auth.issue_token(viewer)}")
        finally:
            auth.resolve_for_user = saved
        self.assertEqual(online.access_role, "admin")
        self.assertEqual(calls, [("viewer", "VIEWER", True), ("viewer", "VIEWER", True)])


class ScopeTests(unittest.TestCase):
    """`resolve_requested` 的兼容签名：`allowed` 提供时它取代 ROLE_ACCESS 白名单（空 = 零可见即拒绝），缺省时旧行为逐字不变。"""

    def test_allowed_override_wins_over_role(self):
        from app.knowledge import resolve_requested
        self.assertEqual(resolve_requested("VIEWER", None, allowed=["kb_hr"]), ["kb_hr"])
        with self.assertRaises(PermissionError):
            resolve_requested("VIEWER", "kb_product", allowed=["kb_hr"])

    def test_none_allowed_keeps_legacy(self):
        from app.knowledge import resolve_requested
        self.assertEqual(set(resolve_requested("HR", None)), {"kb_public", "kb_hr"})

    def test_allowed_branch_keeps_error_messages_and_shapes(self):
        from app.knowledge import resolve_requested
        # None / "" / all 三个入口都是"放行整份白名单"，且返回新列表（不改白名单）。
        allowed = ["kb_public", "kb_hr"]
        for requested in (None, "", "all"):
            self.assertEqual(resolve_requested("ADMIN", requested, allowed=allowed), allowed)
            self.assertIsNot(resolve_requested("ADMIN", requested, allowed=allowed), allowed)
        self.assertEqual(resolve_requested("ADMIN", "kb_hr", allowed=allowed), ["kb_hr"])
        with self.assertRaises(ValueError) as missing:
            resolve_requested("ADMIN", "kb_nope", allowed=allowed)
        self.assertEqual(str(missing.exception), "知识库不存在")
        with self.assertRaises(PermissionError) as denied:
            resolve_requested("ADMIN", "kb_hr", allowed=["kb_public"])
        self.assertEqual(str(denied.exception), "当前账号无权访问该知识库")
        # 白名单即权威：本地 role 未知也按白名单放行，不叠加第二道 role 判定。
        self.assertEqual(resolve_requested("UNKNOWN", "kb_hr", allowed=["kb_hr"]), ["kb_hr"])

    def test_empty_allowed_whitelist_is_denied_not_full_corpus(self):
        # C1：`allowed=[]` 是"零可见"，不是"没有白名单"。放行 all/None 等于把 [] 交给
        # 下游的 falsy 判定（store._kb_filter / retrieval._scope_key），那里曾经=全库。
        from app.knowledge import resolve_requested
        for requested in (None, "", "all", "kb_public", "kb_hr"):
            with self.assertRaises(PermissionError) as denied:
                resolve_requested("ADMIN", requested, allowed=[])
            self.assertEqual(str(denied.exception), "当前账号无知识库访问权限")
        # 文案与"未知 role 的本地 fail-closed"同源，因此 403 + ACCESS/DENIED 映射自动生效。
        with self.assertRaises(PermissionError) as local:
            resolve_requested("UNKNOWN", None)
        self.assertEqual(str(local.exception), "当前账号无知识库访问权限")


class GrantScopeTests(unittest.TestCase):
    """裁决 D：`allowed_for` / `resolve_for` 是知识范围的唯一权威入口。"""

    def _user(self, role, grant=None):
        from app.auth import CurrentUser
        return CurrentUser(username="u", display_name="U", role=role, grant=grant)

    def test_missing_and_empty_grant_are_locally_identical(self):
        # 无授予（开关关闭/未桥接）与零命中空授予必须逐字等于今日本地语义：既不放大也不收紧。
        from app.knowledge import allowed_for, resolve_for, visible_for
        from app.identity.base import FeishuGrant
        for grant in (None, FeishuGrant(), FeishuGrant(degraded=True)):
            user = self._user("HR", grant)
            self.assertEqual(allowed_for(user), ["kb_public", "kb_hr"])
            self.assertEqual(resolve_for(user, None), ["kb_public", "kb_hr"])
            self.assertEqual(resolve_for(user, "kb_hr"), ["kb_hr"])
            self.assertEqual([base["id"] for base in visible_for(user)], ["kb_public", "kb_hr"])
            with self.assertRaises(PermissionError):
                resolve_for(user, "kb_product")
        # CurrentUser.role 是 Literal，未授予时本地语义只可能是这五个角色之一；
        # "未知 role 的 fail-closed" 属 resolve_requested 直调口径，由 ScopeTests 守。
        self.assertEqual(self._user("VIEWER", None).role, "VIEWER")
        self.assertEqual(allowed_for(self._user("VIEWER", FeishuGrant())), ["kb_public"])

    def test_empty_grant_is_not_authoritative(self):
        # 判定"命中与否"收在授予自身，调用方不再各自拼三字段；degraded 不改变空授予=本地。
        from app.identity.base import FeishuGrant
        self.assertFalse(FeishuGrant().is_authoritative())
        self.assertFalse(FeishuGrant(degraded=True).is_authoritative())
        self.assertTrue(FeishuGrant(access_role="viewer").is_authoritative())
        self.assertTrue(FeishuGrant(knowledge_base_ids=["kb_public"]).is_authoritative())
        self.assertTrue(FeishuGrant(all_knowledge_bases=True).is_authoritative())

    def test_degraded_admin_narrowed_to_public(self):
        # 降级 ADMIN：本地 ROLE_ACCESS 的全库不再可见，请求 kb_hr 直接拒。
        from app.knowledge import allowed_for, public_kb_ids, resolve_for
        from app.identity.base import FeishuGrant
        user = self._user("ADMIN", FeishuGrant(knowledge_base_ids=public_kb_ids(), degraded=True))
        self.assertEqual(allowed_for(user), ["kb_public"])
        with self.assertRaises(PermissionError) as denied:
            resolve_for(user, "kb_hr")
        self.assertEqual(str(denied.exception), "当前账号无权访问该知识库")

    def test_promoted_viewer_reaches_granted_kb_only(self):
        from app.knowledge import allowed_for, resolve_for, visible_for
        from app.identity.base import FeishuGrant
        user = self._user("VIEWER", FeishuGrant(access_role="user", knowledge_base_ids=["kb_hr"]))
        self.assertEqual(allowed_for(user), ["kb_hr"])          # 本地 kb_public 被授予范围取代
        self.assertEqual(resolve_for(user, "kb_hr"), ["kb_hr"])
        self.assertEqual([base["id"] for base in visible_for(user)], ["kb_hr"])
        with self.assertRaises(PermissionError):
            resolve_for(user, "kb_product")

    def test_all_knowledge_bases_grant_sees_every_kb_in_definition_order(self):
        from app.knowledge import KNOWLEDGE_BASES, allowed_for
        from app.identity.base import FeishuGrant
        user = self._user("VIEWER", FeishuGrant(access_role="user", knowledge_base_ids=["*"],
                                                all_knowledge_bases=True))
        self.assertEqual(allowed_for(user), list(KNOWLEDGE_BASES.keys()))

    def test_granted_ids_are_intersected_in_definition_order(self):
        from app.knowledge import allowed_for
        from app.identity.base import FeishuGrant
        # 授予里写脏 id（未知/重复/逆序）都不能变成可见范围或打乱展示序。
        user = self._user("USER", FeishuGrant(knowledge_base_ids=["kb_hr", "kb_ghost", "kb_public", "kb_hr"]))
        self.assertEqual(allowed_for(user), ["kb_public", "kb_hr"])

    def test_role_only_grant_has_no_knowledge_scope(self):
        # access_role 只决定平台能力，知识范围只由 kb_ids/all 决定：只给角色 = 零可见，fail closed。
        from app.knowledge import allowed_for, resolve_for, visible_for
        user = self._user("ADMIN", FeishuGrant(access_role="admin"))
        self.assertEqual(allowed_for(user), [])
        self.assertEqual(visible_for(user), [])
        # 零可见对"全部库"的入口（None / "" / all）同样是拒绝——C1 的原始症状就是它返回全库。
        for requested in (None, "", "all"):
            with self.assertRaises(PermissionError) as denied:
                resolve_for(user, requested)
            self.assertEqual(str(denied.exception), "当前账号无知识库访问权限")
        with self.assertRaises(PermissionError) as denied:
            resolve_for(user, "kb_public")
        self.assertEqual(str(denied.exception), "当前账号无知识库访问权限")

    def test_all_dirty_grant_ids_collapse_to_zero_visibility(self):
        # 规则只写了未注册的库（含 "*" 之外的脏 id）→ 交集后为空 = 零可见，
        # 绝不能因为"白名单没东西可比"而落回本地 ADMIN 的全库。
        from app.knowledge import allowed_for, resolve_for
        user = self._user("ADMIN", FeishuGrant(access_role="admin",
                                              knowledge_base_ids=["kb_ghost", "kb_removed"]))
        self.assertEqual(allowed_for(user), [])
        for requested in (None, "all", "kb_public"):
            with self.assertRaises(PermissionError):
                resolve_for(user, requested)

    def test_visible_for_follows_definition_order_not_rule_order(self):
        # M2：展示序只由 KNOWLEDGE_BASES 决定——重排 ROLE_ACCESS（或授予列表）不该改变响应形状。
        import app.knowledge as knowledge
        baseline = [base["id"] for base in knowledge.visible_for(self._user("SALES"))]
        saved = list(knowledge.ROLE_ACCESS["SALES"])
        try:
            knowledge.ROLE_ACCESS["SALES"] = list(reversed(saved))
            self.assertEqual([base["id"] for base in knowledge.visible_for(self._user("SALES"))],
                             baseline)
        finally:
            knowledge.ROLE_ACCESS["SALES"] = saved

    def test_agent_tools_endpoint_follows_grant(self):
        from app.agent_routes import list_tools
        from app.identity.base import FeishuGrant
        plain = self._user("VIEWER")
        self.assertEqual(list_tools(mode="auto", user=plain)["allowed_knowledge_base_ids"], ["kb_public"])
        granted = self._user("VIEWER", FeishuGrant(access_role="user", knowledge_base_ids=["kb_sales"]))
        self.assertEqual(list_tools(mode="auto", user=granted)["allowed_knowledge_base_ids"], ["kb_sales"])

    def test_retrieval_tool_takes_injected_grant_scope(self):
        # 工具层不再自行按 role 判库：白名单由调用方注入，且必须显式注入（见下方必填断言）。
        source = (BACKEND_DIR / "app" / "tools" / "enterprise_search.py").read_text(encoding="utf-8")
        self.assertIn("context.role, requested, allowed=context.allowed_knowledge_base_ids", source)
        # 每请求解析一次：工具内不得再自行计算/改写范围。
        self.assertEqual(source.count("allowed_knowledge_base_ids"), 1)
        self.assertNotIn("allowed_for(", source)

    def test_enterprise_search_scope_comes_from_context_not_role(self):
        # 检索工具是真正的取数关口：授予收窄要挡住越权请求，授予提权要放开被授予的库。
        from app import retrieval as retrieval_module
        from app.tools.base import ToolContext, ToolExecutionError
        from app.tools.enterprise_search import execute_enterprise_search

        calls: list[dict] = []
        saved = retrieval_module.retrieval_service.search_with_timings
        retrieval_module.retrieval_service.search_with_timings = (
            lambda query, **kwargs: calls.append(kwargs) or ([], {}))
        try:
            narrowed_admin = ToolContext(username="u", role="ADMIN", mode="auto", trace_id="t",
                                         allowed_knowledge_base_ids=["kb_public"])
            with self.assertRaises(ToolExecutionError) as box:
                execute_enterprise_search({"query": "问题", "knowledge_base_id": "kb_hr"},
                                          narrowed_admin)
            self.assertEqual(box.exception.status, "DENIED")
            self.assertEqual(calls, [])          # 越权请求根本不该触达检索

            promoted_viewer = ToolContext(username="u", role="VIEWER", mode="auto", trace_id="t",
                                          allowed_knowledge_base_ids=["kb_hr"])
            execute_enterprise_search({"query": "问题", "knowledge_base_id": "kb_hr"},
                                      promoted_viewer)
            self.assertEqual([c["knowledge_base_ids"] for c in calls], [["kb_hr"]])
        finally:
            retrieval_module.retrieval_service.search_with_timings = saved

    def test_enterprise_search_denies_empty_grant_scope_instead_of_full_corpus(self):
        # C1 的 agent 侧症状：role-only 授予（白名单 = []）过去会把全部库交给检索。
        # `[]`（零可见）与 `None`（本请求无授予 → 本地 role）必须是两条不同的路。
        from app import retrieval as retrieval_module
        from app.knowledge import KNOWLEDGE_BASES
        from app.tools.base import ToolContext, ToolExecutionError
        from app.tools.enterprise_search import execute_enterprise_search

        calls: list[dict] = []
        saved = retrieval_module.retrieval_service.search_with_timings
        retrieval_module.retrieval_service.search_with_timings = (
            lambda query, **kwargs: calls.append(kwargs) or ([], {}))
        try:
            zero_scope_admin = ToolContext(username="u", role="ADMIN", mode="auto", trace_id="t",
                                           allowed_knowledge_base_ids=[])
            for arguments in ({"query": "问题"},                                # 未指定库 = all
                              {"query": "问题", "knowledge_base_id": "all"},
                              {"query": "问题", "knowledge_base_id": "kb_public"}):
                with self.assertRaises(ToolExecutionError) as box:
                    execute_enterprise_search(arguments, zero_scope_admin)
                self.assertEqual(box.exception.status, "DENIED")
                self.assertEqual(str(box.exception), "当前账号无知识库访问权限")
            self.assertEqual(calls, [])          # 零可见用户一次都不该触达向量层

            local_admin = ToolContext(username="u", role="ADMIN", mode="auto", trace_id="t",
                                      allowed_knowledge_base_ids=None)
            execute_enterprise_search({"query": "问题"}, local_admin)
            self.assertEqual([c["knowledge_base_ids"] for c in calls],
                             [list(KNOWLEDGE_BASES.keys())])   # 显式 None 才回到本地全库
        finally:
            retrieval_module.retrieval_service.search_with_timings = saved


class EmptyScopeIsNotFullCorpusTests(unittest.TestCase):
    """C1 第 2 层（纵深）：下游两道 falsy 判定都必须把 `None` 与 `[]` 分开。

    上游 `resolve_for` 已经拒绝空白名单；这里守的是"就算上游漏了，向量层与缓存键也不给全库"。
    """

    def test_kb_filter_distinguishes_none_from_empty_list(self):
        from app.store import VectorStore
        self.assertIsNone(VectorStore._kb_filter(None))
        empty = VectorStore._kb_filter([])
        self.assertIsNotNone(empty)
        self.assertNotEqual(empty, VectorStore._kb_filter(None))
        condition = empty.must[0]
        self.assertEqual(condition.key, "knowledge_base_id")
        self.assertEqual(list(condition.match.any), [])   # 空 MatchAny：对任何 point 都不成立
        self.assertNotEqual(VectorStore._kb_filter(["kb_public"]).model_dump(), empty.model_dump())

    def test_scope_key_does_not_fold_empty_scope_into_full_corpus(self):
        from app.retrieval import RetrievalService
        self.assertEqual(RetrievalService._scope_key(None), ("*",))
        self.assertEqual(RetrievalService._scope_key([]), ())
        self.assertNotEqual(RetrievalService._scope_key([]), RetrievalService._scope_key(None))

    def test_empty_scope_filter_returns_zero_rows_and_others_theirs(self):
        # 不靠推测：直接对着 Qdrant 的过滤实现验一次"空 MatchAny == 命中零行"。
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams
        from app.store import VectorStore
        client = QdrantClient(":memory:")
        client.create_collection("kb-scope-probe",
                                 vectors_config=VectorParams(size=2, distance=Distance.COSINE))
        client.upsert("kb-scope-probe", points=[
            PointStruct(id=1, vector=[1.0, 0.0], payload={"knowledge_base_id": "kb_public"}),
            PointStruct(id=2, vector=[1.0, 0.0], payload={"knowledge_base_id": "kb_hr"}),
        ], wait=True)

        def hits(knowledge_base_ids):
            points = client.query_points(
                "kb-scope-probe", query=[1.0, 0.0],
                query_filter=VectorStore._kb_filter(knowledge_base_ids), limit=5,
            ).points
            return sorted(int(point.id) for point in points)

        self.assertEqual(hits(None), [1, 2])      # 不加过滤只属于 None
        self.assertEqual(hits([]), [])            # 零可见 = 一行都不给
        self.assertEqual(hits(["kb_hr"]), [2])
        scrolled, _ = client.scroll("kb-scope-probe",
                                    scroll_filter=VectorStore._kb_filter([]), limit=5)
        self.assertEqual(scrolled, [])            # scroll 与 query_points 同一条过滤路径


class ToolContextScopeGuardTests(unittest.TestCase):
    """I1：白名单入参必填 + 全仓扫描每个 `ToolContext(` 调用点都把它写出来。"""

    def test_construction_requires_the_scope_argument(self):
        from app.tools.base import ToolContext
        with self.assertRaises(TypeError) as raised:
            ToolContext(username="u", role="ADMIN", mode="auto", trace_id="t")
        self.assertIn("allowed_knowledge_base_ids", str(raised.exception))
        # 本地语义也要显式声明：None 是"本请求没有有效授予"，不是可以忘记的默认值。
        self.assertIsNone(ToolContext(username="u", role="ADMIN", mode="auto", trace_id="t",
                                      allowed_knowledge_base_ids=None).allowed_knowledge_base_ids)

    def test_every_tool_context_call_site_passes_the_scope(self):
        sites = [(path, source) for path, source in _python_sources(BACKEND_DIR / "app")
                 if "ToolContext(" in source]
        names = {str(path.relative_to(BACKEND_DIR).as_posix()) for path, _ in sites}
        # 扫描必须真的命中两个注入点，否则这条护栏会退化成空断言。
        self.assertTrue({"app/agent.py", "app/conversation_agent.py"} <= names, names)
        for path, source in sites:
            calls = _call_expressions(source, "ToolContext(")
            self.assertTrue(calls, path.name)
            for call in calls:
                with self.subTest(file=path.relative_to(BACKEND_DIR).as_posix()):
                    self.assertIn("allowed_knowledge_base_ids=", call)


def _python_sources(directory: Path):
    """Yield `(path, source)` for every python file under `directory`."""
    for path in sorted(directory.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path, path.read_text(encoding="utf-8")


def _call_expressions(source: str, marker: str) -> list[str]:
    """Bracket-matched text of every `marker(...)` call in `source`."""
    found: list[str] = []
    cursor = 0
    while True:
        start = source.find(marker, cursor)
        if start < 0:
            return found
        depth = 0
        for position in range(start + len(marker) - 1, len(source)):
            if source[position] == "(":
                depth += 1
            elif source[position] == ")":
                depth -= 1
                if depth == 0:
                    found.append(source[start:position + 1])
                    break
        cursor = start + len(marker)


# ---------- 检索调用点扫描（终审护栏升级）----------

# 真正"读库内容"的调用：检索服务的 search/search_with_timings，与向量层的 vector_search/all_chunks
# （`store.search` 这一类别名一起收，靠方法名 + 接收者名识别，不靠具体 import 写法）。
_RETRIEVAL_RECEIVERS = {"retrieval_service", "retrieval", "vector_store", "store"}
_RETRIEVAL_METHODS = {"search", "search_with_timings", "vector_search", "all_chunks"}
# 范围判定的权威入口（`knowledge.py`）：调用点必须落到其中之一，或落到"包了它们并传 user"的本模块包装。
_SCOPE_AUTHORITIES = {"allowed_for", "resolve_for", "resolve_requested", "visible_for"}
# 判定主体：HTTP 链路是 `user`，工具链路是注入了白名单的 `context`。
_SCOPE_PRINCIPAL = re.compile(r"\b(user|context)\b")
# 不是"用户取数入口"的文件：向量层自身（纵深在 `_kb_filter` / `_scope_key`）与演示数据装载。
_RETRIEVAL_SITE_ALLOWLIST = {
    "app/retrieval.py": "检索实现：knowledge_base_ids 是它的入参，范围由调用方折算后传入",
    "app/store.py": "向量层实现：`_kb_filter` 是 C1 第 2 层纵深，这里没有用户上下文",
    "app/demo.py": "演示数据装载：initialize/reset 跨全库统计 chunk，属于 system:operate 管理动作",
}
# 扫描必须真的覆盖到这些入口文件（终审前 main.py 根本不在扫描集里）。
_RETRIEVAL_ENTRYPOINT_FILES = {"app/main.py", "app/knowledge_os.py", "app/tools/enterprise_search.py"}


def _dotted(node: ast.expr) -> str:
    """`a.b.c` 形式的点号名；下标、调用等复杂表达式返回空串。"""
    if isinstance(node, ast.Attribute):
        parent = _dotted(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _call_leaf(call: ast.Call) -> str:
    return _dotted(call.func).rsplit(".", 1)[-1]


def _is_retrieval_call(call: ast.Call) -> bool:
    parts = _dotted(call.func).split(".")
    return len(parts) >= 2 and parts[-2] in _RETRIEVAL_RECEIVERS and parts[-1] in _RETRIEVAL_METHODS


def _scope_authorities_for(tree: ast.Module) -> set[str]:
    """权威入口 + 本模块里只是"再包一层做审计/HTTP 映射"的函数名（`main._allowed_ids`、
    `knowledge_os._scope`）。包装函数按"函数体直接调用权威入口"识别，所以新增一个包装
    不需要改这份测试；但把范围判定自己实现一遍（不碰权威入口）就照旧会红。"""
    names = set(_SCOPE_AUTHORITIES)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(isinstance(call, ast.Call) and _call_leaf(call) in _SCOPE_AUTHORITIES
               for call in ast.walk(node)):
            names.add(node.name)
    return names


def _user_scoped_calls(func: ast.AST, authorities: set[str]) -> list[str]:
    """`func` 内"把当前用户折算成知识范围"的调用源码列表。"""
    found: list[str] = []
    for call in ast.walk(func):
        if not (isinstance(call, ast.Call) and _call_leaf(call) in authorities):
            continue
        arguments = [ast.unparse(a) for a in call.args]
        arguments += [ast.unparse(keyword.value) for keyword in call.keywords]
        if _SCOPE_PRINCIPAL.search(" ".join(arguments)):
            found.append(ast.unparse(call))
    return found


def _retrieval_sites(source: str):
    """yield `(外层函数或 None, 该函数内的检索调用列表, 权威入口集合)`。"""
    tree = ast.parse(source)
    authorities = _scope_authorities_for(tree)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    grouped: list[list] = []
    index: dict[int, list] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_retrieval_call(node)):
            continue
        owner = parents.get(node)
        while owner is not None and not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = parents.get(owner)
        key = id(owner)
        if key not in index:
            index[key] = [owner, []]
            grouped.append(index[key])
        index[key][1].append(node)
    for owner, calls in grouped:
        yield owner, calls, authorities


class RetrievalCallSiteScopeGuardTests(unittest.TestCase):
    """终审护栏升级：调用点扫描从"枚举几个 legacy 串"改成"从真的在取数的调用点反推"。

    扫描 `backend/app/**/*.py` 里每一个 `retrieval_service.search*` / `store.search*` 类检索调用，
    要求该调用所在函数把知识库范围折算自当前用户（权威入口或其包装）。
    main.py 一并进扫描集——终审 I-1 的漏网之鱼正是它里面的 `/api/evaluation/run`。
    """

    def sites(self):
        found = []
        for path, source in _python_sources(BACKEND_DIR / "app"):
            rel = path.relative_to(BACKEND_DIR).as_posix()
            for owner, calls, authorities in _retrieval_sites(source):
                found.append((rel, owner, calls, authorities))
        return found

    def test_scan_actually_covers_every_entrypoint_file(self):
        found = self.sites()
        self.assertTrue(found, "一个检索调用点都没扫到 = 这条护栏已经退化成空断言")
        scanned = {rel for rel, _, _, _ in found}
        self.assertEqual(scanned - set(_RETRIEVAL_SITE_ALLOWLIST), _RETRIEVAL_ENTRYPOINT_FILES,
                         "取数入口文件集合变了：新增入口要进护栏，删入口要改这里")
        self.assertIn("app/main.py", scanned)
        self.assertTrue(any(rel == "app/main.py" and owner is not None
                            and owner.name == "run_evaluation" for rel, owner, _, _ in found),
                        "评测路由的检索调用点必须留在扫描范围内")

    def test_every_retrieval_call_site_derives_scope_from_the_user(self):
        for rel, owner, calls, authorities in self.sites():
            if rel in _RETRIEVAL_SITE_ALLOWLIST:
                continue
            name = owner.name if owner is not None else "<module>"
            with self.subTest(site=f"{rel}:{name}"):
                self.assertIsNotNone(owner, f"{rel}: 检索调用点不在函数内，判不出范围来源")
                scoped = _user_scoped_calls(owner, authorities)
                self.assertTrue(
                    scoped,
                    f"{rel}:{name} 直接取数，却没把知识库范围折算自当前用户（应调用 "
                    f"allowed_for/resolve_for 或其传 user 的包装）",
                )
                for call in calls:
                    # 范围必须真的传给检索层：不传 `knowledge_base_ids` 等于把全库交给它。
                    self.assertIn("knowledge_base_ids", ast.unparse(call), f"{rel}:{name}")

    def test_no_by_role_scope_call_anywhere_in_the_package(self):
        # legacy「按 role 判库」调用：过去只在 6 个文件里逐串比对，现在整个包扫，
        # 唯一豁免是权威定义点 `knowledge.py`（无授予时正是它落回本地 `ROLE_ACCESS`）。
        legacy = ("allowed_ids(user.role)", "visible_bases(user.role)", "resolve_requested(user.role")
        for path, source in _python_sources(BACKEND_DIR / "app"):
            rel = path.relative_to(BACKEND_DIR).as_posix()
            if rel == "app/knowledge.py":
                continue
            for stale in legacy:
                with self.subTest(site=rel, needle=stale):
                    self.assertNotIn(stale, source)


class _ModuleAuditSpy:
    """按模块名拦截 `record_event`。

    main / knowledge_os 在文件顶部 `from app.audit import record_event`，绑的是自己那份名字，
    只 patch `app.audit.record_event` 打不到它们——必须打消费方的属性。
    """

    def __init__(self, module_name: str):
        self.module_name = module_name

    def __enter__(self):
        import importlib
        self.module = importlib.import_module(self.module_name)
        self.saved = getattr(self.module, "record_event")
        self.events: list[dict] = []
        setattr(self.module, "record_event", lambda **kwargs: self.events.append(kwargs))
        return self

    def __exit__(self, *exc):
        setattr(self.module, "record_event", self.saved)


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
        with _ModuleAuditSpy("app.main") as audit:
            with self.assertRaises(HTTPException) as box:
                _allowed_ids(user, "kb_hr")
        self.assertEqual(box.exception.status_code, 403)
        # 审计包装仍是 main 的职责：拒绝一行 ACCESS/DENIED，文案与改造前逐字一致。
        self.assertEqual([(e["action"], e["status"], e["knowledge_base_id"]) for e in audit.events],
                         [("ACCESS", "DENIED", "kb_hr")])
        self.assertEqual(audit.events[0]["detail"], "当前账号无权访问该知识库")

    def test_unknown_kb_with_grant_still_404(self):
        from app.auth import CurrentUser
        from app.identity.base import FeishuGrant
        from app.main import _allowed_ids
        user = CurrentUser(username="u", display_name="U", role="ADMIN",
                           grant=FeishuGrant(knowledge_base_ids=["kb_public"]))
        with _ModuleAuditSpy("app.main") as audit:
            with self.assertRaises(HTTPException) as box:
                _allowed_ids(user, "kb_nope")
        self.assertEqual(box.exception.status_code, 404)
        self.assertEqual(box.exception.detail, "知识库不存在")
        self.assertEqual(audit.events, [])   # 404 不是越权事件，不该留 DENIED 痕迹

    def test_empty_grant_scope_on_all_scope_is_audited_403(self):
        # C1 的原始复现路径：`/api/query`、`/api/stats` 等"未指定库/全部库"入口对
        # 零可见用户必须 403 + 一行 ACCESS/DENIED，而不是返回 5 个库的内容。
        from app.auth import CurrentUser
        from app.identity.base import FeishuGrant
        from app.main import _allowed_ids
        user = CurrentUser(username="u", display_name="U", role="ADMIN",
                           grant=FeishuGrant(access_role="admin"))
        for requested in (None, "all"):
            with _ModuleAuditSpy("app.main") as audit:
                with self.assertRaises(HTTPException) as box:
                    _allowed_ids(user, requested)
            self.assertEqual(box.exception.status_code, 403)
            self.assertEqual(box.exception.detail, "当前账号无知识库访问权限")
            self.assertEqual([(e["action"], e["status"], e["knowledge_base_id"])
                              for e in audit.events], [("ACCESS", "DENIED", requested)])

    def test_knowledge_bases_endpoint_follows_grant(self):
        from app.auth import CurrentUser
        from app.knowledge import visible_bases
        from app.identity.base import FeishuGrant
        from app.main import knowledge_bases
        granted = CurrentUser(username="u", display_name="U", role="HR",
                              grant=FeishuGrant(knowledge_base_ids=["kb_service"]))
        self.assertEqual([b["id"] for b in knowledge_bases(user=granted)["knowledge_bases"]],
                         ["kb_service"])
        # 无授予：响应与改造前逐字相同（本地 role 语义没被动过）。
        plain = CurrentUser(username="u", display_name="U", role="HR")
        self.assertEqual(knowledge_bases(user=plain)["knowledge_bases"], visible_bases("HR"))


class EvaluationScopeGuardTests(unittest.TestCase):
    """I-1：`/api/evaluation/run` 的 `knowledge_base_id` 来自 `eval_dataset.json` 而非请求参数，
    但它同样把库内容读进响应——是取数入口，就必须先过用户范围再开始跑。"""

    def _user(self, role, grant=None):
        from app.auth import CurrentUser
        return CurrentUser(username="u", display_name="U", role=role, grant=grant)

    def _call_route(self, user, calls: list, events: list):
        """只调路由函数本身（不起 TestClient）：检索、落盘、审计全打桩，异常原样抛出。"""
        import app.main as main
        import app.retrieval as retrieval_module
        from app.main import EvaluationRequest

        saved = (retrieval_module.retrieval_service.search_with_timings,
                 main.persist_eval_run, main.record_event)

        def fake_search(query, **kwargs):
            calls.append(kwargs.get("knowledge_base_ids"))
            return [], {}

        retrieval_module.retrieval_service.search_with_timings = fake_search
        main.persist_eval_run = lambda **kwargs: {"run_id": "run-under-test"}
        main.record_event = lambda **kwargs: events.append(kwargs)
        try:
            return main.run_evaluation(EvaluationRequest(modes=["vector"], top_k=1), user)
        finally:
            (retrieval_module.retrieval_service.search_with_timings,
             main.persist_eval_run, main.record_event) = saved

    def test_dataset_scope_helper_deduplicates_in_file_order(self):
        from app.main import _dataset_knowledge_base_ids
        self.assertEqual(
            _dataset_knowledge_base_ids([{"knowledge_base_id": "kb_hr"},
                                         {"knowledge_base_id": "kb_public"},
                                         {"knowledge_base_id": "kb_hr"}]),
            ["kb_hr", "kb_public"])          # 每个 distinct 库判一次，重复行不重复判

    def test_narrowed_admin_is_denied_before_any_retrieval(self):
        # 数据集含 kb_hr，授予只有 kb_public → 403 + 恰好一行 ACCESS/DENIED，且检索一次都没被触达。
        from app.identity.base import FeishuGrant
        calls: list = []
        events: list = []
        with self.assertRaises(HTTPException) as box:
            self._call_route(self._user("ADMIN", FeishuGrant(knowledge_base_ids=["kb_public"])),
                             calls, events)
        self.assertEqual(box.exception.status_code, 403)
        self.assertEqual(box.exception.detail, "当前账号无权访问该知识库")
        self.assertEqual(calls, [])                                   # 未通过范围校验就不开始跑
        denied = [(e["action"], e["status"], e["knowledge_base_id"]) for e in events]
        self.assertEqual(len(denied), 1)                              # 第一个越权库即失败，不刷审计
        self.assertEqual(denied[0][:2], ("ACCESS", "DENIED"))
        self.assertNotIn(denied[0][2], {"kb_public", None})            # 报的是被授予范围外的库

    def test_full_scope_runners_still_complete(self):
        # 反向：被授予全库、以及无授予的本地 ADMIN，跑完整数据集都不该被这道守卫挡住。
        import json as _json
        from app.identity.base import FeishuGrant
        dataset_size = len(_json.loads(
            (BACKEND_DIR / "eval_dataset.json").read_text(encoding="utf-8")))
        all_grant = FeishuGrant(access_role="admin", knowledge_base_ids=["*"],
                                all_knowledge_bases=True)
        for label, user in (("granted", self._user("ADMIN", all_grant)),
                            ("local", self._user("ADMIN"))):
            with self.subTest(user=label):
                calls: list = []
                events: list = []
                result = self._call_route(user, calls, events)
                self.assertEqual(result["dataset_size"], dataset_size)
                self.assertEqual(len(calls), dataset_size)            # 每条用例都在被授予范围内跑
                self.assertEqual([e["action"] for e in events], ["EVALUATION"])


class ConversationScopeWiringTests(unittest.TestCase):
    """裁决 D 第 4 点：对话链路的授权集合随 grant（函数级断言，不起 TestClient）。"""

    def _user(self, role, grant=None):
        from app.auth import CurrentUser
        return CurrentUser(username="u", display_name="U", role=role, grant=grant)

    def _conversation(self, kb_id):
        return {"id": "c1", "messages": [{"role": "assistant", "content": "答案", "sources": [
            {"source_type": "enterprise", "knowledge_base_id": kb_id, "title": "文档"}]}]}

    def test_validate_scope_follows_grant(self):
        from app.conversation_routes import _validate_knowledge_base_scope
        from app.identity.base import FeishuGrant
        degraded_admin = self._user("ADMIN", FeishuGrant(knowledge_base_ids=["kb_public"]))
        with self.assertRaises(HTTPException) as box:
            _validate_knowledge_base_scope(degraded_admin, "kb_hr")
        self.assertEqual(box.exception.status_code, 403)
        self.assertEqual(box.exception.detail, "当前账号无权访问该知识库")
        # 同一 user 请求授予内库与 all 都必须放行
        _validate_knowledge_base_scope(degraded_admin, "kb_public")
        _validate_knowledge_base_scope(degraded_admin, None)
        # 无授予的本地 ADMIN 仍是全库（本任务没改动本地语义）
        _validate_knowledge_base_scope(self._user("ADMIN"), "kb_hr")

    def test_sanitizer_hides_answers_outside_grant(self):
        from app.conversation_routes import _sanitize_conversation_for_user
        from app.identity.base import FeishuGrant
        conversation = self._conversation("kb_hr")
        narrowed = self._user("ADMIN", FeishuGrant(knowledge_base_ids=["kb_public"]))
        sanitized = _sanitize_conversation_for_user(conversation, narrowed)["messages"][0]
        self.assertTrue(sanitized["redacted"])
        self.assertEqual(sanitized["content"], "该历史回答涉及当前无权访问的知识，已隐藏。")
        self.assertEqual(sanitized["sources"], [])
        # 提权 VIEWER 看得到被授予的库；同一条对本地 ADMIN 原样可见。
        promoted = self._user("VIEWER", FeishuGrant(access_role="user", knowledge_base_ids=["kb_hr"]))
        for user in (promoted, self._user("ADMIN")):
            kept = _sanitize_conversation_for_user(conversation, user)["messages"][0]
            self.assertNotIn("redacted", kept)
            self.assertEqual([s["knowledge_base_id"] for s in kept["sources"]], ["kb_hr"])
        self.assertEqual(conversation["messages"][0]["sources"][0]["knowledge_base_id"], "kb_hr")

    def test_every_call_site_uses_the_grant_aware_entrypoint(self):
        # 收口点必须真的接上新入口（而不是只把旧调用删掉），且热路径每请求解析一次即可。
        # 「全链路再出现按 role 判库」这一半已升级为按调用点驱动，见
        # `RetrievalCallSiteScopeGuardTests`（它扫整个 app 包，不再枚举文件清单）。
        entrypoints = {
            "main.py": ("resolve_for(user, knowledge_base_id)", "visible_for(user)"),
            "conversation_routes.py": ("resolve_for(user, knowledge_base_id)", "allowed_for(user)"),
            "knowledge_os.py": ("resolve_for(user, knowledge_base_id)",),
            "agent_routes.py": ("allowed_for(user)",),
            "agent.py": ("allowed_for(user)", "allowed_knowledge_base_ids=grant_scope"),
            "conversation_agent.py": ("allowed_for(user)", "allowed_knowledge_base_ids=grant_scope"),
        }
        for name, required in entrypoints.items():
            source = (BACKEND_DIR / "app" / name).read_text(encoding="utf-8")
            for needle in required:
                self.assertIn(needle, source, name)
            # 热路径每请求解析一次即可：不允许按 chunk/逐库重复判定。
            self.assertLessEqual(source.count("allowed_for(user)"), 1, name)
        for name in ("agent.py", "conversation_agent.py"):
            # 工具上下文拿的是同一份 grant 白名单，且只算一次。
            source = (BACKEND_DIR / "app" / name).read_text(encoding="utf-8")
            self.assertEqual(source.count("effective_allowed_from_grant(user.grant)"), 1, name)


def _saved_identity_state():
    """存下 identity 包与飞书相关的全部可变态，供 setUp/tearDown 成对还原。"""
    import app.identity as identity
    from app.config import settings

    return (settings.feishu_permissions_enabled, settings.feishu_app_id,
            settings.feishu_app_secret, settings.feishu_rules_file,
            identity._resolver, identity.get_resolver)


def _restore_identity_state(state) -> None:
    import app.identity as identity
    from app.config import settings

    settings.feishu_permissions_enabled = state[0]
    settings.feishu_app_id = state[1]
    settings.feishu_app_secret = state[2]
    settings.feishu_rules_file = state[3]
    identity._resolver = state[4]
    identity.get_resolver = state[5]


class StrictRuleSchemaTests(unittest.TestCase):
    """护栏 7：规则模型 `extra="forbid"` —— 拼错的键拒载，不静默忽略成"这条规则没写"。"""

    def test_unknown_grant_key_rejects_load(self):
        # 最典型的配置事故：access_role 写成 access_roles。静默忽略的结果是
        # "规则命中了却永远不给角色"，运维从响应上完全看不出来。
        path = write_rules({"rules": [{"match": {"department_ids": ["od-hr"]},
                                       "grant": {"access_roles": "user"}}]})
        with self.assertRaises(ValueError) as raised:
            load_rule_set(path)
        self.assertIn("access_roles", str(raised.exception))
        self.assertIn(path, str(raised.exception))     # 报错必须指名是哪个文件

    def test_unknown_match_key_rejects_load(self):
        # 与一个合法键并存才测得准：只写错键时"空 match"那道校验会先拦下来，
        # forbid 形同没生效也照样绿（变异自查 X5 真实踩到过）。
        path = write_rules({"rules": [{"match": {"department_ids": ["od-hr"],
                                                 "department_id": ["od-typo"]},
                                       "grant": {"access_role": "user"}}]})
        with self.assertRaises(ValueError) as raised:
            load_rule_set(path)
        self.assertIn("department_id", str(raised.exception))

    def test_unknown_rule_key_rejects_load(self):
        # 与 match/grant 平级的拼错键（写成 when）会让整条规则既无匹配也无授予。
        path = write_rules({"rules": [{"match": {"department_ids": ["od-hr"]},
                                       "grant": {"access_role": "user"},
                                       "when": "工作时间"}]})
        with self.assertRaises(ValueError):
            load_rule_set(path)

    def test_unknown_top_level_key_rejects_load(self):
        path = write_rules({"rules": [], "default_role": "viewer"})
        with self.assertRaises(ValueError):
            load_rule_set(path)

    def test_shipped_rules_file_still_loads(self):
        # forbid 不能顺手把仓库里那份示例规则打死。
        rule_set = load_rule_set(str(BACKEND_DIR / "config" / "feishu_permissions.json"))
        self.assertTrue(rule_set.rules)
        self.assertTrue(all(not rule.match.is_empty() for rule in rule_set.rules))


class WarmupGateTests(unittest.TestCase):
    """护栏 1：`enabled=True` 时启动即装配一次并加载规则；坏文件必须让启动失败（fail-fast）。"""

    def setUp(self):
        import app.identity as identity
        from app.config import settings

        self.identity = identity
        self.state = _saved_identity_state()
        self.assembly_calls: list[int] = []
        # cwd 收口（Task 9 段 A / T5 N3 同族）：本类的 `_run_startup_lifespan` 真跑 app 的
        # lifespan，而 V2.3 的 `llm.warmup()` 挂在 lifespan 上、读的是 §12 的**相对**默认
        # `config/llm_registry.json` ⇒ 从仓库根起进程就是
        # `RegistryError: LLM 注册表文件不可用`（Task 5 的接线把这个既有 cwd 耦合显性化了）。
        # 修法与本文件既有的 `_set_rules` 同一手法：把配置键指到**绝对**的出厂文件——
        # 不动 §12 的冻结默认值，也不放宽本类的任何断言。
        self._registry_file = settings.llm_registry_file
        settings.llm_registry_file = str(BACKEND_DIR / "config" / "llm_registry.json")

    def tearDown(self):
        from app.config import settings

        settings.llm_registry_file = self._registry_file
        _restore_identity_state(self.state)

    def _forbid_assembly(self):
        self.assembly_calls.append(1)
        raise AssertionError("这条路径不得装配 resolver（会创建真飞书客户端并外呼）")

    def _set_rules(self, payload: dict | None = None, *, path: str | None = None) -> None:
        from app.config import settings

        settings.feishu_rules_file = path if path is not None else write_rules(payload or {"rules": [
            {"match": {"department_names": ["人力资源"]},
             "grant": {"access_role": "user", "knowledge_base_ids": ["kb_hr"]}}]})

    def _run_startup_lifespan(self) -> object:
        """真的走一遍 app 的启动生命周期（不启服务、不发请求）。"""
        import asyncio

        from app.main import app

        async def scenario():
            async with app.router.lifespan_context(app):
                return "started"

        return asyncio.run(scenario())

    def test_disabled_warmup_is_a_no_op(self):
        from app.config import settings

        settings.feishu_permissions_enabled = False
        self.identity.get_resolver = self._forbid_assembly
        self._set_rules(path="no-such-rules.json")     # 连文件都不该去看
        self.identity.reset_resolver()
        self.identity.warmup()
        self.assertEqual(self.assembly_calls, [])
        self.assertIsNone(self.identity._resolver)

    def test_enabled_warmup_assembles_exactly_once(self):
        from app.config import settings
        from app.identity.resolver import IdentityResolver

        settings.feishu_permissions_enabled = True
        self._set_rules()
        self.identity.reset_resolver()
        self.identity.warmup()
        built = self.identity._resolver
        self.assertIsInstance(built, IdentityResolver)
        self.identity.warmup()                          # 幂等：不重复装配
        self.assertIs(self.identity._resolver, built)

    def test_enabled_warmup_raises_on_unreadable_rules_file(self):
        from app.config import settings

        settings.feishu_permissions_enabled = True
        self._set_rules(path="no-such-rules.json")
        self.identity.reset_resolver()
        with self.assertRaises(ValueError):
            self.identity.warmup()
        # 坏配置不能留下半装配的单例，否则后续请求会拿到 None 再懒装配绕过门闸。
        self.assertIsNone(self.identity._resolver)

    def test_enabled_warmup_raises_on_empty_match_rules(self):
        from app.config import settings

        settings.feishu_permissions_enabled = True
        self._set_rules({"rules": [{"match": {}, "grant": {"access_role": "admin"}}]})
        self.identity.reset_resolver()
        with self.assertRaises(ValueError):
            self.identity.warmup()
        self.assertIsNone(self.identity._resolver)

    def test_startup_fails_fast_on_broken_rules(self):
        from app.config import settings

        settings.feishu_permissions_enabled = True
        self._set_rules({"rules": [{"match": {}, "grant": {"access_role": "admin"}}]})
        self.identity.reset_resolver()
        with self.assertRaises(ValueError):
            self._run_startup_lifespan()
        self.assertIsNone(self.identity._resolver)

    def test_startup_warms_the_resolver_on_valid_rules(self):
        from app.config import settings
        from app.identity.resolver import IdentityResolver

        settings.feishu_permissions_enabled = True
        self._set_rules()
        self.identity.reset_resolver()
        self.assertEqual(self._run_startup_lifespan(), "started")
        self.assertIsInstance(self.identity._resolver, IdentityResolver)

    def test_startup_is_a_no_op_when_disabled(self):
        from app.config import settings

        settings.feishu_permissions_enabled = False
        self._set_rules(path="no-such-rules.json")
        self.identity.get_resolver = self._forbid_assembly
        self.identity.reset_resolver()
        self.assertEqual(self._run_startup_lifespan(), "started")   # 默认关闭：启动零影响
        self.assertEqual(self.assembly_calls, [])

    def test_served_entrypoint_shares_the_same_gate(self):
        # uvicorn 实际跑的是 `app.main_agent:app`（Dockerfile CMD）。它复用同一个 app 实例，
        # 门闸必须一并生效——否则生产入口绕开启动校验，门闸就只是测试里的装饰。
        from app.main import app as base_app
        from app.main_agent import app as agent_app

        self.assertIs(agent_app, base_app)
        self.assertIs(agent_app.router.lifespan_context, base_app.router.lifespan_context)


class EndToEndGuardTests(unittest.TestCase):
    """brief Step 1：开关 → resolver → mapper → CurrentUser → 知识范围的一条完整链（零外呼）。"""

    HR_RULES = {"rules": [{"match": {"department_names": ["人力资源"]},
                           "grant": {"access_role": "user",
                                     "knowledge_base_ids": ["kb_hr"]}}]}

    def setUp(self):
        import app.identity as identity

        self.identity = identity
        self.state = _saved_identity_state()
        self.assembly_calls: list[int] = []

    def tearDown(self):
        _restore_identity_state(self.state)

    def _forbid_assembly(self):
        self.assembly_calls.append(1)
        raise AssertionError("本地语义下不得装配 resolver")

    def _resolver(self, rules_payload, client, *, clock=None):
        from app.identity.resolver import IdentityResolver

        path = write_rules(rules_payload)
        return IdentityResolver(client, load_rule_set(path), ttl_seconds=900, stale_seconds=86400,
                                failure_cache_seconds=60, clock=clock or _Clock())

    def _enable(self, resolver) -> None:
        from app.config import settings

        settings.feishu_permissions_enabled = True
        self.identity._resolver = resolver

    def _user(self, role, grant):
        from app.auth import CurrentUser

        return CurrentUser(username="staff", display_name="S", role=role, grant=grant)

    def test_disabled_chain_is_local_semantics_end_to_end(self):
        from app.config import settings
        from app.knowledge import allowed_for, resolve_for

        settings.feishu_permissions_enabled = False
        self.identity.get_resolver = self._forbid_assembly
        grant = self.identity.resolve_for_user("hr01", "HR", {"feishu_open_id": "ou_1"})
        self.assertIsNone(grant)
        self.assertEqual(self.assembly_calls, [])
        user = self._user("HR", grant)
        self.assertEqual(allowed_for(user), ["kb_public", "kb_hr"])
        self.assertEqual(resolve_for(user, "kb_hr"), ["kb_hr"])
        self.assertNotIn("grant", user.model_dump())

    def test_enabled_bridge_narrows_an_hr_account(self):
        from app.auth import enforce_permission
        from app.knowledge import allowed_for, resolve_for, visible_for

        self._enable(self._resolver(self.HR_RULES, FakeClient(departments=["od-hr"])))
        grant = self.identity.resolve_for_user("hr01", "HR", {"feishu_open_id": "ou_1"})
        self.assertIsNotNone(grant)
        self.assertFalse(grant.degraded)
        user = self._user("HR", grant)
        # 本地 HR 能看公共库+HR 库，授予里没写 kb_public → 收窄必须真的生效。
        self.assertEqual(allowed_for(user), ["kb_hr"])
        self.assertEqual([base["id"] for base in visible_for(user)], ["kb_hr"])
        self.assertEqual(resolve_for(user, "kb_hr"), ["kb_hr"])
        with self.assertRaises(PermissionError) as denied:
            resolve_for(user, "kb_public")
        self.assertEqual(str(denied.exception), "当前账号无权访问该知识库")
        # 角色也被接管：HR(user) → 授予 user，权限集合不变但来源换成授予。
        self.assertEqual(enforce_permission(user, "knowledge:query"), user)

    def test_enabled_bridge_promotes_a_viewer_to_every_base(self):
        from app.auth import enforce_permission
        from app.knowledge import KNOWLEDGE_BASES, allowed_for

        rules = {"rules": [
            {"match": {"department_names": ["人力资源"]},
             "grant": {"access_role": "user", "knowledge_base_ids": ["kb_hr"]}},
            {"match": {"chat_names": ["HR群"]},
             "grant": {"access_role": "admin", "knowledge_base_ids": ["*"]}},
        ]}
        client = FakeClient(departments=["od-hr"], chats=[ChatInfo("oc_hr", "HR群")],
                            members={"oc_hr": ["ou_1"]})
        self._enable(self._resolver(rules, client))
        grant = self.identity.resolve_for_user("viewer", "VIEWER", {"feishu_open_id": "ou_1"})
        self.assertEqual(grant.access_role, "admin")            # 多条命中取高
        self.assertTrue(grant.all_knowledge_bases)              # "*" 并集
        user = self._user("VIEWER", grant)
        self.assertEqual(allowed_for(user), list(KNOWLEDGE_BASES.keys()))
        self.assertIs(enforce_permission(user, "system:operate"), user)

    def test_record_without_open_id_never_reaches_the_provider(self):
        resolver = self._resolver(self.HR_RULES, FakeClient(departments=["od-hr"]))

        class Counting:
            def __init__(self, inner):
                self.inner = inner
                self.calls = 0

            def resolve(self, username, role, open_id):
                self.calls += 1
                return self.inner.resolve(username, role, open_id)

        spy = Counting(resolver)
        self._enable(spy)
        from app.config import settings
        from app.knowledge import allowed_for

        for record in ({}, {"feishu_open_id": ""}, {"feishu_open_id": None}):
            self.assertIsNone(self.identity.resolve_for_user("hr01", "HR", record))
        self.assertEqual(spy.calls, 0)
        self.assertEqual(allowed_for(self._user("HR", None)), ["kb_public", "kb_hr"])
        self.assertTrue(settings.feishu_permissions_enabled)

    def test_provider_outage_degrades_and_leaves_one_auditable_row(self):
        from app.knowledge import allowed_for, public_kb_ids

        self._enable(self._resolver(self.HR_RULES, FakeClient(fail=True)))
        with _AuditRecorder() as audit:
            grant = self.identity.resolve_for_user("hr01", "HR", {"feishu_open_id": "ou_1"})
        self.assertTrue(grant.degraded)
        self.assertIsNone(grant.access_role)                    # 角色回本地，不放大
        self.assertEqual(grant.knowledge_base_ids, public_kb_ids())
        self.assertEqual(allowed_for(self._user("HR", grant)), ["kb_public"])
        self.assertEqual([(e["action"], e["status"]) for e in audit.events],
                         [("FEISHU_PERMISSION", "DEGRADED")])
        self.assertEqual(audit.events[0]["username"], "hr01")
        self.assertEqual(audit.events[0]["role"], "HR")
        self.assertIn("down", audit.events[0]["detail"])        # 失败原因可查，不是空串

    def test_role_only_grant_end_to_end_is_zero_visibility(self):
        # C1 的原始症状在真实链路上的回归锚：规则只给角色不给库 → 零可见，不是全库。
        from app.knowledge import allowed_for, resolve_for

        rules = {"rules": [{"match": {"department_names": ["人力资源"]},
                            "grant": {"access_role": "admin"}}]}
        self._enable(self._resolver(rules, FakeClient(departments=["od-hr"])))
        grant = self.identity.resolve_for_user("admin", "ADMIN", {"feishu_open_id": "ou_1"})
        self.assertEqual(grant.access_role, "admin")
        user = self._user("ADMIN", grant)
        self.assertEqual(allowed_for(user), [])
        for requested in (None, "all", "kb_public"):
            with self.assertRaises(PermissionError) as denied:
                resolve_for(user, requested)
            self.assertEqual(str(denied.exception), "当前账号无知识库访问权限")


class ResponseContractTests(unittest.TestCase):
    """护栏 2：`grant` 用 `Field(exclude=True)` 收在进程内 —— 响应体不带它，属性照旧可读。"""

    _LOCAL_KEYS = {"username", "display_name", "role", "access_role", "permissions"}

    def _user(self, grant=None):
        from app.auth import CurrentUser

        return CurrentUser(username="u", display_name="U", role="HR", grant=grant)

    def test_dump_key_set_excludes_grant_in_every_mode(self):
        from app.identity.base import FeishuGrant

        user = self._user(FeishuGrant(access_role="admin", knowledge_base_ids=["kb_hr"]))
        self.assertEqual(set(user.model_dump()), self._LOCAL_KEYS)
        self.assertEqual(set(user.model_dump(mode="json")), self._LOCAL_KEYS)
        self.assertNotIn("grant", user.model_dump_json())
        # exclude 只影响序列化：auth / knowledge 侧的属性读取与授予接管一律照常。
        self.assertEqual(user.grant.knowledge_base_ids, ["kb_hr"])
        self.assertEqual(user.access_role, "admin")

    def test_local_only_user_dump_shape_is_unchanged(self):
        self.assertEqual(set(self._user().model_dump()), self._LOCAL_KEYS)
        self.assertIsNone(self._user().grant)

    def test_login_and_me_bodies_do_not_leak_grant(self):
        # 真走 HTTP：授予生效时也不许把外部身份结构体推给浏览器。
        import app.auth as auth
        import app.identity as identity
        from app.config import settings
        from app.identity.base import FeishuGrant
        from fastapi.testclient import TestClient
        from app.main import app

        class StubResolver:
            def resolve(self, username, role, open_id):
                return FeishuGrant(access_role="user", knowledge_base_ids=["kb_hr"])

        state = _saved_identity_state()
        saved_viewer = auth.USERS["viewer"]
        try:
            settings.feishu_permissions_enabled = True
            identity._resolver = StubResolver()
            auth.USERS["viewer"] = {**saved_viewer, "feishu_open_id": "ou_contract_probe"}
            client = TestClient(app)
            with _ModuleAuditSpy("app.main") as audit:
                login = client.post("/api/auth/login",
                                    json={"username": "viewer", "password": "viewer123"})
            self.assertEqual(login.status_code, 200)
            token = login.json()["access_token"]
            me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(me.status_code, 200)
            for body in (login.json()["user"], me.json()):
                self.assertNotIn("grant", body)
                self.assertEqual(set(body), self._LOCAL_KEYS)
                self.assertEqual(body["access_role"], "user")     # 授予仍然驱动可见角色
            self.assertEqual([e["action"] for e in audit.events], ["LOGIN"])
        finally:
            auth.USERS["viewer"] = saved_viewer
            _restore_identity_state(state)


class DeniedMessageContractTests(unittest.TestCase):
    """护栏 3：403 文案与 DENIED 审计 detail 是对外契约，必须逐字钉住。"""

    def _user(self, role, grant=None):
        from app.auth import CurrentUser

        return CurrentUser(username="u", display_name="U", role=role, grant=grant)

    def _denied(self, user, permission):
        from app.auth import enforce_permission

        with _AuditRecorder() as audit:
            with self.assertRaises(HTTPException) as box:
                enforce_permission(user, permission)
        return box.exception, audit.events

    def test_local_denial_message_and_audit_detail(self):
        exc, events = self._denied(self._user("VIEWER"), "knowledge:query")
        self.assertEqual(exc.status_code, 403)
        self.assertEqual(exc.detail, "当前账号缺少权限：knowledge:query")
        self.assertEqual([(e["action"], e["status"]) for e in events], [("AUTHORIZATION", "DENIED")])
        self.assertEqual(events[0]["detail"], "missing_permission=knowledge:query")
        self.assertEqual((events[0]["username"], events[0]["role"]), ("u", "VIEWER"))

    def test_grant_denial_carries_the_same_message_and_detail(self):
        # 授予收窄导致的 403 必须与本地 403 同文案：前端只有一种"缺权限"提示。
        from app.identity.base import FeishuGrant

        exc, events = self._denied(self._user("ADMIN", FeishuGrant(access_role="viewer")),
                                   "audit:read")
        self.assertEqual(exc.detail, "当前账号缺少权限：audit:read")
        self.assertEqual(events[0]["detail"], "missing_permission=audit:read")
        self.assertEqual(exc.status_code, 403)

    def test_kb_scope_denial_message_and_detail(self):
        # 同一口径的知识范围拒绝：文案走 knowledge 层，审计走 main 的包装层。
        from app.identity.base import FeishuGrant
        from app.main import _allowed_ids

        user = self._user("ADMIN", FeishuGrant(knowledge_base_ids=["kb_public"]))
        with _ModuleAuditSpy("app.main") as audit:
            with self.assertRaises(HTTPException) as box:
                _allowed_ids(user, "kb_hr")
        self.assertEqual(box.exception.status_code, 403)
        self.assertEqual(box.exception.detail, "当前账号无权访问该知识库")
        self.assertEqual(audit.events[0]["detail"], "当前账号无权访问该知识库")
        self.assertEqual(audit.events[0]["status"], "DENIED")


class LegacyAdminHelperTests(unittest.TestCase):
    """护栏 4：`require_admin` 是 grant 盲的 legacy 助手，零调用点即删除，且不得回流。"""

    def test_require_admin_is_gone_from_the_whole_backend_package(self):
        hits = {path.name for path, source in _python_sources(BACKEND_DIR / "app")
                if "require_admin" in source}
        self.assertEqual(hits, set())
        import app.auth as auth

        self.assertFalse(hasattr(auth, "require_admin"))


class AccessTokenClaimTests(unittest.TestCase):
    """护栏 5：JWT 的 `access_role` 只作兼容展示，鉴权不读它（授予每请求重解析）。"""

    def test_forged_claims_do_not_widen_permissions(self):
        import jwt
        from app.auth import require_user
        from app.config import settings

        token = jwt.encode({"sub": "viewer", "role": "ADMIN", "access_role": "admin",
                            "iss": "yaoke"}, settings.jwt_secret, algorithm="HS256")
        online = require_user(f"Bearer {token}")
        self.assertEqual(online.role, "VIEWER")                 # role 也只认本地 USERS 表
        self.assertEqual(online.access_role, "viewer")
        self.assertNotIn("system:operate", online.permissions)

    def test_claim_is_kept_and_documented_as_display_only(self):
        source = (BACKEND_DIR / "app" / "auth.py").read_text(encoding="utf-8")
        self.assertIn('"access_role": user.access_role', source)   # 未删 claim（兼容旧前端）
        self.assertIn("兼容展示", source)
        self.assertIn("鉴权不读", source)


class IdentityProviderReadmeTests(unittest.TestCase):
    """brief Step 3：接入文档是本任务的交付物，关键口径不得写漏（漂移即红）。"""

    README = BACKEND_DIR / "app" / "identity" / "README.md"

    def test_readme_exists(self):
        self.assertTrue(self.README.is_file(), self.README)

    def test_readme_covers_env_keys_semantics_ops_and_provider_steps(self):
        text = self.README.read_text(encoding="utf-8")
        for needle in (
                "FEISHU_PERMISSIONS_ENABLED", "FEISHU_APP_ID", "FEISHU_APP_SECRET",
                "FEISHU_BASE_URL", "FEISHU_RULES_FILE",
                "feishu_open_id", "config/feishu_permissions.json",
                "取高", "并集", '"*"', "空 match", 'extra="forbid"', "零可见",
                "reset_resolver", "DEGRADED", "60", "single-flight", "provider",
                "热更新", "不读",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_readme_documents_the_four_provider_steps(self):
        text = self.README.read_text(encoding="utf-8")
        for needle in ("fetch_user", "resolve_for_user", "判别", "contract"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()

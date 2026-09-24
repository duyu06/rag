from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.agent as agent_module
import app.agent_trace as agent_trace_module
import app.audit as audit_module
import app.knowledge_os as knowledge_os_module
from app.agent import _public_source
from app.agent_routes import _sse as agent_sse
from app.auth import CurrentUser
from app.config import settings
from app.conversation_store import ConversationStore
from app.conversation_stream_routes import _sse as conversation_sse
from app.main_agent import app
from app.security import (
    PUBLIC_TIMING_KEYS,
    PUBLIC_TYPESAFE_METRIC_KEYS,
    PUBLIC_TYPESAFE_STATS_KEYS,
    public_timings,
    public_typesafe_metrics,
    public_typesafe_stats,
    redact_secrets,
)
from app.typesafe_judgments import (
    reset_typesafe_stats,
    typesafe_judgment_service,
    typesafe_stats,
)
from app.typesafe_router import (
    REASON_COMPOUND,
    REASON_DISPERSED,
    REASON_FLOOR,
    REASON_MARGIN,
    REASON_PARAM,
    REASON_RISK,
    REASON_TOKENS,
    trigger_signals,
)


# Task 6 产出的请求级观测键（判定段 timings 里"存在才透传"的那些）。
V2_REQUEST_METRIC_KEYS = {
    "typesafe_trigger": True,
    "typesafe_skipped": "router",
    "typesafe_skip": True,
    "typesafe_cache_hit": 2,
    "typesafe_circuit_open": False,
    "typesafe_slow": True,
    # 段B2：selective 触发原因（值域 = app.typesafe_router.REASON_TOKENS 的子集）。
    "typesafe_reasons": ["compound", "risk"],
    "judge_input_count": 4,
}

# Task 6 产出的本地段计时键（无 `typesafe_` 前缀，走 timings 白名单）。
V2_STAGE_TIMING_KEYS = {"dedup_ms": 3.14, "rerank_stage_ms": 12.5}

# 设计 §7 的聚合面 + Task 5 自决 11 多出的两枚（`sample_count`/`slow_rate`）。
V2_AGGREGATE_KEYS = {
    "sample_count": 3,
    "trigger_rate": 0.333333,
    "skip_rate": 0.666667,
    "cache_hit_ratio": 0.25,
    "requests_per_query_p50": 1.0,
    "requests_per_query_p95": 8.0,
    "input_tokens_per_query_p50": 1200.0,
    "cost_per_query_p50": 0.0000504,
    "timeout_rate": 0.0,
    "degraded_rate": 0.0,
    "slow_rate": 0.333333,
    "latency_p50_ms": 41.0,
    "latency_p95_ms": 77.0,
    "breaker_state": "closed",
}


class TypeSafeSecurityContractTests(unittest.TestCase):
    @staticmethod
    def _canary() -> str:
        return "apikey_" + "A" * 64

    def test_secret_is_server_only_and_example_value_is_blank(self) -> None:
        env_example = (ROOT / "backend" / ".env.example").read_text(encoding="utf-8")
        self.assertRegex(env_example, r"(?m)^TYPESAFE_API_KEY=$")

        frontend = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in (ROOT / "frontend").rglob("*")
            if path.is_file() and "node_modules" not in path.parts and ".next" not in path.parts
        )
        self.assertNotIn("TYPESAFE_API_KEY", frontend)
        self.assertNotIn("typesafe_api_key", frontend)

    def test_public_sources_strip_internal_judgments_and_secrets(self) -> None:
        public = _public_source(
            {
                "citation_index": 1,
                "source_type": "enterprise",
                "file_name": "policy.md",
                "content": "authorized content",
                "knowledge_base_id": "kb_public",
                "typesafe_route": "include",
                "typesafe_signals": {"is_relevant": 0.99},
                "typesafe_api_key": "must-not-leak",
            }
        )
        self.assertNotIn("typesafe_route", public)
        self.assertNotIn("typesafe_signals", public)
        self.assertNotIn("typesafe_api_key", public)
        self.assertNotIn("must-not-leak", repr(public))

    def test_trace_and_audit_code_never_reference_secret_setting(self) -> None:
        for relative in (
            "backend/app/agent.py",
            "backend/app/conversation_agent.py",
            "backend/app/agent_trace.py",
            "backend/app/audit.py",
        ):
            self.assertNotIn(
                "typesafe_api_key",
                (ROOT / relative).read_text(encoding="utf-8"),
                relative,
            )

    def test_public_metric_allowlist_rejects_future_or_secret_fields(self) -> None:
        canary = self._canary()
        public = public_typesafe_metrics(
            {
                "typesafe_request_count": 2,
                "typesafe_models": ["jev-test"],
                "typesafe_api_key": canary,
                "typesafe_future_secret": canary,
            }
        )
        self.assertEqual(set(public), {"typesafe_request_count", "typesafe_models"})
        self.assertEqual(set(public).difference(PUBLIC_TYPESAFE_METRIC_KEYS), set())
        self.assertNotIn(canary, repr(public))

    def test_secret_canary_is_redacted_from_sse_trace_audit_and_sqlite(self) -> None:
        canary = self._canary()
        payload = {
            "query": canary,
            "Authorization": f"Bearer {canary}",
            "timings": {"typesafe_errors": [canary]},
        }
        self.assertNotIn(canary, repr(redact_secrets(payload)))
        self.assertNotIn(canary, agent_sse("done", payload))
        self.assertNotIn(canary, conversation_sse("done", payload))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace_path = root / "trace.jsonl"
            audit_path = root / "audit.jsonl"
            with (
                patch.object(agent_trace_module, "TRACE_PATH", trace_path),
                patch.object(audit_module, "AUDIT_PATH", audit_path),
            ):
                agent_trace_module.save_trace({"trace_id": "canary", **payload})
                audit_module.record_event(
                    username="tester",
                    role="admin",
                    action="QUERY",
                    query=canary,
                    detail=f"Authorization: Bearer {canary}",
                )
            self.assertNotIn(canary, trace_path.read_text(encoding="utf-8"))
            self.assertNotIn(canary, audit_path.read_text(encoding="utf-8"))

            store = ConversationStore(str(root / "conversations.db"))
            conversation = store.create(username="tester", title=canary)
            message = store.add_message(
                conversation_id=conversation["id"],
                username="tester",
                role="user",
                content=canary,
                sources=[{"file_name": "policy.md", "content_preview": canary}],
            )
            self.assertNotIn(canary, repr(conversation))
            self.assertNotIn(canary, repr(message))
            self.assertNotIn(
                canary.encode("utf-8"),
                (root / "conversations.db").read_bytes(),
            )

    def test_no_typesafe_style_api_key_is_tracked(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8").split("\0")
        pattern = re.compile(r"apikey_[A-Za-z0-9_]{20,}")
        findings: list[str] = []
        for relative in filter(None, tracked):
            path = ROOT / relative
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if pattern.search(text):
                findings.append(relative)
        self.assertEqual(findings, [])


class TypeSafeV2ObservabilityContractTests(unittest.TestCase):
    """Task 7 观测面契约：白名单扩展、`/system/status` 判定层块、trace 子事件。

    两条铁律各自有正反两面的用例：
    - 白名单只能逐条枚举（前缀放行 = 边界失效），所以每把新键都配一枚同前缀的
      "邻近键"（值填 canary），漏挡即红。
    - 判定层读数一律 effective 口径（`typesafe_enabled=false` 恒等价 off），
      原始 `settings.typesafe_mode` 不得再出现在任何上报点。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        admin = cls.client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123"}
        )
        assert admin.status_code == 200, admin.text
        cls.admin_headers = {"Authorization": f"Bearer {admin.json()['access_token']}"}
        viewer = cls.client.post(
            "/api/auth/login", json={"username": "viewer", "password": "viewer123"}
        )
        assert viewer.status_code == 200, viewer.text
        cls.viewer_headers = {"Authorization": f"Bearer {viewer.json()['access_token']}"}

    @staticmethod
    def _canary() -> str:
        return "apikey_" + "B" * 64

    def setUp(self) -> None:
        reset_typesafe_stats()

    def tearDown(self) -> None:
        reset_typesafe_stats()

    def _system_status(self, headers: dict[str, str]):
        """只测观测面：把 qdrant / ollama 探测换成替身，避免用例依赖容器在不在跑。"""
        with (
            patch.object(knowledge_os_module.vector_store, "ping", return_value=True),
            patch.object(
                knowledge_os_module.vector_store,
                "stats",
                return_value={
                    "total_chunks": 1,
                    "collection_name": "contract",
                    "embedding_dimension": 4,
                },
            ),
            patch.object(knowledge_os_module, "probe_llm", return_value=(True, "ok")),
            patch.object(knowledge_os_module, "current_model_name", return_value="test-model"),
        ):
            return self.client.get("/api/system/status", headers=headers)

    # ---------- 白名单：请求级新键 ----------

    def test_v2_request_metric_keys_cross_the_boundary_and_lookalikes_do_not(self) -> None:
        canary = self._canary()
        bag = {
            **V2_REQUEST_METRIC_KEYS,
            # 同前缀的邻近键：任何"按前缀放行"的实现都会在这里露馅。
            "typesafe_cache_hit_details": canary,
            "typesafe_skipped_reasons": canary,
            "typesafe_skip_ratio_internal": canary,
            "typesafe_trigger_prompt": canary,
            "typesafe_api_key": canary,
            "judge_input_chars": canary,
        }
        public = public_typesafe_metrics(bag)
        self.assertEqual(set(public), set(V2_REQUEST_METRIC_KEYS))
        self.assertEqual(public["typesafe_skipped"], "router")
        self.assertIs(public["typesafe_skip"], True)
        self.assertEqual(public["judge_input_count"], 4)
        self.assertNotIn(canary, repr(public))

    def test_typesafe_reasons_is_public_and_closed_over_the_six_tokens(self) -> None:
        """段B2 缺陷2 契约：`typesafe_reasons` 过白名单，且值域封闭在 §3 六枚 token。

        这是第一枚"数组过边界"的判定层键，两头都要钉：
        1) 键本身放行（selective 标定必须看得见触发原因，含"为什么免判"）；
        2) 成员只会是 compound/margin/floor/risk/dispersed/param ⇒ 没有任何路径把提交的
           文本或密钥经这个数组带出去，所以放开它不构成新的泄密面。
        同族近邻键仍然必须被拒（白名单是逐枚列举，不是按前缀）。
        """
        canary = self._canary()
        public = public_typesafe_metrics(
            {
                "typesafe_reasons": [REASON_COMPOUND, REASON_RISK],
                "typesafe_skipped_reasons": [canary],
                "typesafe_reasons_detail": {canary: canary},
                "typesafe_reasons_raw_query": canary,
            }
        )
        self.assertIn("typesafe_reasons", PUBLIC_TYPESAFE_METRIC_KEYS)
        self.assertEqual(set(public), {"typesafe_reasons"})
        self.assertEqual(public["typesafe_reasons"], [REASON_COMPOUND, REASON_RISK])
        self.assertNotIn(canary, repr(public))

        # 值域封闭的实证面：把密钥掺进 query 与候选文本，发射器只会回 token。
        hostile_rows = [
            {
                "id": "x",
                "file_name": f"{canary}.md",
                "knowledge_base_id": "kb_public",
                "content": f"条款如下：{canary}",
                "rerank_score": 0.30,
            },
            {
                "id": "y",
                "file_name": "b.md",
                "knowledge_base_id": "kb_public",
                "content": "另一段",
                "rerank_score": 0.29,
            },
        ]
        emitted = trigger_signals(f"保密协议违约怎么处理 {canary}？多少天？", hostile_rows)
        self.assertTrue(set(emitted) <= set(REASON_TOKENS), emitted)
        self.assertNotIn(canary, repr(emitted))
        self.assertEqual(
            set(REASON_TOKENS),
            {
                REASON_COMPOUND,
                REASON_MARGIN,
                REASON_FLOOR,
                REASON_RISK,
                REASON_DISPERSED,
                REASON_PARAM,
            },
        )
        # 数组过 `redact_secrets` 不被打散：脱敏器逐元素处理，token 原样保留。
        self.assertEqual(redact_secrets(["compound", "risk"]), ["compound", "risk"])

    def test_v2_stage_timings_are_public_but_unlisted_timings_are_not(self) -> None:
        canary = self._canary()
        bag = {
            **V2_STAGE_TIMING_KEYS,
            **V2_REQUEST_METRIC_KEYS,
            "rerank_model_path": canary,
            "dedup_threshold_source": canary,
            "typesafe_dedup_vectors": canary,
        }
        public = public_timings(bag)
        self.assertEqual(public["dedup_ms"], 3.14)
        self.assertEqual(public["rerank_stage_ms"], 12.5)
        self.assertNotIn("rerank_model_path", public)
        self.assertNotIn("dedup_threshold_source", public)
        self.assertTrue(set(V2_STAGE_TIMING_KEYS) <= PUBLIC_TIMING_KEYS)
        self.assertTrue(set(V2_REQUEST_METRIC_KEYS) <= PUBLIC_TYPESAFE_METRIC_KEYS)
        self.assertNotIn(canary, repr(public))

    def test_allowlists_are_literal_enumerations_not_prefix_rules(self) -> None:
        source = (ROOT / "backend" / "app" / "security.py").read_text(encoding="utf-8")
        for forbidden in (
            'startswith("typesafe',
            "startswith('typesafe",
            '"typesafe_" in',
            'startswith("judge',
        ):
            self.assertNotIn(forbidden, source)
        # 三张表都得是显式枚举的 frozenset 字面量（聚合表同样不接受派生）。
        for name in (
            "PUBLIC_TYPESAFE_METRIC_KEYS",
            "PUBLIC_TIMING_KEYS",
            "PUBLIC_TYPESAFE_STATS_KEYS",
        ):
            self.assertIn(f"{name} = frozenset(", source)

    # ---------- 白名单：聚合面 ----------

    def test_aggregate_allowlist_matches_the_shipped_stats_vocabulary(self) -> None:
        # 反向 also 钉：判定模块若长出第 15 枚聚合键，这里必须**主动**决定放不放行。
        self.assertEqual(set(typesafe_stats()), set(PUBLIC_TYPESAFE_STATS_KEYS))
        self.assertEqual(set(V2_AGGREGATE_KEYS), set(PUBLIC_TYPESAFE_STATS_KEYS))

    def test_public_stats_blocks_lookalike_aggregate_keys(self) -> None:
        canary = self._canary()
        stats = {
            **V2_AGGREGATE_KEYS,
            "breaker_state_snapshot_raw": canary,
            "typesafe_api_key": canary,
            "sample_query_text": canary,
        }
        public = public_typesafe_stats(stats)
        self.assertEqual(public, V2_AGGREGATE_KEYS)
        self.assertNotIn(canary, repr(public))

    # ---------- /system/status 判定层块 ----------

    def test_status_typesafe_block_field_set_is_whitelisted_and_secret_free(self) -> None:
        canary = self._canary()
        stats = {**V2_AGGREGATE_KEYS, "typesafe_api_key": canary, "judge_prompt": canary}
        with (
            patch.object(settings, "typesafe_enabled", True),
            patch.object(settings, "typesafe_mode", "selective"),
            patch.object(settings, "typesafe_api_key", SecretStr(canary)),
            patch.object(knowledge_os_module, "typesafe_stats", return_value=stats),
        ):
            response = self._system_status(self.admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(canary, response.text)
        block = response.json()["typesafe"]
        self.assertEqual(set(block), {"mode", *PUBLIC_TYPESAFE_STATS_KEYS})
        self.assertEqual(block["mode"], "selective")
        self.assertEqual(block["trigger_rate"], 0.333333)
        self.assertEqual(block["breaker_state"], "closed")
        self.assertEqual(block["requests_per_query_p95"], 8.0)

    def test_status_block_reports_effective_mode_and_keeps_viewer_locked_out(self) -> None:
        # `typesafe_enabled=false` 恒等价 off（Task 2 移交：上报口径统一 effective）。
        with (
            patch.object(settings, "typesafe_enabled", False),
            patch.object(settings, "typesafe_mode", "active"),
        ):
            response = self._system_status(self.admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["typesafe"]["mode"], "off")

        forbidden = self._system_status(self.viewer_headers)
        self.assertEqual(forbidden.status_code, 403)
        self.assertNotIn("typesafe", forbidden.text)

    def test_judgment_metrics_report_effective_mode_without_any_call(self) -> None:
        batch = None
        with (
            patch.object(settings, "typesafe_enabled", False),
            patch.object(settings, "typesafe_mode", "active"),
            patch.object(settings, "typesafe_api_key", SecretStr(self._canary())),
        ):
            batch = typesafe_judgment_service.judge_candidates(
                "合同违约的赔偿上限是多少",
                [{"id": "a", "knowledge_base_id": "kb_public", "content": "x"}],
                knowledge_base_ids=["kb_public"],
            )
        # 键名不动、值换 effective：mode 与 skipped 必须同为 "off"，不许 "active"+"off" 并存。
        self.assertEqual(batch.metrics["typesafe_mode"], "off")
        self.assertEqual(batch.metrics["typesafe_skipped"], "off")
        self.assertIs(batch.metrics["typesafe_trigger"], False)
        self.assertEqual(batch.metrics["typesafe_request_count"], 0)
        self.assertEqual(typesafe_stats()["sample_count"], 0)

    def test_no_report_surface_reads_the_raw_mode_setting(self) -> None:
        offenders: list[str] = []
        for path in sorted((ROOT / "backend" / "app").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for forbidden in (
                '"mode": settings.typesafe_mode',
                '"typesafe_mode": settings.typesafe_mode',
            ):
                if forbidden in text:
                    offenders.append(f"{path.name}:{forbidden}")
        self.assertEqual(offenders, [])

    # ---------- trace：重排阶段 detail 子事件 ----------

    def test_rerank_stage_detail_carries_typesafe_subflags_after_whitelisting(self) -> None:
        canary = self._canary()
        raw_timings = {
            "rerank_ms": 120.0,
            "rerank_stage_ms": 30.0,
            "dedup_ms": 3.0,
            **V2_REQUEST_METRIC_KEYS,
            "typesafe_errors": [canary],
            "typesafe_api_key": canary,
            "typesafe_signals": {canary: canary},
        }
        events = knowledge_os_module.build_stage_events(
            public_timings(raw_timings), scope_count=1, evidence_count=2
        )
        rerank = next(event for event in events if event["stage"] == "rerank")
        self.assertIn("触发 是", rerank["detail"])
        self.assertIn("缓存命中 2", rerank["detail"])
        self.assertIn("熔断 闭合", rerank["detail"])
        self.assertIn("跳过 是", rerank["detail"])
        # 本地 CE 段与判定段仍是同一行（`rerank_ms` 语义未变），且不新增事件类型/字段。
        self.assertEqual({event["type"] for event in events}, {"stage"})
        self.assertEqual(
            set(rerank), {"type", "stage", "status", "elapsed_ms", "detail"}
        )
        self.assertNotIn(canary, repr(events))

    def test_rerank_stage_detail_stays_clean_when_the_layer_is_off(self) -> None:
        events = knowledge_os_module.build_stage_events(
            {"rerank_ms": 30.0, "rerank_stage_ms": 30.0},
            scope_count=1,
            evidence_count=1,
        )
        rerank = next(event for event in events if event["stage"] == "rerank")
        self.assertNotIn("触发", rerank["detail"])
        self.assertNotIn("熔断", rerank["detail"])
        self.assertIn("model=", rerank["detail"])

    def test_agent_path_merges_typesafe_observations_into_the_rerank_stage_detail(self) -> None:
        """钉住 `app/agent.py` 里 `stage_timings = {**retrieval_timings, **typesafe_timings}`。

        上面那条用例是"喂好现成 timings 再调 `build_stage_events`"，绕过了 agent 自己的装配：
        把合并行回退成 `dict(retrieval_timings)`，全套件照样绿——auto 路的 trace 会静默丢掉
        判定层四枚子观测（评审变异存活项）。本用例走真实 `run_agent`，只替两处外部依赖
        （Ollama 与工具执行），断言的就是"agent 把本地段计时与已白名单化的判定层读数并到
        了一起"。顺带反向钉：未列白名单的内部键不得随这条合并渗进 trace/响应。
        """
        holder: list[dict] = []
        internal_note = "internal-only-route-diagnostic"
        tool_result = {
            "ok": True,
            "tool": "enterprise_search",
            "status": "SUCCESS",
            "evidence": [
                {
                    "id": "chunk-1",
                    "knowledge_base_id": "kb_public",
                    "file_name": "policy.md",
                    "page": 1,
                    "content": "违约赔偿上限为合同金额的 20%。",
                    "relevance_score": 0.9,
                }
            ],
            "timings": {
                "vector_ms": 12.0,
                "bm25_ms": 8.0,
                "fusion_ms": 2.0,
                "rerank_ms": 40.0,
                "diversity_ms": 1.5,
                "total_ms": 65.0,
                "returned_documents": 1,
                **V2_REQUEST_METRIC_KEYS,
                internal_note: internal_note,
            },
        }
        turns = iter(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "enterprise_search",
                                "arguments": {"query": "合同违约的赔偿上限是多少"},
                            }
                        }
                    ],
                },
                {"role": "assistant", "content": "赔偿上限为合同金额的 20%[1]。", "tool_calls": []},
            ]
        )
        user = CurrentUser(username="tester", display_name="Tester", role="ADMIN")
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(agent_module, "_ollama_chat", side_effect=lambda *a, **k: next(turns)),
                patch.object(agent_module.tool_registry, "execute", return_value=tool_result),
                patch.object(agent_module, "save_trace", side_effect=lambda trace: holder.append(trace)),
                patch.object(audit_module, "AUDIT_PATH", Path(directory) / "audit.jsonl"),
            ):
                response = agent_module.run_agent(
                    question="合同违约的赔偿上限是多少",
                    user=user,
                    mode="auto",
                )

        self.assertEqual(len(holder), 1, "run_agent 未落 trace")
        trace = holder[0]
        stages = [event for event in trace["events"] if event.get("type") == "stage"]
        rerank = next(event for event in stages if event["stage"] == "rerank")
        self.assertIn("触发 是", rerank["detail"])
        self.assertIn("缓存命中 2", rerank["detail"])
        self.assertIn("熔断 闭合", rerank["detail"])
        self.assertIn("跳过 是", rerank["detail"])
        # 合并只服务这一行渲染：两叠计时各自取值，互不污染（本地段仍是耗时，不是判定读数）。
        self.assertEqual(rerank["elapsed_ms"], 40.0)
        self.assertIs(trace["timings"]["typesafe_trigger"], True)
        self.assertIs(response["timings"]["typesafe_trigger"], True)
        self.assertNotIn(internal_note, repr(trace))
        self.assertNotIn(internal_note, repr(response))


if __name__ == "__main__":
    unittest.main()

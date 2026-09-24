"""REAL-LLM-FAILOVER-001 —— DESIGN §10 的 P0 真机十字（Model Router V2.3 Task 10 段 A 产出）。

**这一段会真的加载模型。** phi3:mini 是 2.03 GiB 的权重，首次加载要几十秒到几分钟；
主 agent 已把「本机内存够不够」写成 runner 的前置判定，未放行前不要手工敲开关。

怎么跑（唯一入口）
----------------
1. 推荐（含环境前置 + 证据 + 许可判定）：

       bash .superpowers/scripts/run_p0_failover_acceptance.sh            # 仓库根
       bash .superpowers/scripts/run_p0_failover_acceptance.sh --dry-run  # 只看要做什么

2. 手工（等价，前提是你自己确认内存够）：

       cd backend
       REAL_LLM_ACCEPTANCE=1 python -m pytest tests/test_real_llm_failover_acceptance.py -q -s

**默认（没有 `REAL_LLM_ACCEPTANCE=1`）本文件不被收集**：文件末尾把那枚类从模块命名空间里
`del` 掉，所以 `pytest tests -q --collect-only` 对本文件的收集数恒为 0。这是刻意的：
用 `@unittest.skipUnless(...)` 会让它在默认套件里长成 `skipped`，而 skipped 在报告里可以被
读成「跑过了只是环境不行」——§10 的 P0 不允许这种含糊态。这条双向纪律（默认收集 0 枚 /
开了开关必须收集 ≥1 枚 / 源码面零 skip 分支）由
`tests/test_real_llm_failover_gate.py` 钉住。

跑完证据落在哪
-------------
    .superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json   # 十枚断言实测值
    .superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/run/<stamp>/conversations.db      # 临时账本
    .superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/run/<stamp>/agent_traces.jsonl    # 临时 trace

两枚路径都是**显式绝对路径**，且都**不在** `backend/data/` 下：账本 env
（`CONVERSATION_DB_PATH`）与 trace 路径（`app.agent_trace.TRACE_PATH`）在用例内改成临时
目录后跑，收尾把 sha1 打印出来（也是证据里的 `files_sha1`）。仓库真实库
`backend/data/conversations.db` 全程零写——`tests/conftest.py` 的会话护栏盯着这件事，
写进去就直接判红，不需要本用例自觉。

谁有权把矩阵改成 GREEN
---------------------
**只有主 agent。** 本文件与 runner 都不碰 `docs/MODEL_ROUTER_V23_MATRIX.md`。闸
（`test_real_llm_failover_gate.py`）只回答一句：「带执行证据的 JSON 在不在、成不成立」——
不在 ⇒ P0 行只许是 `BLOCKED`；成立 ⇒ 只许是 `GREEN`。写盘的那一支笔不在自动化里。

十枚断言的出处
-------------
逐字对应 `docs/MODEL_ROUTER_V23_DESIGN.md` §10 P0 行：primary 真被调用 / 失败归类
`model_unavailable` / fallback 被调 / phi3 有效回答 / `fallback_index=1` / `trace_id` 全链
一致 / `model_route` 两枚 attempt / usage 落库 / 零 prompt 入库 / API 200。第 10 枚的口径
见 `test_api_face_is_200` 的 docstring（它**不**再花一次真加载）。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
import unittest
import uuid
from pathlib import Path
from typing import Any
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
for _entry in (str(BACKEND_DIR), str(TESTS_DIR)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import real_llm_failover_kit as kit                                    # noqa: E402

import app.llm as llm                                                   # noqa: E402
import app.llm.provider as provider_module                              # noqa: E402
import app.llm.usage as usage_module                                    # noqa: E402
from app import agent_trace as agent_trace_module                       # noqa: E402
from app.config import settings                                         # noqa: E402
from app.llm import errors as llm_errors                                # noqa: E402
from app.llm.fallback import BREAKERS                                   # noqa: E402
from app.llm.models import RequestProfile                               # noqa: E402
from app.llm.registry import credentials_for_provider, get_registry     # noqa: E402
from app.llm.router import plan as plan_route                           # noqa: E402
from app.rag import SYSTEM_PROMPT as RAG_SYSTEM_PROMPT                  # noqa: E402

#: §8.1 第 4 条回写后的 `model_route` 九键（等式用，不靠「大概齐」）。
MODEL_ROUTE_NINE_KEYS: tuple[str, ...] = (
    "mode", "requirements", "primary", "fallbacks", "selected_reason_codes",
    "attempts", "stage", "selected_index", "context_dropped",
)

#: P0 的证据面：真机跑一次要几分钟，所以这里**不**写小超时。
#: `REAL_CALL_TIMEOUT_SECONDS` 在 kit 里（900 秒），subTest 的判据不看它，只看事实。
_STEP_NOTE = "step_timings"

#: 真 prompt（含 canary）。问题刻意要三条要点，phi3:mini 也答得出，长度下限才可信。
EVIDENCE_ROW = {
    "content": (f"{kit.PROMPT_CANARY} 员工出差住宿每晚上限 600 元，需事前经部门经理审批，"
                "发票必须在 30 天内提交给财务。"),
    "file_name": "差旅报销制度.md",
    "score": 0.9,
}
QUESTION = ("请用中文分点回答：员工出差住宿需要注意哪三件事？"
            "每条一句话，依据上面给出的资料。")


def _user_prompt() -> str:
    """与 `app/rag.py` 的 `build_context` 同形状的证据块 + 问题（canary 在里面）。"""
    return ("请依据以下证据回答问题。\n\n"
            f"[1] {EVIDENCE_ROW['file_name']}\n{EVIDENCE_ROW['content']}\n\n"
            f"问题：{QUESTION}")


def _messages() -> list[dict[str, str]]:
    return [{"role": "system", "content": RAG_SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt()}]


class RealLlmFailover001Tests(unittest.TestCase):
    """§10 P0：primary=`ornith-1.5:9b-text` 真加载失败 → fallback=`phi3:mini` 真回答。

    一次运行 = 两次**真实** Ollama 外呼，中间没有任何 mock 传输层。
    """

    maxDiff = None

    # ------------------------------------------------------------------ 生命周期
    def setUp(self) -> None:
        if not kit.acceptance_enabled():
            raise self.failureException(
                "本用例只在 REAL_LLM_ACCEPTANCE=1 下运行（默认不该被收集，"
                "被收集到却没开关 = 有人改了收集门）")

        self.started_wall = time.time()
        self.step_timings: list[dict[str, Any]] = []
        self.provider_calls: list[dict[str, Any]] = []
        self.trace_id = f"p0-failover-{uuid.uuid4().hex[:12]}"
        self.request_id = f"p0-req-{uuid.uuid4().hex[:8]}"

        # 临时账本 + 临时 trace：**绝对路径**，绝不落在 backend/data/。
        # 目录跟着**证据文件所在处**走：真机跑落在 `task10/run/`，离线彩排
        # （`EVIDENCE_FILE` 被换成 `task10/rehearsal/…`）就落在彩排自己的目录里，
        # 两边不会互相冒充成对方的现场。
        self.run_dir = (Path(kit.EVIDENCE_FILE).parent / "run"
                        / time.strftime("%Y%m%d-%H%M%S"))
        if self.run_dir.exists():
            shutil.rmtree(self.run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.temp_db = self.run_dir / "conversations.db"
        self.temp_trace = self.run_dir / "agent_traces.jsonl"

        env_patch = mock.patch.dict(
            os.environ, {"CONVERSATION_DB_PATH": str(self.temp_db),
                         "LLM_ROUTER_ENABLED": "true"})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        # usage 的模块级路径覆盖（`_state["db_path"]`）是进程全局，收尾必须清。
        usage_module.reset_usage_state()
        self.addCleanup(usage_module.reset_usage_state)
        usage_module.init_usage_db(str(self.temp_db))
        # sink 走默认（= `usage.log_usage`）：P0 要的就是「真落库」，不是假 sink。
        self.addCleanup(llm.set_usage_sink, None)
        llm.set_usage_sink(None)

        # 熔断器/健康缓存跨用例泄漏会把第二条候选直接闸掉（P0 只发两次真请求）。
        BREAKERS.clear()
        self.addCleanup(BREAKERS.clear)

        # 真机时钟：§12 出厂预算（总 30 s / 单模型 20 s）**装不下**一次 2 GiB 冷加载。
        # 这里是**测试侧**改 settings 实例，产品代码与 .env 默认值一字未动；
        # `llm_retry_per_model` 刻意**不**改（出厂 1 次）：P0 要的是真链的形状，
        # `model_unavailable` 本来就不重试当前模型（errors.py 的 `retryable` 属性），
        # 把它调成 0 只是掩盖，不是收紧。这件事在证据里单独记一条（config_overrides）。
        overrides = {"llm_total_budget_ms": 900000, "llm_model_timeout_seconds": 300,
                     "llm_router_enabled": True,
                     # cwd 前提（矩阵 §5 的同款手法，`WarmupGateTests.setUp` 已开先例）：
                     # §12 的出厂默认 `llm_registry_file` 是**相对**路径
                     # `config/llm_registry.json`，从仓库根起跑就会 `RegistryError`。
                     # 指到绝对出厂文件——**只读**，`config/` 下那一份一字不动。
                     "llm_registry_file": str(BACKEND_DIR / "config"
                                              / "llm_registry.json")}
        for name, value in overrides.items():
            patcher = mock.patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.config_overrides = overrides

        # trace 落盘点改成临时文件（`save_trace` 读的是模块全局）。
        trace_patch = mock.patch.object(agent_trace_module, "TRACE_PATH", self.temp_trace)
        trace_patch.start()
        self.addCleanup(trace_patch.stop)

        self.install_provider_spy()

        self.evidence: dict[str, Any] = {
            "case_id": kit.CASE_ID,
            "schema_version": kit.SCHEMA_VERSION,
            "completed": False,
            # 「真机」的定义性事实：`provider.py` 的测试接缝必须是 None。挂着
            # MockTransport 跑出来的这份 JSON 会被 `validate_evidence()` 直接拒收，
            # 所以离线彩排（`task10_rehearsal.py`）永远不可能冒充真机证据。
            "provider_transport": (None if provider_module._transport is None else
                                   type(provider_module._transport).__name__),
            "generated_at": kit.utc_now(),
            "design_source": "docs/MODEL_ROUTER_V23_DESIGN.md §10 P0 行（十字逐字）",
            "registry_file": str(BACKEND_DIR / "config" / "llm_registry.json"),
            "registry_mutated": "未改（本用例只读注册表；config/llm_registry.json 一字未动）",
            "config_overrides": {
                **overrides,
                "why": "§12 出厂预算（30 s / 20 s）装不下 2 GiB 冷加载；只改测试进程内的 "
                       "Settings 实例，产品默认值与 .env 不动。需要主 agent 裁决是否给真机 "
                       "验收另立一档配置键。",
                "frozen_range_note": "llm_total_budget_ms 出厂约束是 5000..120000，"
                                     "900000 越界（测试侧 patch 绕过 Field 校验）",
            },
            "request": {
                "mode": "rag",
                "trace_id": self.trace_id,
                "request_id": self.request_id,
                "keep_alive": "0",
                "num_predict": 256,
                "temperature": 0.2,
                "user_prompt_chars": len(_user_prompt()),
                "user_prompt_sha1": hashlib.sha1(
                    _user_prompt().encode("utf-8")).hexdigest(),
                "canaries": [kit.PROMPT_CANARY, QUESTION, EVIDENCE_ROW["content"][:24]],
            },
            "timings_ms": {"per_step": self.step_timings},
        }
        self.addCleanup(self.write_evidence)

    # ------------------------------------------------------------------ 观测面
    def timed(self, label: str):
        class _Timer:
            def __enter__(_self):
                _self.t0 = time.perf_counter()
                return _self

            def __exit__(_self, *exc):
                ms = round((time.perf_counter() - _self.t0) * 1000.0, 1)
                self.step_timings.append({"step": label, "ms": ms})
                print(f"[P0] {label}: {ms} ms", flush=True)
                return False

        return _Timer()

    def install_provider_spy(self) -> None:
        """包一层 `provider.complete`：**只记录、原样透传**（不改行为、不改异常）。

        为什么要包：§10 的「primary 真被调用」要的是**出口面**事实（发了什么报文、多少字节、
        服务端回了什么原文），而 `Attempt` 只带 `error_type`（机器码），错误体原文在
        `LLMError.message` 里被截断后就地丢掉。spy 之外的一层什么都不动，
        异常仍然 `raise` 原对象。
        """
        real = provider_module.complete
        calls = self.provider_calls

        def spy(model, req, timeout):
            adapter = provider_module.PROVIDERS[model.provider]
            creds = credentials_for_provider(model.provider, label=model.id)
            target = provider_module.effective_model_name(model, creds)
            payload = adapter.payload(req, target, stream=False)
            record: dict[str, Any] = {
                "entry_id": model.id, "provider": model.provider, "model": target,
                "request_bytes": len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
                "request_bytes_method": "adapter.payload 序列化重建（非 wire 抓包）",
                "timeout_s": timeout,
                "message_roles": [m.get("role") for m in req.messages],
            }
            started = time.perf_counter()
            try:
                response = real(model, req, timeout)
            except BaseException as exc:                      # noqa: BLE001 - 记完原样上抛
                record.update(elapsed_ms=round((time.perf_counter() - started) * 1000.0, 1),
                              ok=False,
                              error_kind=getattr(exc, "kind", None),
                              http_status=getattr(exc, "status_code", None),
                              no_fallback=getattr(exc, "no_fallback", None),
                              error_body_excerpt=str(exc)[:2000])
                calls.append(record)
                raise
            record.update(elapsed_ms=round((time.perf_counter() - started) * 1000.0, 1),
                          ok=True, answer_chars=len(response.content or ""),
                          finish_reason=response.finish_reason,
                          input_tokens=response.input_tokens,
                          output_tokens=response.output_tokens,
                          usage_estimated=response.usage_estimated,
                          error_body_excerpt=None, error_kind=None, http_status=200)
            calls.append(record)
            return response

        patcher = mock.patch.object(provider_module, "complete", spy)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_evidence(self) -> None:
        """收尾把证据 JSON 落盘（**失败也落**：`completed=false` 的残缺证据比没有证据可查）。"""
        self.evidence["timings_ms"]["total"] = round(
            (time.time() - self.started_wall) * 1000.0, 1)
        self.evidence["provider_calls"] = self.provider_calls
        self.evidence["run_artifacts"] = {
            "run_dir": str(self.run_dir), "ledger": str(self.temp_db),
            "trace": str(self.temp_trace)}
        try:
            # 刷新一次（断言之后临时库/trace 又长了几十字节），并且**不含**证据文件自身。
            if self.evidence.get("files_sha1") is None:
                self.evidence["files_sha1"] = kit.fingerprint(
                    [p for p in (self.temp_db, self.temp_trace, kit.PROBE_FILE,
                                 kit.ACCEPTANCE_FILE) if Path(p).is_file()])
        except OSError as exc:                                # pragma: no cover
            self.evidence["files_sha1_error"] = str(exc)
        kit.write_json(kit.EVIDENCE_FILE, self.evidence)
        print(f"[P0] 证据落盘 {kit.EVIDENCE_FILE} (completed="
              f"{self.evidence['completed']})", flush=True)
        for path, digest in (self.evidence.get("files_sha1") or {}).items():
            print(f"[P0] sha1 {digest}  {path}", flush=True)

    # ------------------------------------------------------------------ 前置（不花模型）
    def assert_plan_is_the_shipped_failover_pair(self) -> dict[str, Any]:
        """§10 P0 的前提事实：出厂注册表在 rag 档给出的计划**就是** ornith → phi3。

        这一枚在真调用之前跑：万一哪天注册表或 router 改了序，P0 的十字就失去了对象，
        与其花五分钟加载 phi3 再报告「链条不对」，不如在这里 0 成本地红。
        """
        registry = get_registry()
        profile = RequestProfile(mode="rag", complexity="low", needs_tools=False,
                                 needs_stream=False)
        route_plan = plan_route(profile, registry, {})
        plan_view = {
            "primary_entry": route_plan.primary.model.id,
            "primary_model": route_plan.primary.model.model,
            "fallback_entries": [c.model.id for c in route_plan.fallbacks],
            "fallback_models": [c.model.model for c in route_plan.fallbacks],
            "reason_codes": list(route_plan.reason_codes),
        }
        with self.subTest("plan.primary"):
            self.assertEqual(kit.PRIMARY_ENTRY_ID, route_plan.primary.model.id,
                             f"出厂注册表的 rag primary 条目不是 {kit.PRIMARY_ENTRY_ID}"
                             f"：{plan_view}")
            self.assertEqual(kit.PRIMARY_MODEL, route_plan.primary.model.model,
                             f"primary 的模型名不是 {kit.PRIMARY_MODEL}：{plan_view}")
        with self.subTest("plan.fallback[0]"):
            self.assertTrue(route_plan.fallbacks, f"计划没有 fallback：{plan_view}")
            self.assertEqual(kit.FALLBACK_ENTRY_ID, route_plan.fallbacks[0].model.id,
                             f"第一 fallback 条目不是 {kit.FALLBACK_ENTRY_ID}：{plan_view}")
            self.assertEqual(kit.FALLBACK_MODEL, route_plan.fallbacks[0].model.model,
                             f"第一 fallback 不是 {kit.FALLBACK_MODEL}：{plan_view}")
        self.evidence["plan"] = plan_view
        return plan_view

    # ------------------------------------------------------------------ 十字
    def test_real_llm_failover_001_ten_assertions(self):
        """一次真机运行，逐枚打十枚断言的实测值（编号 = §10 P0 行的十字顺序）。"""
        with self.timed("00_precheck_plan"):
            self.assert_plan_is_the_shipped_failover_pair()
        with self.timed("00_precheck_ollama"):
            inventory_before = kit.ollama_inventory()
            self.assertTrue(inventory_before["reachable"],
                            f"本机 Ollama 不在：{inventory_before['error']}")
            self.assertTrue(inventory_before["has_primary"] and inventory_before["has_fallback"],
                            f"模型条目不齐：{inventory_before['tags']}")
            self.evidence["environment"] = {
                "before": inventory_before, "memory_before": kit.memory_facts(),
                "probe_reference": str(kit.PROBE_FILE)}

        messages = _messages()
        with self.timed("01_real_llm_complete"):
            result = llm.complete(messages, mode="rag", temperature=0.2,
                                  num_predict=256, keep_alive="0",
                                  trace_id=self.trace_id, request_id=self.request_id)
        self.evidence["answer"] = {
            "text": result.response.content,
            "chars": len(result.response.content or ""),
            "cjk_chars": len(kit._CJK.findall(result.response.content or "")),
            "model": result.response.model,
            "finish_reason": result.response.finish_reason,
            "input_tokens": result.response.input_tokens,
            "output_tokens": result.response.output_tokens,
            "usage_estimated": result.response.usage_estimated,
        }
        with self.timed("02_attach_and_save_trace"):
            trace = {"trace_id": self.trace_id, "events": []}
            agent_trace_module.attach_model_route(
                trace, result.plan, result,
                profile=RequestProfile(mode="rag", complexity="low", needs_tools=False,
                                       needs_stream=False))
            agent_trace_module.save_trace(trace)

        route = trace.get(agent_trace_module.MODEL_ROUTE_KEY) or {}
        ledger_rows = kit.ledger_rows(self.temp_db)
        call_primary = self.provider_calls[0] if self.provider_calls else {}
        call_fallback = self.provider_calls[1] if len(self.provider_calls) > 1 else {}

        # ① primary 真被调用（出口面 + 执行面各一枚事实，且互相同源）
        self.record(1, "primary_really_called", {
            "attempts": [{"model_id": a.model_id, "provider": a.provider,
                          "result": a.result, "error_type": a.error_type,
                          "latency_ms": round(a.latency_ms, 1)} for a in result.attempts],
            "egress_entry_id": call_primary.get("entry_id"),
            "egress_model": call_primary.get("model"),
            "egress_request_bytes": call_primary.get("request_bytes"),
            "egress_ok": call_primary.get("ok"),
        }, lambda: [
            self.assertEqual(kit.PRIMARY_ENTRY_ID, result.attempts[0].model_id),
            self.assertEqual(kit.PRIMARY_MODEL, call_primary.get("model")),
            self.assertEqual("failed", result.attempts[0].result,
                             "primary 这一枚不是 failed ⇒ 今天没有发生真加载失败，"
                             "P0 的前提不成立（不许把它当『意外成功了也算过』）"),
            self.assertGreater(int(call_primary.get("request_bytes") or 0), 0),
            self.assertIs(False, call_primary.get("ok")),
        ])

        # ② 失败归类 model_unavailable（机器码 + 服务端原文双证）
        excerpt = str(call_primary.get("error_body_excerpt") or "")
        self.record(2, "failure_classified_model_unavailable", {
            "attempt_error_type": result.attempts[0].error_type,
            "llm_error_message_verbatim": excerpt,
            "http_status": call_primary.get("http_status"),
            "markers_hit": [m for m in llm_errors.MODEL_UNAVAILABLE_MARKERS
                            if m in excerpt.lower()],
            "probe_classification": (self.read_probe() or {}).get("classification"),
        }, lambda: [
            self.assertEqual("model_unavailable", result.attempts[0].error_type),
            self.assertEqual("model_unavailable", call_primary.get("error_kind")),
            self.assertEqual(500, call_primary.get("http_status")),
            self.assertGreaterEqual(len(excerpt), 20,
                                    "没有服务端原文摘要 = 无法复核这是真失败"),
            self.assertTrue(any(m in excerpt.lower()
                                for m in llm_errors.MODEL_UNAVAILABLE_MARKERS)
                            or any(p.search(excerpt.lower())
                                   for p in llm_errors.MODEL_UNAVAILABLE_PATTERNS),
                            "错误体不含 §6 的加载失败特征：归类与原文对不上"),
        ])

        # ③ fallback 被调（同一条链上的第二次真外呼）
        self.record(3, "fallback_called", {
            "attempts_count": len(result.attempts),
            "second_attempt": {"model_id": result.attempts[1].model_id,
                               "result": result.attempts[1].result,
                               "error_type": result.attempts[1].error_type,
                               "latency_ms": round(result.attempts[1].latency_ms, 1)}
            if len(result.attempts) > 1 else None,
            "egress_model": call_fallback.get("model"),
            "egress_request_bytes": call_fallback.get("request_bytes"),
            "egress_ok": call_fallback.get("ok"),
        }, lambda: [
            self.assertGreaterEqual(len(result.attempts), 2,
                                    "链上只有一枚 attempt ⇒ 根本没换模型"),
            self.assertEqual(kit.FALLBACK_ENTRY_ID, result.attempts[1].model_id),
            self.assertEqual("success", result.attempts[1].result),
            self.assertEqual(kit.FALLBACK_MODEL, call_fallback.get("model")),
            self.assertIs(True, call_fallback.get("ok")),
            self.assertEqual(2, len(self.provider_calls),
                             "真外呼次数不是 2：要么没走到 fallback，要么多走了"),
        ])

        # ④ phi3 给出**有效**中文回答（非空 + 长度下限 + 真含中文 + 不是拒答话术）
        answer = result.response.content or ""
        refusal_markers = ("未找到可靠依据", "没有找到", "依据不足", "无法回答")
        self.record(4, "phi3_valid_chinese_answer", {
            "chars": len(answer), "cjk_chars": len(kit._CJK.findall(answer)),
            "model_field": result.response.model,
            "answer_head": answer[:120],
            "min_chars": kit.MIN_ANSWER_CHARS,
            "min_cjk_chars": kit.MIN_ANSWER_CJK_CHARS,
        }, lambda: [
            self.assertTrue(answer.strip(), "空回答"),
            self.assertGreaterEqual(len(answer.strip()), kit.MIN_ANSWER_CHARS),
            self.assertGreaterEqual(len(kit._CJK.findall(answer)), kit.MIN_ANSWER_CJK_CHARS,
                                    "没有中文：§10 要的是「真实生成中文答案」"),
            self.assertNotIn(answer.strip(), refusal_markers,
                             "拿到的是「没有依据」的兜底文案，不是模型答案"),
            self.assertEqual(kit.FALLBACK_MODEL, result.response.model,
                             "响应的 model 字段不是真正答出这句话的那个模型"),
        ])

        # ⑤ fallback_index == 1
        self.record(5, "fallback_index_is_one", {
            "selected_index": result.selected_index,
            "reason_codes": list(result.reason_codes),
            "context_dropped": result.context_dropped,
        }, lambda: [
            self.assertEqual(1, result.selected_index),
            self.assertGreaterEqual(result.context_dropped, 0),
        ])

        # ⑥ trace_id 全链一致（入口 → 账本 → trace 落盘件）
        on_disk = self.read_trace_lines()
        trace_row = on_disk[-1] if on_disk else {}
        ledger_row = ledger_rows[0] if ledger_rows else {}
        self.record(6, "trace_id_consistent", {
            "entry_trace_id": self.trace_id,
            "ledger_trace_id": ledger_row.get("trace_id"),
            "trace_file_trace_id": trace_row.get("trace_id"),
            "request_id": self.request_id,
            "ledger_request_id": ledger_row.get("request_id"),
            "trace_file_count": len(on_disk),
        }, lambda: [
            self.assertEqual(1, len(on_disk), "trace 落盘件应该恰好一条"),
            self.assertEqual(self.trace_id, trace_row.get("trace_id")),
            self.assertEqual(self.trace_id, ledger_row.get("trace_id"),
                             "账本与 trace 的 trace_id 劈叉 = 全链不可对齐"),
            self.assertEqual(self.request_id, ledger_row.get("request_id")),
        ])

        # ⑦ model_route 两枚 attempt（九键 + attempts 逐枚同源）
        self.record(7, "model_route_two_attempts", {
            "keys": sorted(route.keys()),
            "attempts": route.get("attempts"),
            "stage": route.get("stage"),
            "selected_index": route.get("selected_index"),
            "primary": route.get("primary"),
        }, lambda: [
            self.assertEqual(set(MODEL_ROUTE_NINE_KEYS), set(route),
                             "九键不齐：#17 的交付物形状漂了"),
            self.assertEqual(2, len(route.get("attempts") or []),
                             "model_route 的 attempts 不是两枚"),
            self.assertEqual([kit.PRIMARY_MODEL, kit.FALLBACK_MODEL],
                             [a.get("model") for a in route["attempts"]]),
            self.assertEqual("model_unavailable", route["attempts"][0].get("error_type")),
            self.assertEqual("fallback", route.get("stage")),
            self.assertEqual(1, route.get("selected_index")),
        ])

        # ⑧ usage 落库一行（19 列的实测值整枚进证据）
        self.record(8, "usage_row_landed", {
            "rows": len(ledger_rows), "row": ledger_row,
            "ledger_path": str(self.temp_db),
            "tables_in_temp_db": kit.other_tables(self.temp_db),
        }, lambda: [
            self.assertEqual(1, len(ledger_rows),
                             "账本行数 != 1：P0 只该产出一行成功账"),
            self.assertEqual(kit.FALLBACK_MODEL, ledger_row.get("model")),
            self.assertEqual(1, ledger_row.get("fallback_index")),
            self.assertEqual(1, int(ledger_row.get("success") or 0)),
            self.assertEqual("rag", ledger_row.get("route_mode")),
            self.assertIn(ledger_row.get("error_type"), (None, ""),
                          "成功行携带 error_type：§8.1 第 2 条的口径破了"),
            self.assertGreater(int(ledger_row.get("total_tokens") or 0), 0,
                               "零 token 的账 = 这次生成其实没发生"),
        ])

        # ⑨ 零 prompt 入库（**全列**扫 canary，不挑列）
        needles = [kit.PROMPT_CANARY, QUESTION, EVIDENCE_ROW["content"][:24],
                   RAG_SYSTEM_PROMPT[:24], "请依据以下证据回答问题"]
        hits = kit.scan_cells(ledger_rows, needles) + kit.scan_cells(
            [{"id": None, "trace_file": json.dumps(on_disk, ensure_ascii=False)}], needles)
        self.record(9, "zero_prompt_stored", {
            "needles": needles, "hits": hits,
            "columns_scanned": sorted(ledger_row.keys()),
            "cells_scanned": len(ledger_rows) * max(1, len(ledger_row)),
        }, lambda: [
            self.assertEqual([], hits, "canary 出现在账本/trace 里：§8「永不存储」破防"),
        ])

        # ⑩ API 面 200 语义（见 `_http_face_200` 的口径说明）
        self.record(10, "api_face_is_200", lambda: self._http_face_200(answer),
                    lambda: [])

        # 收尾：环境后置 + 证据自洽性（十枚全 pass 才配 completed=true）
        with self.timed("08_assemble_evidence"):
            self.assemble_evidence(result, route, ledger_rows, trace_row, hits, needles,
                                   on_disk)
        with self.timed("09_postcheck"):
            self.evidence["environment"]["after"] = kit.ollama_inventory()
            self.evidence["environment"]["memory_after"] = kit.memory_facts()
        # `completed` / `timings_ms.total` 必须在**自校验之前**落定：`write_evidence` 是
        # cleanup（跑在断言之后），拿它的产物去自校验就是「先判卷再答卷」。
        self.evidence["timings_ms"]["total"] = round(
            (time.time() - self.started_wall) * 1000.0, 1)
        self.evidence["completed"] = True
        problems = kit.validate_evidence(self.evidence)
        self.evidence["self_validation_problems"] = problems
        with self.subTest("证据自校验（validate_evidence）"):
            self.assertEqual([], problems,
                             "证据不成立，矩阵就没有改 GREEN 的依据")
        self.evidence["green_permission"] = kit.green_permission()
        print(f"[P0] 全链耗时 {round(time.time() - self.started_wall, 1)} s；"
              f"矩阵许可判定 = {self.evidence['green_permission']['green_permitted_by_evidence']}"
              f"（当前矩阵 P0 状态 {self.evidence['green_permission']['matrix_status_now']}）",
              flush=True)

    # ------------------------------------------------------------------ 记账小工具
    def assemble_evidence(self, result, route: dict[str, Any],
                          ledger_rows: list[dict[str, Any]], trace_row: dict[str, Any],
                          hits: list[dict[str, Any]], needles: list[str],
                          on_disk: list[dict[str, Any]]) -> None:
        """把「证据 JSON 的机器判据字段」组装出来（`validate_evidence()` 读的就是这些）。

        放在断言之后、自校验之前：证据必须描述**这次真跑**留下的事实，而不是断言的复读——
        所以账本行、trace 行都是**从盘上重读**的（`ledger_rows` / `on_disk` 来自只读连接与
        真 JSONL），不是内存对象的副本。
        """
        self.evidence["provider_calls"] = self.provider_calls
        self.evidence["ledger"] = {
            "path": str(self.temp_db),
            "rows": len(ledger_rows),
            "row": ledger_rows[0] if ledger_rows else {},
            "canary_needles": needles,
            "canary_hits": hits,
            "tables": kit.other_tables(self.temp_db),
            "protected_repo_ledgers": kit.repo_ledger_row_counts(),
        }
        self.evidence["trace"] = {
            "path": str(self.temp_trace),
            "lines": len(on_disk),
            "trace_id": (trace_row or {}).get("trace_id"),
            "model_route_keys": sorted((route or {}).keys()),
            "model_route_attempts": (route or {}).get("attempts"),
            "model_route_stage": (route or {}).get("stage"),
            "model_route_selected_index": (route or {}).get("selected_index"),
        }
        self.evidence["chain"] = {
            "selected_index": result.selected_index,
            "reason_codes": list(result.reason_codes),
            "attempts": [{"model_id": a.model_id, "result": a.result,
                          "error_type": a.error_type} for a in result.attempts],
            "response_model": result.response.model,
        }
        # 证据**自己**与闸/矩阵文件都**不进**指纹表：
        # - 证据文件此刻还在被写，自指纹不可能成立（自引用）；
        # - `docs/MODEL_ROUTER_V23_MATRIX.md` 与 `test_real_llm_failover_gate.py` 是「因这份
        #   证据才允许改动」的对象，把它们钉进去会造成死锁（改完矩阵就判证据失效）。
        # `ACCEPTANCE_FILE` 进表是**刻意**的：跑完之后有人改过 P0 用例源码 ⇒ 这份证据描述的
        # 就不再是现在这份代码，必须重跑（stale 判定，不是洁癖）。
        self.evidence["sha1_scope_note"] = (
            "files_sha1 覆盖：临时库、临时 trace、A-2 探针件、本用例源码（stale 检测）。"
            "不含证据文件自身与矩阵/闸文件（见上）。")
        self.evidence["files_sha1"] = kit.fingerprint(
            [self.temp_db, self.temp_trace, kit.PROBE_FILE, kit.ACCEPTANCE_FILE])

    def record(self, number: int, name: str, observed, run) -> None:
        """跑那一枚断言，并把**实测值**留在证据里（红也留：残缺证据比没有证据可查）。

        `observed` 可以是 dict，也可以是「产出 dict 的可调用」——后者给需要**当场测量**的
        那一枚（#10 要打一次 HTTP 面）用，这样「测」与「记」在同一个 try 里，
        失败时 `observed` 仍会是空表 + `failure` 字样，而不是整枚消失。
        """
        entry: dict[str, Any] = {"id": number, "name": name, "observed": {},
                                 "pass": False}
        started = time.perf_counter()
        try:
            if callable(observed):
                entry["observed"] = observed()
            else:
                entry["observed"] = observed
            run()
        except BaseException as exc:
            entry["failure"] = f"{type(exc).__name__}: {exc}"
            entry["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
            self.evidence.setdefault("assertions", []).append(entry)
            raise
        entry["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        entry["pass"] = True
        self.evidence.setdefault("assertions", []).append(entry)
        print(f"[P0] 断言 {number} {name} PASS ({entry['elapsed_ms']} ms)", flush=True)

    def read_probe(self) -> dict[str, Any] | None:
        evidence, _error = kit.read_evidence(kit.PROBE_FILE)
        return (evidence or {}).get("probe") if evidence else None

    def read_trace_lines(self) -> list[dict[str, Any]]:
        if not self.temp_trace.is_file():
            return []
        return [json.loads(line) for line in
                self.temp_trace.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _http_face_200(self, answer: str) -> dict[str, Any]:
        """第 ⑩ 枚的口径：**状态码**，不再花一次真加载。

        `POST /api/query` 的实现（`app/main.py:484`）里，模型事实只经
        `generate_answer()` 的返回值进入响应体。本用例把「检索腿」和「生成腿」都换成
        **本次真跑已经拿到的事实**（检索腿本来就要 mock，容器状态不属于 P0 的对象；
        生成腿回放真答案），于是这一枚测的是那句话本身：
        「一次 `fallback_index=1` 的真结果在 API 面上是 200，而不是被错误吞成 5xx」。
        口径写在证据里，不假装它是端到端。
        """
        from fastapi.testclient import TestClient

        from app.main import app as fastapi_app

        rows = [dict(EVIDENCE_ROW)]
        with (mock.patch("app.main.safe_rows_with_timings",
                         return_value=(rows, {})),
              mock.patch("app.main.generate_answer", return_value=answer)):
            client = TestClient(fastapi_app)
            login = client.post("/api/auth/login",
                                json={"username": "admin", "password": "admin123"})
            self.assertEqual(200, login.status_code, login.text)
            response = client.post(
                "/api/query",
                headers={"Authorization": f"Bearer {login.json()['access_token']}"},
                json={"question": QUESTION, "k": 1, "include_sources": False})
        facts = {
            "caliber": "状态码口径：生成腿回放本次真答案（零第二次外呼），检索腿替身；"
                       "测的是「fallback 成功不塌成 5xx」",
            "status_code": response.status_code,
            "answer_equals_real": (response.json().get("answer") == answer
                                   if response.status_code == 200 else None),
            "model_used_field": response.json().get("model_used")
                                if response.status_code == 200 else None,
            "response_body_chars": len(response.text),
        }
        self.assertEqual(200, response.status_code,
                         f"API 面不是 200：{response.text[:300]}")
        self.assertEqual(answer, response.json().get("answer"))
        return facts


# ==========================================================================
# 收集门（A-1 闸②的对象）：**只**认 `REAL_LLM_ACCEPTANCE=1` 这一枚 env 开关。
# 默认关闭时把类从模块命名空间摘掉 ⇒ pytest 收集 0 枚（不是 skipped、也不会「跑成绿」）。
# 这条 if 里不许出现第二个条件、不许换成 skipUnless，也不许用 `__test__ = False` 之类的
# 旁路旗标——由 `test_real_llm_failover_gate.py` 逐条钉住（三向：源码面 / 收集面 / 运行面）。
# ==========================================================================
if not kit.acceptance_enabled():
    del RealLlmFailover001Tests

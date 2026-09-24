from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from collections import defaultdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "backend" / "eval_dataset_complex.json"
API = os.environ.get("YAOKE_API", "http://localhost:8001/api").rstrip("/")
MODES = ("vector", "bm25", "hybrid", "hybrid_rerank")
# CLI 门禁接受的运行档（设计 §3 五档）。`off` 也列出来，因为 `typesafe_enabled=false`
# 的恒定退路就是 off，验收时可能要断言"确实一档都没跑"。
TYPESAFE_MODES = ("off", "shadow", "selective", "active", "strict")


def percentile(values: list[float], quantile: float) -> float:
    """最近秩分位（与 `app.typesafe_judgments._percentile` 同口径）。空集返回 0。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(round(quantile * (len(ordered) - 1)), len(ordered) - 1)
    return ordered[index]


def call(
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict | None = None,
    timeout: int = 180,
) -> tuple[int, dict]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(API + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"detail": raw}
        return exc.code, body


def login(username: str, password: str) -> str:
    status, body = call(
        "POST",
        "/auth/login",
        payload={"username": username, "password": password},
        timeout=30,
    )
    if status != 200 or not body.get("access_token"):
        raise RuntimeError(f"login failed for {username}: HTTP {status} {body}")
    return str(body["access_token"])


def extract_typesafe_metrics(body: dict) -> dict | None:
    direct = body.get("typesafe")
    if isinstance(direct, dict) and direct:
        return dict(direct)
    timings = body.get("timings")
    if not isinstance(timings, dict):
        return None
    metrics = {
        key: value
        for key, value in timings.items()
        # `judge_input_count` is a TypeSafe metric that travels in the timing bag
        # without the prefix (it is whitelisted in app/security.py); the acceptance
        # reader must not silently drop it or the dynamic TopK observation is lost.
        if str(key).startswith("typesafe_") or key == "judge_input_count"
    }
    return metrics or None


def percentile(values: list[float], quantile: float) -> float:
    """最近秩分位。空集返回 0.0（与 `app.typesafe_judgments._percentile` 同口径）。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(round(quantile * (len(ordered) - 1)), len(ordered) - 1)
    return ordered[index]


def per_query_request_counts(samples: list[dict]) -> list[int]:
    """每查询外呼数分布（"按输出集计"口径）。

    单查询原始样本直接取 `typesafe_request_count`；已经聚合过一次的阶段汇总带着
    `per_query_request_counts` 走过来，展开它才不会把"整阶段总数"当成"一次查询的外呼数"
    塞进分位（那会把 P50/P95 拉成无意义的巨值）。
    """
    counts: list[int] = []
    for item in samples:
        carried = item.get("per_query_request_counts")
        if isinstance(carried, list) and carried:
            counts.extend(int(value or 0) for value in carried)
            continue
        counts.append(
            int(item.get("typesafe_request_count") or item.get("request_count") or 0)
        )
    return counts


def _stat_or_zero(values: list[float], stat: object) -> float:
    """空集给 0.0 而不是让 `statistics.median([])` 抛——零外呼的阶段本来就"没有分位"。"""
    return round(float(stat(values)), 2) if values else 0.0  # type: ignore[operator]


def _latency_values(samples: list[dict], *keys: str) -> list[float]:
    """判定段分位的取数集：**只收真的发过外呼的样本**。

    selective 档里路由免判/早退的查询压根没有 `typesafe_latency_*`（或恒 0），把它们
    塞进中位数会得到一个"看着达标"的假 P50。分位口径本身（对每查询批级分位再取中位/
    最大）与 V1 逐字相同，所以 strict/shadow 轮——那里每条样本都有外呼——读数不变。
    """
    values: list[float] = []
    for item in samples:
        made_calls = int(item.get("typesafe_request_count") or item.get("request_count") or 0) > 0
        if not made_calls:
            continue
        for key in keys:
            if item.get(key) is not None:
                values.append(float(item[key] or 0.0))
                break
    return values


def _merge_hist(samples: list[dict], carried_key: str, item_key: str) -> dict[str, int]:
    """把"每查询一个值"的观测键汇成频次表；阶段汇总（已汇过的表）直接累加透传。"""
    hist: dict[str, int] = defaultdict(int)
    for item in samples:
        carried = item.get(carried_key)
        if isinstance(carried, dict) and carried:
            for bucket, count in carried.items():
                hist[str(bucket)] += int(count or 0)
            continue
        value = item.get(item_key)
        if value is not None:
            hist[str(int(value))] += 1
    return {bucket: count for bucket, count in sorted(hist.items(), key=lambda kv: int(kv[0]))}


def summarize_typesafe(samples: list[dict]) -> dict | None:
    if not samples:
        return None

    modes_set: set[str] = set()
    models: set[str] = set()
    errors: set[str] = set()
    route_counts: dict[str, int] = defaultdict(int)
    for item in samples:
        raw_modes = item.get("modes") or []
        if isinstance(raw_modes, str):
            raw_modes = [raw_modes]
        modes_set.update(str(mode).strip() for mode in raw_modes if str(mode).strip())
        direct_mode = str(item.get("typesafe_mode") or item.get("mode") or "").strip()
        if direct_mode:
            modes_set.add(direct_mode)

        raw_models = item.get("typesafe_models") or item.get("models") or []
        if isinstance(raw_models, str):
            raw_models = [raw_models]
        models.update(str(model) for model in raw_models if str(model).strip())
        configured_model = str(item.get("model") or "").strip()
        if configured_model:
            models.add(configured_model)

        raw_errors = item.get("typesafe_errors") or item.get("errors") or []
        if isinstance(raw_errors, str):
            raw_errors = [raw_errors]
        errors.update(str(error) for error in raw_errors if str(error).strip())

        raw_routes = item.get("typesafe_route_counts") or item.get("route_counts") or {}
        if isinstance(raw_routes, dict):
            for route, count in raw_routes.items():
                route_counts[str(route)] += int(count or 0)

    modes = sorted(modes_set)

    # V2 观测聚合（设计 §3/§7）：路由免判、缓存命中、熔断主动避险与动态 TopK 落档。
    # 这些计数**不进任何通过/失败判定**——`validate_typesafe_gate` 的既有语义逐字保留，
    # 新增的只有 `--max-avg-typesafe-requests-per-query` 一条成本门禁。
    query_counts = per_query_request_counts(samples)

    return {
        "sample_count": sum(
            int(item.get("sample_count") or 0)
            if "sample_count" in item
            else 1
            for item in samples
        ),
        "mode": modes[0] if len(modes) == 1 else None,
        "modes": modes,
        "models": sorted(models),
        "degraded_cases": sum(
            int(item.get("degraded_cases") or 0)
            if "degraded_cases" in item
            else int(bool(item.get("typesafe_degraded")))
            for item in samples
        ),
        "triggered_cases": sum(
            int(item.get("triggered_cases") or 0)
            if "triggered_cases" in item
            else int(bool(item.get("typesafe_trigger")))
            for item in samples
        ),
        "router_skipped_cases": sum(
            int(item.get("router_skipped_cases") or 0)
            if "router_skipped_cases" in item
            else int(item.get("typesafe_skipped") == "router")
            for item in samples
        ),
        "circuit_open_cases": sum(
            int(item.get("circuit_open_cases") or 0)
            if "circuit_open_cases" in item
            else int(bool(item.get("typesafe_circuit_open")))
            for item in samples
        ),
        "cache_hit_requests": sum(
            int(item.get("cache_hit_requests") or 0)
            if "cache_hit_requests" in item
            else int(item.get("typesafe_cache_hit") or 0)
            for item in samples
        ),
        "slow_cases": sum(
            int(item.get("slow_cases") or 0)
            if "slow_cases" in item
            else int(bool(item.get("typesafe_slow")))
            for item in samples
        ),
        # 返回行数分布与"空结果但判定层没退化"的计数（Task 8 观测项）。
        "result_rows_hist": _merge_hist(
            samples, "result_rows_hist", "result_rows"
        ),
        "empty_result_cases": sum(
            int(item.get("empty_result_cases") or 0)
            if "empty_result_cases" in item
            else int(
                item.get("result_rows") is not None
                and int(item.get("result_rows") or 0) == 0
                and not item.get("typesafe_degraded")
            )
            for item in samples
        ),
        "judge_input_count_hist": _merge_hist(
            samples, "judge_input_count_hist", "judge_input_count"
        ),
        # 每查询外呼数分布（selective 成本门禁的分位口径来源）。
        "per_query_request_counts": query_counts,
        "requests_per_query_avg": round(
            (sum(query_counts) / len(query_counts)) if query_counts else 0.0, 4
        ),
        "requests_per_query_p50": round(percentile([float(v) for v in query_counts], 0.50), 2),
        "requests_per_query_p95": round(percentile([float(v) for v in query_counts], 0.95), 2),
        "request_count": sum(
            int(item.get("typesafe_request_count") or item.get("request_count") or 0)
            for item in samples
        ),
        "input_tokens": sum(
            int(item.get("typesafe_input_tokens") or item.get("input_tokens") or 0)
            for item in samples
        ),
        "output_tokens": sum(
            int(item.get("typesafe_output_tokens") or item.get("output_tokens") or 0)
            for item in samples
        ),
        "estimated_cost_usd": round(
            sum(
                float(
                    item.get("typesafe_estimated_cost_usd")
                    or item.get("estimated_cost_usd")
                    or 0.0
                )
                for item in samples
            ),
            8,
        ),
        # 判定段分位：**只在真的发过外呼的样本上统计**。selective 档一个查询里必然混着
        # 路由免判的零值样本，把它们一起进分位会把 P50 拉到 0 附近，得到一个"看起来达标"
        # 的假数字。strict/shadow 下每条样本都有外呼，本口径与 V1 报告的读数逐字相同。
        "latency_p50_ms": _stat_or_zero(
            _latency_values(samples, "typesafe_latency_p50_ms", "latency_p50_ms"),
            statistics.median,
        ),
        "latency_p95_ms": _stat_or_zero(
            _latency_values(samples, "typesafe_latency_p95_ms", "latency_p95_ms"),
            lambda values: max(values),
        ),
        "total_ms": round(
            sum(
                float(item.get("typesafe_total_ms") or item.get("total_ms") or 0.0)
                for item in samples
            ),
            2,
        ),
        "unauthorized_candidates_blocked": sum(
            int(
                item.get("typesafe_unauthorized_candidates_blocked")
                or item.get("unauthorized_candidates_blocked")
                or 0
            )
            for item in samples
        ),
        "route_counts": dict(sorted(route_counts.items())),
        "errors": sorted(errors),
    }


def combine_typesafe_summaries(summaries: list[dict]) -> dict | None:
    normalized: list[dict] = []
    for summary in summaries:
        if not summary:
            continue
        normalized.append(
            {
                "mode": summary.get("mode"),
                "modes": summary.get("modes") or [],
                "sample_count": summary.get("sample_count") or 0,
                "models": summary.get("models") or [],
                "errors": summary.get("errors") or [],
                "route_counts": summary.get("route_counts") or {},
                "degraded_cases": summary.get("degraded_cases") or 0,
                "triggered_cases": summary.get("triggered_cases") or 0,
                "router_skipped_cases": summary.get("router_skipped_cases") or 0,
                "circuit_open_cases": summary.get("circuit_open_cases") or 0,
                "cache_hit_requests": summary.get("cache_hit_requests") or 0,
                "slow_cases": summary.get("slow_cases") or 0,
                "judge_input_count_hist": summary.get("judge_input_count_hist") or {},
                "result_rows_hist": summary.get("result_rows_hist") or {},
                "empty_result_cases": summary.get("empty_result_cases") or 0,
                "per_query_request_counts": summary.get("per_query_request_counts") or [],
                "request_count": summary.get("request_count") or 0,
                "input_tokens": summary.get("input_tokens") or 0,
                "output_tokens": summary.get("output_tokens") or 0,
                "estimated_cost_usd": summary.get("estimated_cost_usd") or 0.0,
                "latency_p50_ms": summary.get("latency_p50_ms") or 0.0,
                "latency_p95_ms": summary.get("latency_p95_ms") or 0.0,
                "total_ms": summary.get("total_ms") or 0.0,
                "unauthorized_candidates_blocked": summary.get(
                    "unauthorized_candidates_blocked"
                )
                or 0,
            }
        )
    return summarize_typesafe(normalized)


def validate_typesafe_gate(
    summary: dict | None,
    *,
    required_stages: list[str],
    observed_stages: list[str],
    stage_summaries: dict[str, dict] | None = None,
    expected_stage_samples: dict[str, int] | None = None,
    require_typesafe: bool,
    expect_mode: str | None,
    max_degraded: int | None,
    min_requests: int | None,
    max_avg_requests_per_query: float | None = None,
) -> list[str]:
    gate_requested = bool(
        require_typesafe
        or expect_mode is not None
        or max_degraded is not None
        or min_requests is not None
        or max_avg_requests_per_query is not None
    )
    if not gate_requested:
        return []

    failures: list[str] = []
    stages = stage_summaries or {}
    expected_samples = expected_stage_samples or {}
    observed = set(observed_stages).union(stages)
    missing_stages = sorted(set(required_stages) - observed)
    if missing_stages:
        failures.append(f"missing TypeSafe metrics for stages: {', '.join(missing_stages)}")
    if summary is None:
        failures.append("no TypeSafe metrics were reported")
        return failures

    if require_typesafe:
        for stage_name in required_stages:
            stage = stages.get(stage_name)
            if not stage:
                continue
            stage_requests = int(stage.get("request_count") or 0)
            stage_modes = set(stage.get("modes") or ())
            stage_models = list(stage.get("models") or ())
            stage_degraded = int(stage.get("degraded_cases") or 0)
            stage_errors = list(stage.get("errors") or ())
            stage_blocked = int(stage.get("unauthorized_candidates_blocked") or 0)
            expected_count = int(expected_samples.get(stage_name) or 0)
            actual_count = int(stage.get("sample_count") or 0)
            if expected_count and actual_count != expected_count:
                failures.append(
                    f"TypeSafe stage {stage_name} metrics incomplete: "
                    f"{actual_count}/{expected_count} samples"
                )
            if stage_requests <= 0:
                failures.append(f"TypeSafe stage {stage_name} reported no real requests")
            if not stage_modes:
                failures.append(f"TypeSafe stage {stage_name} reported no runtime mode")
            if expect_mode is not None and stage_modes != {expect_mode}:
                failures.append(
                    f"TypeSafe stage {stage_name} mode mismatch: expected "
                    f"{expect_mode}, observed {sorted(stage_modes)}"
                )
            if not stage_models:
                failures.append(f"TypeSafe stage {stage_name} reported no response model")
            if stage_degraded:
                failures.append(
                    f"TypeSafe stage {stage_name} degraded in {stage_degraded} cases"
                )
            if stage_errors:
                failures.append(
                    f"TypeSafe stage {stage_name} reported errors: {stage_errors}"
                )
            if stage_blocked:
                failures.append(
                    f"TypeSafe stage {stage_name} sent {stage_blocked} unauthorized candidates"
                )

    effective_max_degraded = 0 if require_typesafe and max_degraded is None else max_degraded
    effective_min_requests = 1 if require_typesafe and min_requests is None else min_requests
    if (
        effective_max_degraded is not None
        and int(summary.get("degraded_cases") or 0) > effective_max_degraded
    ):
        failures.append(
            "TypeSafe degraded cases exceeded limit: "
            f"{summary.get('degraded_cases', 0)} > {effective_max_degraded}"
        )
    if (
        effective_min_requests is not None
        and int(summary.get("request_count") or 0) < effective_min_requests
    ):
        failures.append(
            "TypeSafe request count below minimum: "
            f"{summary.get('request_count', 0)} < {effective_min_requests}"
        )

    modes = set(summary.get("modes") or ())
    if expect_mode is not None and modes != {expect_mode}:
        failures.append(
            f"TypeSafe mode mismatch: expected {expect_mode}, observed {sorted(modes)}"
        )
    if require_typesafe and not modes:
        failures.append("TypeSafe runtime mode was not reported")
    if require_typesafe and not summary.get("models"):
        failures.append("TypeSafe response model was not reported")
    if require_typesafe and int(summary.get("unauthorized_candidates_blocked") or 0):
        failures.append(
            "unauthorized candidates reached the TypeSafe boundary: "
            f"{summary.get('unauthorized_candidates_blocked')}"
        )
    # V2 成本门禁：每查询外呼数（分位按**本次输出集**计，不用进程滚动窗口，
    # 否则一次跑挂两阶段会把 P95 摊平）。`--max-avg-typesafe-requests-per-query`
    # 卡的是均值，同时把 P50/P95 打进门禁文案，方便 spec §9 的 `P50≤4 / P95≤8` 读数。
    if max_avg_requests_per_query is not None:
        avg = summary.get("requests_per_query_avg")
        if avg is None:
            counts = per_query_request_counts([summary])
            avg = round((sum(counts) / len(counts)) if counts else 0.0, 4)
        if float(avg) > float(max_avg_requests_per_query):
            failures.append(
                "TypeSafe requests per query above limit: "
                f"avg={float(avg):.3f} "
                f"p50={float(summary.get('requests_per_query_p50') or 0.0):.2f} "
                f"p95={float(summary.get('requests_per_query_p95') or 0.0):.2f} "
                f"> {float(max_avg_requests_per_query):.3f}"
            )
    return failures


def print_typesafe_summary(label: str, summary: dict | None) -> None:
    if summary is None:
        return
    print(
        f"{label:>15}  mode={summary.get('mode') or summary.get('modes')}  "
        f"models={summary.get('models')}  requests={summary['request_count']}  "
        f"P50={summary['latency_p50_ms']:.1f}ms  "
        f"P95={summary['latency_p95_ms']:.1f}ms  "
        f"input={summary['input_tokens']}  output={summary['output_tokens']}  "
        f"cost=${summary['estimated_cost_usd']:.6f}  "
        f"total={summary['total_ms']:.1f}ms  "
        f"degraded={summary['degraded_cases']}  "
        f"blocked={summary['unauthorized_candidates_blocked']}  "
        f"errors={summary['errors']}"
    )
    print(
        f"{label:>15}  V2  samples={summary['sample_count']}  "
        f"triggered={summary.get('triggered_cases', 0)}  "
        f"router_skip={summary.get('router_skipped_cases', 0)}  "
        f"circuit_open={summary.get('circuit_open_cases', 0)}  "
        f"cache_hit={summary.get('cache_hit_requests', 0)}  "
        f"slow={summary.get('slow_cases', 0)}  "
        f"calls/query avg={summary.get('requests_per_query_avg', 0.0):.3f} "
        f"p50={summary.get('requests_per_query_p50', 0.0):.2f} "
        f"p95={summary.get('requests_per_query_p95', 0.0):.2f}  "
        f"judge_input_count={summary.get('judge_input_count_hist') or {}}"
    )


# GET /api/system/status 的判定层块（`app/security.py::public_typesafe_stats` 白名单后的
# 进程内滚动聚合）。只读白名单里点名的键，不做 `typesafe_*` 前缀透传——与响应面同纲。
ROLLUP_KEYS = (
    "mode",
    "breaker_state",
    "sample_count",
    "trigger_rate",
    "skip_rate",
    "cache_hit_ratio",
    "requests_per_query_p50",
    "requests_per_query_p95",
    "input_tokens_per_query_p50",
    "cost_per_query_p50",
    "timeout_rate",
    "degraded_rate",
    "latency_p50_ms",
    "latency_p95_ms",
)


def report_typesafe_rollup(token: str) -> dict:
    """打印服务端进程内滚动聚合（spec §9 的 calls/query 与判定段分位来源）。"""
    status, body = call("GET", "/system/status", token=token, timeout=60)
    if status != 200:
        print(f"[rollup] GET /api/system/status -> HTTP {status}: {body}")
        return {}
    block = body.get("typesafe")
    if not isinstance(block, dict):
        print("[rollup] /api/system/status 未返回 typesafe 块")
        return {}
    print("[rollup] GET /api/system/status -> typesafe 块（白名单聚合）")
    for key in ROLLUP_KEYS:
        if key in block:
            print(f"[rollup]   {key} = {block[key]}")
    for key in sorted(set(block) - set(ROLLUP_KEYS)):
        print(f"[rollup]   {key} = {block[key]}")
    return block


def summarize_case_observations(cases: list[dict], top_k: int) -> dict:
    """逐查询观测项（设计 §4/§9 的 Task 8 观察清单）。**只报数，不判门禁**。

    - `judge_input_count_hist`：动态 TopK 落档（3/4/6/8/12）占比。
    - `request_count_hist` / `result_rows_hist`：每查询真实外呼数与最终返回行数分布。
    - `all_excluded_gap_cases`：判定输入被 exclude 全中、导致返回行数不足 `top_k` 的题数。
    - `empty_result_non_degraded`：结果为空但判定层**没有**退化的题数（Task 6 尾部保留
      不变式的反例哨兵——理论上应为 0）。
    """
    request_hist: dict[str, int] = defaultdict(int)
    rows_hist: dict[str, int] = defaultdict(int)
    judge_hist: dict[str, int] = defaultdict(int)
    all_excluded_gap = 0
    empty_non_degraded = 0
    short_result = 0
    total_calls = 0
    for item in cases:
        requests = int(item.get("typesafe_request_count") or 0)
        rows = int(item.get("result_rows") or 0)
        judged = int(item.get("judge_input_count") or 0)
        excluded = int((item.get("typesafe_route_counts") or {}).get("exclude") or 0)
        degraded = bool(item.get("typesafe_degraded"))
        total_calls += requests
        request_hist[str(requests)] += 1
        rows_hist[str(rows)] += 1
        if judged:
            judge_hist[str(judged)] += 1
        if rows < top_k:
            short_result += 1
        if judged and excluded == judged and rows < top_k:
            all_excluded_gap += 1
        if rows == 0 and not degraded:
            empty_non_degraded += 1
    total = max(len(cases), 1)
    return {
        "cases": len(cases),
        "requests_per_query_avg": round(total_calls / len(cases), 4) if cases else 0.0,
        "judge_input_count_hist": {k: judge_hist[k] for k in sorted(judge_hist, key=int)},
        "judge_input_count_share": {
            k: round(judge_hist[k] / total, 4) for k in sorted(judge_hist, key=int)
        },
        "request_count_hist": {k: request_hist[k] for k in sorted(request_hist, key=int)},
        "result_rows_hist": {k: rows_hist[k] for k in sorted(rows_hist, key=int)},
        "short_result_cases": short_result,
        "all_excluded_gap_cases": all_excluded_gap,
        "empty_result_non_degraded_cases": empty_non_degraded,
    }


def observe_typesafe_cases(report: dict, top_k: int) -> dict:
    """把逐查询明细汇成观测块（逐模式），供 spec §9 的 Task 8 观察项读数。"""
    observed: dict[str, dict] = {}
    for mode, row in report.items():
        cases = row.get("typesafe_cases") if isinstance(row, dict) else None
        if cases:
            observed[mode] = summarize_case_observations(cases, top_k)
    return observed


def write_json_output(path: Path | None, payload: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def evaluate_retrieval(dataset: dict, token: str, top_k: int) -> tuple[dict, list[dict]]:
    report: dict[str, dict] = {}
    failures: list[dict] = []
    cases = list(dataset["retrieval_cases"])

    for eval_mode in MODES:
        mode = "hybrid" if eval_mode == "hybrid_rerank" else eval_mode
        rerank = eval_mode == "hybrid_rerank"
        started = time.perf_counter()
        hit_1 = 0
        hit_k = 0
        reciprocal_rank = 0.0
        category_stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        typesafe_samples: list[dict] = []
        case_observations: list[dict] = []

        for case in cases:
            status, body = call(
                "POST",
                "/retrieval/debug",
                token=token,
                payload={
                    "query": case["question"],
                    "mode": mode,
                    "top_k": top_k,
                    "rerank": rerank,
                    "knowledge_base_id": case["knowledge_base_id"],
                },
            )
            if status != 200:
                failures.append({"mode": eval_mode, "case": case["id"], "error": f"HTTP {status}"})
                continue

            metrics = extract_typesafe_metrics(body)
            if metrics:
                # 观测附加：每查询返回行数与逐查询路由计数（Task 8 的"结果=本地序"
                # 与"exclude 全中"两项只能在这里拿到——判定层本身看不到 diversify 的结果）。
                metrics["result_rows"] = len(body.get("results") or [])
                metrics["case_id"] = str(case["id"])
                typesafe_samples.append(metrics)
                case_observations.append(metrics)

            rows = body.get("results") or []
            names = [str(row.get("file_name") or "") for row in rows]
            accepted = set(case["acceptable_files"])
            rank = next((index + 1 for index, name in enumerate(names) if name in accepted), None)
            category_stats[case["category"]][1] += 1
            if rank == 1:
                hit_1 += 1
                category_stats[case["category"]][0] += 1
            if rank is not None and rank <= top_k:
                hit_k += 1
                reciprocal_rank += 1 / rank
            if rank != 1:
                failures.append(
                    {
                        "mode": eval_mode,
                        "case": case["id"],
                        "category": case["category"],
                        "question": case["question"],
                        "rank": rank,
                        "acceptable": sorted(accepted),
                        "top_files": names,
                    }
                )

        total = max(len(cases), 1)
        mode_report = {
            "total": len(cases),
            "hit_at_1": hit_1 / total,
            f"hit_at_{top_k}": hit_k / total,
            "mrr": reciprocal_rank / total,
            "elapsed_ms": (time.perf_counter() - started) * 1000,
            "categories": {
                category: {"hit_at_1": hits / total_cases, "total": total_cases}
                for category, (hits, total_cases) in sorted(category_stats.items())
            },
        }
        typesafe_summary = summarize_typesafe(typesafe_samples)
        if typesafe_summary:
            mode_report["typesafe"] = typesafe_summary
            # 逐查询观测明细（Task 8：`typesafe_request_count` × `len(final_rows)` 分布、
            # `judge_input_count` 落档、exclude 全中缺口、空结果且非 degraded 计数）。
            # 纯增量字段，不参与任何门禁判定。
            mode_report["typesafe_cases"] = case_observations
        report[eval_mode] = mode_report
    return report, failures


def evaluate_access(dataset: dict) -> tuple[int, int, list[str]]:
    credentials: dict[tuple[str, str], str] = {}
    failures: list[str] = []
    passed = 0
    total = 0

    def token_for(case: dict) -> str:
        key = (case["username"], case["password"])
        if key not in credentials:
            credentials[key] = login(*key)
        return credentials[key]

    for case in dataset.get("access_cases", []):
        total += 1
        status, _ = call(
            "POST",
            "/retrieval/debug",
            token=token_for(case),
            payload={
                "query": case["question"],
                "mode": "hybrid",
                "top_k": 3,
                "rerank": False,
                "knowledge_base_id": case["knowledge_base_id"],
            },
        )
        if status == int(case["expected_status"]):
            passed += 1
        else:
            failures.append(f"{case['id']}: expected HTTP {case['expected_status']}, got {status}")

    for case in dataset.get("scope_cases", []):
        total += 1
        status, body = call(
            "POST",
            "/retrieval/debug",
            token=token_for(case),
            payload={"query": case["question"], "mode": "hybrid", "top_k": 8, "rerank": False},
        )
        leaked = {
            str(row.get("knowledge_base_id") or "")
            for row in body.get("results") or []
        }.intersection(case["forbidden_knowledge_base_ids"])
        # retrieval/debug is an administrator capability in the current RBAC
        # model. A non-admin 403 with no result body is a stronger safe outcome;
        # if the endpoint is available, it must still return only authorized KBs.
        denied_safely = status == 403 and not body.get("results")
        scoped_safely = status == 200 and not leaked
        if denied_safely or scoped_safely:
            passed += 1
        else:
            failures.append(f"{case['id']}: HTTP {status}, leaked={sorted(leaked)}")
    return passed, total, failures


def evaluate_compound(
    dataset: dict,
    token: str,
) -> tuple[int, int, list[str], dict | None]:
    failures: list[str] = []
    typesafe_samples: list[dict] = []
    passed = 0
    cases = dataset.get("compound_cases", [])
    for case in cases:
        status, body = call(
            "POST",
            "/retrieval/debug",
            token=token,
            payload={
                "query": case["question"],
                "mode": "hybrid",
                "top_k": 8,
                "rerank": True,
                "knowledge_base_id": case["knowledge_base_id"],
            },
        )
        metrics = extract_typesafe_metrics(body)
        if metrics:
            metrics["result_rows"] = len(body.get("results") or [])
            metrics["case_id"] = str(case["id"])
            typesafe_samples.append(metrics)
        names = {str(row.get("file_name") or "") for row in body.get("results") or []}
        missing = set(case["required_files"]) - names
        if status == 200 and not missing:
            passed += 1
        else:
            failures.append(f"{case['id']}: HTTP {status}, missing={sorted(missing)}")
    return passed, len(cases), failures, summarize_typesafe(typesafe_samples)


def _message_sources(body: dict) -> set[str]:
    message = body.get("message") or {}
    rows = body.get("sources") or message.get("sources") or []
    return {str(row.get("file_name") or "") for row in rows}


def evaluate_llm_boundaries(
    dataset: dict,
    token: str,
    *,
    rerank: bool = False,
) -> tuple[int, int, list[str], dict | None]:
    failures: list[str] = []
    typesafe_samples: list[dict] = []
    passed = 0
    total = 0

    for case in dataset.get("conversation_cases", []):
        status, created = call(
            "POST",
            "/conversations",
            token=token,
            payload={"mode": "local", "knowledge_base_id": case["knowledge_base_id"]},
        )
        conversation_id = str(created.get("id") or "")
        if status != 201 or not conversation_id:
            total += len(case["turns"])
            failures.append(f"{case['id']}: conversation create HTTP {status}")
            continue
        try:
            for index, turn in enumerate(case["turns"], start=1):
                total += 1
                status, body = call(
                    "POST",
                    f"/conversations/{conversation_id}/messages",
                    token=token,
                    payload={
                        "content": turn["question"],
                        "mode": "local",
                        "knowledge_base_id": case["knowledge_base_id"],
                        "top_k": 5,
                        "rerank": rerank,
                    },
                    timeout=300,
                )
                metrics = extract_typesafe_metrics(body)
                if metrics:
                    metrics["result_rows"] = len(
                        body.get("sources")
                        or (body.get("message") or {}).get("sources")
                        or []
                    )
                    metrics["case_id"] = f"{case['id']}#{index}"
                    typesafe_samples.append(metrics)
                accepted = set(turn["acceptable_files"])
                sources = _message_sources(body)
                if status == 200 and sources.intersection(accepted):
                    passed += 1
                else:
                    failures.append(
                        f"{case['id']} turn={index}: HTTP {status}, sources={sorted(sources)}"
                    )
        finally:
            call("DELETE", f"/conversations/{conversation_id}", token=token)

    refusal_markers_default = ("没有", "未找到", "不足", "无法", "未提供")
    for case in dataset.get("no_answer_cases", []):
        total += 1
        status, created = call(
            "POST",
            "/conversations",
            token=token,
            payload={"mode": "local", "knowledge_base_id": case["knowledge_base_id"]},
        )
        conversation_id = str(created.get("id") or "")
        if status != 201 or not conversation_id:
            failures.append(f"{case['id']}: conversation create HTTP {status}")
            continue
        try:
            status, body = call(
                "POST",
                f"/conversations/{conversation_id}/messages",
                token=token,
                payload={
                    "content": case["question"],
                    "mode": "local",
                    "knowledge_base_id": case["knowledge_base_id"],
                    "top_k": 5,
                    "rerank": rerank,
                },
                timeout=300,
            )
            metrics = extract_typesafe_metrics(body)
            if metrics:
                typesafe_samples.append(metrics)
            answer = str((body.get("message") or {}).get("content") or body.get("answer") or "")
            markers = tuple(case.get("refusal_markers") or refusal_markers_default)
            if status == 200 and any(marker in answer for marker in markers):
                passed += 1
            else:
                failures.append(f"{case['id']}: HTTP {status}, answer={answer[:160]!r}")
        finally:
            call("DELETE", f"/conversations/{conversation_id}", token=token)
    return passed, total, failures, summarize_typesafe(typesafe_samples)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the yaoke complex retrieval and RBAC evaluation")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--min-hit1", type=float, default=0.90)
    parser.add_argument("--min-hit3", type=float, default=0.90)
    parser.add_argument("--min-mrr", type=float, default=0.90)
    parser.add_argument("--show-failures", type=int, default=20)
    parser.add_argument("--with-llm", action="store_true", help="also run live multi-turn and no-answer checks")
    parser.add_argument("--llm-only", action="store_true", help="run only live multi-turn and no-answer checks")
    parser.add_argument(
        "--rerank-llm-boundaries",
        action="store_true",
        help="enable the configured reranker for live multi-turn and no-answer checks",
    )
    parser.add_argument(
        "--require-typesafe",
        action="store_true",
        help="fail unless every requested TypeSafe stage reports real, non-degraded calls",
    )
    parser.add_argument(
        "--expect-typesafe-mode",
        choices=TYPESAFE_MODES,
        help="fail unless all observed TypeSafe stages report this runtime mode",
    )
    parser.add_argument(
        "--max-typesafe-degraded",
        type=int,
        help="maximum allowed degraded TypeSafe cases (default 0 with --require-typesafe)",
    )
    parser.add_argument(
        "--min-typesafe-requests",
        type=int,
        help="minimum aggregate TypeSafe request count (default 1 with --require-typesafe)",
    )
    parser.add_argument(
        "--max-avg-typesafe-requests-per-query",
        type=float,
        help=(
            "fail when the average TypeSafe requests per query exceeds this limit; "
            "the distribution is computed over this run's output set (not the server's "
            "rolling window), and stage P50/P95 are printed with the finding"
        ),
    )
    parser.add_argument(
        "--report-typesafe-rollup",
        action="store_true",
        help=(
            "print the server-side in-process TypeSafe aggregate from GET "
            "/api/system/status after the evaluation (whitelisted keys only)"
        ),
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="write the complete machine-readable evaluation report to this path",
    )
    args = parser.parse_args()

    try:
        if args.max_typesafe_degraded is not None and args.max_typesafe_degraded < 0:
            raise ValueError("--max-typesafe-degraded must be non-negative")
        if args.min_typesafe_requests is not None and args.min_typesafe_requests < 0:
            raise ValueError("--min-typesafe-requests must be non-negative")
        if (
            args.max_avg_typesafe_requests_per_query is not None
            and args.max_avg_typesafe_requests_per_query < 0
        ):
            raise ValueError("--max-avg-typesafe-requests-per-query must be non-negative")
        type_gate_requested = bool(
            args.require_typesafe
            or args.expect_typesafe_mode is not None
            or args.max_typesafe_degraded is not None
            or args.min_typesafe_requests is not None
            or args.max_avg_typesafe_requests_per_query is not None
        )
        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        admin_token = login("admin", "admin123")
        if args.llm_only:
            llm_passed, llm_total, llm_failures, llm_typesafe = evaluate_llm_boundaries(
                dataset,
                admin_token,
                rerank=args.rerank_llm_boundaries,
            )
            stage_summaries = {"live_llm": llm_typesafe} if llm_typesafe else {}
            aggregate_typesafe = combine_typesafe_summaries(
                list(stage_summaries.values())
            )
            type_gate_failures = validate_typesafe_gate(
                aggregate_typesafe,
                required_stages=["live_llm"] if type_gate_requested else [],
                observed_stages=list(stage_summaries),
                stage_summaries=stage_summaries,
                expected_stage_samples={"live_llm": llm_total},
                require_typesafe=args.require_typesafe,
                expect_mode=args.expect_typesafe_mode,
                max_degraded=args.max_typesafe_degraded,
                min_requests=args.min_typesafe_requests,
                max_avg_requests_per_query=args.max_avg_typesafe_requests_per_query,
            )
            print(f"Live LLM boundary: {llm_passed}/{llm_total} {'PASS' if llm_passed == llm_total else 'FAIL'}")
            print_typesafe_summary("TypeSafe", aggregate_typesafe)
            for failure in llm_failures:
                print(f"- {failure}")
            for failure in type_gate_failures:
                print(f"- TypeSafe gate: {failure}")
            gate_passed = llm_passed == llm_total and not type_gate_failures
            write_json_output(
                args.json_output,
                {
                    "dataset_version": dataset.get("version"),
                    "retrieval": {},
                    "access": {
                        "enabled": False,
                        "passed": 0,
                        "total": 0,
                        "failures": [],
                    },
                    "compound": {
                        "enabled": False,
                        "passed": 0,
                        "total": 0,
                        "failures": [],
                        "typesafe": None,
                    },
                    "live_llm": {
                        "enabled": True,
                        "rerank": args.rerank_llm_boundaries,
                        "passed": llm_passed,
                        "total": llm_total,
                        "failures": llm_failures,
                        "typesafe": llm_typesafe,
                    },
                    "typesafe": {
                        "stages": stage_summaries,
                        "aggregate": aggregate_typesafe,
                        "gate_failures": type_gate_failures,
                    },
                    "gate_passed": gate_passed,
                },
            )
            return 0 if gate_passed else 1
        report, retrieval_failures = evaluate_retrieval(dataset, admin_token, args.top_k)
        access_passed, access_total, access_failures = evaluate_access(dataset)
        compound_passed, compound_total, compound_failures, compound_typesafe = (
            evaluate_compound(dataset, admin_token)
        )
        llm_passed, llm_total, llm_failures, llm_typesafe = (0, 0, [], None)
        if args.with_llm:
            llm_passed, llm_total, llm_failures, llm_typesafe = evaluate_llm_boundaries(
                dataset,
                admin_token,
                rerank=args.rerank_llm_boundaries,
            )

        stage_summaries: dict[str, dict] = {
            mode: row["typesafe"]
            for mode, row in report.items()
            if row.get("typesafe")
        }
        if compound_typesafe:
            stage_summaries["compound"] = compound_typesafe
        if llm_typesafe:
            stage_summaries["live_llm"] = llm_typesafe
        aggregate_typesafe = combine_typesafe_summaries(list(stage_summaries.values()))
        required_typesafe_stages = ["hybrid_rerank", "compound"]
        if args.with_llm and type_gate_requested:
            required_typesafe_stages.append("live_llm")
        type_gate_failures = validate_typesafe_gate(
            aggregate_typesafe,
            required_stages=required_typesafe_stages,
            observed_stages=list(stage_summaries),
            stage_summaries=stage_summaries,
            expected_stage_samples={
                "hybrid_rerank": len(dataset["retrieval_cases"]),
                "compound": compound_total,
                "live_llm": llm_total,
            },
            require_typesafe=args.require_typesafe,
            expect_mode=args.expect_typesafe_mode,
            max_degraded=args.max_typesafe_degraded,
            min_requests=args.min_typesafe_requests,
            max_avg_requests_per_query=args.max_avg_typesafe_requests_per_query,
        )

        print(
            f"Complex dataset: {dataset['version']} "
            f"({len(dataset['retrieval_cases'])} retrieval + {compound_total} compound + "
            f"{access_total} access + {llm_total} live LLM cases)"
        )
        print()
        gate_failed = False
        for mode in MODES:
            row = report[mode]
            hit_k = row[f"hit_at_{args.top_k}"]
            passed = (
                row["hit_at_1"] >= args.min_hit1
                and hit_k >= args.min_hit3
                and row["mrr"] >= args.min_mrr
            )
            gate_failed = gate_failed or not passed
            print(
                f"{mode:>15}  H@1={row['hit_at_1']:.2%}  H@{args.top_k}={hit_k:.2%}  "
                f"MRR={row['mrr']:.3f}  elapsed={row['elapsed_ms']:.1f}ms  "
                f"{'PASS' if passed else 'FAIL'}"
            )
            if row.get("typesafe"):
                print_typesafe_summary("TypeSafe", row["typesafe"])

        print(f"{'RBAC / scope':>15}  {access_passed}/{access_total}  {'PASS' if access_passed == access_total else 'FAIL'}")
        gate_failed = gate_failed or access_passed != access_total
        print(f"{'Compound':>15}  {compound_passed}/{compound_total}  {'PASS' if compound_passed == compound_total else 'FAIL'}")
        gate_failed = gate_failed or compound_passed != compound_total
        print_typesafe_summary("TypeSafe cmp", compound_typesafe)
        if args.with_llm:
            print(f"{'Live LLM':>15}  {llm_passed}/{llm_total}  {'PASS' if llm_passed == llm_total else 'FAIL'}")
            gate_failed = gate_failed or llm_passed != llm_total
            print_typesafe_summary("TypeSafe LLM", llm_typesafe)

        print_typesafe_summary("TypeSafe all", aggregate_typesafe)
        observation = observe_typesafe_cases(report, args.top_k)
        for mode in MODES:
            if observation.get(mode):
                print(
                    f"{'Observation':>{15}}  [{mode}]  "
                    + json.dumps(observation[mode], ensure_ascii=False)
                )
        if type_gate_failures:
            gate_failed = True
            print("\nTypeSafe gate failures:")
            for failure in type_gate_failures:
                print(f"- {failure}")

        if retrieval_failures:
            print(f"\nTop-1 diagnostics (first {args.show_failures}):")
            for failure in retrieval_failures[: max(0, args.show_failures)]:
                if failure.get("question"):
                    print(
                        f"- [{failure['mode']}/{failure['category']}] {failure['case']} "
                        f"rank={failure['rank']} top1={(failure['top_files'] or [''])[0]}"
                    )
                else:
                    print(f"- [{failure['mode']}] {failure['case']} {failure['error']}")
        if access_failures:
            print("\nAccess failures:")
            for failure in access_failures:
                print(f"- {failure}")
        if compound_failures:
            print("\nCompound failures:")
            for failure in compound_failures:
                print(f"- {failure}")
        if llm_failures:
            print("\nLive LLM failures:")
            for failure in llm_failures:
                print(f"- {failure}")

        rollup = report_typesafe_rollup(admin_token) if args.report_typesafe_rollup else {}
        output_payload = {
            "dataset_version": dataset.get("version"),
            "retrieval": report,
            "access": {
                "enabled": True,
                "passed": access_passed,
                "total": access_total,
                "failures": access_failures,
            },
            "compound": {
                "enabled": True,
                "passed": compound_passed,
                "total": compound_total,
                "failures": compound_failures,
                "typesafe": compound_typesafe,
            },
            "live_llm": {
                "enabled": args.with_llm,
                "rerank": args.rerank_llm_boundaries,
                "passed": llm_passed,
                "total": llm_total,
                "failures": llm_failures,
                "typesafe": llm_typesafe,
            },
            "typesafe": {
                "stages": stage_summaries,
                "aggregate": aggregate_typesafe,
                "gate_failures": type_gate_failures,
                "rollup": rollup,
            },
            "observation": observation,
            "gate_passed": not gate_failed,
        }
        write_json_output(args.json_output, output_payload)
        print(f"\nComplex accuracy gate: {'FAIL' if gate_failed else 'PASS'}")
        return 1 if gate_failed else 0
    except (OSError, KeyError, ValueError, RuntimeError, URLError) as exc:
        error = f"{type(exc).__name__}: {exc}"
        print(f"[FAIL] {exc}")
        write_json_output(
            args.json_output,
            {
                "dataset_version": None,
                "retrieval": {},
                "access": {"enabled": False, "passed": 0, "total": 0, "failures": []},
                "compound": {
                    "enabled": False,
                    "passed": 0,
                    "total": 0,
                    "failures": [],
                    "typesafe": None,
                },
                "live_llm": {
                    "enabled": False,
                    "rerank": args.rerank_llm_boundaries,
                    "passed": 0,
                    "total": 0,
                    "failures": [],
                    "typesafe": None,
                },
                "typesafe": {"stages": {}, "aggregate": None, "gate_failures": []},
                "gate_passed": False,
                "error": error,
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

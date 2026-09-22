from __future__ import annotations

import argparse
import concurrent.futures
import statistics
import time
from dataclasses import dataclass

import httpx


@dataclass
class Sample:
    ok: bool
    latency_ms: float
    status_code: int
    error: str = ""


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * percent))))
    return ordered[index]


def one_request(
    *,
    api: str,
    token: str,
    question: str,
    kb: str | None,
    timeout: float,
) -> Sample:
    started = time.perf_counter()
    try:
        response = httpx.post(
            api.rstrip("/") + "/query",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "question": question,
                "k": 5,
                "include_sources": True,
                "use_hybrid_search": True,
                "use_reranking": False,
                "knowledge_base_id": kb,
            },
            timeout=timeout,
        )
        latency = (time.perf_counter() - started) * 1000
        return Sample(
            ok=response.status_code == 200,
            latency_ms=latency,
            status_code=response.status_code,
            error="" if response.status_code == 200 else response.text[:200],
        )
    except Exception as exc:
        return Sample(
            ok=False,
            latency_ms=(time.perf_counter() - started) * 1000,
            status_code=0,
            error=type(exc).__name__,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="yaoke release load/SLO gate")
    parser.add_argument("--api", default="http://localhost:8001/api")
    parser.add_argument("--token", required=True)
    parser.add_argument("--question", default="X200 的工作温度范围是多少？")
    parser.add_argument("--knowledge-base-id", default=None)
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=5000.0)
    args = parser.parse_args()

    total = max(1, args.requests)
    concurrency = max(1, min(args.concurrency, total))
    samples: list[Sample] = []
    started = time.perf_counter()

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(
                one_request,
                api=args.api,
                token=args.token,
                question=args.question,
                kb=args.knowledge_base_id,
                timeout=args.timeout,
            )
            for _ in range(total)
        ]
        for future in concurrent.futures.as_completed(futures):
            samples.append(future.result())

    elapsed = time.perf_counter() - started
    latencies = [sample.latency_ms for sample in samples]
    failures = [sample for sample in samples if not sample.ok]
    error_rate = len(failures) / max(1, len(samples))

    report = {
        "requests": len(samples),
        "concurrency": concurrency,
        "elapsed_seconds": round(elapsed, 3),
        "throughput_rps": round(len(samples) / max(elapsed, 0.001), 3),
        "success_rate": round(1.0 - error_rate, 4),
        "error_rate": round(error_rate, 4),
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 2) if latencies else 0.0,
            "p50": round(percentile(latencies, 0.50), 2),
            "p95": round(percentile(latencies, 0.95), 2),
            "max": round(max(latencies), 2) if latencies else 0.0,
        },
        "failure_statuses": sorted({sample.status_code for sample in failures}),
        "failure_examples": [sample.error for sample in failures[:3]],
    }
    print(report)

    if error_rate > args.max_error_rate:
        print("SLO_GATE=FAIL error_rate")
        return 1
    if percentile(latencies, 0.95) > args.max_p95_ms:
        print("SLO_GATE=FAIL p95")
        return 1
    print("SLO_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

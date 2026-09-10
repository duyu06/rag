from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API = os.environ.get("YAOKE_API", "http://localhost:8001/api").rstrip("/")


def call(method: str, path: str, *, token: str | None = None, payload: dict | None = None, timeout: int = 120):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(API + path, data=data, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return response.status, json.loads(raw) if raw else {}


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * percentile_value))
    return ordered[max(0, min(index, len(ordered) - 1))]


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark yaoke retrieval latency")
    parser.add_argument("--query", default="X100 产品整机保修期多久？")
    parser.add_argument("--kb", default="kb_product")
    parser.add_argument("--mode", choices=["vector", "bm25", "hybrid"], default="hybrid")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--rerank", action="store_true")
    args = parser.parse_args()

    try:
        status, login = call(
            "POST",
            "/auth/login",
            payload={"username": "admin", "password": "admin123"},
            timeout=20,
        )
        if status != 200:
            raise RuntimeError(f"login failed: HTTP {status}")
        token = str(login.get("access_token") or "")
        if not token:
            raise RuntimeError("login response missing access_token")

        payload = {
            "query": args.query,
            "mode": args.mode,
            "top_k": args.top_k,
            "rerank": args.rerank,
            "knowledge_base_id": args.kb,
        }

        samples: list[float] = []
        cache_hits: list[bool | None] = []
        total_rounds = max(2, args.rounds)
        print(f"API:   {API}")
        print(f"Mode:  {args.mode}  KB: {args.kb}  rerank={args.rerank}")
        print(f"Query: {args.query}")
        print()

        for index in range(total_rounds):
            started = time.perf_counter()
            status, result = call("POST", "/retrieval/debug", token=token, payload=payload)
            elapsed_ms = (time.perf_counter() - started) * 1000
            if status != 200:
                raise RuntimeError(f"retrieval failed: HTTP {status}: {result}")
            rows = result.get("results") or []
            cache_hit = rows[0].get("bm25_cache_hit") if rows else None
            cache_hits.append(cache_hit)
            samples.append(elapsed_ms)
            label = "cold" if index == 0 else f"warm-{index}"
            print(
                f"{label:>7}: {elapsed_ms:8.2f} ms  "
                f"results={len(rows):2d}  bm25_cache_hit={cache_hit}"
            )

        cold = samples[0]
        warm = samples[1:]
        print("\nSummary")
        print(f"cold:      {cold:.2f} ms")
        print(f"warm avg:  {statistics.mean(warm):.2f} ms")
        print(f"warm P50:  {statistics.median(warm):.2f} ms")
        print(f"warm P95:  {percentile(warm, 0.95):.2f} ms")
        if args.mode in {"bm25", "hybrid"}:
            warm_hits = [value for value in cache_hits[1:] if value is not None]
            if warm_hits and not all(warm_hits):
                raise RuntimeError("BM25 warm queries did not consistently hit cache")
            print("BM25 warm cache: PASS")
        return 0
    except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        print(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

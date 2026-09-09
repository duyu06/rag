from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

AUDIT_PATH = Path("data/audit.jsonl")
_LOCK = Lock()


def record_event(
    *,
    username: str,
    role: str,
    action: str,
    status: str = "SUCCESS",
    knowledge_base_id: str | None = None,
    query: str | None = None,
    latency_ms: float | None = None,
    num_sources: int | None = None,
    detail: str | None = None,
) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    event: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "username": username,
        "role": role,
        "action": action,
        "status": status,
    }
    optional = {
        "knowledge_base_id": knowledge_base_id,
        "query": query,
        "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
        "num_sources": num_sources,
        "detail": detail,
    }
    event.update({key: value for key, value in optional.items() if value is not None})
    line = json.dumps(event, ensure_ascii=False)
    with _LOCK:
        with AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def recent_events(limit: int = 100) -> list[dict[str, Any]]:
    if not AUDIT_PATH.exists():
        return []
    with _LOCK:
        lines = AUDIT_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    events: list[dict[str, Any]] = []
    for line in reversed(lines[-max(limit * 3, limit) :]):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(events) >= limit:
            break
    return events


def today_summary() -> dict[str, Any]:
    today = datetime.now(timezone.utc).date().isoformat()
    events = [item for item in recent_events(5000) if str(item.get("timestamp", "")).startswith(today)]
    queries = [item for item in events if item.get("action") == "QUERY" and item.get("status") == "SUCCESS"]
    denied = [item for item in events if item.get("status") == "DENIED"]
    latencies = [float(item["latency_ms"]) for item in queries if item.get("latency_ms") is not None]
    return {
        "today_queries": len(queries),
        "denied_access": len(denied),
        "avg_query_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
        "events_today": len(events),
    }

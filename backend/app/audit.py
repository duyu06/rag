from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from pydantic import SecretStr

from app.config import settings

AUDIT_PATH = Path("data/audit.jsonl")
_LOCK = Lock()

_SECRET_PATTERNS = [
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+"),
]


def _secret(value: SecretStr | str | None) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value or "")


def _redact(value: str | None, *, max_chars: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]", text)
    if max_chars is not None and max_chars >= 0:
        text = text[:max_chars]
    return text


def _last_event_hash() -> str:
    if not AUDIT_PATH.exists():
        return ""
    try:
        lines = AUDIT_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_hash = str(item.get("event_hash") or "")
        if event_hash:
            return event_hash
    return ""


def _event_hash(event: dict[str, Any], previous_hash: str) -> tuple[str, str]:
    payload = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    data = (previous_hash + "\n" + payload).encode("utf-8")
    key = _secret(settings.audit_hmac_key).encode("utf-8")
    if key:
        return "hmac-sha256", hmac.new(key, data, hashlib.sha256).hexdigest()
    return "sha256-chain", hashlib.sha256(data).hexdigest()


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
        "username": _redact(username, max_chars=128) or "unknown",
        "role": _redact(role, max_chars=32) or "UNKNOWN",
        "action": _redact(action, max_chars=64) or "UNKNOWN",
        "status": _redact(status, max_chars=32) or "UNKNOWN",
    }
    optional = {
        "knowledge_base_id": _redact(knowledge_base_id, max_chars=128),
        "query": _redact(query, max_chars=int(settings.audit_query_max_chars)),
        "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
        "num_sources": num_sources,
        "detail": _redact(detail, max_chars=1000),
    }
    event.update({key: value for key, value in optional.items() if value is not None})

    with _LOCK:
        previous_hash = _last_event_hash()
        hash_mode, event_hash = _event_hash(event, previous_hash)
        event["prev_hash"] = previous_hash or None
        event["hash_mode"] = hash_mode
        event["event_hash"] = event_hash
        line = json.dumps(event, ensure_ascii=False)
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


def verify_audit_chain() -> dict[str, Any]:
    if not AUDIT_PATH.exists():
        return {"valid": True, "checked": 0, "legacy_unhashed": 0}

    key = _secret(settings.audit_hmac_key).encode("utf-8")
    with _LOCK:
        lines = AUDIT_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()

    previous_hash = ""
    checked = 0
    legacy_unhashed = 0
    for index, line in enumerate(lines, start=1):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            return {"valid": False, "checked": checked, "line": index, "reason": "invalid_json"}

        stored_hash = str(item.pop("event_hash", "") or "")
        stored_prev = str(item.pop("prev_hash", "") or "")
        hash_mode = str(item.pop("hash_mode", "") or "")
        if not stored_hash:
            legacy_unhashed += 1
            continue
        if stored_prev != previous_hash:
            return {"valid": False, "checked": checked, "line": index, "reason": "prev_hash_mismatch"}

        payload = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        data = (previous_hash + "\n" + payload).encode("utf-8")
        if hash_mode == "hmac-sha256":
            if not key:
                return {"valid": False, "checked": checked, "line": index, "reason": "missing_hmac_key"}
            expected = hmac.new(key, data, hashlib.sha256).hexdigest()
        else:
            expected = hashlib.sha256(data).hexdigest()
        if not hmac.compare_digest(stored_hash, expected):
            return {"valid": False, "checked": checked, "line": index, "reason": "hash_mismatch"}
        previous_hash = stored_hash
        checked += 1

    return {"valid": True, "checked": checked, "legacy_unhashed": legacy_unhashed}


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

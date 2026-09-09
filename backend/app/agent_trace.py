from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

TRACE_PATH = Path("data/agent_traces.jsonl")
_LOCK = Lock()


def new_trace_id() -> str:
    return uuid4().hex


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_args(arguments: dict[str, Any]) -> dict[str, Any]:
    """Keep debugger useful without persisting full potentially-sensitive prompts."""
    allowed: dict[str, Any] = {}
    for key in ("knowledge_base_id", "top_k", "max_results"):
        if key in arguments:
            allowed[key] = arguments[key]
    if "query" in arguments:
        allowed["query_preview"] = str(arguments["query"])[:180]
    return allowed


def save_trace(trace: dict[str, Any]) -> None:
    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(trace, ensure_ascii=False)
    with _LOCK:
        with TRACE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def get_trace(trace_id: str) -> dict[str, Any] | None:
    if not TRACE_PATH.exists():
        return None
    with _LOCK:
        lines = TRACE_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("trace_id") == trace_id:
            return item
    return None

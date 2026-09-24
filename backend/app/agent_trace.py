from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from app.security import redact_secrets, redact_text

TRACE_PATH = Path("data/agent_traces.jsonl")
_LOCK = Lock()
logger = logging.getLogger("app.agent_trace")

#: §8 里 trace 新增的那个对象的键名。**唯一出处**：三条链写、TraceView 读，都引这个常量。
MODEL_ROUTE_KEY = "model_route"


def new_trace_id() -> str:
    return uuid4().hex


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def attach_model_route(trace: dict[str, Any], plan: Any, result: Any, *,
                       profile: Any = None) -> dict[str, Any]:
    """把 §8 的 `model_route` 对象挂到一条 trace 上——**Task 6/7/8 的一行接缝**。

    本轮（Task 5）只建接缝并钉契约：今天 `rag.py` / `conversation_agent.py` / `agent.py`
    三条链都还没走 `llm.complete/stream`（那是 T6/T7/T8 的迁移），所以业务代码里没有任何
    调用点。迁移时的**义务**是在各自收尾处写这一行::

        attach_model_route(trace, plan, result, profile=profile)   # result 亦可为
                                                                   # StreamSummary

    三条口径：
    - **additive**：只写 `trace["model_route"]` 这一个键，已有事件与字段一个都不动（§9
      「既有响应结构对外不变」）。键值本身是 `app.llm.usage.model_route_trace()` 的产出，
      只含机器码与模型名——query、prompt、context、reasoning 在其中没有落点。
    - **fail-open**：构造失败（传错类型、注册表读不到）只记 warning 并原样返回 trace。
      「解释这次为什么用这个模型」是观测面：它塌了不能把一次已经成功的生成变成 500，
      也不能让一条 trace 因此整个丢掉（与 §8 的记账同一语义）。
    - 局部 import `app.llm.usage`：`agent_trace` 在 import 图上比 llm 包更底层（`rag.py`、
      `agent.py`、审计都引它），把 httpx / 注册表那串依赖挂到模块顶层等于让每个 import
      本文件的人背上整个 llm 包——而这里只在路由真的跑过时才需要它。
    """
    try:
        from app.llm.usage import model_route_trace
        trace[MODEL_ROUTE_KEY] = model_route_trace(plan, result, profile=profile)
    except Exception as exc:                            # noqa: BLE001 - 观测面 fail-open
        logger.warning("trace 的 model_route 未挂载（不影响生成）：%s: %s",
                       type(exc).__name__, exc)
    return trace


def public_args(arguments: dict[str, Any]) -> dict[str, Any]:
    """Keep debugger useful without persisting full potentially-sensitive prompts."""
    allowed: dict[str, Any] = {}
    for key in ("knowledge_base_id", "top_k", "max_results"):
        if key in arguments:
            allowed[key] = arguments[key]
    if "query" in arguments:
        allowed["query_preview"] = redact_text(arguments["query"])[:180]
    return allowed


def save_trace(trace: dict[str, Any]) -> None:
    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(redact_secrets(trace), ensure_ascii=False)
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
            # Keep legacy trace rows safe when served through the debugger.
            return redact_secrets(item)
    return None

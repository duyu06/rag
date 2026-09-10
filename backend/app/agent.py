from __future__ import annotations

import json
import time
from typing import Any, Literal

import httpx

from app.agent_trace import new_trace_id, public_args, save_trace, utc_now
from app.audit import record_event
from app.auth import CurrentUser
from app.config import settings
from app.knowledge import allowed_ids, visible_bases
from app.tools.base import AgentMode, ToolContext, ToolExecutionError
from app.tools.registry import tool_registry

AGENT_SYSTEM_PROMPT = """You are yaoke Agent running with the local Ornith model.
You may answer simple conversation directly, but factual enterprise or current external questions should use tools.
Rules:
1. Internal policies, HR, product parameters, sales rules and after-sales SOPs: use enterprise_search.
2. Current public news, public releases, industry trends or external facts: use web_search when the current mode allows it.
3. Never use public web results to override internal enterprise policy. Enterprise evidence has priority for internal facts.
4. Never claim access to data a tool denied. Authorization belongs to the backend, not to you.
5. Cite evidence with [1], [2], etc. using the citation_index returned by tools. Do not invent citation numbers.
6. If evidence is insufficient, say so clearly instead of fabricating.
7. Do not reveal chain-of-thought or hidden reasoning. Only return the final answer and tool calls supported by the API.
"""


def _mode_prompt(mode: AgentMode) -> str:
    if mode == "local":
        return "Mode=local. Web search is forbidden. Use enterprise_search for factual knowledge questions."
    if mode == "web":
        return "Mode=web. Use web_search for current/external facts; use enterprise_search for internal company facts."
    return "Mode=auto. Choose enterprise_search for internal facts and web_search only when public/current information is needed."


def _ollama_chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": settings.ollama_model,
        "stream": False,
        "think": True,
        "messages": messages,
        "tools": tools,
        "options": {"temperature": 0.2},
    }
    response = httpx.post(
        settings.ollama_base_url.rstrip("/") + "/api/chat",
        json=payload,
        timeout=settings.agent_llm_timeout_seconds,
    )
    response.raise_for_status()
    message = response.json().get("message")
    if not isinstance(message, dict):
        raise RuntimeError("Ollama 返回缺少 message")
    return message


def _tool_arguments(call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    function = call.get("function") if isinstance(call, dict) else None
    if not isinstance(function, dict):
        return "", {}
    name = str(function.get("name") or "")
    arguments = function.get("arguments") or {}
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            arguments = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            arguments = {}
    return name, arguments if isinstance(arguments, dict) else {}


def _evidence_key(item: dict[str, Any]) -> tuple[Any, ...]:
    if item.get("source_type") == "web":
        return ("web", item.get("url"))
    return (
        "enterprise",
        item.get("knowledge_base_id"),
        item.get("file_name"),
        item.get("page"),
        str(item.get("content") or "")[:120],
    )


def _public_source(item: dict[str, Any]) -> dict[str, Any]:
    preview = str(item.get("content") or "")[:420]
    if item.get("source_type") == "web" and item.get("url"):
        preview = f"{preview}\n{item['url']}"
    return {
        "citation_index": item.get("citation_index"),
        "source_type": item.get("source_type", "enterprise"),
        "title": item.get("title") or item.get("file_name"),
        "file_name": item.get("file_name") or item.get("title") or "来源",
        "page": item.get("page"),
        "content_preview": preview,
        "relevance_score": item.get("relevance_score"),
        "knowledge_base_id": item.get("knowledge_base_id"),
        "knowledge_base_name": item.get("knowledge_base_name"),
        "url": item.get("url"),
        "domain": item.get("domain"),
    }


def _conversation_history(history: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    limit = max(0, int(settings.agent_history_max_messages))
    if limit == 0 or not history:
        return []
    normalized: list[dict[str, str]] = []
    for item in history:
        role = str(item.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        if item.get("status") not in {None, "completed"}:
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        normalized.append({"role": role, "content": content[:4000]})
    return normalized[-limit:]


def run_agent(
    *,
    question: str,
    user: CurrentUser,
    mode: AgentMode = "auto",
    knowledge_base_id: str | None = None,
    top_k: int = 5,
    rerank: bool = False,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if mode not in {"local", "auto", "web"}:
        raise ValueError("无效 Agent 模式")

    trace_id = new_trace_id()
    started = time.perf_counter()
    allowed = allowed_ids(user.role)
    visible = ", ".join(f"{item['id']}={item['name']}" for item in visible_bases(user.role))
    history_messages = _conversation_history(history)
    system = (
        AGENT_SYSTEM_PROMPT
        + "\n"
        + _mode_prompt(mode)
        + f"\nCurrent role={user.role}; backend-authorized KBs: {visible}."
        + " Do not assume any KB outside this list is accessible."
        + (" Use recent conversation messages only to resolve follow-up references; current tool evidence remains authoritative." if history_messages else "")
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        *history_messages,
        {"role": "user", "content": question.strip()},
    ]
    schemas = tool_registry.schemas(mode)
    events: list[dict[str, Any]] = [
        {
            "type": "user",
            "timestamp": utc_now(),
            "mode": mode,
            "question_preview": question[:240],
            "allowed_knowledge_base_ids": allowed,
            "context_messages": len(history_messages),
        }
    ]
    evidence: list[dict[str, Any]] = []
    evidence_keys: dict[tuple[Any, ...], int] = {}
    final_answer = ""
    max_rounds = max(1, min(int(settings.agent_max_tool_rounds), 6))

    for round_index in range(1, max_rounds + 1):
        message = _ollama_chat(messages, schemas)
        tool_calls = message.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            tool_calls = []

        if not tool_calls:
            final_answer = str(message.get("content") or "").strip()
            events.append(
                {
                    "type": "final",
                    "timestamp": utc_now(),
                    "round": round_index,
                    "answer_preview": final_answer[:400],
                }
            )
            break

        messages.append(message)
        decisions: list[str] = []
        for call in tool_calls:
            tool_name, arguments = _tool_arguments(call)
            decisions.append(tool_name or "unknown")
        events.append(
            {
                "type": "model_decision",
                "timestamp": utc_now(),
                "round": round_index,
                "tools": decisions,
            }
        )

        for call in tool_calls:
            tool_name, arguments = _tool_arguments(call)
            tool_started = time.perf_counter()
            safe_arguments = public_args(arguments)
            events.append(
                {
                    "type": "tool_start",
                    "timestamp": utc_now(),
                    "round": round_index,
                    "tool": tool_name,
                    "arguments": safe_arguments,
                }
            )
            record_event(
                username=user.username,
                role=user.role,
                action="TOOL_CALL",
                query=str(arguments.get("query") or "")[:240] or None,
                detail=f"tool={tool_name};trace_id={trace_id};args={json.dumps(safe_arguments, ensure_ascii=False)}",
            )

            context = ToolContext(
                username=user.username,
                role=user.role,
                mode=mode,
                trace_id=trace_id,
                selected_knowledge_base_id=knowledge_base_id,
                top_k=top_k,
                rerank=rerank,
            )
            status = "SUCCESS"
            try:
                result = tool_registry.execute(tool_name, arguments, context)
                for item in result.get("evidence", []):
                    key = _evidence_key(item)
                    if key not in evidence_keys:
                        evidence_keys[key] = len(evidence) + 1
                        item = dict(item)
                        item["citation_index"] = evidence_keys[key]
                        evidence.append(item)
                    else:
                        item["citation_index"] = evidence_keys[key]
                result = dict(result)
                result["evidence"] = [
                    {**item, "citation_index": evidence_keys.get(_evidence_key(item))}
                    for item in result.get("evidence", [])
                ]
            except ToolExecutionError as exc:
                status = exc.status
                result = {"ok": False, "tool": tool_name, "status": exc.status, "error": str(exc), "evidence": []}
            except Exception as exc:
                status = "FAILED"
                result = {"ok": False, "tool": tool_name, "status": "FAILED", "error": f"{type(exc).__name__}: {exc}", "evidence": []}

            latency_ms = (time.perf_counter() - tool_started) * 1000
            result_count = len(result.get("evidence", []))
            events.append(
                {
                    "type": "tool_end",
                    "timestamp": utc_now(),
                    "round": round_index,
                    "tool": tool_name,
                    "status": status,
                    "latency_ms": round(latency_ms, 2),
                    "result_count": result_count,
                }
            )
            record_event(
                username=user.username,
                role=user.role,
                action="TOOL_RESULT",
                status=status,
                knowledge_base_id=str(arguments.get("knowledge_base_id") or knowledge_base_id or "all") if tool_name == "enterprise_search" else None,
                latency_ms=latency_ms,
                num_sources=result_count,
                detail=f"tool={tool_name};trace_id={trace_id}",
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_name": tool_name or "unknown",
                    "content": json.dumps(result, ensure_ascii=False)[:16000],
                }
            )
    else:
        messages.append(
            {
                "role": "system",
                "content": "Tool-call limit reached. Do not call more tools. Produce a final answer only from tool results already present; cite their citation_index values.",
            }
        )
        message = _ollama_chat(messages, [])
        final_answer = str(message.get("content") or "").strip()
        events.append(
            {
                "type": "limit",
                "timestamp": utc_now(),
                "max_tool_rounds": max_rounds,
            }
        )
        events.append(
            {
                "type": "final",
                "timestamp": utc_now(),
                "answer_preview": final_answer[:400],
            }
        )

    if not final_answer:
        final_answer = "当前没有获得足够证据生成可靠答案。"

    elapsed_ms = (time.perf_counter() - started) * 1000
    trace = {
        "trace_id": trace_id,
        "timestamp": utc_now(),
        "username": user.username,
        "role": user.role,
        "mode": mode,
        "model": settings.ollama_model,
        "max_tool_rounds": max_rounds,
        "context_messages": len(history_messages),
        "events": events,
        "evidence_count": len(evidence),
        "elapsed_ms": round(elapsed_ms, 2),
    }
    save_trace(trace)
    record_event(
        username=user.username,
        role=user.role,
        action="QUERY",
        knowledge_base_id=knowledge_base_id or "all",
        query=question[:500],
        latency_ms=elapsed_ms,
        num_sources=len(evidence),
        detail=f"agent_mode={mode};trace_id={trace_id}",
    )

    return {
        "answer": final_answer,
        "query": question,
        "mode": mode,
        "trace_id": trace_id,
        "sources": [_public_source(item) for item in evidence],
        "num_sources": len(evidence),
        "model_used": settings.ollama_model,
        "max_tool_rounds": max_rounds,
        "context_messages": len(history_messages),
    }

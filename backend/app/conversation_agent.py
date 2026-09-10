from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

import app.agent as agent_module
from app.agent_trace import new_trace_id, save_trace, utc_now
from app.audit import record_event
from app.auth import CurrentUser
from app.config import settings
from app.knowledge import allowed_ids, visible_bases
from app.native_stream import ollama_chat_stream
from app.tools.base import AgentMode, ToolContext, ToolExecutionError
from app.tools.registry import tool_registry

ENTITY_PATTERN = re.compile(r"(?i)(?<![a-z0-9])[a-z]{1,12}[-_]?\d+[a-z0-9_-]*(?![a-z0-9])")


def _entity_family(value: str) -> str:
    """Return the alphabetic identifier family (X100 -> x, IP67 -> ip)."""
    match = re.match(r"(?i)^([a-z]{1,12})[-_]?\d", value.strip())
    return match.group(1).lower() if match else ""


def _contextual_retrieval_query(
    question: str,
    history_messages: list[dict[str, str]],
) -> tuple[str, bool]:
    """Enrich short follow-ups from recent context without another LLM call.

    A new identifier only replaces a stale identifier from the same family. This
    lets X200 replace X100 while preserving unrelated identifiers such as IP65,
    and lets an IP67 follow-up replace IP65 without dropping the product entity.
    """
    current = question.strip()
    previous_user = next(
        (
            str(item.get("content") or "").strip()
            for item in reversed(history_messages)
            if item.get("role") == "user" and str(item.get("content") or "").strip()
        ),
        "",
    )
    if not previous_user:
        return current, False

    compact = current.replace(" ", "")
    followup_prefixes = ("那", "那么", "它", "这个", "那个", "上述", "前面", "刚才", "另外", "还有")
    looks_like_followup = len(compact) <= 24 or compact.startswith(followup_prefixes)
    if not looks_like_followup:
        return current, False

    context = previous_user
    current_entities = ENTITY_PATTERN.findall(current)
    previous_entities = ENTITY_PATTERN.findall(previous_user)
    if current_entities and previous_entities:
        for replacement in current_entities:
            family = _entity_family(replacement)
            if not family:
                continue
            old = next(
                (
                    candidate
                    for candidate in previous_entities
                    if candidate.lower() != replacement.lower()
                    and _entity_family(candidate) == family
                ),
                None,
            )
            if old:
                context = re.sub(
                    re.escape(old),
                    replacement,
                    context,
                    count=1,
                    flags=re.IGNORECASE,
                )

    max_chars = max(80, int(settings.retrieval_query_context_max_chars))
    context = context[:max_chars].strip()
    if not context:
        return current, False
    return f"{current}\n上下文主题：{context}", True


def _with_citation_indexes(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(evidence, start=1):
        row = dict(item)
        row["citation_index"] = index
        rows.append(row)
    return rows


def _timing_value(timings: dict[str, Any], key: str) -> Any:
    value = timings.get(key)
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return value


def _local_fast_path(
    *,
    question: str,
    user: CurrentUser,
    knowledge_base_id: str | None,
    top_k: int,
    rerank: bool,
    history: list[dict[str, Any]] | None,
    token_sink: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    trace_id = new_trace_id()
    started = time.perf_counter()
    history_messages = agent_module._conversation_history(history)
    retrieval_query, contextualized = _contextual_retrieval_query(question, history_messages)
    allowed = allowed_ids(user.role)

    events: list[dict[str, Any]] = [
        {
            "type": "user",
            "timestamp": utc_now(),
            "mode": "local",
            "question_preview": question[:240],
            "allowed_knowledge_base_ids": allowed,
            "context_messages": len(history_messages),
        },
        {
            "type": "fast_path",
            "timestamp": utc_now(),
            "tool": "enterprise_search",
            "contextual_retrieval_query": contextualized,
        },
    ]

    arguments: dict[str, Any] = {"query": retrieval_query, "top_k": top_k}
    if knowledge_base_id:
        arguments["knowledge_base_id"] = knowledge_base_id

    events.append(
        {
            "type": "tool_start",
            "timestamp": utc_now(),
            "round": 0,
            "tool": "enterprise_search",
            # Never persist the expanded retrieval query because it can contain a
            # previous conversation turn. Current user question remains in audit.
            "arguments": {
                "top_k": top_k,
                "knowledge_base_id": knowledge_base_id,
                "contextual_query": contextualized,
            },
        }
    )
    record_event(
        username=user.username,
        role=user.role,
        action="TOOL_CALL",
        query=question[:240],
        detail=f"tool=enterprise_search;trace_id={trace_id};fast_path=true",
    )

    tool_started = time.perf_counter()
    status = "SUCCESS"
    try:
        result = tool_registry.execute(
            "enterprise_search",
            arguments,
            ToolContext(
                username=user.username,
                role=user.role,
                mode="local",
                trace_id=trace_id,
                selected_knowledge_base_id=knowledge_base_id,
                top_k=top_k,
                rerank=rerank,
            ),
        )
    except ToolExecutionError as exc:
        status = exc.status
        result = {
            "ok": False,
            "tool": "enterprise_search",
            "status": exc.status,
            "error": str(exc),
            "evidence": [],
            "timings": {},
        }
    except Exception as exc:
        status = "FAILED"
        result = {
            "ok": False,
            "tool": "enterprise_search",
            "status": "FAILED",
            "error": f"{type(exc).__name__}: {exc}",
            "evidence": [],
            "timings": {},
        }

    retrieval_ms = (time.perf_counter() - tool_started) * 1000
    retrieval_breakdown = dict(result.get("timings") or {})
    evidence = _with_citation_indexes(list(result.get("evidence") or []))
    result = dict(result)
    result["evidence"] = evidence
    events.append(
        {
            "type": "tool_end",
            "timestamp": utc_now(),
            "round": 0,
            "tool": "enterprise_search",
            "status": status,
            "latency_ms": round(retrieval_ms, 2),
            "result_count": len(evidence),
            "timings": retrieval_breakdown,
        }
    )
    record_event(
        username=user.username,
        role=user.role,
        action="TOOL_RESULT",
        status=status,
        knowledge_base_id=knowledge_base_id or "all",
        latency_ms=retrieval_ms,
        num_sources=len(evidence),
        detail=f"tool=enterprise_search;trace_id={trace_id};fast_path=true",
    )

    llm_ms = 0.0
    llm_calls = 0
    native_stream = False
    if status == "DENIED":
        final_answer = "当前账号无权访问该知识库，因此不能基于未授权资料回答。"
    elif status != "SUCCESS":
        final_answer = "企业知识检索暂时失败，请稍后重试。"
    elif not evidence:
        final_answer = "当前授权范围内没有检索到足够证据，暂时无法可靠回答。"
    else:
        visible = ", ".join(f"{item['id']}={item['name']}" for item in visible_bases(user.role))
        evidence_json = json.dumps(
            {
                "tool": "enterprise_search",
                "evidence": evidence,
            },
            ensure_ascii=False,
        )[:16000]
        system = (
            agent_module.AGENT_SYSTEM_PROMPT
            + "\nMode=local fast path. The backend already executed enterprise_search."
            + " Do not call tools. Answer the CURRENT question only from AUTHORIZED_ENTERPRISE_EVIDENCE below."
            + " Conversation history may resolve pronouns/follow-ups but cannot override current evidence."
            + f"\nCurrent role={user.role}; backend-authorized KBs: {visible}."
            + f"\nAUTHORIZED_ENTERPRISE_EVIDENCE={evidence_json}"
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            *history_messages,
            {"role": "user", "content": question.strip()},
        ]
        llm_started = time.perf_counter()
        llm_calls = 1
        if token_sink is None:
            message = agent_module._ollama_chat(messages, [])
            final_answer = str(message.get("content") or "").strip()
        else:
            native_stream = True
            chunks: list[str] = []
            for text in ollama_chat_stream(messages):
                chunks.append(text)
                token_sink(text)
            final_answer = "".join(chunks).strip()
        llm_ms = (time.perf_counter() - llm_started) * 1000
        if not final_answer:
            final_answer = "当前没有获得足够证据生成可靠答案。"

    events.append(
        {
            "type": "final",
            "timestamp": utc_now(),
            "answer_preview": final_answer[:400],
            "native_stream": native_stream,
        }
    )
    total_ms = (time.perf_counter() - started) * 1000
    timings = {
        "retrieval_ms": round(retrieval_ms, 2),
        "vector_ms": _timing_value(retrieval_breakdown, "vector_ms"),
        "bm25_ms": _timing_value(retrieval_breakdown, "bm25_ms"),
        "fusion_ms": _timing_value(retrieval_breakdown, "fusion_ms"),
        "rerank_ms": _timing_value(retrieval_breakdown, "rerank_ms"),
        "retrieval_total_ms": _timing_value(retrieval_breakdown, "total_ms"),
        "bm25_cache_hit": retrieval_breakdown.get("bm25_cache_hit"),
        "parallel_hybrid": retrieval_breakdown.get("parallel_hybrid"),
        "fusion": retrieval_breakdown.get("fusion"),
        "vector_candidates": retrieval_breakdown.get("vector_candidates"),
        "bm25_candidates": retrieval_breakdown.get("bm25_candidates"),
        "llm_ms": round(llm_ms, 2),
        "total_ms": round(total_ms, 2),
        "llm_calls": llm_calls,
        "tool_calls": 1,
        "fast_path": True,
        "native_stream": native_stream,
    }
    trace = {
        "trace_id": trace_id,
        "timestamp": utc_now(),
        "username": user.username,
        "role": user.role,
        "mode": "local",
        "model": settings.ollama_model,
        "max_tool_rounds": 0,
        "context_messages": len(history_messages),
        "events": events,
        "evidence_count": len(evidence),
        "elapsed_ms": round(total_ms, 2),
        "timings": timings,
    }
    save_trace(trace)
    record_event(
        username=user.username,
        role=user.role,
        action="QUERY",
        knowledge_base_id=knowledge_base_id or "all",
        query=question[:500],
        latency_ms=total_ms,
        num_sources=len(evidence),
        detail=f"agent_mode=local;trace_id={trace_id};fast_path=true",
    )

    return {
        "answer": final_answer,
        "query": question,
        "mode": "local",
        "trace_id": trace_id,
        "sources": [agent_module._public_source(item) for item in evidence],
        "num_sources": len(evidence),
        "model_used": settings.ollama_model,
        "max_tool_rounds": 0,
        "context_messages": len(history_messages),
        "timings": timings,
    }


def run_conversation_agent(
    *,
    question: str,
    user: CurrentUser,
    mode: AgentMode,
    knowledge_base_id: str | None,
    top_k: int,
    rerank: bool,
    history: list[dict[str, Any]] | None,
    token_sink: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if mode == "local" and settings.agent_local_fast_path:
        return _local_fast_path(
            question=question,
            user=user,
            knowledge_base_id=knowledge_base_id,
            top_k=top_k,
            rerank=rerank,
            history=history,
            token_sink=token_sink,
        )

    started = time.perf_counter()
    result = agent_module.run_agent(
        question=question,
        user=user,
        mode=mode,
        knowledge_base_id=knowledge_base_id,
        top_k=top_k,
        rerank=rerank,
        history=history,
    )
    total_ms = (time.perf_counter() - started) * 1000
    result = dict(result)
    if token_sink is not None:
        buffered_answer = str(result.get("answer") or "")
        if buffered_answer:
            token_sink(buffered_answer)
    result["timings"] = {
        "total_ms": round(total_ms, 2),
        "fast_path": False,
        "native_stream": False,
    }
    return result

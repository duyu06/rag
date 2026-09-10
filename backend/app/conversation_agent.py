from __future__ import annotations

import json
import time
from typing import Any

import app.agent as agent_module
from app.agent_trace import new_trace_id, save_trace, utc_now
from app.audit import record_event
from app.auth import CurrentUser
from app.config import settings
from app.knowledge import allowed_ids, visible_bases
from app.tools.base import AgentMode, ToolContext, ToolExecutionError
from app.tools.registry import tool_registry


def _contextual_retrieval_query(
    question: str,
    history_messages: list[dict[str, str]],
) -> tuple[str, bool]:
    """Use recent user context for short/elliptical follow-ups without another LLM call."""
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

    # Retrieval gets context, while audit and the final answer still use only the
    # current question. The previous message is capped to avoid query inflation.
    return f"{previous_user[:500]}\n{current}", True


def _with_citation_indexes(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(evidence, start=1):
        row = dict(item)
        row["citation_index"] = index
        rows.append(row)
    return rows


def _local_fast_path(
    *,
    question: str,
    user: CurrentUser,
    knowledge_base_id: str | None,
    top_k: int,
    rerank: bool,
    history: list[dict[str, Any]] | None,
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
        }
    except Exception as exc:
        status = "FAILED"
        result = {
            "ok": False,
            "tool": "enterprise_search",
            "status": "FAILED",
            "error": f"{type(exc).__name__}: {exc}",
            "evidence": [],
        }

    retrieval_ms = (time.perf_counter() - tool_started) * 1000
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
        message = agent_module._ollama_chat(messages, [])
        llm_ms = (time.perf_counter() - llm_started) * 1000
        final_answer = str(message.get("content") or "").strip()
        if not final_answer:
            final_answer = "当前没有获得足够证据生成可靠答案。"

    events.append(
        {
            "type": "final",
            "timestamp": utc_now(),
            "answer_preview": final_answer[:400],
        }
    )
    total_ms = (time.perf_counter() - started) * 1000
    timings = {
        "retrieval_ms": round(retrieval_ms, 2),
        "llm_ms": round(llm_ms, 2),
        "total_ms": round(total_ms, 2),
        "llm_calls": llm_calls,
        "tool_calls": 1,
        "fast_path": True,
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
) -> dict[str, Any]:
    if mode == "local" and settings.agent_local_fast_path:
        return _local_fast_path(
            question=question,
            user=user,
            knowledge_base_id=knowledge_base_id,
            top_k=top_k,
            rerank=rerank,
            history=history,
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
    result["timings"] = {
        "total_ms": round(total_ms, 2),
        "fast_path": False,
    }
    return result

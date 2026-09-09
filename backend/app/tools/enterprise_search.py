from __future__ import annotations

from typing import Any

from app.knowledge import get_base, resolve_requested
from app.retrieval import retrieval_service
from app.tools.base import ToolContext, ToolExecutionError


def execute_enterprise_search(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ToolExecutionError("enterprise_search 缺少 query")

    requested = str(arguments.get("knowledge_base_id") or "").strip() or None
    if context.selected_knowledge_base_id:
        if requested and requested != context.selected_knowledge_base_id:
            raise ToolExecutionError("模型不能扩大用户选定的知识库范围", status="DENIED")
        requested = context.selected_knowledge_base_id

    try:
        knowledge_base_ids = resolve_requested(context.role, requested)
    except PermissionError as exc:
        raise ToolExecutionError(str(exc), status="DENIED") from exc
    except ValueError as exc:
        raise ToolExecutionError(str(exc), status="FAILED") from exc

    requested_top_k = arguments.get("top_k", context.top_k)
    try:
        top_k = max(1, min(int(requested_top_k), 10))
    except (TypeError, ValueError):
        top_k = context.top_k

    rows = retrieval_service.search(
        query,
        top_k=top_k,
        mode="hybrid",
        rerank=context.rerank,
        knowledge_base_ids=knowledge_base_ids,
    )

    evidence: list[dict[str, Any]] = []
    for row in rows:
        kb_id = str(row.get("knowledge_base_id") or "")
        kb_name = row.get("knowledge_base_name")
        if not kb_name and kb_id:
            try:
                kb_name = get_base(kb_id)["name"]
            except ValueError:
                kb_name = kb_id
        score = row.get("rerank_score")
        if score is None:
            score = row.get("hybrid_score", row.get("vector_score"))
        evidence.append(
            {
                "source_type": "enterprise",
                "title": str(row.get("file_name") or "未知文档"),
                "file_name": str(row.get("file_name") or "未知文档"),
                "knowledge_base_id": kb_id or None,
                "knowledge_base_name": str(kb_name or "企业知识库"),
                "page": row.get("page"),
                "content": str(row.get("content") or "")[:2400],
                "relevance_score": score,
                "url": None,
                "domain": None,
            }
        )

    return {
        "ok": True,
        "tool": "enterprise_search",
        "knowledge_base_ids": knowledge_base_ids,
        "result_count": len(evidence),
        "evidence": evidence,
    }

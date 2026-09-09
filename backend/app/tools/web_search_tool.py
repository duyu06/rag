from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.config import settings
from app.tools.base import ToolContext, ToolExecutionError
from app.web_search import search_web


def execute_web_search(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    if context.mode == "local":
        raise ToolExecutionError("Local 模式禁止联网搜索", status="DENIED")
    if not settings.web_search_enabled:
        raise ToolExecutionError("服务器已关闭 Web Search")

    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ToolExecutionError("web_search 缺少 query")

    try:
        requested = int(arguments.get("max_results", settings.web_search_max_results))
    except (TypeError, ValueError):
        requested = settings.web_search_max_results
    max_results = max(1, min(requested, settings.web_search_max_results, 10))

    rows = search_web(query)[:max_results]
    evidence: list[dict[str, Any]] = []
    for row in rows:
        url = str(row.get("url") or "")
        domain = urlparse(url).hostname or ""
        evidence.append(
            {
                "source_type": "web",
                "title": str(row.get("file_name") or "网页"),
                "file_name": str(row.get("file_name") or "网页"),
                "knowledge_base_id": None,
                "knowledge_base_name": f"Web · {domain}" if domain else "Web",
                "page": None,
                "content": str(row.get("content") or "")[:2400],
                "relevance_score": None,
                "url": url,
                "domain": domain,
            }
        )

    return {
        "ok": True,
        "tool": "web_search",
        "result_count": len(evidence),
        "evidence": evidence,
    }

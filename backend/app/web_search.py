from __future__ import annotations

from urllib.parse import urlparse

from ddgs import DDGS

from app.config import settings

WEB_SEARCH_MARKER = "[[NEXUS_WEB_SEARCH]]"


def wants_web_search(question: str) -> bool:
    return question.lstrip().startswith(WEB_SEARCH_MARKER)


def clean_question(question: str) -> str:
    value = question.strip()
    if value.startswith(WEB_SEARCH_MARKER):
        value = value[len(WEB_SEARCH_MARKER) :].lstrip()
    return value


def _safe_public_url(value: str) -> str | None:
    try:
        parsed = urlparse(value.strip())
    except Exception:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return parsed.geturl()


def normalize_web_results(raw_results: list[dict]) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for item in raw_results:
        url = _safe_public_url(str(item.get("href") or item.get("url") or ""))
        if not url or url in seen:
            continue
        seen.add(url)
        title = str(item.get("title") or url).strip()[:240]
        body = str(item.get("body") or item.get("snippet") or item.get("description") or "").strip()
        if not body:
            continue
        rows.append(
            {
                "source_type": "web",
                "file_name": title,
                "content": body[:1800],
                "url": url,
                "knowledge_base_id": None,
                "knowledge_base_name": "互联网检索",
                "page": None,
                "vector_score": None,
                "bm25_score": None,
                "hybrid_score": None,
                "rerank_score": None,
            }
        )
    return rows


def search_web(query: str) -> list[dict]:
    if not settings.web_search_enabled:
        return []
    clean = clean_question(query)
    if not clean:
        return []
    client = DDGS(timeout=settings.web_search_timeout_seconds)
    raw = client.text(
        clean,
        region=settings.web_search_region,
        safesearch="moderate",
        max_results=settings.web_search_max_results,
        backend=settings.web_search_backend,
    )
    return normalize_web_results(list(raw or []))[: settings.web_search_max_results]

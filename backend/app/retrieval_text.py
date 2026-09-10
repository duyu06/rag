from __future__ import annotations

from pathlib import Path
from typing import Any


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def document_title(row: dict[str, Any]) -> str:
    explicit = _clean(row.get("document_title"))
    if explicit:
        return explicit
    file_name = _clean(row.get("file_name"))
    return Path(file_name).stem if file_name else ""


def build_retrieval_text(row: dict[str, Any]) -> str:
    """Build the text embedded/indexed for retrieval without changing Citation content.

    Enterprise questions frequently contain product names, policy titles, section names,
    or KB domain terms that may not be repeated inside a small body chunk. Prefixing
    this metadata gives both dense retrieval and BM25 the missing semantic anchors.
    """
    parts: list[str] = []
    title = document_title(row)
    section = _clean(row.get("section_title"))
    kb_name = _clean(row.get("knowledge_base_name"))
    content = str(row.get("content") or "").strip()

    if title:
        parts.append(f"文档：{title}")
    if section and section != title:
        parts.append(f"章节：{section}")
    if kb_name:
        parts.append(f"知识库：{kb_name}")
    if content:
        parts.append(content)
    return "\n".join(parts)

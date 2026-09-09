from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz
from docx import Document as DocxDocument

from app.config import settings
from app.store import vector_store

DOC_DIR = Path("data/documents")
DOC_DIR.mkdir(parents=True, exist_ok=True)
SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    size = size or settings.chunk_size
    overlap = overlap or settings.chunk_overlap
    clean = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not clean:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + size)
        if end < len(clean):
            candidates = [
                clean.rfind(mark, start + size // 2, end)
                for mark in ("\n", "。", "；", "！", "？", ". ")
            ]
            cut = max(candidates)
            if cut > start:
                end = cut + 1

        value = clean[start:end].strip()
        if value:
            chunks.append(value)
        if end >= len(clean):
            break
        start = max(start + 1, end - overlap)
    return chunks


def parse_document(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("仅支持 PDF / DOCX / TXT / Markdown")

    parts: list[dict[str, Any]] = []

    if suffix == ".pdf":
        pdf = fitz.open(path)
        try:
            for page_no, page in enumerate(pdf, start=1):
                text = page.get_text("text")
                for index, chunk in enumerate(chunk_text(text)):
                    parts.append({"content": chunk, "page": page_no, "chunk_index": index})
        finally:
            pdf.close()
        return parts

    if suffix == ".docx":
        doc = DocxDocument(path)
        blocks: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                blocks.append(" | ".join(cell.text.strip() for cell in row.cells))
        text = "\n".join(blocks)
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")

    return [
        {"content": chunk, "page": None, "chunk_index": index}
        for index, chunk in enumerate(chunk_text(text))
    ]


def ingest_file(path: Path) -> int:
    chunks = parse_document(path)
    if not chunks:
        raise ValueError("文档未解析出有效文本")

    vector_store.delete_file(path.name)
    enriched = [
        {
            **chunk,
            "file_name": path.name,
            "file_type": path.suffix.lower().lstrip("."),
        }
        for chunk in chunks
    ]
    return vector_store.add_chunks(enriched)

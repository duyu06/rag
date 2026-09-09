from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.ingestion import DOC_DIR, SUPPORTED_SUFFIXES, ingest_file
from app.rag import current_model_name, generate_answer
from app.retrieval import retrieval_service
from app.store import vector_store

app = FastAPI(
    title="NexusKB 企业 AI 知识中台 API",
    version="0.1.0",
    description="Enterprise RAG demo: Vector + BM25 + Hybrid + Rerank + Citation",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=5, ge=1, le=20)
    include_sources: bool = True
    use_hybrid_search: bool = True
    use_reranking: bool = False


class DebugRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    mode: Literal["vector", "bm25", "hybrid"] = "hybrid"
    top_k: int = Field(default=8, ge=1, le=30)
    rerank: bool = False


def source_from_row(row: dict) -> dict:
    score = row.get("rerank_score")
    if score is None:
        score = row.get("hybrid_score", row.get("vector_score"))
    return {
        "file_name": row.get("file_name", "未知文档"),
        "page": row.get("page"),
        "content_preview": str(row.get("content", ""))[:320],
        "relevance_score": score,
    }


def safe_rows(question: str, k: int, hybrid: bool, rerank: bool) -> list[dict]:
    mode = "hybrid" if hybrid else "vector"
    try:
        return retrieval_service.search(question, top_k=k, mode=mode, rerank=rerank)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"检索服务不可用：{exc}") from exc


@app.get("/")
def root():
    return {
        "name": "NexusKB Enterprise Knowledge Copilot",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/api/health",
    }


@app.get("/api/health")
def health():
    qdrant_ok = vector_store.ping()
    provider = "openai-compatible" if settings.openai_api_key else "ollama"
    return {
        "status": "healthy" if qdrant_ok else "degraded",
        "vector_db_connected": qdrant_ok,
        "ollama_connected": provider == "ollama",
        "llm_provider": provider,
        "llm_model": current_model_name(),
    }


@app.get("/api/stats")
def stats():
    try:
        store_stats = vector_store.stats()
        chunks = vector_store.all_chunks()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"向量库不可用：{exc}") from exc

    documents = {str(row.get("file_name")) for row in chunks if row.get("file_name")}
    return {
        "total_documents": len(documents),
        "total_chunks": store_stats["total_chunks"],
        "collection_name": store_stats["collection_name"],
        "embedding_model": store_stats["embedding_model"],
        "embedding_dimension": store_stats["embedding_dimension"],
        "llm_model": current_model_name(),
    }


@app.post("/api/ingest")
async def ingest(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    safe_name = Path(file.filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail="仅支持 PDF / DOCX / TXT / Markdown")

    content = await file.read()
    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"文件不能超过 {settings.max_file_size_mb}MB")

    path = DOC_DIR / safe_name
    path.write_bytes(content)
    try:
        chunk_count = ingest_file(path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"文档处理失败：{exc}") from exc

    return {
        "success": True,
        "message": "文档已写入知识库",
        "file_name": safe_name,
        "chunks_stored": chunk_count,
    }


@app.get("/api/documents")
def documents():
    try:
        rows = vector_store.all_chunks()
    except Exception:
        rows = []
    counts = Counter(str(row.get("file_name")) for row in rows if row.get("file_name"))

    result = []
    for path in sorted(DOC_DIR.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_file():
            continue
        stat = path.stat()
        result.append(
            {
                "file_name": path.name,
                "file_type": path.suffix.lower().lstrip("."),
                "file_size_kb": round(stat.st_size / 1024, 2),
                "upload_date": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "chunk_count": counts.get(path.name, 0),
            }
        )
    return {
        "documents": result,
        "total_documents": len(result),
        "total_chunks": sum(counts.values()),
    }


@app.delete("/api/documents/{file_name}")
def delete_document(file_name: str):
    safe_name = Path(file_name).name
    try:
        vector_store.delete_file(safe_name)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"删除向量失败：{exc}") from exc
    (DOC_DIR / safe_name).unlink(missing_ok=True)
    return {"success": True, "message": "文档已删除"}


@app.post("/api/query")
def query(request: QueryRequest):
    rows = safe_rows(
        request.question,
        request.k,
        request.use_hybrid_search,
        request.use_reranking,
    )
    answer = generate_answer(request.question, rows)
    sources = [source_from_row(row) for row in rows] if request.include_sources else []
    return {
        "answer": answer,
        "query": request.question,
        "sources": sources,
        "num_sources": len(sources),
        "model_used": current_model_name(),
    }


@app.post("/api/query/stream")
def query_stream(request: QueryRequest):
    rows = safe_rows(
        request.question,
        request.k,
        request.use_hybrid_search,
        request.use_reranking,
    )
    sources = [source_from_row(row) for row in rows] if request.include_sources else []

    def event_stream():
        yield "event: sources\ndata: " + json.dumps({"sources": sources}, ensure_ascii=False) + "\n\n"
        answer = generate_answer(request.question, rows)
        for start in range(0, len(answer), 14):
            payload = json.dumps({"text": answer[start : start + 14]}, ensure_ascii=False)
            yield f"event: token\ndata: {payload}\n\n"
        yield 'event: done\ndata: {"finish_reason":"stop"}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/retrieval/debug")
def retrieval_debug(request: DebugRequest):
    try:
        rows = retrieval_service.search(
            request.query,
            top_k=request.top_k,
            mode=request.mode,
            rerank=request.rerank,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"检索服务不可用：{exc}") from exc

    return {
        "query": request.query,
        "mode": request.mode,
        "rerank": request.rerank,
        "results": [
            {
                "file_name": row.get("file_name"),
                "page": row.get("page"),
                "content": str(row.get("content", ""))[:600],
                "vector_score": row.get("vector_score"),
                "bm25_score": row.get("bm25_score"),
                "hybrid_score": row.get("hybrid_score"),
                "rerank_score": row.get("rerank_score"),
            }
            for row in rows
        ],
    }

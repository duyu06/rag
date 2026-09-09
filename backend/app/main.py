from __future__ import annotations

import json
import mimetypes
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.audit import recent_events, record_event, today_summary
from app.auth import CurrentUser, authenticate, issue_token, require_admin, require_user
from app.config import settings
from app.demo import demo_status, initialize_demo, reset_demo
from app.ingestion import DOC_DIR, SUPPORTED_SUFFIXES, document_path, ingest_file
from app.knowledge import get_base, resolve_requested, visible_bases
from app.rag import current_model_name, generate_answer, probe_llm
from app.retrieval import retrieval_service
from app.store import vector_store

app = FastAPI(
    title="NexusKB 企业 AI 知识中台 API",
    version="0.3.0",
    description="Enterprise RAG demo: RBAC + multi-KB + Hybrid Retrieval + Rerank + Citation + Audit",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=5, ge=1, le=20)
    include_sources: bool = True
    use_hybrid_search: bool = True
    use_reranking: bool = False
    knowledge_base_id: str | None = None


class DebugRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    mode: Literal["vector", "bm25", "hybrid"] = "hybrid"
    top_k: int = Field(default=8, ge=1, le=30)
    rerank: bool = False
    knowledge_base_id: str | None = None


EvalMode = Literal["vector", "bm25", "hybrid", "hybrid_rerank"]


class EvaluationRequest(BaseModel):
    modes: list[EvalMode] = Field(
        default_factory=lambda: ["vector", "bm25", "hybrid", "hybrid_rerank"]
    )
    top_k: int = Field(default=3, ge=1, le=10)


def _audit(user: CurrentUser, action: str, **kwargs) -> None:
    record_event(username=user.username, role=user.role, action=action, **kwargs)


def _allowed_ids(user: CurrentUser, knowledge_base_id: str | None) -> list[str]:
    try:
        return resolve_requested(user.role, knowledge_base_id)
    except PermissionError as exc:
        _audit(
            user,
            "ACCESS",
            status="DENIED",
            knowledge_base_id=knowledge_base_id,
            detail=str(exc),
        )
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def source_from_row(row: dict) -> dict:
    score = row.get("rerank_score")
    if score is None:
        score = row.get("hybrid_score", row.get("vector_score"))
    return {
        "file_name": row.get("file_name", "未知文档"),
        "page": row.get("page"),
        "content_preview": str(row.get("content", ""))[:320],
        "relevance_score": score,
        "knowledge_base_id": row.get("knowledge_base_id"),
        "knowledge_base_name": row.get("knowledge_base_name"),
    }


def safe_rows(
    question: str,
    k: int,
    hybrid: bool,
    rerank: bool,
    user: CurrentUser,
    knowledge_base_id: str | None,
) -> list[dict]:
    mode = "hybrid" if hybrid else "vector"
    kb_ids = _allowed_ids(user, knowledge_base_id)
    try:
        return retrieval_service.search(
            question,
            top_k=k,
            mode=mode,
            rerank=rerank,
            knowledge_base_ids=kb_ids,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"检索服务不可用：{exc}") from exc


@app.get("/")
def root():
    return {
        "name": "NexusKB Enterprise Knowledge Copilot",
        "version": "0.3.0",
        "docs": "/docs",
        "health": "/api/health",
        "ready": "/api/ready",
    }


@app.get("/api/ready")
def ready():
    qdrant_ok = vector_store.ping()
    if not qdrant_ok:
        raise HTTPException(status_code=503, detail="Qdrant not ready")
    return {"status": "ready", "vector_db_connected": True}


@app.get("/api/health")
def health():
    qdrant_ok = vector_store.ping()
    llm_ok, llm_detail = probe_llm()
    provider = "openai-compatible" if settings.openai_api_key else "ollama"
    return {
        "status": "healthy" if (qdrant_ok and llm_ok) else "degraded",
        "vector_db_connected": qdrant_ok,
        "llm_connected": llm_ok,
        "llm_detail": llm_detail,
        "ollama_connected": llm_ok if provider == "ollama" else False,
        "llm_provider": provider,
        "llm_model": current_model_name(),
    }


@app.post("/api/auth/login")
def login(request: LoginRequest):
    user = authenticate(request.username.strip(), request.password)
    if not user:
        record_event(
            username=request.username.strip() or "unknown",
            role="UNKNOWN",
            action="LOGIN",
            status="DENIED",
            detail="invalid_credentials",
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    _audit(user, "LOGIN")
    return {
        "access_token": issue_token(user),
        "token_type": "bearer",
        "user": user.model_dump(),
    }


@app.get("/api/auth/me")
def me(user: CurrentUser = Depends(require_user)):
    return user.model_dump()


@app.get("/api/knowledge-bases")
def knowledge_bases(user: CurrentUser = Depends(require_user)):
    return {"knowledge_bases": visible_bases(user.role)}


@app.get("/api/stats")
def stats(
    knowledge_base_id: str | None = Query(default=None),
    user: CurrentUser = Depends(require_user),
):
    kb_ids = _allowed_ids(user, knowledge_base_id)
    try:
        chunks = vector_store.all_chunks(knowledge_base_ids=kb_ids)
        store_stats = vector_store.stats(knowledge_base_ids=kb_ids)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"向量库不可用：{exc}") from exc

    documents = {
        (str(row.get("knowledge_base_id")), str(row.get("file_name")))
        for row in chunks
        if row.get("file_name")
    }
    audit = today_summary()
    return {
        "total_documents": len(documents),
        "total_chunks": store_stats["total_chunks"],
        "knowledge_bases": len(kb_ids),
        "collection_name": store_stats["collection_name"],
        "embedding_model": store_stats["embedding_model"],
        "embedding_dimension": store_stats["embedding_dimension"],
        "llm_model": current_model_name(),
        **audit,
    }


@app.get("/api/audit")
def audit_log(
    limit: int = Query(default=50, ge=1, le=500),
    user: CurrentUser = Depends(require_user),
):
    require_admin(user)
    return {"events": recent_events(limit), "summary": today_summary()}


@app.post("/api/ingest")
async def ingest(
    file: UploadFile = File(...),
    knowledge_base_id: str = Form(...),
    user: CurrentUser = Depends(require_user),
):
    require_admin(user)
    try:
        base = get_base(knowledge_base_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    safe_name = Path(file.filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail="仅支持 PDF / DOCX / TXT / Markdown")

    content = await file.read()
    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"文件不能超过 {settings.max_file_size_mb}MB")

    path = document_path(knowledge_base_id, safe_name)
    path.write_bytes(content)
    try:
        chunk_count = ingest_file(path, knowledge_base_id)
    except Exception as exc:
        path.unlink(missing_ok=True)
        _audit(user, "INGEST", status="FAILED", knowledge_base_id=knowledge_base_id, detail=str(exc))
        raise HTTPException(status_code=500, detail=f"文档处理失败：{exc}") from exc

    _audit(
        user,
        "INGEST",
        knowledge_base_id=knowledge_base_id,
        num_sources=chunk_count,
        detail=safe_name,
    )
    return {
        "success": True,
        "message": "文档已写入知识库",
        "file_name": safe_name,
        "knowledge_base_id": knowledge_base_id,
        "knowledge_base_name": base["name"],
        "chunks_stored": chunk_count,
    }


@app.get("/api/documents")
def documents(
    knowledge_base_id: str | None = Query(default=None),
    user: CurrentUser = Depends(require_user),
):
    kb_ids = _allowed_ids(user, knowledge_base_id)
    try:
        rows = vector_store.all_chunks(knowledge_base_ids=kb_ids)
    except Exception:
        rows = []

    counts = Counter(
        (str(row.get("knowledge_base_id")), str(row.get("file_name")))
        for row in rows
        if row.get("knowledge_base_id") and row.get("file_name")
    )

    result = []
    for kb_id in kb_ids:
        base = get_base(kb_id)
        directory = DOC_DIR / kb_id
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True):
            if not path.is_file():
                continue
            stat = path.stat()
            result.append(
                {
                    "file_name": path.name,
                    "file_type": path.suffix.lower().lstrip("."),
                    "file_size_kb": round(stat.st_size / 1024, 2),
                    "upload_date": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "chunk_count": counts.get((kb_id, path.name), 0),
                    "knowledge_base_id": kb_id,
                    "knowledge_base_name": base["name"],
                }
            )

    result.sort(key=lambda item: item["upload_date"], reverse=True)
    return {
        "documents": result,
        "total_documents": len(result),
        "total_chunks": sum(counts.values()),
    }


@app.get("/api/source/{knowledge_base_id}/{file_name}")
def source_document(
    knowledge_base_id: str,
    file_name: str,
    user: CurrentUser = Depends(require_user),
):
    _allowed_ids(user, knowledge_base_id)
    safe_name = Path(file_name).name
    path = document_path(knowledge_base_id, safe_name)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="来源文件不存在")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    _audit(user, "SOURCE_VIEW", knowledge_base_id=knowledge_base_id, detail=safe_name)
    return FileResponse(path, media_type=media_type)


@app.delete("/api/documents/{file_name}")
def delete_document(
    file_name: str,
    knowledge_base_id: str = Query(...),
    user: CurrentUser = Depends(require_user),
):
    require_admin(user)
    try:
        get_base(knowledge_base_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    safe_name = Path(file_name).name
    try:
        vector_store.delete_file(safe_name, knowledge_base_id)
    except Exception as exc:
        _audit(user, "DELETE", status="FAILED", knowledge_base_id=knowledge_base_id, detail=str(exc))
        raise HTTPException(status_code=503, detail=f"删除向量失败：{exc}") from exc

    document_path(knowledge_base_id, safe_name).unlink(missing_ok=True)
    _audit(user, "DELETE", knowledge_base_id=knowledge_base_id, detail=safe_name)
    return {"success": True, "message": "文档已删除"}


@app.get("/api/demo/status")
def get_demo_status(user: CurrentUser = Depends(require_user)):
    require_admin(user)
    try:
        return demo_status()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Demo 状态读取失败：{exc}") from exc


@app.post("/api/demo/initialize")
def init_demo(user: CurrentUser = Depends(require_user)):
    require_admin(user)
    started = time.perf_counter()
    try:
        result = initialize_demo(force=False)
    except Exception as exc:
        _audit(user, "DEMO_INIT", status="FAILED", detail=str(exc))
        raise HTTPException(status_code=500, detail=f"Demo 初始化失败：{exc}") from exc
    _audit(user, "DEMO_INIT", latency_ms=(time.perf_counter() - started) * 1000, detail=f"{result['status']['ready_count']}/{result['status']['total']}")
    return result


@app.post("/api/demo/reset")
def reset_demo_endpoint(user: CurrentUser = Depends(require_user)):
    require_admin(user)
    started = time.perf_counter()
    try:
        result = reset_demo()
    except Exception as exc:
        _audit(user, "DEMO_RESET", status="FAILED", detail=str(exc))
        raise HTTPException(status_code=500, detail=f"Demo 重置失败：{exc}") from exc
    _audit(user, "DEMO_RESET", latency_ms=(time.perf_counter() - started) * 1000, detail=f"{result['status']['ready_count']}/{result['status']['total']}")
    return result


@app.post("/api/query")
def query(request: QueryRequest, user: CurrentUser = Depends(require_user)):
    started = time.perf_counter()
    rows = safe_rows(
        request.question,
        request.k,
        request.use_hybrid_search,
        request.use_reranking,
        user,
        request.knowledge_base_id,
    )
    answer = generate_answer(request.question, rows)
    sources = [source_from_row(row) for row in rows] if request.include_sources else []
    _audit(
        user,
        "QUERY",
        knowledge_base_id=request.knowledge_base_id or "all",
        query=request.question,
        latency_ms=(time.perf_counter() - started) * 1000,
        num_sources=len(sources),
    )
    return {
        "answer": answer,
        "query": request.question,
        "sources": sources,
        "num_sources": len(sources),
        "model_used": current_model_name(),
    }


@app.post("/api/query/stream")
def query_stream(request: QueryRequest, user: CurrentUser = Depends(require_user)):
    started = time.perf_counter()
    rows = safe_rows(
        request.question,
        request.k,
        request.use_hybrid_search,
        request.use_reranking,
        user,
        request.knowledge_base_id,
    )
    sources = [source_from_row(row) for row in rows] if request.include_sources else []

    def event_stream():
        try:
            yield "event: sources\ndata: " + json.dumps({"sources": sources}, ensure_ascii=False) + "\n\n"
            answer = generate_answer(request.question, rows)
            for start in range(0, len(answer), 14):
                payload = json.dumps({"text": answer[start : start + 14]}, ensure_ascii=False)
                yield f"event: token\ndata: {payload}\n\n"
            yield 'event: done\ndata: {"finish_reason":"stop"}\n\n'
        finally:
            _audit(
                user,
                "QUERY",
                knowledge_base_id=request.knowledge_base_id or "all",
                query=request.question,
                latency_ms=(time.perf_counter() - started) * 1000,
                num_sources=len(sources),
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/retrieval/debug")
def retrieval_debug(request: DebugRequest, user: CurrentUser = Depends(require_user)):
    kb_ids = _allowed_ids(user, request.knowledge_base_id)
    started = time.perf_counter()
    try:
        rows = retrieval_service.search(
            request.query,
            top_k=request.top_k,
            mode=request.mode,
            rerank=request.rerank,
            knowledge_base_ids=kb_ids,
        )
    except Exception as exc:
        _audit(user, "RETRIEVAL_DEBUG", status="FAILED", query=request.query, detail=str(exc))
        raise HTTPException(status_code=503, detail=f"检索服务不可用：{exc}") from exc

    _audit(
        user,
        "RETRIEVAL_DEBUG",
        knowledge_base_id=request.knowledge_base_id or "all",
        query=request.query,
        latency_ms=(time.perf_counter() - started) * 1000,
        num_sources=len(rows),
        detail=f"mode={request.mode},rerank={request.rerank}",
    )
    return {
        "query": request.query,
        "mode": request.mode,
        "rerank": request.rerank,
        "knowledge_base_ids": kb_ids,
        "results": [
            {
                "file_name": row.get("file_name"),
                "page": row.get("page"),
                "content": str(row.get("content", ""))[:600],
                "knowledge_base_id": row.get("knowledge_base_id"),
                "knowledge_base_name": row.get("knowledge_base_name"),
                "vector_score": row.get("vector_score"),
                "bm25_score": row.get("bm25_score"),
                "hybrid_score": row.get("hybrid_score"),
                "rerank_score": row.get("rerank_score"),
            }
            for row in rows
        ],
    }


@app.post("/api/evaluation/run")
def run_evaluation(request: EvaluationRequest, user: CurrentUser = Depends(require_user)):
    require_admin(user)
    dataset_path = Path(__file__).resolve().parent.parent / "eval_dataset.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    overall_started = time.perf_counter()

    report: dict[str, dict] = {}
    for eval_mode in request.modes:
        retrieval_mode: Literal["vector", "bm25", "hybrid"] = (
            "hybrid" if eval_mode == "hybrid_rerank" else eval_mode
        )
        use_rerank = eval_mode == "hybrid_rerank"
        started = time.perf_counter()
        hits_at_1 = 0
        hits_at_k = 0
        reciprocal_rank = 0.0
        cases = []

        for item in dataset:
            rows = retrieval_service.search(
                item["question"],
                top_k=request.top_k,
                mode=retrieval_mode,
                rerank=use_rerank,
                knowledge_base_ids=[item["knowledge_base_id"]],
            )
            names = [str(row.get("file_name", "")) for row in rows]
            expected = item["expected_file"]
            rank = next((index + 1 for index, name in enumerate(names) if name == expected), None)
            if rank == 1:
                hits_at_1 += 1
            if rank is not None and rank <= request.top_k:
                hits_at_k += 1
                reciprocal_rank += 1 / rank
            cases.append(
                {
                    "question": item["question"],
                    "knowledge_base_id": item["knowledge_base_id"],
                    "expected_file": expected,
                    "rank": rank,
                    "top_files": names,
                }
            )

        total = max(len(dataset), 1)
        report[eval_mode] = {
            "total": len(dataset),
            "hit_at_1": round(hits_at_1 / total, 4),
            f"hit_at_{request.top_k}": round(hits_at_k / total, 4),
            "mrr": round(reciprocal_rank / total, 4),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "rerank": use_rerank,
            "cases": cases,
        }

    _audit(
        user,
        "EVALUATION",
        latency_ms=(time.perf_counter() - overall_started) * 1000,
        detail=",".join(request.modes),
    )
    return {
        "dataset_size": len(dataset),
        "top_k": request.top_k,
        "modes": request.modes,
        "report": report,
    }

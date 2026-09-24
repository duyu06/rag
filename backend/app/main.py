from __future__ import annotations

import json
import mimetypes
import statistics
import time
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.audit import recent_events, record_event, today_summary
from app.auth import (
    CurrentUser,
    authenticate,
    has_permission,
    issue_token,
    require_permission,
    require_user,
)
from app.config import settings
from app.demo import demo_status, initialize_demo, reset_demo
from app.identity import warmup as warmup_identity_permissions
from app.ingestion import DOC_DIR, SUPPORTED_SUFFIXES, document_path
from app.knowledge import get_base, resolve_for, visible_for
from app.knowledge_os import (
    is_document_excluded,
    persist_eval_run,
    registry_entry,
    registry_remove,
    run_ingest_job,
)
from app.llm.health import probe_llm
from app.llm.usage import warmup as warmup_llm_router
from app.rag import MODEL_USED_KEY, current_model_name, generate_answer
from app.retrieval import retrieval_service
from app.security import (
    public_exception_detail,
    public_typesafe_metrics,
    redact_secrets,
    redact_text,
)
from app.store import vector_store


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动门闸：坏配置让进程起不来，而不是第一个请求才炸。

    放在 lifespan 而不是模块顶层，是因为顶层 import 的副作用会波及所有导入方
    （测试、脚本、`python -c "import app.main"`）；lifespan 只在服务真正启动时跑一次。
    两个 warmup 各自的前置条件都在**函数内部**判，所以默认配置下启动零额外行为：
    - `warmup_identity_permissions()`：`FEISHU_PERMISSIONS_ENABLED=false` 直接 return。
    - `warmup_llm_router()`（Model Router V2.3 §8）：`LLM_ROUTER_ENABLED=false` 整链 no-op；
      开启时跑注册表 fail-fast + 建 `llm_request_logs` 表 + 接 usage sink（观测面自身
      fail-open，只有注册表错误才是启动事故）。
    异常不上抛成 500 而是穿出启动阶段——uvicorn 会因此退出（fail-fast）。
    `main_agent.py` 复用同一个 app 实例，门闸一并生效。
    """
    warmup_identity_permissions()
    warmup_llm_router()
    yield


app = FastAPI(
    title="yaoke 企业 AI 知识中台 API",
    version="0.4.0",
    description="Enterprise RAG demo: RBAC + multi-KB + Hybrid Retrieval + Rerank + Citation + Audit",
    lifespan=lifespan,
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
    """范围判定交给 `knowledge.resolve_for`（授予为权威），这里只保留拒绝审计与 HTTP 映射。"""
    try:
        return resolve_for(user, knowledge_base_id)
    except PermissionError as exc:
        _audit(
            user,
            "ACCESS",
            status="DENIED",
            knowledge_base_id=knowledge_base_id,
            detail=redact_text(exc),
        )
        raise HTTPException(status_code=403, detail=redact_text(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=redact_text(exc)) from exc


def _dataset_knowledge_base_ids(dataset: list[dict]) -> list[str]:
    """评测数据集里出现过的 distinct 库 id（按文件里的出现顺序去重）。

    拆出来只为"每个库判一次"这件事可测：范围校验要覆盖数据集，但重复行不该重复判。
    """
    return list(dict.fromkeys(str(item["knowledge_base_id"]) for item in dataset))


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
    rows, _ = safe_rows_with_timings(
        question,
        k,
        hybrid,
        rerank,
        user,
        knowledge_base_id,
    )
    return rows


def safe_rows_with_timings(
    question: str,
    k: int,
    hybrid: bool,
    rerank: bool,
    user: CurrentUser,
    knowledge_base_id: str | None,
) -> tuple[list[dict], dict[str, Any]]:
    mode = "hybrid" if hybrid else "vector"
    kb_ids = _allowed_ids(user, knowledge_base_id)
    try:
        rows, timings = retrieval_service.search_with_timings(
            question,
            top_k=k,
            mode=mode,
            rerank=rerank,
            knowledge_base_ids=kb_ids,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"检索服务不可用：{public_exception_detail(exc)}") from exc
    return [row for row in rows if not is_document_excluded(row.get("knowledge_base_id"), row.get("file_name"))], timings


@app.get("/")
def root():
    return {
        "name": "yaoke Enterprise Knowledge Copilot",
        "version": "0.4.0",
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
def knowledge_bases(user: CurrentUser = Depends(require_permission("knowledge:read"))):
    return {"knowledge_bases": visible_for(user)}


@app.get("/api/stats")
def stats(
    knowledge_base_id: str | None = Query(default=None),
    user: CurrentUser = Depends(require_permission("knowledge:read")),
):
    kb_ids = _allowed_ids(user, knowledge_base_id)
    try:
        chunks = vector_store.all_chunks(knowledge_base_ids=kb_ids)
        store_stats = vector_store.stats(knowledge_base_ids=kb_ids)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"向量库不可用：{public_exception_detail(exc)}") from exc

    documents = {
        (str(row.get("knowledge_base_id")), str(row.get("file_name")))
        for row in chunks
        if row.get("file_name")
    }
    # Non-auditors receive only their own activity counters, never global usage.
    audit = today_summary() if has_permission(user, "audit:read") else today_summary(username=user.username)
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
    user: CurrentUser = Depends(require_permission("audit:read")),
):
    return {"events": recent_events(limit), "summary": today_summary()}


@app.post("/api/ingest")
async def ingest(
    file: UploadFile = File(...),
    knowledge_base_id: str = Form(...),
    user: CurrentUser = Depends(require_permission("knowledge:manage")),
):
    _allowed_ids(user, knowledge_base_id)
    try:
        base = get_base(knowledge_base_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=redact_text(exc)) from exc

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
        chunk_count = run_ingest_job(user, path, knowledge_base_id, origin="upload")
    except Exception as exc:
        path.unlink(missing_ok=True)
        _audit(user, "INGEST", status="FAILED", knowledge_base_id=knowledge_base_id, detail=public_exception_detail(exc))
        raise HTTPException(status_code=500, detail=f"文档处理失败：{public_exception_detail(exc)}") from exc

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
    user: CurrentUser = Depends(require_permission("knowledge:read")),
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
            uploaded_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
            chunk_total = counts.get((kb_id, path.name), 0)
            entry = registry_entry(kb_id, path.name, chunk_count=chunk_total)
            result.append(
                {
                    "file_name": path.name,
                    "file_type": path.suffix.lower().lstrip("."),
                    "file_size_kb": round(stat.st_size / 1024, 2),
                    "upload_date": uploaded_at,
                    "chunk_count": chunk_total,
                    "knowledge_base_id": kb_id,
                    "knowledge_base_name": base["name"],
                    "status": entry["status"],
                    "enabled": bool(entry.get("enabled", True)),
                    "archived": bool(entry.get("archived", False)),
                    "last_error": entry.get("last_error"),
                    "indexed_at": entry.get("updated_at") or uploaded_at,
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
    user: CurrentUser = Depends(require_permission("knowledge:read")),
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
    user: CurrentUser = Depends(require_permission("knowledge:manage")),
):
    _allowed_ids(user, knowledge_base_id)
    try:
        get_base(knowledge_base_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=redact_text(exc)) from exc

    safe_name = Path(file_name).name
    try:
        vector_store.delete_file(safe_name, knowledge_base_id)
    except Exception as exc:
        _audit(user, "DELETE", status="FAILED", knowledge_base_id=knowledge_base_id, detail=public_exception_detail(exc))
        raise HTTPException(status_code=503, detail=f"删除向量失败：{public_exception_detail(exc)}") from exc

    document_path(knowledge_base_id, safe_name).unlink(missing_ok=True)
    registry_remove(knowledge_base_id, safe_name)
    _audit(user, "DELETE", knowledge_base_id=knowledge_base_id, detail=safe_name)
    return {"success": True, "message": "文档已删除"}


@app.get("/api/demo/status")
def get_demo_status(user: CurrentUser = Depends(require_permission("system:operate"))):
    try:
        return demo_status()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Demo 状态读取失败：{public_exception_detail(exc)}") from exc


@app.post("/api/demo/initialize")
def init_demo(user: CurrentUser = Depends(require_permission("system:operate"))):
    started = time.perf_counter()
    try:
        result = initialize_demo(force=False)
    except Exception as exc:
        _audit(user, "DEMO_INIT", status="FAILED", detail=public_exception_detail(exc))
        raise HTTPException(status_code=500, detail=f"Demo 初始化失败：{public_exception_detail(exc)}") from exc
    _audit(user, "DEMO_INIT", latency_ms=(time.perf_counter() - started) * 1000, detail=f"{result['status']['ready_count']}/{result['status']['total']}")
    return result


@app.post("/api/demo/reset")
def reset_demo_endpoint(user: CurrentUser = Depends(require_permission("system:operate"))):
    started = time.perf_counter()
    try:
        result = reset_demo()
    except Exception as exc:
        _audit(user, "DEMO_RESET", status="FAILED", detail=public_exception_detail(exc))
        raise HTTPException(status_code=500, detail=f"Demo 重置失败：{public_exception_detail(exc)}") from exc
    _audit(user, "DEMO_RESET", latency_ms=(time.perf_counter() - started) * 1000, detail=f"{result['status']['ready_count']}/{result['status']['total']}")
    return result


@app.post("/api/query")
def query(request: QueryRequest, user: CurrentUser = Depends(require_permission("knowledge:query"))):
    started = time.perf_counter()
    question = redact_text(request.question)
    rows, retrieval_timings = safe_rows_with_timings(
        question,
        request.k,
        request.use_hybrid_search,
        request.use_reranking,
        user,
        request.knowledge_base_id,
    )
    # 终审 I-11-2（DESIGN §9「响应 model 字段来自实际选中模型」）：`model_used` 优先报
    # **这次真答出那句话的模型**（router 腿的执行面生效名，与账本 `model` 列同源）；
    # 盒子为空 ⇒ 零候选 / 全链失败 / legacy 路，那三种情况**没有**「实际答话的模型」这枚
    # 事实，于是回退计划面读数 `current_model_name()`。键名与键集合一字不改。
    model_out: dict[str, str] = {}
    answer = redact_text(generate_answer(question, rows, model_out=model_out))
    sources = [source_from_row(row) for row in rows] if request.include_sources else []
    _audit(
        user,
        "QUERY",
        knowledge_base_id=request.knowledge_base_id or "all",
        query=question,
        latency_ms=(time.perf_counter() - started) * 1000,
        num_sources=len(sources),
    )
    response = {
        "answer": answer,
        "query": question,
        "sources": sources,
        "num_sources": len(sources),
        "model_used": model_out.get(MODEL_USED_KEY) or current_model_name(),
    }
    typesafe_timings = public_typesafe_metrics(retrieval_timings)
    if typesafe_timings:
        response["timings"] = typesafe_timings
    return redact_secrets(response)


@app.post("/api/query/stream")
def query_stream(
    request: QueryRequest,
    user: CurrentUser = Depends(require_permission("knowledge:query")),
):
    started = time.perf_counter()
    question = redact_text(request.question)
    rows, retrieval_timings = safe_rows_with_timings(
        question,
        request.k,
        request.use_hybrid_search,
        request.use_reranking,
        user,
        request.knowledge_base_id,
    )
    sources = [source_from_row(row) for row in rows] if request.include_sources else []

    def event_stream():
        try:
            yield "event: sources\ndata: " + json.dumps(redact_secrets({"sources": sources}), ensure_ascii=False) + "\n\n"
            # 同 I-11-2：流式腿带同一个盒子（与上面 `/api/query` 那处同一个调用形状）。
            # SSE 的 `done` 事件今天**没有** `model_used` 键，这里按「有没有执行面事实」
            # 决定挂不挂——与既有的 `timings` 同一道姿势；缺键即「本次没有实际答话的模型
            # 可报」，不写空串、也不拿计划面名字冒充。
            model_out: dict[str, str] = {}
            answer = redact_text(generate_answer(question, rows, model_out=model_out))
            for start in range(0, len(answer), 14):
                payload = json.dumps({"text": answer[start : start + 14]}, ensure_ascii=False)
                yield f"event: token\ndata: {payload}\n\n"
            done_payload: dict[str, Any] = {"finish_reason": "stop"}
            answered_by = model_out.get(MODEL_USED_KEY)
            if answered_by:
                done_payload[MODEL_USED_KEY] = answered_by
            typesafe_timings = public_typesafe_metrics(retrieval_timings)
            if typesafe_timings:
                done_payload["timings"] = typesafe_timings
            yield "event: done\ndata: " + json.dumps(done_payload, ensure_ascii=False) + "\n\n"
        finally:
            _audit(
                user,
                "QUERY",
                knowledge_base_id=request.knowledge_base_id or "all",
                query=question,
                latency_ms=(time.perf_counter() - started) * 1000,
                num_sources=len(sources),
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/retrieval/debug")
def retrieval_debug(
    request: DebugRequest,
    user: CurrentUser = Depends(require_permission("retrieval:debug")),
):
    kb_ids = _allowed_ids(user, request.knowledge_base_id)
    query = redact_text(request.query)
    started = time.perf_counter()
    try:
        rows, retrieval_timings = retrieval_service.search_with_timings(
            query,
            top_k=request.top_k,
            mode=request.mode,
            rerank=request.rerank,
            knowledge_base_ids=kb_ids,
        )
    except Exception as exc:
        _audit(user, "RETRIEVAL_DEBUG", status="FAILED", query=query, detail=public_exception_detail(exc))
        raise HTTPException(status_code=503, detail=f"检索服务不可用：{public_exception_detail(exc)}") from exc

    _audit(
        user,
        "RETRIEVAL_DEBUG",
        knowledge_base_id=request.knowledge_base_id or "all",
        query=query,
        latency_ms=(time.perf_counter() - started) * 1000,
        num_sources=len(rows),
        detail=f"mode={request.mode},rerank={request.rerank}",
    )
    response = {
        "query": query,
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
    typesafe_timings = public_typesafe_metrics(retrieval_timings)
    if typesafe_timings:
        response["typesafe"] = typesafe_timings
    return redact_secrets(response)


@app.post("/api/evaluation/run")
def run_evaluation(
    request: EvaluationRequest,
    user: CurrentUser = Depends(require_permission("evaluation:run")),
):
    dataset_path = Path(__file__).resolve().parent.parent / "eval_dataset.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    # 取数入口一律过用户范围：这里的 `knowledge_base_id` 来自数据集而不是请求参数，
    # 但它同样会把库内容读进响应（`cases[].top_files` 等），所以先对数据集里出现过的每个
    # distinct 库调一次 `_allowed_ids(user, kb_id)`——权限错误自然抛 403 + 一行 ACCESS/DENIED
    # 审计，未知库 404。全部通过才开始跑，不存在"跑出半份报告再失败"。
    for kb_id in _dataset_knowledge_base_ids(dataset):
        _allowed_ids(user, kb_id)
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
        typesafe_case_metrics: list[dict[str, Any]] = []

        for item in dataset:
            rows, retrieval_timings = retrieval_service.search_with_timings(
                item["question"],
                top_k=request.top_k,
                mode=retrieval_mode,
                rerank=use_rerank,
                knowledge_base_ids=[item["knowledge_base_id"]],
            )
            safe_typesafe_metrics = public_typesafe_metrics(retrieval_timings)
            if safe_typesafe_metrics:
                typesafe_case_metrics.append(safe_typesafe_metrics)
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
        mode_report: dict[str, Any] = {
            "total": len(dataset),
            "hit_at_1": round(hits_at_1 / total, 4),
            f"hit_at_{request.top_k}": round(hits_at_k / total, 4),
            "mrr": round(reciprocal_rank / total, 4),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "rerank": use_rerank,
            "cases": cases,
        }
        if typesafe_case_metrics:
            p50_values = [
                float(item.get("typesafe_latency_p50_ms") or 0.0)
                for item in typesafe_case_metrics
            ]
            p95_values = [
                float(item.get("typesafe_latency_p95_ms") or 0.0)
                for item in typesafe_case_metrics
            ]
            mode_report["typesafe"] = {
                # effective 口径：`typesafe_enabled=false` 恒等价 "off"（Task 2 移交）。
                # 上报原始 `typesafe_mode` 会让评测报告在判定层整体关闭时仍写着 "shadow"，
                # 与 `typesafe_mode` metrics 键的值（同样已改 effective）互相打脸。
                "mode": settings.effective_typesafe_mode,
                "model": settings.typesafe_model,
                "degraded_cases": sum(
                    1 for item in typesafe_case_metrics if item.get("typesafe_degraded")
                ),
                "request_count": sum(
                    int(item.get("typesafe_request_count") or 0)
                    for item in typesafe_case_metrics
                ),
                "input_tokens": sum(
                    int(item.get("typesafe_input_tokens") or 0)
                    for item in typesafe_case_metrics
                ),
                "output_tokens": sum(
                    int(item.get("typesafe_output_tokens") or 0)
                    for item in typesafe_case_metrics
                ),
                "estimated_cost_usd": round(
                    sum(
                        float(item.get("typesafe_estimated_cost_usd") or 0.0)
                        for item in typesafe_case_metrics
                    ),
                    8,
                ),
                "latency_p50_ms": round(statistics.median(p50_values), 2),
                "latency_p95_ms": round(max(p95_values), 2),
                "total_ms": round(
                    sum(
                        float(item.get("typesafe_total_ms") or 0.0)
                        for item in typesafe_case_metrics
                    ),
                    2,
                ),
                "unauthorized_candidates_blocked": sum(
                    int(item.get("typesafe_unauthorized_candidates_blocked") or 0)
                    for item in typesafe_case_metrics
                ),
            }
        report[eval_mode] = mode_report

    _audit(
        user,
        "EVALUATION",
        latency_ms=(time.perf_counter() - overall_started) * 1000,
        detail=",".join(request.modes),
    )
    stored_run = persist_eval_run(
        dataset_size=len(dataset),
        top_k=request.top_k,
        report=report,
    )
    return {
        "run_id": stored_run["run_id"],
        "dataset_size": len(dataset),
        "top_k": request.top_k,
        "modes": request.modes,
        "report": report,
    }

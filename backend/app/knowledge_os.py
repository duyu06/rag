"""Knowledge OS API: search, chunk explorer, document lifecycle, ingestion jobs,
feedback, usage, system status, members, access requests, evaluation history.

This module is a leaf: it imports auth/store/retrieval/ingestion/knowledge/audit
(and the typesafe judgment module, which retrieval already depends on) only, so
main.py and main_agent.py can both depend on it without cycles.
"""
from __future__ import annotations

import json
import statistics
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.audit import AUDIT_PATH, recent_events, record_event
from app.auth import CurrentUser, USERS, require_permission, require_user
from app.config import settings
from app.ingestion import DOC_DIR, document_path, parse_document
from app.knowledge import get_base, resolve_for
from app.llm import usage as llm_usage
from app.llm.health import probe_llm
from app.rag import current_model_name
from app.retrieval import retrieval_service
from app.security import (
    public_exception_detail,
    public_llm_status,
    public_typesafe_stats,
    redact_secrets,
    redact_text,
)
from app.store import vector_store
from app.typesafe_judgments import typesafe_stats

router = APIRouter(prefix="/api", tags=["knowledge-os"])

DATA_DIR = Path("data")
REGISTRY_PATH = DATA_DIR / "document_registry.json"
JOBS_PATH = DATA_DIR / "ingestion_jobs.jsonl"
FEEDBACK_PATH = DATA_DIR / "feedback.jsonl"
EVAL_RUNS_PATH = DATA_DIR / "eval_runs.jsonl"
TRIAGE_PATH = DATA_DIR / "failure_triage.json"
ACCESS_REQUESTS_PATH = DATA_DIR / "access_requests.jsonl"
TRACES_PATH = DATA_DIR / "agent_traces.jsonl"

_WRITE_LOCK = Lock()

ROLE_DEPARTMENT = {
    "ADMIN": "平台管理",
    "SALES": "销售",
    "HR": "人力资源",
    "USER": "全员",
    "VIEWER": "外部访客",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(redact_secrets(payload), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(redact_secrets(record), ensure_ascii=False)
    with _WRITE_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with _WRITE_LOCK:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if limit is not None:
        lines = lines[-limit:]
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def _audit(user: CurrentUser, action: str, **kwargs) -> None:
    record_event(username=user.username, role=user.role, action=action, **kwargs)


def _scope(user: CurrentUser, knowledge_base_id: str | None) -> list[str]:
    """范围判定走 `knowledge.resolve_for`（授予为权威），此处只保留拒绝审计与 HTTP 映射。"""
    try:
        return resolve_for(user, knowledge_base_id)
    except PermissionError as exc:
        _audit(user, "ACCESS", status="DENIED", knowledge_base_id=knowledge_base_id, detail=redact_text(exc))
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=redact_text(exc)) from exc


def _key(kb_id: str, file_name: str) -> str:
    return f"{kb_id}::{file_name}"


# ---------- document registry (lifecycle state) ----------

def _registry() -> dict[str, dict[str, Any]]:
    data = _read_json(REGISTRY_PATH, {})
    return data if isinstance(data, dict) else {}


def registry_update(kb_id: str, file_name: str, **fields: Any) -> dict[str, Any]:
    data = _registry()
    entry = data.setdefault(_key(kb_id, file_name), {})
    entry.update({k: v for k, v in fields.items() if v is not None or k == "last_error"})
    data[_key(kb_id, file_name)] = entry
    _write_json(REGISTRY_PATH, data)
    return entry


def registry_entry(kb_id: str, file_name: str, *, chunk_count: int | None = None) -> dict[str, Any]:
    entry = dict(_registry().get(_key(kb_id, file_name)) or {})
    if "enabled" not in entry:
        entry["enabled"] = True
    if "archived" not in entry:
        entry["archived"] = False
    if not entry.get("status"):
        if entry.get("enabled") is False:
            entry["status"] = "DISABLED"
        elif chunk_count is None:
            entry["status"] = "UNKNOWN"
        else:
            entry["status"] = "READY" if chunk_count > 0 else "MISSING_INDEX"
    return entry


def registry_remove(kb_id: str, file_name: str) -> None:
    data = _registry()
    if data.pop(_key(kb_id, file_name), None) is not None:
        _write_json(REGISTRY_PATH, data)


def excluded_document_keys() -> set[str]:
    keys = set()
    for key, entry in _registry().items():
        if entry.get("archived") or entry.get("enabled") is False:
            keys.add(key)
    return keys


def is_document_excluded(kb_id: Any, file_name: Any) -> bool:
    if not kb_id or not file_name:
        return False
    return _key(str(kb_id), str(file_name)) in excluded_document_keys()


# ---------- ingestion pipeline jobs ----------

def _stage(name: str, status: str, *, detail: str | None = None, error: str | None = None, elapsed_ms: float | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"name": name, "status": status}
    if detail:
        record["detail"] = detail
    if error:
        record["error"] = error
    if elapsed_ms is not None:
        record["elapsed_ms"] = elapsed_ms
    return record


def run_ingest_job(user: CurrentUser, path: Path, kb_id: str, *, origin: str = "upload") -> int:
    """Stage-tracked ingest: UPLOAD -> PARSE -> NORMALIZE -> CHUNK -> EMBED -> INDEX."""
    base = get_base(kb_id)
    job_id = uuid.uuid4().hex[:12]
    created_at = _now()
    total_started = time.perf_counter()
    stages: list[dict[str, Any]] = []
    current = "UPLOAD"
    stored = 0
    failure: str | None = None
    registry_update(kb_id, path.name, status="INDEXING", last_error=None)
    try:
        size_bytes = path.stat().st_size
        stages.append(_stage("UPLOAD", "ok", detail=f"{path.name} · {round(size_bytes / 1024, 1)} KB", elapsed_ms=0.0))
        current = "PARSE"
        started = time.perf_counter()
        chunks = parse_document(path)
        if not chunks:
            raise ValueError("文档未解析出有效文本")
        stages.append(_stage("PARSE", "ok", elapsed_ms=_ms(started), detail=f"{len(chunks)} 个原始区块"))
        current = "NORMALIZE"
        stages.append(_stage("NORMALIZE", "ok", elapsed_ms=0.0, detail="空白清洗 + 页码/章节元数据"))
        current = "CHUNK"
        stages.append(_stage("CHUNK", "ok", elapsed_ms=0.0, detail=f"{len(chunks)} chunks · size={settings.chunk_size}/overlap={settings.chunk_overlap}"))
        vector_store.delete_file(path.name, kb_id)
        current = "EMBED"
        enriched = [
            {
                **chunk,
                "file_name": path.name,
                "file_type": path.suffix.lower().lstrip("."),
                "document_title": path.stem,
                "knowledge_base_id": kb_id,
                "knowledge_base_name": base["name"],
                "retrieval_schema_version": settings.retrieval_schema_version,
            }
            for chunk in chunks
        ]
        started = time.perf_counter()
        stored = vector_store.add_chunks(enriched)
        stages.append(_stage("EMBED", "ok", elapsed_ms=_ms(started), detail=settings.embedding_model))
        current = "INDEX"
        stages.append(_stage("INDEX", "ok", elapsed_ms=0.0, detail=f"{stored} points upserted → {settings.qdrant_collection}"))
        registry_update(kb_id, path.name, status="READY", updated_at=created_at, last_error=None)
        return stored
    except Exception as exc:
        failure = public_exception_detail(exc)
        stages.append(_stage(current, "failed", error=failure))
        registry_update(kb_id, path.name, status="FAILED", updated_at=created_at, last_error=failure)
        raise
    finally:
        _append_jsonl(
            JOBS_PATH,
            {
                "job_id": job_id,
                "origin": origin,
                "username": user.username,
                "file_name": path.name,
                "knowledge_base_id": kb_id,
                "knowledge_base_name": base["name"],
                "status": "READY" if failure is None else "FAILED",
                "total_elapsed_ms": _ms(total_started),
                "created_at": created_at,
                "stages": stages,
            },
        )


def _normalize_job(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": record.get("job_id"),
        "file_name": record.get("file_name"),
        "knowledge_base_id": record.get("knowledge_base_id"),
        "knowledge_base_name": record.get("knowledge_base_name"),
        "status": record.get("status", "FAILED"),
        "total_elapsed_ms": record.get("total_elapsed_ms"),
        "created_at": record.get("created_at"),
        "stages": [
            {
                "name": stage.get("name"),
                "status": "ok" if stage.get("status") == "ok" else "failed",
                "detail": stage.get("detail"),
                "error": stage.get("error"),
                "elapsed_ms": stage.get("elapsed_ms"),
            }
            for stage in record.get("stages", [])
            if isinstance(stage, dict)
        ],
    }


# ---------- query payloads ----------

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=20, ge=1, le=50)
    knowledge_base_id: str | None = None


class DocumentActionRequest(BaseModel):
    file_name: str
    knowledge_base_id: str
    target_knowledge_base_id: str | None = None


class FeedbackRequest(BaseModel):
    conversation_id: str | None = None
    message_id: str | None = None
    question: str = Field(min_length=1, max_length=1000)
    verdict: Literal["up", "down"]
    category: str | None = None
    detail: str | None = None


class FailurePatchRequest(BaseModel):
    failure_type: str | None = None
    root_cause: str | None = None
    action: str | None = None
    regression: bool | None = None


class AccessRequestPayload(BaseModel):
    resource: str = Field(min_length=1, max_length=200)
    policy: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)


# ---------- Search (find documents, not answers) ----------

@router.post("/search")
def search(
    payload: SearchRequest,
    user: CurrentUser = Depends(require_permission("knowledge:read")),
):
    kb_ids = _scope(user, payload.knowledge_base_id)
    query = redact_text(payload.query)
    started = time.perf_counter()
    try:
        rows, timings = retrieval_service.search_with_timings(
            query, top_k=payload.top_k, mode="hybrid", rerank=False, knowledge_base_ids=kb_ids
        )
    except Exception as exc:
        _audit(user, "SEARCH", status="FAILED", query=query, detail=public_exception_detail(exc))
        raise HTTPException(status_code=503, detail=f"检索服务不可用：{public_exception_detail(exc)}") from exc

    results = []
    for row in rows:
        if is_document_excluded(row.get("knowledge_base_id"), row.get("file_name")):
            continue
        kb_id = row.get("knowledge_base_id")
        department = None
        try:
            department = get_base(str(kb_id)).get("department") if kb_id else None
        except ValueError:
            pass
        results.append(
            {
                "file_name": row.get("file_name"),
                "knowledge_base_id": kb_id,
                "knowledge_base_name": row.get("knowledge_base_name"),
                "page": row.get("page"),
                "section": row.get("section_title"),
                "content": str(row.get("content", ""))[:600],
                "score": row.get("hybrid_score", row.get("vector_score")),
                "file_type": row.get("file_type"),
                "department": department,
                "updated_at": row.get("uploaded_at"),
            }
        )
    took_ms = float(timings.get("total_ms") or _ms(started))
    _audit(user, "SEARCH", knowledge_base_id=payload.knowledge_base_id or "all", query=query, latency_ms=took_ms, num_sources=len(results))
    return {"results": results, "took_ms": round(took_ms, 1)}


# ---------- Chunk Explorer ----------

def _estimate_tokens(text: str) -> int:
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return max(1, cjk + (len(text) - cjk) // 4)


@router.get("/chunks")
def list_chunks(
    knowledge_base_id: str | None = Query(default=None),
    file_name: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_permission("knowledge:read")),
):
    kb_ids = _scope(user, knowledge_base_id)
    try:
        rows = vector_store.all_chunks(knowledge_base_ids=kb_ids)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"向量库不可用：{public_exception_detail(exc)}") from exc
    excluded = excluded_document_keys()
    filtered = []
    for row in rows:
        if _key(str(row.get("knowledge_base_id")), str(row.get("file_name"))) in excluded:
            continue
        if file_name and str(row.get("file_name")) != file_name:
            continue
        filtered.append(row)
    filtered.sort(key=lambda row: (str(row.get("file_name")), row.get("chunk_index") if row.get("chunk_index") is not None else 0))
    page = filtered[offset : offset + limit]
    return {
        "chunks": [
            {
                "id": str(row.get("id")),
                "file_name": row.get("file_name"),
                "knowledge_base_id": row.get("knowledge_base_id"),
                "knowledge_base_name": row.get("knowledge_base_name"),
                "page": row.get("page"),
                "section": row.get("section_title"),
                "chunk_index": row.get("chunk_index"),
                "content": row.get("content", ""),
                "tokens": _estimate_tokens(str(row.get("content", ""))),
                "uploaded_at": row.get("uploaded_at"),
            }
            for row in page
        ],
        "total": len(filtered),
    }


# ---------- Document lifecycle ----------

@router.post("/documents/{action}")
def document_action(
    action: str,
    payload: DocumentActionRequest,
    user: CurrentUser = Depends(require_permission("knowledge:manage")),
):
    if action not in {"reindex", "enable", "disable", "archive", "restore", "move"}:
        raise HTTPException(status_code=400, detail=f"不支持的文档操作：{action}")
    _scope(user, payload.knowledge_base_id)
    name = Path(payload.file_name).name
    kb_id = payload.knowledge_base_id
    try:
        get_base(kb_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=redact_text(exc)) from exc

    if action == "reindex":
        path = document_path(kb_id, name)
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"原始文件不存在，无法重建索引：{name}")
        try:
            stored = run_ingest_job(user, path, kb_id, origin="reindex")
        except Exception as exc:
            _audit(user, "DOCUMENT_REINDEX", status="FAILED", knowledge_base_id=kb_id, detail=f"{name}: {public_exception_detail(exc)}")
            raise HTTPException(status_code=500, detail=f"重建索引失败：{public_exception_detail(exc)}") from exc
        _audit(user, "DOCUMENT_REINDEX", knowledge_base_id=kb_id, num_sources=stored, detail=name)
        return {"success": True, "message": "索引已重建", "file_name": name, "chunks_stored": stored}

    if action == "move":
        target = payload.target_knowledge_base_id
        if not target or target == kb_id:
            raise HTTPException(status_code=400, detail="移动需要提供不同的目标知识库")
        _scope(user, target)
        try:
            get_base(target)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=redact_text(exc)) from exc
        source_path = document_path(kb_id, name)
        if not source_path.is_file():
            raise HTTPException(status_code=404, detail=f"原始文件不存在：{name}")
        target_path = document_path(target, name)
        try:
            target_path.write_bytes(source_path.read_bytes())
            source_path.unlink(missing_ok=True)
            vector_store.delete_file(name, kb_id)
            stored = run_ingest_job(user, target_path, target, origin="move")
        except Exception as exc:
            _audit(user, "DOCUMENT_MOVE", status="FAILED", knowledge_base_id=kb_id, detail=f"{name}: {public_exception_detail(exc)}")
            raise HTTPException(status_code=500, detail=f"文档移动失败：{public_exception_detail(exc)}") from exc
        data = _registry()
        old = data.pop(_key(kb_id, name), {})
        new_entry = data.setdefault(_key(target, name), {})
        new_entry.update({k: v for k, v in old.items() if k not in {"status", "last_error"}})
        new_entry.update({"status": "READY", "updated_at": _now(), "moved_from": kb_id})
        _write_json(REGISTRY_PATH, data)
        _audit(user, "DOCUMENT_MOVE", knowledge_base_id=target, num_sources=stored, detail=f"{name}: {kb_id} -> {target}")
        return {"success": True, "message": "文档已移动并重建索引", "file_name": name, "knowledge_base_id": target, "chunks_stored": stored}

    # enable / disable / archive / restore are pure registry transitions
    if action == "enable":
        entry = registry_update(kb_id, name, enabled=True, status="READY")
    elif action == "disable":
        entry = registry_update(kb_id, name, enabled=False, status="DISABLED")
    elif action == "archive":
        entry = registry_update(kb_id, name, archived=True, enabled=False, status="DISABLED")
    else:  # restore
        entry = registry_update(kb_id, name, archived=False, enabled=True, status="READY")
    _audit(user, "DOCUMENT_" + action.upper(), knowledge_base_id=kb_id, detail=name)
    return {"success": True, "message": f"{name} 已更新", "file_name": name, "knowledge_base_id": kb_id, "document": entry}


@router.get("/ingestion/jobs")
def ingestion_jobs(
    limit: int = Query(default=20, ge=1, le=200),
    user: CurrentUser = Depends(require_permission("audit:read")),
):
    records = _read_jsonl(JOBS_PATH, limit=limit * 4)
    jobs = [_normalize_job(record) for record in reversed(records[-limit:])]
    return {"jobs": jobs}


# ---------- Feedback ----------

@router.post("/feedback")
def submit_feedback(
    payload: FeedbackRequest,
    user: CurrentUser = Depends(require_user),
):
    record = {
        "id": uuid.uuid4().hex[:12],
        "username": user.username,
        "created_at": _now(),
        **payload.model_dump(),
    }
    _append_jsonl(FEEDBACK_PATH, record)
    _audit(user, "FEEDBACK", query=payload.question, detail=f"verdict={payload.verdict},category={payload.category or '-'}")
    return {"success": True, "id": record["id"]}


@router.get("/feedback")
def feedback_list(
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(require_permission("audit:read")),
):
    records = _read_jsonl(FEEDBACK_PATH, limit=limit)
    items = [
        {
            "id": r.get("id"),
            "username": r.get("username"),
            "question": r.get("question"),
            "verdict": r.get("verdict"),
            "category": r.get("category"),
            "detail": r.get("detail"),
            "created_at": r.get("created_at"),
        }
        for r in reversed(records)
    ]
    return {"items": items}


# ---------- Operations usage ----------

@router.get("/operations/usage")
def usage_summary(user: CurrentUser = Depends(require_permission("audit:read"))):
    events = recent_events(20000)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    queries = [
        e for e in events
        if e.get("action") == "QUERY" and e.get("status") == "SUCCESS" and str(e.get("timestamp", "")) >= cutoff
    ]
    active_users = {str(e.get("username")) for e in queries if e.get("username")}
    latencies = [float(e["latency_ms"]) for e in queries if e.get("latency_ms") is not None]
    dept_counter: Counter[str] = Counter()
    for event in queries:
        record = USERS.get(str(event.get("username")))
        if record:
            dept_counter[ROLE_DEPARTMENT.get(str(record.get("role")), "其他")] += 1
    top = dept_counter.most_common(1)
    total_users = max(len(USERS), 1)
    return {
        "active_users": len(active_users),
        "total_users": len(USERS),
        "queries_30d": len(queries),
        "adoption_pct": round(len(active_users) / total_users * 100, 1),
        "top_department": {"name": top[0][0], "queries": top[0][1]} if top else None,
        "queries_today": sum(1 for e in queries if str(e.get("timestamp", "")).startswith(today)),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
    }


# ---------- System status ----------

def _percentile(values: list[float], quantile: float) -> float | None:
    if len(values) < 5:
        return None
    ordered = sorted(values)
    index = min(round(quantile * (len(ordered) - 1)), len(ordered) - 1)
    return round(ordered[index], 1)


def _trace_latency_stats() -> dict[str, float | None]:
    traces = _read_jsonl(TRACES_PATH, limit=60)
    llm_values = [
        float(t["timings"]["llm_ms"])
        for t in traces
        if isinstance(t.get("timings"), dict) and t["timings"].get("llm_ms") is not None
    ]
    ttft_values = [
        float(t["timings"]["ttft_ms"])
        for t in traces
        if isinstance(t.get("timings"), dict) and t["timings"].get("ttft_ms") is not None
    ]
    return {
        "p50_ms": round(statistics.median(llm_values), 1) if llm_values else None,
        "p95_ms": _percentile(llm_values, 0.95),
        "ttft_ms": round(statistics.median(ttft_values), 1) if ttft_values else None,
    }


@router.get("/system/status")
def system_status(user: CurrentUser = Depends(require_permission("system:operate"))):
    qdrant_ok = vector_store.ping()
    llm_ok, _llm_detail = probe_llm()
    provider = "openai-compatible" if settings.openai_api_key else "ollama"
    try:
        store_stats = vector_store.stats()
    except Exception:
        store_stats = {"total_chunks": 0, "collection_name": settings.qdrant_collection, "embedding_dimension": None}
    chunks = int(store_stats.get("total_chunks") or 0)

    documents = 0
    for kb_dir in DOC_DIR.glob("*"):
        if kb_dir.is_dir():
            documents += sum(1 for f in kb_dir.iterdir() if f.is_file())
    failed_jobs = sum(1 for record in _read_jsonl(JOBS_PATH, limit=500) if record.get("status") == "FAILED")
    registry = _registry()
    sync_times = [str(entry.get("updated_at")) for entry in registry.values() if entry.get("updated_at")]
    llm_stats = _trace_latency_stats()

    bm25_status = "ONLINE" if chunks > 0 else "DEGRADED"
    reranker_status = "ONLINE" if settings.rerank_model else "OFFLINE"
    components = [
        qdrant_ok,
        llm_ok,
        bm25_status == "ONLINE",
        reranker_status == "ONLINE",
    ]
    overall = "ONLINE" if all(components) else ("OFFLINE" if not qdrant_ok else "DEGRADED")
    # 判定层观测块（设计 §7）。三条口径写在源头，免得下游各自猜：
    # 1) `mode` 用 `effective_typesafe_mode`：`typesafe_enabled=false` 恒等价 "off"，
    #    与检索层/判定层的实际行为同一个口径（Task 2 移交的原始 mode 上报点之一）。
    # 2) 聚合键一律过 `public_typesafe_stats` 白名单：`typesafe_stats()` 会长键
    #    （Task 5 就在 §7 之外多了 `sample_count`/`slow_rate`），响应面不跟着长。
    # 3) `skip_rate`/`trigger_rate` 的分母是"进入判定层的请求"（Task 5 自决 7）：
    #    selective/active 的路由免判压根不调用判定服务，故不在分母里。
    # 已知副作用：`breaker_state` 走 `CircuitBreaker.state`（"观测即推进"，Task 1 限制），
    # 本端点只在系统页手动加载/刷新时采样，不是轮询热路径。
    typesafe_block: dict[str, Any] = {
        "mode": settings.effective_typesafe_mode,
        **public_typesafe_stats(typesafe_stats()),
    }
    return {
        "overall": overall,
        # §8 的 `llm` 观测块：**additive 合并**，不是替换。前六个键是 V2.3 之前就存在的
        # 探针面（`SystemView` 在消费 `status/model/provider/p50_ms/p95_ms/ttft_ms`，
        # §9「既有响应结构对外不变」），后七个键是 Router 的聚合出口。两组合起来没有
        # 一个同名键（`p95_ms` 是 trace 面的生成耗时，`p95_latency_ms` 是 usage 面的
        # 全链耗时——**故意不同名**，让它们各自说清自己量的是什么）。
        # 聚合并不外泄行：`aggregate_status` 只回比率/分位数/provider 名，且整块再过
        # `public_llm_status` 白名单（deny-by-default）。`LLM_ROUTER_ENABLED=false` 时
        # 聚合块是空形状，不探测、不读库。
        "llm": public_llm_status({
            "status": "ONLINE" if llm_ok else "OFFLINE",
            "model": current_model_name(),
            "provider": provider,
            **llm_stats,
            **llm_usage.aggregate_status(),
        }),
        "embedding": {
            "status": "ONLINE" if qdrant_ok else "OFFLINE",
            "model": settings.embedding_model,
            "dimension": store_stats.get("embedding_dimension"),
        },
        "bm25": {"status": bm25_status},
        "reranker": {"status": reranker_status, "model": settings.rerank_model},
        "vector_db": {"status": "ONLINE" if qdrant_ok else "OFFLINE", "collection": store_stats.get("collection_name")},
        "index": {
            "documents": documents,
            "chunks": chunks,
            "failed_jobs": failed_jobs,
            "last_sync_at": max(sync_times) if sync_times else None,
        },
        "typesafe": typesafe_block,
    }


# ---------- Members & access requests ----------

@router.get("/auth/users")
def list_users(user: CurrentUser = Depends(require_permission("audit:read"))):
    events = recent_events(5000)
    last_login: dict[str, str] = {}
    for event in events:
        if event.get("action") == "LOGIN" and event.get("status") == "SUCCESS":
            name = str(event.get("username"))
            ts = str(event.get("timestamp", ""))
            if ts >= last_login.get(name, ""):
                last_login[name] = ts
    users = [
        {
            "username": record["username"],
            "display_name": record["display_name"],
            "role": record["role"],
            "department": ROLE_DEPARTMENT.get(str(record["role"]), "其他"),
            "status": "ACTIVE",
            "last_login": last_login.get(record["username"]),
        }
        for record in USERS.values()
    ]
    return {"users": users}


@router.post("/access/requests")
def request_access(
    payload: AccessRequestPayload,
    user: CurrentUser = Depends(require_user),
):
    record = {
        "id": uuid.uuid4().hex[:12],
        "username": user.username,
        "role": user.role,
        "status": "PENDING",
        "created_at": _now(),
        **payload.model_dump(),
    }
    _append_jsonl(ACCESS_REQUESTS_PATH, record)
    _audit(user, "ACCESS_REQUEST", detail=f"{payload.resource}::{payload.policy}")
    return {"success": True, "id": record["id"], "message": "申请已提交，等待管理员处理"}


# ---------- Evaluation persistence ----------

def persist_eval_run(*, dataset_size: int, top_k: int, report: dict[str, Any], name_prefix: str = "eval") -> dict[str, Any]:
    run_id = uuid.uuid4().hex[:10]
    stamp = datetime.now(timezone.utc)
    modes: dict[str, Any] = {}
    cases: dict[str, list[dict[str, Any]]] = {}
    for mode, block in report.items():
        hit_at_k_key = f"hit_at_{top_k}" if f"hit_at_{top_k}" in block else "hit_at_3"
        modes[mode] = {
            "hit_at_1": block.get("hit_at_1"),
            "hit_at_3": block.get(hit_at_k_key) if top_k == 3 else block.get("hit_at_3", block.get(hit_at_k_key)),
            "mrr": block.get("mrr"),
            "total": block.get("total"),
            "elapsed_ms": block.get("elapsed_ms"),
        }
        mode_cases = []
        for index, case in enumerate(block.get("cases", [])):
            rank = case.get("rank")
            passed = rank is not None and rank <= top_k
            mode_cases.append(
                {
                    "case_id": f"{mode}-{index:02d}",
                    "question": case.get("question"),
                    "expected_file": case.get("expected_file"),
                    "tag": case.get("knowledge_base_id"),
                    "rank": rank,
                    "top_files": case.get("top_files") or [],
                    "passed": passed,
                }
            )
        cases[mode] = mode_cases
    run = {
        "run_id": run_id,
        "name": f"{name_prefix}-{stamp.strftime('%Y%m%d-%H%M%S')}",
        "created_at": stamp.isoformat(),
        "dataset_size": dataset_size,
        "top_k": top_k,
        "modes": modes,
        "cases": cases,
    }
    _append_jsonl(EVAL_RUNS_PATH, run)
    return run


@router.get("/evaluation/runs")
def evaluation_runs(
    limit: int = Query(default=10, ge=1, le=100),
    user: CurrentUser = Depends(require_permission("evaluation:run")),
):
    records = _read_jsonl(EVAL_RUNS_PATH, limit=limit * 3)
    runs = []
    for record in reversed(records[-limit:]):
        summary = {k: v for k, v in record.items() if k != "cases"}
        summary.setdefault("dataset_size", 0)
        summary.setdefault("modes", {})
        runs.append(summary)
    return {"runs": runs}


def _fetch_run(run_id: str) -> dict[str, Any]:
    for record in reversed(_read_jsonl(EVAL_RUNS_PATH, limit=2000)):
        if record.get("run_id") == run_id:
            return record
    raise HTTPException(status_code=404, detail="评测记录不存在")


@router.get("/evaluation/runs/{run_id}")
def evaluation_run_detail(run_id: str, user: CurrentUser = Depends(require_permission("evaluation:run"))):
    return _fetch_run(run_id)


@router.get("/evaluation/failures")
def evaluation_failures(user: CurrentUser = Depends(require_permission("evaluation:run"))):
    records = _read_jsonl(EVAL_RUNS_PATH, limit=1000)
    if not records:
        return {"cases": []}
    latest = records[-1]
    triage = _read_json(TRIAGE_PATH, {})
    cases: list[dict[str, Any]] = []
    for mode, items in (latest.get("cases") or {}).items():
        for case in items:
            if case.get("passed"):
                continue
            case_id = str(case.get("case_id") or f"{mode}-unknown")
            annotations = triage.get(case_id) or {}
            cases.append(
                {
                    "case_id": case_id,
                    "run_id": latest.get("run_id"),
                    "question": case.get("question"),
                    "expected_file": case.get("expected_file"),
                    "tag": case.get("tag"),
                    "rank": case.get("rank"),
                    "actual_rank": case.get("rank"),
                    "top_files": case.get("top_files") or [],
                    "passed": False,
                    "failure_type": annotations.get("failure_type"),
                    "root_cause": annotations.get("root_cause"),
                    "action": annotations.get("action"),
                    "regression": bool(annotations.get("regression", False)),
                }
            )
    return {"cases": cases}


@router.patch("/evaluation/failures/{case_id}")
def patch_failure(
    case_id: str,
    payload: FailurePatchRequest,
    user: CurrentUser = Depends(require_permission("evaluation:run")),
):
    triage = _read_json(TRIAGE_PATH, {})
    entry = dict(triage.get(case_id) or {})
    entry.update({k: v for k, v in payload.model_dump().items() if v is not None})
    entry["updated_at"] = _now()
    entry["updated_by"] = user.username
    triage[case_id] = entry
    _write_json(TRIAGE_PATH, triage)
    _audit(user, "EVAL_FAILURE_TRIAGE", detail=f"{case_id}: {entry.get('failure_type') or '-'}")
    return {"success": True, "case_id": case_id, "triage": entry}


# ---------- Query Trace stage events (shared by agent + fast path) ----------

TRACE_STAGES = (
    "query_received",
    "query_rewrite",
    "acl_filter",
    "vector_search",
    "bm25",
    "hybrid_fusion",
    "rerank",
    "context_build",
    "generation",
    "citation_verify",
)


def build_stage_events(
    timings: dict[str, Any] | None,
    *,
    scope_count: int,
    evidence_count: int,
    query_rewrite: bool = False,
) -> list[dict[str, Any]]:
    data = timings or {}

    def timed(name: str, key: str, detail: str | None = None) -> dict[str, Any]:
        value = data.get(key)
        if value is None:
            return {"type": "stage", "stage": name, "status": "skipped", "elapsed_ms": None, "detail": detail or "未启用"}
        return {"type": "stage", "stage": name, "status": "ok", "elapsed_ms": round(float(value), 1), "detail": detail}

    # 判定层子事件（设计 §7）：重排阶段的 detail 追加"触发 / 缓存命中 / 熔断 / 跳过"。
    # 三条刻意约束：
    # - 只认这四枚已进 `PUBLIC_TYPESAFE_METRIC_KEYS` 的键，缺键整段不渲染——路由免判
    #   与 mode=off 的批次没有批次键（Task 6 交接第 1 条："存在才透传，别假设齐套"）。
    # - 不新增事件类型、不新增事件字段：前端 `TraceView` 按 stage 事件 + detail 文本
    #   渲染，多出来的未知键是它的盲区（也是"前端未知键风险"本身）。
    # - 值取自调用方已白名单化 + 脱敏后的 timings，本函数不再碰原始批次。
    def typesafe_flags() -> str | None:
        bits: list[str] = []
        if data.get("typesafe_trigger") is not None:
            bits.append(f"触发 {'是' if data['typesafe_trigger'] else '否'}")
        if data.get("typesafe_cache_hit") is not None:
            bits.append(f"缓存命中 {data['typesafe_cache_hit']}")
        if data.get("typesafe_circuit_open") is not None:
            bits.append(f"熔断 {'打开' if data['typesafe_circuit_open'] else '闭合'}")
        if data.get("typesafe_skip") is not None:
            bits.append(f"跳过 {'是' if data['typesafe_skip'] else '否'}")
        return " · ".join(bits) or None

    rerank_detail = (
        f"model={settings.rerank_model}"
        if data.get("rerank_ms") is not None
        else "未启用 Rerank"
    )
    typesafe_bits = typesafe_flags()
    if typesafe_bits:
        rerank_detail = f"{rerank_detail} · {typesafe_bits}"

    events = [
        {"type": "stage", "stage": "query_received", "status": "ok", "elapsed_ms": 0.0, "detail": "query accepted & redacted"},
        {"type": "stage", "stage": "query_rewrite", "status": "ok" if query_rewrite else "skipped", "elapsed_ms": None, "detail": "passthrough（未启用改写）"},
        {"type": "stage", "stage": "acl_filter", "status": "ok", "elapsed_ms": 0.0, "detail": f"scopes={scope_count or 'role-visible'}"},
        timed("vector_search", "vector_ms", f"candidates={data.get('vector_candidates', '—')}"),
        timed("bm25", "bm25_ms", f"{'cache hit' if data.get('bm25_cache_hit') else 'cache miss'} · candidates={data.get('bm25_candidates', '—')}"),
        timed("hybrid_fusion", "fusion_ms", str(data.get("fusion") or "rrf")),
        timed("rerank", "rerank_ms", rerank_detail),
        timed("context_build", "diversity_ms", f"returned={data.get('returned_documents', evidence_count)}"),
    ]
    llm_ms = data.get("llm_ms")
    if llm_ms is not None:
        events.append({"type": "stage", "stage": "generation", "status": "ok", "elapsed_ms": round(float(llm_ms), 1), "detail": f"ttft={data.get('ttft_ms')}ms" if data.get("ttft_ms") is not None else f"model={settings.ollama_model}"})
    else:
        events.append({"type": "stage", "stage": "generation", "status": "skipped", "elapsed_ms": None, "detail": "无生成阶段（检索调试）"})
    events.append(
        {"type": "stage", "stage": "citation_verify", "status": "ok" if evidence_count > 0 else "skipped", "elapsed_ms": 0.0, "detail": f"citations={evidence_count}"}
    )
    return events

from __future__ import annotations

from app.agent_routes import router as agent_router
from app.config import settings
from app.conversation_routes import router as conversation_router
from app.conversation_stream_routes import router as conversation_stream_router
from app.enterprise_routes import router as enterprise_router
from app.llm_admin_routes import router as llm_admin_router
from app.main import app
from app.llm_provider import current_provider_name
from app.llm_router import router_registry_snapshot
from app.rag import current_model_name, probe_llm, probe_ollama
from app.store import vector_store

# P1.8 runtime metadata for the yaoke Agent entrypoint.
app.title = "yaoke API"
app.version = "0.8.0"
app.description = "yaoke enterprise AI knowledge and tool-calling agent API"

# Replace base RAG product/health routes with P1.8 Agent + Conversation semantics.
# Legacy app.main remains independently usable when imported directly.
for route in list(app.router.routes):
    path = getattr(route, "path", None)
    methods = getattr(route, "methods", set()) or set()
    if path in {"/", "/api/health"} and "GET" in methods:
        app.router.routes.remove(route)


@app.get("/")
def yaoke_root():
    return {
        "name": "yaoke",
        "product": "Enterprise AI Knowledge & Agent Platform",
        "version": "0.8.0",
        "phase": "P1.8",
        "docs": "/docs",
        "health": "/api/health",
        "ready": "/api/ready",
    }


@app.get("/api/health")
def yaoke_health():
    qdrant_ok = vector_store.ping()
    agent_ok, agent_detail = probe_llm()
    try:
        provider = current_provider_name()
        model = current_model_name()
    except Exception:
        provider = str(settings.llm_provider or "auto")
        model = str(settings.llm_model or settings.ollama_model)

    return {
        # Agent and legacy RAG now share the same provider adapter.
        "status": "healthy" if (qdrant_ok and agent_ok) else "degraded",
        "version": "0.8.0",
        "phase": "P1.8",
        "native_streaming": True,
        "model_router_enabled": bool(settings.llm_router_enabled),
        "vector_db_connected": qdrant_ok,
        "llm_connected": agent_ok,
        "llm_detail": agent_detail,
        "ollama_connected": agent_ok if provider == "ollama" else False,
        "llm_provider": provider,
        "llm_model": model,
        "agent_llm_connected": agent_ok,
        "agent_llm_detail": agent_detail,
        "agent_llm_provider": provider,
        "agent_llm_model": model,
        "legacy_rag_connected": agent_ok,
        "legacy_rag_detail": agent_detail,
        "legacy_rag_provider": provider,
        "legacy_rag_model": model,
    }


app.include_router(agent_router)
app.include_router(llm_admin_router)
app.include_router(enterprise_router)
app.include_router(conversation_router)
app.include_router(conversation_stream_router)

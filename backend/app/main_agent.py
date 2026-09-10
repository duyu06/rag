from __future__ import annotations

from app.agent_routes import router as agent_router
from app.config import settings
from app.conversation_routes import router as conversation_router
from app.main import app
from app.rag import current_model_name, probe_llm, probe_ollama
from app.store import vector_store

# P1.4 runtime metadata for the yaoke Agent entrypoint.
app.title = "yaoke API"
app.version = "0.4.0"
app.description = "yaoke enterprise AI knowledge and tool-calling agent API"

# Replace base RAG product/health routes with P1.4 Agent semantics.
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
        "version": "0.4.0",
        "docs": "/docs",
        "health": "/api/health",
        "ready": "/api/ready",
    }


@app.get("/api/health")
def yaoke_health():
    qdrant_ok = vector_store.ping()
    agent_ok, agent_detail = probe_ollama()

    if settings.openai_api_key:
        legacy_ok, legacy_detail = probe_llm()
        legacy_provider = "openai-compatible"
    else:
        legacy_ok, legacy_detail = agent_ok, agent_detail
        legacy_provider = "ollama"

    return {
        # P1.4 frontend and preflight use these compatibility fields. They must
        # describe the provider run_agent() actually calls.
        "status": "healthy" if (qdrant_ok and agent_ok) else "degraded",
        "vector_db_connected": qdrant_ok,
        "llm_connected": agent_ok,
        "llm_detail": agent_detail,
        "ollama_connected": agent_ok,
        "llm_provider": "ollama",
        "llm_model": settings.ollama_model,
        "agent_llm_connected": agent_ok,
        "agent_llm_detail": agent_detail,
        "agent_llm_provider": "ollama",
        "agent_llm_model": settings.ollama_model,
        # Optional legacy RAG path may use OpenAI-compatible instead.
        "legacy_rag_connected": legacy_ok,
        "legacy_rag_detail": legacy_detail,
        "legacy_rag_provider": legacy_provider,
        "legacy_rag_model": current_model_name(),
    }


app.include_router(agent_router)
app.include_router(conversation_router)

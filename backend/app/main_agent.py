from __future__ import annotations

from app.agent_routes import router as agent_router
from app.main import app

# P1.4 runtime metadata for the yaoke Agent entrypoint.
app.title = "yaoke API"
app.version = "0.4.0"
app.description = "yaoke enterprise AI knowledge and tool-calling agent API"

# Replace the base RAG root with the P1.4 product identity.
for route in list(app.router.routes):
    if getattr(route, "path", None) == "/" and "GET" in (getattr(route, "methods", set()) or set()):
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


app.include_router(agent_router)

from __future__ import annotations

from app.agent_routes import router as agent_router
from app.main import app

# yaoke branding lives at the P1.4 entrypoint while preserving legacy RAG routes.
app.title = "yaoke API"
app.description = "yaoke enterprise AI knowledge and tool-calling agent API"

# Replace the legacy root identity without touching the stable P1.3 route module.
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

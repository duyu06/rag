from __future__ import annotations

from app.agent_routes import router as agent_router
from app.main import app

# Keep the proven P1.3 endpoints untouched and layer the P1.4 Agent API on top.
app.include_router(agent_router)

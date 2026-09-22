from __future__ import annotations

from fastapi import APIRouter, Depends

from app.audit import record_event
from app.auth import CurrentUser, require_admin, require_user
from app.llm_metrics import reset_llm_metrics
from app.llm_provider import probe_llm, resolve_llm_config
from app.llm_router import (
    reset_circuit_breakers,
    router_registry_snapshot,
)

router = APIRouter(prefix="/api/admin/llm", tags=["llm-admin"])


@router.get("/router")
def llm_router_status(user: CurrentUser = Depends(require_user)):
    require_admin(user)
    return router_registry_snapshot()


@router.get("/providers/health")
def llm_provider_health(user: CurrentUser = Depends(require_user)):
    require_admin(user)
    registry = router_registry_snapshot()
    results: list[dict] = []
    for item in registry.get("providers", []):
        provider = str(item.get("provider") or "")
        if not item.get("configured"):
            results.append(
                {
                    "provider": provider,
                    "configured": False,
                    "connected": False,
                    "detail": "not_configured",
                }
            )
            continue
        try:
            primary = registry.get("primary", {})
            cfg = (
                resolve_llm_config()
                if primary.get("provider") == provider
                else resolve_llm_config(provider)
            )
            ok, detail = probe_llm(runtime_config=cfg)
            results.append(
                {
                    "provider": provider,
                    "model": cfg.model,
                    "configured": True,
                    "connected": ok,
                    "detail": detail,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "provider": provider,
                    "configured": True,
                    "connected": False,
                    "detail": type(exc).__name__,
                }
            )
    return {"providers": results}


@router.post("/circuit-breakers/reset")
def reset_llm_breakers(user: CurrentUser = Depends(require_user)):
    require_admin(user)
    reset_circuit_breakers()
    record_event(
        username=user.username,
        role=user.role,
        action="LLM_BREAKER_RESET",
        detail="all",
    )
    return {"success": True}


@router.post("/metrics/reset")
def reset_llm_runtime_metrics(user: CurrentUser = Depends(require_user)):
    require_admin(user)
    reset_llm_metrics()
    record_event(
        username=user.username,
        role=user.role,
        action="LLM_METRICS_RESET",
        detail="all",
    )
    return {"success": True}

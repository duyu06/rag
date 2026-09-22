from __future__ import annotations

from fastapi import APIRouter, Depends

from app.audit import verify_audit_chain
from app.auth import CurrentUser, require_admin, require_user
from app.config import settings
from app.conversation_store import conversation_store
from app.llm_router import router_registry_snapshot
from app.rate_limit import rate_limit_ready
from app.security import cors_origins, trusted_hosts, validate_production_security
from app.store import vector_store

router = APIRouter(prefix="/api/admin/enterprise", tags=["enterprise-readiness"])


@router.get("/readiness")
def enterprise_readiness(user: CurrentUser = Depends(require_user)):
    require_admin(user)

    qdrant_ok = vector_store.ping()
    redis_ok, redis_detail = rate_limit_ready()
    conversation_ok = bool(conversation_store.ping())
    audit = verify_audit_chain()
    router_state = router_registry_snapshot()

    production_config_ok = True
    production_config_error: str | None = None
    try:
        validate_production_security()
    except RuntimeError as exc:
        production_config_ok = False
        production_config_error = str(exc)

    checks = {
        "qdrant": qdrant_ok,
        "rate_limit_backend": redis_ok,
        "conversation_store": conversation_ok,
        "audit_integrity": bool(audit.get("valid")),
        "production_security_config": production_config_ok,
        "model_router_configured": bool(router_state.get("primary", {}).get("provider")),
    }
    ready = all(checks.values())

    return {
        "ready": ready,
        "environment": str(settings.app_env),
        "auth_mode": str(settings.auth_mode),
        "conversation_store_backend": str(settings.conversation_store_backend),
        "checks": checks,
        "rate_limit_detail": redis_detail,
        "audit": audit,
        "model_router": router_state,
        "perimeter": {
            "cors_origin_count": len(cors_origins()),
            "trusted_host_count": len(trusted_hosts()),
            "security_headers_enabled": bool(settings.security_headers_enabled),
        },
        "production_config_error": production_config_error,
    }

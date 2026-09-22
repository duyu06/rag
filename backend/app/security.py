from __future__ import annotations

from uuid import uuid4

from fastapi import Request
from pydantic import SecretStr

from app.config import settings


def _secret(value: SecretStr | str | None) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value().strip()
    return str(value or "").strip()


def csv_values(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def cors_origins() -> list[str]:
    return csv_values(settings.cors_allowed_origins)


def trusted_hosts() -> list[str]:
    return csv_values(settings.trusted_hosts)


def validate_production_security() -> None:
    """Fail startup when production perimeter/auth controls are unsafe."""
    if str(settings.app_env or "development").lower() != "production":
        return

    errors: list[str] = []
    origins = cors_origins()
    hosts = trusted_hosts()

    if str(settings.auth_mode or "").lower() != "oidc":
        errors.append("AUTH_MODE must be oidc in production")
    if "*" in origins or not origins:
        errors.append("CORS_ALLOWED_ORIGINS must be an explicit allowlist")
    if "*" in hosts or not hosts:
        errors.append("TRUSTED_HOSTS must be an explicit allowlist")
    if not str(settings.oidc_issuer or "").strip():
        errors.append("OIDC_ISSUER is required")
    if not str(settings.oidc_audience or "").strip():
        errors.append("OIDC_AUDIENCE is required")
    if not str(settings.oidc_jwks_url or "").strip():
        errors.append("OIDC_JWKS_URL is required")
    if not _secret(settings.audit_hmac_key):
        errors.append("AUDIT_HMAC_KEY is required")
    if settings.jwt_secret == "change-me-before-production-yaoke-demo-secret":
        errors.append("JWT_SECRET must not use the demo default")

    if not settings.rate_limit_enabled:
        errors.append("RATE_LIMIT_ENABLED must be true")
    if settings.rate_limit_fail_open:
        errors.append("RATE_LIMIT_FAIL_OPEN must be false")
    if not str(settings.redis_url or "").strip():
        errors.append("REDIS_URL is required")

    if str(settings.conversation_store_backend or "").lower() != "postgres":
        errors.append("CONVERSATION_STORE_BACKEND must be postgres")
    if not _secret(settings.postgres_dsn):
        errors.append("POSTGRES_DSN is required")

    if errors:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))


async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    response.headers["X-Request-ID"] = request_id
    if settings.security_headers_enabled:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
    return response

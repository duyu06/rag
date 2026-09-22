from __future__ import annotations

import hashlib
import time
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse
from redis import Redis
from redis.exceptions import RedisError

from app.config import settings

_REDIS: Redis | None = None
_REDIS_URL = ""
_REDIS_LOCK = Lock()


def _client() -> Redis:
    global _REDIS, _REDIS_URL
    url = str(settings.redis_url or "").strip()
    if not url:
        raise RuntimeError("REDIS_URL is required when rate limiting is enabled")
    with _REDIS_LOCK:
        if _REDIS is None or _REDIS_URL != url:
            _REDIS = Redis.from_url(url, decode_responses=True, socket_timeout=1.5)
            _REDIS_URL = url
        return _REDIS


def _identity(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    if authorization:
        digest = hashlib.sha256(authorization.encode("utf-8")).hexdigest()[:24]
        return "auth:" + digest
    forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    host = forwarded or (request.client.host if request.client else "unknown")
    return "ip:" + hashlib.sha256(host.encode("utf-8")).hexdigest()[:24]


def _policy(request: Request) -> tuple[str, int] | None:
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/"):
        return None
    if path in {"/api/health", "/api/ready"}:
        return None
    if path == "/api/auth/login":
        return "login", int(settings.rate_limit_login_per_minute)
    return "api", int(settings.rate_limit_requests_per_minute)


def rate_limit_ready() -> tuple[bool, str]:
    if not settings.rate_limit_enabled:
        return True, "disabled"
    try:
        ok = bool(_client().ping())
        return ok, "redis=ok" if ok else "redis=not_ready"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def rate_limit_middleware(request: Request, call_next):
    if not settings.rate_limit_enabled:
        return await call_next(request)

    policy = _policy(request)
    if policy is None:
        return await call_next(request)

    bucket, limit = policy
    window = int(time.time() // 60)
    key = f"yaoke:ratelimit:{bucket}:{_identity(request)}:{window}"

    try:
        redis = _client()
        pipe = redis.pipeline()
        pipe.incr(key, 1)
        pipe.expire(key, 65)
        count, _ = pipe.execute()
        count = int(count)
    except (RedisError, RuntimeError):
        if settings.rate_limit_fail_open:
            return await call_next(request)
        return JSONResponse(
            status_code=503,
            content={"detail": "Rate limit service unavailable"},
            headers={"Retry-After": "5"},
        )

    remaining = max(0, limit - count)
    headers = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str((window + 1) * 60),
    }
    if count > limit:
        headers["Retry-After"] = "60"
        return JSONResponse(
            status_code=429,
            content={"detail": "请求过于频繁，请稍后重试"},
            headers=headers,
        )

    response = await call_next(request)
    for name, value in headers.items():
        response.headers[name] = value
    return response

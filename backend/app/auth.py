from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Annotated, Any, Literal

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient
from pydantic import BaseModel

from app.config import settings

Role = Literal["ADMIN", "SALES", "HR"]

# Demo-only users. Production validation forbids AUTH_MODE=demo.
USERS = {
    "admin": {
        "username": "admin",
        "display_name": "系统管理员",
        "role": "ADMIN",
        "password_hash": "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9",
    },
    "sales01": {
        "username": "sales01",
        "display_name": "销售演示账号",
        "role": "SALES",
        "password_hash": "6bc0a63cb29c92306020c0a6bbc358cc4628db277dc06e253535e126517ad637",
    },
    "hr01": {
        "username": "hr01",
        "display_name": "HR 演示账号",
        "role": "HR",
        "password_hash": "070a3b5e8d4bd5c46acccb91c9c54614c0cd649e78c4c4719e3a64270bae5ddf",
    },
}


class CurrentUser(BaseModel):
    username: str
    display_name: str
    role: Role


def _password_digest(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def authenticate(username: str, password: str) -> CurrentUser | None:
    if str(settings.auth_mode).lower() != "demo":
        return None
    record = USERS.get(username)
    if not record:
        return None
    if not hmac.compare_digest(record["password_hash"], _password_digest(password)):
        return None
    return CurrentUser(
        username=record["username"],
        display_name=record["display_name"],
        role=record["role"],
    )


def issue_token(user: CurrentUser) -> str:
    if str(settings.auth_mode).lower() != "demo":
        raise RuntimeError("Local JWT issuance is disabled outside demo auth mode")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.username,
        "name": user.display_name,
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_expire_hours)).timestamp()),
        "iss": "yaoke",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _decode_demo_token(token: str) -> CurrentUser:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer="yaoke",
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="无效登录凭证") from exc

    username = str(payload.get("sub", ""))
    record = USERS.get(username)
    if not record:
        raise HTTPException(status_code=401, detail="账号不存在")
    return CurrentUser(
        username=record["username"],
        display_name=record["display_name"],
        role=record["role"],
    )


_JWKS_LOCK = Lock()
_JWKS_CLIENT: PyJWKClient | None = None
_JWKS_CLIENT_URL = ""


def _jwks_client() -> PyJWKClient:
    global _JWKS_CLIENT, _JWKS_CLIENT_URL
    url = str(settings.oidc_jwks_url or "").strip()
    if not url:
        raise HTTPException(status_code=503, detail="OIDC JWKS 未配置")
    with _JWKS_LOCK:
        if _JWKS_CLIENT is None or _JWKS_CLIENT_URL != url:
            _JWKS_CLIENT = PyJWKClient(url, cache_jwk_set=True, lifespan=300)
            _JWKS_CLIENT_URL = url
        return _JWKS_CLIENT


def _oidc_role(payload: dict[str, Any]) -> Role:
    raw = payload.get(str(settings.oidc_role_claim))
    values: list[str]
    if isinstance(raw, list):
        values = [str(item) for item in raw]
    elif isinstance(raw, str):
        values = [raw]
    else:
        values = []

    try:
        role_map_raw = json.loads(str(settings.oidc_role_map_json or "{}"))
        role_map = (
            {str(key): str(value).upper() for key, value in role_map_raw.items()}
            if isinstance(role_map_raw, dict)
            else {}
        )
    except json.JSONDecodeError:
        role_map = {}

    mapped: list[str] = []
    for value in values:
        candidate = role_map.get(value, value.upper())
        if candidate in {"ADMIN", "SALES", "HR"}:
            mapped.append(candidate)

    # Deterministic least-surprise precedence for users with multiple IdP roles.
    for candidate in ("ADMIN", "HR", "SALES"):
        if candidate in mapped:
            return candidate  # type: ignore[return-value]
    raise HTTPException(status_code=403, detail="账号没有可映射的系统角色")


def _decode_oidc_token(token: str) -> CurrentUser:
    issuer = str(settings.oidc_issuer or "").strip()
    audience = str(settings.oidc_audience or "").strip()
    if not issuer or not audience:
        raise HTTPException(status_code=503, detail="OIDC issuer/audience 未配置")
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            issuer=issuer,
            audience=audience,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="无效 OIDC 登录凭证") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="OIDC 验证服务暂不可用") from exc

    username_claim = str(settings.oidc_username_claim or "preferred_username")
    display_claim = str(settings.oidc_display_name_claim or "name")
    username = str(payload.get(username_claim) or payload.get("sub") or "").strip()
    if not username:
        raise HTTPException(status_code=401, detail="OIDC Token 缺少用户标识")
    return CurrentUser(
        username=username,
        display_name=str(payload.get(display_claim) or username),
        role=_oidc_role(payload),
    )


def require_user(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    token = authorization[7:].strip()
    mode = str(settings.auth_mode or "demo").strip().lower()
    if mode == "demo":
        return _decode_demo_token(token)
    if mode == "oidc":
        return _decode_oidc_token(token)
    raise HTTPException(status_code=503, detail="AUTH_MODE 配置无效")


def require_admin(user: CurrentUser) -> None:
    if user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="仅管理员可执行该操作")

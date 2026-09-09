from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

import jwt
from fastapi import Header, HTTPException
from pydantic import BaseModel

from app.config import settings

Role = Literal["ADMIN", "SALES", "HR"]

# Demo-only users. Passwords are stored as SHA-256 digests so the source does not
# contain plaintext credentials. Replace this file with your SSO / IdP adapter in production.
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
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.username,
        "name": user.display_name,
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_expire_hours)).timestamp()),
        "iss": "nexuskb",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def require_user(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    token = authorization[7:].strip()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer="nexuskb",
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


def require_admin(user: CurrentUser) -> None:
    if user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="仅管理员可执行该操作")

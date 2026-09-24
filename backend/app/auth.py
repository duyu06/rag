from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Annotated, Callable, Literal

import jwt
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, Field, computed_field

from app.config import settings
from app.identity import resolve_for_user
from app.identity.base import FeishuGrant

Role = Literal["ADMIN", "SALES", "HR", "USER", "VIEWER"]
AccessRole = Literal["admin", "user", "viewer"]
Permission = Literal[
    "knowledge:read",
    "knowledge:query",
    "knowledge:manage",
    "conversation:read",
    "conversation:write",
    "agent:run",
    "trace:read",
    "trace:read:any",
    "retrieval:debug",
    "evaluation:run",
    "audit:read",
    "system:operate",
]

# Platform permissions and department/knowledge scopes are deliberately separate.
# SALES and HR remain accepted as legacy, department-scoped user roles.
ROLE_ACCESS_LEVEL: dict[str, AccessRole] = {
    "ADMIN": "admin",
    "SALES": "user",
    "HR": "user",
    "USER": "user",
    "VIEWER": "viewer",
}

VIEWER_PERMISSIONS: tuple[Permission, ...] = (
    "knowledge:read",
    "conversation:read",
    "trace:read",
)
USER_PERMISSIONS: tuple[Permission, ...] = (
    *VIEWER_PERMISSIONS,
    "knowledge:query",
    "conversation:write",
    "agent:run",
)
ADMIN_PERMISSIONS: tuple[Permission, ...] = (
    *USER_PERMISSIONS,
    "knowledge:manage",
    "trace:read:any",
    "retrieval:debug",
    "evaluation:run",
    "audit:read",
    "system:operate",
)
ACCESS_ROLE_PERMISSIONS: dict[AccessRole, tuple[Permission, ...]] = {
    "viewer": VIEWER_PERMISSIONS,
    "user": USER_PERMISSIONS,
    "admin": ADMIN_PERMISSIONS,
}

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
    "user": {
        "username": "user",
        "display_name": "普通用户演示账号",
        "role": "USER",
        "password_hash": "e606e38b0d8c19b24cf0ee3808183162ea7cd63ff7912dbb22b5e803286b4446",
    },
    "viewer": {
        "username": "viewer",
        "display_name": "只读访客演示账号",
        "role": "VIEWER",
        # 演示注释：在此加一行 "feishu_open_id": "ou_xxx" 即接入飞书匹配（需 feishu_permissions_enabled=true）。
        "password_hash": "65375049b9e4d7cad6c9ba286fdeb9394b28135a3e84136404cfccfdcc438894",
    },
}


class CurrentUser(BaseModel):
    username: str
    display_name: str
    role: Role
    # 飞书桥接授予：None = 本地语义（开关关闭或该账号未接 feishu_open_id）。
    # 空授予（access_role=None）同样是本地语义，见 identity.resolver 的零命中口径。
    #
    # `exclude=True`：授予是**服务端内部**判定结果，不进任何响应体（/login、/me 都走
    # model_dump）。选它而不是"响应当场重建"的理由有两条：
    # 1) 前端不读 grant（`access_role` / `permissions` 已够用，两者本就是授予的投影），
    #    少一个键等于少一处能被反推外部身份结构的信息；
    # 2) 一处声明覆盖所有出口，新增端点不会忘记脱敏。
    # 注意 exclude 只影响**序列化**：`user.grant` 属性照旧可读，
    # access_role / permissions 两个计算字段与 knowledge.allowed_for 的授予判定都不受影响。
    grant: FeishuGrant | None = Field(default=None, exclude=True)

    @computed_field
    @property
    def access_role(self) -> AccessRole | None:
        """Canonical platform role exposed to clients without breaking legacy role."""
        if self.grant is not None and self.grant.access_role:
            return self.grant.access_role
        return access_role_for(self.role)

    @computed_field
    @property
    def permissions(self) -> list[Permission]:
        # 未知 access_role（含 legacy 角色缺失映射）一律空权限，fail closed。
        return list(ACCESS_ROLE_PERMISSIONS.get(self.access_role, ()))


def access_role_for(role: str) -> AccessRole | None:
    return ROLE_ACCESS_LEVEL.get(str(role).upper())


def permissions_for_role(role: str) -> tuple[Permission, ...]:
    access_role = access_role_for(role)
    if access_role is None:
        return ()
    return ACCESS_ROLE_PERMISSIONS[access_role]


def has_permission(user: CurrentUser, permission: Permission) -> bool:
    # 走 user.permissions，使 has/enforce 两处都自动 grant 感知（含 DENIED 审计口径）。
    return permission in user.permissions


def enforce_permission(user: CurrentUser, permission: Permission) -> CurrentUser:
    if not has_permission(user, permission):
        # Authorization denials are security events. Logging must not be able to
        # turn a deterministic 403 into a storage failure.
        try:
            from app.audit import record_event

            record_event(
                username=user.username,
                role=user.role,
                action="AUTHORIZATION",
                status="DENIED",
                detail=f"missing_permission={permission}",
            )
        except Exception:
            pass
        raise HTTPException(status_code=403, detail=f"当前账号缺少权限：{permission}")
    return user


def _password_digest(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def authenticate(username: str, password: str) -> CurrentUser | None:
    record = USERS.get(username)
    if not record:
        return None
    if not hmac.compare_digest(record["password_hash"], _password_digest(password)):
        return None
    grant = resolve_for_user(record["username"], record["role"], record)
    return CurrentUser(
        username=record["username"],
        display_name=record["display_name"],
        role=record["role"],
        grant=grant,
    )


def issue_token(user: CurrentUser) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.username,
        "name": user.display_name,
        "role": user.role,
        # access_role 仅为兼容展示用（旧客户端会解 JWT 拿它做角标），鉴权不读该字段：
        # require_user 每请求按本地用户表重解析授予，token 里的 role/access_role 都不信。
        # 保留 claim 以免打断既有外部消费方；契约测试同时钉住"claim 还在"与"鉴权不读它"。
        "access_role": user.access_role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_expire_hours)).timestamp()),
        "iss": "yaoke",
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

    # 授予每请求重解析：token 只证明身份，角色/范围不信任 JWT 里的旧值。
    grant = resolve_for_user(record["username"], record["role"], record)
    return CurrentUser(
        username=record["username"],
        display_name=record["display_name"],
        role=record["role"],
        grant=grant,
    )


def require_permission(permission: Permission) -> Callable[..., CurrentUser]:
    """Build a FastAPI dependency for one declarative capability."""

    return require_permissions(permission)


def require_permissions(*permissions: Permission) -> Callable[..., CurrentUser]:
    """Build a dependency that requires every listed capability."""
    if not permissions:
        raise ValueError("至少需要声明一个权限")

    def dependency(user: CurrentUser = Depends(require_user)) -> CurrentUser:
        for permission in permissions:
            enforce_permission(user, permission)
        return user

    return dependency

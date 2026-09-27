from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Callable, Literal

import jwt
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, Field, computed_field

from app import credentials, directory, login_throttle, user_store
from app.audit import record_event as _record_event
from app.config import settings
from app.identity import resolve_for_user
from app.identity.base import FeishuGrant
from app.login_throttle import LoginThrottledError

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


def _password_change_required(username: str) -> bool:
    """门只读表：`must_change` 不是 claim 里的声明，是当前凭据状态（§8.4 末段）。"""
    record = user_store.get_record(username)
    return bool(record and record.must_change)


#: 新口令规则的两枚边界（§8.8）。上限与 `LoginRequest.password` 的 `max_length` 同值：
#: 一处事实抄两遍就会漂，漂了的症状是"登录进得来的口令改不进去"。
_MIN_PASSWORD_LENGTH = 12
_MAX_PASSWORD_LENGTH = 128

COPY_PASSWORD_LENGTH = "新口令长度需在 12 到 128 个字符之间"
COPY_PASSWORD_SAME_AS_USERNAME = "新口令不得与账号名相同"


def validate_new_password(username: str, new_password: str) -> str | None:
    """新口令的两条规则：长度带 + 不得回声账号名。返回中文理由，`None` = 通过。

    这里**没有**弱口令词典——SEC-A 把它移出了范围。理由不是"词典难写"：同一个"太弱"在
    登录腿与改密腿会给出两句不同的话，而 §9.1 要展示面可枚举、可翻译。长度下界挡的是零成本
    爆破（Argon2 已经把在线慢验兜住），词典挡的是字典攻击却顺带挡掉合法口令，两者代价不同，
    不该由同一个函数一起判。

    返回值是**给用户看的那一句**（§9.1 展示面），机器可读性由调用方的状态码 422 承担；
    函数不抛异常，因为它同时被 CLI 用在那里——CLI 要把这句话原样打到 stderr 上。
    """
    if not _MIN_PASSWORD_LENGTH <= len(str(new_password)) <= _MAX_PASSWORD_LENGTH:
        return COPY_PASSWORD_LENGTH
    if str(new_password).casefold() == str(username).casefold():
        return COPY_PASSWORD_SAME_AS_USERNAME
    return None


def provision_credentials(username: str, *, plain_password: str, must_change: bool) -> int:
    """唯一一条"把一个新口令落成可用凭据"的路径（自助改密 / 管理员重置 / CLI 共用）。

    只产 argon2id：这里没有任何参数能让它产出别的算法（SEC-A-001），legacy 行也只有迁移器
    写得出来（SEC-A-004）。两个分支的差别只在"表里有没有行"，写路径本身是同一条事务，
    所以 bump 版本 + 清锁 + 置门这些副作用**不可能**只发生在其中一支。
    `must_change` 由调用方给（改密传 False、重置传 True），这是两条腿共用一条写路径、
    却不共用意图的唯一写法。返回落库后的 `credentials_version`：调用方要打印或签发的
    正是"这一刻的凭据纪元"。
    """
    if user_store.get_record(username) is None:
        return user_store.create_argon2(
            username, plain_password=plain_password, must_change=must_change
        )
    return user_store.set_password_argon2(
        username, plain_password=plain_password, must_change=must_change
    )


# ---------------------------------------------------------------------------
# 登录腿（规格 §7.1 的顺序即契约）
#
# 身份读 `directory`、凭据状态读 `user_store`、口令运算只在 `credentials`——三处各自有
# 唯一真源（SEC-A-010），这一层只是把它们按 §7.1 串起来，不在这里存任何用户材料。
# ---------------------------------------------------------------------------

#: 登录面 `detail` 的**全部**合法取值（§9.1 末段：自由文本不得进入该字段）。
#: 成功面是空串——`main.py` 只在非空时叫 `record_login_event`，成功事件继续走既有
#: `_audit(user, "LOGIN")`，那是 SEC-A-006 不许动的既有面。
#: 最后两枚是**可用性**事实（节流命中 / 容量溢出），不是凭据结论；它们之所以仍从这同一个
#: 出口走，是因为审计值域只该有一处真源——多开一个"可用性专用" writer 就等于允许自由文本。
AUDIT_INVALID_CREDENTIALS = "invalid_credentials"
AUDIT_LOGIN_LOCKED = "AUTH_LOGIN_LOCKED"
AUDIT_REHASH_DEGRADED = "AUTH_REHASH_DEGRADED"
AUDIT_LOGIN_THROTTLED = "login_throttled"
AUDIT_PASSWORD_CAPACITY = "password_capacity"

#: §9.1 展示面里 429 / 503 那两行的中文文案。与 `用户名或密码错误` 同一条纪律：**不提账号**
#: ——两格都是在身份查找之前判出来的，文案一旦说"该账号被限制"，可用性的事实就变成了
#: 存在性的证据。住在这一层（而不是 `main.py` 的字面量里）是因为它就是登录腿契约的一部分，
#: 契约测试与 HTTP 面读的是同一枚常量。
COPY_LOGIN_THROTTLED = "登录尝试过于频繁，请稍后再试"
COPY_PASSWORD_CAPACITY = "服务繁忙，请稍后重试"

#: 策略拒绝（422）的审计 token（§9.1 表）。改密 / 管理员重置 / CLI 三条腿共用这一枚常量，
#: 而不是各抄一遍字符串——抄三处就有第四处会漏。它是 `PASSWORD` 动作下的 DENIED 事件，
#: 与登录枚举 `LOGIN_AUDIT_DETAILS` 不是一族（后者由 `record_login_event` 单独把关）。
AUDIT_PASSWORD_POLICY_REJECTED = "password_policy_rejected"

#: 上面五枚的**值域容器**：`record_login_event` 用它自己判成员，而不是靠调用方各抄一遍
#: 字符串——抄一次就多一处会漏的复制品，而这条枚举的存在意义正是"审计字段里只有这几枚"。
LOGIN_AUDIT_DETAILS: tuple[str, ...] = (
    AUDIT_INVALID_CREDENTIALS,
    AUDIT_LOGIN_LOCKED,
    AUDIT_REHASH_DEGRADED,
    AUDIT_LOGIN_THROTTLED,
    AUDIT_PASSWORD_CAPACITY,
)


@dataclass(frozen=True)
class LoginResult:
    """登录腿的完整结论。HTTP 面（`main.py`）与契约测试读的是同一份，不分两条腿。"""

    user: CurrentUser | None
    audit_detail: str
    password_change_required: bool


def record_login_event(*, username: str, detail: str, action: str = "LOGIN") -> None:
    """登录/认证面的唯一审计出口。`detail` 必须落在 `LOGIN_AUDIT_DETAILS` 里。

    空串是**成功面**的取值，而成功事件属于既有 `_audit(user, "LOGIN")` 那一条腿：空值根本
    不该走到这里，否则落下的是一条 status=DENIED、detail 空白的伪拒绝事件（它既不是拒绝，
    也没说出任何事）。值域外的文本直接抛，不"洗成"某个枚举值——把自由文本降级成合法 token
    等于把这条门想钉的东西擦掉。

    `action` 默认 `LOGIN`（登录腿的事实）。但同一道可用性闸也守在改密/管理员重置两条**口令
    操作腿**上（它们带旧口令校验、共用这唯一的 detail 值域）。那两条腿上的 429/503 若仍记成
    `LOGIN`，审计里"一次被容量挡下的重置"就和"一次失败的登录"混成一件事——所以调用方把本腿
    的动作名传进来（`PASSWORD`）。detail 值域**一字不动**（§9.1 冻结的是取值集合，不是动作轴），
    只是让可用性拒绝带上它真正发生的那张脸。
    """
    if not detail:
        return
    if detail not in LOGIN_AUDIT_DETAILS:
        raise ValueError("登录审计 detail 不在枚举值域内")
    _record_event(
        username=username or "unknown",
        role="UNKNOWN",
        action=action,
        status="SUCCESS" if detail == AUDIT_REHASH_DEGRADED else "DENIED",
        detail=detail,
    )


def _user_from(identity: directory.UserIdentity, grant: FeishuGrant | None) -> CurrentUser:
    """`CurrentUser` 的唯一构造点。登录腿与令牌腿共用，避免两处的 grant 语义劈叉。"""
    return CurrentUser(
        username=identity.username,
        display_name=identity.display_name,
        role=identity.role,
        grant=grant,
    )


def authenticate_with_result(
    username: str, password: str, *, client_ip: str = ""
) -> LoginResult:
    # §7.1 步骤 0：闸门在任何身份查找、任何口令运算**之前**。它判的是"这次请求配不配消耗
    # 一次内存硬运算"，答案只来自 (归一化账号, 来源地址) 这一对客户端自己给出的事实，因此
    # 命中即抛也不构成存在性证据。键里两枚都算：去掉 client_ip ⇒ 换 IP 绕过第一层；
    # 把 client_ip 也塞进账号锁定键 ⇒ 分布式猜测一人一份计数，第二层永不触发。
    # `client_ip` 默认空串是给 CLI 与既有调用方的（它们没有 HTTP 请求可问）；那一格与
    # `main.py` 传来的真实地址落在**不同**的桶里，两条腿互不清零。
    # 单例只在**这一处**读（`login_throttle.pre_hash_throttle`）：按值绑进本模块的名字会成
    # 第二份读数，将来任何测试替身打在源头那一格上都会静默无效，而这条腿照样绿。
    bucket = login_throttle.throttle_bucket(username, client_ip)
    if not login_throttle.pre_hash_throttle.allow(bucket):
        raise LoginThrottledError(bucket)
    # 同一格的第二枚闸门：容量。它与节流同属步骤 0，先后不构成契约差异（节流命中即抛，那一格
    # 请求已经不该去问服务器还剩多少槽）。判在这里而不是判在 `credentials` 的运算处，理由是
    # §7.4——锁定那条腿本来就不付运算，若容量排在身份/锁定查找之后，饱和时"锁着的账号答 401、
    # 其余答 503"，那张对外统一的脸立刻长成一条存在性指纹。探针不预约，运算处 `argon2_slot`
    # 的抛错原样留着当兜底：竞态窗口里没占到的路径仍然只能以容量错误出去，不会退化成凭据结论。
    if not credentials.capacity_available():
        raise credentials.PasswordCapacityError("password operation capacity exceeded")
    identity = directory.get_identity(username)
    record = user_store.get_record(username)
    # 未知账号 / 已停用 / 有身份无凭据：三态共用一条恒定成本路径（§7.3）。停用账号在此
    # 归入"无可校验凭据"，既不是第四态，也不去看它那一行凭据——`enabled=false` 因此
    # 在响应面上完全不可见（名册那一面另有它自己的口径，两处读的都是同一个字段）。
    if identity is None or not identity.enabled or record is None:
        credentials.verify_dummy(password)
        return LoginResult(None, AUDIT_INVALID_CREDENTIALS, False)

    if login_throttle.is_locked(record.locked_until):
        # 不跑 Argon2：锁定路径显式排除在 timing 承诺之外（§7.4）。判定住在
        # `login_throttle.is_locked`——两层节流与锁定共读同一个谓词，这里不留第二份实现。
        return LoginResult(None, AUDIT_LOGIN_LOCKED, False)

    outcome = credentials.verify_password(
        password, algorithm=record.algorithm, encoded=record.password_hash
    )
    if not outcome.ok:
        # 第四态（口令错）在 algorithm 列上有两种形态，成本天然不等：argon2 行走真 verify，
        # legacy 行只走一次 `hmac.compare_digest`。不补一次同档运算，收敛窗口里就有两件事
        # 同时成立——猜错未升级账号的口令几乎免费，且响应时间本身指纹出"这个账号还没升级"，
        # 而那正是 §7.3 要关上的那张枚举面（账号级失败计数只滞后拦，拦不住时间差）。
        if record.algorithm == credentials.ALGORITHM_LEGACY_SHA256:
            credentials.verify_dummy(password)
        user_store.record_login_failure(
            username,
            max_attempts=settings.account_max_failed_attempts,
            lock_seconds=settings.account_lock_seconds,
        )
        return LoginResult(None, AUDIT_INVALID_CREDENTIALS, False)

    user_store.clear_login_failures(username)
    must_change = record.must_change
    detail = ""
    if outcome.needs_rehash:
        # legacy 出身 ⇒ 当场置 must_change（§8.3：只升级不置门会留出"已升级却自由读"的窗口）；
        # 参数漂移 ⇒ 保持原值，它不是弱口令。
        forced = record.algorithm == credentials.ALGORITHM_LEGACY_SHA256
        must_change = True if forced else must_change
        try:
            wrote = user_store.apply_rehash(
                username,
                plain_password=password,
                must_change=must_change,
                expected_version=record.credentials_version,
            )
        except Exception:
            # 这里的宽捕获**故意**涵盖 `PasswordCapacityError`：升级那一次哈希也过同一道闸，
            # 而这一刻人已经凭正确口令通过了判定。容量事实若从这里以 503 出去，就是把一次
            # 成功登录改写成一次服务不可用——写盘失败（锁 / 盘满）从来不该挡人，容量失败同理，
            # 二者在这里走同一条降级路：跳过本次升级、legacy 行留着等下一次登录、以 degraded
            # token 记下这条事实（SECA-21）。闸门本身不许变成第二道认证门。
            wrote = False
        if forced and not wrote:
            # 写盘失败 = 收敛延迟，不是安全放行：人已经进来了，legacy 行留着等下一次登录，
            # 但这条事实必须以 token 出现（SECA-21）。
            detail = AUDIT_REHASH_DEGRADED

    return LoginResult(
        _user_from(identity, resolve_for_user(identity.username, identity.role, identity)),
        detail,
        must_change,
    )


def authenticate(
    username: str, password: str, *, client_ip: str = ""
) -> CurrentUser | None:
    """既有契约：仍然只回答"这个口令能不能换到一个会话主体"。

    HTTP 面要的是 `LoginResult`（审计 token 与门状态），这里保留 `user | None` 是给
    CLI 与既有调用方——两条腿走的是同一个 `authenticate_with_result`，不存在第二套判定。
    `client_ip` 与上面同一条理由：不传就是 CLI 那一格，不与 HTTP 面的桶互相清零。
    """
    return authenticate_with_result(username, password, client_ip=client_ip).user


#: 令牌生命周期 claim 的名字（§7.5）。签发与鉴权两侧都从这里取值：字面量抄两遍就是
#: 留给"两侧拼写劈叉"的那条缝，而真劈了的症状是每次请求都 401「无效登录凭证」，
#: 排查方向会被带到口令上而不是 claim 名上。
CREDENTIAL_VERSION_CLAIM = "cv"


def issue_token(user: CurrentUser) -> str:
    now = datetime.now(timezone.utc)
    record = user_store.get_record(user.username)
    payload = {
        "sub": user.username,
        "name": user.display_name,
        "role": user.role,
        # access_role 仅为兼容展示用（旧客户端会解 JWT 拿它做角标），鉴权不读该字段：
        # require_user 每请求按身份声明文件重解析授予，token 里的 role/access_role 都不信。
        # 保留 claim 以免打断既有外部消费方；契约测试同时钉住"claim 还在"与"鉴权不读它"。
        "access_role": user.access_role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_expire_hours)).timestamp()),
        "iss": "yaoke",
        # 凭据纪元（§7.5）：这枚 token 属于哪一代凭据。鉴权判定的权威是表里那一行，claim
        # 只是"要比哪个版本"的提示——与上面 role/access_role 同一条不信任口径。
        # 无凭据行 ⇒ 0，不是"随手给个值"：0 与表内任何真实版本（首版恒 1）都不等，于是这枚
        # token 一签发即死，正是"有身份无凭据"那个主体应有的行为；同时 `CurrentUser` 的构造
        # 面不因身份类型分裂成第二条路径（两扇门迟早会在 grant 语义上劈叉）。
        CREDENTIAL_VERSION_CLAIM: int(record.credentials_version) if record else 0,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _user_from_token(authorization: str | None) -> CurrentUser:
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
    identity = directory.get_identity(username)
    record = user_store.get_record(username)
    if identity is None or not identity.enabled or record is None:
        # 「账号不存在」并入通用文案（§9.1）：原 `auth.py:230` 的单列 detail 是一条存在性指纹。
        # 三种状态（不认识主体 / 身份已停用 / 有身份无凭据行）在这里同形，与登录腿那四态合一
        # 是一个口径：撤销这件事不许长成"我能区分你属于哪一种"的一条新枚举面。
        raise HTTPException(status_code=401, detail="无效登录凭证")
    # 读表判定，不信 claim 的值：claim 只回答"要比哪个版本"，权威是 `user_store` 那一行。
    # 缺 claim **即视为不符**（SECA-09b）——"`cv` 为 None 就放行"不是向后兼容，是把 §7.5
    # 整条撤销通道让出去；代价如实记为"SEC-A 上线时旧会话强制重新登录一次"。
    # `bool` 单独挡掉：`True == 1`，版本号是整数，不许它经弱等值混成一次匹配。
    claimed = payload.get(CREDENTIAL_VERSION_CLAIM)
    if isinstance(claimed, bool) or not isinstance(claimed, int):
        raise HTTPException(status_code=401, detail="无效登录凭证")
    if claimed != record.credentials_version:
        # 改密 / 重置 / 停用会 bump 版本或删除凭据行 ⇒ 全部已发 token 即刻作废，不等 `exp`。
        raise HTTPException(status_code=401, detail="无效登录凭证")

    # 授予每请求重解析：token 只证明身份，角色/范围不信任 JWT 里的旧值。
    grant = resolve_for_user(identity.username, identity.role, identity)
    return _user_from(identity, grant)


def require_user(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    user = _user_from_token(authorization)
    if _password_change_required(user.username):
        # 展示面中文、审计面枚举 token，与 enforce_permission 既有的
        # AUTHORIZATION/DENIED/missing_permission=X 同构（规格 §9.1 两栏）。
        _record_event(
            username=user.username, role=user.role, action="AUTHORIZATION",
            status="DENIED", detail="password_change_required",
        )
        raise HTTPException(status_code=403, detail="当前账号需先修改口令")
    return user


def require_user_pending_password(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """`must_change=1` 期间仍可访问的两条腿的依赖：改密与 /me。"""
    return _user_from_token(authorization)


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

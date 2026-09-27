from __future__ import annotations

import json
import mimetypes
import statistics
import time
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.routing import get_route_path

from app.audit import recent_events, record_event, today_summary
from app.auth import (
    AUDIT_LOGIN_THROTTLED,
    AUDIT_PASSWORD_CAPACITY,
    AUDIT_PASSWORD_POLICY_REJECTED,
    COPY_LOGIN_THROTTLED,
    COPY_PASSWORD_CAPACITY,
    CurrentUser,
    _MAX_PASSWORD_LENGTH,
    _password_change_required,
    authenticate_with_result,
    has_permission,
    issue_token,
    provision_credentials,
    record_login_event,
    require_permission,
    require_user_pending_password,
    validate_new_password,
)
from app import security_startup, user_store
from app.config import settings
from app.credentials import PasswordCapacityError
from app.demo import demo_status, initialize_demo, reset_demo
from app.directory import get_identity as get_user_identity
from app.identity import warmup as warmup_identity_permissions
from app.ingestion import DOC_DIR, SUPPORTED_SUFFIXES, document_path
from app.knowledge import get_base, resolve_for, visible_for
from app.knowledge_os import (
    is_document_excluded,
    persist_eval_run,
    registry_entry,
    registry_remove,
    run_ingest_job,
)
from app.llm.health import probe_llm
from app.llm.usage import warmup as warmup_llm_router
from app.login_throttle import LoginThrottledError, client_ip_of
from app.rag import MODEL_USED_KEY, current_model_name, generate_answer
from app.retrieval import retrieval_service
from app.security import (
    public_exception_detail,
    public_typesafe_metrics,
    redact_secrets,
    redact_text,
)
from app.store import vector_store
from app.user_store import CredentialStoreError


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动门闸：坏配置让进程起不来，而不是第一个请求才炸。

    放在 lifespan 而不是模块顶层，是因为顶层 import 的副作用会波及所有导入方
    （测试、脚本、`python -c "import app.main"`）；lifespan 只在服务真正启动时跑一次。
    四步的**顺序**是契约的一部分（§8.5：先拒坏配置，再谈落盘）。守卫与两枚 warmup 的前置
    条件都在**函数内部**判，所以默认配置下那三格零额外行为；四步里只有第二道建表是无条件的，
    它只写 DDL、一行为都不写，理由写在下面那一格的注释里：
    - `security_startup.assert_startup_safe()`（§8.5 三守卫，本任务第一道）：
      `SECURITY_ENTERPRISE_MODE=false`（默认）时整体 no-op；打到 true 才把默认/过短的
      JWT secret 与缺失或含 * 的 CORS 白名单判成拒启动。异常穿出启动阶段 = fail-fast。
    - `user_store.ensure_user_credentials_schema()`（§8.5 增补段，来由见 §20.6）：见下面
      行内注释——它补的就是那两处注释一起交给「启动编排」、却从没人写下的那半句。
    - `warmup_identity_permissions()`：`FEISHU_PERMISSIONS_ENABLED=false` 直接 return。
    - `warmup_llm_router()`（Model Router V2.3 §8）：`LLM_ROUTER_ENABLED=false` 整链 no-op；
      开启时跑注册表 fail-fast + 建 `llm_request_logs` 表 + 接 usage sink（观测面自身
      fail-open，只有注册表错误才是启动事故）。
    异常不上抛成 500 而是穿出启动阶段——uvicorn 会因此退出（fail-fast）。
    `main_agent.py` 复用同一个 app 实例，门闸一并生效。
    """
    security_startup.assert_startup_safe()
    # 凭据表的**存在性**（§8.5 增补段 / §20.6 第七轮回写）。`user_store` 的读路径刻意不建表
    # （`app/user_store.py:105-113`：env 被清掉时默认落点会退回 `data/conversations.db`，
    # 让读路径顺手提交 DDL 等于往可能是生产库的那份文件里长出半张凭据表），于是"谁建表"被
    # 那处注释与 `credentials_migration.py:157-160` 一起交给「启动编排 / CLI」。CLI 那半条
    # 只有运维敲过才生效，启动编排这半句本轮之前根本没写。实测症状：全新安装（没跑过任何
    # CLI）打 `/api/auth/login` 抛 `no such table: user_credentials` ⇒ 裸 500，两形态同病，
    # 当场破掉 §8.5 企业列那句「`user_credentials` 无行 ⇒ 任何登录统一失败（fail-closed，
    # **非 500**）」。这一行就是那半句编排：`CREATE TABLE IF NOT EXISTS` ⇒ 幂等，CLI 已建过
    # 表照样通过；它**只**保证表在场，不写任何行——"全新安装不自动造凭据行"（§8.2 / M19）
    # 仍由 `ensure_user_credentials_schema()` 这个唯一建表者 + 运维显式的 `credentials
    # migrate` 守着。失败按上一道守卫的同一条形状穿出启动阶段（uvicorn 退出），而不是退化成
    # 每个请求各自撞一次 500；读路径也照旧不建表，两侧都要成立才有那张统一的脸。
    user_store.ensure_user_credentials_schema()
    warmup_identity_permissions()
    warmup_llm_router()
    yield


app = FastAPI(
    title="yaoke 企业 AI 知识中台 API",
    version="0.4.0",
    description="Enterprise RAG demo: RBAC + multi-KB + Hybrid Retrieval + Rerank + Citation + Audit",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    # CORS 白名单来自 config（§10）：默认 http://localhost:3000；企业形态下这一格缺失或含 *
    # 已由 lifespan 第一道的启动守卫拒启动，中间件这里只把逗号分隔白名单喂进去。
    allow_origins=[item.strip() for item in settings.cors_allow_origins.split(",") if item.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


#: 只有这两条腿的输入校验错误需要"脱敏回显"。FastAPI 默认的 `RequestValidationError`
#: 载荷把被拒取值原样放进 `detail[*].input`：漏填 `new_password` 那一格会把同请求里的
#: `current_password`（用户当下有效的那枚口令）整份抄进响应体，超长口令更会把自己抄进去。
#: §8.8 明写两端点"不回显任何口令"、SEC-A-002 禁止口令进任何响应面 ⇒ 这两条腿的校验错误
#: 一律换成一句不含 `input` 的中文。
#: 判据用**路径**而不是解析 body：`/api/auth/password/change` 全表唯一，`.../password/reset`
#: 后缀也唯一（`/api/demo/reset` 不以此结尾）。其余所有路径——含 V2.3 契约与 `/api/query`
#: 键集合钉所在的全部端点——原样交给 FastAPI 内置处理器 `request_validation_exception_handler`，
#: 那条就是默认注册的同一枚函数，输出逐字节不变。异常处理器只能是 app 级（Starlette 无路由级
#: 处理），故用路径分支把改动**关在这两条腿内**，不触碰任何既有端点的校验载荷。
def _is_no_echo_auth_path(path: str) -> bool:
    return path == "/api/auth/password/change" or path.endswith("/password/reset")


@app.exception_handler(RequestValidationError)
async def auth_validation_error_handler(
    request: Request, exc: RequestValidationError
):
    # 判据用**路由真正使用的那条路径**（get_route_path 会剥掉 root_path），不是
    # request.url.path：后者在 --root-path=/gw 部署下带着前缀（/gw/...），而 Starlette
    # 派发前已把前缀剥掉。用后者会让改密腿的校验错误漏过脱敏、回落 FastAPI 默认处理器，
    # 把用户刚提交的 current_password 抄进响应体（§8.8 / SEC-A-002）。
    if _is_no_echo_auth_path(get_route_path(request.scope)):
        return JSONResponse(status_code=422, content={"detail": "请求参数不合法"})
    return await request_validation_exception_handler(request, exc)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    # 上限引 `auth._MAX_PASSWORD_LENGTH` 而不是抄 128：登录面与改密面共用同一个字节天花板，
    # 抄两遍就会漂，漂了的症状是"登录进得来的口令改不进去"（`auth.py` 同一条理由）。
    password: str = Field(min_length=1, max_length=_MAX_PASSWORD_LENGTH)


class PasswordChangeRequest(BaseModel):
    # 两个字段的 `min_length` 都是 1，不是笔误：短口令的"不合格"必须由 `validate_new_password`
    # 用中文说（§9.1 展示面），而不是由 pydantic 用英文结构错误说；旧口令这一侧更要如此——
    # 一个 legacy 出身的账号旧口令本来就可以只有 8 位，先 422 就把 401 那条正确文案挡住了。
    # 这里**不设** `max_length`：长度上界唯一判在 `validate_new_password`（它给中文 422 且
    # 不回显输入）。一旦把 `max_length` 抄到字段上，超长口令会先撞 pydantic 的
    # `RequestValidationError`，而它的默认载荷把被拒的值原样写进 `detail[*].input`——等于
    # 把用户刚提交的那枚新口令抄进 HTTP 响应体，正面违反 §8.8「不回显任何口令」/ SEC-A-002。
    # 长度带因此只有一处真源（`auth._MAX_PASSWORD_LENGTH`），响应面回显面为 0。
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


class AdminPasswordResetRequest(BaseModel):
    # 同 `PasswordChangeRequest`：不设 `max_length`，超长由 `validate_new_password` 判，
    # 免得 pydantic 的输入回显把管理员给的新口令抄进响应体。
    new_password: str = Field(min_length=1)


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=5, ge=1, le=20)
    include_sources: bool = True
    use_hybrid_search: bool = True
    use_reranking: bool = False
    knowledge_base_id: str | None = None


class DebugRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    mode: Literal["vector", "bm25", "hybrid"] = "hybrid"
    top_k: int = Field(default=8, ge=1, le=30)
    rerank: bool = False
    knowledge_base_id: str | None = None


EvalMode = Literal["vector", "bm25", "hybrid", "hybrid_rerank"]


class EvaluationRequest(BaseModel):
    modes: list[EvalMode] = Field(
        default_factory=lambda: ["vector", "bm25", "hybrid", "hybrid_rerank"]
    )
    top_k: int = Field(default=3, ge=1, le=10)


def _audit(user: CurrentUser, action: str, **kwargs) -> None:
    record_event(username=user.username, role=user.role, action=action, **kwargs)


def _allowed_ids(user: CurrentUser, knowledge_base_id: str | None) -> list[str]:
    """范围判定交给 `knowledge.resolve_for`（授予为权威），这里只保留拒绝审计与 HTTP 映射。"""
    try:
        return resolve_for(user, knowledge_base_id)
    except PermissionError as exc:
        _audit(
            user,
            "ACCESS",
            status="DENIED",
            knowledge_base_id=knowledge_base_id,
            detail=redact_text(exc),
        )
        raise HTTPException(status_code=403, detail=redact_text(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=redact_text(exc)) from exc


def _dataset_knowledge_base_ids(dataset: list[dict]) -> list[str]:
    """评测数据集里出现过的 distinct 库 id（按文件里的出现顺序去重）。

    拆出来只为"每个库判一次"这件事可测：范围校验要覆盖数据集，但重复行不该重复判。
    """
    return list(dict.fromkeys(str(item["knowledge_base_id"]) for item in dataset))


def source_from_row(row: dict) -> dict:
    score = row.get("rerank_score")
    if score is None:
        score = row.get("hybrid_score", row.get("vector_score"))
    return {
        "file_name": row.get("file_name", "未知文档"),
        "page": row.get("page"),
        "content_preview": str(row.get("content", ""))[:320],
        "relevance_score": score,
        "knowledge_base_id": row.get("knowledge_base_id"),
        "knowledge_base_name": row.get("knowledge_base_name"),
    }


def safe_rows(
    question: str,
    k: int,
    hybrid: bool,
    rerank: bool,
    user: CurrentUser,
    knowledge_base_id: str | None,
) -> list[dict]:
    rows, _ = safe_rows_with_timings(
        question,
        k,
        hybrid,
        rerank,
        user,
        knowledge_base_id,
    )
    return rows


def safe_rows_with_timings(
    question: str,
    k: int,
    hybrid: bool,
    rerank: bool,
    user: CurrentUser,
    knowledge_base_id: str | None,
) -> tuple[list[dict], dict[str, Any]]:
    mode = "hybrid" if hybrid else "vector"
    kb_ids = _allowed_ids(user, knowledge_base_id)
    try:
        rows, timings = retrieval_service.search_with_timings(
            question,
            top_k=k,
            mode=mode,
            rerank=rerank,
            knowledge_base_ids=kb_ids,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"检索服务不可用：{public_exception_detail(exc)}") from exc
    return [row for row in rows if not is_document_excluded(row.get("knowledge_base_id"), row.get("file_name"))], timings


@app.get("/")
def root():
    return {
        "name": "yaoke Enterprise Knowledge Copilot",
        "version": "0.4.0",
        "docs": "/docs",
        "health": "/api/health",
        "ready": "/api/ready",
    }


@app.get("/api/ready")
def ready():
    qdrant_ok = vector_store.ping()
    if not qdrant_ok:
        raise HTTPException(status_code=503, detail="Qdrant not ready")
    return {"status": "ready", "vector_db_connected": True}


@app.get("/api/health")
def health():
    qdrant_ok = vector_store.ping()
    llm_ok, llm_detail = probe_llm()
    provider = "openai-compatible" if settings.openai_api_key else "ollama"
    return {
        "status": "healthy" if (qdrant_ok and llm_ok) else "degraded",
        "vector_db_connected": qdrant_ok,
        "llm_connected": llm_ok,
        "llm_detail": llm_detail,
        "ollama_connected": llm_ok if provider == "ollama" else False,
        "llm_provider": provider,
        "llm_model": current_model_name(),
    }


def _auth_availability_denial(username: str, exc: Exception, *, action: str = "LOGIN") -> HTTPException:
    """把两格**可用性**事实翻成 HTTPException：429（pre-hash 节流命中）/ 503（Argon2 槽溢出）。

    两格都不是凭据结论：判定发生在身份查找与昂贵运算的两侧，客户端材料一个都没被读过，
    所以响应面只说"现在不行"，绝不提账号存在与否——那才会把可用性事实变成存在性证据。
    审计走 `record_login_event` 那唯一的出口（token 已在 `LOGIN_AUDIT_DETAILS` 里），
    不在这里另开 writer。异常识别按类型、不按消息，且**只**认这两枚：别的异常一律原样上抛，
    免得多年以后有人往这条 try 里塞进一枚凭据异常而它被静默翻成 503。
    """
    if isinstance(exc, LoginThrottledError):
        record_login_event(username=username, detail=AUDIT_LOGIN_THROTTLED, action=action)
        return HTTPException(status_code=429, detail=COPY_LOGIN_THROTTLED)
    if isinstance(exc, PasswordCapacityError):
        record_login_event(username=username, detail=AUDIT_PASSWORD_CAPACITY, action=action)
        return HTTPException(status_code=503, detail=COPY_PASSWORD_CAPACITY)
    raise exc


@app.post("/api/auth/login")
def login(http_request: Request, request: LoginRequest):
    username = request.username.strip()
    # 来源地址只认 `request.client.host`（当前 compose 前面没有反代，`X-Forwarded-For`
    # 是客户端自述的字符串，信任它等于把节流键交给攻击者挑）。
    client_ip = client_ip_of(http_request)
    try:
        result = authenticate_with_result(username, request.password, client_ip=client_ip)
    except (LoginThrottledError, PasswordCapacityError) as exc:
        raise _auth_availability_denial(username, exc) from exc
    if result.user is None:
        # 四种失败态（未知账号 / 停用 / 有身份无凭据 / 口令错）到这里已经塌成同一条
        # 状态码 + 同一段中文文案；它们唯一的区别是审计 token，而那个只进审计面（§9.1）。
        record_login_event(username=username, detail=result.audit_detail)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if result.audit_detail:
        # 成功面上多出来的那一格只有 AUTH_REHASH_DEGRADED（重哈希没写进去，人已经进来了）。
        # 成功事件本身仍是下面那条既有 _audit，不在这里另起一笔。
        record_login_event(username=username, detail=result.audit_detail)
    user = result.user
    _audit(user, "LOGIN")
    return {
        "access_token": issue_token(user),
        "token_type": "bearer",
        "user": user.model_dump(),
        # §11 声明的本版唯一一处响应面键集合变化（additive）。值取自登录腿已经算好的那一格，
        # 不在这里再查一次表：同一条判定有两个读数点，早晚会在"登录刚置门"这类中间态上劈叉。
        "password_change_required": result.password_change_required,
    }


@app.get("/api/auth/me")
def me(user: CurrentUser = Depends(require_user_pending_password)):
    # 同一个布尔键在这里必须**读表**：`/me` 拿到的是任意时刻的既有 token，签发那一刻的门状态
    # 早就不是当前事实了（改密页与前端引导都靠这一格判断要不要留在改密流程里）。
    return {**user.model_dump(), "password_change_required": _password_change_required(user.username)}


@app.post("/api/auth/password/change")
def change_password(
    http_request: Request,
    request: PasswordChangeRequest,
    user: CurrentUser = Depends(require_user_pending_password),
):
    """自助改密：带着旧口令来，带着**新的一枚** token 走（§8.7 / §7.5）。

    顺序即契约：策略 422 → 旧口令 401 → 写库 → 签新 token。
    - 422 排在口令校验之前：`new_password` 太短或与账号名同形都不涉及任何凭据事实，
      而口令校验要付一次 Argon2。
    - 旧口令走 `authenticate_with_result`：它带旧口令校验，所以这一条腿与登录是**同一个**
      爆破面，共用同一份账号级失败/锁定状态（`failed_attempts` 与 `locked_until` 就在这一跳
      被写被读）。这里不自造第二把计数器——两把计数器等于给攻击者一条不被记录的通道。
    - 版本 bump 会废掉**包括来路那一枚在内**的全部已发 token（§7.5）。因此响应必须交出一枚
      新签的：否则走完强制改密流程的人会在下一跳被弹回登录页，而"改密腿在 must_change 期间
      可达"这件事就只剩一半。新 token 在写库**之后**签，`issue_token` 读到的才是新一代纪元。
    """
    reason = validate_new_password(user.username, request.new_password)
    if reason:
        # 策略拒绝是一枚安全事实，不是一句被丢弃的返回值：脚本化地批量提交不合格新口令若
        # 不留痕，§9.1 的 `password_policy_rejected` 审计面就是空的（422 只到展示面）。
        _audit(user, "PASSWORD", status="DENIED", detail=AUDIT_PASSWORD_POLICY_REJECTED)
        raise HTTPException(status_code=422, detail=reason)
    try:
        # 这一跳带旧口令校验，所以它与登录是**同一个**猜测面：同一个 (username, client_ip)
        # 桶、同一份账号级锁定，不自造第二把计数器。异常翻译与登录腿共用同一个 helper——
        # 两条腿各抄一遍 except 就是留给"其中一条忘了 503"的那条缝。
        result = authenticate_with_result(
            user.username, request.current_password, client_ip=client_ip_of(http_request)
        )
    except (LoginThrottledError, PasswordCapacityError) as exc:
        raise _auth_availability_denial(user.username, exc, action="PASSWORD") from exc
    if result.user is None:
        # 四种失败态（含锁定期）到这里已经塌成同一条 401 + 同一段中文，与登录面一字不差；
        # 区别只在审计 token，而那个只进审计面。
        # 事件归属由路由决定：改密腿上的**每一格**拒绝都记 PASSWORD（与上面 429/503 同属一条腿），
        # 只有 `/api/auth/login` 的拒绝才记 LOGIN。混着记的话，运维面就再也分不出"爆破改密接口"
        # 与"爆破登录接口"——判定与计数器共用，事件归属却严格按路由分。
        record_login_event(username=user.username, detail=result.audit_detail,
                           action="PASSWORD")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    try:
        provision_credentials(
            user.username, plain_password=request.new_password, must_change=False
        )
    except PasswordCapacityError as exc:
        # 写库那一次哈希也过同一道闸了（provisioning 不再在闸门外做同档运算），于是这条腿
        # 多出一格容量面。翻译仍取自那唯一一处 helper：文案与审计 token 都不许有第二份写法。
        raise _auth_availability_denial(user.username, exc, action="PASSWORD") from exc
    except CredentialStoreError as exc:
        # 存储事故（锁 / 盘满 / 约束）不是认证结论：翻成中文 500 + FAILED 审计，与既有
        # `文档处理失败` / `Demo 初始化失败` 两条腿同一形状；`public_exception_detail` 负责脱敏，
        # 异常消息与响应体都不带口令。CLI 腿对此映射 exit 1，两条写腿因此都不再漏裸栈。
        _audit(result.user, "PASSWORD", status="FAILED", detail=f"credential_write_failed:{public_exception_detail(exc)}")
        raise HTTPException(status_code=500, detail=f"凭据写入失败：{public_exception_detail(exc)}") from exc
    _audit(result.user, "PASSWORD", status="SUCCESS", detail="password_changed")
    return {
        "changed": True,
        "access_token": issue_token(result.user),
        "token_type": "bearer",
        # 读表而不是写死 False：这一格与 `require_user` 那道门用的是同一个谓词，两边读数一旦
        # 劈叉，症状就是"界面说改完了、下一跳还是 403"。
        "password_change_required": _password_change_required(result.user.username),
    }


@app.post("/api/admin/users/{username}/password/reset")
def admin_reset_password(
    username: str,
    request: AdminPasswordResetRequest,
    user: CurrentUser = Depends(require_permission("system:operate")),
):
    """管理员重置：设一个管理员知道的口令，并把门开给下一次登录（§8.6）。

    用的是**既有**能力 `system:operate`，不新增权限名——角色权限矩阵是冻结契约。
    `must_change=True` 是这条腿的语义本身：不置门等于把"这个账号从此用别人给的口令"留成静默。
    口令、hash、长度一概不上响应面；`must_change` 那一格读表，理由与上面同一条。

    未知身份给 404「账号不存在」不构成枚举面：能走到这一格的主体已经过 `system:operate` 鉴权，
    对外那张脸是登录腿的四态合一（§9.1）。

    这条腿**不**要求 `username != actor`（没有"不能给自己重置"的守卫）：持 `system:operate` 的
    主体在同一台主机上本就能经 CLI 达到逐字节相同的后果（重置任意账号并撤销其会话），HTTP 侧
    再切一道只会把同一能力变成两条不等价的路径、不缩小任何可达面。缓解落在**效果**这一维：
    自重置同样置 `must_change=1` 并 bump 凭据纪元，于是操作者自己签发的 token 也即刻作废——
    "谁被重置"这件事（含 actor 本人）由 `target` 与门状态如实记账，不靠拒绝某个用户名来伪装。
    """
    reason = validate_new_password(username, request.new_password)
    if reason:
        # 与自助改密腿同一枚 token、同一道理：重置腿的策略拒绝也得留痕，否则被拒的批量
        # 尝试在审计里追不到（§9.1）。展示面只有中文那句，值/长度/hash 一概不进事件。
        _audit(user, "PASSWORD", status="DENIED", detail=AUDIT_PASSWORD_POLICY_REJECTED)
        raise HTTPException(status_code=422, detail=reason)
    if get_user_identity(username) is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    try:
        provision_credentials(username, plain_password=request.new_password, must_change=True)
    except PasswordCapacityError as exc:
        # 重置腿此前**够不到**容量面（写入侧不占槽），槽一进到 `hash_password` 它就是第三格：
        # 已鉴权的主体也不该被裸栈顶成 500。文案与 token 同样取自那唯一一处翻译，审计记的是
        # 拿到拒绝的那位（actor）；`target` 那一格另有它自己的登记，不在这里分叉。
        raise _auth_availability_denial(user.username, exc, action="PASSWORD") from exc
    except CredentialStoreError as exc:
        # 与自助改密腿同一条错误处理：存储事故翻成中文 500 + FAILED 审计，绝不漏裸栈（CLI 腿 exit 1）。
        _audit(user, "PASSWORD", status="FAILED", detail=f"credential_write_failed:{public_exception_detail(exc)}", target=username)
        raise HTTPException(status_code=500, detail=f"凭据写入失败：{public_exception_detail(exc)}") from exc
    # `username=actor` 记的是"谁干的"，`target` 记的是"对谁干的"：CLI 重置那腿 username 直接是
    # 受体，两条腿光看 username 会在 audit.jsonl 里混成一件事（detail 枚举止损又被 spec :405
    # 冻死，不许各造 per-face token）。加 `target` 才让 HTTP 重置腿与 CLI 重置腿在审计里分得开。
    _audit(user, "PASSWORD", status="SUCCESS", detail="password_reset_by_admin", target=username)
    return {"reset": True, "must_change": _password_change_required(username)}


@app.get("/api/knowledge-bases")
def knowledge_bases(user: CurrentUser = Depends(require_permission("knowledge:read"))):
    return {"knowledge_bases": visible_for(user)}


@app.get("/api/stats")
def stats(
    knowledge_base_id: str | None = Query(default=None),
    user: CurrentUser = Depends(require_permission("knowledge:read")),
):
    kb_ids = _allowed_ids(user, knowledge_base_id)
    try:
        chunks = vector_store.all_chunks(knowledge_base_ids=kb_ids)
        store_stats = vector_store.stats(knowledge_base_ids=kb_ids)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"向量库不可用：{public_exception_detail(exc)}") from exc

    documents = {
        (str(row.get("knowledge_base_id")), str(row.get("file_name")))
        for row in chunks
        if row.get("file_name")
    }
    # Non-auditors receive only their own activity counters, never global usage.
    audit = today_summary() if has_permission(user, "audit:read") else today_summary(username=user.username)
    return {
        "total_documents": len(documents),
        "total_chunks": store_stats["total_chunks"],
        "knowledge_bases": len(kb_ids),
        "collection_name": store_stats["collection_name"],
        "embedding_model": store_stats["embedding_model"],
        "embedding_dimension": store_stats["embedding_dimension"],
        "llm_model": current_model_name(),
        **audit,
    }


@app.get("/api/audit")
def audit_log(
    limit: int = Query(default=50, ge=1, le=500),
    user: CurrentUser = Depends(require_permission("audit:read")),
):
    return {"events": recent_events(limit), "summary": today_summary()}


@app.post("/api/ingest")
async def ingest(
    file: UploadFile = File(...),
    knowledge_base_id: str = Form(...),
    user: CurrentUser = Depends(require_permission("knowledge:manage")),
):
    _allowed_ids(user, knowledge_base_id)
    try:
        base = get_base(knowledge_base_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=redact_text(exc)) from exc

    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    safe_name = Path(file.filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail="仅支持 PDF / DOCX / TXT / Markdown")

    content = await file.read()
    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"文件不能超过 {settings.max_file_size_mb}MB")

    path = document_path(knowledge_base_id, safe_name)
    path.write_bytes(content)
    try:
        chunk_count = run_ingest_job(user, path, knowledge_base_id, origin="upload")
    except Exception as exc:
        path.unlink(missing_ok=True)
        _audit(user, "INGEST", status="FAILED", knowledge_base_id=knowledge_base_id, detail=public_exception_detail(exc))
        raise HTTPException(status_code=500, detail=f"文档处理失败：{public_exception_detail(exc)}") from exc

    _audit(
        user,
        "INGEST",
        knowledge_base_id=knowledge_base_id,
        num_sources=chunk_count,
        detail=safe_name,
    )
    return {
        "success": True,
        "message": "文档已写入知识库",
        "file_name": safe_name,
        "knowledge_base_id": knowledge_base_id,
        "knowledge_base_name": base["name"],
        "chunks_stored": chunk_count,
    }


@app.get("/api/documents")
def documents(
    knowledge_base_id: str | None = Query(default=None),
    user: CurrentUser = Depends(require_permission("knowledge:read")),
):
    kb_ids = _allowed_ids(user, knowledge_base_id)
    try:
        rows = vector_store.all_chunks(knowledge_base_ids=kb_ids)
    except Exception:
        rows = []

    counts = Counter(
        (str(row.get("knowledge_base_id")), str(row.get("file_name")))
        for row in rows
        if row.get("knowledge_base_id") and row.get("file_name")
    )

    result = []
    for kb_id in kb_ids:
        base = get_base(kb_id)
        directory = DOC_DIR / kb_id
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True):
            if not path.is_file():
                continue
            stat = path.stat()
            uploaded_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
            chunk_total = counts.get((kb_id, path.name), 0)
            entry = registry_entry(kb_id, path.name, chunk_count=chunk_total)
            result.append(
                {
                    "file_name": path.name,
                    "file_type": path.suffix.lower().lstrip("."),
                    "file_size_kb": round(stat.st_size / 1024, 2),
                    "upload_date": uploaded_at,
                    "chunk_count": chunk_total,
                    "knowledge_base_id": kb_id,
                    "knowledge_base_name": base["name"],
                    "status": entry["status"],
                    "enabled": bool(entry.get("enabled", True)),
                    "archived": bool(entry.get("archived", False)),
                    "last_error": entry.get("last_error"),
                    "indexed_at": entry.get("updated_at") or uploaded_at,
                }
            )

    result.sort(key=lambda item: item["upload_date"], reverse=True)
    return {
        "documents": result,
        "total_documents": len(result),
        "total_chunks": sum(counts.values()),
    }


@app.get("/api/source/{knowledge_base_id}/{file_name}")
def source_document(
    knowledge_base_id: str,
    file_name: str,
    user: CurrentUser = Depends(require_permission("knowledge:read")),
):
    _allowed_ids(user, knowledge_base_id)
    safe_name = Path(file_name).name
    path = document_path(knowledge_base_id, safe_name)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="来源文件不存在")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    _audit(user, "SOURCE_VIEW", knowledge_base_id=knowledge_base_id, detail=safe_name)
    return FileResponse(path, media_type=media_type)


@app.delete("/api/documents/{file_name}")
def delete_document(
    file_name: str,
    knowledge_base_id: str = Query(...),
    user: CurrentUser = Depends(require_permission("knowledge:manage")),
):
    _allowed_ids(user, knowledge_base_id)
    try:
        get_base(knowledge_base_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=redact_text(exc)) from exc

    safe_name = Path(file_name).name
    try:
        vector_store.delete_file(safe_name, knowledge_base_id)
    except Exception as exc:
        _audit(user, "DELETE", status="FAILED", knowledge_base_id=knowledge_base_id, detail=public_exception_detail(exc))
        raise HTTPException(status_code=503, detail=f"删除向量失败：{public_exception_detail(exc)}") from exc

    document_path(knowledge_base_id, safe_name).unlink(missing_ok=True)
    registry_remove(knowledge_base_id, safe_name)
    _audit(user, "DELETE", knowledge_base_id=knowledge_base_id, detail=safe_name)
    return {"success": True, "message": "文档已删除"}


@app.get("/api/demo/status")
def get_demo_status(user: CurrentUser = Depends(require_permission("system:operate"))):
    try:
        return demo_status()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Demo 状态读取失败：{public_exception_detail(exc)}") from exc


@app.post("/api/demo/initialize")
def init_demo(user: CurrentUser = Depends(require_permission("system:operate"))):
    started = time.perf_counter()
    try:
        result = initialize_demo(force=False)
    except Exception as exc:
        _audit(user, "DEMO_INIT", status="FAILED", detail=public_exception_detail(exc))
        raise HTTPException(status_code=500, detail=f"Demo 初始化失败：{public_exception_detail(exc)}") from exc
    _audit(user, "DEMO_INIT", latency_ms=(time.perf_counter() - started) * 1000, detail=f"{result['status']['ready_count']}/{result['status']['total']}")
    return result


@app.post("/api/demo/reset")
def reset_demo_endpoint(user: CurrentUser = Depends(require_permission("system:operate"))):
    started = time.perf_counter()
    try:
        result = reset_demo()
    except Exception as exc:
        _audit(user, "DEMO_RESET", status="FAILED", detail=public_exception_detail(exc))
        raise HTTPException(status_code=500, detail=f"Demo 重置失败：{public_exception_detail(exc)}") from exc
    _audit(user, "DEMO_RESET", latency_ms=(time.perf_counter() - started) * 1000, detail=f"{result['status']['ready_count']}/{result['status']['total']}")
    return result


@app.post("/api/query")
def query(request: QueryRequest, user: CurrentUser = Depends(require_permission("knowledge:query"))):
    started = time.perf_counter()
    question = redact_text(request.question)
    rows, retrieval_timings = safe_rows_with_timings(
        question,
        request.k,
        request.use_hybrid_search,
        request.use_reranking,
        user,
        request.knowledge_base_id,
    )
    # 终审 I-11-2（DESIGN §9「响应 model 字段来自实际选中模型」）：`model_used` 优先报
    # **这次真答出那句话的模型**（router 腿的执行面生效名，与账本 `model` 列同源）；
    # 盒子为空 ⇒ 零候选 / 全链失败 / legacy 路，那三种情况**没有**「实际答话的模型」这枚
    # 事实，于是回退计划面读数 `current_model_name()`。键名与键集合一字不改。
    model_out: dict[str, str] = {}
    answer = redact_text(generate_answer(question, rows, model_out=model_out))
    sources = [source_from_row(row) for row in rows] if request.include_sources else []
    _audit(
        user,
        "QUERY",
        knowledge_base_id=request.knowledge_base_id or "all",
        query=question,
        latency_ms=(time.perf_counter() - started) * 1000,
        num_sources=len(sources),
    )
    response = {
        "answer": answer,
        "query": question,
        "sources": sources,
        "num_sources": len(sources),
        "model_used": model_out.get(MODEL_USED_KEY) or current_model_name(),
    }
    typesafe_timings = public_typesafe_metrics(retrieval_timings)
    if typesafe_timings:
        response["timings"] = typesafe_timings
    return redact_secrets(response)


@app.post("/api/query/stream")
def query_stream(
    request: QueryRequest,
    user: CurrentUser = Depends(require_permission("knowledge:query")),
):
    started = time.perf_counter()
    question = redact_text(request.question)
    rows, retrieval_timings = safe_rows_with_timings(
        question,
        request.k,
        request.use_hybrid_search,
        request.use_reranking,
        user,
        request.knowledge_base_id,
    )
    sources = [source_from_row(row) for row in rows] if request.include_sources else []

    def event_stream():
        try:
            yield "event: sources\ndata: " + json.dumps(redact_secrets({"sources": sources}), ensure_ascii=False) + "\n\n"
            # 同 I-11-2：流式腿带同一个盒子（与上面 `/api/query` 那处同一个调用形状）。
            # SSE 的 `done` 事件今天**没有** `model_used` 键，这里按「有没有执行面事实」
            # 决定挂不挂——与既有的 `timings` 同一道姿势；缺键即「本次没有实际答话的模型
            # 可报」，不写空串、也不拿计划面名字冒充。
            model_out: dict[str, str] = {}
            answer = redact_text(generate_answer(question, rows, model_out=model_out))
            for start in range(0, len(answer), 14):
                payload = json.dumps({"text": answer[start : start + 14]}, ensure_ascii=False)
                yield f"event: token\ndata: {payload}\n\n"
            done_payload: dict[str, Any] = {"finish_reason": "stop"}
            answered_by = model_out.get(MODEL_USED_KEY)
            if answered_by:
                done_payload[MODEL_USED_KEY] = answered_by
            typesafe_timings = public_typesafe_metrics(retrieval_timings)
            if typesafe_timings:
                done_payload["timings"] = typesafe_timings
            yield "event: done\ndata: " + json.dumps(done_payload, ensure_ascii=False) + "\n\n"
        finally:
            _audit(
                user,
                "QUERY",
                knowledge_base_id=request.knowledge_base_id or "all",
                query=question,
                latency_ms=(time.perf_counter() - started) * 1000,
                num_sources=len(sources),
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/retrieval/debug")
def retrieval_debug(
    request: DebugRequest,
    user: CurrentUser = Depends(require_permission("retrieval:debug")),
):
    kb_ids = _allowed_ids(user, request.knowledge_base_id)
    query = redact_text(request.query)
    started = time.perf_counter()
    try:
        rows, retrieval_timings = retrieval_service.search_with_timings(
            query,
            top_k=request.top_k,
            mode=request.mode,
            rerank=request.rerank,
            knowledge_base_ids=kb_ids,
        )
    except Exception as exc:
        _audit(user, "RETRIEVAL_DEBUG", status="FAILED", query=query, detail=public_exception_detail(exc))
        raise HTTPException(status_code=503, detail=f"检索服务不可用：{public_exception_detail(exc)}") from exc

    _audit(
        user,
        "RETRIEVAL_DEBUG",
        knowledge_base_id=request.knowledge_base_id or "all",
        query=query,
        latency_ms=(time.perf_counter() - started) * 1000,
        num_sources=len(rows),
        detail=f"mode={request.mode},rerank={request.rerank}",
    )
    response = {
        "query": query,
        "mode": request.mode,
        "rerank": request.rerank,
        "knowledge_base_ids": kb_ids,
        "results": [
            {
                "file_name": row.get("file_name"),
                "page": row.get("page"),
                "content": str(row.get("content", ""))[:600],
                "knowledge_base_id": row.get("knowledge_base_id"),
                "knowledge_base_name": row.get("knowledge_base_name"),
                "vector_score": row.get("vector_score"),
                "bm25_score": row.get("bm25_score"),
                "hybrid_score": row.get("hybrid_score"),
                "rerank_score": row.get("rerank_score"),
            }
            for row in rows
        ],
    }
    typesafe_timings = public_typesafe_metrics(retrieval_timings)
    if typesafe_timings:
        response["typesafe"] = typesafe_timings
    return redact_secrets(response)


@app.post("/api/evaluation/run")
def run_evaluation(
    request: EvaluationRequest,
    user: CurrentUser = Depends(require_permission("evaluation:run")),
):
    dataset_path = Path(__file__).resolve().parent.parent / "eval_dataset.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    # 取数入口一律过用户范围：这里的 `knowledge_base_id` 来自数据集而不是请求参数，
    # 但它同样会把库内容读进响应（`cases[].top_files` 等），所以先对数据集里出现过的每个
    # distinct 库调一次 `_allowed_ids(user, kb_id)`——权限错误自然抛 403 + 一行 ACCESS/DENIED
    # 审计，未知库 404。全部通过才开始跑，不存在"跑出半份报告再失败"。
    for kb_id in _dataset_knowledge_base_ids(dataset):
        _allowed_ids(user, kb_id)
    overall_started = time.perf_counter()

    report: dict[str, dict] = {}
    for eval_mode in request.modes:
        retrieval_mode: Literal["vector", "bm25", "hybrid"] = (
            "hybrid" if eval_mode == "hybrid_rerank" else eval_mode
        )
        use_rerank = eval_mode == "hybrid_rerank"
        started = time.perf_counter()
        hits_at_1 = 0
        hits_at_k = 0
        reciprocal_rank = 0.0
        cases = []
        typesafe_case_metrics: list[dict[str, Any]] = []

        for item in dataset:
            rows, retrieval_timings = retrieval_service.search_with_timings(
                item["question"],
                top_k=request.top_k,
                mode=retrieval_mode,
                rerank=use_rerank,
                knowledge_base_ids=[item["knowledge_base_id"]],
            )
            safe_typesafe_metrics = public_typesafe_metrics(retrieval_timings)
            if safe_typesafe_metrics:
                typesafe_case_metrics.append(safe_typesafe_metrics)
            names = [str(row.get("file_name", "")) for row in rows]
            expected = item["expected_file"]
            rank = next((index + 1 for index, name in enumerate(names) if name == expected), None)
            if rank == 1:
                hits_at_1 += 1
            if rank is not None and rank <= request.top_k:
                hits_at_k += 1
                reciprocal_rank += 1 / rank
            cases.append(
                {
                    "question": item["question"],
                    "knowledge_base_id": item["knowledge_base_id"],
                    "expected_file": expected,
                    "rank": rank,
                    "top_files": names,
                }
            )

        total = max(len(dataset), 1)
        mode_report: dict[str, Any] = {
            "total": len(dataset),
            "hit_at_1": round(hits_at_1 / total, 4),
            f"hit_at_{request.top_k}": round(hits_at_k / total, 4),
            "mrr": round(reciprocal_rank / total, 4),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "rerank": use_rerank,
            "cases": cases,
        }
        if typesafe_case_metrics:
            p50_values = [
                float(item.get("typesafe_latency_p50_ms") or 0.0)
                for item in typesafe_case_metrics
            ]
            p95_values = [
                float(item.get("typesafe_latency_p95_ms") or 0.0)
                for item in typesafe_case_metrics
            ]
            mode_report["typesafe"] = {
                # effective 口径：`typesafe_enabled=false` 恒等价 "off"（Task 2 移交）。
                # 上报原始 `typesafe_mode` 会让评测报告在判定层整体关闭时仍写着 "shadow"，
                # 与 `typesafe_mode` metrics 键的值（同样已改 effective）互相打脸。
                "mode": settings.effective_typesafe_mode,
                "model": settings.typesafe_model,
                "degraded_cases": sum(
                    1 for item in typesafe_case_metrics if item.get("typesafe_degraded")
                ),
                "request_count": sum(
                    int(item.get("typesafe_request_count") or 0)
                    for item in typesafe_case_metrics
                ),
                "input_tokens": sum(
                    int(item.get("typesafe_input_tokens") or 0)
                    for item in typesafe_case_metrics
                ),
                "output_tokens": sum(
                    int(item.get("typesafe_output_tokens") or 0)
                    for item in typesafe_case_metrics
                ),
                "estimated_cost_usd": round(
                    sum(
                        float(item.get("typesafe_estimated_cost_usd") or 0.0)
                        for item in typesafe_case_metrics
                    ),
                    8,
                ),
                "latency_p50_ms": round(statistics.median(p50_values), 2),
                "latency_p95_ms": round(max(p95_values), 2),
                "total_ms": round(
                    sum(
                        float(item.get("typesafe_total_ms") or 0.0)
                        for item in typesafe_case_metrics
                    ),
                    2,
                ),
                "unauthorized_candidates_blocked": sum(
                    int(item.get("typesafe_unauthorized_candidates_blocked") or 0)
                    for item in typesafe_case_metrics
                ),
            }
        report[eval_mode] = mode_report

    _audit(
        user,
        "EVALUATION",
        latency_ms=(time.perf_counter() - overall_started) * 1000,
        detail=",".join(request.modes),
    )
    stored_run = persist_eval_run(
        dataset_size=len(dataset),
        top_k=request.top_k,
        report=report,
    )
    return {
        "run_id": stored_run["run_id"],
        "dataset_size": len(dataset),
        "top_k": request.top_k,
        "modes": request.modes,
        "report": report,
    }

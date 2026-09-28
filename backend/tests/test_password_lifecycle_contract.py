"""令牌生命周期的契约（规格 §7.5 / §8.4 / §9.1 / §11，SECA-09 / SECA-09b / SECA-10）。

四件事，各自的形状：

1. **`cv` 说的是"这枚 token 属于哪一代凭据"**：`issue_token` 从表里读当前版本写进 payload，
   `_user_from_token` 再拿它去比对**表里的当前值**。claim 只回答"要比哪个版本"，判定权在
   `user_store`——与"鉴权不读 JWT 里的 role/access_role"同族：能签出这枚 token 的那把秘密
   同样能签出任何版本号，所以 claim 从来不是权威，只是提示。
2. **claim 缺失即不符（SECA-09b）**：签名有效但 payload 里没有 `cv`（SEC-A 之前签发的全部
   会话）一律 401，与普通过期同形。"`cv is None` 就放行"那种兼容分支不是兼容，是把 §7.5
   整条撤销通道让出去。代价如实记着：**上线那一刻所有旧会话强制重新登录一次**，
   这是安全升级里可解释的一次性事件，不粉饰成无感升级。
3. **改密 / 重置 / 停用即废全部已发 token，不等 `exp`**。停用是**成对动作**（§6.4：身份侧置
   `enabled=false` + 凭据侧删行或 bump）。两半这里各自也被钉住，且理由不是"多做一遍"：
   身份文件按形态缓存在进程里，改文件不改缓存 ⇒ 真正对在线会话立即生效的那一半永远是
   凭据侧，只钉身份侧会把一条运维假设当成契约。
4. **`must_change` 门的覆盖面由路由表自证**（SECA-10）：走 `require_user` / `require_permissions`
   的每条端点（今天 41 条）都必须真 403 + 中文文案；走 `require_user_pending_password` 的端点
   集合**恰好等于**白名单（漏一条即红，多一条也红）。手写清单随端点增长必然失真，所以清单由
   遍历依赖树生成；带未登记 path 参数的新端点**主动 fail 并要求登记样例**，而不是猜一个值
   混过去。而"每条都真打 HTTP"这件事本身带着风险：门一旦退化，那 41 条请求就落在 41 个
   真端点上（其中 `POST /api/demo/reset` 会删掉演示语料再强制重建索引）。所以扫描把每条路由的
   处理器换成**绊线桩**——依赖层照旧跑（403 仍然由它产生，判据强度一分不减），业务函数叫不到；
   桩还要与路由器真正派发的那一枚路由对象核对齐，最后断言绊线一次都没响。安全判据与覆盖面
   判据因此不是同一件事，"这次跑完数据没坏"也不再是唯一的 bound。

响应面另有单独一枚钉子：本版**唯一**一处键集合变化是 `POST /api/auth/login` 与
`GET /api/auth/me` 各多 `password_change_required: bool`（§11），值读表不读 claim；其余端点的
键集合由既有契约钉住（`/api/query` 那三枚在本文件之外，跑到红就是本任务做错了）。

已知边界（写在这里，不留给下一个人猜）：第 4 项判的是"**已被认证覆盖的**端点有没有都过门"。
一条压根不挂任何认证依赖的端点、或自造第三条依赖绕开这两个门面的端点，不在本门的判定对象内
（前者属"根本没鉴权"那一类缺陷，后者要靠评审看 diff）；本枚门不假装覆盖它们。但**枚举自己
看得见的边界**是断言而不是假设：挂载点、非 `APIRoute` 的服务面、表上出现未知 HTTP 动词，
都会先红在前提那一枚用例上，而不是让覆盖面从此静默变窄。
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Callable
from unittest import mock

import jwt as pyjwt
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import Host, Match, Mount

BACKEND_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = BACKEND_DIR / "tests"
for _path in (str(BACKEND_DIR), str(TESTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app import auth, credentials, directory, user_store  # noqa: E402
from app import cli  # noqa: E402  —— 凭据运维面（本文件是它唯一的契约读者）
from app import config as config_module  # noqa: E402
from app import main as main_module  # noqa: E402  —— 桩要打在这份命名空间里的绑定上，见 `LoginFaceKeyTests`
import app.main_agent  # noqa: E402,F401  —— uvicorn 跑的是 `app.main_agent:app`：三张 router 挂在同一个 app 实例上，少 import 这一行，覆盖面就只剩半张表
from app.main import app  # noqa: E402
import sec_a_fixtures  # noqa: E402  —— 换库 / 审计落点 / JWT secret 三件地基只留一份实现
from sec_a_seed import ensure_demo_credentials  # noqa: E402

INVALID_TOKEN = "无效登录凭证"
GATE_COPY = "当前账号需先修改口令"
GOOD_PASSWORD = "a-good-password 123456"
NEW_PASSWORD = "a-brand-new-password 123"
LEGACY_ADMIN = hashlib.sha256(b"admin123").hexdigest()

#: 绊线桩被踩到时给出的状态码。它必须**不是** 403：门的判据是"403 + 这句中文"，处理器可达
#: 的形状得在状态码上就分得出来，而不是混进覆盖面里那一格里。
TRIPEWIRE_STATUS = 599
TRIPEWIRE_COPY = "tripwire-handler-unreachable"

#: 本文件唯一认识的 HTTP 方法字母表。`PATCH` 必须在内——会话标题与评测失败案例两条腿就是
#: PATCH，字母表漏一项等于那两条端点从枚举里静默消失（门再红也轮不到它们）。
#: 这件事不再只靠注释提醒：`_method_alphabet_is_closed` 那一枚用例把"表上没有未知动词"钉成
#: 前提，长出 `OPTIONS` / `TRACE` 之类的那天先红在前提上。`HEAD` 是 Starlette 对 GET 路由
#: 可能补出来的别名，允许它出现但**不**把它算成一条端点。
_HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_KNOWN_METHODS = frozenset(_HTTP_METHODS) | {"HEAD"}


def _callee_name(node: ast.Call) -> str:
    """调用点上的函数名：`CurrentUser(...)` 与 `mod.CurrentUser(...)` 同形命中。"""
    return getattr(node.func, "id", None) or getattr(node.func, "attr", None) or ""


def _identity(username: str, *, role: str = "VIEWER", enabled: bool = True,
              feishu_open_id: str | None = None) -> directory.UserIdentity:
    return directory.UserIdentity(
        username=username, display_name=username.title(), role=role,
        enabled=enabled, feishu_open_id=feishu_open_id,
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _fresh_db(test: unittest.TestCase) -> Path:
    """每例一份临时库（实现见 `sec_a_fixtures`）。

    本文件尤其离不开它：用例反复 bump / 删除凭据行，共用一份库就是在共享状态里互相踩对方
    的 token 生命周期。文件名也留在本文件——它是"这一例的库"的标识，红的时候指得出是谁。
    """
    return sec_a_fixtures.fresh_db(test, filename="lifecycle.db")


class _LongJwtSecret(sec_a_fixtures.LongJwtSecretMixin):
    """用例自带一枚够长的 JWT secret（≥32 字节）。

    默认 dev secret 短于 PyJWT 的建议下限，每次签发/校验都喊一句 `InsecureKeyLengthWarning`；
    本文件签的 token 数量比认证腿多一个量级，警告计数跟着漂的话，"套件警告数不变"这枚
    回归信号就废了。选配的写法与认证腿一致：换 `settings.jwt_secret`，不静音警告。
    """

    SECRET = "sec-a-token-lifecycle-test-secret-0123456789abcdef"


class _AuditToTempFile(sec_a_fixtures.AuditToTempFileMixin):
    """审计落到临时文件：既取到证，又不往仓库的 `data/audit.jsonl` 里写测试笔迹。"""


def _decode(token: str) -> dict:
    return pyjwt.decode(token, _LongJwtSecret.SECRET, algorithms=["HS256"], issuer="yaoke")


# --------------------------------------------------------------------------
# 依赖树枚举（SECA-10 的清单生成器）
# --------------------------------------------------------------------------
def _route_keys(route: object) -> tuple[str, ...]:
    """一条路由拆成若干 `"METHOD path"`；挂了多个方法就逐个算，绝不折成一项。

    只取第一个方法那条写法会把 `GET+POST` 同路径的第二个方法静默丢出覆盖面。今天的表里
    每行都只有一个方法（`MustChangeGateCoverageTests` 另钉一条"没有多方法路由"，
    长出那一天这条拆行逻辑必须跟着改判据，而不是让它继续只报第一项）。
    """
    methods = sorted(set(getattr(route, "methods", set()) or ()) & set(_HTTP_METHODS))
    return tuple(f"{method} {route.path}" for method in methods)


def _uses_dependency(dependant, predicate: Callable[[object], bool]) -> bool:
    for sub in dependant.dependencies:
        if predicate(sub.call) or _uses_dependency(sub, predicate):
            return True
    return False


# --- 路由树展开（B0-T5 修复轮，规格 §10.3 第 2 类）-------------------------
# 为什么这里是**递归展开**而不是"把看不懂的顶层条目过滤掉"（§10.3 第 2 类：断言写死了
# 本机形态）：新版 FastAPI（`fastapi/routing.py` 的 `_IncludedRouter`，**不是** Starlette）
# 让 `include_router()` 在顶层只挂一枚指回子路由表的条目、不再把子表复制上来，于是
# "顶层 `app.routes` 就是全部服务面"这个前提已经假了；把它过滤掉等于继续假装前提为真，
# 覆盖面塌一块而门照样绿。递归只可能让清单变宽（宿主的旧形状下逐位等，见 B0 修复报告）。
def _child_nodes(node: object) -> list[object] | None:
    """这枚条目内部挂着的子路由表；不是容器就返回 `None`。

    认三种形状，全部只读属性：① `effective_candidates()`——新版 include 条目给出的**生效**
    子条目，路径已含 include 前缀、dependant 是 include 时重建的那一枚（处理器桩必须打在
    它身上才拦得到真调用）；② `original_router.routes`——同一批子路由的原始形状（宿主
    fastapi 0.135.3 没有 ①，且 `include_router(prefix="")` 时两者等价）；③ 任何自带
    `.routes` 的 router 形状。`Mount` / `Host` **不**在这里展开：它们的子路径是相对挂载点的，
    直接拼出来的 `"METHOD path"` 是一条盘上不存在的假腿——那种形状继续由
    `test_the_enumeration_sees_every_service_surface` 判红，而不是被递归"支持"掉。
    """
    if isinstance(node, (Mount, Host)):
        return None
    candidates = getattr(node, "effective_candidates", None)
    if callable(candidates):
        children = list(candidates())
        if children:
            return children
    router = getattr(node, "original_router", None)
    if router is not None and getattr(router, "routes", None):
        return list(router.routes)
    children = getattr(node, "routes", None)
    if isinstance(children, (list, tuple)) and children:
        return list(children)
    return None


def _node_prefix(node: object) -> str:
    """include 时带的前缀；只在 ②/③ 那种"原始子条目"形状下才需要手工拼进路径。"""
    context = getattr(node, "include_context", None)
    return str(getattr(context, "prefix", "") or "")


def _walk_surfaces(nodes: list[object], prefix: str = "") -> list[dict]:
    """深度优先把整棵路由树摊平成"服务面条目"清单（递归，绝不跳过容器）。

    每条 `{route, path, methods, dependants, node}`：`route` 是可上桩的 `APIRoute`
    （非 `APIRoute` 的条目为 `None`），`path` 是**生效**路径，`dependants` 是派发时真会被读
    到的 dependant 集合（include 重建的那一枚若与 `route.dependant` 不同，两枚都在里面）。
    """
    surfaces: list[dict] = []
    for node in nodes:
        children = _child_nodes(node)
        if children is not None:
            surfaces.extend(
                _walk_surfaces(children, prefix + _node_prefix(node))
            )
            continue
        route = node if isinstance(node, APIRoute) else None
        if route is None:
            original = getattr(node, "original_route", None)
            route = original if isinstance(original, APIRoute) else None
        if route is not None and node is not route:
            # 生效条目（形状 ①）：路径已经带前缀，别再拼一次。
            path, own_prefix = str(getattr(node, "path", "") or ""), ""
        else:
            path, own_prefix = str(getattr(route, "path", "") or ""), prefix
        dependants: list[object] = []
        for holder in (route, node if node is not route else None):
            dependant = getattr(holder, "dependant", None) if holder is not None else None
            if dependant is not None and all(dependant is not seen for seen in dependants):
                dependants.append(dependant)
        surfaces.append({
            "route": route,
            "path": own_prefix + path,
            "methods": getattr(node, "methods", None),
            "dependants": dependants,
            "node": node,
        })
    return surfaces


def _service_surfaces() -> list[dict]:
    return _walk_surfaces(list(app.routes))


def _walk_nodes(nodes: list[object]) -> list[object]:
    """递归访问到的**每一枚**条目（容器自己也算在内）。

    给"挂载点一条都不许有"那枚判据用：它要问的是"树里有没有走不进去的形状"，
    而不是"叶子长什么样"。
    """
    seen: list[object] = []
    for node in nodes:
        seen.append(node)
        children = _child_nodes(node)
        if children:
            seen.extend(_walk_nodes(children))
    return seen


def _surface_keys(surface: dict) -> tuple[str, ...]:
    methods = sorted(set(surface["methods"] or set()) & set(_HTTP_METHODS))
    return tuple(f"{method} {surface['path']}" for method in methods)


def _route_index(predicate: Callable[[object], bool]) -> dict[str, APIRoute]:
    """`"METHOD path" -> 路由对象`：覆盖面清单与处理器桩必须指向**同一个对象**。

    清单来自 `_service_surfaces()` 的**递归**展开（为什么必须递归见 `_child_nodes` 上方那段）。
    这条边界不是谦逊、也不是假设：挂载点、非 `APIRoute` 但带着服务面的条目、表上出现未知
    HTTP 动词都会先红在前提用例上，所以"清单只看得见这些"是一句可核对的话，
    而不是等某次重构把覆盖面静默削窄。
    """
    index: dict[str, APIRoute] = {}
    for surface in _service_surfaces():
        route, dependants = surface["route"], surface["dependants"]
        if route is None or not dependants:
            continue
        if any(_uses_dependency(dependant, predicate) for dependant in dependants):
            for key in _surface_keys(surface):
                index[key] = route
    return index


def _routes_where(predicate: Callable[[object], bool]) -> set[str]:
    return set(_route_index(predicate))


def _predicate_using(target: Callable[..., object]) -> Callable[[object], bool]:
    """把"依赖树经过某个依赖"翻成树上一枚可复用的判定（两判据的说明见 `_routes_using`）。"""
    name = getattr(target, "__name__", "")
    return lambda call: (
        call is target
        or getattr(call, "__qualname__", "") == f"{name}.<locals>.dependency"
    )


def _routes_using(target: Callable[..., object]) -> set[str]:
    """返回"这条路由的依赖树经过该依赖"的端点集合。

    认两件事：① 依赖函数本身（按对象身份，`require_user` 这类直接依赖）；② 依赖**工厂**
    造出的那个闭包——`require_permissions("x")` 交给路由的是函数体内定义的 `dependency`，
    按对象身份永远比不上（每次调用都是新的一枚），于是按限定 qualname 认。
    ② 认不出来也不构成漏覆盖：那枚闭包自己 `Depends(require_user)`，① 那条腿照样把它
    底下整棵子树收进 `authenticated`。② 存在的意义是让"权限族"这件事在清单上**指名可见**，
    而不是靠一条隐式包含关系撑着。
    """
    return _routes_where(_predicate_using(target))


def _resolve_dispatch(nodes: list[object], scope: dict) -> object | None:
    """照 Starlette/FastAPI 的派发循环取**第一个 FULL match**，命中容器就走进它再继续匹配。

    为什么这里也要递归（§10.3 第 2 类，与 `_child_nodes` 同一枚理由）：include 条目自己会
    FULL 命中，而真跑业务的是它里面那枚 `APIRoute`；派发侧不展开的话，"我遍历的树 == 执行器
    跑的树"这句核对会拿容器去比清单里的端点，两边根本不是同一层东西。
    """
    for node in nodes:
        match, child_scope = node.matches(scope)  # type: ignore[arg-type]
        if match is not Match.FULL:
            continue
        children = _child_nodes(node)
        if children is None:
            original = getattr(node, "original_route", None)
            return original if isinstance(original, APIRoute) else node
        inner = _resolve_dispatch(children, {**scope, **child_scope})
        return inner if inner is not None else node
    return None


def _dispatched_route(method: str, path: str) -> object | None:
    """路由器真正会交给哪一枚路由对象。

    "我遍历了 `app.routes`"并不自动等于"请求落在我遍历的那枚路由上"：清单是遍历出来的，
    派发是按顺序匹配出来的，两者会在挂载点、路由遮蔽或注册顺序变化时劈叉，而劈叉的症状恰好
    是"桩打在 A 上、请求进了 B 的真处理器"。这里用路由器自己那枚 `matches()` 把两端对齐，
    并且**跟着 include 条目走进子表**（实现见 `_resolve_dispatch`）。
    """
    scope: dict[str, object] = {
        "type": "http", "path": path, "method": method, "headers": [], "root_path": "",
    }
    return _resolve_dispatch(list(app.router.routes), scope)


def _restore_call(holder: object, original: object) -> None:
    """把 `holder`（一枚 dependant）的处理器换回去。

    单独一个函数是为了能直接挂进 `addCleanup`：用 lambda 的话，清理阶段真抛错时栈上看不出
    是哪一条路由没还原。参数是 dependant 而不是路由对象，因为 include 生效形状下一条端点有
    两枚 dependant，逐枚还原才谈得上"没留桩"。
    """
    holder.call = original


def _route_for(route_key: str) -> APIRoute | None:
    """按 `"METHOD path"` 找那枚路由对象——清单与处理器桩共用的入口。"""
    _method, path = route_key.split(" ", 1)
    for surface in _service_surfaces():
        route = surface["route"]
        if route is not None and surface["path"] == path:
            if route_key in _surface_keys(surface):
                return route
    return None


def _surfaces_of(route: APIRoute) -> list[dict]:
    """这枚路由在**递归展开后**的清单里的全部条目（同一枚路由可能因 include 出现多枚形状）。"""
    return [surface for surface in _service_surfaces() if surface["route"] is route]


def _route_dependants(route: APIRoute) -> list[object]:
    """派发时真会被读到的 dependant 集合：`route.dependant` 加上 include 重建的那一枚。

    为什么两枚都要（§10.3 第 2 类）：新版 include 会给同一枚端点**另建**生效 dependant，
    只把 `route.dependant.call` 换成桩拦不住真调用 —— 那正是本文件最不肯要的失败形状
    （"覆盖面是假的而破坏是真的"）。宿主旧形状下这里只有一枚，逐位等于改前的行为。
    """
    dependants: list[object] = []
    for surface in _surfaces_of(route):
        for dependant in surface["dependants"]:
            if all(dependant is not seen for seen in dependants):
                dependants.append(dependant)
    if not dependants:
        dependant = getattr(route, "dependant", None)
        if dependant is not None:
            dependants.append(dependant)
    return dependants


def _arm_tripwire(test: unittest.TestCase, route: APIRoute, route_key: str,
                  tripped: list[str]) -> object:
    """把这条路由的**处理器**换成绊线桩，返回桩本身（调用方拿它核对派发目标）。

    FastAPI 在每次请求里现取 `dependant.call`（`run_endpoint_function` 与两条流式分支都是
    如此），所以换这一个属性就够——不重建路由、不伪造依赖：403 仍然由真依赖树产生，判的
    仍然是"这条端点过没过门"。桩是**同步**函数并当场抛 `HTTPException`：协程端点的
    `is_coroutine_callable` 在建路由时就定死了，而抛异常发生在调用点上，同步/异步/生成器三条
    分支都在序列化之前出局。还原挂在 `addCleanup` 上，红也没处躲。
    打上的是 `_route_dependants()` 给出的**每一枚** dependant（include 生效形状下有两枚，
    只打一枚等于桩打空；为什么见 `_route_dependants`）。
    """
    tripwires: list[tuple[object, object]] = []

    def tripwire(**_values: object) -> None:
        tripped.append(route_key)
        raise HTTPException(status_code=TRIPEWIRE_STATUS, detail=TRIPEWIRE_COPY)

    for dependant in _route_dependants(route):
        tripwires.append((dependant, dependant.call))
        dependant.call = tripwire
    for dependant, original in tripwires:
        test.addCleanup(_restore_call, dependant, original)
    return tripwire


class TokenClaimTests(_LongJwtSecret, unittest.TestCase):
    """签发面：`cv` 从表里读，其余 claim 一字不少（SEC-A-006）。"""

    def setUp(self):
        super().setUp()
        _fresh_db(self)
        ensure_demo_credentials("admin")
        self.identity = _identity("admin", role="ADMIN")

    def _token(self) -> str:
        with directory.override_identities({"admin": self.identity}):
            return auth.issue_token(auth._user_from(self.identity, None))

    def test_the_issued_token_carries_the_current_table_version(self):
        claimed = _decode(self._token())[auth.CREDENTIAL_VERSION_CLAIM]
        self.assertEqual(user_store.get_record("admin").credentials_version, claimed)
        self.assertEqual("cv", auth.CREDENTIAL_VERSION_CLAIM)

    def test_the_claim_moves_with_the_table_after_a_password_change(self):
        """两枚 token 各自钉住自己那一代：改密后重签的那一枚才跟着表走。"""
        before = _decode(self._token())[auth.CREDENTIAL_VERSION_CLAIM]
        user_store.set_password_argon2(
            "admin", plain_password=NEW_PASSWORD, must_change=False
        )
        after = _decode(self._token())[auth.CREDENTIAL_VERSION_CLAIM]
        self.assertEqual(before + 1, after)

    def test_the_progressive_rehash_does_not_move_the_claim(self):
        """登录把 legacy 行原地换成 argon2id 时**不** bump 版本 ⇒ 会话不该被这次收敛打断。

        这一枚钉的是 claim 的取值口径：`cv` 是"凭据换代"的纪元，不是"这一行被写过"的计数。
        把它写成后者会在每次渐进重哈希时把用户踢下线，而 §8.3 明确说收敛不改会话。
        """
        user_store.delete_record("admin")
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
        user = auth.authenticate("admin", "admin123")
        self.assertIsNotNone(user)
        record = user_store.get_record("admin")
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, record.algorithm)
        with directory.override_identities({"admin": self.identity}):
            token = auth.issue_token(auth._user_from(self.identity, None))
        self.assertEqual(record.credentials_version,
                         _decode(token)[auth.CREDENTIAL_VERSION_CLAIM])
        self.assertEqual(1, record.credentials_version)

    def test_the_pre_existing_claims_are_all_still_issued(self):
        """加一枚 `cv` 不许顺手改掉任何一枚既有 claim：外部消费方在解这个 payload。"""
        payload = _decode(self._token())
        self.assertTrue(
            {"sub", "name", "role", "access_role", "iat", "exp", "iss", "cv"}
            <= set(payload),
            sorted(payload),
        )
        self.assertEqual("yaoke", payload["iss"])
        self.assertEqual("ADMIN", payload["role"])


class TokenRevocationTests(_LongJwtSecret, unittest.TestCase):
    """SECA-09 / SECA-09b：验签之后还要过身份、凭据、版本三关。"""

    def setUp(self):
        super().setUp()
        _fresh_db(self)
        user_store.create_argon2("revoker", plain_password=GOOD_PASSWORD, must_change=False)
        self.identity = _identity("revoker")
        with directory.override_identities({"revoker": self.identity}):
            self.token = auth.issue_token(auth._user_from(self.identity, None))

    @contextlib.contextmanager
    def _known(self, *identities: directory.UserIdentity):
        mapping = {item.username: item for item in identities}
        with directory.override_identities(mapping):
            yield

    def _require(self, token: str):
        return auth.require_user(f"Bearer {token}")

    def test_a_bumped_version_invalidates_the_previously_issued_token(self):
        """SECA-09：改密即废 token，不等 `exp`。"""
        with self._known(self.identity):
            self.assertIsInstance(self._require(self.token), auth.CurrentUser)
            user_store.set_password_argon2(
                "revoker", plain_password=NEW_PASSWORD, must_change=False
            )
            with self.assertRaises(HTTPException) as raised:
                self._require(self.token)
        self.assertEqual(401, raised.exception.status_code)
        self.assertEqual(INVALID_TOKEN, raised.exception.detail)

    def test_a_reissued_token_after_the_change_works_again(self):
        """撤销的是**那一代**凭据，不是这个账号：新版本签出的 token 照常通。

        少这一枚反钉，"旧 token 被拒"的实现可以顺手把整条令牌腿判成死（例如恒定 401），
        而正向用例照样绿。
        """
        user_store.set_password_argon2("revoker", plain_password=NEW_PASSWORD, must_change=False)
        with self._known(self.identity):
            fresh = auth.issue_token(auth._user_from(self.identity, None))
            self.assertEqual("revoker", self._require(fresh).username)

    def test_a_pre_seca_token_without_cv_is_rejected_not_allowed(self):
        """SECA-09b：M17 的靶子——"兼容旧 token"的放行分支必须撞红。"""
        legacy = pyjwt.encode(
            {"sub": "revoker", "role": "VIEWER", "iss": "yaoke",
             "exp": 2 ** 31 - 1, "iat": 1},
            config_module.settings.jwt_secret,
            algorithm="HS256",
        )
        with self._known(self.identity):
            with self.assertRaises(HTTPException) as raised:
                self._require(legacy)
        self.assertEqual(401, raised.exception.status_code)
        self.assertEqual(INVALID_TOKEN, raised.exception.detail)

    def test_a_forged_cv_does_not_outlive_the_table(self):
        """判定读表：claim 里写多大的版本都不算数，它只是"要比哪个"的提示。"""
        forged = pyjwt.encode(
            {"sub": "revoker", "role": "VIEWER", "iss": "yaoke", "exp": 2 ** 31 - 1,
             "iat": 1, auth.CREDENTIAL_VERSION_CLAIM: 10_000},
            config_module.settings.jwt_secret,
            algorithm="HS256",
        )
        with self._known(self.identity):
            with self.assertRaises(HTTPException) as raised:
                self._require(forged)
        self.assertEqual(INVALID_TOKEN, raised.exception.detail)

    def test_a_non_integer_cv_claim_is_rejected(self):
        """`True == 1`、`"1" != 1`：版本必须按整数比，别让它经由弱等值混过去。"""
        record = user_store.get_record("revoker")
        for claim in (True, str(record.credentials_version), 1.0, None, [1]):
            with self.subTest(cv=claim):
                token = pyjwt.encode(
                    {"sub": "revoker", "role": "VIEWER", "iss": "yaoke", "exp": 2 ** 31 - 1,
                     "iat": 1, auth.CREDENTIAL_VERSION_CLAIM: claim},
                    config_module.settings.jwt_secret,
                    algorithm="HS256",
                )
                with self._known(self.identity):
                    with self.assertRaises(HTTPException) as raised:
                        self._require(token)
                self.assertEqual(INVALID_TOKEN, raised.exception.detail)

    def test_the_removed_account_specificity_message_is_gone_from_the_token_face(self):
        """§9.1：「账号不存在」并入「无效登录凭证」，不再泄露存在性。"""
        with self._known():
            with self.assertRaises(HTTPException) as raised:
                self._require(self.token)
        self.assertEqual(401, raised.exception.status_code)
        self.assertEqual(INVALID_TOKEN, raised.exception.detail)
        self.assertNotIn("账号不存在", raised.exception.detail)

    def test_a_deleted_credential_row_revokes_an_issued_token(self):
        """有身份、无凭据行 ⇒ 与"不认识这个主体"同一格（§6.4 停用动作的凭据侧那一半）。"""
        user_store.delete_record("revoker")
        with self._known(self.identity):
            with self.assertRaises(HTTPException) as raised:
                self._require(self.token)
        self.assertEqual(INVALID_TOKEN, raised.exception.detail)

    def test_an_expired_token_still_reports_the_expired_copy(self):
        """过期与撤销同**状态码**、不同**文案**：运维得能从审计之外的响应面分清两者。"""
        stale = pyjwt.encode(
            {"sub": "revoker", "role": "VIEWER", "iss": "yaoke", "iat": 1, "exp": 1,
             auth.CREDENTIAL_VERSION_CLAIM: user_store.get_record("revoker").credentials_version},
            config_module.settings.jwt_secret,
            algorithm="HS256",
        )
        with self._known(self.identity):
            with self.assertRaises(HTTPException) as raised:
                self._require(stale)
        self.assertEqual("登录已过期，请重新登录", raised.exception.detail)

    def test_a_missing_header_still_reports_the_login_first_copy(self):
        """三格 401 文案互不相同，而认证失败面不区分"你是谁"（§9.1 表）。"""
        with self.assertRaises(HTTPException) as raised:
            auth.require_user(None)
        self.assertEqual("请先登录", raised.exception.detail)


class TokenFaceHttpTests(_LongJwtSecret, _AuditToTempFile, unittest.TestCase):
    """撤销必须在**真 HTTP 面**上落地：SECA-09 点名的判据对象是 `/api/query`。"""

    #: 本文件唯一一处"带着真 body 打业务面"的判据对象。它要的 401 来自依赖层，因此处理器
    #: 根本不该被叫到——上绊线桩之后，"实现退化"那次跑（例如 `cv` 缺失被放行）就只红在断言
    #: 上，而不是顺手拨一次向量库/模型：判据说"到不了业务"，那就让它到不了。
    DATA_FACE = "POST /api/query"

    def setUp(self):
        super().setUp()
        _fresh_db(self)
        ensure_demo_credentials("admin")
        self.client = TestClient(app)
        self.tripped: list[str] = []
        route = _route_for(self.DATA_FACE)
        self.assertIsNotNone(route, f"{self.DATA_FACE} 不在路由表上：本类的判据对象没了")
        _arm_tripwire(self, route, self.DATA_FACE, self.tripped)

    def _headers(self, username: str = "admin", password: str = "admin123") -> dict[str, str]:
        login = self.client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        self.assertEqual(200, login.status_code, login.text)
        return _bearer(login.json()["access_token"])

    def _query(self, headers: dict[str, str]):
        response = self.client.post(
            "/api/query", json={"question": "撤销之后还能问吗", "k": 1}, headers=headers
        )
        self.assertEqual([], self.tripped, "数据面处理器可达：本用例不必碰外部服务就能判")
        return response

    def test_a_password_change_kicks_the_old_token_out_of_the_data_face(self):
        headers = self._headers()
        # 前置"此刻是活的"走 `/me` 而不是 `/api/query`：后者要真读向量库与模型，
        # 把一本来只看依赖层的用例绑到外部服务上，红起来分不清是谁的锅。
        self.assertEqual(200, self.client.get("/api/auth/me", headers=headers).status_code)
        user_store.set_password_argon2(
            "admin", plain_password=NEW_PASSWORD, must_change=False
        )
        blocked = self._query(headers)
        self.assertEqual(401, blocked.status_code, blocked.text)
        self.assertEqual(INVALID_TOKEN, blocked.json()["detail"])
        # 响应面不许出现任何英文 token 或撤销原因（§9.1 两栏：机器可读性走审计）
        self.assertNotIn("invalid", blocked.text.lower())
        self.assertNotIn(NEW_PASSWORD, blocked.text)
        self.assertNotIn("admin123", blocked.text)

    def test_a_pre_seca_token_is_rejected_by_the_data_face_too(self):
        """依赖层与 HTTP 层同一条腿：这一枚钉的是"兼容分支"在真请求上也不许留缝。"""
        legacy = pyjwt.encode(
            {"sub": "admin", "role": "ADMIN", "iss": "yaoke", "exp": 2 ** 31 - 1, "iat": 1},
            config_module.settings.jwt_secret,
            algorithm="HS256",
        )
        blocked = self._query(_bearer(legacy))
        self.assertEqual(401, blocked.status_code, blocked.text)
        self.assertEqual(INVALID_TOKEN, blocked.json()["detail"])

    def test_the_pending_leg_compares_versions_as_well(self):
        """白名单腿免的是 `must_change` 门，不免令牌生命周期：旧 token 连 `/me` 也进不去。

        这一条是后面改密腿的地基：改密成功那一刻旧会话整体作废，客户端必须重新登录
        才能再拿到一枚活的 token——"改完还能用旧 token 读 /me"会变成第二条撤销绕过。
        """
        headers = self._headers()
        self.assertEqual(200, self.client.get("/api/auth/me", headers=headers).status_code)
        user_store.set_password_argon2(
            "admin", plain_password=NEW_PASSWORD, must_change=True
        )
        blocked = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(401, blocked.status_code, blocked.text)
        self.assertEqual(INVALID_TOKEN, blocked.json()["detail"])


class AccountDisablePairingTests(_LongJwtSecret, _AuditToTempFile, unittest.TestCase):
    """§6.4：停用是**成对**动作。这里把两半各自钉住，顺带钉住"为什么必须有第二半"。"""

    def setUp(self):
        super().setUp()
        _fresh_db(self)
        user_store.create_argon2("paused", plain_password=GOOD_PASSWORD, must_change=False)
        self.enabled = _identity("paused", role="USER", enabled=True)
        with directory.override_identities({"paused": self.enabled}):
            self.token = auth.issue_token(auth._user_from(self.enabled, None))

    def test_the_credential_side_alone_revokes_a_live_token_while_the_cache_is_stale(self):
        """只删凭据行（身份缓存还写着 enabled=true）也必须废掉 token——这是在线的那一半。

        身份文件按形态缓存在进程里（`directory.identities()`），改文件不调 `reset_cache()`
        就不进进程 ⇒ 运维改完文件的那一刻，能立刻挡住旧 token 的只有凭据侧。
        """
        user_store.delete_record("paused")
        with directory.override_identities({"paused": self.enabled}):
            with self.assertRaises(HTTPException) as raised:
                auth.require_user(f"Bearer {self.token}")
        self.assertEqual(INVALID_TOKEN, raised.exception.detail)

    def test_the_identity_side_alone_revokes_a_live_token(self):
        """进程读到 `enabled=false` 之后（重启或缓存复位），身份侧那一半单独也够用。"""
        disabled = _identity("paused", role="USER", enabled=False)
        with directory.override_identities({"paused": disabled}):
            with self.assertRaises(HTTPException) as raised:
                auth.require_user(f"Bearer {self.token}")
        self.assertEqual(INVALID_TOKEN, raised.exception.detail)

    def test_the_pairing_revokes_it_on_the_http_face(self):
        """成对动作在真请求上的合力：401、中文文案、且停用二字不上响应面。"""
        user_store.set_password_argon2(
            "paused", plain_password=NEW_PASSWORD, must_change=False
        )
        disabled = _identity("paused", role="USER", enabled=False)
        client = TestClient(app)
        with directory.override_identities({"paused": disabled}):
            blocked = client.get("/api/auth/me", headers=_bearer(self.token))
        self.assertEqual(401, blocked.status_code, blocked.text)
        self.assertEqual(INVALID_TOKEN, blocked.json()["detail"])
        self.assertNotIn("停用", blocked.text)


class NoCredentialIdentityTokenTests(_LongJwtSecret, unittest.TestCase):
    """无凭据身份签出的 token 一签发即死（`cv=0` 裁定的形状）。"""

    def setUp(self):
        super().setUp()
        _fresh_db(self)
        self.identity = _identity("ghost")

    def test_a_token_for_an_identity_without_a_row_carries_version_zero(self):
        with directory.override_identities({"ghost": self.identity}):
            token = auth.issue_token(auth._user_from(self.identity, None))
        self.assertEqual(0, _decode(token)[auth.CREDENTIAL_VERSION_CLAIM])

    def test_version_zero_never_matches_a_real_row_however_later_it_appears(self):
        """`0` 与表内任何真实版本都不等 ⇒ 不给"无凭据身份"另开第二条构造路径。

        凭据行晚一步出现（首版恒 1）时这枚 token 仍是死的：判据不是"当时有没有行"，
        而是"这一代凭据有没有换过"，两件事在 `cv=0` 上不会分叉成一个放行分支。
        """
        with directory.override_identities({"ghost": self.identity}):
            token = auth.issue_token(auth._user_from(self.identity, None))
        user_store.create_argon2("ghost", plain_password=GOOD_PASSWORD, must_change=False)
        with directory.override_identities({"ghost": self.identity}):
            with self.assertRaises(HTTPException) as raised:
                auth.require_user(f"Bearer {token}")
        self.assertEqual(INVALID_TOKEN, raised.exception.detail)

    def test_the_current_user_construction_face_stays_a_single_door(self):
        """有凭据与无凭据两种身份走的是**同一个**构造点，差别只在 payload 那一枚数字。

        构造面一分裂，`grant` 语义就会在两扇门里劈叉（认证腿的既有裁定：`_user_from` 是
        `CurrentUser` 的唯一构造点）。这里钉的是源码结构，因为行为用例对"两条路径"这件事
        天生不敏感——两条路径可以各自绿很久。判据走 AST 而不是数子串：数 `return CurrentUser(`
        会被一次换行/加括号的重排误伤，也会放过"第二处写成 `user = CurrentUser(...)`"这种
        真正要抓的形状。同一句理由也管住了被并入的旧文案：「账号不存在」一旦回到 `detail=`，
        它就又是一条存在性指纹。
        """
        source = Path(auth.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        doors = [
            (fn.name, node.lineno)
            for fn in ast.walk(tree)
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
            for node in ast.walk(fn)
            if isinstance(node, ast.Call) and _callee_name(node) == "CurrentUser"
        ]
        # 一条等值判定同时管住"只有一处"和"就在唯一那道门下"：多一处、少一处、挪到别的
        # 函数里三种漂移都红，而换行与括号重排都动不了它。
        self.assertEqual(
            ["_user_from"], [name for name, _lineno in doors],
            f"CurrentUser 的构造点必须只有一处、且就在唯一那道门下：{doors}",
        )
        self.assertNotIn('detail="账号不存在"', source)


class LoginFaceKeyTests(_LongJwtSecret, _AuditToTempFile, unittest.TestCase):
    """§11：本版**唯一**一处响应面键集合变化，两处 additive 键。"""

    USER_KEYS = {"username", "display_name", "role", "access_role", "permissions"}

    def setUp(self):
        super().setUp()
        _fresh_db(self)
        self.client = TestClient(app)

    def _login(self, username: str, password: str):
        return self.client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )

    def test_the_login_body_gained_exactly_one_key(self):
        ensure_demo_credentials("admin")
        response = self._login("admin", "admin123")
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual(
            {"access_token", "token_type", "user", "password_change_required"}, set(body)
        )
        self.assertIsInstance(body["password_change_required"], bool)
        self.assertFalse(body["password_change_required"])
        # 既有嵌套投影一字不动：新键只加在顶层，不塞进 `user` 里改它的形状
        self.assertEqual(self.USER_KEYS, set(body["user"]))
        self.assertNotIn("grant", body["user"])

    def test_the_me_body_gained_the_same_one_key(self):
        ensure_demo_credentials("admin")
        token = self._login("admin", "admin123").json()["access_token"]
        body = self.client.get("/api/auth/me", headers=_bearer(token)).json()
        self.assertEqual(self.USER_KEYS | {"password_change_required"}, set(body))
        self.assertFalse(body["password_change_required"])
        self.assertNotIn("grant", body)

    def test_both_faces_say_true_for_an_account_behind_the_gate(self):
        """键不是摆设：legacy 出身当场置门（§8.3），两处都得报 True。"""
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
        body = self._login("admin", "admin123").json()
        self.assertTrue(body["password_change_required"])
        me = self.client.get(
            "/api/auth/me", headers=_bearer(body["access_token"])
        ).json()
        self.assertTrue(me["password_change_required"])

    def _handler_lookup(self) -> tuple[object, object]:
        """两个处理器在**调用瞬间**各自会查到的那个名字（登录面、`/me`）。

        `from app.auth import _password_change_required` 在 import 那一刻就把名字复制进了
        `app.main` 的命名空间；此后改 `app.auth` 那一格根本够不到这两个调用点。桩必须打在
        处理器真正查找的位置上，否则用例判的是一段没人执行的代码——所以每次上桩都先拿这两格
        核对一遍：命名空间哪天劈叉，先红的是这条核对，而不是一枚永远不会失败的假桩。
        """
        globals_ = main_module.me.__globals__
        return (
            main_module.login.__globals__["_password_change_required"],
            globals_["_password_change_required"],
        )

    def test_both_faces_resolve_the_gate_predicate_through_one_binding(self):
        """前提：登录面与 `/me` 查的是同一个名字，而且它就是 `app.main` 自己那份绑定。

        这一枚只钉"桩该打在哪"这件事。值本身的两个方向（表说 0 / 表说 1）由下面两枚各判一次。
        """
        login_side, me_side = self._handler_lookup()
        self.assertIs(login_side, me_side, "两处判定已经各自拿了不同的函数")
        self.assertIs(login_side, main_module._password_change_required)
        self.assertIs(login_side, auth._password_change_required)

    def test_the_login_value_comes_from_the_login_leg_not_from_a_second_read(self):
        """两处判定早晚劈叉：登录面读的是 `LoginResult`，不在这儿重新查表。

        桩打在**登录面会叫到的那个读表函数**上（`app.main` 自己那份绑定，见
        `_handler_lookup`）：登录面若改去叫它，本例立刻拿到 True，而真值（argon2 行未置门）
        是 False。§8.3 的渐进重哈希路径正是两处读数会劈叉的地方——登录腿当场置门，表里那一格
        在这次登录之前还是 0，"响应面说不用改密、门已经挡在下一跳"就是从这里长出来的。
        """
        ensure_demo_credentials("admin")
        with mock.patch.object(
            main_module, "_password_change_required", return_value=True
        ) as stub:
            self.assertIs(stub, self._handler_lookup()[0], "桩不在登录面的查找路径上")
            self.assertIs(stub, self._handler_lookup()[1], "桩不在 /me 的查找路径上")
            body = self._login("admin", "admin123").json()
        self.assertFalse(body["password_change_required"])
        self.assertEqual(0, stub.call_count, "登录面重新查表了：这一格的值必须来自 LoginResult")

    def test_the_me_value_is_the_same_predicate_the_gate_uses(self):
        """反方向：`/me` 那一格确实经过同一个判定——把它桩成 False，门开着也报 False。

        与上一枚成对：上一枚证明登录面**不叫**这个函数，这一枚证明 `/me` 叫的**就是**它。
        只留上一枚的话，"桩打错了命名空间"也能一路绿（本文件此前判的正是那种绿）。若哪天
        `/me` 改从别处取这一格，本例应当**改判据**而不是删断言。
        """
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
        token = self._login("admin", "admin123").json()["access_token"]
        self.assertTrue(
            self.client.get("/api/auth/me", headers=_bearer(token)).json()[
                "password_change_required"
            ]
        )
        with mock.patch.object(
            main_module, "_password_change_required", return_value=False
        ) as stub:
            self.assertIs(stub, self._handler_lookup()[1], "桩不在 /me 的查找路径上")
            body = self.client.get("/api/auth/me", headers=_bearer(token)).json()
        self.assertEqual(1, stub.call_count, "/me 没经过那个判定：两处读数的同源就没了")
        self.assertFalse(body["password_change_required"])

    def test_the_auth_side_attribute_is_not_a_second_door_for_the_me_face(self):
        """`app.auth` 那一格改不动响应面：门状态在 `/me` 这里只有一个来源。

        令牌腿自己（`require_user` 里的门）叫的是同一枚函数对象，但在 def-site 上换属性
        进不了 `app.main` 的命名空间——于是"表在门里"的 `/me` 照旧报 True。这一枚与上一枚
        合起来把"桩该打在哪"钉成两边各判一次，而不是靠注释提醒。
        """
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
        token = self._login("admin", "admin123").json()["access_token"]
        with mock.patch.object(auth, "_password_change_required", return_value=False):
            self.assertIsNot(
                auth._password_change_required,
                self._handler_lookup()[1],
                "两份绑定已经合一了：本例的前提随之消失，改判据而不是留着当装饰",
            )
            body = self.client.get("/api/auth/me", headers=_bearer(token)).json()
        self.assertTrue(body["password_change_required"])

    def test_the_me_value_is_read_from_the_table_not_from_the_token(self):
        """`/me` 的判定读表：把门状态写进 claim 就等于让 token 自己声明"我不必改密"。"""
        ensure_demo_credentials("admin")
        token = self._login("admin", "admin123").json()["access_token"]
        self.assertFalse(
            self.client.get("/api/auth/me", headers=_bearer(token)).json()[
                "password_change_required"
            ]
        )
        # 同一枚 token（payload 里没有任何门状态），表一置门两处读数就都翻成 True。
        user_store.set_password_argon2("admin", plain_password=NEW_PASSWORD, must_change=True)
        revived = self._login("admin", NEW_PASSWORD).json()["access_token"]
        self.assertTrue(
            self.client.get("/api/auth/me", headers=_bearer(revived)).json()[
                "password_change_required"
            ]
        )
        self.assertNotIn(
            "must_change", json.dumps(pyjwt.decode(token, options={"verify_signature": False}))
        )

    def test_the_two_faces_carry_no_english_token_in_their_bodies(self):
        """§9.1 两栏：布尔**键**叫 `password_change_required` 是协议，值域里没有自由文本。

        判的是"任何一格取值都不许长成审计 token"——`must_change` 那种把内部字段名顺手
        投影到响应面的写法会在这里红；键名本身不在判定对象内（它是 §11 声明的契约）。
        """
        ensure_demo_credentials("admin")
        login = self._login("admin", "admin123").json()
        me = self.client.get(
            "/api/auth/me", headers=_bearer(login["access_token"])
        ).json()
        tokens = set(auth.LOGIN_AUDIT_DETAILS) | {
            "password_change_required", "invalid_credentials", "invalid_token", "must_change",
        }
        for body in (login, login["user"], me):
            for key, value in body.items():
                if isinstance(value, str):
                    # 只判字符串取值：`permissions` 那一格是 list，`in` 一枚 set 会先撞
                    # unhashable 而不是给出结论。
                    self.assertNotIn(value, tokens, f"{key} 的取值成了审计 token")
        self.assertIsInstance(login["password_change_required"], bool)
        self.assertIsInstance(me["password_change_required"], bool)


class MustChangeGateCoverageTests(_LongJwtSecret, _AuditToTempFile, unittest.TestCase):
    """SECA-10：门必须由路由表自证覆盖，不靠手写清单——新增端点忘了登记就直接红。"""

    #: `require_user_pending_password` 的端点集合恰好等于这两条免门腿——多一条或漏一条，
    #: 覆盖面用例里那句"白名单 == 走免门依赖的端点集合"的相等断言立刻红。
    WHITELIST = frozenset({"POST /api/auth/password/change", "GET /api/auth/me"})

    #: 白名单两条腿各自的"合法请求"与"放行后必须看到的那一格"。只比集合相等会被"整表为空"
    #: 骗过去（见 `test_the_pending_dependency_is_used_by_the_whitelist_only`）：改密这条腿
    #: 免的是门，不免请求体，所以它得带着**合法** body 进来才算真到了处理器。
    PENDING_PROBE = {
        "GET /api/auth/me": (
            None,
            lambda body: body["password_change_required"] is True,
        ),
        "POST /api/auth/password/change": (
            {"current_password": GOOD_PASSWORD, "new_password": NEW_PASSWORD},
            lambda body: body["changed"] is True and isinstance(body["access_token"], str),
        ),
    }

    #: 表里出现的每一个 path 参数都得有样例；样例只用"必然不存在"的 id，让放行分支顶多
    #: 走到 404/403，不会真读到别人的数据。这条规则不是洁癖：处理器可达恰恰发生在"门退化"
    #: 那一次运行里，用真 KB id 就等于把那次跑测试变成一次真读。
    PARAM_SAMPLES = {
        "conversation_id": "conv-nonexistent",
        "message_id": "msg-nonexistent",
        "document_id": "doc-nonexistent",
        "knowledge_base_id": "kb-nonexistent",
        "kb_id": "kb-nonexistent",
        "run_id": "run-nonexistent",
        "trace_id": "trace-nonexistent",
        "job_id": "job-nonexistent",
        "case_id": "case-nonexistent",
        "file_name": "absent.txt",
        #: 管理员重置腿的账号名。样例取"必然不存在"的名字：可达时它顶多走到 404「账号不存在」，
        #: 不会真改掉任何一个活账号的凭据。
        "username": "user-nonexistent",
        #: `action` 不是 id，是一条枚举：`list` 落在 `document_action` 的白名单**之外**，
        #: 于是可达时它先 400/422 而不会真去重建索引或移动文件。
        "action": "list",
    }

    #: 规格 §8.4 点名的三条腿 + 名册那一面：枚举机制一旦失效（依赖树读空、qualname 漂了），
    #: authenticated 集合会缩水成空集，只靠"每条都 403"是判不出来的——那叫没人参加的检查。
    #: `POST /api/demo/reset` 也在内：它是这条扫描唯一一处"门没了就会真删数据"的端点，
    #: 扫描的安全论证要求它**必须**在覆盖面里被上桩，而不是靠运气不在清单上。
    MUST_BE_COVERED = frozenset({
        "POST /api/query",
        "POST /api/query/stream",
        "POST /api/conversations/{conversation_id}/messages/stream",
        "POST /api/agent/query",
        "POST /api/agent/query/stream",
        "PATCH /api/conversations/{conversation_id}",
        "GET /api/auth/users",
        "POST /api/demo/reset",
    })

    #: 天然不该被认证覆盖的面：它们出现在 authenticated 里就是枚举在瞎报。
    MUST_NOT_BE_COVERED = frozenset({
        "GET /api/health",
        "GET /api/ready",
        "POST /api/auth/login",
    })

    #: 扫描期间必须"叫不到"的破坏性入口（`app.main` 里的那两份绑定）。`reset_demo()` 逐条
    #: 从向量库里删掉演示文档、unlink `data/documents/**` 下的原件，再 `initialize_demo(force=True)`
    #: 强制重建索引；后者往同一批路径写文件。绊线桩已经让处理器不可达，这一层是给"桩打错了
    #: 地方 / 派发目标与遍历结果劈叉"那种形状兜底的：它把已知会伤数据的两个函数就地变成红，
    #: 而不是等跑完再去比对 mtime——一次核对管不住一次可重复的机制。
    DESTRUCTIVE_DEMO_ENTRIES = ("reset_demo", "initialize_demo")

    def setUp(self):
        super().setUp()
        # 失败信息要把每条端点的实际 `(route, status, detail)` 都摊开给人看（今天 41 条）：
        # 默认的截断会把诊断缩成一份看不全的名单，而这份名单正是这条用例的全部结论。
        self.maxDiff = None
        _fresh_db(self)
        user_store.create_argon2("gated", plain_password=GOOD_PASSWORD, must_change=True)
        self.identity = _identity("gated", role="ADMIN")
        stack = contextlib.ExitStack()
        stack.enter_context(directory.override_identities({"gated": self.identity}))
        self.addCleanup(stack.close)
        # 一整个用例只签一枚 token：每次签都付一次 Argon2 之外的读表，而覆盖面判据要的
        # 只是"同一枚活 token 打遍全表"。
        self.token = auth.issue_token(auth._user_from(self.identity, None))
        self.client = TestClient(app)
        #: 绊线记录：谁被踩了。判据是"永远为空"。
        self.tripped: list[str] = []
        #: `id(路由对象) -> 本次上上去的桩`，用来核对"派发目标身上的 call 就是我上的桩"。
        self.stub_of: dict[int, object] = {}
        self.demo_sentinels: dict[str, mock.MagicMock] = {}
        for name in self.DESTRUCTIVE_DEMO_ENTRIES:
            sentinel = mock.patch.object(
                main_module, name,
                side_effect=AssertionError(f"扫描期间调到了真处理器 {name}()"),
            )
            self.demo_sentinels[name] = sentinel.start()
            self.addCleanup(sentinel.stop)
        # 先登记、因此最后执行（`addCleanup` 是 LIFO）：扫描不许把任何一条路由留在桩上。
        # 漏还原的症状是"本会话之后每条打到这些端点的用例都拿到 599"，那比当场红难查得多。
        self.addCleanup(self._assert_no_stub_left)

    def _assert_no_stub_left(self) -> None:
        stubs = set(self.stub_of.values())
        stuck = sorted({
            surface["path"] for surface in _service_surfaces()
            for dependant in surface["dependants"]
            if getattr(dependant, "call", None) in stubs
        })
        self.assertEqual([], stuck, f"这些路由的处理器还挂在绊线上：{stuck}")

    # --- 覆盖面判定 -------------------------------------------------------
    def test_every_authenticated_route_is_gated_or_whitelisted(self):
        """逐条真打 HTTP，而处理器逐条**不可达**：安全判据与覆盖面判据不能是同一件事。

        这条扫描对 `authenticated - pending` 的每一条端点（今天 41 条；白名单那条走的是免门
        腿、从来不在 `authenticated` 里，所以不减）发出真请求。它的危险性也在这里：门一退化，
        这些请求就落在真端点上，其中 `POST /api/demo/reset` 会删演示语料再重建索引。于是先把每
        条路由的 `dependant.call` 换成绊线桩、再发第一条请求——依赖层照旧跑（403 正是从那儿
        来的，"这条端点过没过门"判的强度一分不减），业务函数叫不到。桩是否与路由器真正派发的
        那枚路由对齐逐条核对；绊线有没有响过、demo 入口有没有被叫过、审计有没有逐条落笔，
        最后各判一次。
        """
        index = _route_index(_predicate_using(auth.require_user))
        index.update(_route_index(_predicate_using(auth.require_permissions)))
        authenticated = set(index)
        pending = _routes_using(auth.require_user_pending_password)
        self.assertEqual(set(self.WHITELIST), pending, "白名单外泄：有端点改走了免门依赖")
        self.assertTrue(
            self.MUST_BE_COVERED <= authenticated,
            f"枚举漏腿：{sorted(self.MUST_BE_COVERED - authenticated)}",
        )
        self.assertEqual(
            set(), self.MUST_NOT_BE_COVERED & authenticated, "枚举把公开面算成了认证面"
        )
        swept = sorted(authenticated - pending)

        urls: dict[str, str] = {}
        for key in swept:
            url = self._url(key.split(" ", 1)[1])
            if "{" in url:
                # 猜一个值过去 = 这一条从此不再被覆盖。让它红在这里，红在**加端点的人**身上。
                self.fail(f"新增端点带未登记的 path 参数，请把样例加进 PARAM_SAMPLES：{key}")
            urls[key] = url
        for key in swept:
            self._arm(index[key], key)          # 全部上桩之后才发第一条请求

        misplaced: list[str] = []
        findings: list[tuple[str, int, object]] = []
        for key in swept:
            method, path = key.split(" ", 1)
            route = index[key]
            dispatched = _dispatched_route(method, urls[key])
            if dispatched is not route:
                misplaced.append(
                    f"{key}: 路由器把请求交给 {getattr(dispatched, 'path', dispatched)!r}"
                )
            elif getattr(route.dependant, "call", None) is not self.stub_of.get(id(route)):
                misplaced.append(f"{path}: 派发目标身上的 call 不是本次上的桩（桩被打掉了）")
            status, detail = self._attempt(method, urls[key])
            if (status, detail) != (403, GATE_COPY):
                findings.append((key, status, detail))

        self.assertEqual(
            [], misplaced,
            "扫描桩不在路由器派发的那枚路由上：我遍历的树 ≠ 执行器跑的树，"
            "这种形状下覆盖面是假的而破坏是真的",
        )
        tripped = sorted(set(self.tripped))
        self.assertEqual(
            [], findings,
            f"{len(swept)} 条已认证端点应逐条 403 + 中文文案；没过门的"
            f"（route, status, detail）：{findings}。同批次绊线命中 {len(tripped)} 条——"
            f"其余 {len(swept) - len(tripped)} 条是必填 query/body 先 422 的，"
            "处理器到不了不等于门在场，两条判据各判各的",
        )
        self.assertEqual(
            [], tripped,
            f"绊线响了 {len(tripped)} 条：处理器可达 ⇒ 这条扫描本身不再是安全的",
        )
        self.assertEqual(
            {name: 0 for name in self.DESTRUCTIVE_DEMO_ENTRIES},
            {name: int(sentinel.call_count) for name, sentinel in self.demo_sentinels.items()},
            "破坏性 demo 入口在扫描期间被调到",
        )
        # SECA-10 的审计条款逐条成立才算成立：挡了几条，审计就该有几笔。
        denials = [
            event for event in self.events()
            if (event["action"], event["status"], event["detail"])
            == ("AUTHORIZATION", "DENIED", "password_change_required")
        ]
        self.assertEqual(len(swept), len(denials), "门挡下的请求与审计笔数不等")

    def test_no_route_is_registered_with_several_http_methods(self):
        """拆行枚举的前提：今天没有一条路由同时挂多个方法。长出那一天本枚红，提醒改判据。

        取的是递归展开后的清单（为什么见 `_child_nodes`）——include 子表里的多方法路由同样是
        真路由，只看顶层会把这条前提悄悄放宽成"只有顶层那几条不许多方法"。
        """
        multi = sorted(
            (surface["path"], sorted(set(surface["methods"] or ())))
            for surface in _service_surfaces()
            if surface["route"] is not None and len(set(surface["methods"] or ())) > 1
        )
        self.assertEqual([], multi)

    def test_the_method_alphabet_sees_every_registered_verb(self):
        """`_route_keys` 是与 `_HTTP_METHODS` **求交**：字母表漏一项，那条端点就静默消失。

        两种形状都在这里红：表上出现本文件不认识的动词（`OPTIONS` / `TRACE` / 自定义），以及
        一条路由的方法集只剩 `HEAD` 以致一行都拆不出来。门的覆盖面要跟着路由表长，而不是跟着
        本文件的常量长——否则新增一条 `TRACE` 端点会既不过门也不被任何人发现。
        清单同样取递归展开后的（为什么见 `_child_nodes`）。
        """
        blind: list[tuple[str, list[str]]] = []
        for surface in _service_surfaces():
            if surface["route"] is None:
                continue
            methods = set(surface["methods"] or ())
            unknown = sorted(methods - _KNOWN_METHODS)
            if unknown:
                blind.append((surface["path"], unknown))
            elif methods and not _surface_keys(surface):
                blind.append((surface["path"], sorted(methods)))
        self.assertEqual([], blind, "枚举看不见这些方法：把字母表补全，别把端点丢掉")

    def test_the_enumeration_sees_every_service_surface(self):
        """`_route_index` 走的是**递归展开**后的整棵树——这条边界得**看得见**、也得走得动。

        挂载点（`app.mount()`）、子路由、带依赖的非 `APIRoute` 条目都会让一棵子树**静默**退出
        覆盖面：清单少了条目，剩下的每条照样各得 403，门是绿的而覆盖面已经塌了一块。这里把
        "没有枚举看不见的服务面"钉成断言。

        B0 Task 5 容器格的实测形状（fastapi 0.141.1）改了这条的写法但**没有放宽它**：
        `include_router()` 现在在顶层挂一枚 `_IncludedRouter` 条目而不再把子表复制上来，
        所以"带子表 = 枚举看不见"这句已经不成立——递归恰恰是走进它。于是本枚改成两条都判：
        ① 递归**走不进**的容器（挂载点族）一条都不许有；
        ② 递归展开后的叶子里，非 `APIRoute` 的只允许是文档面那类——不挂依赖、不在 `/api/` 之下。
        外加一条把"只增不减"钉死的探针：递归清单必须**包含**只看顶层时能看见的每一条腿。
        哪天要挂静态资源或子应用，先在这里改判据，再谈覆盖面。
        """
        unwalkable = sorted({
            getattr(node, "path", type(node).__name__)
            for node in _walk_nodes(list(app.routes))
            if isinstance(node, (Mount, Host))
        })
        self.assertEqual([], unwalkable, "出现挂载点：递归也不展开它，覆盖面会漏掉整棵子树")
        off_enumeration = sorted({
            getattr(surface["node"], "path", type(surface["node"]).__name__)
            for surface in _service_surfaces()
            if surface["route"] is None
            and (
                str(getattr(surface["node"], "path", "")).startswith("/api")
                or getattr(surface["node"], "dependant", None) is not None
                or bool(surface["dependants"])
                or surface["methods"] is None
            )
        })
        self.assertEqual([], off_enumeration, "非 APIRoute 的叶子带着服务面：枚举不覆盖它")
        # "只增不减"钉：顶层那一条腿都不许因为这次改递归而消失（放宽覆盖面就红在这里）。
        top_level = {
            key for route in app.routes
            if isinstance(route, APIRoute) and getattr(route, "dependant", None) is not None
            for key in _route_keys(route)
        }
        recursive = {
            key for surface in _service_surfaces()
            if surface["route"] is not None
            for key in _surface_keys(surface)
        }
        self.assertEqual(
            [], sorted(top_level - recursive),
            "递归展开反而比顶层枚举少看见了这些腿：那是放宽，不是修复",
        )
        # 独立 oracle：OpenAPI 是库**自己**遍历生效路由表生成的，它列出的每一条 operation 都
        # 必须出现在递归清单里。顶层枚举 vs 递归枚举谁赢是本枚自己算的，容易被"两边都漏了
        # 同一处"糊过去；库自己那张表漏不了——递归走不进某一棵子树时，这里立刻点名。
        openapi_blind: list[str] = []
        for path, item in app.openapi().get("paths", {}).items():
            for verb in item:
                if verb.upper() in _HTTP_METHODS:
                    key = f"{verb.upper()} {path}"
                    if key not in recursive:
                        openapi_blind.append(key)
        self.assertEqual(
            [], sorted(openapi_blind),
            "OpenAPI 有这些 operation 而递归清单看不见：覆盖面已经塌了一块",
        )

    def test_the_pending_dependency_is_used_by_the_whitelist_only(self):
        """白名单那两条得**真的**在免门腿上：只比集合相等会被"整表为空"骗过去。

        两条腿各有各的"到得了"形状：`/me` 无 body，改密腿要带合法 body（少这一格，改密腿
        会因为"空 body 先 422"而被误判成"门没挡 = 白名单生效"）。判据用 `PENDING_PROBE` 里
        那一格**值**，不是状态码——200 而键值不对同样是没走到真处理器。
        """
        for key in sorted(self.WHITELIST):
            method, path = key.split(" ", 1)
            body, observes = self.PENDING_PROBE[key]
            request: dict[str, object] = {"headers": _bearer(self.token)}
            if body is not None:
                request["json"] = body
            response = self.client.request(method, self._url(path), **request)
            self.assertEqual(200, response.status_code, f"{key}: {response.text}")
            payload = response.json()
            self.assertTrue(observes(payload), f"{key} 到了处理器，但那一格不对：{payload}")
            self.assertNotEqual(GATE_COPY, payload.get("detail"))

    # --- 工具 ------------------------------------------------------------
    def _url(self, path: str) -> str:
        url = path
        for name, sample in self.PARAM_SAMPLES.items():
            url = url.replace("{" + name + "}", sample)
        return url

    def _arm(self, route: APIRoute, route_key: str) -> None:
        """给这条路由上绊线桩（实现见 `_arm_tripwire`），并记下桩本身用于派发核对。"""
        self.stub_of[id(route)] = _arm_tripwire(self, route, route_key, self.tripped)

    def _attempt(self, method: str, url: str) -> tuple[int, object]:
        """发一条真请求，把 `(状态码, detail)` 原样交回调用方——诊断不许在这儿被吞掉。"""
        request: dict[str, object] = {"headers": _bearer(self.token)}
        if method in {"POST", "PUT", "PATCH"}:
            # 空 body 是刻意的：403 必须先于请求体校验发生，门的顺序才没有被"先 422"顶掉的可能。
            request["json"] = {}
        response = self.client.request(method, url, **request)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        detail = payload.get("detail") if isinstance(payload, dict) else response.text[:200]
        return response.status_code, detail

    def test_the_gate_copy_wins_over_a_missing_permission(self):
        """门排在权限判定**之前**：既没改密又缺权限的账号拿到的是门那句中文。

        扫描用的身份是 ADMIN（权限满格），所以"先授权、后门"的重排在那 41 格里一格都不会变
        ——这一枚补的正是那一格：换成 VIEWER 去打只有 ADMIN 能打的 `POST /api/demo/reset`。
        它同时也是"扫描不许碰真处理器"的又一枚证据：这条路由上了桩、demo 入口设了哨。
        """
        key = "POST /api/demo/reset"
        route = _route_index(_predicate_using(auth.require_permissions)).get(key)
        self.assertIsNotNone(route, f"{key} 不在权限族的覆盖面里：枚举或路由表已经变了")
        self._arm(route, key)
        user_store.create_argon2("underr", plain_password=GOOD_PASSWORD, must_change=True)
        identity = _identity("underr", role="VIEWER")
        with directory.override_identities({"gated": self.identity, "underr": identity}):
            token = auth.issue_token(auth._user_from(identity, None))
            blocked = self.client.post(key.split(" ", 1)[1], json={}, headers=_bearer(token))
        self.assertEqual(403, blocked.status_code, blocked.text)
        self.assertEqual(GATE_COPY, blocked.json()["detail"])
        self.assertNotIn("缺少权限", blocked.text, "门的文案被权限文案顶掉了")
        self.assertEqual([], self.tripped, "处理器可达：这条用例正打在会删数据的那条腿上")
        self.assertEqual(0, self.demo_sentinels["reset_demo"].call_count)
        self.assertEqual(
            1,
            sum(
                1 for event in self.events()
                if (event["action"], event["status"], event["detail"])
                == ("AUTHORIZATION", "DENIED", "password_change_required")
            ),
            "门挡下的这一条也得在审计里留一笔",
        )

    def test_a_gate_denial_writes_the_enum_token_to_the_audit_face(self):
        """覆盖面之外再钉一格**值**：门放行的是审计 token，响应面只有中文。

        这里同样先上桩：本例判的是依赖层给出的那一笔，业务函数在不在场都不影响结论，而"门
        退化那次跑"少一个能到得了的处理器就少一处外部依赖。
        """
        key = "GET /api/knowledge-bases"
        route = _route_for(key)
        self.assertIsNotNone(route, f"{key} 不在路由表上：本例的判据对象没了")
        self._arm(route, key)
        blocked = self.client.get("/api/knowledge-bases", headers=_bearer(self.token))
        self.assertEqual(403, blocked.status_code, blocked.text)
        self.assertEqual(GATE_COPY, blocked.json()["detail"])
        self.assertEqual([], self.tripped, "处理器可达：本例不必叫到业务层就能判")
        self.assertEqual(
            [("AUTHORIZATION", "DENIED", "password_change_required")],
            [
                (e["action"], e["status"], e["detail"])
                for e in self.events()
                if e["action"] == "AUTHORIZATION"
            ],
        )


# ---------------------------------------------------------------------------
# 口令策略 / 自助改密 / 管理员重置 / 凭据运维面（§8.6 / §8.7 / §8.8）
# ---------------------------------------------------------------------------

#: §8.8 的三条长度/回声判据在 HTTP 面上的那一句中文（422 的展示面）。
COPY_TOO_SHORT = "新口令长度需在 12 到 128 个字符之间"
COPY_SAME_AS_USERNAME = "新口令不得与账号名相同"
COPY_BAD_CREDENTIALS = "用户名或密码错误"
COPY_NO_ACCOUNT = "账号不存在"
AUDIT_PASSWORD_CHANGED = "password_changed"
AUDIT_RESET_BY_ADMIN = "password_reset_by_admin"
AUDIT_BOOTSTRAP = "credential_bootstrap"


def _seed_legacy_admin(user_store_module: object, auth_module: object) -> None:
    """把 admin 的那一行换成 legacy(sha256) 出身并置门——升级路径的**起点**形状。

    先删后种是必须的：`import_legacy_digest` 带 `ON CONFLICT DO NOTHING`，行已在场时它一根
    手指都不碰（那是迁移器 `only_missing` 口径的下半），于是"种成 legacy"会静默变成"留着
    argon2 行"，这条用例从此永远绿。
    两个模块参数按调用形状留着并当场核对：本例判的是登录腿会不会把 legacy 行升上去，种行的
    人与读行的人必须是同一对模块对象——reload 把两边劈开时，红要红在夹具上而不是红在断言上。
    """
    if auth_module is not auth or user_store_module is not user_store:
        raise AssertionError("_seed_legacy_admin 只认本文件导入的那一对模块对象")
    user_store.delete_record("admin")
    user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)


def _identity_file_bytes() -> dict[str, bytes | None]:
    """两份身份文件的当前字节（不在场 ⇒ None）。

    `directory` 的路径常量是**相对**的（部署口径，镜像 WORKDIR 就是 `backend/`，不许改绝对），
    而本套件按两种 cwd 跑：从仓库根起那条相对路径指向不存在的位置。这里按
    `conftest.shipped_identity_files` 的同一手法锚到 `BACKEND_DIR` 上再读，否则"CLI 不改身份
    文件"这条判据会在其中一种 cwd 下先把用例自己判死。
    """
    snapshot: dict[str, bytes | None] = {}
    for path in (directory.ENTERPRISE_IDENTITIES_FILE, directory.DEMO_IDENTITIES_FILE):
        target = path if path.is_absolute() else BACKEND_DIR / path
        snapshot[str(path)] = target.read_bytes() if target.exists() else None
    return snapshot


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    """跑一次 CLI，把 `(exit_code, stdout, stderr)` 一起交回来。

    口令的正确性判据全都落在这三格里：口令**不许**出现在任何一格，所以捕获必须是原文而不是
    "只看退出码"。
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class _ClientCase(_LongJwtSecret, _AuditToTempFile, unittest.TestCase):
    """HTTP 腿与 CLI 腿的共同地基：每例一份临时库、三行 demo 凭据、一个 client。

    只种 admin / viewer / hr01：`sales01` 与 `user` 刻意**留空**——它们是"有身份无凭据行"
    那条腿的判据对象，bootstrap 与管理员重置要在它们身上**新建**（`create_argon2` 那一支），
    而不是撞进一次 `CredentialStoreError`。
    """

    def setUp(self):
        super().setUp()
        _fresh_db(self)
        ensure_demo_credentials("admin", "viewer", "hr01")
        self.client = TestClient(app)

    def _login(self, username: str, password: str):
        return self.client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )

    def _headers(self, username: str, password: str) -> dict[str, str]:
        response = self._login(username, password)
        self.assertEqual(200, response.status_code, response.text)
        return _bearer(response.json()["access_token"])

    def _admin_headers(self) -> dict[str, str]:
        return self._headers("admin", "admin123")

    def _post(self, path: str, body: dict[str, str], headers: dict[str, str]):
        return self.client.post(path, json=body, headers=headers)


class PasswordPolicyTests(_ClientCase):
    #: 长度下界的两侧（11/12）与上界的两侧（128/129）都在这里，判据是**函数**而不是文案：
    #: 文案归 §9.1 的展示面管，边界归策略管，两处混判就会出现"改了字就以为改了规则"。
    POLICY_CASES: tuple[tuple[str, str, bool], ...] = (
        ("someone", "l" * 11, False),
        ("someone", "l" * 12, True),
        ("someone", "l" * 128, True),
        ("someone", "l" * 129, False),
        ("admin", "ADMIN", False),
        ("admin", "AdMiN", False),
        ("admin", "admin", False),
    )

    def test_short_passwords_and_username_echo_are_rejected_with_422(self):
        """§8.8：422 是输入校验，403 是权限。混用会污染既有 RBAC 语义面。"""
        body = {"current_password": "admin123", "new_password": "abc"}
        response = self._post(
            "/api/auth/password/change", body, self._admin_headers()
        )
        self.assertEqual(422, response.status_code, response.text)
        # 展示面是中文：422 由策略判出，不是 pydantic 那句英文（见 `PasswordChangeRequest`）。
        self.assertEqual(COPY_TOO_SHORT, response.json()["detail"])
        for candidate in ("admin", "ADMIN", "AdMiN"):
            self.assertIsNotNone(auth.validate_new_password("admin", candidate))
        self.assertIsNone(auth.validate_new_password("admin", "a-good-new-password 123"))

    def test_policy_accepts_a_12_char_and_rejects_a_129_char_password(self):
        self.assertIsNone(auth.validate_new_password("someone", "l" * 12))
        self.assertIsNotNone(auth.validate_new_password("someone", "l" * 129))

    def test_the_policy_boundaries_are_exactly_the_ones_the_spec_names(self):
        for username, password, accepted in self.POLICY_CASES:
            with self.subTest(length=len(password), username=username):
                reason = auth.validate_new_password(username, password)
                if accepted:
                    self.assertIsNone(reason)
                else:
                    self.assertIsNotNone(reason)

    def test_a_new_password_that_echoes_a_long_username_is_rejected_with_422_copy(self):
        """回声规则在 HTTP 面上的形状：它排在长度**之后**，所以判据账号名得够 12 字符。

        取一个长账号名不是绕路：`admin` 的任何 casefold 等值串都短于下界，那条规则在短名账号
        上永远轮不到发言——只看函数级判据会把它当成"已经生效"，而它在真请求上先被长度挡掉。
        """
        name = "operations-lead-01"
        identity = _identity(name, role="ADMIN")
        user_store.create_argon2(name, plain_password=GOOD_PASSWORD, must_change=False)
        with directory.override_identities({**dict(directory.identities()), name: identity}):
            headers = self._headers(name, GOOD_PASSWORD)
            response = self._post(
                "/api/auth/password/change",
                {"current_password": GOOD_PASSWORD, "new_password": name.upper()},
                headers,
            )
        self.assertEqual(422, response.status_code, response.text)
        self.assertEqual(COPY_SAME_AS_USERNAME, response.json()["detail"])
        # 被拒的那一次**不写任何凭据**：策略排在写路径之前，否则"先落库再判"就把旧口令换掉了。
        self.assertEqual(1, user_store.get_record(name).credentials_version)

    def test_no_weak_password_dictionary_exists_on_the_policy_face(self):
        """SEC-A 把弱口令词典**移出**了范围：字典会在两条腿上给出不同的拒绝理由。"""
        self.assertIsNone(auth.validate_new_password("someone", "Password1!abc"))
        self.assertNotIn("弱", COPY_TOO_SHORT + COPY_SAME_AS_USERNAME)

    def test_a_rejected_change_attempt_writes_the_policy_denied_audit_event(self):
        """§9.1 两栏：422 只到展示面，`password_policy_rejected` 必须落在审计面。
        没有这一笔，脚本化地批量提交不合格新口令就追不到。"""
        response = self._post(
            "/api/auth/password/change",
            {"current_password": "admin123", "new_password": "abc"},
            self._admin_headers(),
        )
        self.assertEqual(422, response.status_code, response.text)
        self.assertEqual(
            [("PASSWORD", "DENIED", "password_policy_rejected")],
            [
                (e["action"], e["status"], e["detail"])
                for e in self.events()
                if e.get("detail") == "password_policy_rejected"
            ],
        )
        self.assertNotIn("abc", json.dumps(self.events(), ensure_ascii=False))


class SelfServiceChangeTests(_ClientCase):
    CHANGE_PATH = "/api/auth/password/change"

    def _change(self, headers: dict[str, str], *, current: str, new: str):
        return self._post(
            self.CHANGE_PATH,
            {"current_password": current, "new_password": new},
            headers,
        )

    def test_changing_password_logs_in_clears_the_gate_and_kills_old_tokens(self):
        """SECA-03 半边 B：升级路径的终态是"改完密就能正常用"。"""
        _seed_legacy_admin(user_store, auth)
        login = self._login("admin", "admin123")
        self.assertTrue(login.json()["password_change_required"])
        old = _bearer(login.json()["access_token"])
        blocked = self.client.get("/api/knowledge-bases", headers=old)
        self.assertEqual((403, GATE_COPY), (blocked.status_code, blocked.json()["detail"]))

        changed = self._change(old, current="admin123", new=NEW_PASSWORD)
        self.assertEqual(200, changed.status_code, changed.text)
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, user_store.get_record("admin").algorithm)
        self.assertFalse(user_store.get_record("admin").must_change)
        # 旧 token 已经随着凭据纪元 bump 出局（§7.5 的撤销通道），"改完密就能用"这一句只能由
        # 响应里那枚**新** token 兑现——少了它，走完强制改密流程的人被弹回登录页。
        self.assertEqual(
            (401, INVALID_TOKEN),
            (
                self.client.get("/api/knowledge-bases", headers=old).status_code,
                self.client.get("/api/knowledge-bases", headers=old).json()["detail"],
            ),
        )
        fresh = _bearer(changed.json()["access_token"])
        self.assertEqual(200, self.client.get("/api/knowledge-bases", headers=fresh).status_code)
        self.assertFalse(self.client.get("/api/auth/me", headers=fresh).json()["password_change_required"])

    def test_the_change_response_shape_is_pinned_and_carries_no_password(self):
        """响应面：一枚活 token + 两枚机器可读布尔键，零口令、零 hash、零长度。"""
        token = self._login("admin", "admin123").json()["access_token"]
        changed = self._change(_bearer(token), current="admin123", new=NEW_PASSWORD)
        body = changed.json()
        self.assertEqual(
            {"changed", "access_token", "token_type", "password_change_required"}, set(body)
        )
        self.assertIs(True, body["changed"])
        self.assertIs(False, body["password_change_required"], "改完密还报 True = 门与表劈叉")
        self.assertIsInstance(body["access_token"], str)
        self.assertNotEqual(token, body["access_token"], "回手交出旧 token：撤销没生效")
        self.assertEqual("bearer", body["token_type"])
        self.assertNotIn("admin123", changed.text)
        self.assertNotIn(NEW_PASSWORD, changed.text)
        self.assertNotIn("$argon2", changed.text)
        # 新 token 的版本号必须与表一致（旧 token 的 cv 已经死了，靠的是这一格）。
        self.assertEqual(
            user_store.get_record("admin").credentials_version,
            _decode(body["access_token"])[auth.CREDENTIAL_VERSION_CLAIM],
        )

    def test_changing_requires_the_current_password(self):
        headers = self._admin_headers()
        response = self._change(
            headers, current="not-my-password 123", new=NEW_PASSWORD
        )
        self.assertEqual(401, response.status_code, response.text)
        self.assertEqual(COPY_BAD_CREDENTIALS, response.json()["detail"])
        # 展示面是中文文案，审计面是枚举 token（规格 §9.1 的两栏模型）。
        from app.audit import recent_events

        self.assertEqual("invalid_credentials", recent_events(limit=1)[0]["detail"])
        self.assertEqual(1, user_store.get_record("admin").credentials_version)
        self.assertEqual(1, user_store.get_record("admin").failed_attempts)

    def test_the_change_leg_shares_the_login_lockout_state_rather_than_a_second_counter(self):
        """改密腿带旧口令校验 ⇒ 它与登录是**同一个**爆破面（SECA-07 的键只有 username）。

        这一枚只钉"共用"这件事本身：把账号锁住之后改密腿给出的必须是登录腿那一条 401 文案 +
        `AUTH_LOGIN_LOCKED` token，而不是自造的第二套状态（两把计数器等于给攻击者留一条不被记录的通道）。
        """
        headers = self._admin_headers()
        user_store.record_login_failure("admin", max_attempts=1, lock_seconds=900)
        response = self._change(headers, current="admin123", new=NEW_PASSWORD)
        self.assertEqual(401, response.status_code, response.text)
        self.assertEqual(COPY_BAD_CREDENTIALS, response.json()["detail"])
        from app.audit import recent_events

        self.assertEqual("AUTH_LOGIN_LOCKED", recent_events(limit=1)[0]["detail"])
        record = user_store.get_record("admin")
        self.assertEqual(1, record.credentials_version, "锁定期里口令被换掉了")
        self.assertIsNotNone(record.locked_until)

    def test_the_change_leg_needs_a_token_and_sits_on_the_pending_side(self):
        """免门**不免身份**：没有 token 进来就是 401，与 `/me` 同一条腿。"""
        anonymous = self.client.post(
            self.CHANGE_PATH,
            json={"current_password": "admin123", "new_password": NEW_PASSWORD},
        )
        self.assertEqual(401, anonymous.status_code, anonymous.text)
        self.assertEqual("请先登录", anonymous.json()["detail"])
        # 门后的账号改得了自己的密（这正是它在白名单里的理由）。
        user_store.set_password_argon2("admin", plain_password=NEW_PASSWORD, must_change=True)
        gate = self._login("admin", NEW_PASSWORD).json()["access_token"]
        changed = self._change(_bearer(gate), current=NEW_PASSWORD, new=GOOD_PASSWORD)
        self.assertEqual(200, changed.status_code, changed.text)
        self.assertFalse(user_store.get_record("admin").must_change)

    def test_a_successful_change_leaves_the_enum_audit_token_and_no_password(self):
        headers = self._admin_headers()
        self.assertEqual(200, self._change(headers, current="admin123", new=NEW_PASSWORD).status_code)
        events = self.events()
        self.assertEqual(
            [("PASSWORD", "SUCCESS", AUDIT_PASSWORD_CHANGED)],
            [
                (e["action"], e["status"], e["detail"])
                for e in events
                if e["action"] == "PASSWORD"
            ],
        )
        self.assertNotIn(NEW_PASSWORD, json.dumps(events, ensure_ascii=False))
        self.assertNotIn("admin123", json.dumps(events, ensure_ascii=False))


class AdminResetTests(_ClientCase):
    def _reset(self, username: str, headers: dict[str, str], *, new: str):
        return self._post(f"/api/admin/users/{username}/password/reset", {"new_password": new}, headers)

    def test_reset_requires_the_operate_capability(self):
        viewer = self._headers("viewer", "viewer123")
        response = self._reset("hr01", viewer, new=NEW_PASSWORD)
        self.assertEqual(403, response.status_code, response.text)
        self.assertIn("system:operate", response.json()["detail"])
        self.assertEqual(1, user_store.get_record("hr01").credentials_version, "被拒的 reset 动了凭据")

    def test_admin_reset_clears_a_stale_lock_in_the_same_transaction(self):
        """SECA-12：reset 之后用户仍被旧 lock 挡住，是一条必被观测到的事故形态。"""
        user_store.record_login_failure("hr01", max_attempts=1, lock_seconds=900)
        self.assertIsNotNone(user_store.get_record("hr01").locked_until)
        response = self._reset("hr01", self._admin_headers(), new=NEW_PASSWORD)
        self.assertEqual(200, response.status_code, response.text)
        record = user_store.get_record("hr01")
        self.assertIsNone(record.locked_until)
        self.assertEqual(0, record.failed_attempts)
        self.assertTrue(record.must_change)
        self.assertEqual(2, record.credentials_version)
        login = self._login("hr01", NEW_PASSWORD)
        self.assertEqual(200, login.status_code, login.text)
        self.assertTrue(login.json()["password_change_required"])

    def test_reset_forces_the_gate_while_a_self_change_clears_it(self):
        """两个方向同场对照：管理员交出去的是"这口令不是你的"，自助交出去的是"改完了"。

        把两处的 `must_change` 实参写成同一个值，本例的两格各红一次——这是这一版唯一一处
        "同一个写路径、两种意图"的地方，所以判据必须成对出现在同一个用例里。
        """
        headers = self._admin_headers()
        self.assertEqual(
            200, self._reset("hr01", headers, new=NEW_PASSWORD).status_code
        )
        self.assertTrue(user_store.get_record("hr01").must_change, "reset 没置门")
        login = self._login("hr01", NEW_PASSWORD).json()
        self.assertTrue(login["password_change_required"])
        changed = self.client.post(
            "/api/auth/password/change",
            json={"current_password": NEW_PASSWORD, "new_password": GOOD_PASSWORD},
            headers=_bearer(login["access_token"]),
        )
        self.assertEqual(200, changed.status_code, changed.text)
        self.assertFalse(user_store.get_record("hr01").must_change, "自助改密没关门")

    def test_reset_never_echoes_the_password_and_404s_an_unknown_identity(self):
        """404 留给已鉴权管理员的资源面：登录腿才是枚举面，这里不构成新的一条（§9.1 裁定）。"""
        response = self._reset("ghost", self._admin_headers(), new=NEW_PASSWORD)
        self.assertEqual(404, response.status_code, response.text)
        self.assertEqual(COPY_NO_ACCOUNT, response.json()["detail"])
        self.assertIsNone(user_store.get_record("ghost"))
        ok = self._reset("hr01", self._admin_headers(), new=NEW_PASSWORD)
        self.assertEqual({"reset", "must_change"}, set(ok.json()))
        self.assertNotIn(NEW_PASSWORD, ok.text)
        self.assertNotIn("$argon2", ok.text)

    def test_reset_of_an_identity_without_a_row_creates_one_at_version_one(self):
        """`provision_credentials` 是一条腿：无行新建、有行 bump，两个分支共用一个入口。"""
        self.assertIsNone(user_store.get_record("sales01"))
        response = self._reset("sales01", self._admin_headers(), new=NEW_PASSWORD)
        self.assertEqual(200, response.status_code, response.text)
        record = user_store.get_record("sales01")
        self.assertEqual(1, record.credentials_version)
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, record.algorithm)
        self.assertTrue(record.must_change)
        login = self._login("sales01", NEW_PASSWORD)
        self.assertTrue(login.json()["password_change_required"])

    def test_reset_rejects_a_weak_new_password_before_touching_the_target(self):
        response = self._reset("hr01", self._admin_headers(), new="abc")
        self.assertEqual(422, response.status_code, response.text)
        self.assertEqual(COPY_TOO_SHORT, response.json()["detail"])
        self.assertEqual(1, user_store.get_record("hr01").credentials_version)

    def test_a_rejected_reset_writes_the_policy_denied_audit_event(self):
        """§9.1：重置腿的策略拒绝也留 `password_policy_rejected`，与自助改密腿同 token。"""
        response = self._reset("hr01", self._admin_headers(), new="abc")
        self.assertEqual(422, response.status_code, response.text)
        self.assertEqual(
            [("PASSWORD", "DENIED")],
            [
                (e["action"], e["status"])
                for e in self.events()
                if e.get("detail") == "password_policy_rejected"
            ],
        )
        self.assertNotIn("abc", json.dumps(self.events(), ensure_ascii=False))

    def test_successful_reset_records_actor_as_username_and_recipient_as_target(self):
        """HTTP 重置事件必须有覆盖：username=actor、target=受体，两条重置腿才分得开。
        顺带钉 additivity：`target` 只在重置事件上出现，任何别的既有事件不被多塞这一个键。"""
        login = self._login("admin", "admin123")
        self.assertEqual(200, login.status_code)  # 先留一条 LOGIN 事件当 additivity 反例
        response = self._reset("hr01", self._admin_headers(), new=NEW_PASSWORD)
        self.assertEqual(200, response.status_code, response.text)
        resets = [e for e in self.events() if e.get("detail") == "password_reset_by_admin"]
        self.assertEqual(1, len(resets), resets)
        event = resets[0]
        self.assertEqual(("PASSWORD", "SUCCESS"), (event["action"], event["status"]))
        self.assertEqual("admin", event["username"], "记的应是下这道命令的管理员")
        self.assertEqual("hr01", event["target"], "受体账号必须落在 target 上")
        self.assertNotIn(NEW_PASSWORD, json.dumps(resets, ensure_ascii=False))
        for other in self.events():
            if other.get("detail") != "password_reset_by_admin":
                self.assertNotIn("target", other, "非重置事件被多塞了一个键：additivity 破了")

    def test_an_operator_can_reset_their_own_account_and_is_evicted_by_it(self):
        """自重置经管理员端点是**可接受**的形状，且必须钉住它的效果。

        不设 `username != actor` 守卫的理由是可达性等价：持 `system:operate` 的人在同主机上
        本就能用 CLI 做到同一件事，HTTP 侧拒绝只是做样子。真正兜底的是**效果**：自重置同样
        置 `must_change=1` + bump 凭据纪元 ⇒ 操作者自己那枚来路 token 也即刻出局（§7.5）。
        """
        headers = self._admin_headers()  # admin/admin123 -> token@cv=N、must_change=0
        self.assertFalse(user_store.get_record("admin").must_change)
        version_before = user_store.get_record("admin").credentials_version
        response = self._reset("admin", headers, new=NEW_PASSWORD)
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual({"reset", "must_change"}, set(response.json()))
        self.assertTrue(response.json()["must_change"], "自重置没置门")
        record = user_store.get_record("admin")
        self.assertTrue(record.must_change)
        self.assertEqual(version_before + 1, record.credentials_version)
        # 纪元 bump 撤销了**包括来路那一枚在内**的全部 token —— 操作者自己也被踢下线。
        self.assertEqual(
            (401, INVALID_TOKEN),
            (
                self.client.get("/api/knowledge-bases", headers=headers).status_code,
                self.client.get("/api/knowledge-bases", headers=headers).json()["detail"],
            ),
        )
        login = self._login("admin", NEW_PASSWORD)
        self.assertEqual(200, login.status_code, login.text)
        self.assertTrue(login.json()["password_change_required"])


class PasswordEchoGuardTests(_ClientCase):
    """§8.8 / SEC-A-002：两条新腿的输入校验错误**绝不**把提交里的口令抄进响应体。

    钉两个真实泄漏形状：① 旧版 `max_length` 由 pydantic 判超长时，默认载荷把被拒取值原样
    放进 `detail[*].input`——那正是用户刚提交的新口令；② 漏填 `new_password` 时 pydantic 的
    `missing` 错误把**同请求里的 `current_password`**（用户当下有效的那枚口令）整份带进 input。
    两条都断言"提交进请求的那枚 secret 不出现在响应字节里"，且响应面没有 `input` 结构。
    反向再钉一格：脱敏处理器只关在这两条腿内，既有端点（登录）的默认校验载荷逐字节不变。
    """

    def test_change_with_oversized_password_does_not_echo_the_secret(self):
        headers = self._admin_headers()
        secret = "o" * 200
        response = self.client.post(
            "/api/auth/password/change",
            json={"current_password": "admin123", "new_password": secret},
            headers=headers,
        )
        self.assertEqual(422, response.status_code, response.text)
        self.assertEqual(COPY_TOO_SHORT, response.json()["detail"])
        self.assertNotIn(secret, response.text)
        self.assertNotIn(secret.encode("utf-8"), response.content)
        self.assertNotIn("input", response.text, "pydantic 的 input 回显结构漏进来了")

    def test_change_missing_new_password_does_not_echo_current_password(self):
        headers = self._admin_headers()
        current = "the-user-current-password 123"
        response = self.client.post(
            "/api/auth/password/change",
            json={"current_password": current},
            headers=headers,
        )
        self.assertEqual(422, response.status_code, response.text)
        self.assertNotIn(current, response.text)
        self.assertNotIn(current.encode("utf-8"), response.content)
        self.assertNotIn("input", response.text)

    def test_reset_oversized_and_missing_new_password_do_not_echo(self):
        headers = self._admin_headers()
        secret = "r" * 200
        over = self.client.post(
            "/api/admin/users/hr01/password/reset",
            json={"new_password": secret},
            headers=headers,
        )
        self.assertEqual(422, over.status_code, over.text)
        self.assertNotIn(secret, over.text)
        self.assertNotIn(secret.encode("utf-8"), over.content)
        self.assertNotIn("input", over.text)
        missing = self.client.post(
            "/api/admin/users/hr01/password/reset", json={}, headers=headers
        )
        self.assertEqual(422, missing.status_code, missing.text)
        self.assertNotIn("input", missing.text)

    def test_existing_login_validation_payload_shape_is_unchanged(self):
        """反向钉：非新腿端点仍走 FastAPI 默认载荷（`detail[0]` 带 loc/input/msg/type）。
        若脱敏是全局的、把 input 一并抹了，这一格先红——它守的是"改动不外溢"这条边界。"""
        secret = "z" * 200
        response = self.client.post(
            "/api/auth/login", json={"username": "admin", "password": secret}
        )
        self.assertEqual(422, response.status_code, response.text)
        detail = response.json()["detail"]
        self.assertEqual(["body", "password"], detail[0]["loc"])
        self.assertIn("input", detail[0], "既有端点的默认校验形状被改动了")
        self.assertEqual(secret, detail[0]["input"])


class CliTests(_ClientCase):
    def test_bootstrap_requires_a_preexisting_identity_and_never_creates_one(self):
        """SEC-A-010：bootstrap 只写凭据，身份文件不因 CLI 而改变。"""
        before = _identity_file_bytes()
        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: NEW_PASSWORD}):
            code, out, err = _run_cli(["credentials", "bootstrap-admin", "--username", "ghost"])
        self.assertEqual(2, code, f"out={out!r} err={err!r}")
        self.assertIsNone(user_store.get_record("ghost"))
        self.assertEqual(before, _identity_file_bytes())
        self.assertNotIn(NEW_PASSWORD, out + err)

    def test_the_cli_never_accepts_a_password_on_argv(self):
        """SECA-02：argv 会被 ps 与 shell history 观察到。"""
        parser = cli.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                ["credentials", "bootstrap-admin", "--username", "admin", "--password", "x"]
            )
        # 翻 `--help` 文本只会被措辞漂移骗过去，这里判的是 argparse 的**行为**：未定义选项即拒。
        with self.assertRaises(SystemExit):
            parser.parse_args(["credentials", "reset", "--username", "admin", "--pwd", "x"])
        # 行为之外再钉两格结构：命名空间里连一个能装口令的槽位都不该有。`--password` 一旦被
        # 改名成 `-p`（dest="p"）这种绕法，骗得过 `hasattr(args,"password")`，骗不过"dest 全集 ⊆ 白名单"。
        args = parser.parse_args(["credentials", "reset", "--username", "admin"])
        self.assertEqual("reset", args.action)
        self.assertFalse(hasattr(args, "password"), "命名空间里多了一枚口令槽位")
        # 闭集：解析出的 dest 只允许 {command, action, username}（外加 argparse 可能带的 help）。
        # 任何新增 dest——含把口令改名落到 `p` 上——都在这里红，而不是静默多出一个能装凭据材料的槽位。
        self.assertLessEqual(
            set(vars(args)),
            {"command", "action", "username", "help"},
            "命名空间多出白名单外的 dest：可能是被改名的口令参数",
        )

    def test_migration_status_reports_the_legacy_count(self):
        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: NEW_PASSWORD}):
            code, out, err = _run_cli(["credentials", "migration-status"])
        self.assertEqual(0, code, f"out={out!r} err={err!r}")
        self.assertIn("legacy_count=0", out)
        self.assertIn("argon2id_count=3", out)
        user_store.delete_record("sales01")
        user_store.import_legacy_digest("sales01", LEGACY_ADMIN, must_change=True)
        code, out, err = _run_cli(["credentials", "migration-status"])
        self.assertEqual(0, code, f"out={out!r} err={err!r}")
        self.assertIn("legacy_count=1", out)
        self.assertIn("sales01", out)
        self.assertNotIn(LEGACY_ADMIN, out, "digest 被打印出来了")

    def test_migration_status_derives_last_login_and_prints_updated_at(self):
        """§8.7：逐账号带派生的最后成功登录时间与凭据行 `updated_at`；审计里没有 ⇒ `-`。
        派生不加 schema 列（progress 裁定），从既有审计面取，手法同 `knowledge_os` 名册。"""
        from app.audit import record_event

        # admin 与 viewer 都在 setUp 里 create_argon2（各有一行凭据），只给 admin 记一次成功登录。
        record_event(username="admin", role="ADMIN", action="LOGIN", status="SUCCESS")
        code, out, err = _run_cli(["credentials", "migration-status"])
        self.assertEqual(0, code, f"out={out!r} err={err!r}")
        lines = {
            line.split("\t")[0]: line
            for line in out.splitlines()
            if line.split("\t")[0] in {"admin", "viewer"}
        }
        admin_line = lines["admin"]
        self.assertIn("updated_at=", admin_line)
        self.assertNotIn("last_login=-", admin_line, "有成功登录却派生不出时间")
        self.assertIn("last_login=20", admin_line)  # ISO-8601 UTC，年份打头
        viewer_line = lines["viewer"]
        self.assertIn("last_login=-", viewer_line, "从未成功登录的账号该打印 `-`")
        self.assertIn("updated_at=", viewer_line)
        self.assertNotIn(NEW_PASSWORD, out)
        self.assertNotIn(LEGACY_ADMIN, out)

    def test_bootstrap_writes_an_argon2_row_for_the_identity_that_has_none(self):
        """新建分支：`sales01` 有身份无凭据行 ⇒ bootstrap 产出 v1 的 argon2id 行。"""
        self.assertIsNone(user_store.get_record("sales01"))
        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: NEW_PASSWORD}):
            code, out, err = _run_cli(["credentials", "bootstrap-admin", "--username", "sales01"])
        self.assertEqual(0, code, f"out={out!r} err={err!r}")
        record = user_store.get_record("sales01")
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, record.algorithm)
        self.assertEqual(1, record.credentials_version)
        self.assertFalse(record.must_change, "bootstrap 造的是一个可用账号，不是待改密账号")
        self.assertNotIn(NEW_PASSWORD, out + err)
        self.assertNotIn("$argon2", out + err)

    def test_cli_reset_clears_a_stale_lock_and_leaves_the_gate_open(self):
        """SECA-12 的 CLI 半边：走的是同一条写路径，判据也必须在真进程面上重做一遍。"""
        user_store.record_login_failure("hr01", max_attempts=1, lock_seconds=900)
        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: NEW_PASSWORD}):
            code, out, err = _run_cli(["credentials", "reset", "--username", "hr01"])
        self.assertEqual(0, code, f"out={out!r} err={err!r}")
        record = user_store.get_record("hr01")
        self.assertIsNone(record.locked_until)
        self.assertEqual(0, record.failed_attempts)
        self.assertTrue(record.must_change)
        self.assertEqual(2, record.credentials_version)
        self.assertNotIn(NEW_PASSWORD, out + err)
        login = self._login("hr01", NEW_PASSWORD)
        self.assertEqual(200, login.status_code, login.text)
        self.assertTrue(login.json()["password_change_required"])

    def test_an_absent_or_too_short_env_password_is_refused_without_echoing_the_value(self):
        """"env 没设" 与 "env 太短" 给同一句可执行提示，且两句里都没有口令本体。"""
        with mock.patch.dict(os.environ):
            os.environ.pop(cli.PASSWORD_ENV_VAR, None)
            absent = _run_cli(["credentials", "bootstrap-admin", "--username", "admin"])
        too_short = "abc"
        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: too_short}):
            short = _run_cli(["credentials", "bootstrap-admin", "--username", "admin"])
        self.assertEqual(2, absent[0], absent)
        self.assertEqual(2, short[0], short)
        self.assertEqual(absent[2], short[2], "两种输入形状给了两句不同的话：运维读不出该做什么")
        self.assertIn(cli.PASSWORD_ENV_VAR, absent[2])
        self.assertNotIn(too_short, short[1] + short[2])
        self.assertEqual(1, user_store.get_record("admin").credentials_version)

    def test_the_cli_writes_the_enum_audit_token_and_no_password(self):
        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: NEW_PASSWORD}):
            self.assertEqual(0, _run_cli(["credentials", "bootstrap-admin", "--username", "admin"])[0])
            # 用完即弹：这一格之后本进程的环境里不该再有那枚变量（后续 print、异常栈、
            # 任何被 exec 的子进程都不该拿到它）。也正因为它被弹掉了，第二条命令必须重新给 env——
            # 少给一次这里就红，"弹"这件事因此不是只写在注释里的承诺。
            self.assertNotIn(cli.PASSWORD_ENV_VAR, os.environ, "口令还留在 environ 里")
        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: NEW_PASSWORD}):
            self.assertEqual(0, _run_cli(["credentials", "reset", "--username", "hr01"])[0])
        events = self.events()
        self.assertEqual(
            [("PASSWORD", "SUCCESS", AUDIT_BOOTSTRAP), ("PASSWORD", "SUCCESS", AUDIT_RESET_BY_ADMIN)],
            [(e["action"], e["status"], e["detail"]) for e in events if e["action"] == "PASSWORD"],
        )
        self.assertNotIn(NEW_PASSWORD, json.dumps(events, ensure_ascii=False))
        self.assertEqual("ADMIN", [e["role"] for e in events if e["action"] == "PASSWORD"][0])

    def test_cli_policy_rejection_writes_the_denied_audit_event(self):
        """CLI 腿的 §9.1 半边：不合格新口令同样给 `password_policy_rejected`。
        取 129 字符——既过 `_password_from_env` 的 12 下界、又撞 `validate_new_password` 的 128 上界，
        于是这条腿真走到策略拒绝那一支（"abc" 会先被 env 下界挡在门外、根本到不了这里）。"""
        too_long = "a" * 129
        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: too_long}):
            code, out, err = _run_cli(["credentials", "reset", "--username", "hr01"])
        self.assertEqual(2, code, f"out={out!r} err={err!r}")
        self.assertEqual(
            [("PASSWORD", "DENIED", "hr01")],
            [
                (e["action"], e["status"], e["username"])
                for e in self.events()
                if e.get("detail") == "password_policy_rejected"
            ],
        )
        self.assertNotIn(too_long, json.dumps(self.events(), ensure_ascii=False))
        self.assertEqual(1, user_store.get_record("hr01").credentials_version)

    def test_cli_reset_records_the_recipient_in_target(self):
        """CLI 重置也落 `target`（无独立 actor，username 与 target 同指受体），
        好让 audit.jsonl 里两条重置腿用同一个字段口径辨"谁被重置过"。"""
        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: NEW_PASSWORD}):
            code, out, err = _run_cli(["credentials", "reset", "--username", "hr01"])
        self.assertEqual(0, code, f"out={out!r} err={err!r}")
        resets = [e for e in self.events() if e.get("detail") == "password_reset_by_admin"]
        self.assertEqual(1, len(resets), resets)
        self.assertEqual("hr01", resets[0]["target"])
        self.assertEqual("hr01", resets[0]["username"], "CLI 无 actor，username 即受体")
        self.assertNotIn(NEW_PASSWORD, json.dumps(self.events(), ensure_ascii=False))

    def test_an_action_missing_from_the_intent_table_is_refused_not_crashed(self):
        """未来的第四个动作没进 `_MUST_CHANGE_BY_ACTION` 那一臂：CLI 以退出码 3 点名拒绝，
        而不是崩一个 `KeyError` 栈、也不静默取某个默认值（"重置却忘置门"就是这么漏的）。
        用临时摘掉 reset 的映射来复现那条守卫臂，不碰真解析器。"""
        with mock.patch.dict(cli._MUST_CHANGE_BY_ACTION, clear=False) as patched:
            del patched["reset"]
            with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: NEW_PASSWORD}):
                code, out, err = _run_cli(["credentials", "reset", "--username", "hr01"])
        self.assertEqual(3, code, f"out={out!r} err={err!r}")
        self.assertNotIn(NEW_PASSWORD, out + err)
        self.assertEqual(1, user_store.get_record("hr01").credentials_version, "守卫触发前不该已写库")

    def test_credentials_actions_do_not_change_the_enable_state_in_the_identity_file(self):
        """bootstrap/reset 都不碰 `enabled`（那是身份侧的事，CLI 根本没有对应动作）。
        旧写法断言输出里不含"启用/停用/enabled"三个词，几乎不可杀、也没真判到它命名的东西；
        改成钉两份身份文件的字节不变——真要翻转某个账号的 `enabled`，改动只会落在这些文件上。"""
        before = _identity_file_bytes()
        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: NEW_PASSWORD}):
            code, out, err = _run_cli(["credentials", "reset", "--username", "hr01"])
        self.assertEqual(0, code, f"out={out!r} err={err!r}")
        self.assertEqual(before, _identity_file_bytes(), "CLI 改动了身份文件里的 enabled")


class CredentialWriteFailureHttpTests(_ClientCase):
    """存储事故（`CredentialStoreError`）在两条 HTTP 写腿上必须翻成中文 500 + FAILED 审计，
    与 CLI 腿的 exit 1 对齐；此前它裸逸成一个不受控的 500。用 patch `provision_credentials`
    注入异常，不碰真写路径。"""

    def test_change_maps_credential_store_error_to_a_chinese_500(self):
        headers = self._admin_headers()
        with mock.patch(
            "app.main.provision_credentials",
            side_effect=user_store.CredentialStoreError("database is locked"),
        ):
            response = self.client.post(
                "/api/auth/password/change",
                json={"current_password": "admin123", "new_password": NEW_PASSWORD},
                headers=headers,
            )
        self.assertEqual(500, response.status_code, response.text)
        self.assertIn("凭据写入失败", response.json()["detail"])
        self.assertNotIn(NEW_PASSWORD, response.text)
        self.assertNotIn("admin123", response.text)
        self.assertEqual(
            1,
            sum(
                1 for e in self.events()
                if e["action"] == "PASSWORD" and e["status"] == "FAILED"
            ),
        )

    def test_reset_maps_credential_store_error_to_a_chinese_500(self):
        with mock.patch(
            "app.main.provision_credentials",
            side_effect=user_store.CredentialStoreError("disk full"),
        ):
            response = self.client.post(
                "/api/admin/users/hr01/password/reset",
                json={"new_password": NEW_PASSWORD},
                headers=self._admin_headers(),
            )
        self.assertEqual(500, response.status_code, response.text)
        self.assertIn("凭据写入失败", response.json()["detail"])
        self.assertNotIn(NEW_PASSWORD, response.text)


if __name__ == "__main__":
    unittest.main()

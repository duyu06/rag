"""仓外只读探针：测宿主真 app 上"顶层枚举"与"递归枚举"的集合关系。

不改仓库任何文件。用法（cwd 任意）：
    python C:/Users/zhang/AppData/Local/Temp/b0-t5-fix/probe_host_routes.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(r"E:/xiangmu/rag")
BACKEND = REPO / "backend"
TESTS = BACKEND / "tests"
for p in (str(BACKEND), str(TESTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.routing import APIRoute  # noqa: E402
import app.main_agent  # noqa: E402,F401  —— 四张 router 挂在同一个 app 实例上
from app.main import app  # noqa: E402
from app import auth  # noqa: E402

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


def keys_of(route) -> tuple[str, ...]:
    methods = sorted(set(getattr(route, "methods", set()) or ()) & set(HTTP_METHODS))
    return tuple(f"{m} {route.path}" for m in methods)


def uses_dependency(dependant, predicate) -> bool:
    for sub in dependant.dependencies:
        if predicate(sub.call) or uses_dependency(sub, predicate):
            return True
    return False


def predicate_using(target) -> callable:
    name = getattr(target, "__name__", "")
    return lambda call: (
        call is target
        or getattr(call, "__qualname__", "") == f"{name}.<locals>.dependency"
    )


# ---- 旧走法：只走顶层 APIRoute（修复前的 _route_index 形状） ----------------
def old_index() -> dict:
    index = {}
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if not isinstance(route, APIRoute) or dependant is None:
            continue
        if uses_dependency(dependant, predicate_using(auth.require_user)) or uses_dependency(
            dependant, predicate_using(auth.require_permissions)
        ):
            for key in keys_of(route):
                index[key] = route
    return index


def old_all_routes() -> list:
    return [r for r in app.routes if isinstance(r, APIRoute)]


# ---- 新走法：递归展开（修复后的形状，先在探针里验语义） ---------------------
def child_routes(node):
    if type(node).__name__ in {"Mount", "Host"}:
        return None
    router = getattr(node, "original_router", None)
    if router is not None:
        return getattr(router, "routes", None)
    children = getattr(node, "routes", None)
    return children if isinstance(children, (list, tuple)) else None


def include_prefix(node) -> str:
    ctx = getattr(node, "include_context", None)
    return str(getattr(ctx, "prefix", "") or "")


def walk(nodes, prefix=""):
    for node in nodes:
        here = prefix + include_prefix(node)
        children = child_routes(node)
        if children is None:
            yield node, here
        else:
            yield from walk(children, here)


def new_all_routes() -> list:
    return [n for n, _prefix in walk(app.routes) if isinstance(n, APIRoute)]


def new_index() -> dict:
    index = {}
    for route, prefix in walk(app.routes):
        dependant = getattr(route, "dependant", None)
        if not isinstance(route, APIRoute) or dependant is None:
            continue
        if uses_dependency(dependant, predicate_using(auth.require_user)) or uses_dependency(
            dependant, predicate_using(auth.require_permissions)
        ):
            for key in keys_of(route):
                index[f"{key.split(' ', 1)[0]} {prefix}{key.split(' ', 1)[1]}"] = route
    return index


top_types = sorted({type(r).__name__ for r in app.routes})
print("top-level route type census:", top_types)
print("len(app.routes) top level   :", len(app.routes))

old_all = old_all_routes()
new_all = new_all_routes()
old_idx = old_index()
new_idx = new_index()
print("APIRoute objects  old walk  :", len(old_all))
print("APIRoute objects  new walk  :", len(new_all))
print("enumerated keys   old walk  :", len(old_idx))
print("enumerated keys   new walk  :", len(new_idx))
missing = sorted(set(old_idx) - set(new_idx))
extra = sorted(set(new_idx) - set(old_idx))
print("old \\ new (must be empty)   :", missing)
print("new \\ old (strictly added)  :", extra)
print("SUPERSET(old <= new)        :", set(old_idx) <= set(new_idx))
print("IDENTICAL SETS              :", set(old_idx) == set(new_idx))
ids_old = {id(r) for r in old_all}
ids_new = {id(r) for r in new_all}
print("object-id superset          :", ids_old <= ids_new)

# OpenAPI 作为**独立**枚举 oracle：它的每条 operation 都必须被递归走法看见
spec = app.openapi()
ops = set()
for path, item in spec.get("paths", {}).items():
    for method in item:
        if method.upper() in HTTP_METHODS:
            ops.add(f"{method.upper()} {path}")
all_new_keys = set()
for route, prefix in walk(app.routes):
    if isinstance(route, APIRoute):
        for key in keys_of(route):
            m, p = key.split(" ", 1)
            all_new_keys.add(f"{m} {prefix}{p}")
print("openapi operations          :", len(ops))
print("recursive full-surface keys :", len(all_new_keys))
print("openapi \\ recursive (blind) :", sorted(ops - all_new_keys))
print("openapi subset of recursive :", ops <= all_new_keys)

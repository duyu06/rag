"""Fix 1 的合成路由树证明（**仓外**运行，不碰仓库任何文件）。

三件事：
  (a) 旧走法（只走顶层 APIRoute）漏掉假 `_IncludedRouter` 里的嵌套腿；
  (b) 新走法（`_walk_surfaces` 递归）看见它们；
  (c) 在宿主真 app 上，递归后的枚举集合是旧集合的**超集**（逐字计数 + 差集必须为空）。

旧走法那 8 行是从 `git show HEAD:backend/tests/test_password_lifecycle_contract.py` 的
`_route_index` 逐字抄来的，不是我自己想象的形状。
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

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402

# 被修复的那枚模块：证明用的递归 helper 就是它**本次改后**的那一份
import test_password_lifecycle_contract as plc  # noqa: E402
from app import auth  # noqa: E402


def gate_dep() -> None:  # 假装是 require_user：predicate 认它
    return None


# --------------------------------------------------------------------------
# (a)(b) 合成树：一枚顶层"看起来像 _IncludedRouter"的对象，肚子里挂着两条真腿
# --------------------------------------------------------------------------
inner_app = FastAPI()


@inner_app.get("/api/nested/one", dependencies=[Depends(gate_dep)])
def nested_one() -> dict:
    return {}


@inner_app.post("/api/nested/two", dependencies=[Depends(gate_dep)])
def nested_two() -> dict:
    return {}


@inner_app.patch("/api/nested/three", dependencies=[Depends(gate_dep)])
def nested_three() -> dict:
    return {}


class FakeIncludeContext:
    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix


class FakeDependant:
    """库在 include 时为同一枚端点**另建**的那份生效 dependant：内容与真的同、身份是新的。"""

    def __init__(self, real) -> None:
        self._real = real

    @property
    def call(self):
        return self._real.call

    @property
    def dependencies(self):
        return self._real.dependencies


class FakeEffectiveContext:
    """形状 ①：`_EffectiveRouteContext` —— 路径已含 include 前缀 + 自带生效 dependant。"""

    def __init__(self, original_route, prefix: str) -> None:
        self.original_route = original_route
        self.path = prefix + original_route.path
        self.methods = set(getattr(original_route, "methods", set()) or ())
        self.dependant = FakeDependant(original_route.dependant)


class FakeIncludedRouter:
    """行为照 `fastapi/routing.py::_IncludedRouter`（0.141.1）：
    顶层只挂这一枚，子表在 `original_router.routes` 里；它自己**没有** path / methods /
    dependant —— 所以旧走法的 isinstance(APIRoute) 直接跳过它，容器那格的
    `off_enumeration` 也因为 `methods is None` 把它判成"带着服务面而枚举不覆盖"。
    """

    def __init__(self, original_router, include_context=None, with_candidates=False):
        self.original_router = original_router
        self.include_context = include_context or FakeIncludeContext()
        self._with_candidates = with_candidates

    def effective_candidates(self):  # 形状 ①：库给的"生效子条目"
        if not self._with_candidates:
            return []
        prefix = self.include_context.prefix
        return [
            FakeEffectiveContext(route, prefix)
            for route in self.original_router.routes
            if isinstance(route, APIRoute)
        ]


def old_route_index_from_HEAD(nodes, predicate):
    """HEAD 版的 `_route_index` 逐字（只走顶层）。"""
    index = {}
    for route in nodes:
        dependant = getattr(route, "dependant", None)
        if not isinstance(route, APIRoute) or dependant is None:
            continue
        if plc._uses_dependency(dependant, predicate):
            for key in plc._route_keys(route):
                index[key] = route
    return index


predicate = lambda call: call is gate_dep  # noqa: E731

print("=" * 72)
print("形状 ②（原始子表 original_router.routes，无 include 前缀）")
top = list(inner_app.routes)
node = FakeIncludedRouter(inner_app)          # 肚子里 3 条腿
mixed = [top[0], node]                        # 顶层：1 条真腿 + 1 枚 include 条目
old = old_route_index_from_HEAD(mixed, predicate)
new = {}
for surface in plc._walk_surfaces(mixed):
    if surface["route"] is None or not surface["dependants"]:
        continue
    if any(plc._uses_dependency(d, predicate) for d in surface["dependants"]):
        for key in plc._surface_keys(surface):
            new[key] = surface["route"]
print(f"  顶层条目数                     = {len(mixed)}")
print(f"  旧走法枚举到的腿              = {len(old)}  {sorted(old)}")
print(f"  新走法枚举到的腿              = {len(new)}  {sorted(new)}")
print(f"  (a) 旧走法漏掉的腿            = {sorted(set(new) - set(old))}")
print(f"  (b) 递归多看见的腿数          = {len(new) - len(old)}")
print(f"  超集（旧 ⊆ 新）               = {set(old) <= set(new)}")
print(f"  顶层那枚容器被展开了          = {plc._child_nodes(node) is not None}")

print("=" * 72)
print("形状 ①（effective_candidates 给出生效子表 + include 前缀 /api/v2）")
node2 = FakeIncludedRouter(inner_app, FakeIncludeContext("/api/v2"), with_candidates=True)
new2 = {}
for surface in plc._walk_surfaces([top[0], node2]):
    if surface["route"] is None or not surface["dependants"]:
        continue
    if any(plc._uses_dependency(d, predicate) for d in surface["dependants"]):
        for key in plc._surface_keys(surface):
            new2[key] = surface["route"]
old2 = old_route_index_from_HEAD([top[0], node2], predicate)
nested = [s for s in plc._walk_surfaces([node2]) if s["route"] is not None]
print(f"  旧走法枚举到的腿              = {len(old2)}  {sorted(old2)}")
print(f"  新走法枚举到的腿              = {len(new2)}  {sorted(new2)}")
print(f"  带前缀的腿被拼对了            = {all('/api/v2/' in k for k in new2 if 'nested' in k)}")
print(f"  每条嵌套腿带几枚 dependant    = {sorted({len(s['dependants']) for s in nested})}"
      f"  （路由自己那枚 + include 生效那枚 ⇒ 桩打得到真调用）")
print(f"  超集（旧 ⊆ 新）               = {set(old2) <= set(new2)}")

# --------------------------------------------------------------------------
# (c) 宿主真 app：递归后的集合必须是旧集合的超集，且差集为空（宿主没有那枚形状）
# --------------------------------------------------------------------------
print("=" * 72)
print("(c) 宿主真 app（fastapi 0.135.3，顶层无 _IncludedRouter 形状）")
predicates = [plc._predicate_using(auth.require_user), plc._predicate_using(auth.require_permissions)]
old_real: dict[str, object] = {}
for predicate in predicates:
    old_real.update(old_route_index_from_HEAD(list(plc.app.routes), predicate))
new_real: dict[str, object] = {}
for predicate in predicates:
    new_real.update(plc._route_index(predicate))
print(f"  顶层条目数                    = {len(plc.app.routes)}")
print(f"  递归访问到的条目数            = {len(plc._walk_nodes(list(plc.app.routes)))}")
print(f"  旧走法腿数                    = {len(old_real)}")
print(f"  新走法腿数                    = {len(new_real)}")
print(f"  旧 \\ 新（必须为空）           = {sorted(set(old_real) - set(new_real))}")
print(f"  新 \\ 旧（只增不减的那部分）   = {sorted(set(new_real) - set(old_real))}")
print(f"  SUPERSET(old ⊆ new)           = {set(old_real) <= set(new_real)}")
print(f"  IDENTICAL(旧==新，宿主形态)   = {set(old_real) == set(new_real)}")

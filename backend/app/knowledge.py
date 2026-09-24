from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型标注，运行期不 import，避免与 auth 形成环
    from app.auth import CurrentUser
    from app.identity.base import FeishuGrant

KNOWLEDGE_BASES: dict[str, dict[str, str]] = {
    "kb_public": {
        "id": "kb_public",
        "name": "公共制度",
        "description": "全员可访问的公司制度、通用规范与公告",
        "department": "ALL",
    },
    "kb_hr": {
        "id": "kb_hr",
        "name": "HR 知识库",
        "description": "人事制度、员工手册、招聘与薪酬相关资料",
        "department": "HR",
    },
    "kb_product": {
        "id": "kb_product",
        "name": "产品知识库",
        "description": "产品说明书、参数、FAQ 与交付文档",
        "department": "PRODUCT",
    },
    "kb_sales": {
        "id": "kb_sales",
        "name": "销售知识库",
        "description": "销售政策、折扣规则、客户沟通与渠道资料",
        "department": "SALES",
    },
    "kb_service": {
        "id": "kb_service",
        "name": "售后知识库",
        "description": "售后 SOP、退款规则、维修与服务规范",
        "department": "SERVICE",
    },
}

ROLE_ACCESS: dict[str, list[str]] = {
    "ADMIN": list(KNOWLEDGE_BASES.keys()),
    "SALES": ["kb_public", "kb_product", "kb_sales", "kb_service"],
    "HR": ["kb_public", "kb_hr"],
    "USER": ["kb_public"],
    "VIEWER": ["kb_public"],
}


def allowed_ids(role: str) -> list[str]:
    # Unknown identities must never inherit a public scope implicitly. Authentication
    # and authorization may evolve independently, so this boundary stays fail-closed.
    return list(ROLE_ACCESS.get(str(role).upper(), ()))


def visible_bases(role: str) -> list[dict[str, Any]]:
    allowed = set(allowed_ids(role))
    return [dict(value) for key, value in KNOWLEDGE_BASES.items() if key in allowed]


def public_kb_ids() -> list[str]:
    return [base["id"] for base in KNOWLEDGE_BASES.values() if base["department"] == "ALL"]


def visible_bases_by_ids(knowledge_base_ids: list[str]) -> list[dict[str, Any]]:
    return [dict(KNOWLEDGE_BASES[kb_id]) for kb_id in knowledge_base_ids if kb_id in KNOWLEDGE_BASES]


def _in_definition_order(knowledge_base_ids: list[str]) -> list[str]:
    """按 `KNOWLEDGE_BASES` 定义序去重输出。

    白名单可以来自 `KNOWLEDGE_BASES`、`ROLE_ACCESS` 或飞书授予，次序各不相同；
    统一过一次定义序，次序就不再泄漏进响应形状（改 `ROLE_ACCESS` 的写法不该改变 `/knowledge-bases` 的输出）。
    """
    selected = set(knowledge_base_ids)
    return [kb_id for kb_id in KNOWLEDGE_BASES if kb_id in selected]


def effective_allowed_from_grant(grant: "FeishuGrant | None") -> list[str] | None:
    """授予接管知识范围时返回白名单；`None` 表示完全走本地 `ROLE_ACCESS`。

    `None` 有两种来源：开关关闭 / 未桥接（`grant is None`），以及规则零命中的空授予
    （裁决 A：空授予 == 本地语义，既不放宽也不收紧）。
    命中但只给了 `access_role`（平台能力）而未给库时返回 `[]`——知识范围只由
    `knowledge_base_ids` / `all_knowledge_bases` 决定，缺省即零可见，fail closed：
    `[]` 在下游一律表示"命中零行"，只有 `None` 才是"不加过滤"。
    顺序按 `KNOWLEDGE_BASES` 定义序，保证列表与展示序稳定。
    """
    if grant is None or not grant.is_authoritative():
        return None
    if grant.all_knowledge_bases:
        return list(KNOWLEDGE_BASES.keys())
    return _in_definition_order(grant.knowledge_base_ids)


def allowed_for(user: "CurrentUser") -> list[str]:
    """知识范围唯一消费入口：某个当前用户可见的全部知识库 id。

    "唯一"是口径上的：所有取数入口（问答 / 检索调试 / 统计 / 文档列表 / 评测 / Knowledge OS
    的 search 与 chunks / agent 检索工具）都只看它或它的派生 `resolve_for(user, kb_id)`，
    零可见一律 403。哪些函数真的在取数是机器校验的，不靠这份注释同步：
    见 `tests/test_feishu_identity_contract.py` 的检索调用点扫描
    （`test_every_retrieval_call_site_derives_scope_from_the_user`）。
    """
    allowed = effective_allowed_from_grant(user.grant)
    return allowed_ids(user.role) if allowed is None else allowed


def visible_for(user: "CurrentUser") -> list[dict[str, Any]]:
    """`visible_bases(role)` 的 grant 感知版。

    与 `visible_bases` 同源：先取 `allowed_for(user)` 的集合，再按 `KNOWLEDGE_BASES` 定义序输出，
    所以无论白名单来自授予还是本地规则，响应次序都只由定义序决定。
    """
    return visible_bases_by_ids(_in_definition_order(allowed_for(user)))


def resolve_requested(
    role: str,
    knowledge_base_id: str | None,
    allowed: list[str] | None = None,
) -> list[str]:
    if allowed is not None:
        # 白名单即权威（来自授予）：不再查 ROLE_ACCESS，未知 role 也不额外否决，
        # 可见范围完全由 allowed 决定。
        # 空白名单 == 零可见，绝不等价于"不加过滤"：放行 all/None 会把 [] 交给下游
        # （store._kb_filter / retrieval._scope_key），那里 falsy 曾经意味着全库。
        if not allowed:
            raise PermissionError("当前账号无知识库访问权限")
        if knowledge_base_id is None or knowledge_base_id in {"", "all"}:
            return list(allowed)
        if knowledge_base_id not in KNOWLEDGE_BASES:
            raise ValueError("知识库不存在")
        if knowledge_base_id not in allowed:
            raise PermissionError("当前账号无权访问该知识库")
        return [knowledge_base_id]

    normalized_role = str(role).upper()
    if normalized_role not in ROLE_ACCESS:
        raise PermissionError("当前账号无知识库访问权限")
    allowed = allowed_ids(normalized_role)
    if knowledge_base_id is None or knowledge_base_id in {"", "all"}:
        return allowed
    if knowledge_base_id not in KNOWLEDGE_BASES:
        raise ValueError("知识库不存在")
    if knowledge_base_id not in allowed:
        raise PermissionError("当前账号无权访问该知识库")
    return [knowledge_base_id]


def resolve_for(user: "CurrentUser", knowledge_base_id: str | None) -> list[str]:
    """`resolve_requested` 的 grant 感知版：白名单**就是** `allowed_for(user)`。

    与 `allowed_for` 同源（这里不再自己拼 grant 判定），所以"这个用户看得到哪些库"与
    "这个用户能不能访问某个库"永远出自同一个答案：无有效授予时白名单是 `allowed_ids(role)`，
    有授予时是授予范围；两者都为空即整条请求 fail closed。
    """
    return resolve_requested(user.role, knowledge_base_id, allowed=allowed_for(user))


def get_base(knowledge_base_id: str) -> dict[str, str]:
    if knowledge_base_id not in KNOWLEDGE_BASES:
        raise ValueError("知识库不存在")
    return dict(KNOWLEDGE_BASES[knowledge_base_id])

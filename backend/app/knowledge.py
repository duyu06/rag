from __future__ import annotations

from typing import Any, Literal

Sensitivity = Literal["public", "internal", "confidential", "restricted"]

KNOWLEDGE_BASES: dict[str, dict[str, str]] = {
    "kb_public": {
        "id": "kb_public",
        "name": "公共制度",
        "description": "全员可访问的公司制度、通用规范与公告",
        "department": "ALL",
        "sensitivity": "public",
    },
    "kb_hr": {
        "id": "kb_hr",
        "name": "HR 知识库",
        "description": "人事制度、员工手册、招聘与薪酬相关资料",
        "department": "HR",
        "sensitivity": "restricted",
    },
    "kb_product": {
        "id": "kb_product",
        "name": "产品知识库",
        "description": "产品说明书、参数、FAQ 与交付文档",
        "department": "PRODUCT",
        "sensitivity": "internal",
    },
    "kb_sales": {
        "id": "kb_sales",
        "name": "销售知识库",
        "description": "销售政策、折扣规则、客户沟通与渠道资料",
        "department": "SALES",
        "sensitivity": "confidential",
    },
    "kb_service": {
        "id": "kb_service",
        "name": "售后知识库",
        "description": "售后 SOP、退款规则、维修与服务规范",
        "department": "SERVICE",
        "sensitivity": "internal",
    },
}

ROLE_ACCESS: dict[str, list[str]] = {
    "ADMIN": list(KNOWLEDGE_BASES.keys()),
    "SALES": ["kb_public", "kb_product", "kb_sales", "kb_service"],
    "HR": ["kb_public", "kb_hr"],
}


def allowed_ids(role: str) -> list[str]:
    return list(ROLE_ACCESS.get(role.upper(), ["kb_public"]))


def visible_bases(role: str) -> list[dict[str, Any]]:
    allowed = set(allowed_ids(role))
    return [dict(value) for key, value in KNOWLEDGE_BASES.items() if key in allowed]


def resolve_requested(role: str, knowledge_base_id: str | None) -> list[str]:
    allowed = allowed_ids(role)
    if knowledge_base_id is None or knowledge_base_id in {"", "all"}:
        return allowed
    if knowledge_base_id not in KNOWLEDGE_BASES:
        raise ValueError("知识库不存在")
    if knowledge_base_id not in allowed:
        raise PermissionError("当前账号无权访问该知识库")
    return [knowledge_base_id]


def get_base(knowledge_base_id: str) -> dict[str, str]:
    if knowledge_base_id not in KNOWLEDGE_BASES:
        raise ValueError("知识库不存在")
    return dict(KNOWLEDGE_BASES[knowledge_base_id])


_SENSITIVITY_RANK: dict[str, int] = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}


def sensitivity_for_ids(knowledge_base_ids: list[str] | None) -> Sensitivity:
    """Return the highest sensitivity in the requested/evidence scope."""
    if not knowledge_base_ids:
        return "public"
    highest = "public"
    highest_rank = 0
    for knowledge_base_id in knowledge_base_ids:
        item = KNOWLEDGE_BASES.get(str(knowledge_base_id))
        if not item:
            continue
        sensitivity = str(item.get("sensitivity") or "internal")
        rank = _SENSITIVITY_RANK.get(sensitivity, 1)
        if rank > highest_rank:
            highest = sensitivity
            highest_rank = rank
    return highest  # type: ignore[return-value]


def evidence_knowledge_base_ids(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            str(row.get("knowledge_base_id"))
            for row in rows
            if row.get("knowledge_base_id")
        }
    )

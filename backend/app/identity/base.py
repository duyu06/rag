from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AccessLevel = Literal["viewer", "user", "admin"]
ROLE_RANK: dict[str, int] = {"viewer": 0, "user": 1, "admin": 2}


class ExternalIdentity(BaseModel):
    username: str
    open_id: str
    department_ids: list[str] = Field(default_factory=list)
    department_names: list[str] = Field(default_factory=list)
    chat_ids: list[str] = Field(default_factory=list)
    chat_names: list[str] = Field(default_factory=list)


# 规则模型一律 extra="forbid"：写错的键（`access_role` → `access_roles`）在静默忽略下
# 会变成"规则命中了却什么都没授予"，从响应上完全看不出来。配置事故必须在加载期报错。
class RuleMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department_ids: list[str] = Field(default_factory=list)
    department_names: list[str] = Field(default_factory=list)
    chat_ids: list[str] = Field(default_factory=list)
    chat_names: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.department_ids or self.department_names or self.chat_ids or self.chat_names)


class RuleGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_role: AccessLevel | None = None
    knowledge_base_ids: list[str] = Field(default_factory=list)


class FeishuRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match: RuleMatch = Field(default_factory=RuleMatch)
    grant: RuleGrant


class FeishuRuleSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[FeishuRule] = Field(default_factory=list)


class FeishuGrant(BaseModel):
    access_role: AccessLevel | None = None
    knowledge_base_ids: list[str] = Field(default_factory=list)
    all_knowledge_bases: bool = False
    degraded: bool = False

    def is_authoritative(self) -> bool:
        """这份授予是否接管本地知识范围判定。

        命中任一授予字段（角色 / 库列表 / 全库）即以授予为权威；零命中的空授予返回 False，
        调用方据此原样落回本地 `ROLE_ACCESS` 语义（裁决 A：空授予 == 本地）。
        降级授予（`degraded=True` + 仅公共库）同样为 True——收紧必须可见。
        """
        return bool(self.access_role or self.knowledge_base_ids or self.all_knowledge_bases)

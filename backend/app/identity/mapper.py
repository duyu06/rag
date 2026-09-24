from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.identity.base import ExternalIdentity, FeishuGrant, FeishuRuleSet


def load_rule_set(path: str) -> FeishuRuleSet:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"飞书权限规则文件不可用：{path}") from exc
    try:
        rule_set = FeishuRuleSet.model_validate(raw)
    except ValidationError as exc:
        # 规则模型是 extra="forbid"：拼错的键到这里就是校验失败。报错文案带上文件路径，
        # 因为它是启动门闸（`identity.warmup()`）的失败原因，只出现在启动日志里。
        raise ValueError(f"飞书权限规则文件字段不合法：{path}：{exc}") from exc
    for index, rule in enumerate(rule_set.rules):
        # 空 match 等于向全员授予，是配置事故而不是宽松规则。
        if rule.match.is_empty():
            raise ValueError(f"飞书权限规则 #{index} 缺少匹配条件")
    return rule_set


def _rule_hits(identity: ExternalIdentity, rule) -> bool:
    match = rule.match
    checks = (
        (match.department_ids, identity.department_ids),
        (match.department_names, identity.department_names),
        (match.chat_ids, identity.chat_ids),
        (match.chat_names, identity.chat_names),
    )
    for wanted, owned in checks:
        if wanted and not (set(wanted) & set(owned)):
            return False
    return True


def match_identity(identity: ExternalIdentity, rule_set: FeishuRuleSet) -> FeishuGrant | None:
    from app.identity.base import ROLE_RANK

    best_role = None
    kb_ids: set[str] = set()
    all_kb = False
    hit = False
    for rule in rule_set.rules:
        if not _rule_hits(identity, rule):
            continue
        hit = True
        if rule.grant.access_role and (
            best_role is None or ROLE_RANK[rule.grant.access_role] > ROLE_RANK[best_role]
        ):
            best_role = rule.grant.access_role
        if "*" in rule.grant.knowledge_base_ids:
            all_kb = True
        kb_ids.update(k for k in rule.grant.knowledge_base_ids if k != "*")
    if not hit:
        return None
    return FeishuGrant(access_role=best_role, knowledge_base_ids=sorted(kb_ids),
                       all_knowledge_bases=all_kb)

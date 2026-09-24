"""TTL 缓存 + 失败收紧链 + 审计：把飞书外部身份编排成本地 `FeishuGrant`。

三条口径（收紧链见 FEISHU_PERMISSION_BRIDGE_DESIGN §2.3）：
1. 正常路径不产生审计：规则**零命中**返回空授予（`access_role=None`、库列表为空、
   `degraded=False`），它与本地语义等价，是一次成功解析，不是失败。
2. 只有抓取失败才收紧：条目 `fetched_at` 距今不超过 `stale_seconds` 时复用旧授予并标
   `degraded`；没有可用条目则回退"本地角色 + 仅公共知识库"。两条都写一行
   `FEISHU_PERMISSION/DEGRADED` 审计，任何路径都不放宽权限。
3. 降级产物同样写缓存（裁决C），但只活 `failure_cache_seconds`：故障期不是"每请求
   一次外呼 + 每请求一行审计"，恢复后最多隔一个失败窗口即重试成功。

首轮就失败（此前没有任何缓存）时，新条目的 `fetched_at` 记的是**失败时刻**——无更早的
成功抓取可沿用；该条目本身已是第 2 条里最保守那份，所以 stale 窗口从失败时刻起算。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from app.identity.base import ExternalIdentity, FeishuGrant, FeishuRuleSet
from app.identity.feishu_client import FeishuAPIError, FeishuClient
from app.identity.mapper import match_identity


@dataclass
class _CacheEntry:
    """一条授予缓存。

    `fetched_at` 是这份授予**底层成功抓取**的时刻，只用于 stale 判定；唯一例外是首轮
    即失败、无旧条目可沿用的降级条目——那时它记的是失败时刻（见模块 docstring 末段）。
    降级条目续期时不刷新它，否则故障期会把 stale 窗口无限推后，"超 stale 回退公共库"
    永远走不到。
    `expires_at` 是该条目可原样复用的截止点——成功条目 now+ttl、失败条目
    now+failure_cache_seconds，所以 fresh 判定按条目各自的生效 TTL 走。
    """

    grant: FeishuGrant
    fetched_at: float
    expires_at: float


class IdentityResolver:
    """Per-user grant cache. `resolve` never fails and never widens local authority."""

    def __init__(self, client: FeishuClient, rule_set: FeishuRuleSet, *,
                 ttl_seconds: int, stale_seconds: int, failure_cache_seconds: int = 60,
                 clock=time.monotonic) -> None:
        self._client = client
        self._rule_set = rule_set
        self._ttl = ttl_seconds
        self._stale = stale_seconds
        self._failure_ttl = failure_cache_seconds
        self._clock = clock
        self._cache: dict[str, _CacheEntry] = {}

    def resolve(self, username: str, role: str, open_id: str) -> FeishuGrant:
        entry = self._cache.get(username)
        now = self._clock()
        if entry and now <= entry.expires_at:
            # 成功条目命中返回 degraded=False，降级条目命中返回 degraded=True：
            # 降级标记就存在条目里，不需要额外分支。
            return _copy(entry.grant)
        try:
            grant = self._fetch_and_match(username, open_id)
        except (FeishuAPIError, RuntimeError) as exc:
            # 裁决C：降级产物写回缓存，但用短 TTL（failure_cache_seconds）；
            # fetched_at 沿用原条目，stale 判定不被降级续期刷新。
            degraded = self._tighten(username, role, entry, exc, now)
            self._cache[username] = _CacheEntry(_copy(degraded),
                                                entry.fetched_at if entry else now,
                                                now + self._failure_ttl)
            return degraded
        self._cache[username] = _CacheEntry(grant, now, now + self._ttl)
        return _copy(grant)

    def _fetch_and_match(self, username: str, open_id: str) -> FeishuGrant:
        user = self._client.fetch_user(open_id)
        department_ids = [str(i) for i in user.get("department_ids") or []]
        names = [self._client.department_name(i) for i in department_ids]
        chat_ids, chat_names = self._visible_chats(open_id)
        identity = ExternalIdentity(username=username, open_id=open_id,
                                    department_ids=department_ids, department_names=[n for n in names if n],
                                    chat_ids=chat_ids, chat_names=chat_names)
        # 零命中返回空授予（等价于本地语义），而不是 None：None 只表示"未启用/无 open_id"，
        # 那一层由 app.identity.resolve_for_user 表达。
        return match_identity(identity, self._rule_set) or FeishuGrant()

    def _visible_chats(self, open_id: str) -> tuple[list[str], list[str]]:
        # tenant 身份只能枚举机器人所在群，因此按规则白名单逐群确认成员，
        # 避免全量扫群。
        wanted_ids = {v for rule in self._rule_set.rules for v in rule.match.chat_ids}
        wanted_names = {v for rule in self._rule_set.rules for v in rule.match.chat_names}
        if not wanted_ids and not wanted_names:
            return [], []
        hit_ids, hit_names = [], []
        for chat in self._client.list_chats():
            if chat.chat_id not in wanted_ids and chat.name not in wanted_names:
                continue
            if open_id in self._client.chat_member_ids(chat.chat_id):
                hit_ids.append(chat.chat_id)
                hit_names.append(chat.name)
        return hit_ids, hit_names

    def _tighten(self, username: str, role: str, entry: _CacheEntry | None,
                 exc: Exception, now: float) -> FeishuGrant:
        # `now` 由 `resolve()` 采样后传入：一次解析只读一次时钟，fresh / stale /
        # expires_at 三处判定共用同一基准，不会因两次采样之间的漂移而不一致。
        from app.audit import record_event
        from app.knowledge import public_kb_ids
        from app.security import redact_text

        if entry and now - entry.fetched_at <= self._stale:
            degraded = _copy(entry.grant, degraded=True)
        else:
            # 无可用缓存：本地角色（access_role=None）+ 仅公共知识库。
            degraded = FeishuGrant(access_role=None, knowledge_base_ids=public_kb_ids(),
                                   all_knowledge_bases=False, degraded=True)
        record_event(username=username, role=role, action="FEISHU_PERMISSION",
                     status="DEGRADED", detail=redact_text(exc))
        return degraded


def _copy(grant: FeishuGrant, degraded: bool | None = None) -> FeishuGrant:
    # model_copy() 只复制模型壳，list 字段仍与缓存条目共享；显式换一份列表，
    # 避免调用方就地改写授予后污染缓存（降级结果就是这样被写坏的）。
    clone = grant.model_copy(update={"knowledge_base_ids": list(grant.knowledge_base_ids)})
    if degraded is not None:
        clone.degraded = degraded
    return clone

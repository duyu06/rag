"""Feishu permission bridge package.

运行期入口只有一个：`resolve_for_user()`。开关（`feishu_permissions_enabled`）与
`feishu_open_id` 桥接判断都收在这里，auth 侧不感知 resolver/client 的实现细节；
`app.config` 与 `app.audit` 全部延迟到函数内 import，避免与 auth 形成环。
启动期入口是 `warmup()`（由 `app/main.py` 的 lifespan 调一次），把"规则文件坏了"
这件事从第一个用户请求提前到进程启动。接入与运维口径见本目录 `README.md`。
"""
from __future__ import annotations

from app.identity.base import FeishuGrant

# 裁决C：飞书故障期降级产物的复用窗口（秒）。故意不做成 Settings 键——
# 它是"故障期别把每个请求打成 3s 外呼"的护栏，不是给运维调的策略参数。
FAILURE_CACHE_SECONDS = 60

_resolver = None


def get_resolver():
    global _resolver
    if _resolver is None:
        from app.config import settings
        from app.identity.feishu_client import FeishuClient
        from app.identity.mapper import load_rule_set
        from app.identity.resolver import IdentityResolver

        client = FeishuClient(settings.feishu_app_id,
                              settings.feishu_app_secret.get_secret_value(),
                              settings.feishu_base_url, settings.feishu_timeout_seconds)
        _resolver = IdentityResolver(client, load_rule_set(settings.feishu_rules_file),
                                     ttl_seconds=settings.feishu_cache_ttl_seconds,
                                     stale_seconds=settings.feishu_cache_stale_seconds,
                                     failure_cache_seconds=FAILURE_CACHE_SECONDS)
    return _resolver


def reset_resolver() -> None:
    global _resolver
    _resolver = None


def warmup() -> None:
    """启动门闸：进程起来就装配一次 resolver（读规则文件、建客户端）。

    开关关闭时直接返回——不 import 客户端、不读文件、不发请求，行为与今天逐字一致。
    开关打开时**任何异常都原样上抛**，让 uvicorn 的启动阶段失败：
    规则文件坏 / 不可读时，"放宽为 None 继续跑"等于让此后每个请求都走降级链，
    运维只能从审计里反推，而 fail-fast 是把同一件事摊在启动日志上。
    这里禁止 catch：装配失败后 `_resolver` 保持 None，也不会留下半装配的单例。
    """
    from app.config import settings

    if not settings.feishu_permissions_enabled:
        return
    get_resolver()


def resolve_for_user(username: str, role: str, record: dict) -> FeishuGrant | None:
    """Grant for one local account. None keeps today's local-only semantics."""
    from app.config import settings

    open_id = str(record.get("feishu_open_id") or "")
    if not settings.feishu_permissions_enabled or not open_id:
        return None
    return get_resolver().resolve(username, role, open_id)

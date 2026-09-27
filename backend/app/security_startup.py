"""生产形态的启动守卫（规格 §8.5）。三件守卫由一枚开关共同驱动，不存在矛盾组合。

`SECURITY_ENTERPRISE_MODE=false`（默认）⇒ 本模块整体是 no-op：`evaluate_startup_guards`
直接返回空列表，`assert_startup_safe` 因此永不抛。默认配置下启动不新增任何行为，这条
不变量与 `warmup_identity_permissions` / `warmup_llm_router` 的前置判法同形（各自在内部
按开关早退）。只有把总开关打到 true，下面三件才同生同死：

- 默认 / 过短的 `JWT_SECRET` ⇒ 拒启动（默认值留在 `config.py` 是给测试形态的，不是给生产的）；
- CORS 白名单缺失或含 `*` ⇒ 拒启动（收紧 origin 才是有效项，`allow_credentials` 保持 False）；
- demo 身份 ⇒ 企业形态下 `directory` 根本不加载 `config/users.demo.json`（结构事实，
  不在这张表里重复判，也不按用户名过滤）。

守卫放在 `main.py` 的 lifespan 第一道，而不是模块顶层 import：顶层副作用会波及所有导入方
（测试、脚本、`python -c "import app.main"`）。SECA-18 直接调用 `evaluate_startup_guards`
断言三件同时生效，不依赖 lifespan 是否被执行。
"""

from __future__ import annotations

#: 与 `app.config.Settings.jwt_secret` 的默认字面量同源。守卫靠"等于这枚值"识别出厂默认，
#: 所以两处必须是**同一个字符串**——抄错一位就会把生产误判成不安全或把默认值放过。
DEFAULT_JWT_SECRET = "change-me-before-production-yaoke-demo-secret"

#: 企业形态下 JWT secret 的长度下限。出厂默认有 49 字符，单靠长度抓不到它，故"等于默认值"
#: 与"短于 32"是两条独立判据：前者杀"忘了改"，后者杀"随手敲了枚短的"。
_MIN_JWT_SECRET_LENGTH = 32


class SecurityStartupError(RuntimeError):
    """企业形态下配置不安全 ⇒ 拒绝启动。比第一个请求才炸好。"""


def evaluate_startup_guards(
    *, enterprise_mode: bool, jwt_secret: str, cors_allow_origins: str
) -> list[str]:
    """返回违规清单（空列表 = 通过）。三件守卫在同一枚开关下聚合，调用方据此一次报全。

    非企业形态**直接早退**——dev / 测试形态允许默认 secret、允许空 CORS 白名单（走
    `http://localhost:3000` 默认），这既是 §8.5 表的语义，也是"默认配置零额外启动行为"
    这条不变量的来源。
    """
    if not enterprise_mode:
        return []
    violations: list[str] = []
    if not jwt_secret or jwt_secret == DEFAULT_JWT_SECRET or len(jwt_secret) < _MIN_JWT_SECRET_LENGTH:
        violations.append("SECURITY_ENTERPRISE_MODE 下 JWT_SECRET 必须是 ≥32 字符的非默认值")
    origins = [item.strip() for item in (cors_allow_origins or "").split(",") if item.strip()]
    if not origins or "*" in origins:
        violations.append("SECURITY_ENTERPRISE_MODE 下 CORS_ALLOW_ORIGINS 必须是显式白名单")
    return violations


def assert_startup_safe() -> None:
    """读 `settings` 跑一遍三守卫；有违规即抛。lifespan 第一道调它。"""
    from app.config import settings

    violations = evaluate_startup_guards(
        enterprise_mode=bool(settings.security_enterprise_mode),
        jwt_secret=str(settings.jwt_secret),
        cors_allow_origins=str(settings.cors_allow_origins),
    )
    if violations:
        raise SecurityStartupError("；".join(violations))

"""LLM 模型注册表：加载 + 校验（fail-fast）+ D1 凭据解析 + 进程内单例与 warmup。

设计口径（§3 冻结）
------------------
- `config/llm_registry.json` 是**声明式、零 secret** 的：这里出现 `api_key` /
  `base_url` 字段就是 D1 红线，所以注册表模型全部 `extra="forbid"`（`_RegistryFile`
  顶层同样 forbid），拼错的键与凭据键都会变成启动期 `RegistryError`。
- 凭据来自 D1 约定：env 名由 `_env_name` 在运行期按 provider 拼出，形状是
  「provider 大写 + 字段大写」两段（字段即 api_key / base_url / model_override 三路）；
  `ollama` 只有 base_url 一路（**无 key**，恒返回空串）；内置 `openai` 条目复用现有
  openai 配置键——查找顺序是「`Settings` 字段优先，其次 OS env」，因此
  `backend/.env` 里的值与 legacy `rag.py` 的判断同源，不产生第二套配置。
  env 名**只在运行期拼装**：本文件的代码与注释里都不出现字面量凭据键名，因此 Task 9
  的单一出口静态扫描（D6）下 `app/llm/` 是永久零命中目录，不必为注册表层开任何文档豁免。
  ollama 的全局 model 默认值 **不参与** model 覆盖：注册表里两条 ollama 条目
  （ornith / phi3）各自写死模型名，全局默认值一覆盖就会把它们折叠成同一个模型，真实的
  failover 源→备对子也就没了。只有 provider 级的 model_override 那一路才生效。
- 校验失败（结构 / 重复 id / 非法 priority 键 / 能力全 false）抛
  `RegistryError(ValueError)`；`LLM_ROUTER_ENABLED=true` 时 `warmup()` 原样上抛，
  让坏配置死在启动日志里（沿用 `app/identity/warmup` 的门闸语义）。
  `warmup()` 在加载之后还跑 `validate_registry()`（Task 2 评审 I-3）：每个 `enabled`
  条目的 provider 必须在 `provider.PROVIDERS` 的键集里，否则同样 `RegistryError`——
  未登记名在运行期是 NO_FALLBACK 终止（换模型也救不回来），不该等第一个请求才发现。
  结构不合法时异常消息**只列 pydantic 的 `loc + msg`**（见 `_validation_detail`）：
  条目字段值不得回显，否则误写进 JSON 的 key 会随启动日志泄漏（D1/D3）。
- `load_registry` 的解析层还会把「`external` 且凭据缺失」的条目从
  `enabled=true` 收成 `enabled=false`（openai 条目的 JSON 声明是意图，
  其 api_key 是否为空才是事实）。因此 `Registry.models[*].enabled`
  读到的永远是生效值，Task 3 的 `enabled` 过滤不必再判一次 key。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError, Field

from app.config import settings
from app.llm.models import ModelDefinition, PRIORITY_KEYS

__all__ = [
    "ProviderCredentials",
    "Registry",
    "RegistryError",
    "credentials_for_provider",
    "get_registry",
    "load_registry",
    "provider_credentials",
    "reset_registry",
    "validate_registry",
    "warmup",
]


class RegistryError(ValueError):
    """注册表不可用（文件坏 / 结构错 / 校验不过）= 配置事故，不是运行期可重试错误。"""


class _RegistryFile(BaseModel):
    """JSON 顶层形状：`{version, models[]}`，未知顶层键 forbid（§3 schema 冻结）。"""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    models: list[ModelDefinition] = Field(min_length=1)


@dataclass(frozen=True)
class Registry:
    """只读快照。`models` 保持文件声明顺序（打分与排序是 router 的职责）。"""

    models: tuple[ModelDefinition, ...]

    def get(self, model_id: str) -> ModelDefinition:
        for model in self.models:
            if model.id == model_id:
                return model
        raise RegistryError(f"注册表中不存在模型 id：{model_id}")

    def ids(self) -> tuple[str, ...]:
        return tuple(model.id for model in self.models)


# --------------------------------------------------------------------------
# 加载与校验
# --------------------------------------------------------------------------
def load_registry(path: str) -> Registry:
    """读取并校验注册表文件，返回已解析（enabled 收成生效值）的 `Registry`。

    任何问题都抛 `RegistryError`：包括文件不可读、JSON 语法错、结构不合法、
    重复 id、priority 键越界与能力全 false。空 `models` 数组同样拒（`min_length=1`）：
    一份一个条目都没有的注册表会让每个请求都 `NO_CAPABLE_MODEL`，那是配置事故。
    """
    raw = _read_json(path)
    try:
        parsed = _RegistryFile.model_validate(raw)
    except ValidationError as exc:
        # from None：连 __cause__/traceback 都不给原始 ValidationError 露出字段值的机会。
        raise RegistryError(
            f"LLM 注册表结构不合法：{path}：{_validation_detail(exc)}") from None

    _reject_duplicate_ids(parsed.models, path)
    for index, model in enumerate(parsed.models):
        _check_priority_keys(model, path, index)
        _check_capabilities(model, path, index)

    return Registry(models=tuple(_with_effective_enabled(m) for m in parsed.models))


def validate_registry(registry: Registry, *, supported_providers: frozenset[str]) -> None:
    """每个 enabled 条目的 provider 都必须在分发面上（Task 2 评审 I-3 的 fail-fast）。

    后果链：provider 名未登记 ⇒ `provider._adapter()` 抛 `LLMError(kind="hard",
    no_fallback=True)` ⇒ **整条请求终止**而不是静默降级到别的候选（Task 2 报告 D-5）。
    一个打字错误不该等到第一个线上请求才暴露，所以它是启动事故 ⇒ `RegistryError`。

    `supported_providers` 由调用方注入（`provider.SUPPORTED_PROVIDERS`），本文件不
    import provider——见 `warmup()` 里的循环导入说明。只查 `enabled=True` 的条目：
    禁用条目进不了候选列表，写错的 provider 名没有运行期后果。
    消息里回显 provider 名是安全的：它已经过 `^[a-z0-9_]+$` 模式校验，不可能是
    误写进来的凭据（与 `_validation_detail` 的「不回显条目值」不同场景）。
    """
    offenders = [
        f"{model.id}→{model.provider}"
        for model in registry.models
        if model.enabled and model.provider not in supported_providers
    ]
    if offenders:
        raise RegistryError(
            f"LLM 注册表有 {len(offenders)} 个启用条目的 provider 未登记：{offenders}；"
            f"可分发的 provider 是 {sorted(supported_providers)}。"
            "未登记名会让请求以 NO_FALLBACK 终止而不是降级，请在注册表或 PROVIDERS 里改正。")


def _validation_detail(exc: ValidationError) -> str:
    """把 `ValidationError` 压成 `loc: msg` 清单——**只取键名与诊断语，不取值**。

    pydantic 的 `str(ValidationError)`（以及 `errors()` 的 `input`/`context`）会回显
    条目字段值：有人误把凭据写进 JSON 时，那个值就出现在异常文本里，而 `warmup()` 不
    catch、异常原样进启动日志 ⇒ D1/D3 的泄漏面。位置（`models.0.api_key`）与原因保留，
    诊断能力不减。
    """
    return "；".join(
        f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
        for err in exc.errors(include_url=False, include_context=False))


def _read_json(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(
            f"LLM 注册表文件不可用：{path}（{type(exc).__name__}: {exc}）") from exc


def _reject_duplicate_ids(models: list[ModelDefinition], path: str) -> None:
    seen: set[str] = set()
    duplicated: set[str] = set()
    for model in models:
        if model.id in seen:
            duplicated.add(model.id)
        seen.add(model.id)
    if duplicated:
        # 重复 id 会让 `Registry.get()` 与 usage 归因指向不确定的一条，必须拒。
        raise RegistryError(
            f"LLM 注册表存在重复 id：{sorted(duplicated)}（文件：{path}）")


def _check_priority_keys(model: ModelDefinition, path: str, index: int) -> None:
    illegal = sorted(set(model.priority) - set(PRIORITY_KEYS))
    if illegal:
        raise RegistryError(
            f"LLM 注册表条目 #{index}（{model.id}）的 priority 含非法键 {illegal}；"
            f"允许的键是 {list(PRIORITY_KEYS)}（mode=agent 复用 tools 档）。文件：{path}")


def _check_capabilities(model: ModelDefinition, path: str, index: int) -> None:
    if not model.capabilities.any_enabled():
        raise RegistryError(
            f"LLM 注册表条目 #{index}（{model.id}）的五项 capabilities 全为 false，"
            f"它永远不可能被选中——属于配置事故。文件：{path}")


def _with_effective_enabled(model: ModelDefinition) -> ModelDefinition:
    """external 条目缺 key ⇒ enabled=False（D1；openai 条目的动态判定就发生在这里）。"""
    if not model.enabled or not model.external:
        return model
    if _credential_value(model.provider, "api_key"):
        return model
    return model.model_copy(update={"enabled": False})


# --------------------------------------------------------------------------
# D1 凭据解析
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ProviderCredentials:
    """一个 provider 的连接参数。`model_override` 为空串表示沿用注册表条目的 model。"""

    base_url: str
    api_key: str
    model_override: str = ""


_CREDENTIAL_FIELDS = ("api_key", "base_url", "model_override")


def _env_name(provider: str, field: str) -> str:
    """D1 约定的 env 名（运行期拼装，源码里不出现字面量凭据键名，见模块 docstring）。"""
    return f"{provider.upper()}_{field.upper()}"


def _settings_value(name: str) -> str:
    """`Settings` 里存在该字段就取值（SecretStr 会解开），否则返回空串。"""
    raw = getattr(settings, name, None)
    if isinstance(raw, SecretStr):
        return raw.get_secret_value().strip()
    if isinstance(raw, str):
        return raw.strip()
    return ""


def _credential_value(provider: str, field: str) -> str:
    """查找顺序：`Settings.{provider}_{field}` → OS env `{PROVIDER}_{FIELD}` → 空串。"""
    # Settings→env 两路对同一凭据等价（pydantic-settings 已把同名大写 env 读进字段），故意不钉这个偏序。
    from_settings = _settings_value(f"{provider}_{field}")
    if from_settings:
        return from_settings
    return os.environ.get(_env_name(provider, field), "").strip()


def provider_credentials(model: ModelDefinition) -> ProviderCredentials:
    """按 D1 解析一个条目的凭据。ollama 恒无 key；缺 base_url 即配置事故。

    返回的 `api_key` 只应存在于 provider 层的一次请求里：不得写日志、不得入
    usage 表、不得进 trace（D3/D6）。
    """
    return credentials_for_provider(model.provider, label=model.id)


def credentials_for_provider(provider: str, *, label: str = "") -> ProviderCredentials:
    """按 provider 名解析 D1 凭据——`provider_credentials()` 的底层实现，也是 health/probe
    这类「没有注册表条目、只有 provider 名」场景的唯一入口（Task 2：避免 provider 层
    为了复用 D1 而伪造一条 `ModelDefinition`）。

    `label` 只用于错误文案（缺 base_url 时指出是谁在用这个 provider）。
    """
    api_key = "" if provider == "ollama" else _credential_value(provider, "api_key")
    base_url = _credential_value(provider, "base_url")
    if not base_url:
        raise RegistryError(
            f"模型 {label or f'provider:{provider}'} 的 provider「{provider}」缺少 base url："
            f"请配置 {_env_name(provider, 'base_url')}（D1 凭据约定）。")
    return ProviderCredentials(
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        model_override=_credential_value(provider, "model_override"),
    )


# --------------------------------------------------------------------------
# 单例与启动门闸
# --------------------------------------------------------------------------
_registry: Registry | None = None


def get_registry() -> Registry:
    """进程内单例（配置键只在启动时读一次，与 `identity.get_resolver()` 同构）。"""
    global _registry
    if _registry is None:
        _registry = load_registry(settings.llm_registry_file)
    return _registry


def reset_registry() -> None:
    """清单例。测试之间换文件 / 换 env 后必须调用，否则会读到上一个用例的快照。"""
    global _registry
    _registry = None


def warmup() -> None:
    """启动门闸：路由开启时加载注册表一次，并校验 provider 都在分发面上——坏配置死在启动日志里。

    `LLM_ROUTER_ENABLED=false` 直接返回——不读文件、不校验，行为与今天逐字一致。
    这里禁止 catch：与 `app/identity/warmup` 同理，「半份注册表」比「启动失败」更糟。
    lifespan 接线在 Task 5 统一处理（pre-flight 裁决：本任务不动 main/lifespan）。

    `provider` 在**函数体内** import（I-3）：`provider → registry` 已经是编译期依赖
    （provider 要复用本文件的 D1 凭据解析），registry 再模块级 import 一次 provider 就是
    循环导入；运行期只取 `SUPPORTED_PROVIDERS` 一个常量，环不存在。也因此这一步只能落在
    `warmup()`，不能落进 `load_registry()`（它会被 provider 侧间接调用）。
    """
    if not settings.llm_router_enabled:
        return
    from app.llm import provider                # 运行期 import，避开 provider↔registry 环

    registry = get_registry()
    validate_registry(registry, supported_providers=provider.SUPPORTED_PROVIDERS)

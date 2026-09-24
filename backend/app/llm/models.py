"""Model Router V2.3 的数据对象（设计 §3 冻结清单，不过度抽象）。

命名与字段顺序按 plan/spec 冻结，后续 provider / router / fallback / usage
全部消费本模块，不再各自定义平行结构。

两类对象刻意分开：
- **注册表侧**（`ModelCapabilities` / `ModelPricing` / `ModelLimits` / `ModelDefinition`）
  是 pydantic 模型，直接对应 `config/llm_registry.json` 的形状，`extra="forbid"`：
  凭据键（api_key / base_url）出现在 JSON 里就是 D1 红线，拼错的键也必须在启动期
  变成 `RegistryError`，而不是悄悄退化成默认值。全部 `frozen=True`——注册表是
  跨请求共享的只读快照（D1 的动态 enabled 用 `model_copy` 造新对象，不改共享实例）。
- **调用链侧**（`RequestProfile` / `RouteCandidate` / `RoutePlan` / `LLMRequest` /
  `ToolCall` / `LLMResponse` / `LLMChunk` / `UsageRecord`）是执行期一次性值对象：
  路由与请求类用 frozen dataclass（Router 的唯一合法输入必须是不可变画像），
  provider 报文类用 pydantic（要吸收两侧 provider 的可选字段差异，默认值比校验更重要）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# 注册表 priority 字典允许的键（§3 schema）：mode=agent 复用 tools 这一档，
# 因此这里**不含** "agent"；越界的键名是配置事故，registry 层直接拒。
PRIORITY_KEYS: tuple[str, ...] = ("chat", "rag", "tools")
# capabilities 的五个旗标名，顺序与 JSON 声明一致（校验/遍历用）。
CAPABILITY_KEYS: tuple[str, ...] = ("chat", "rag", "tools", "stream", "reasoning")


# --------------------------------------------------------------------------
# 注册表（声明式，零 secret）
# --------------------------------------------------------------------------
class ModelCapabilities(BaseModel):
    """一个模型能干什么。缺省全 False：漏写旗标等于「不会这项」，fail-closed。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chat: bool = False
    rag: bool = False
    tools: bool = False
    stream: bool = False
    reasoning: bool = False

    def any_enabled(self) -> bool:
        """五项旗标至少一项为真——全 False 的条目永远不会被选中，属配置事故。"""
        return any(getattr(self, name) for name in CAPABILITY_KEYS)


class ModelPricing(BaseModel):
    """每 100 万 token 单价（§8 `estimated_cost` 的唯一数据源）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_per_1m: float = Field(default=0.0, ge=0.0)
    output_per_1m: float = Field(default=0.0, ge=0.0)
    currency: str = "USD"


class ModelLimits(BaseModel):
    """上下文与输出上限；router 用它做粗筛（§5 的 limits 过滤段）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    context_tokens: int = Field(default=8192, ge=1)
    max_output_tokens: int = Field(default=2048, ge=1)


class ModelDefinition(BaseModel):
    """注册表里的一条模型声明。凭据一律不在此处（D1：env 约定 + provider 层解析）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    # provider 名要参与 D1 的 env 名拼装（registry._env_name 会大写它），所以只收
    # 小写字母/数字/下划线：带大写、连字符、空格或换行的值会拼出解析不到的 env 名，
    # 那是配置事故——在模型层就拒，不等运行期「凭据 mysteriously 缺失」。
    provider: str = Field(min_length=1, pattern="^[a-z0-9_]+$")
    model: str = Field(min_length=1)
    # JSON 里的 enabled 是「意图」；`load_registry` 解析层会把「external 且无 key」
    # 收成 enabled=False 的事实值（见 registry._with_effective_enabled）。
    enabled: bool
    external: bool
    capabilities: ModelCapabilities
    priority: dict[str, int] = Field(default_factory=dict)
    limits: ModelLimits = Field(default_factory=ModelLimits)
    pricing: ModelPricing = Field(default_factory=ModelPricing)


# --------------------------------------------------------------------------
# 路由输入/输出（纯值对象）
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class RequestProfile:
    """Router 的唯一合法输入（§3/§4）：调用点声明 mode，classifier 补复杂度与需求旗标。"""

    mode: Literal["chat", "rag", "agent"]
    complexity: Literal["low", "medium", "high"]
    needs_tools: bool
    needs_stream: bool
    needs_reasoning: bool = False


@dataclass(frozen=True)
class RouteCandidate:
    """一个通过过滤的候选及其打分与机器可读理由码（§5 冻结枚举）。"""

    model: ModelDefinition
    score: int = 0
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoutePlan:
    """primary + 有序 fallbacks；reason_codes 是整条计划的合并理由。"""

    primary: RouteCandidate
    fallbacks: tuple[RouteCandidate, ...] = ()
    reason_codes: tuple[str, ...] = ()


# --------------------------------------------------------------------------
# provider 报文（两侧差异在 provider/normalize 层吸收，业务只认这些形状）
# --------------------------------------------------------------------------
class LLMRequest(BaseModel):
    """一次生成请求。Ollama 专有项（num_predict/think/keep_alive）保持可选。

    `temperature` 是**唯一**温度来源：`normalize` 层不注入默认值，也不读 provider 侧默认。
    各链的现值由调用方携带——rag 非流式的 legacy 现值是 0.1（`rag.py`），agent 的 Ollama
    轮次是 0.2（`agent.py`）；Task 6/8 迁移时按各自的现值显式传，否则字段默认 0.2 会
    悄悄改掉 rag 的采样温度。
    """

    messages: list[dict[str, Any]]
    temperature: float = 0.2
    tools: list[dict[str, Any]] = Field(default_factory=list)
    num_predict: int | None = None
    think: bool | None = None
    keep_alive: str | None = None


class ToolCall(BaseModel):
    """标准化后的工具调用：`arguments` 在 normalize 层已从字符串解析成 dict（§6）。"""

    id: str = ""
    name: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """非流式统一响应；usage 缺失时 token 记 0 并置 `usage_estimated=True`。

    `usage_estimated` 是**内存旗标**，不是 §8 的列：那 19 列已冻结且没有 estimated 字段，
    要落库得先经用户裁决（Task 1 报告移交项）。命名上刻意避开 `estimated_cost`（§8 里
    那是「按牌价折算的成本」），两个 concept 混在一个词里迟早出 accounting bug。
    """

    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str = "stop"
    model: str = ""
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    usage_estimated: bool = False


class LLMChunk(BaseModel):
    """流式片段：`finish` 标最后一个有效块，`usage` 在末尾块携带（可能为 None）。"""

    text: str = ""
    finish: bool = False
    usage: dict[str, Any] | None = None


@dataclass
class UsageRecord:
    """`llm_request_logs` 的一行（§8 冻结 19 列，顺序与列名逐字镜像）。

    永不入这里的字段（D3）：prompt、完整 context、reasoning/CoT、API key、
    Authorization。`route_reason` 在内存里保持理由码元组，由 `usage.py` 落库时
    JSON 序列化；`id` / `created_at` 交给 SQLite（自增主键与 DEFAULT 时间戳），
    构造时留 None。字段可变（流式链路边生成边补 ttft/usage），不加 frozen。
    """

    id: int | None = None
    trace_id: str | None = None
    request_id: str | None = None
    route_mode: str = ""
    route_reason: tuple[str, ...] = ()
    provider: str = ""
    model: str = ""
    fallback_index: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    ttft_ms: float | None = None
    latency_ms: float = 0.0
    estimated_cost: float = 0.0
    currency: str = "USD"
    success: bool = True
    error_type: str | None = None
    status_code: int | None = None
    created_at: str | None = None

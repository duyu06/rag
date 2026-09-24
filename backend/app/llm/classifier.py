"""规则分类器（spec §4：禁 LLM 判路由）。

`classify()` 是 Router 画像的唯一入口：把「调用点声明的 mode」与「问题文本的规则判定」
折叠成一个 frozen `RequestProfile`。纯函数、零 IO、零时钟、零随机 —— 同一个输入永远得到
同一个画像，所以路由可复现、可离线回放（trace/usage 里只需记 mode/complexity/需求旗标，
不需要留存问题原文，D3 因此没有额外义务）。

判定口径（本任务的冻结面）
--------------------------
- **mode 由调用点声明**（RAG=rag、SSE=rag+needs_stream、Agent=agent+needs_tools），
  classifier 不猜「这是不是 agent 请求」：猜错一次的代价是一次真实的熔断器抖动与一条
  注定失败的云端往返，而调用点本来就知道自己在哪条链上。
- **complexity 走规则三级**（顺序即优先级，high 短路）：
  1. high —— 字符数 ≥ `HIGH_COMPLEXITY_LENGTH_THRESHOLD`（60），或命中
     `HIGH_COMPLEXITY_MARKERS`（对比 / 为什么 / 方案 / 风险 / 优缺点 / 多条件 / 同时 / 分别 …）；
  2. medium —— 命中 `MEDIUM_CONNECTIVE_MARKERS`（并且 / 以及 / 或者 / 如果 …），或被
     句子级分隔符切出 ≥2 个非空子句（「先翻译第一段。再校对第二段。」这种多约束单请求）；
  3. low —— 以上都不成立：短、单意图、无分析动词。
- 词表刻意只收**两个字符以上**的窄词。单字标记（「和」「要」「多」「改」）会把绝大多数
  正常问句升级成 high，于是把流量整体推向高优先级的云端条目 —— 那是成本事故，比判准度
  更贵。同理 medium 表里的词不得包含 high 表的词作为子串（否则一条规则吃掉另一条），
  这条不变量由契约测试逐词钉住。
- **`needs_reasoning` 恒为 False**：V2.3 没有推理需求方（§3 冻结的字段默认值），
  注册表的 reasoning capability 位与本字段保留是给后续版本的接缝；router 仍按字段消费
  （双态都有契约测试），所以将来置真时不需要改路由代码，只改调用点。

复杂度目前**不参与打分**（§5 的评分只读 `priority[mode]` 与 `pricing`）。它今天是 trace
与 usage 的解释字段，将来是「按难度选档」的输入面 —— 现在把判定口径钉死，改判定不改形状。

词表风格参考 typesafe 判定层的常量表（大写 tuple 常量 + 逐条中文注释），但**独立实现、
不 import 那个模块**：分类层与判定层一旦成环，V2.3 的路由就继承了对方的全部回归面。
"""
from __future__ import annotations

from typing import Literal

from app.llm.models import RequestProfile

__all__ = [
    "CLAUSE_SEPARATORS",
    "HIGH_COMPLEXITY_LENGTH_THRESHOLD",
    "HIGH_COMPLEXITY_MARKERS",
    "MEDIUM_CONNECTIVE_MARKERS",
    "MODES",
    "classify",
    "complexity_of",
]

# §3/§4 的三种 mode：priority 取档与 capability 取位都以它为主键，越界值在入口就拒。
MODES: tuple[str, ...] = ("chat", "rag", "agent")

# high 的长度门槛（字符数，中文按字计）。60 是任务书逐字给定的值。
HIGH_COMPLEXITY_LENGTH_THRESHOLD = 60

# 句子级分隔符：只在「。！？；」与换行处切子句。**不含**逗号/顿号 —— 带顿号的列举
# （「把甲、乙、丙三段的引号统一」）是一个意图，不是多约束。
CLAUSE_SEPARATORS: tuple[str, ...] = ("。", "！", "？", "；", ";", "!", "?", "\n")

# high 词表：分析/对比/方案/风险类动词，以及「一句里要好几件事」的显式多条件说法。
# 英文几枚是给「用英文提问的运维」的兜底；表里一律小写，匹配前对文本 casefold。
HIGH_COMPLEXITY_MARKERS: tuple[str, ...] = (
    "对比", "比较", "对照", "区别", "差别", "为什么", "为何", "原因", "成因", "原理",
    "机制", "方案", "架构", "设计", "选型", "权衡", "取舍", "风险", "隐患", "优缺点",
    "优劣", "利弊", "多条件", "多步骤", "同时", "分别", "逐条", "分点", "评估", "分析",
    "推导", "证明", "排查", "定位", "根因", "归因", "复盘", "总结成", "规划",
    "why", "compare", "versus", "trade-off", "tradeoff",
)

# medium 词表：连接词/条件词 = 一句话里挂了多个约束，但没要求分析。
# 约束：不得包含 high 表的任何词作为子串（「同时满足」就不许出现在这里，它含「同时」）。
MEDIUM_CONNECTIVE_MARKERS: tuple[str, ...] = (
    "并且", "而且", "以及", "还有", "或者", "要么", "除了", "不仅", "不但", "然后",
    "接着", "但是", "不过", "然而", "因此", "所以", "如果", "假如", "要是", "即便",
    "既要", "兼顾", "一是", "其二", "另外", "此外",
)


def complexity_of(query: str) -> Literal["low", "medium", "high"]:
    """规则判定三级复杂度（口径见模块 docstring；纯函数，不读任何外部状态）。"""
    text = "" if query is None else str(query).strip()
    if not text:
        return "low"
    if len(text) >= HIGH_COMPLEXITY_LENGTH_THRESHOLD:
        return "high"
    probe = text.casefold()
    if any(marker in probe for marker in HIGH_COMPLEXITY_MARKERS):
        return "high"
    if any(marker in probe for marker in MEDIUM_CONNECTIVE_MARKERS):
        return "medium"
    if _clause_count(probe) >= 2:
        return "medium"
    return "low"


def classify(query: str, *, mode: Literal["chat", "rag", "agent"],
             needs_tools: bool = False,
             needs_stream: bool = False) -> RequestProfile:
    """把一个请求折叠成 Router 的唯一合法输入 `RequestProfile`（§4）。

    参数命名按 plan brief 冻结：`mode` 关键词强制且**无默认值** —— 漏声明 mode 的调用点
    等于让 Router 自己猜链路，那是 §4「mode 由调用点声明」的反面，所以宁可在构造画像时
    就 `TypeError`/`ValueError`，也不产出一个谁都匹配不到的画像去换一次
    `NO_CAPABLE_MODEL`。
    """
    if mode not in MODES:
        raise ValueError(
            f"未知的调用点 mode：{mode!r}；允许的是 {MODES}"
            "（RAG=rag、SSE=rag+needs_stream、Agent=agent+needs_tools）。")
    return RequestProfile(
        mode=mode,
        complexity=complexity_of(query),
        needs_tools=bool(needs_tools),
        needs_stream=bool(needs_stream),
        needs_reasoning=False,      # V2.3 无推理需求方，见模块 docstring
    )


def _clause_count(text: str) -> int:
    """句子级子句数：按分隔符切完再剔掉空段（「A。」不是两句）。"""
    pieces = [text]
    for separator in CLAUSE_SEPARATORS:
        pieces = [piece for part in pieces for piece in part.split(separator)]
    return sum(1 for piece in pieces if piece.strip())

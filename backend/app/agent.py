from __future__ import annotations

import json
import time
from typing import Any, Literal, NamedTuple

# --------------------------------------------------------------------------
# D6「单一出口」豁免项（Model Router V2.3 Task 8 迁移后**仍然存在**）：与 `app/rag.py`
# 文件头那段同形，Task 9 的静态扫描要把本文件列进 legacy 豁免清单，命中面逐枚可查——
#
#   1. `import httpx`（紧跟本段注释的那一行）
#   2. `_ollama_chat` 里 `LLM_ROUTER_ENABLED=false` 那一条 Ollama 原生聊天端点的
#      `httpx.post` 分支（端点路径字面量只有那一行里的**一枚**）
#
# 合计（**AST 口径**，Task 8 复审 m-1/m-2 的更正版）：httpx 代码命中 2 处 / 端点路径
# 字面量 1 处 / 读 `ollama_base_url` 1 处 / `httpx.stream|Client|get` 0 处。这五项由
# `AgentLegacyBranchTests.test_d6_exemption_inventory_for_agent_py` 按**等式**钉住，
# Task 9 的 D6 豁免表**只抄这五项**。
# 全文（含散文）的 `httpx` 字样行数与代码命中数**天然不相等**（本段自己就写了好几处），
# 旧版本这里声称「全文扫描与代码扫描同数」是错的：那句被本段自己的文本反证。散文计数
# 不是义务面，谁要引用就现算（`grep -c httpx`），别把它抄进豁免表。
#
# 它们**不是**漏迁：`LLM_ROUTER_ENABLED=false` 是 V2.3 的紧急回退口（DESIGN §1 + §7 +
# 验收矩阵 **#18「legacy 回退三链原行为」**）。#18 在 agent 这条链上的对照物**只有**这一
# 条原样保留的 httpx 路（§9.1：对话链流式腿已因 `native_stream.py` 退役而无 legacy 形态），
# 把它改写成 `llm.complete()` 就等于把 #18 的最后一张基准牌也烧掉——`AgentLegacyBranchTests`
# 正是拿它当报文面基准的。
# 删除时机与 rag.py 同一个裁定：DESIGN §1 冻结的义务是「下一稳定版必须删除 legacy 路径」，
# 那一次删除同时带走 `import httpx` 与这条 `httpx.post` 分支，并由 Task 9 的守卫测试在
# 那之后断言本文件零命中。本轮（Task 8）不提前删。
# --------------------------------------------------------------------------
import httpx

from app import llm
from app.agent_trace import attach_model_route, new_trace_id, public_args, save_trace, utc_now
from app.knowledge_os import build_stage_events
from app.audit import record_event
from app.auth import CurrentUser
from app.config import settings
from app.knowledge import allowed_for, effective_allowed_from_grant, visible_bases_by_ids
from app.llm.models import LLMResponse, RequestProfile
from app.llm.router import NoCapableModelError
from app.security import (
    public_exception_detail,
    public_typesafe_metrics,
    redact_secrets,
    redact_text,
)
from app.tools.base import AgentMode, ToolContext, ToolExecutionError
from app.tools.registry import tool_registry

AGENT_SYSTEM_PROMPT = """You are yaoke Agent running with the local Ornith model.
You may answer simple conversation directly, but factual enterprise or current external questions should use tools.
Rules:
1. Internal policies, HR, product parameters, sales rules and after-sales SOPs: use enterprise_search.
2. Current public news, public releases, industry trends or external facts: use web_search when the current mode allows it.
3. Never use public web results to override internal enterprise policy. Enterprise evidence has priority for internal facts.
4. Never claim access to data a tool denied. Authorization belongs to the backend, not to you.
5. Cite evidence with [1], [2], etc. using the citation_index returned by tools. Do not invent citation numbers.
6. If evidence is insufficient, say so clearly instead of fabricating.
7. Do not reveal chain-of-thought or hidden reasoning. Only return the final answer and tool calls supported by the API.
8. Output-language hard constraint: the user-facing final answer — including refusals and error notes — is ALWAYS written in Simplified Chinese (简体中文), no matter which language the question uses. Citation markers keep the [1], [2] form. 无论用户使用何种语言提问，面向用户的最终答案语言为中文。
9. 证据不足时必须以中文输出拒答说明，不得切换成英文或其他语言，也不得编造答案。参考固定话术：当前知识库中没有找到可以回答该问题的资料，请补充更多信息或换个问法。
"""

#: Model Router V2.3 Task 8：agent 链的**现网采样温度 = 0.2**，出处是本文件迁移前
#: `_ollama_chat` 报文里的 `"options": {"temperature": 0.2}`（`agent.py:65`，快照见
#: `baseline-app/agent.py`），**与 `app/rag.py` 那条链的 0.1 无关**（DESIGN §9.1 第二段的
#: 同一口径：给本链套 0.1 属于未声明的行为变更）。命名手法照 T7 的
#: `CONVERSATION_LEGACY_TEMPERATURE`：本链自己的常量，不依赖 `LLMRequest.temperature`
#: 的字段默认（0.2）**也不依赖 `llm.complete(temperature=...)` 的形参默认（同为 0.2）**——
#: 两个默认值都「碰巧」等于现值，漏传参数在报文面上完全不可见，所以本链的**两轮两腿**
#: （工具轮 / 合成轮 / D2 降级合成腿）都显式传它，并由
#: `tests/test_model_router_v23_contract.py` 的 `AgentTemperatureEquivalenceTests` 各钉
#: 两个面：①报文面 `options.temperature` 的三枚等式（产品常量 / 独立写死的 0.2 / != 0.1），
#: ②调用面 kwargs spy 断言 `"temperature" in kwargs`。legacy 那条 httpx 分支**照原样保留
#: 字面量 0.2**（#18 的对照物要求报文逐字不变，rag.py 的 T6 先例同此）。
AGENT_LEGACY_TEMPERATURE = 0.2

#: D2 降级腿（无工具直执行企业检索后的合成）追加的系统段。措辞与
#: `app/conversation_agent.py::_local_fast_path` 的现网那段同源（「后端已经执行过
#: enterprise_search / 不要再调工具 / 只依据 AUTHORIZED_ENTERPRISE_EVIDENCE 回答 /
#: 输出语言硬约束」），但**不 import 那份 prompt**：那一支的证据是塞进 *system* 段的
#: `AUTHORIZED_ENTERPRISE_EVIDENCE=<json>`，而 `run_agent` 这里已经有整条工具回路的
#: messages，只能再追加一段；两处各自演进比互相偷渡更可控。
#: 为什么证据走 system 段而不是 `{"role": "tool"}` 消息：本轮降级**没有**assistant 的
#: tool_calls 轮次，Ollama 对「没有前置工具调用的 tool 消息」会直接 400，那等于把 D2
#: 要求的「不得 500/503」换成一次真实的外呼失败。
_FAST_PATH_DEGRADE_PROMPT = (
    "Mode=local fast path (router returned NO_CAPABLE_MODEL). The backend already executed"
    " enterprise_search. Do not call tools. Answer the CURRENT question only from"
    " AUTHORIZED_ENTERPRISE_EVIDENCE below."
    " 输出语言硬约束：最终答案与拒答说明一律使用简体中文（无论用户提问语言），"
    "证据不足时参考固定话术：当前知识库中没有找到可以回答该问题的资料。"
)


class RouteOutcome(NamedTuple):
    """一次**经过路由的**生成回合留下的执行面事实（供 `attach_model_route` 消费）。

    `_ollama_chat` 对外仍然只交回 message dict（pre-flight 冻结：循环体零改），所以
    `FallbackResult` 与本次画像另走这只盒子：调用方传一个 list 进来，本文件往里塞一条。
    刻意不返回 `(message, result)` 二元组：那会改掉 `_ollama_chat` 的对外形状，而
    `app/conversation_agent.py`（矩阵 #18 的 legacy 腿）和 `scripts/*` 都按 dict 消费它。
    """

    result: Any
    profile: RequestProfile


def _mode_prompt(mode: AgentMode) -> str:
    if mode == "local":
        return "Mode=local. Web search is forbidden. Use enterprise_search for factual knowledge questions."
    if mode == "web":
        return "Mode=web. Use web_search for current/external facts; use enterprise_search for internal company facts."
    return "Mode=auto. Choose enterprise_search for internal facts and web_search only when public/current information is needed."


def _ollama_chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    trace_id: str | None = None,
    route_out: list["RouteOutcome"] | None = None,
) -> dict[str, Any]:
    """一次非流式生成回合，返回**现行 message dict 形状**（`content` + `tool_calls`）。

    两条出口（矩阵 #18 的双路契约）：

    * `llm.router_enabled()` ⇒ `_chat_via_router`：`llm.complete(mode="agent",
      needs_tools=bool(tools))`，tool_calls 由 §6 的 `LLMResponse.tool_calls` 标准化后
      回填成同一形状（pre-flight 冻结：转换在 llm 层完成，回填在**本函数**完成，
      `run_agent` 的循环体因此零改）。
    * 旗标关掉 ⇒ 下面这段**原样保留**的 httpx 报文（一条字节都没改，含空 `tools` 也带键、
      `think`/`keep_alive`/`options` 的形状、以及 `message` 缺失时的同一句 RuntimeError 文案）。

    逐轮开关（tool_routing vs synthesis 两套 settings）在**分支之前**算一次，两条出口
    吃同一对值：这正是 `routing_turn = bool(tools)` 这枚钉子存在的原因——把开关挪进某一条
    分支里，另一条就会悄悄换档。
    """
    # Routing turns benefit from model reasoning. Evidence-only synthesis (no tools)
    # should be fast, bounded and keep the already-loaded local model resident.
    routing_turn = bool(tools)
    think = settings.agent_think_tool_routing if routing_turn else settings.agent_think_synthesis
    num_predict = (
        settings.agent_num_predict_tool_routing
        if routing_turn
        else settings.agent_num_predict_synthesis
    )
    if llm.router_enabled():
        return _chat_via_router(
            messages, tools, think=think, num_predict=num_predict,
            trace_id=trace_id, route_out=route_out)
    payload: dict[str, Any] = {
        "model": settings.ollama_model,
        "stream": False,
        "think": bool(think),
        "keep_alive": settings.ollama_keep_alive,
        "messages": messages,
        "tools": tools,
        "options": {
            "temperature": 0.2,
            "num_predict": int(num_predict),
        },
    }
    response = httpx.post(
        settings.ollama_base_url.rstrip("/") + "/api/chat",
        json=payload,
        timeout=settings.agent_llm_timeout_seconds,
    )
    response.raise_for_status()
    message = response.json().get("message")
    if not isinstance(message, dict):
        raise RuntimeError("Ollama 返回缺少 message")
    return message


def _chat_via_router(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    think: bool,
    num_predict: int,
    trace_id: str | None,
    route_out: list["RouteOutcome"] | None,
) -> dict[str, Any]:
    """router 腿（§9）：统一出口 `llm.complete(mode="agent")`，**零本地 HTTP**。

    `needs_tools=bool(tools)` 由 `profile` 携带（§4：mode 由调用点声明、禁 LLM 判路由）。
    出厂注册表 + 无云 key 时这条画像**必然**零候选（本地两条 `tools=false` 且 `tools`
    档 priority=0，§5 的 capability/preference 双保险）⇒ `NoCapableModelError` 原样上抛，
    由 `run_agent` 承接 D2 降级：本函数**不**吞、也不自己换模式重发（降级是调用链的权利，
    见 `app/llm/__init__.py::complete` 的「一律透传不吞」）。
    """
    profile = llm.classify(
        _classification_query(messages), mode="agent", needs_tools=bool(tools))
    result = llm.complete(
        messages,
        mode="agent",
        temperature=AGENT_LEGACY_TEMPERATURE,
        tools=list(tools),
        think=bool(think),
        num_predict=int(num_predict),
        keep_alive=settings.ollama_keep_alive,
        needs_stream=False,
        trace_id=trace_id,
        profile=profile,
    )
    if route_out is not None:
        route_out.append(RouteOutcome(result=result, profile=profile))
    return _message_from_response(result.response)


def _synthesize_without_tools(
    messages: list[dict[str, Any]],
    *,
    trace_id: str | None,
    route_out: list["RouteOutcome"] | None = None,
) -> str:
    """D2 降级腿的合成：**没有工具 schema 的一次生成**，画像是 `mode="rag"`。

    为什么不复用 `_chat_via_router`（即不用 `mode="agent"` + 空 tools）：§5 的
    `CAPABILITY_BY_MODE` 里 `agent ⇒ tools`，零候选的根因就是这条链要 tools 能力，
    拿同一个画像重发只会再抛一次同一个异常（然后要么递归要么 500）。`rag` 是本仓库里
    「依据已授权证据作答」的既有档位，也正是 T7 给对话链非流式腿选的同一枚画像
    （`conversation_agent.py` 的 buffered 腿）。温度仍是**本链**的 0.2，两腿同值。
    全链失败时这里上抛 `AllCandidatesFailedError`，语义与 legacy 的 httpx 异常一样：
    交给路由层兜底文案，本文件不静默换文案。
    """
    profile = llm.classify(
        _classification_query(messages), mode="rag", needs_tools=False)
    result = llm.complete(
        messages,
        mode="rag",
        temperature=AGENT_LEGACY_TEMPERATURE,
        think=bool(settings.agent_think_synthesis),
        num_predict=int(settings.agent_num_predict_synthesis),
        keep_alive=settings.ollama_keep_alive,
        needs_stream=False,
        trace_id=trace_id,
        profile=profile,
    )
    if route_out is not None:
        route_out.append(RouteOutcome(result=result, profile=profile))
    return str(result.response.content or "").strip()


def _classification_query(messages: list[dict[str, Any]]) -> str:
    """分类器读的问题文本 = **最后一条有内容的消息**（与 `llm._query_of` 同一口径）。

    只看最后一条是刻意的（同 `app/llm/__init__.py::_query_of` 的理由）：整段拼接会把
    工具回执的几千字算进复杂度判定，那测的就不再是「这一轮难不难」。
    """
    for message in reversed(list(messages or [])):
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
    return ""


def _message_from_response(response: LLMResponse) -> dict[str, Any]:
    """`LLMResponse` → 现行 Ollama message dict（§6 标准化之后的回填）。

    `tool_calls` 的唯一来源是 **`response.tool_calls`（`ToolCall` 三元组）**，不再读
    provider 的原始 JSON：`arguments` 已在 normalize 层从「字符串或 dict」收敛成 dict，
    所以本文件这一侧不需要再 `json.loads` 一次（那是迁移前的手写路径，见
    `_tool_arguments` 的存留理由）。`id` 逐条带回：Ollama 不回 id 时它是空串（§6 冻结，
    不许假设唯一）。空列表也带键：让「有没有工具轮」在形状上可判定，而不是靠缺键。
    """
    calls = [
        {
            "id": call.id,
            "type": "function",
            "function": {"name": call.name, "arguments": dict(call.arguments)},
        }
        for call in response.tool_calls
    ]
    return {
        "role": "assistant",
        "content": response.content,
        "tool_calls": calls,
    }


def _tool_arguments(call: Any) -> tuple[str, dict[str, Any]]:
    """tool_calls 条目 → `(name, arguments)`。两条来源共用这一个读取器。

    为什么不删（Task 8 的 grep 结论：全仓只有 `run_agent` 的两处消费点，无测试直接调用）：
    * **router 腿**给的是 `_message_from_response` 回填的 dict，`arguments` **已经是 dict**
      （§6 的 `ToolCall` 标准化），这里只是把它取出来——这一段两条路都要用，删了就得在
      别处再写一遍。
    * **legacy 腿**（`LLM_ROUTER_ENABLED=false` 的原 httpx 路）交回的是 provider 原始
      message，`arguments` 可能是 **JSON 字符串**（OpenAI 协议恒为字符串、老版 Ollama 也是），
      下面那段 `json.loads` + 「坏 JSON/非对象 ⇒ `{}`」的退化口径就是它原来挡的东西：
      模型给了半截 JSON 时让工具自己报缺参，而不是让整条 agent 链崩成 503。
    换句话说：**解析职责已上移到 normalize（新链路），本函数只剩「取值 + 兼容 legacy 形状」**。
    下一稳定版随 legacy 分支一起瘦身（届时字符串分支可删）。
    """
    function = call.get("function") if isinstance(call, dict) else None
    if not isinstance(function, dict):
        return "", {}
    name = str(function.get("name") or "")
    arguments = function.get("arguments") or {}
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            arguments = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            arguments = {}
    return name, arguments if isinstance(arguments, dict) else {}


def _evidence_key(item: dict[str, Any]) -> tuple[Any, ...]:
    if item.get("source_type") == "web":
        return ("web", item.get("url"))
    return (
        "enterprise",
        item.get("knowledge_base_id"),
        item.get("file_name"),
        item.get("page"),
        str(item.get("content") or "")[:120],
    )


def _public_source(item: dict[str, Any]) -> dict[str, Any]:
    preview = str(item.get("content") or "")[:420]
    if item.get("source_type") == "web" and item.get("url"):
        preview = f"{preview}\n{item['url']}"
    return redact_secrets({
        "citation_index": item.get("citation_index"),
        "source_type": item.get("source_type", "enterprise"),
        "title": item.get("title") or item.get("file_name"),
        "file_name": item.get("file_name") or item.get("title") or "来源",
        "page": item.get("page"),
        "content_preview": preview,
        "relevance_score": item.get("relevance_score"),
        "knowledge_base_id": item.get("knowledge_base_id"),
        "knowledge_base_name": item.get("knowledge_base_name"),
        "url": item.get("url"),
        "domain": item.get("domain"),
    })


def _conversation_history(history: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    limit = max(0, int(settings.agent_history_max_messages))
    if limit == 0 or not history:
        return []
    normalized: list[dict[str, str]] = []
    for item in history:
        role = str(item.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        if item.get("status") not in {None, "completed"}:
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        normalized.append({"role": role, "content": content[:4000]})
    return normalized[-limit:]


def _no_capable_event(round_index: int, exc: NoCapableModelError) -> dict[str, Any]:
    """D2 降级在 trace 上的**唯一解释出口**（事件，不是 `model_route`）。

    为什么零候选时没有 `model_route`：§5 的 `NoCapableModelError` 在 `plan()` 阶段抛出，
    既没有 `RoutePlan` 也没有 attempts，而 `model_route` 的九键**唯一生产者**是
    `app.llm.usage.model_route_trace()`（§8.1 第 4 条）——它要求 `RoutePlan` 入参，
    在这里凭空造一份就等于造第二个生产者。更要紧的是 T5 裁定的「零候选不产账行」
    （零外呼 ⇒ `llm_request_logs` 里没有这一笔），于是这条事件是运维**唯一**能看到
    「这次为什么走 fast path」的地方。字段全是机器码（`stage` / 理由码 / 画像摘要），
    不含问题文本（D3）。
    """
    return {
        "type": "model_route_downgrade",
        "timestamp": utc_now(),
        "round": round_index,
        "note": "NO_CAPABLE_MODEL→fast_path",
        "reason_codes": list(exc.reason_codes),
        "stage": exc.stage,
        "action": "fast_path",
        "tool": "enterprise_search",
        "profile": exc.profile_summary,
    }


def _fast_path_copy_event(round_index: int, *, note: str, tool_status: str) -> dict[str, Any]:
    """I-3：三支**硬文案短路**在 trace 上的注记（与 `_no_capable_event` 同一 type）。

    为什么要第二枚注记：第一枚解释的是「路由零候选」，这一枚解释的是「零候选之后
    **连合成都没有发生**」。DENIED / 检索失败 / 零证据三支按对话链 `_local_fast_path`
    的同源口径一次模型都不调 ⇒ 既没有 `model_route`（没跑过路由）也没有账行（零外呼），
    于是这枚 note 是「这一行答案为什么是后端文案」的唯一出口。`reason_codes` 仍只写
    冻结枚举里的那枚 `NO_CAPABLE_MODEL`（PLAN Global Constraints 的 reason codes 清单），
    区分三支的事实放在 `note` 与 `tool_status` 里，不新增机器码词表。
    """
    return {
        "type": "model_route_downgrade",
        "timestamp": utc_now(),
        "round": round_index,
        "note": note,
        "reason_codes": ["NO_CAPABLE_MODEL"],
        "stage": "copy_shortcut",
        "action": "fast_path",
        "tool": "enterprise_search",
        "tool_status": tool_status,
    }


def _degraded_with_evidence_event(round_index: int, *, tool_status: str) -> dict[str, Any]:
    """N-3：本轮检索失败、但**在手证据非空**因而继续合成时的那枚注记。

    与 `_fast_path_copy_event` 同一 `type`、同一枚冻结理由码，区别只在 `stage`：那一枚是
    `copy_shortcut`（连生成都没走到），这一枚是 `degraded_synthesis`（走了生成，只是不
    再重跑检索）。为什么必须留一行：本轮失败这件事已经进了 `tool_end` 事件与 TOOL_RESULT
    审计，但「这一行答案是**前轮**证据合成的」在 trace 上否则只能靠反推。理由码仍只用
    冻结枚举里的那枚 `NO_CAPABLE_MODEL`（PLAN Global Constraints），区分事实放在 `note`
    与 `tool_status` 里，不新增机器码词表。
    """
    return {
        "type": "model_route_downgrade",
        "timestamp": utc_now(),
        "round": round_index,
        "note": "NO_CAPABLE_MODEL→fast_path_failed_with_evidence",
        "reason_codes": ["NO_CAPABLE_MODEL"],
        "stage": "degraded_synthesis",
        "action": "fast_path",
        "tool": "enterprise_search",
        "tool_status": tool_status,
    }


def _synthesize_with_second_door(
    messages: list[dict[str, Any]],
    *,
    round_index: int,
    trace_id: str,
    events: list[dict[str, Any]],
    route_out: list["RouteOutcome"],
) -> str:
    """C-1：**降级腿自己那次合成**也可能是零候选的那一条路，必须有第二道 catch。

    缺它会发生什么（Task 8 复审 C-1，实测两次）：`_degrade_to_local_fast_path` 往 messages
    里追加的证据 dump 上限是 16000 字符，而出厂两条本地条目 `context_tokens=8192`，
    §5（Task 4 修订）的上下文粗估口径是 `sum(len(str(m)) for m in messages)/2` ⇒ 一次普通
    提问 + 稍长证据就能把 rag 画像也剔成零候选，`NoCapableModelError(stage="context")`
    从**except 块内部**穿出 `run_agent` ⇒ `agent_routes.py` 兜成 503、`save_trace` 与
    `QUERY` 审计都不执行（审计只剩 TOOL_CALL+TOOL_RESULT 的孤儿对）、那条唯一解释出口
    随之消失。D2 冻结的是「不得 500/503、答案仍交付」，这里两条同时断。

    修法刻意不改文案：交回空串，由 `run_agent` 既有的收尾判据（`if not final_answer:`）
    补那句中文文案 ⇒ 对外文案面零新增、trace 落**一行**且带**两枚**注记、审计成对。
    两支降级门（工具回路 + 工具轮次耗尽的收尾腿）都走这一个出口，不再各写一份。
    """
    try:
        return _synthesize_without_tools(messages, trace_id=trace_id, route_out=route_out)
    except NoCapableModelError as second_exc:
        events.append(_no_capable_event(round_index, second_exc))
        return ""


def _degrade_to_local_fast_path(
    *,
    question: str,
    user: CurrentUser,
    grant_scope: list[str] | None,
    trace_id: str,
    knowledge_base_id: str | None,
    top_k: int,
    rerank: bool,
    round_index: int,
    messages: list[dict[str, Any]],
    events: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    evidence_keys: dict[tuple[Any, ...], int],
    retrieval_timings: dict[str, Any],
    typesafe_timings: dict[str, Any],
    route_out: list["RouteOutcome"],
    tool_time: dict[str, float],
) -> str:
    """D2 的降级本体：等价 local fast-path（**无工具**直执行企业检索 + tools-free 合成）。

    与 `app/conversation_agent.py::_local_fast_path` **同源但不复用**：那一支自带
    `new_trace_id()` + `save_trace()` + 自己的 `mode="local"` 响应体，而本函数是在
    `run_agent` 已有的 trace_id / 事件流 / evidence 去重表里就地降级。复用它的后果是
    一次用户提问落**两条** trace 行（且响应里的 trace_id 与 `NO_CAPABLE_MODEL→fast_path`
    那条注记不在同一行上），而那条注记正是零候选唯一的解释出口——`conversation_agent.py`
    在 Task 8 是**禁改文件**，也没法把注记塞进它的 trace。
    共用的是同一套机器件：`tool_registry.execute` / `ToolContext` / `record_event` 两笔
    审计 / `redact_secrets` / `public_typesafe_metrics`，所以审计面与来源面和现网同形。

    「同一条 D2 义务的两个入口变体」的**六项统一口径**（Task 8 复审 §6 裁定）里，本函数
    负责的四项：①工具执行权在后端（`ToolContext(mode="local",
    allowed_knowledge_base_ids=<run_agent 顶部解析一次的 grant_scope>)` ⇒ web 证据按构造
    拿不到）；②审计成对且**必须有 `QUERY` 收尾行**（C-1 的第二道 catch 就是为这一条）；
    ③计时归因：检索耗时走 `tool_time` 盒子、**不并进** `llm_ms`/`generation` stage（I-2）；
    ④文案短路：**DENIED**（不吃门）/「检索失败**且手上没货**」/ 零证据三支走同源硬文案且
    **零外呼**（I-3）；本轮失败但在手有授权证据时**不短路**，继续合成（N-3，与 `status !=
    "SUCCESS" and not evidence` 那支逐字对齐）；降级腿自己再遇零候选时给收尾中文文案、
    **绝不 503**（C-1）。①③④缺任何一项都不是「等价降级」。
    """
    arguments: dict[str, Any] = {"query": question.strip(), "top_k": top_k}
    if knowledge_base_id:
        arguments["knowledge_base_id"] = knowledge_base_id
    safe_arguments = public_args(arguments)
    events.append(
        {
            "type": "tool_start",
            "timestamp": utc_now(),
            "round": round_index,
            "tool": "enterprise_search",
            "arguments": safe_arguments,
            "degraded": True,
        }
    )
    record_event(
        username=user.username,
        role=user.role,
        action="TOOL_CALL",
        query=question[:240] or None,
        detail=f"tool=enterprise_search;trace_id={trace_id};args={json.dumps(safe_arguments, ensure_ascii=False)};degraded=true",
    )

    tool_started = time.perf_counter()
    status = "SUCCESS"
    try:
        # `mode="local"`：降级腿**按构造**没有 web 证据可拿（web_search 在 local 档被后端
        # 拒绝），这与 D2 的「无工具直执行企业检索」是同一件事，不是顺手收紧权限。
        result = tool_registry.execute(
            "enterprise_search",
            arguments,
            ToolContext(
                username=user.username,
                role=user.role,
                mode="local",
                trace_id=trace_id,
                selected_knowledge_base_id=knowledge_base_id,
                top_k=top_k,
                rerank=rerank,
                # **复用** `run_agent` 顶部算好的那一份：`effective_allowed_from_grant`
                # 每请求只许解析一次（`test_feishu_identity_contract` 的等式钉着计数=1），
                # 降级腿再算一遍就是热路径上的重复判定。
                allowed_knowledge_base_ids=grant_scope,
            ),
        )
        for item in result.get("evidence", []):
            key = _evidence_key(item)
            if key not in evidence_keys:
                evidence_keys[key] = len(evidence) + 1
                item = dict(item)
                item["citation_index"] = evidence_keys[key]
                evidence.append(item)
            else:
                item["citation_index"] = evidence_keys[key]
        result = redact_secrets(dict(result))
        typesafe_timings.update(public_typesafe_metrics(result.get("timings")))
        result["evidence"] = [
            {**item, "citation_index": evidence_keys.get(_evidence_key(item))}
            for item in result.get("evidence", [])
        ]
    except ToolExecutionError as exc:
        status = exc.status
        result = {"ok": False, "tool": "enterprise_search", "status": exc.status,
                  "error": redact_text(exc), "evidence": []}
    except Exception as exc:                       # 与工具回路的 catch-all 同宽（#18）
        status = "FAILED"
        result = {"ok": False, "tool": "enterprise_search", "status": "FAILED",
                  "error": public_exception_detail(exc), "evidence": []}

    latency_ms = (time.perf_counter() - tool_started) * 1000
    # I-2：这只**可变盒子**把降级腿那次检索的真实推进量交回 `run_agent` 的收尾算式
    # （`tool_time_total` 是它的局部标量，本函数拿不到）。不接进盒子的后果是出厂形态下
    # **每一次** `stage_timings["llm_ms"]` 都虚高一整次检索（复审实测：400ms 工具被记成
    # 426ms 生成），Query Trace / SSE stage 重排的「生成」行长期失真、p95 跟着歪。
    # 手法与 `retrieval_timings` / `events` 同一套：调用方传盒子进来，本函数往里塞。
    tool_time["enterprise_search"] = latency_ms
    current_typesafe_timings = public_typesafe_metrics(result.get("timings"))
    if status == "SUCCESS" and isinstance(result.get("timings"), dict):
        for timing_key in (
            "vector_ms", "bm25_ms", "fusion_ms", "rerank_ms", "diversity_ms",
            "total_ms", "bm25_cache_hit", "fusion", "vector_candidates",
            "bm25_candidates", "returned_documents",
        ):
            if result["timings"].get(timing_key) is not None:
                retrieval_timings[timing_key] = result["timings"][timing_key]
    result_count = len(result.get("evidence", []))
    tool_end_event: dict[str, Any] = {
        "type": "tool_end",
        "timestamp": utc_now(),
        "round": round_index,
        "tool": "enterprise_search",
        "status": status,
        "latency_ms": round(latency_ms, 2),
        "result_count": result_count,
        "degraded": True,
    }
    if current_typesafe_timings:
        tool_end_event["timings"] = current_typesafe_timings
    events.append(tool_end_event)
    record_event(
        username=user.username,
        role=user.role,
        action="TOOL_RESULT",
        status=status,
        knowledge_base_id=str(knowledge_base_id or "all"),
        latency_ms=latency_ms,
        num_sources=result_count,
        detail=f"tool=enterprise_search;trace_id={trace_id};degraded=true",
    )

    # I-3（等价性收口，安全相邻）：**同源三支硬文案短路**，逐字引
    # `app/conversation_agent.py:316-321` 的那三句。缺一支就等于把 RBAC 拒绝面从
    # 「后端硬文案」降成「模型自律 + 提示词约束」：工具回路的 catch-all 语义（把错误
    # JSON 塞回上下文让模型继续）属于「模型自己选了工具」的正常轮，而降级腿是**后端替
    # 模型执行了工具**，权威形态在这里明确短路、一次模型都不调。
    # 短路时 `route_out` 不塞盒子 ⇒ trace 也不挂 `model_route`（与对话链 307-310 的注释
    # 同一条口径：没走到生成就没有执行面事实可解释）。
    copy_note = ""
    fast_path_copy = ""
    if status == "DENIED":
        # I-3 的 RBAC 拒绝面：**不吃**下面那枚 N-3 的门。即使前几轮已经有在手证据，
        # 这一支仍然零外呼 + 同源硬文案（`DENIED` 与「本轮检索失败」是两件事，合并短路
        # 就是拿拒绝面换一致性）。承载用例：
        # `AgentNoCapableFastPathTests::test_a_denied_current_round_keeps_the_hard_copy_even_with_evidence_in_hand`。
        fast_path_copy = "当前账号无权访问该知识库，因此不能基于未授权资料回答。"
        copy_note = "NO_CAPABLE_MODEL→fast_path_denied"
    elif status != "SUCCESS" and not evidence:
        # N-3（Task 8 修复轮复审）：**本轮失败且手里没货**才用失败文案。权威实现
        # `conversation_agent.py:316-321` 那三支的条件是「本轮检索结果」——`status` 与
        # `evidence` 都只来自它自己那一次 `tool_registry.execute`（`:232-275`），而
        # `_local_fast_path` 只有 round 0、没有工具回路，对它而言「本轮 == 全链路」，
        # 两种读法等价。本函数继承同一判据时语义就分叉了：这里的 `evidence` 是
        # `run_agent` 传进来的**累加盒**（工具回路每轮 append、`evidence_keys` 去重），
        # 「前轮已拿到授权证据 + 本轮失败」时会一边回「检索失败」一边把 `num_sources`
        # 记成在手的量（收尾处 `len(evidence)`），与 `run_agent` 的 D2 catch 里
        # `stage == "context"` 那支自家理由（"证据已在手 ⇒ 直接走 tools-free 合成"）
        # 自相矛盾。刻意**不写裸行号**（Task 9 评审 m-2：那种自指一改就漂）：按函数名 +
        # 分支条件定位。出厂注册表 100% 走 D2 ⇒ 今天不显形；配云 key 或新增 `tools=true`
        # 条目后这就是常态路径。
        fast_path_copy = "企业知识检索暂时失败，请稍后重试。"
        copy_note = "NO_CAPABLE_MODEL→fast_path_failed"
    elif not evidence:
        fast_path_copy = "当前授权范围内没有检索到足够证据，暂时无法可靠回答。"
        copy_note = "NO_CAPABLE_MODEL→fast_path_no_evidence"
    if copy_note:
        events.append(_fast_path_copy_event(round_index, note=copy_note, tool_status=status))
        events.append(
            {
                "type": "final",
                "timestamp": utc_now(),
                "round": round_index,
                "answer_preview": fast_path_copy[:400],
                "degraded": True,
            }
        )
        return fast_path_copy

    # N-3 的另一半：本轮失败/异常时 `result["evidence"]` 是错误 dict 里的空壳，货在
    # `evidence` 这只累加盒里 ⇒ dump 取「本轮有货用本轮的，否则用在手的」。成功支的
    # 本轮 dump 与旧行为逐字相同（只有「本轮无货 + 手上有货」才是新形状，那正是过去
    # 被失败文案糊掉的那一支）。
    synthesis_evidence = list(result.get("evidence") or []) or list(evidence)
    if status != "SUCCESS" and synthesis_evidence:
        events.append(_degraded_with_evidence_event(round_index, tool_status=status))
    messages.append(
        {
            "role": "system",
            "content": _FAST_PATH_DEGRADE_PROMPT + "\nAUTHORIZED_ENTERPRISE_EVIDENCE="
            + json.dumps(synthesis_evidence, ensure_ascii=False)[:16000],
        }
    )
    # C-1：这次合成自己也可能是零候选的那一条路（证据 dump 上限 16000 字符 vs 出厂
    # 两条本地条目 `context_tokens=8192` ⇒ 一次普通提问就能把 rag 画像也剔空）。
    answer = _synthesize_with_second_door(
        messages, round_index=round_index, trace_id=trace_id,
        events=events, route_out=route_out)
    events.append(
        {
            "type": "final",
            "timestamp": utc_now(),
            "round": round_index,
            "answer_preview": answer[:400],
            "degraded": True,
        }
    )
    return answer


def run_agent(
    *,
    question: str,
    user: CurrentUser,
    mode: AgentMode = "auto",
    knowledge_base_id: str | None = None,
    top_k: int = 5,
    rerank: bool = False,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if mode not in {"local", "auto", "web"}:
        raise ValueError("无效 Agent 模式")

    trace_id = new_trace_id()
    started = time.perf_counter()
    # 每请求解析一次知识范围：allowed 供 trace 与提示词，grant_scope 供工具层
    # （None = 无有效授予，工具层继续按本地 role 判定）。
    allowed = allowed_for(user)
    grant_scope = effective_allowed_from_grant(user.grant)
    visible = ", ".join(f"{item['id']}={item['name']}" for item in visible_bases_by_ids(allowed))
    history_messages = _conversation_history(history)
    system = (
        AGENT_SYSTEM_PROMPT
        + "\n"
        + _mode_prompt(mode)
        + f"\nCurrent role={user.role}; backend-authorized KBs: {visible}."
        + " Do not assume any KB outside this list is accessible."
        + (" Use recent conversation messages only to resolve follow-up references; current tool evidence remains authoritative." if history_messages else "")
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        *history_messages,
        {"role": "user", "content": question.strip()},
    ]
    schemas = tool_registry.schemas(mode)
    events: list[dict[str, Any]] = [
        {
            "type": "user",
            "timestamp": utc_now(),
            "mode": mode,
            "question_preview": question[:240],
            "allowed_knowledge_base_ids": allowed,
            "context_messages": len(history_messages),
        }
    ]
    evidence: list[dict[str, Any]] = []
    evidence_keys: dict[tuple[Any, ...], int] = {}
    typesafe_timings: dict[str, Any] = {}
    retrieval_timings: dict[str, Any] = {}
    tool_time_total = 0.0
    # I-2：降级腿那次 `enterprise_search` 的推进量走这只盒子回来（`tool_time_total` 只
    # 收工具回路里的账，降级函数拿不到它），收尾处一起从 `llm_ms` 里扣掉。
    tool_time_box: dict[str, float] = {}
    final_answer = ""
    # 执行面事实（矩阵 #17 的 agent 半边）：只收**经过路由**的回合。legacy 旗标关掉时
    # 这里永远是空的 ⇒ `attach_model_route` 不挂、trace 形状与迁移前逐字相同（#18）。
    outcomes: list[RouteOutcome] = []
    max_rounds = max(1, min(int(settings.agent_max_tool_rounds), 6))

    for round_index in range(1, max_rounds + 1):
        round_outcomes: list[RouteOutcome] = []
        try:
            message = _ollama_chat(messages, schemas, trace_id=trace_id,
                                   route_out=round_outcomes)
        except NoCapableModelError as exc:
            # D2（§5 冻结）：零候选是**降级路径**，不是错误。`app/llm` 层刻意透传不吞，
            # 权利在这条链上：记一条 `NO_CAPABLE_MODEL→fast_path` 事件 + 无工具直执行
            # 企业检索 + 一次 tools-free 合成，**不得 500/503**。
            # 注意 `AllCandidatesFailedError` / 硬终态 `LLMError` **不在这里 catch**：
            # 现网（legacy httpx 路）provider 报错同样是异常上抛、由 `agent_routes` 兜成
            # 「Agent 服务不可用：…」，这里换文案或改走 fast path 都是未声明的行为变更。
            events.append(_no_capable_event(round_index, exc))
            if exc.stage == "context":
                # m-6：`stage == "context"` 说明溢出发生在**已经投递的证据**上（前几轮
                # 的工具回执把 messages 撑过了 `context_tokens`）。这时再跑一次
                # `enterprise_search` 就是三笔白付的代价：多一次后端检索、多两条审计、
                # 还要在已经溢出的上下文上继续追加证据 ⇒ 必然二次溢出（C-1 的另一半诱因）。
                # 证据已在手 ⇒ 直接走那次 tools-free 合成（与收尾腿同一个出口、同一道
                # 第二 catch）。
                final_answer = _synthesize_with_second_door(
                    messages, round_index=round_index, trace_id=trace_id,
                    events=events, route_out=outcomes)
                break
            final_answer = _degrade_to_local_fast_path(
                question=question,
                user=user,
                grant_scope=grant_scope,
                trace_id=trace_id,
                knowledge_base_id=knowledge_base_id,
                top_k=top_k,
                rerank=rerank,
                round_index=round_index,
                messages=messages,
                events=events,
                evidence=evidence,
                evidence_keys=evidence_keys,
                retrieval_timings=retrieval_timings,
                typesafe_timings=typesafe_timings,
                route_out=outcomes,
                tool_time=tool_time_box,
            )
            break
        outcomes.extend(round_outcomes)
        tool_calls = message.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            tool_calls = []

        if not tool_calls:
            final_answer = str(message.get("content") or "").strip()
            events.append(
                {
                    "type": "final",
                    "timestamp": utc_now(),
                    "round": round_index,
                    "answer_preview": final_answer[:400],
                }
            )
            break

        messages.append(message)
        decisions: list[str] = []
        for call in tool_calls:
            tool_name, arguments = _tool_arguments(call)
            decisions.append(tool_name or "unknown")
        events.append(
            {
                "type": "model_decision",
                "timestamp": utc_now(),
                "round": round_index,
                "tools": decisions,
            }
        )

        for call in tool_calls:
            tool_name, arguments = _tool_arguments(call)
            tool_started = time.perf_counter()
            safe_arguments = public_args(arguments)
            events.append(
                {
                    "type": "tool_start",
                    "timestamp": utc_now(),
                    "round": round_index,
                    "tool": tool_name,
                    "arguments": safe_arguments,
                }
            )
            record_event(
                username=user.username,
                role=user.role,
                action="TOOL_CALL",
                query=str(arguments.get("query") or "")[:240] or None,
                detail=f"tool={tool_name};trace_id={trace_id};args={json.dumps(safe_arguments, ensure_ascii=False)}",
            )

            context = ToolContext(
                username=user.username,
                role=user.role,
                mode=mode,
                trace_id=trace_id,
                selected_knowledge_base_id=knowledge_base_id,
                top_k=top_k,
                rerank=rerank,
                allowed_knowledge_base_ids=grant_scope,
            )
            status = "SUCCESS"
            try:
                result = tool_registry.execute(tool_name, arguments, context)
                for item in result.get("evidence", []):
                    key = _evidence_key(item)
                    if key not in evidence_keys:
                        evidence_keys[key] = len(evidence) + 1
                        item = dict(item)
                        item["citation_index"] = evidence_keys[key]
                        evidence.append(item)
                    else:
                        item["citation_index"] = evidence_keys[key]
                result = redact_secrets(dict(result))
                typesafe_timings.update(
                    public_typesafe_metrics(result.get("timings"))
                )
                result["evidence"] = [
                    {**item, "citation_index": evidence_keys.get(_evidence_key(item))}
                    for item in result.get("evidence", [])
                ]
            except ToolExecutionError as exc:
                status = exc.status
                result = {"ok": False, "tool": tool_name, "status": exc.status, "error": redact_text(exc), "evidence": []}
            except Exception as exc:
                status = "FAILED"
                result = {"ok": False, "tool": tool_name, "status": "FAILED", "error": public_exception_detail(exc), "evidence": []}

            latency_ms = (time.perf_counter() - tool_started) * 1000
            tool_time_total += latency_ms
            if status == "SUCCESS" and isinstance(result.get("timings"), dict):
                for timing_key in (
                    "vector_ms",
                    "bm25_ms",
                    "fusion_ms",
                    "rerank_ms",
                    "diversity_ms",
                    "total_ms",
                    "bm25_cache_hit",
                    "fusion",
                    "vector_candidates",
                    "bm25_candidates",
                    "returned_documents",
                ):
                    if result["timings"].get(timing_key) is not None:
                        retrieval_timings[timing_key] = result["timings"][timing_key]
            result_count = len(result.get("evidence", []))
            tool_end_event: dict[str, Any] = {
                "type": "tool_end",
                "timestamp": utc_now(),
                "round": round_index,
                "tool": tool_name,
                "status": status,
                "latency_ms": round(latency_ms, 2),
                "result_count": result_count,
            }
            current_typesafe_timings = public_typesafe_metrics(
                result.get("timings")
            )
            if current_typesafe_timings:
                tool_end_event["timings"] = current_typesafe_timings
            events.append(tool_end_event)
            record_event(
                username=user.username,
                role=user.role,
                action="TOOL_RESULT",
                status=status,
                knowledge_base_id=str(arguments.get("knowledge_base_id") or knowledge_base_id or "all") if tool_name == "enterprise_search" else None,
                latency_ms=latency_ms,
                num_sources=result_count,
                detail=f"tool={tool_name};trace_id={trace_id}",
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_name": tool_name or "unknown",
                    "content": json.dumps(result, ensure_ascii=False)[:16000],
                }
            )
    else:
        messages.append(
            {
                "role": "system",
                "content": "Tool-call limit reached. Do not call more tools. Produce a final answer only from tool results already present; cite their citation_index values.",
            }
        )
        # I-1：与主降级门**同形** —— 把 `outcomes` 直接交给这次调用，不再另起一只局部盒
        # 然后指望调用方记得 merge。上一版传的是 `limit_outcomes`，成功支写了
        # `outcomes.extend(limit_outcomes)` 而 except 支漏了 ⇒ 收尾腿降级那次明明真跑过
        # 路由，trace 上却没有 `model_route`（九键是「跑过一次真路由」唯一的解释产物，
        # §8.1 第 4 条），`model_used` 也跟着回落成 `settings.ollama_model`。
        try:
            message = _ollama_chat(messages, [], trace_id=trace_id, route_out=outcomes)
        except NoCapableModelError as exc:
            # 同一枚 D2 义务的第二处落点：这一轮**本来就**不带工具 schema（证据已在
            # messages 里），零候选时的等价降级就是那次 tools-free 合成——同一个出口，
            # 只是不再补 `enterprise_search`（证据已经在手，重复检索才是行为变更）。
            events.append(_no_capable_event(max_rounds + 1, exc))
            # C-1：那次合成自己再抛一次零候选时同样不许穿出 `run_agent`。
            final_answer = _synthesize_with_second_door(
                messages, round_index=max_rounds + 1, trace_id=trace_id,
                events=events, route_out=outcomes)
        else:
            final_answer = str(message.get("content") or "").strip()
        events.append(
            {
                "type": "limit",
                "timestamp": utc_now(),
                "max_tool_rounds": max_rounds,
            }
        )
        events.append(
            {
                "type": "final",
                "timestamp": utc_now(),
                "answer_preview": final_answer[:400],
            }
        )

    if not final_answer:
        final_answer = "当前没有获得足够证据生成可靠答案。"

    elapsed_ms = (time.perf_counter() - started) * 1000
    # `typesafe_timings` 是 `public_typesafe_metrics()` 的产物（已白名单化 + 脱敏），
    # 并入分阶段计时只为一处消费：`build_stage_events` 的重排阶段 detail 要显示判定层
    # 触发/缓存/熔断/跳过四枚子观测（设计 §7）。`timed()` 按各自的键名取值，故多出来的
    # 键不会渗进别的阶段行。
    stage_timings = {**retrieval_timings, **typesafe_timings}
    # I-2：`llm_ms` = 总耗时 −（工具回路那笔 `tool_time_total`）−（降级腿那次检索）。
    # 少了后一项，出厂形态下 agent 链**每一次**的「生成」stage 都含一整次检索。
    model_ms = max(elapsed_ms - tool_time_total - sum(tool_time_box.values()), 0.0)
    if model_ms > 1:
        stage_timings["llm_ms"] = round(model_ms, 2)
    events.extend(
        build_stage_events(
            stage_timings,
            scope_count=1 if knowledge_base_id else 0,
            evidence_count=len(evidence),
        )
    )
    # §9 + T4 移交 M2：`model_used` = **selected 候选的生效模型名**（provider 回显），
    # 没经过路由（legacy 旗标关掉 / 零候选连合成都没走通）时仍是 `settings.ollama_model`
    # ——取值集合与迁移前一致，additive only。
    outcome = outcomes[-1] if outcomes else None
    selected_model = str(
        getattr(getattr(outcome, "result", None), "response", None)
        and outcome.result.response.model or "") if outcome is not None else ""
    model_used = selected_model or settings.ollama_model
    trace = {
        "trace_id": trace_id,
        "timestamp": utc_now(),
        "username": user.username,
        "role": user.role,
        "mode": mode,
        "model": settings.ollama_model,
        "max_tool_rounds": max_rounds,
        "context_messages": len(history_messages),
        "events": events,
        "evidence_count": len(evidence),
        "elapsed_ms": round(elapsed_ms, 2),
    }
    if typesafe_timings:
        trace["timings"] = typesafe_timings
    # 矩阵 #17 的「真调用 + 真落盘九键」这半段归本任务（agent 这条链**有** trace）。
    # 挂载点唯一 = `app.agent_trace.attach_model_route`，九键唯一生产者 =
    # `app.llm.usage.model_route_trace`。取**最后一次**经过路由的回合：trace 要解释的是
    # 「这一行答案是谁生成的」，中间回合的事实在它自己的账行里。
    # 必须在 `save_trace` **之前**：落盘之后再挂就得改 JSONL 语义（追加一行同 trace_id 会
    # 让 `get_trace` 的逆序扫描只看见后一行）。
    if getattr(getattr(outcome, "result", None), "plan", None) is not None:
        attach_model_route(trace, outcome.result.plan, outcome.result, profile=outcome.profile)
    save_trace(trace)
    record_event(
        username=user.username,
        role=user.role,
        action="QUERY",
        knowledge_base_id=knowledge_base_id or "all",
        query=question[:500],
        latency_ms=elapsed_ms,
        num_sources=len(evidence),
        detail=f"agent_mode={mode};trace_id={trace_id}",
    )

    response = {
        "answer": final_answer,
        "query": question,
        "mode": mode,
        "trace_id": trace_id,
        "sources": [_public_source(item) for item in evidence],
        "num_sources": len(evidence),
        "model_used": model_used,
        "max_tool_rounds": max_rounds,
        "context_messages": len(history_messages),
    }
    if typesafe_timings:
        response["timings"] = typesafe_timings
    return redact_secrets(response)

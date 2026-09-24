"""两个协议侧的报文构造与解析（设计 §6：差异全部在 provider 层吸收）。

本文件**纯函数、零 I/O、不 import httpx**：`*_stream_lines()` 接收的是「bytes 分片的可迭代
对象」（`provider.py` 传 `httpx.Response.iter_bytes()`，测试可以直接传 `[b"...", b"..."]`），
所以这里既不依赖 httpx，也不依赖任何具体响应类型——D6「`app/llm/` 内只有 provider.py 出现
httpx」因此是结构性的，不靠扫描豁免维持。

Ollama 侧的形状刻意**逐字平移** `app/agent.py::_ollama_chat`（`model / stream / think /
keep_alive / messages / tools / options{temperature, num_predict}` 的键序与「空 tools 仍然
带键」的现网行为），因为现网那套字段是 Ollama 0.9.x 已验证可用的最小集：
- `tools=[]` 时仍然发送 `"tools": []`：Ollama 对「有键但为空数组」和「无键」在部分版本上
  行为不同（前者会强制关掉工具模板），现网一直在发空数组，改了就是行为变更；
- `think` / `keep_alive` 为 `None` 时**整键省略**：`agent.py` 的两类轮次总是带这两个键
  （值来自 settings），而 `rag.py` 的 legacy 非流式路径完全不发它们。用「可选键」而不是
  「恒发 false / 恒发默认值」才能同时平移两种现网形状，Task 6/8 各自传自己要的值即可；
- `options.temperature` 恒发、`options.num_predict` 仅在请求携带时发：温度唯一来源是
  `LLMRequest.temperature`（本层不注入默认值；rag 链的 legacy 现值 0.1 由调用方携带，
  常量在 `app/llm/__init__.py` 的 `RAG_LEGACY_TEMPERATURE`——单一出处，本模块不重复定义）。

usage 缺失记 0 并置内存旗标 `usage_estimated=True`（§8 冻结 19 列**没有** estimated 列，
落库需要用户裁决，见 Task 1 报告移交项），流式侧同义信息放在 `LLMChunk.usage["estimated"]`。
"""
from __future__ import annotations

import codecs
import json
from typing import Any, Iterable, Iterator

from app.llm.errors import LLMError, from_response
from app.llm.models import LLMChunk, LLMRequest, LLMResponse, ToolCall

__all__ = [
    "ollama_payload",
    "openai_payload",
    "parse_ollama_response",
    "parse_openai_response",
    "parse_openai_tool_calls",
    "ollama_stream_lines",
    "openai_stream_lines",
]

_STREAM_DONE_SENTINEL = "[DONE]"


# --------------------------------------------------------------------------
# 请求报文
# --------------------------------------------------------------------------
def ollama_payload(req: LLMRequest, model: str, *, stream: bool = False) -> dict[str, Any]:
    """Ollama 聊天端点的请求体，形状与 `agent.py::_ollama_chat` 一致（见模块 docstring）。

    这里不写端点路径字面量：D6/Task 9 的全文扫描要求路径只出现在 `provider.py`。
    """
    payload: dict[str, Any] = {"model": model, "stream": bool(stream)}
    if req.think is not None:
        payload["think"] = bool(req.think)
    if req.keep_alive is not None:
        payload["keep_alive"] = req.keep_alive
    payload["messages"] = [dict(m) for m in req.messages]
    payload["tools"] = [dict(t) for t in req.tools]      # 空列表也保留键：现网同形
    options: dict[str, Any] = {"temperature": req.temperature}
    if req.num_predict is not None:
        options["num_predict"] = int(req.num_predict)
    payload["options"] = options
    return payload


def openai_payload(req: LLMRequest, model: str, *, stream: bool = False) -> dict[str, Any]:
    """OpenAI 兼容聊天端点的请求体。`tools` 为空时**不发**该键（现网 rag.py 同形）。

    同 `ollama_payload`：端点路径字面量只出现在 `provider.py`，本模块的 docstring 也不写。
    `messages` 在出口前过一次 `_replay_messages()`（I-4 / 矩阵 #12b）：请求侧把协议差异
    吃掉，`app/agent.py` 与业务层的内部消息形状一字不改（§6 冻结的两句话在此闭合）。
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": _replay_messages(req.messages),
        "temperature": req.temperature,
        "stream": bool(stream),
    }
    if req.num_predict is not None:
        payload["max_tokens"] = int(req.num_predict)
    if req.tools:
        payload["tools"] = [dict(t) for t in req.tools]
    if stream:
        # 不发 include_usage 就拿不到末尾 usage 块（§8 记账与 §6 usage 提取要它）。
        payload["stream_options"] = {"include_usage": True}
    return payload


#: 工具回执的角色名（只在这里出现一次，配对逻辑与消息回放都读它）。
_TOOL_ROLE = "tool"


def _replay_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """内部回放形状 → OpenAI chat-completions 的 `messages`（Task 8 评审 I-4，矩阵 #12b）。

    缺这段映射会发生什么（评审探针 P8 实测）：agent 工具轮的**第二轮**出口体带
    `"arguments": {"query": "…"}`（dict）与 `{"role": "tool", "tool_name": X}`（没有
    `tool_call_id`）⇒ 云侧 400，归类 non-retryable（换候选也救不了，每条 OpenAI 兼容腿
    都 400），配 key 之后工具轮在云侧根本不可用。

    授权依据（DESIGN §6 冻结）：「`OpenAICompat` 与 `OllamaNative` **差异全部在此层吸收**」
    +「两侧 tool_calls → `ToolCall(id, name, arguments dict)`；**Agent 只认内部模型**」。
    ⇒ 映射只能坐在这里，不能坐进 `app/agent.py` 的回放，也不能改 `LLMResponse/ToolCall`。

    两处差异：
    1. `assistant.tool_calls[].function.arguments` 内部是 **dict**，OpenAI 要求 **JSON
       字符串** ⇒ `json.dumps(..., ensure_ascii=False)`（中文不许被转义成 uXXXX 序列）。
       已是字符串的原样透传 ⇒ 本函数**幂等**，同一份请求连发两次不会二次编码。
    2. 工具回执内部是 `{"role": "tool", "tool_name": X}`，OpenAI 要求带
       `tool_call_id`。配对规则（四枚用例钉在 `OpenAIMultiTurnReplayTests`，不靠注释）：
       - 回看**最近一条还有未消费调用**的 assistant 消息（工具轮的回放就是那个顺序）；
       - 优先取该轮里**第一枚同名且未消费**的调用（工具名是最强的配对信号）；
       - 同名多枚 ⇒ 按 assistant 里的**出现次序**逐一消费（第 N 枚回执配第 N 枚调用）；
       - 名字对不上（`tool_name` 缺失或被改）⇒ 退化成该轮**最早未消费**的那枚；
       - 回执自己已经带 `tool_call_id` ⇒ 原样透传，并把那枚 id 占掉（调用方优先）；
       - `id` 为空串的调用（§6：老版 Ollama 不回 id，不许假设唯一）**照样按次序占槽**，
         只是它自己那条回执写不出 `tool_call_id` ⇒ **不许**跳过它去领后面调用的 id
         （跨槽 = 错配，Task 9 复审 I-1）；
       - 该轮没有可调用的槽（孤儿回执）⇒ **不造假 id**，原样交回：宁缺不错配。

    全程在副本上做：`dict(m)` 只是浅拷贝，所以 `tool_calls` 数组与 `function` 子对象各自
    另建 dict 再改——调用方 `req.messages` 里的内部形状一字不动（另一条 Ollama 腿读的就是
    这一份，`test_payload_does_not_mutate_the_request` 钉着）。
    """
    replayed: list[dict[str, Any]] = []
    #: 每个工具轮的槽：`(该轮映射后的 calls, 已消费的下标集合)`，按出现顺序入栈。
    rounds: list[tuple[list[Any], set[int]]] = []
    for raw in messages:
        message = dict(raw)
        role = message.get("role")
        calls = message.get("tool_calls")
        if isinstance(calls, list) and calls:
            mapped = [_stringified_tool_call(call) for call in calls]
            message["tool_calls"] = mapped
            if role == "assistant":
                rounds.append((mapped, set()))
        elif role == _TOOL_ROLE:
            paired = _paired_tool_receipt(message, rounds)
            if paired is not None:
                message = paired
        replayed.append(message)
    return replayed


def _stringified_tool_call(call: Any) -> Any:
    """单枚 tool_call → `arguments` 为 JSON 字符串的出口形状（非 dict 的一律原样）。"""
    if not isinstance(call, dict):
        return call
    function = call.get("function")
    if not isinstance(function, dict) or not isinstance(function.get("arguments"), dict):
        return dict(call)
    rebuilt = dict(call)
    rebuilt_function = dict(function)
    rebuilt_function["arguments"] = json.dumps(function["arguments"], ensure_ascii=False)
    rebuilt["function"] = rebuilt_function
    return rebuilt


def _paired_tool_receipt(message: dict[str, Any], rounds: list[tuple[list[Any], set[int]]]) -> dict[str, Any] | None:
    """把 `{"role":"tool","tool_name":X}` 换成带 `tool_call_id` 的协议形状；配不上返回 None。

    可配对性在**选出槽之后**才判（Task 9 复审 I-1）：选出即占槽，于是空 id 只会让它自己
    那条回执写不出 id，不会让下一枚回执跨到后面的调用上去。
    """
    given = message.get("tool_call_id")
    if isinstance(given, str) and given:
        _consume_id(rounds, given)                 # 调用方给的 id 优先，但仍占槽
        return None
    name = message.get("tool_name")
    for calls, consumed in reversed(rounds):
        index = _matching_call(calls, consumed, name)
        if index is None:
            continue
        consumed.add(index)                        # 先占槽：写不出也不许下一枚回执退回来重复领
        if not _pairable_id(calls[index]):
            return None                            # 宁缺不错配，且**不许跨槽**
        mapped: dict[str, Any] = {"role": _TOOL_ROLE,
                                  "tool_call_id": str(calls[index].get("id") or "")}
        mapped.update({k: v for k, v in message.items() if k not in ("role", "tool_name")})
        return mapped
    return None


def _matching_call(calls: list[Any], consumed: set[int], name: Any) -> int | None:
    """该轮里的配对槽：先按名字（第一枚同名未消费），再退化到最早未消费的那枚。

    扫描入口**不看** `id` 可不可配对（Task 9 复审 I-1）：「第 N 枚回执配第 N 枚调用」的次序
    是由槽位决定的，把可配对性判断放在这里等于让空 id 的调用从轮里凭空消失，前一枚回执于是
    跨槽领走后一枚调用的 id（错配）。可配对性交给 `_paired_tool_receipt` 在选出之后判。
    """
    fallback: int | None = None
    for index, call in enumerate(calls):
        if index in consumed or not isinstance(call, dict):
            continue
        if fallback is None:
            fallback = index
        function = call.get("function")
        call_name = function.get("name") if isinstance(function, dict) else None
        if isinstance(name, str) and call_name == name:
            return index
    return fallback


def _consume_id(rounds: list[tuple[list[Any], set[int]]], call_id: str) -> None:
    """调用方自带 id 时把那枚槽占掉，免得后面的回执重复领同一枚。"""
    for calls, consumed in reversed(rounds):
        for index, call in enumerate(calls):
            if index in consumed or not isinstance(call, dict):
                continue
            if call.get("id") == call_id:
                consumed.add(index)
                return


def _pairable_id(call: dict[str, Any]) -> bool:
    """`id` 必须是非空字符串才**写得出**回执：空串（Ollama 不回 id）造不出合法 id。

    这是**出口**判据（这枚槽能不能写出 id），不是**槽位**判据（谁是第 N 枚调用）——
    后者由 `_matching_call` 按名字/次序决定，两层混在一处就会跨槽（Task 9 复审 I-1）。
    """
    call_id = call.get("id")
    return isinstance(call_id, str) and bool(call_id)


# --------------------------------------------------------------------------
# 非流式响应解析
# --------------------------------------------------------------------------
def parse_openai_response(
    data: dict[str, Any], model: str, provider: str, latency_ms: float
) -> LLMResponse:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMError("hard", None, "OpenAI 响应缺少 choices")
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    # 只取 content：reasoning_content / reasoning 一律不读（D3 永不存 CoT）。
    content = str((message or {}).get("content") or "")
    usage = _usage(data.get("usage"), "prompt_tokens", "completion_tokens")
    return LLMResponse(
        content=content,
        tool_calls=parse_openai_tool_calls((message or {}).get("tool_calls")),
        finish_reason=str(choice.get("finish_reason") or "stop"),
        model=str(data.get("model") or model),
        provider=provider,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        latency_ms=float(latency_ms),
        usage_estimated=usage["estimated"],
    )


def parse_ollama_response(
    data: dict[str, Any], model: str, provider: str, latency_ms: float
) -> LLMResponse:
    message = data.get("message")
    if not isinstance(message, dict):
        # 文案与 agent.py 现网的 RuntimeError 一致，迁移时运维读到的字没变。
        raise LLMError("hard", None, "Ollama 返回缺少 message")
    usage = _usage(data, "prompt_eval_count", "eval_count")
    return LLMResponse(
        content=str(message.get("content") or ""),
        # tool_calls 两侧同形（{function:{name,arguments}}），共用同一个解析器。
        tool_calls=parse_openai_tool_calls(message.get("tool_calls")),
        finish_reason=str(data.get("done_reason") or "stop"),
        model=str(data.get("model") or model),
        provider=provider,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        latency_ms=float(latency_ms),
        usage_estimated=usage["estimated"],
    )


def parse_openai_tool_calls(raw: Any) -> tuple[ToolCall, ...]:
    """两侧 tool_calls 的标准化：`arguments` 无论是 JSON 字符串还是 dict 都收成 dict。

    名字保留 `openai_` 前缀（brief 冻结），但 Ollama 也用它——两个协议的 tool_calls 数组
    形状一致，唯一差异是 OpenAI 的 arguments 恒为字符串、Ollama 新版本恒为对象，
    `_arguments()` 两边都能吃。解析失败按现网 `agent.py::_tool_arguments` 的口径退化成
    `{}`（不是抛异常）：模型给了坏参数时让工具自己报缺参，比整条链崩溃更可用。
    """
    calls = raw if isinstance(raw, list) else []
    parsed: list[ToolCall] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        parsed.append(ToolCall(
            id=str(call.get("id") or ""),       # Ollama 不回 id ⇒ 空串（Task 8 不得假设唯一）
            name=str(function.get("name") or ""),
            arguments=_arguments(function.get("arguments")),
        ))
    return tuple(parsed)


def _arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def _usage(source: Any, input_key: str, output_key: str) -> dict[str, Any]:
    """usage 提取：缺失记 0 并置 `estimated`（§6）。`source` 可以是 usage 块或整个响应体。"""
    body = source if isinstance(source, dict) else {}
    raw_input, raw_output = body.get(input_key), body.get(output_key)
    input_tokens = _token_count(raw_input)
    output_tokens = _token_count(raw_output)
    estimated = input_tokens is None or output_tokens is None
    return {
        "input_tokens": input_tokens or 0,
        "output_tokens": output_tokens or 0,
        "total_tokens": (input_tokens or 0) + (output_tokens or 0),
        "estimated": estimated,
    }


def _token_count(raw: Any) -> int | None:
    """只接受非负整数；None / 字符串 / 负数一律视作「没有 usage」⇒ estimated。"""
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw if raw >= 0 else None


# --------------------------------------------------------------------------
# 流式解析
# --------------------------------------------------------------------------
def openai_stream_lines(source: Any) -> Iterator[LLMChunk]:
    """OpenAI SSE：`data:` 行 + `[DONE]` 终止；末尾 usage 块（可能缺失）在 finish 块携带。

    流式工具增量（`delta.tool_calls`）暂不解析，`LLMChunk` 也不带 tool_calls 字段——
    Task 7（SSE 迁移）之前不得出现 tools+stream 的组合，届时按 Task 7 的裁决扩这一层。
    """
    usage: dict[str, Any] | None = None
    terminated = False
    for line in _text_lines(source):
        text = line.strip()
        if not text or text.startswith(":") or not text.startswith("data:"):
            continue                              # 注释/心跳/`event:`/`id:` 行
        data = text[len("data:"):].strip()
        if data == _STREAM_DONE_SENTINEL:
            terminated = True
            break
        payload = _load(data, "OpenAI")
        _raise_stream_error(payload, "OpenAI")
        if isinstance(payload.get("usage"), dict):
            usage = payload["usage"]
        for chunk_text in _openai_delta(payload):
            yield LLMChunk(text=chunk_text)
    if not terminated:
        raise LLMError("retryable", 200, "OpenAI 流式响应提前结束，未收到 [DONE]")
    yield LLMChunk(text="", finish=True,
                   usage=_usage(usage, "prompt_tokens", "completion_tokens"))


def _openai_delta(payload: dict[str, Any]) -> Iterator[str]:
    choices = payload.get("choices")
    first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    # include_usage 的最后一块 choices 为空，只有 usage：这里自然产出空文本。
    delta = first.get("delta") if isinstance(first.get("delta"), dict) else {}
    text = str(delta.get("content") or "")
    if text:
        yield text


def ollama_stream_lines(source: Any) -> Iterator[LLMChunk]:
    """Ollama NDJSON：逐行 JSON，`message.content` 出文本，`done:true` 行携带 eval_count。"""
    finished = False
    for line in _text_lines(source):
        text = line.strip()
        if not text:
            continue
        payload = _load(text, "Ollama")
        _raise_stream_error(payload, "Ollama")
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        content = str(message.get("content") or "")
        if payload.get("done") is True:
            finished = True
            yield LLMChunk(text=content, finish=True,
                           usage=_usage(payload, "prompt_eval_count", "eval_count"))
            break
        if content:
            yield LLMChunk(text=content)
    if not finished:
        raise LLMError("retryable", 200, "Ollama 流式响应提前结束，未收到 done=true")


def _raise_stream_error(payload: dict[str, Any], protocol: str) -> None:
    """200 状态里的错误帧：Ollama 的 `{"error": ...}` 与兼容层的 `{"error": {...}}`。

    归类走 `from_response(200, text)`，于是「模型没加载」这类字样仍能命中 §6 的
    `model_unavailable` 特征，而不是被 200 掩成成功。
    """
    if payload.get("error") is None:
        return
    raise from_response(200, str(payload.get("error")))


def _load(text: str, protocol: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise LLMError("hard", 200, f"{protocol} 流式响应不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise LLMError("hard", 200, f"{protocol} 流式响应不是 JSON 对象")
    return payload


def _text_lines(source: Any) -> Iterator[str]:
    """把 bytes 分片流切成「完整文本行」，跨分片的多字节字符不丢不换。

    中文场景必测：一个汉字的 3 个 UTF-8 字节落在两个 TCP 包里时，逐包 `decode()` 会抛
    `UnicodeDecodeError`（或用 errors=replace 把字打烂）。这里用 **增量解码器**：尾部不完整
    的字节序列由解码器自己扣住，下一片到达时续上。行缓冲同理——半行 JSON 不进解析器。
    """
    chunks: Iterable[Any] = source.iter_bytes() if hasattr(source, "iter_bytes") else source
    decoder = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    for raw in chunks:
        buffer += decoder.decode(bytes(raw))
        while True:
            index = buffer.find("\n")
            if index < 0:
                break
            yield buffer[:index]
            buffer = buffer[index + 1:]
    buffer += decoder.decode(b"", final=True)
    if buffer:
        yield buffer

from __future__ import annotations

import logging

# --------------------------------------------------------------------------
# D6「单一出口」豁免项（Model Router V2.3 Task 6 迁移后**仍然存在**）：Task 9 的静态扫描
# 要把本文件列进 legacy 豁免清单，命中面逐枚可查——
#
#   1. `import httpx`（紧跟本段注释的那一行）
#   2. `generate_answer` 里 `LLM_ROUTER_ENABLED=false` 的两条 `httpx.post` 分支
#      （端点路径字面量 `/chat/completions` 与 `/api/chat` 各一枚，也都只出现在这两行里）
#
# 合计：**httpx 代码命中 3 处 / 端点路径字面量 2 处**（其余 httpx 字样都在注释里）。
#
# 它们**不是**漏迁：`LLM_ROUTER_ENABLED=false` 是 V2.3 的紧急回退口（DESIGN §1「legacy 路径
# 仅限 V2.3 紧急回退」+ §7 + 验收矩阵 **#18「legacy 回退三链原行为」**）。矩阵 #18 要的是
# 「旗标关掉 ⇒ 三条链逐字回到今天的行为」，而唯一能钉住这件事的对照组就是这条**原样保留**
# 的 httpx 路：把它改写成 `provider.complete()`，#18 就没有对照物了（Task 6 的
# `RagTemperatureEquivalenceTests` 正是拿这两条分支当报文面基准）。
# 因此本文件的 httpx 命中随 legacy 一起消失，不提前删：
# DESIGN §1 冻结的义务是「**下一稳定版必须删除 legacy 路径**」——那一次删除同时带走
# `import httpx`、两条 `httpx.post` 分支、`current_model_name()` 的 `_legacy_model_name`
# 以及 `generate_answer` 尾部那道为 legacy 保留的 catch-all，
# 并由 Task 9 的守卫测试在那之后断言本文件零命中。用户已裁定：legacy 是应急口，
# 删除归后续版本，不归 Task 6。
# --------------------------------------------------------------------------
import httpx

from app import llm
from app.config import settings
from app.llm import RAG_LEGACY_TEMPERATURE
from app.llm.errors import LLMError
from app.llm.fallback import AllCandidatesFailedError, routing_health_view
from app.llm.models import RequestProfile
from app.llm.registry import RegistryError
from app.llm.router import NoCapableModelError
from app.web_search import clean_question, search_web, wants_web_search

# Model Router V2.3 Task 2（D6）：`probe_ollama` / `probe_llm` 已迁至 `app.llm.health`，
# HTTP 出口收编进 `app.llm.provider`。这里不再重新导出它们——三个消费方
# （main.py / main_agent.py / knowledge_os.py）直接改 import，避免出现「两条 import 路径
# 指向同一个 probe」的第二套口径。

logger = logging.getLogger("app.rag")

#: RAG 链的**路由画像**（§4：mode 由调用点声明，禁 LLM 判路由）。
#: 只有 `current_model_name()`（展示面）直接用它；生成面走 `llm.complete(mode="rag")`，
#: 那里的画像由 `classifier.classify()` 按问题文本补 `complexity`。
#: `complexity="low"` 是刻意占位：§5 的打分 today 只看 `priority[mode]` 与 pricing
#: （T3 报告「偏离 3」），复杂度不参与裁决；若将来参与，展示面必须先决定「无问题的
#: 默认档位」是什么，而不是跟着某个用户的问法抖。
_RAG_PROFILE = RequestProfile(mode="rag", complexity="low", needs_tools=False,
                              needs_stream=False)

#: `generate_answer(..., model_out=...)` 盒子的**唯一键名**（终审 I-11-2）。
#: 键名放在 `app.rag` 而不是 `app.main`：写方与读方共读一枚常量，避免「盒子写了、
#: 调用方查另一个词」这种静默失配——那正是本项要修的劈叉的同一形状。
MODEL_USED_KEY = "model_used"


SYSTEM_PROMPT = """你是 yaoke 企业知识助手。
你可以使用两类证据：企业知识库资料，以及用户明确开启联网搜索后提供的互联网搜索摘要。
必须遵守：
1. 企业制度、金额、日期、流程、产品参数等内部事实，以企业知识库为最高优先级；互联网资料不得覆盖内部制度。
2. 不得编造事实。证据不足时明确说明依据不足。
3. 关键事实使用 [1] [2] 形式标注引用来源。
4. 互联网搜索摘要可能过时或不完整；涉及最新信息时说明其来源属于互联网检索。
5. 回答保持专业、简洁，优先直接回答用户问题。
6. 输出语言硬约束：无论用户使用何种语言提问，面向用户的最终答案一律使用简体中文；引用标记保持 [1] [2] 形式不变。
7. 证据不足时必须以**中文**输出拒答说明，不得改写成其他语言，也不得编造答案。参考固定话术：当前知识库中没有找到可以回答该问题的资料，请补充更多信息或换个问法。
"""


def build_context(rows: list[dict]) -> str:
    blocks: list[str] = []
    for index, row in enumerate(rows, start=1):
        if row.get("source_type") == "web":
            blocks.append(
                f"[{index}] 类型：互联网检索\n标题：{row.get('file_name', '网页')}\n"
                f"URL：{row.get('url', '')}\n摘要：{row.get('content', '')}"
            )
            continue
        page = f"，第 {row.get('page')} 页" if row.get("page") else ""
        evidence_type = (
            "冲突证据"
            if row.get("typesafe_route") == "conflicting_evidence"
            else "企业知识库"
        )
        blocks.append(
            f"[{index}] 类型：{evidence_type}\n来源：{row.get('file_name', '未知文档')}{page}\n"
            f"{row.get('content', '')}"
        )
    return "\n\n".join(blocks)


def current_model_name() -> str:
    """Model used by the RAG answer path（§9：改由 router 解析，不再猜 `openai_api_key`）。

    **router 路**给的是「rag 模式的默认候选（`RoutePlan.primary`）的生效模型名」，与
    `provider.effective_model_name` 同一个口径（含 D1 的 `{PROVIDER}_MODEL_OVERRIDE` 别名），
    所以 `/api/health` 与 `/api/system/status` 的 `llm_model` 指向**计划面打算**用哪个名字。
    `/api/query` 的 `model_used` 只在**没有发生 fallback** 时与它一致：那枚字段自终审
    I-11-2 起优先取执行面的实际生效名（`generate_answer(..., model_out=...)` 的盒子），
    取不到才回退到这里。本函数**保留**：它仍是合法的「计划面/展示面」读数
    （health、status、`main_agent.legacy_rag_model` 三处在消费），只是不再冒充「这次真
    答话的模型」。
    无云 key 时出厂注册表里 `external ∧ 无 key ⇒ enabled=false`（`registry._with_effective_enabled`），
    于是 primary 必然是本地条目，读到的就是 `settings.ollama_model` 那个名字。

    **展示面的三条硬约束**（为什么它不等于「再跑一次 `llm.complete`」）：
    1. **不打网络**：本函数被 `/api/health`、`/api/system/status`（前端每 30s 轮询）与
       `/api/query` 的响应体消费。用 `routing_health_view(include_probes=False)` 就是为了让
       它只并**熔断态**、不触发 `provider_health_view()` 的探测。代价写在「失败面」第 3 条。
    2. **不抛异常**：注册表坏 / 零候选 ⇒ 退回 `_legacy_model_name()`。一个名字不值得把
       `/api/health` 变成 500，也不值得让 status 页塌掉——那是观测面自己制造故障。
    3. **不外呼、不计费**：这里只跑 `plan()` 这个纯函数（§5：P95 ≤ 10ms），不进 fallback。

    **失败面（新解析路径相对 legacy `if openai_api_key` 少/多出来的东西）**：
    - `RegistryError`（文件缺失 / 结构坏 / 重复 id / provider 未登记）：legacy 那两句 if
      永远不会失败，本函数会——收口成退回值 + 一条 warning（坏注册表在 `warmup()` 里已经
      该把进程拦在启动阶段，走到这里说明是 fresh 部署或有人热改了文件）。
    - `NoCapableModelError`（enabled 全灭 / rag capability 全 false / rag priority 全 0 /
      健康视图把所有 provider 闸掉）：同样退回 `_legacy_model_name()`。
      注意这是**可能**发生的：legacy 判断只看「有没有 key」，而注册表还要看能力旗标——
      有人把 `ollama-ornith` 的 `capabilities.rag` 写成 false 就会零候选。
      此时 `model_used` 会显示一个「其实不会服务这一行」的名字；这是刻意的取舍
      （宁可显示一个可解释的默认，也不要一个空字段），真值在 `llm_request_logs` 与
      status 的 `llm` 块里，不在这个展示位上。
    - **展示面与生成面的候选可能不同**：两处只有「provider 恰好不健康」这一个窗口会劈叉
      ——生成路 `llm.complete()` 的 `_plan()` 带探针视图，展示路刻意不带（约束 1）。
      探针本身有 60s 缓存（`health.HEALTH_CACHE_TTL_SECONDS`），所以劈叉窗口是有界的，
      而换来的是 status 轮询不把 Ollama 打个来回。
    - **上下文收口不在这里**：§5 的 context 粗估在 Task 4 的 execute 前置做，本函数没有
      请求体可比，所以报的是「计划面的 primary」，不是「这次真会用的那个 primary」。
    """
    if not llm.router_enabled():
        return _legacy_model_name()
    try:
        registry = llm.get_registry()
        route = llm.plan(_RAG_PROFILE, registry,
                         routing_health_view(registry, include_probes=False))
        return llm.effective_model_name_for_entry(route.primary.model)
    except (RegistryError, NoCapableModelError) as exc:
        logger.warning("RAG 展示面无法经 router 解析默认候选，退回 legacy 模型名：%s: %s",
                       type(exc).__name__, exc)
        return _legacy_model_name()


def _legacy_model_name() -> str:
    """`LLM_ROUTER_ENABLED=false` 时的原名（矩阵 #18 的对照组，随 legacy 一起删除）。"""
    if settings.openai_api_key:
        return settings.openai_model
    return settings.ollama_model


def _append_web_sources(answer: str, enterprise_count: int, web_rows: list[dict]) -> str:
    if not web_rows:
        return answer
    lines = ["", "联网来源："]
    for offset, row in enumerate(web_rows, start=1):
        index = enterprise_count + offset
        lines.append(f"- [{index}] {row.get('file_name', '网页')} — {row.get('url', '')}")
    return answer.rstrip() + "\n" + "\n".join(lines)


def generate_answer(question: str, rows: list[dict], *,
                    model_out: dict | None = None) -> str:
    """检索证据 → 一次生成 → 对外答案文本（`/api/query` 与 `/api/query/stream` 的生成腿）。

    终审 I-11-2：`model_out` 是把**执行面事实**带出本函数的可变盒子（与 Task 8/9 的
    `route_out` / `tool_time` 同一族：线程安全、不改返回形状）。
    - **只有** router 路真拿到响应时才写：`model_out[MODEL_USED_KEY] = 本次 LLMResponse.model`
      （M2 的生效模型名，与账本 `llm_request_logs.model` 同一个词表）。
    - `NoCapableModelError` / 全链失败 / legacy 路 **不写这个键**：那三种情况下「这次真答出
      那句话的模型」根本不存在，写个猜值或空串就是把「不知道」伪装成事实。调用方读到缺键
      就自己回退（`main.py` 回退到 `current_model_name()` 这个计划面读数）。
    - 参形状是**关键字 + 默认 None**：既有的 `generate_answer(question, rows)` 调用点与
      测试逐字不破（DESIGN §9「既有响应结构对外不变」）。
    """
    clean = clean_question(question)
    web_rows: list[dict] = []
    web_error: str | None = None

    if wants_web_search(question) and settings.web_search_enabled:
        try:
            web_rows = search_web(clean)
        except Exception as exc:
            web_error = f"{type(exc).__name__}: {exc}"

    evidence_rows = [*rows, *web_rows]
    if not evidence_rows:
        if web_error:
            return "联网检索失败，且当前知识库中未找到可靠依据。"
        return "当前知识库中未找到可靠依据。"

    context = build_context(evidence_rows)
    mode_note = (
        "用户已明确开启联网搜索。企业知识库证据优先，互联网证据仅作为外部补充。"
        if wants_web_search(question)
        else "用户未开启联网搜索，只使用企业知识库证据。"
    )
    user_prompt = f"""请依据以下证据回答问题。

检索模式：{mode_note}

证据：
{context}

用户问题：{clean}

请给出答案，并对关键结论标注引用编号。答案必须使用简体中文；若证据不足，请用中文说明没有找到可回答该问题的资料。"""

    # 生成面与展示面共用的两条消息。legacy 那两条分支**照今天一样把它内联写进请求体**
    # （矩阵 #18 的对照组要求逐字节可对照），所以这里构造的 `messages` 只服务 router 路；
    # 两者同源（`SYSTEM_PROMPT` + `user_prompt` 两个值），不存在第二套 prompt 口径。
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        if llm.router_enabled():
            answer = _answer_via_router(messages, model_out)
        elif settings.openai_api_key:
            url = settings.openai_base_url.rstrip("/") + "/chat/completions"
            response = httpx.post(
                url,
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_model,
                    "temperature": 0.1,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=120,
            )
            response.raise_for_status()
            answer = str(response.json()["choices"][0]["message"]["content"])
        else:
            response = httpx.post(
                settings.ollama_base_url.rstrip("/") + "/api/chat",
                json={
                    "model": settings.ollama_model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=120,
            )
            response.raise_for_status()
            answer = str(response.json()["message"]["content"])

        if web_error:
            answer = answer.rstrip() + "\n\n注：本次联网检索部分失败，答案主要依据已成功获得的证据。"
        return _append_web_sources(answer, len(rows), web_rows)
    except (LLMError, AllCandidatesFailedError, NoCapableModelError) as exc:
        # Router 的**声明失败面**（D2）：`LLMError` 含 `AllCandidatesFailedError`（子类，
        # 这里点名是为了让「聚合失败也走这条文案」在源码上可读），`NoCapableModelError`
        # 不是 LLMError 的子类（§4/fallback 的刻意区分），必须显式列出来。
        # 三条链都不得把它变成裸错（D2「不得 500/503 给用户」）——这里的出口就是今天那句。
        return _llm_unavailable(exc, evidence_rows, rows, web_rows)
    except Exception as exc:
        # catch-all 的宽度**照 legacy 原样保留**（矩阵 #18）：今天这条链上
        # `KeyError` / `JSONDecodeError` / `httpx.InvalidURL` 都会落到同一句兜底文案，
        # 收窄成只 catch Router 异常就会把「坏响应体」从降级变成 500 —— 那是行为变更，
        # 不是重构。删它要等 legacy 应急路一起删（见文件头 D6 豁免段）。
        return _llm_unavailable(exc, evidence_rows, rows, web_rows)


def _answer_via_router(messages: list[dict],
                       model_out: dict | None = None) -> str:
    """Model Router V2.3（§9）：RAG 非流式生成走统一出口 `llm.complete()`。

    `temperature=RAG_LEGACY_TEMPERATURE`（0.1）**不是可选项**（Task 2 评审移交 I-4）：
    `LLMRequest.temperature` 的字段默认是 Task 1 冻结的通用 0.2，provider/normalize 两层
    刻意不注入默认温度，漏掉这一参就是把 RAG 链的采样温度从现网 0.1 静默改成 0.2。
    `trace_id=None`：RAG 链今天没有 trace（`model_route` 属 agent/SSE 链，Task 7/8 接线）。

    终审 I-11-2：成功返回**之前**把这次真答话的生效模型名放进 `model_out`。取值只用
    `result.response.model`（M2 口径：`provider.complete()` 以 `effective_model_name()` 为
    target 发请求、`adapter.parse` 再把同一个 target 回填进响应，因此它与 usage 落库的
    `model` 列同源），**不取** `result.plan.primary`——计划面的 primary 正是本项要修的那枚
    说谎读数。失败路径（`NoCapableModelError` / `AllCandidatesFailedError` / 硬终态
    `LLMError`）从 `llm.complete()` 抛出时根本到不了写入那一行，天然不写键；provider 回显
    空串时同样不写（宁缺毋空：空串会被调用方的 `or` 吃掉，但依赖那个 `or` 就等于把
    「不写空串」这条约束外包给调用方）。
    """
    result = llm.complete(messages, mode="rag",
                          temperature=RAG_LEGACY_TEMPERATURE, trace_id=None)
    if model_out is not None:
        answered_by = str(result.response.model or "")
        if answered_by:
            model_out[MODEL_USED_KEY] = answered_by
    return str(result.response.content)


def _llm_unavailable(exc: BaseException, evidence_rows: list[dict],
                     rows: list[dict], web_rows: list[dict]) -> str:
    """LLM 不可用时的现文案（一字未改）：原文预览 + 异常类名 + 联网来源尾块。

    `模型连接错误：{type(exc).__name__}` 里的**类名**是事实而不是修饰：router 路上它会是
    `AllCandidatesFailedError` / `NoCapableModelError` / `LLMError`，legacy 路上仍是
    `ConnectError` / `HTTPStatusError`——两个词表都指向「谁让这次生成没成」，不换成固定
    字面量（那等于把归因能力删掉，只留一句安慰话）。
    """
    preview = evidence_rows[0].get("content", "")[:220]
    fallback = (
        "已完成检索，但当前 LLM 服务不可用，因此暂不生成推断性答案。\n\n"
        f"最相关原文：[1] {preview}\n\n"
        f"模型连接错误：{type(exc).__name__}"
    )
    return _append_web_sources(fallback, len(rows), web_rows)

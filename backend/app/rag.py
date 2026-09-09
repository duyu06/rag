from __future__ import annotations

import httpx

from app.config import settings
from app.web_search import clean_question, search_web, wants_web_search

SYSTEM_PROMPT = """你是 NexusKB 企业知识助手。
你可以使用两类证据：企业知识库资料，以及用户明确开启联网搜索后提供的互联网搜索摘要。
必须遵守：
1. 企业制度、金额、日期、流程、产品参数等内部事实，以企业知识库为最高优先级；互联网资料不得覆盖内部制度。
2. 不得编造事实。证据不足时明确说明依据不足。
3. 关键事实使用 [1] [2] 形式标注引用来源。
4. 互联网搜索摘要可能过时或不完整；涉及最新信息时说明其来源属于互联网检索。
5. 回答保持专业、简洁，优先直接回答用户问题。
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
        blocks.append(
            f"[{index}] 类型：企业知识库\n来源：{row.get('file_name', '未知文档')}{page}\n"
            f"{row.get('content', '')}"
        )
    return "\n\n".join(blocks)


def current_model_name() -> str:
    if settings.openai_api_key:
        return settings.openai_model
    return settings.ollama_model


def probe_llm(timeout: float = 2.5) -> tuple[bool, str]:
    """Cheap connectivity probe used by the status page and local preflight checks."""
    try:
        if settings.openai_api_key:
            response = httpx.get(
                settings.openai_base_url.rstrip("/") + "/models",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                timeout=timeout,
            )
            response.raise_for_status()
            return True, "openai-compatible"

        response = httpx.get(
            settings.ollama_base_url.rstrip("/") + "/api/tags",
            timeout=timeout,
        )
        response.raise_for_status()
        models = response.json().get("models", [])
        wanted = settings.ollama_model.split(":", 1)[0]
        installed = any(str(item.get("name", "")).split(":", 1)[0] == wanted for item in models)
        if not installed:
            return False, f"Ollama 已连接，但未发现模型 {settings.ollama_model}"
        return True, "ollama"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _append_web_sources(answer: str, enterprise_count: int, web_rows: list[dict]) -> str:
    if not web_rows:
        return answer
    lines = ["", "联网来源："]
    for offset, row in enumerate(web_rows, start=1):
        index = enterprise_count + offset
        lines.append(f"- [{index}] {row.get('file_name', '网页')} — {row.get('url', '')}")
    return answer.rstrip() + "\n" + "\n".join(lines)


def generate_answer(question: str, rows: list[dict]) -> str:
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

请给出答案，并对关键结论标注引用编号。"""

    try:
        if settings.openai_api_key:
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
    except Exception as exc:
        preview = evidence_rows[0].get("content", "")[:220]
        fallback = (
            "已完成检索，但当前 LLM 服务不可用，因此暂不生成推断性答案。\n\n"
            f"最相关原文：[1] {preview}\n\n"
            f"模型连接错误：{type(exc).__name__}"
        )
        return _append_web_sources(fallback, len(rows), web_rows)

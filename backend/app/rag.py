from __future__ import annotations

import httpx

from app.config import settings

SYSTEM_PROMPT = """你是企业知识库助手。只能依据提供的企业资料回答。
必须遵守：
1. 不得编造企业制度、金额、日期、流程或产品参数。
2. 如果资料不足，明确回答“当前知识库中未找到可靠依据”。
3. 关键事实使用 [1] [2] 形式标注引用来源。
4. 回答保持专业、简洁，优先直接回答用户问题。
"""


def build_context(rows: list[dict]) -> str:
    blocks: list[str] = []
    for index, row in enumerate(rows, start=1):
        page = f"，第 {row.get('page')} 页" if row.get("page") else ""
        blocks.append(
            f"[{index}] 来源：{row.get('file_name', '未知文档')}{page}\n{row.get('content', '')}"
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


def generate_answer(question: str, rows: list[dict]) -> str:
    if not rows:
        return "当前知识库中未找到可靠依据。"

    context = build_context(rows)
    user_prompt = f"""请依据以下企业资料回答问题。

企业资料：
{context}

用户问题：{question}

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
            return str(response.json()["choices"][0]["message"]["content"])

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
        return str(response.json()["message"]["content"])
    except Exception as exc:
        preview = rows[0].get("content", "")[:220]
        return (
            "已完成知识检索，但当前 LLM 服务不可用，因此暂不生成推断性答案。\n\n"
            f"最相关原文：[1] {preview}\n\n"
            f"模型连接错误：{type(exc).__name__}"
        )

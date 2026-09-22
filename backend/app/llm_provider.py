from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator

import httpx
from pydantic import SecretStr

from app.config import settings


@dataclass(frozen=True)
class LLMRuntimeConfig:
    provider: str
    base_url: str
    api_key: str
    model: str
    is_ollama: bool


_PROVIDER_DEFAULTS: dict[str, tuple[str, str]] = {
    "openai": ("https://api.openai.com/v1", "gpt-4.1-mini"),
    "deepseek": ("https://api.deepseek.com", "deepseek-flash"),
    "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
}


def _secret_value(value: SecretStr | str | None) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value().strip()
    return str(value or "").strip()


def _normalized_provider(value: str | None) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _explicit_provider_config(provider: str) -> LLMRuntimeConfig:
    """Resolve one named provider without borrowing another provider's secret."""
    provider = _normalized_provider(provider)
    if provider == "ollama":
        return LLMRuntimeConfig(
            provider="ollama",
            base_url=settings.ollama_base_url.rstrip("/"),
            api_key="",
            model=settings.ollama_model,
            is_ollama=True,
        )

    if provider == "deepseek":
        api_key = _secret_value(settings.deepseek_api_key)
        if not api_key:
            raise RuntimeError("DeepSeek fallback requires DEEPSEEK_API_KEY")
        return LLMRuntimeConfig(
            provider="deepseek",
            base_url=str(settings.deepseek_base_url).rstrip("/"),
            api_key=api_key,
            model=str(settings.deepseek_model),
            is_ollama=False,
        )

    if provider == "qwen":
        api_key = _secret_value(settings.qwen_api_key)
        if not api_key:
            raise RuntimeError("Qwen fallback requires QWEN_API_KEY")
        return LLMRuntimeConfig(
            provider="qwen",
            base_url=str(settings.qwen_base_url).rstrip("/"),
            api_key=api_key,
            model=str(settings.qwen_model),
            is_ollama=False,
        )

    if provider == "openai":
        api_key = _secret_value(settings.openai_api_key)
        if not api_key:
            raise RuntimeError("OpenAI provider requires OPENAI_API_KEY")
        return LLMRuntimeConfig(
            provider="openai",
            base_url=str(settings.openai_base_url).rstrip("/"),
            api_key=api_key,
            model=str(settings.openai_model),
            is_ollama=False,
        )

    raise RuntimeError(f"Named provider '{provider}' has no dedicated fallback credentials")


def resolve_llm_config(provider_name: str | None = None) -> LLMRuntimeConfig:
    """Resolve the primary provider or an explicitly named fallback.

    LLM_* controls the primary model. Dedicated provider credentials are used for
    fallbacks so a secret configured for one provider is never sent to another.
    """
    requested_provider = _normalized_provider(settings.llm_provider or "auto")
    generic_key = _secret_value(settings.llm_api_key)
    generic_base = str(settings.llm_base_url or "").strip()
    generic_model = str(settings.llm_model or "").strip()
    generic_configured = bool(generic_key or generic_base or generic_model)

    if provider_name:
        target = _normalized_provider(provider_name)
        # The explicitly selected primary is allowed to use generic LLM_* settings.
        if target == requested_provider and requested_provider not in {"", "auto"} and generic_configured:
            if target == "ollama":
                return _explicit_provider_config("ollama")
            defaults = _PROVIDER_DEFAULTS.get(target)
            base_url = generic_base or (defaults[0] if defaults else "")
            model = generic_model or (defaults[1] if defaults else "")
            if not generic_key:
                raise RuntimeError(f"LLM provider '{target}' requires LLM_API_KEY")
            if not base_url or not model:
                raise RuntimeError(f"LLM provider '{target}' requires LLM_BASE_URL and LLM_MODEL")
            return LLMRuntimeConfig(
                provider=target,
                base_url=base_url.rstrip("/"),
                api_key=generic_key,
                model=model,
                is_ollama=False,
            )
        return _explicit_provider_config(target)

    provider = requested_provider
    if provider in {"", "auto"}:
        if generic_configured:
            provider = "openai-compatible"
        elif _secret_value(settings.openai_api_key):
            return LLMRuntimeConfig(
                provider="openai-compatible",
                base_url=settings.openai_base_url.rstrip("/"),
                api_key=_secret_value(settings.openai_api_key),
                model=settings.openai_model,
                is_ollama=False,
            )
        else:
            return _explicit_provider_config("ollama")

    if provider == "ollama":
        return _explicit_provider_config("ollama")

    defaults = _PROVIDER_DEFAULTS.get(provider)
    base_url = generic_base or (defaults[0] if defaults else "")
    model = generic_model or (defaults[1] if defaults else "")
    if not base_url:
        raise RuntimeError(
            f"LLM provider '{provider}' requires LLM_BASE_URL (or a built-in provider alias)"
        )
    if not generic_key:
        raise RuntimeError(f"LLM provider '{provider}' requires LLM_API_KEY")
    if not model:
        raise RuntimeError(f"LLM provider '{provider}' requires LLM_MODEL")
    return LLMRuntimeConfig(
        provider=provider,
        base_url=base_url.rstrip("/"),
        api_key=generic_key,
        model=model,
        is_ollama=False,
    )


def current_provider_name() -> str:
    return resolve_llm_config().provider


def current_model_name() -> str:
    return resolve_llm_config().model


def public_runtime_config(cfg: LLMRuntimeConfig) -> dict[str, Any]:
    """Safe metadata for traces/admin APIs. Never include credentials."""
    return {
        "provider": cfg.provider,
        "model": cfg.model,
        "base_url": cfg.base_url,
        "external": not cfg.is_ollama,
    }


def _ollama_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed = {"role", "content", "tool_calls", "tool_name"}
    return [{key: value for key, value in message.items() if key in allowed} for message in messages]


def _openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "")
        item: dict[str, Any] = {
            key: value
            for key, value in message.items()
            if key in {"role", "content", "tool_calls", "tool_call_id", "name"}
        }
        if role == "tool":
            tool_name = str(message.get("name") or message.get("tool_name") or "").strip()
            if tool_name:
                item["name"] = tool_name
        normalized.append(item)
    return normalized


def chat_message(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    think: bool = False,
    runtime_config: LLMRuntimeConfig | None = None,
) -> dict[str, Any]:
    cfg = runtime_config or resolve_llm_config()
    tools = tools or []

    if cfg.is_ollama:
        payload: dict[str, Any] = {
            "model": cfg.model,
            "stream": False,
            "think": bool(think),
            "keep_alive": settings.ollama_keep_alive,
            "messages": _ollama_messages(messages),
            "tools": tools,
            "options": {"temperature": temperature},
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = int(max_tokens)
        response = httpx.post(
            cfg.base_url + "/api/chat",
            json=payload,
            timeout=settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        message = body.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Ollama 返回缺少 message")
        result = dict(message)
        result["_provider"] = cfg.provider
        result["_model"] = cfg.model
        result["_usage"] = {
            "input_tokens": int(body.get("prompt_eval_count") or 0),
            "output_tokens": int(body.get("eval_count") or 0),
        }
        return result

    payload: dict[str, Any] = {
        "model": cfg.model,
        "stream": False,
        "temperature": temperature,
        "messages": _openai_messages(messages),
    }
    if tools:
        payload["tools"] = tools
    if cfg.provider == "deepseek":
        # DeepSeek thinking + tools requires replaying hidden reasoning_content.
        # yaoke does not persist hidden reasoning, so tool rounds are non-thinking.
        payload["thinking"] = {"type": "disabled" if tools else ("enabled" if think else "disabled")}
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)

    response = httpx.post(
        cfg.base_url + "/chat/completions",
        headers={
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=settings.llm_timeout_seconds,
    )
    response.raise_for_status()
    body = response.json()
    choices = body.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        raise RuntimeError(f"{cfg.provider} 返回缺少 choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise RuntimeError(f"{cfg.provider} 返回缺少 message")
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    return {
        "role": str(message.get("role") or "assistant"),
        "content": message.get("content") or "",
        "tool_calls": message.get("tool_calls") or [],
        "_provider": cfg.provider,
        "_model": cfg.model,
        "_usage": {
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
        },
    }


def stream_chat(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    think: bool = False,
    runtime_config: LLMRuntimeConfig | None = None,
) -> Iterator[str]:
    cfg = runtime_config or resolve_llm_config()

    if cfg.is_ollama:
        payload: dict[str, Any] = {
            "model": cfg.model,
            "stream": True,
            "think": bool(think),
            "keep_alive": settings.ollama_keep_alive,
            "messages": _ollama_messages(messages),
            "tools": [],
            "options": {"temperature": temperature},
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = int(max_tokens)
        finished = False
        with httpx.stream(
            "POST",
            cfg.base_url + "/api/chat",
            json=payload,
            timeout=settings.llm_timeout_seconds,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("Ollama 流式响应不是合法 JSON") from exc
                if chunk.get("error"):
                    raise RuntimeError(f"Ollama 流式生成失败：{chunk['error']}")
                message = chunk.get("message")
                if isinstance(message, dict):
                    text = str(message.get("content") or "")
                    if text:
                        yield text
                if chunk.get("done") is True:
                    finished = True
                    break
        if not finished:
            raise RuntimeError("Ollama 流式响应提前结束，未收到 done=true")
        return

    payload: dict[str, Any] = {
        "model": cfg.model,
        "stream": True,
        "temperature": temperature,
        "messages": _openai_messages(messages),
    }
    if cfg.provider == "deepseek":
        payload["thinking"] = {"type": "enabled" if think else "disabled"}
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)

    finished = False
    with httpx.stream(
        "POST",
        cfg.base_url + "/chat/completions",
        headers={
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=settings.llm_timeout_seconds,
    ) as response:
        response.raise_for_status()
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                finished = True
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{cfg.provider} 流式响应不是合法 JSON") from exc
            if chunk.get("error"):
                raise RuntimeError(f"{cfg.provider} 流式生成失败：{chunk['error']}")
            choices = chunk.get("choices") or []
            if not choices:
                continue
            choice = choices[0] if isinstance(choices[0], dict) else {}
            delta = choice.get("delta") if isinstance(choice, dict) else None
            if isinstance(delta, dict):
                text = str(delta.get("content") or "")
                if text:
                    yield text
            if isinstance(choice, dict) and choice.get("finish_reason"):
                finished = True
        if not finished:
            raise RuntimeError(f"{cfg.provider} 流式响应提前结束")


def probe_ollama(timeout: float = 2.5) -> tuple[bool, str]:
    try:
        cfg = _explicit_provider_config("ollama")
        response = httpx.get(cfg.base_url + "/api/tags", timeout=timeout)
        response.raise_for_status()
        models = response.json().get("models", [])
        installed_names = {
            str(item.get(key) or "").strip()
            for item in models
            for key in ("name", "model")
            if isinstance(item, dict) and item.get(key)
        }
        wanted = cfg.model.strip()
        installed = (
            wanted in installed_names
            if ":" in wanted
            else any(name == wanted or name.split(":", 1)[0] == wanted for name in installed_names)
        )
        if not installed:
            return False, f"Ollama 已连接，但未发现模型 {cfg.model}"
        return True, f"provider=ollama;model={cfg.model}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def probe_llm(
    timeout: float = 2.5,
    runtime_config: LLMRuntimeConfig | None = None,
) -> tuple[bool, str]:
    try:
        cfg = runtime_config or resolve_llm_config()
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if cfg.is_ollama:
        return probe_ollama(timeout)
    try:
        response = httpx.get(
            cfg.base_url + "/models",
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=timeout,
        )
        response.raise_for_status()
        return True, f"provider={cfg.provider};model={cfg.model}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

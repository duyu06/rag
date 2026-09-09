from __future__ import annotations

import json
import sys
from urllib.error import URLError
from urllib.request import urlopen


def get(url: str, timeout: float = 3.0):
    with urlopen(url, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
        content_type = response.headers.get("content-type", "")
        return response.status, json.loads(raw) if "json" in content_type else raw


def check(name: str, url: str, required: bool = True):
    try:
        status, data = get(url)
        ok = 200 <= status < 300
        print(f"{'[OK]' if ok else '[FAIL]'} {name:<10} {url}")
        return ok, data
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        print(f"{'[FAIL]' if required else '[WARN]'} {name:<10} {url} -> {exc}")
        return False, None


def main() -> int:
    core_ok = True
    ok, _ = check("Qdrant", "http://localhost:6333/healthz")
    core_ok &= ok
    ok, health = check("Backend", "http://localhost:8001/api/ready")
    core_ok &= ok
    ok, _ = check("Frontend", "http://localhost:3000")
    core_ok &= ok

    if isinstance(health, dict):
        provider = health.get("llm_provider")
        llm_connected = bool(health.get("llm_connected"))
        detail = health.get("llm_detail", "")
        print(f"{'[OK]' if llm_connected else '[WARN]'} LLM        {provider} {detail}")
        if provider == "ollama" and not llm_connected:
            core_ok = False

    print("\nDemo preflight:", "PASS" if core_ok else "FAIL")
    return 0 if core_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

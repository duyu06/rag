from __future__ import annotations

import argparse
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = os.environ.get("NEXUSKB_API", "http://localhost:8001/api").rstrip("/")


def request(method: str, path: str, body: dict | None = None, token: str | None = None, timeout: int = 180):
    headers = {}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(API + path, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return response.status, json.loads(raw) if raw else None


def login(username: str, password: str):
    _, data = request("POST", "/auth/login", {"username": username, "password": password})
    return data["access_token"], data["user"]


def tool_names(token: str, mode: str) -> set[str]:
    _, payload = request("GET", "/tools?" + urlencode({"mode": mode}), token=token)
    return {str(item.get("name")) for item in payload.get("tools", [])}


def trace_tools(trace: dict) -> list[str]:
    result: list[str] = []
    for event in trace.get("events", []):
        if event.get("type") == "tool_start" and event.get("tool"):
            result.append(str(event["tool"]))
    return result


def has_hidden_reasoning(trace: dict) -> bool:
    raw = json.dumps(trace, ensure_ascii=False).lower()
    return any(key in raw for key in ('"thinking"', "reasoning_content", "chain-of-thought", "chain_of_thought"))


def agent_query(token: str, *, question: str, mode: str, knowledge_base_id: str | None = None):
    _, result = request(
        "POST",
        "/agent/query",
        {
            "question": question,
            "mode": mode,
            "knowledge_base_id": knowledge_base_id,
            "top_k": 5,
            "rerank": False,
        },
        token=token,
        timeout=240,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="NexusKB P1.4 Ornith Agent runtime acceptance smoke")
    parser.add_argument("--agent", action="store_true", help="run real Ornith tool-calling and RBAC checks")
    parser.add_argument("--web", action="store_true", help="also require a real DDGS web_search call (implies --agent)")
    args = parser.parse_args()
    if args.web:
        args.agent = True

    ok = True
    try:
        admin_token, _ = login("admin", "admin123")
        sales_token, _ = login("sales01", "sales123")
        hr_token, _ = login("hr01", "hr123")

        expected = {
            "local": {"enterprise_search"},
            "auto": {"enterprise_search", "web_search"},
            "web": {"enterprise_search", "web_search"},
        }
        for mode, wanted in expected.items():
            actual = tool_names(admin_token, mode)
            passed = actual == wanted
            ok &= passed
            print(f"{'[OK]' if passed else '[FAIL]'} {mode:<5} tools: {sorted(actual)}")

        print("[INFO] Policy-only checks complete. Use --agent for real Ollama Tool Calling.")

        if args.agent:
            internal = agent_query(
                admin_token,
                question="X100 的标准整机质保多久？请依据企业资料回答。",
                mode="local",
            )
            trace_id = str(internal.get("trace_id") or "")
            _, trace = request("GET", f"/agent/traces/{trace_id}", token=admin_token)
            tools = trace_tools(trace)
            enterprise_called = "enterprise_search" in tools
            local_no_web = "web_search" not in tools and not any(
                source.get("source_type") == "web" for source in internal.get("sources", [])
            )
            trace_safe = not has_hidden_reasoning(trace)
            ok &= enterprise_called and local_no_web and trace_safe
            print(f"{'[OK]' if enterprise_called else '[FAIL]'} internal query selected enterprise_search")
            print(f"{'[OK]' if local_no_web else '[FAIL]'} local mode produced no web evidence/tool call")
            print(f"{'[OK]' if trace_safe else '[FAIL]'} trace excludes hidden reasoning fields")

            sales = agent_query(
                sales_token,
                question="公司年度调薪通常安排在几月？请查询内部制度。",
                mode="local",
            )
            sales_leaks = [
                item for item in sales.get("sources", []) if item.get("knowledge_base_id") == "kb_hr"
            ]
            sales_ok = not sales_leaks
            ok &= sales_ok
            print(f"{'[OK]' if sales_ok else '[FAIL]'} SALES Agent result excludes kb_hr")

            hr = agent_query(
                hr_token,
                question="合同金额超过100万需要谁审批？请查询内部制度。",
                mode="local",
            )
            forbidden = {"kb_sales", "kb_product", "kb_service"}
            hr_leaks = [
                item for item in hr.get("sources", []) if item.get("knowledge_base_id") in forbidden
            ]
            hr_ok = not hr_leaks
            ok &= hr_ok
            print(f"{'[OK]' if hr_ok else '[FAIL]'} HR Agent result excludes sales/product/service KBs")

        if args.web:
            web = agent_query(
                admin_token,
                question="今天 AI 行业有什么重要新闻？请联网查找最新公开信息。",
                mode="web",
            )
            trace_id = str(web.get("trace_id") or "")
            _, trace = request("GET", f"/agent/traces/{trace_id}", token=admin_token)
            tools = trace_tools(trace)
            web_called = "web_search" in tools
            web_sources = [item for item in web.get("sources", []) if item.get("source_type") == "web"]
            web_ok = web_called and bool(web_sources)
            ok &= web_ok
            print(f"{'[OK]' if web_called else '[FAIL]'} public-current query selected web_search")
            print(f"{'[OK]' if web_sources else '[FAIL]'} web_search returned public web evidence")

    except (HTTPError, URLError, OSError, KeyError, ValueError, TypeError) as exc:
        print(f"[FAIL] Agent smoke aborted: {exc}")
        return 1

    print("\nAgent runtime smoke:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

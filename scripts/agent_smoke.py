from __future__ import annotations

import argparse
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = os.environ.get("YAOKE_API", "http://localhost:8001/api").rstrip("/")


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


def trace_has_tool_status(trace: dict, tool_name: str, status: str) -> bool:
    return any(
        event.get("type") == "tool_end"
        and event.get("tool") == tool_name
        and event.get("status") == status
        for event in trace.get("events", [])
    )


def has_hidden_reasoning(trace: dict) -> bool:
    raw = json.dumps(trace, ensure_ascii=False).lower()
    return any(key in raw for key in ('"thinking"', "reasoning_content", "chain-of-thought", "chain_of_thought"))


def demo_ready(status: dict | None) -> bool:
    if not isinstance(status, dict):
        return False
    ready_count = int(status.get("ready_count", 0) or 0)
    total = int(status.get("total", 0) or 0)
    return bool(status.get("ready")) and total > 0 and ready_count == total


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


def load_trace(token: str, result: dict) -> dict:
    trace_id = str(result.get("trace_id") or "")
    if not trace_id:
        raise ValueError("Agent response missing trace_id")
    _, trace = request("GET", f"/agent/traces/{trace_id}", token=token)
    return trace


def citation_indexes_are_contiguous(sources: list[dict]) -> bool:
    indexes = [item.get("citation_index") for item in sources]
    return bool(indexes) and indexes == list(range(1, len(indexes) + 1))


def main() -> int:
    parser = argparse.ArgumentParser(description="yaoke P1.4 Ornith Agent runtime acceptance smoke")
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
            _, demo = request("GET", "/demo/status", token=admin_token)
            if not demo_ready(demo):
                print(
                    f"[FAIL] Agent smoke requires Demo 100% ready; current "
                    f"{demo.get('ready_count', 0)}/{demo.get('total', 0)}. "
                    "Run Demo 初始化 / scripts/init_demo.py first."
                )
                return 1
            print(f"[OK] Demo corpus ready: {demo.get('ready_count')}/{demo.get('total')}")

            internal = agent_query(
                admin_token,
                question="X100 的标准整机质保多久？请先调用企业知识检索，并依据检索证据回答。",
                mode="local",
            )
            trace = load_trace(admin_token, internal)
            tools = trace_tools(trace)
            enterprise_called = "enterprise_search" in tools
            local_no_web = "web_search" not in tools and not any(
                source.get("source_type") == "web" for source in internal.get("sources", [])
            )
            trace_safe = not has_hidden_reasoning(trace)
            enterprise_sources = [
                item for item in internal.get("sources", []) if item.get("source_type") == "enterprise"
            ]
            product_evidence = any(
                item.get("knowledge_base_id") == "kb_product" for item in enterprise_sources
            )
            citations_ok = citation_indexes_are_contiguous(enterprise_sources)
            ok &= enterprise_called and local_no_web and trace_safe and product_evidence and citations_ok
            print(f"{'[OK]' if enterprise_called else '[FAIL]'} internal query selected enterprise_search")
            print(f"{'[OK]' if product_evidence else '[FAIL]'} internal query returned kb_product evidence")
            print(f"{'[OK]' if citations_ok else '[FAIL]'} enterprise citation indexes are contiguous")
            print(f"{'[OK]' if local_no_web else '[FAIL]'} local mode produced no web evidence/tool call")
            print(f"{'[OK]' if trace_safe else '[FAIL]'} trace excludes hidden reasoning fields")

            sales = agent_query(
                sales_token,
                question="请查询 HR 知识库中的年度调薪月份。若无权限请明确说明。",
                mode="local",
                knowledge_base_id="kb_hr",
            )
            sales_trace = load_trace(sales_token, sales)
            sales_denied = trace_has_tool_status(sales_trace, "enterprise_search", "DENIED")
            sales_leaks = [
                item for item in sales.get("sources", []) if item.get("knowledge_base_id") == "kb_hr"
            ]
            sales_ok = sales_denied and not sales_leaks
            ok &= sales_ok
            print(f"{'[OK]' if sales_denied else '[FAIL]'} SALES -> kb_hr enterprise_search is DENIED")
            print(f"{'[OK]' if not sales_leaks else '[FAIL]'} SALES Agent result contains no kb_hr evidence")

            hr = agent_query(
                hr_token,
                question="请查询销售知识库中的合同审批规则。若无权限请明确说明。",
                mode="local",
                knowledge_base_id="kb_sales",
            )
            hr_trace = load_trace(hr_token, hr)
            hr_denied = trace_has_tool_status(hr_trace, "enterprise_search", "DENIED")
            forbidden = {"kb_sales", "kb_product", "kb_service"}
            hr_leaks = [
                item for item in hr.get("sources", []) if item.get("knowledge_base_id") in forbidden
            ]
            hr_ok = hr_denied and not hr_leaks
            ok &= hr_ok
            print(f"{'[OK]' if hr_denied else '[FAIL]'} HR -> kb_sales enterprise_search is DENIED")
            print(f"{'[OK]' if not hr_leaks else '[FAIL]'} HR Agent result contains no forbidden evidence")

        if args.web:
            web = agent_query(
                admin_token,
                question="今天 AI 行业有什么重要新闻？请调用联网搜索查找最新公开信息。",
                mode="web",
            )
            trace = load_trace(admin_token, web)
            tools = trace_tools(trace)
            web_called = "web_search" in tools
            web_sources = [item for item in web.get("sources", []) if item.get("source_type") == "web"]
            urls_ok = bool(web_sources) and all(
                str(item.get("url") or "").startswith(("http://", "https://"))
                for item in web_sources
            )
            web_ok = web_called and bool(web_sources) and urls_ok
            ok &= web_ok
            print(f"{'[OK]' if web_called else '[FAIL]'} public-current query selected web_search")
            print(f"{'[OK]' if web_sources else '[FAIL]'} web_search returned public web evidence")
            print(f"{'[OK]' if urls_ok else '[FAIL]'} web evidence exposes public HTTP(S) URLs")

    except (HTTPError, URLError, OSError, KeyError, ValueError, TypeError) as exc:
        print(f"[FAIL] Agent smoke aborted: {exc}")
        return 1

    print("\nAgent runtime smoke:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

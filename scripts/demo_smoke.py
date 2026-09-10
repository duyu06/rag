from __future__ import annotations

import argparse
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = os.environ.get("YAOKE_API", "http://localhost:8001/api").rstrip("/")

EXPECTED = {
    "ADMIN": {"kb_public", "kb_hr", "kb_product", "kb_sales", "kb_service"},
    "SALES": {"kb_public", "kb_product", "kb_sales", "kb_service"},
    "HR": {"kb_public", "kb_hr"},
}


def request(method: str, path: str, body: dict | None = None, token: str | None = None):
    headers = {}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(API + path, data=data, headers=headers, method=method)
    with urlopen(req, timeout=120) as response:
        raw = response.read().decode("utf-8")
        return response.status, json.loads(raw) if raw else None


def login(username: str, password: str):
    _, data = request("POST", "/auth/login", {"username": username, "password": password})
    return data["access_token"], data["user"]


def expect_denied(path: str, token: str) -> bool:
    try:
        request("GET", path, token=token)
    except HTTPError as exc:
        return exc.code == 403
    return False


def demo_ready(status: dict | None) -> bool:
    if not isinstance(status, dict):
        return False
    ready_count = int(status.get("ready_count", 0) or 0)
    total = int(status.get("total", 0) or 0)
    return bool(status.get("ready")) and total > 0 and ready_count == total


def main() -> int:
    parser = argparse.ArgumentParser(description="yaoke runtime RBAC smoke test")
    parser.add_argument("--retrieval", action="store_true", help="also run model-backed retrieval ACL checks")
    args = parser.parse_args()

    accounts = [
        ("admin", "admin123"),
        ("sales01", "sales123"),
        ("hr01", "hr123"),
    ]
    tokens: dict[str, str] = {}
    ok = True

    try:
        for username, password in accounts:
            token, user = login(username, password)
            role = user["role"]
            tokens[role] = token
            _, payload = request("GET", "/knowledge-bases", token=token)
            actual = {item["id"] for item in payload.get("knowledge_bases", [])}
            passed = actual == EXPECTED[role]
            ok &= passed
            print(f"{'[OK]' if passed else '[FAIL]'} {role:<5} visible KBs: {sorted(actual)}")

        denied_sales = expect_denied("/documents?" + urlencode({"knowledge_base_id": "kb_hr"}), tokens["SALES"])
        denied_hr = expect_denied("/documents?" + urlencode({"knowledge_base_id": "kb_sales"}), tokens["HR"])
        ok &= denied_sales and denied_hr
        print(f"{'[OK]' if denied_sales else '[FAIL]'} SALES -> HR direct access denied")
        print(f"{'[OK]' if denied_hr else '[FAIL]'} HR -> SALES direct access denied")

        _, status = request("GET", "/demo/status", token=tokens["ADMIN"])
        ready = demo_ready(status)
        print(f"[INFO] Demo corpus: {status.get('ready_count', 0)}/{status.get('total', 0)} indexed")

        if args.retrieval:
            if not ready:
                print("[FAIL] Retrieval smoke requires a fully initialized Demo corpus. Run Demo 初始化 / scripts/init_demo.py first.")
                return 1

            checks = [
                ("SALES", "公司年度调薪通常安排在几月？", "kb_hr"),
                ("HR", "合同金额超过100万需要谁审批？", "kb_sales"),
            ]
            for role, query, forbidden_kb in checks:
                _, result = request(
                    "POST",
                    "/retrieval/debug",
                    {"query": query, "mode": "hybrid", "top_k": 8, "rerank": False},
                    tokens[role],
                )
                rows = list(result.get("results", []))
                leaked = [row for row in rows if row.get("knowledge_base_id") == forbidden_kb]
                nonempty = bool(rows)
                passed = nonempty and not leaked
                ok &= passed
                print(f"{'[OK]' if nonempty else '[FAIL]'} {role} retrieval returned authorized candidates")
                print(f"{'[OK]' if not leaked else '[FAIL]'} {role} retrieval excludes {forbidden_kb}")

    except (HTTPError, URLError, OSError, KeyError, ValueError, TypeError) as exc:
        print(f"[FAIL] Smoke test aborted: {exc}")
        return 1

    print("\nRBAC runtime smoke:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
from urllib.request import Request, urlopen

API = os.environ.get("YAOKE_API", "http://localhost:8001/api").rstrip("/")


def request(method: str, path: str, body: dict | None = None, token: str | None = None, timeout: int = 60):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(API + path, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize the bundled yaoke Demo corpus")
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-index the bundled Demo corpus even when it is already fully ready",
    )
    args = parser.parse_args()

    login = request("POST", "/auth/login", {"username": "admin", "password": "admin123"})
    token = login["access_token"]

    status = request("GET", "/demo/status", token=token)
    ready_count = int(status.get("ready_count", 0) or 0)
    total = int(status.get("total", 0) or 0)
    if not args.force and bool(status.get("ready")) and total > 0 and ready_count == total:
        print(f"Demo corpus already ready: {ready_count}/{total}; skipping re-index. Use --force to rebuild.")
        return 0

    result = request("POST", "/demo/initialize", {}, token=token, timeout=600)
    print(result["message"])
    for item in result["results"]:
        print(f"- {item['knowledge_base_name']}: {item['file_name']} -> {item['status']} ({item['chunks_stored']} chunks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

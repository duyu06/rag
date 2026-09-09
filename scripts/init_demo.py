from __future__ import annotations

import json
from urllib.request import Request, urlopen

API = "http://localhost:8001/api"


def post(path: str, body: dict, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        API + path,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=600) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    login = post("/auth/login", {"username": "admin", "password": "admin123"})
    result = post("/demo/initialize", {}, login["access_token"])
    print(result["message"])
    for item in result["results"]:
        print(f"- {item['knowledge_base_name']}: {item['file_name']} -> {item['status']} ({item['chunks_stored']} chunks)")


if __name__ == "__main__":
    main()

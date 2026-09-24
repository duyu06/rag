from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

# tenant_access_token 有效期解析失败时的兜底值（飞书文档口径 7200 秒）。
_DEFAULT_TOKEN_EXPIRE_SECONDS = 7200.0

# 单次列表最多翻多少页。飞书一页 100 条 → 5000 个群 / 5000 个成员，演示规模下永远到不了；
# 它守的是"分页参数坏死导致的无限循环"：曾经 `"page_token": null` + `has_more: true` 被
# `str(data.get("page_token", ""))` 变成字符串 "None"（真值），1.5s 内打出 11076 个请求。
# 超过上限一律抛 `FeishuAPIError`，落进 resolver 的降级链而不是继续打飞书。
_MAX_PAGES = 50


class FeishuAPIError(RuntimeError):
    """Any Feishu failure: non-2xx HTTP status, transport error, malformed
    body, or non-zero business code. Nothing else escapes this client, so
    callers can degrade safely with a single `except FeishuAPIError`."""


@dataclass(frozen=True)
class ChatInfo:
    chat_id: str
    name: str


def _as_dict(value: object) -> dict:
    """畸形字段（None / 列表 / 字符串）当空对象，避免 KeyError/AttributeError 外逃。"""
    return value if isinstance(value, dict) else {}


def _as_objects(value: object) -> list[dict]:
    """列表中的非对象元素直接丢弃，理由同上。"""
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


class FeishuClient:
    """Tenant-token server-side client. Only the bot-visible chat universe is
    queryable, so membership is confirmed per chat via the members endpoint."""

    def __init__(self, app_id: str, app_secret: str, base_url: str,
                 timeout_seconds: float, client: httpx.Client | None = None) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._base_url = base_url.rstrip("/")
        self._http = client or httpx.Client(timeout=timeout_seconds)
        self._token = ""
        self._token_expire_at = 0.0

    def tenant_access_token(self) -> str:
        now = time.monotonic()
        if self._token and now < self._token_expire_at - 60:
            return self._token
        data = self._request("POST", "/open-apis/auth/v3/tenant_access_token/internal",
                             json={"app_id": self._app_id, "app_secret": self._app_secret}, auth=False)
        token = data.get("tenant_access_token")
        if not token:
            raise FeishuAPIError("飞书鉴权响应缺少 tenant_access_token")
        self._token = str(token)
        self._token_expire_at = now + self._expire_seconds(data.get("expire"))
        return self._token

    @staticmethod
    def _expire_seconds(raw: object) -> float:
        try:
            # raw 为 None / 非数字字符串 / 容器时分别抛 TypeError、ValueError、TypeError。
            return float(raw)
        except (TypeError, ValueError):
            return _DEFAULT_TOKEN_EXPIRE_SECONDS

    def fetch_user(self, open_id: str) -> dict:
        data = self._request("GET", f"/open-apis/contact/v3/users/{open_id}",
                             params={"user_id_type": "open_id"})
        return dict(_as_dict(data.get("user")))

    def department_name(self, department_id: str) -> str:
        data = self._request("GET", f"/open-apis/contact/v3/departments/{department_id}",
                             params={"department_id_type": "open_department_id"})
        return str(_as_dict(data.get("department")).get("name", ""))

    def list_chats(self) -> list[ChatInfo]:
        path = "/open-apis/im/v1/chats"
        chats: list[ChatInfo] = []
        page_token = ""
        for _ in range(_MAX_PAGES):
            params = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            data = self._request("GET", path, params=params)
            chats.extend(ChatInfo(str(i.get("chat_id", "")), str(i.get("name", "")))
                         for i in _as_objects(data.get("items")))
            if not data.get("has_more"):
                return chats
            # `or ""` 而非 `, ""`：响应显式给 `"page_token": null` 时 `str(None)` 是 "None"，
            # 真值 → 下一页照发 → 飞书一直返回 has_more → 无限翻页。
            page_token = str(data.get("page_token") or "")
            if not page_token:
                return chats
        raise FeishuAPIError("飞书分页超过安全上限：" + path)

    def chat_member_ids(self, chat_id: str) -> list[str]:
        path = f"/open-apis/im/v1/chats/{chat_id}/members"
        members: list[str] = []
        page_token = ""
        for _ in range(_MAX_PAGES):
            params = {"member_id_type": "open_id", "page_size": 100}
            if page_token:
                params["page_token"] = page_token
            data = self._request("GET", path, params=params)
            members.extend(str(i.get("member_id", "")) for i in _as_objects(data.get("members")))
            if not data.get("has_more"):
                return members
            page_token = str(data.get("page_token") or "")
            if not page_token:
                return members
        raise FeishuAPIError("飞书分页超过安全上限：" + path)

    def _request(self, method: str, path: str, *, json=None, params=None, auth: bool = True) -> dict:
        try:
            headers = {"Authorization": f"Bearer {self.tenant_access_token()}"} if auth else {}
            response = self._http.request(method, f"{self._base_url}{path}",
                                          json=json, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except FeishuAPIError:
            # 嵌套取 token 失败时保留原始错误语义（含"缺少 tenant_access_token"）。
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise FeishuAPIError(f"飞书接口请求失败：{path}") from exc
        except Exception as exc:  # 未预期异常一律在客户端边界收口，避免穿透降级分支
            raise FeishuAPIError(f"飞书接口请求失败：{path}") from exc
        if not isinstance(payload, dict):
            raise FeishuAPIError(f"飞书接口响应体格式异常：{path}（不是 JSON 对象）")
        if payload.get("code", 0) != 0:
            raise FeishuAPIError(f"飞书接口返回错误：{path}（业务码 {payload.get('code')}）")
        data = payload.get("data") or payload
        return data if isinstance(data, dict) else {}

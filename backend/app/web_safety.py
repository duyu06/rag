from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

_BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "metadata.google.internal"}


def safe_public_url(value: str) -> str | None:
    """Accept only normal public HTTP(S) URLs.

    NexusKB currently stores search-result URLs instead of fetching them, but keeping
    this boundary strict prevents a future web_fetch tool from inheriting unsafe URL handling.
    """
    try:
        parsed = urlparse(value.strip())
    except Exception:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.username or parsed.password:
        return None

    host = (parsed.hostname or "").rstrip(".").lower()
    if not host or host in _BLOCKED_HOSTS or host.endswith(".localhost") or host.endswith(".local"):
        return None

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return None

    return parsed.geturl()

"""Conservative page identity for retrieval deduplication, never for fetching.

Inspired by w3lib's separation of host normalization from case-sensitive paths.
Keep business query parameters (including their order) and fragment routes;
only discard unambiguous marketing parameters and ordinary anchor fragments.
"""
from __future__ import annotations

import re
from urllib.parse import unquote_plus, urlsplit, urlunsplit

_TRACKING_KEYS = frozenset({"gclid", "dclid", "fbclid", "msclkid"})


def retrieval_url_identity(url: str) -> str | None:
    """Return a safe comparison key or None for missing/malformed page URLs."""
    value = url.strip()
    if not value or re.search(r"[\s\\\x00-\x1f\x7f]|%(?![0-9a-fA-F]{2})", value):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return None
        # Credentials and malformed ports are not usable article identities.
        if parts.username is not None or parts.password is not None:
            return None
        port = parts.port
        host = parts.hostname.lower()
        if "%" in host:
            return None
        if ":" in host:
            host = f"[{host}]"
        scheme = parts.scheme.lower()
        if port is not None and (scheme, port) not in {("http", 80), ("https", 443)}:
            host = f"{host}:{port}"
    except ValueError:
        return None

    kept_query = []
    for field in parts.query.split("&"):
        key = unquote_plus(field.partition("=")[0]).lower()
        if key.startswith("utm_") or key in _TRACKING_KEYS:
            continue
        kept_query.append(field)
    # Hash routers can identify different articles, unlike ordinary anchors.
    fragment = parts.fragment if parts.fragment.startswith(("/", "!")) or "=" in parts.fragment else ""
    return urlunsplit((scheme, host, parts.path or "/", "&".join(kept_query), fragment))

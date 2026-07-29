"""URL validation to prevent SSRF attacks.

Blocks requests to internal/private networks, link-local addresses, and
non-HTTP(S) schemes before any outbound fetch is attempted.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def is_safe_url(url: str) -> bool:
    """Return True only if the URL is safe to fetch (public, HTTP(S))."""
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False

    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return False
    except ValueError:
        try:
            resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            for _, _, _, _, sockaddr in resolved:
                ip = sockaddr[0]
                addr = ipaddress.ip_address(ip)
                if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                    return False
        except (socket.gaierror, OSError):
            pass

    return True

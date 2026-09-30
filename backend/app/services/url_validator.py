"""URL validation to prevent SSRF attacks.

Blocks requests to internal/private networks, link-local addresses, and
non-HTTP(S) schemes before any outbound fetch is attempted.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def resolve_public_ip(url: str) -> str:
    """Validate the logical URL and return one address safe to pin for this hop."""
    try:
        if len(url) > 2048 or any(ord(character) < 32 or ord(character) == 127 for character in url):
            raise ValueError("invalid_public_url")
        parsed = urlparse(url.strip())
        hostname = (parsed.hostname or "").rstrip(".")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if (parsed.scheme not in {"http", "https"} or not hostname or parsed.username is not None
                or parsed.password is not None or hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal"))):
            raise ValueError("invalid_public_url")
        try:
            addresses = [ipaddress.ip_address(hostname)]
        except ValueError:
            resolved = socket.getaddrinfo(hostname, port)
            addresses = [ipaddress.ip_address(entry[4][0]) for entry in resolved]
        if not addresses or any(not address.is_global or address.is_multicast for address in addresses):
            raise ValueError("non_public_address")
        return str(addresses[0])
    except (OSError, ValueError, IndexError, TypeError) as exc:
        raise ValueError("unsafe_public_url") from exc


def is_safe_url(url: str) -> bool:
    """Return False on validation or DNS failure; transports must still pin the IP."""
    try:
        resolve_public_ip(url)
        return True
    except ValueError:
        return False

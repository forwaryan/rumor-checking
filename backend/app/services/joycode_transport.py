"""Optional JoyCode chat transport, using the locally configured Magpie login."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from backend.app.core.config import Settings


def _auth(settings: Settings) -> tuple[str, str, str]:
    if not settings.joycode_auth_file:
        raise RuntimeError("JOYCODE_AUTH_FILE is not configured")
    auth = json.loads(settings.joycode_auth_file.read_text(encoding="utf-8"))["joycode"]
    if auth.get("type") != "api" or not auth.get("key"):
        raise RuntimeError("JoyCode login is unavailable")
    metadata = auth.get("metadata") or {}
    return auth["key"], metadata.get("tenant") or "", metadata.get("loginType") or "PIN_JD_CLOUD"


def _gateway_url(settings: Settings, function_id: str) -> str:
    if not settings.joycode_base_url or not settings.joycode_sign_key:
        raise RuntimeError("JoyCode gateway and signing configuration are required")
    fields = {"appid": "joycode_ide", "functionId": function_id, "t": int(time.time() * 1000)}
    material = "&".join(str(fields[key]) for key in sorted(fields) if fields[key] not in (None, ""))
    signature = hmac.new(settings.joycode_sign_key.encode(), material.encode(), hashlib.sha256).hexdigest()
    return f"{settings.joycode_base_url}/api?{urlencode({**fields, 'sign': signature})}"


def _headers(key: str, tenant: str, login_type: str) -> dict[str, str]:
    headers = {"ptkey": key, "logintype": login_type, "Content-Type": "application/json; charset=UTF-8"}
    if tenant:
        headers["tenant"] = quote(tenant, safe="")
    return headers


def prepare_joycode_request(settings: Settings, body: dict[str, Any], *, timeout: float) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Resolve account identity and sign this request; never log credentials or URLs."""
    key, tenant, login_type = _auth(settings)
    headers = _headers(key, tenant, login_type)
    identity = httpx.post(
        _gateway_url(settings, "joycode_userInfo"),
        headers=headers,
        json={},
        timeout=min(timeout, 15.0),
    )
    identity.raise_for_status()
    result = identity.json()
    if result.get("code") is not None and int(result["code"]) != 0:
        raise RuntimeError("JoyCode account identity request failed")
    account = result.get("data") or result
    if not isinstance(account, dict) or not isinstance(account.get("userId"), str) or not account["userId"]:
        raise RuntimeError("JoyCode account identity is unavailable")
    payload = {
        **body,
        "userId": account["userId"],
        "tenant": account.get("tenant") or tenant,
        "orgFullName": account.get("orgFullName") or "",
        "language": "UNKNOWN",
    }
    return _gateway_url(settings, "chat_completions"), headers, payload

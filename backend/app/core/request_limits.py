from __future__ import annotations

import asyncio

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_REQUEST_BYTES = 1024 * 1024


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        async def reject(status: int, code: str, message: str) -> None:
            response = JSONResponse(status_code=status, content={"error": {
                "code": code, "message": message, "trace_id": scope.get("state", {}).get("request_id", "unknown"),
                "details": None,
            }})
            await response(scope, receive, send)

        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                if not value.isdigit():
                    await reject(400, "invalid_content_length", "Invalid request body length.")
                    return
                if int(value) > MAX_REQUEST_BYTES:
                    await reject(413, "request_too_large", "Request body exceeds 1 MiB.")
                    return
        body = bytearray()
        try:
            async with asyncio.timeout(30):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                        await reject(413, "request_too_large", "Request body exceeds 1 MiB.")
                        return
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await reject(408, "request_body_timeout", "Request body timed out.")
            return

        pending = True

        async def replay() -> Message:
            nonlocal pending
            if not pending:
                return await receive()
            pending = False
            content = bytes(body)
            body.clear()
            return {"type": "http.request", "body": content, "more_body": False}

        await self.app(scope, replay, send)

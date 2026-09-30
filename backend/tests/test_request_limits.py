import asyncio
import json

from backend.app.core.request_limits import MAX_REQUEST_BYTES, RequestBodyLimitMiddleware


def test_oversized_declared_body_rejected_before_receive_or_application():
    async def run():
        output = []

        async def unexpected(*args):
            raise AssertionError("oversized request reached application or body reader")

        async def send(message):
            output.append(message)

        app = RequestBodyLimitMiddleware(unexpected)
        await app({"type": "http", "method": "POST", "headers": [(b"content-length", str(MAX_REQUEST_BYTES + 1).encode())]}, unexpected, send)
        assert output[0]["status"] == 413

    asyncio.run(run())


def test_chunked_body_is_bounded_without_content_length():
    async def run():
        output = []
        chunks = iter([{"type": "http.request", "body": b"x" * (MAX_REQUEST_BYTES // 2), "more_body": True}] * 3)

        async def receive():
            return next(chunks)

        async def unexpected(*args):
            raise AssertionError("oversized request reached application")

        async def send(message):
            output.append(message)

        await RequestBodyLimitMiddleware(unexpected)({"type": "http", "method": "POST", "headers": []}, receive, send)
        assert output[0]["status"] == 413
        assert json.loads(output[1]["body"])["error"]["code"] == "request_too_large"

    asyncio.run(run())


def test_small_request_replays_body_and_preserves_disconnect():
    async def run():
        chunks = iter([{"type": "http.request", "body": b"hello", "more_body": False}, {"type": "http.disconnect"}])
        observed = []

        async def receive():
            return next(chunks)

        async def application(scope, receive, send):
            observed.extend([await receive(), await receive()])

        await RequestBodyLimitMiddleware(application)({"type": "http", "method": "POST", "headers": []}, receive, None)
        assert observed[0]["body"] == b"hello"
        assert observed[1]["type"] == "http.disconnect"

    asyncio.run(run())


def test_raw_input_character_limit_is_shared_by_new_and_legacy_endpoints(client):
    for path in ("/api/v1/analysis-runs", "/api/v1/analyze", "/api/v1/analyze/stream"):
        response = client.post(path, json={"raw_input": "x" * 100001})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


def test_json_body_limit_covers_request_context(client):
    response = client.post("/api/v1/analysis-runs", json={"raw_input": "small", "request_context": {"extra": "x" * MAX_REQUEST_BYTES}})
    assert response.status_code == 413


def test_small_chunks_are_coalesced_instead_of_retaining_unbounded_message_objects():
    async def run():
        count = 0

        async def receive():
            nonlocal count
            count += 1
            return {"type": "http.request", "body": b"x", "more_body": count < 1000}

        async def application(scope, receive, send):
            message = await receive()
            assert message["body"] == b"x" * 1000
            assert not message["more_body"]

        await RequestBodyLimitMiddleware(application)({"type": "http", "method": "POST", "headers": []}, receive, None)

    asyncio.run(run())

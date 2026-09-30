import asyncio
import json
from types import SimpleNamespace

from starlette.requests import Request

from backend.app.api.v1.endpoints.analyze import analyze_stream
from backend.app.models.schemas import AnalyzeRequest


def test_legacy_stream_handles_both_persisted_events_and_top_level_heartbeat():
    async def run():
        async def events(run_id):
            for payload in [
                {"event_id": 1, "event": {"type": "session", "run_id": run_id}},
                {"type": "heartbeat", "run_id": run_id},
                {"event_id": 2, "event": {"type": "complete", "run_id": run_id, "success": True}},
            ]:
                yield json.dumps(payload) + "\n"

        manager = SimpleNamespace(create=lambda payload: SimpleNamespace(run_id="a" * 32), events=events)
        response = await analyze_stream(AnalyzeRequest(raw_input="心跳测试"), Request({"type": "http"}), manager)
        received = [json.loads(chunk) async for chunk in response.body_iterator]
        assert [event["type"] for event in received] == ["session", "heartbeat", "complete"]
        assert received[0]["preview"] == "心跳测试"
        assert response.headers["x-analysis-run-id"] == "a" * 32

    asyncio.run(run())

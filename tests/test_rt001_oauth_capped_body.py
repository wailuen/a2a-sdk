import pytest
from starlette.requests import Request

from agent_sdk.routes import oauth


def _req(chunks):
    sent = {"n": 0}
    it = iter(chunks)

    async def receive():
        sent["n"] += 1
        try:
            return {"type": "http.request", "body": next(it), "more_body": True}
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    return Request({"type": "http", "headers": []}, receive), sent


@pytest.mark.asyncio
async def test_parse_form_stops_streaming_at_cap():
    req, sent = _req([b"a" * 8192] * 50)
    with pytest.raises(Exception):
        await oauth._parse_form(req)
    assert sent["n"] <= 3


import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from hermes.services import instagram_api


def test_local_rate_budget(client):
    instagram_api._local_calls.clear()

    async def exercise():
        for _ in range(200):
            await instagram_api._reserve("rate-user")
        with pytest.raises(instagram_api.InstagramError) as exc:
            await instagram_api._reserve("rate-user")
        assert exc.value.status == 429

    asyncio.run(exercise())


def test_backoff_on_rate_response(client, monkeypatch):
    calls = []

    class Response:
        def __init__(self, code):
            self.status_code = code
            self.headers = {}

        def json(self):
            return {"id": "ok"} if self.status_code == 200 else {"error": {"code": 4}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, *args, **kwargs):
            calls.append(args)
            return Response(429 if len(calls) == 1 else 200)

    monkeypatch.setattr(instagram_api.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(instagram_api, "asyncio", SimpleNamespace(sleep=AsyncMock()))
    assert asyncio.run(instagram_api.InstagramAPI("retry-user", "token").request("GET", "https://graph.instagram.com/test")) == {"id": "ok"}
    assert len(calls) == 2

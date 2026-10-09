from unittest.mock import AsyncMock

from hermes.database import _read, _write
from hermes.services.instagram_api import InstagramAPI


def test_insights_cached_and_forced_refresh(client, account, monkeypatch):
    monkeypatch.setattr(InstagramAPI, "profile", AsyncMock(return_value={"followers_count": 120, "follows_count": 20}))
    insights = AsyncMock(side_effect=lambda _id, metrics, **_kw: {name: 50 for name in metrics})
    monkeypatch.setattr(InstagramAPI, "insights", insights)
    data = _read()
    data.setdefault("posts", {})["post-one"] = {"id": "post-one", "account_id": account["id"], "ig_post_id": "ig-post-one", "status": "posted"}
    _write(data)
    first = client.get(f"/api/hermes/analytics/account/{account['id']}")
    assert first.status_code == 200, first.text
    assert first.json()["followers"] == 120
    client.get(f"/api/hermes/analytics/account/{account['id']}")
    assert insights.await_count == 1
    posts = client.get(f"/api/hermes/analytics/posts/{account['id']}")
    assert posts.status_code == 200, posts.text
    assert posts.json()[0]["engagement_rate"] == 400.0
    client.get(f"/api/hermes/analytics/posts/{account['id']}")
    assert insights.await_count == 2
    refreshed = client.post(f"/api/hermes/analytics/refresh/{account['id']}")
    assert refreshed.status_code == 200
    assert insights.await_count == 4


def test_analytics_owner_scope(client):
    assert client.get("/api/hermes/analytics/account/foreign").status_code == 404

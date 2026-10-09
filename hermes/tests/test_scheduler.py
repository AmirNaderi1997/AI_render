from datetime import datetime, timedelta, timezone


def test_bulk_schedule_and_calendar(client, account):
    post = client.post("/api/hermes/posts/", json={"account_id": account["id"], "media_urls": ["https://example.com/a.jpg"]}).json()
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    result = client.post("/api/hermes/schedule/bulk", json={"items": [{"post_id": post["id"], "scheduled_at": when}]})
    assert result.status_code == 200, result.text
    assert result.json()[0]["status"] == "scheduled"
    assert client.get("/api/hermes/schedule/").json()[0]["id"] == post["id"]
    assert client.post("/api/hermes/schedule/bulk", json={"items": [{"post_id": post["id"], "scheduled_at": when}] * 2}).status_code == 422


def test_schedule_rejects_past(client, account):
    post = client.post("/api/hermes/posts/", json={"account_id": account["id"], "media_urls": ["https://example.com/a.jpg"]}).json()
    when = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert client.post("/api/hermes/schedule/bulk", json={"items": [{"post_id": post["id"], "scheduled_at": when}]}).status_code == 422

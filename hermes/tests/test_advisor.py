from hermes.database import _read


def test_all_advisor_routes_log_results(client, account, monkeypatch):
    from hermes.services import advisor_service
    monkeypatch.setattr(advisor_service, "chat_json", lambda system, user, **kwargs: ({"answer": "sample"}, None))
    paths = {
        "best-times": {"account_id": account["id"], "topic": "coffee"},
        "hashtags": {"account_id": account["id"], "content": "coffee"},
        "caption": {"account_id": account["id"], "content": "coffee"},
        "content-plan": {"account_id": account["id"], "topic": "coffee"},
    }
    for path, body in paths.items():
        response = client.post("/api/hermes/advisor/" + path, json=body)
        assert response.status_code == 200, response.text
        assert response.json() == {"answer": "sample"}
    assert len(_read()["advisor_logs"]) == 4
    assert client.post("/api/hermes/advisor/hashtags", json={"account_id": "foreign", "content": "coffee"}).status_code == 404

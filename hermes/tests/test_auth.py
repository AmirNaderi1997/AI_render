from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

from hermes.config import settings
from hermes.database import _read
from hermes.services.instagram_api import InstagramAPI


def test_connect_callback_encrypt_refresh_and_replay(client, monkeypatch):
    monkeypatch.setattr(settings, "INSTAGRAM_APP_ID", "123")
    monkeypatch.setattr(settings, "INSTAGRAM_APP_SECRET", "secret")
    monkeypatch.setattr(settings, "INSTAGRAM_REDIRECT_URI", "http://localhost:8001/api/hermes/auth/callback")
    monkeypatch.setattr(InstagramAPI, "exchange_code", AsyncMock(return_value={"access_token": "short", "user_id": "ig-1"}))
    monkeypatch.setattr(InstagramAPI, "long_lived_token", AsyncMock(return_value={"access_token": "long", "expires_in": 3600}))
    monkeypatch.setattr(InstagramAPI, "profile", AsyncMock(return_value={"id": "ig-1", "username": "creator"}))
    monkeypatch.setattr(InstagramAPI, "refresh_token", AsyncMock(return_value={"access_token": "new", "expires_in": 3600}))
    url = client.post("/api/hermes/auth/connect").json()["authorization_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    response = client.get("/api/hermes/auth/callback", params={"code": "abc", "state": state})
    assert response.status_code == 200
    account_id = response.json()["id"]
    assert "access_token" not in response.json()
    assert _read()["accounts"][account_id]["access_token"] not in ("short", "long")
    assert client.get("/api/hermes/auth/callback", params={"code": "abc", "state": state}).status_code == 400
    assert client.post("/api/hermes/auth/refresh", json={"account_id": account_id}).status_code == 200
    assert "access_token" not in client.get("/api/hermes/auth/accounts").json()[0]


def test_shared_jwt_and_required_auth(client, monkeypatch):
    from hermes.main import app
    from hermes.security import current_user
    from app import auth
    app.dependency_overrides.pop(current_user)
    monkeypatch.setattr(auth, "USE_DB", False)
    monkeypatch.setattr(auth, "_find_by_id", lambda uid: auth.User(uid, "u@example.com", "U", "", 0))
    token = auth._create_access_token("user-one", "u@example.com", "U")
    assert client.get("/api/hermes/health").status_code == 401
    assert client.get("/api/hermes/health", headers={"Authorization": "Bearer " + token}).json()["status"] == "ok"

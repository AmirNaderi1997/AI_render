from unittest.mock import AsyncMock

from hermes.config import settings
from hermes.database import _read
from hermes.services.instagram_api import InstagramAPI, InstagramError


def test_settings_encrypt_mask_and_isolate(client, monkeypatch):
    for field in ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_APP_ID", "INSTAGRAM_APP_SECRET", "INSTAGRAM_BUSINESS_ACCOUNT_ID"):
        monkeypatch.setattr(settings, field, "")
    payload = {"access_token": "IGQ-token-xyz", "app_id": "123456789", "app_secret": "secret-value-xyz", "business_account_id": "178414123456789"}
    result = client.post("/api/hermes/settings", json=payload)
    assert result.status_code == 200
    assert result.json()["access_token"] == "IGQ...***xyz"
    assert result.json()["connection_status"] == "disconnected"
    persisted = _read()["settings"]["user-one"]
    assert all(persisted[field] != value and value not in str(persisted) for field, value in payload.items())
    assert all(value not in result.text for value in payload.values())
    assert client.get("/api/hermes/settings").json() == result.json()

    from hermes.main import app
    from hermes.security import current_user
    from types import SimpleNamespace
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id="user-two", is_active=True)
    other = client.get("/api/hermes/settings").json()
    assert other["access_token"] == ""
    assert other["connection_status"] == "disconnected"


def test_connection_status_uses_graph_api(client, monkeypatch):
    for field in ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_APP_ID", "INSTAGRAM_APP_SECRET", "INSTAGRAM_BUSINESS_ACCOUNT_ID"):
        monkeypatch.setattr(settings, field, "")
    client.post("/api/hermes/settings", json={"access_token": "IGQ-token-xyz", "business_account_id": "178414123456789"})
    profile = AsyncMock(return_value={"id": "178414123456789", "username": "creator"})
    monkeypatch.setattr(InstagramAPI, "profile", profile)
    assert client.post("/api/hermes/settings/test").json()["connection_status"] == "connected"
    profile.return_value = {"id": "other"}
    assert client.post("/api/hermes/settings/test").json()["connection_status"] == "disconnected"
    profile.side_effect = InstagramError("INSTAGRAM_AUTH_ERROR")
    assert client.post("/api/hermes/settings/test").json()["connection_status"] == "expired"
    profile.side_effect = InstagramError("INSTAGRAM_UNAVAILABLE")
    assert client.post("/api/hermes/settings/test").status_code == 502
    assert client.get("/api/hermes/settings").json()["connection_status"] == "expired"


def test_settings_env_precedence_and_partial_update(client, monkeypatch):
    monkeypatch.setattr(settings, "INSTAGRAM_ACCESS_TOKEN", "")
    monkeypatch.setattr(settings, "INSTAGRAM_APP_ID", "")
    monkeypatch.setattr(settings, "INSTAGRAM_APP_SECRET", "")
    monkeypatch.setattr(settings, "INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
    client.post("/api/hermes/settings", json={"access_token": "saved-token-xyz", "app_id": "saved-app-id"})
    monkeypatch.setattr(settings, "INSTAGRAM_APP_ID", "env-app-id")
    result = client.post("/api/hermes/settings", json={"app_secret": "saved-secret-xyz"}).json()
    assert result["access_token"] == "sav...***xyz"
    assert result["app_id"] == "env...***-id"
    assert result["app_secret"] == "sav...***xyz"
    assert client.post("/api/hermes/settings", json={"unexpected": "value"}).status_code == 422


def test_settings_requires_shared_jwt(client):
    from hermes.main import app
    from hermes.security import current_user
    app.dependency_overrides.pop(current_user)
    assert client.get("/api/hermes/settings").status_code == 401
    assert client.post("/api/hermes/settings", json={"access_token": "secret"}).status_code == 401
    assert client.post("/api/hermes/settings/test").status_code == 401

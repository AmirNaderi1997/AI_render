from types import SimpleNamespace
from unittest.mock import AsyncMock

from hermes.config import instagram_credentials, settings
from hermes.database import _read
from hermes.main import app
from hermes.security import current_user
from hermes.services.instagram_api import InstagramAPI, InstagramError

URL = "/api/hermes/settings/instagram"
PAYLOAD = {"access_token": "IGQ-token-xyz", "instagram_user_id": "178414123456789", "app_secret": "secret-value-xyz"}


def clear_env(monkeypatch):
    for field in ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_APP_SECRET", "INSTAGRAM_BUSINESS_ACCOUNT_ID"):
        monkeypatch.setattr(settings, field, "")


def test_save_encrypts_and_never_returns_secrets(client, monkeypatch):
    clear_env(monkeypatch)
    assert client.get(URL).json() == {"configured": False, "instagram_user_id": None}
    result = client.post(URL, json=PAYLOAD)
    assert result.status_code == 200
    assert result.json() == {"configured": True, "instagram_user_id": "178414123456789"}
    row = _read()["settings"]["instagram:user-one"]
    assert row["provider"] == "instagram"
    assert set(row["encrypted_credentials"]) == set(PAYLOAD)
    assert all(value not in str(row) for value in PAYLOAD.values())
    assert PAYLOAD["access_token"] not in result.text and PAYLOAD["app_secret"] not in client.get(URL).text


def test_settings_are_isolated_per_user_and_deletable(client, monkeypatch):
    clear_env(monkeypatch)
    client.post(URL, json=PAYLOAD)
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id="user-two", is_active=True)
    assert client.get(URL).json()["configured"] is False
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id="user-one", is_active=True)
    assert client.delete(URL).json() == {"configured": False, "instagram_user_id": None}
    assert client.get(URL).json()["configured"] is False
    assert client.delete(URL).status_code == 200  # idempotent


def test_resave_keeps_created_at(client, monkeypatch):
    clear_env(monkeypatch)
    client.post(URL, json=PAYLOAD)
    created = _read()["settings"]["instagram:user-one"]["created_at"]
    client.post(URL, json={**PAYLOAD, "instagram_user_id": "999"})
    assert _read()["settings"]["instagram:user-one"]["created_at"] == created
    assert client.get(URL).json()["instagram_user_id"] == "999"


def test_validation_rejects_blank_missing_and_extra_fields(client):
    assert client.post(URL, json={**PAYLOAD, "access_token": "   "}).status_code == 422
    assert client.post(URL, json={"access_token": "x"}).status_code == 422
    assert client.post(URL, json={**PAYLOAD, "unexpected": "value"}).status_code == 422


def test_database_credentials_take_precedence_over_env(client, monkeypatch):
    import asyncio
    clear_env(monkeypatch)
    monkeypatch.setattr(settings, "INSTAGRAM_ACCESS_TOKEN", "env-token")
    monkeypatch.setattr(settings, "INSTAGRAM_APP_SECRET", "env-secret")
    monkeypatch.setattr(settings, "INSTAGRAM_BUSINESS_ACCOUNT_ID", "env-id")
    assert asyncio.run(instagram_credentials("user-one"))["access_token"] == "env-token"
    client.post(URL, json=PAYLOAD)
    values = asyncio.run(instagram_credentials("user-one"))
    assert (values["access_token"], values["app_secret"], values["business_account_id"]) == (
        "IGQ-token-xyz", "secret-value-xyz", "178414123456789")
    client.delete(URL)
    assert asyncio.run(instagram_credentials("user-one"))["access_token"] == "env-token"


def test_unreadable_stored_credentials_fall_back_to_env(client, monkeypatch):
    import asyncio
    clear_env(monkeypatch)
    client.post(URL, json=PAYLOAD)
    monkeypatch.setattr(settings, "HERMES_ENCRYPTION_KEY", "a-different-key-after-restart-0000")
    monkeypatch.setattr(settings, "INSTAGRAM_ACCESS_TOKEN", "env-token")
    assert asyncio.run(instagram_credentials("user-one"))["access_token"] == "env-token"
    assert client.get(URL).json()["configured"] is False


def test_connection_status_uses_graph_api(client, monkeypatch):
    clear_env(monkeypatch)
    client.post(URL, json=PAYLOAD)
    profile = AsyncMock(return_value={"id": "178414123456789", "username": "creator"})
    monkeypatch.setattr(InstagramAPI, "profile", profile)
    assert client.post(URL + "/test").json()["connection_status"] == "connected"
    profile.return_value = {"id": "other"}
    assert client.post(URL + "/test").json()["connection_status"] == "disconnected"
    profile.side_effect = InstagramError("INSTAGRAM_AUTH_ERROR")
    assert client.post(URL + "/test").json()["connection_status"] == "expired"
    profile.side_effect = InstagramError("INSTAGRAM_UNAVAILABLE")
    assert client.post(URL + "/test").status_code == 502


def test_settings_requires_shared_jwt(client):
    app.dependency_overrides.pop(current_user)
    assert client.get(URL).status_code == 401
    assert client.post(URL, json=PAYLOAD).status_code == 401
    assert client.delete(URL).status_code == 401
    assert client.post(URL + "/test").status_code == 401

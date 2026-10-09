from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from hermes import database
from hermes.config import settings
from hermes.main import app
from hermes.security import current_user, encrypt_token


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "HERMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "DATABASE_URL", "")
    monkeypatch.setattr(settings, "REDIS_URL", "")
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "Session", None)
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id="user-one", is_active=True)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def account(client):
    value = {
        "id": "account-one", "user_id": "user-one", "ig_user_id": "1784140000",
        "username": "test_creator", "access_token": encrypt_token("ig-token"),
        "token_expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(), "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    database._write({**database._read(), "accounts": {value["id"]: value}})
    return value

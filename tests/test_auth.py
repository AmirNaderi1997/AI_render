"""Authentication tests."""
from __future__ import annotations
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import auth, jobs as jobstore


@pytest.fixture(autouse=True)
def clean_users(tmp_path, monkeypatch):
    users_file = tmp_path / "users.json"
    monkeypatch.setattr(auth, "USERS_FILE", users_file)
    monkeypatch.setattr(auth, "_secret", "test-secret-key-for-jwt-at-least-32-bytes")
    monkeypatch.setattr(auth, "USE_DB", False)
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir()
    monkeypatch.setattr(jobstore, "JOBS_ROOT", jobs_root)
    jobstore._jobs.clear()
    yield
    jobstore._jobs.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _signup(client, email="test@example.com", name="Test User", password="password123"):
    return client.post("/auth/signup", json={"email": email, "name": name, "password": password})


def _login(client, email="test@example.com", password="password123"):
    return client.post("/auth/login", json={"email": email, "password": password})


def _auth_header(client, email="test@example.com", name="Test User", password="password123"):
    r = _signup(client, email, name, password)
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestSignup:
    def test_signup_success(self, client):
        r = _signup(client)
        assert r.status_code == 201
        data = r.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == "test@example.com"
        assert data["user"]["name"] == "Test User"
        cookie = r.cookies.get("ai_render_refresh_token")
        assert cookie == data["refresh_token"]
        set_cookie = r.headers["set-cookie"].lower()
        assert "httponly" in set_cookie
        assert "samesite=lax" in set_cookie

    def test_signup_duplicate_email(self, client):
        _signup(client)
        r = _signup(client)
        assert r.status_code == 409

    def test_signup_weak_password(self, client):
        r = _signup(client, password="short")
        assert r.status_code == 422

    def test_signup_invalid_email(self, client):
        r = _signup(client, email="notanemail")
        assert r.status_code == 422


class TestLogin:
    def test_login_success(self, client):
        _signup(client)
        r = _login(client)
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert "refresh_token" in data
        set_cookie = r.headers["set-cookie"].lower()
        assert "ai_render_refresh_token=" in set_cookie
        assert "httponly" in set_cookie
        assert "samesite=lax" in set_cookie

    def test_login_wrong_password(self, client):
        _signup(client)
        r = _login(client, password="wrongpassword")
        assert r.status_code == 401

    def test_login_nonexistent_email(self, client):
        r = _login(client, email="nobody@example.com")
        assert r.status_code == 401


class TestProtectedRoutes:
    def test_protected_route_no_token(self, client):
        r = client.get("/jobs")
        assert r.status_code == 401

    def test_protected_route_valid_token(self, client):
        headers = _auth_header(client)
        r = client.get("/jobs", headers=headers)
        assert r.status_code == 200

    def test_protected_route_expired_token(self, client, monkeypatch):
        monkeypatch.setattr(auth, "ACCESS_TOKEN_EXPIRES", -1)
        r = _signup(client)
        token = r.json()["access_token"]
        r = client.get("/jobs", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_health_check_no_auth(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_job_owner_is_persisted_and_other_user_is_forbidden(self, client):
        owner = _signup(client, email="owner@example.com").json()
        created = client.post(
            "/jobs",
            headers={"Authorization": f"Bearer {owner['access_token']}"},
            files={"video": ("raw.mp4", b"video", "video/mp4")},
        )
        assert created.status_code == 201
        job_id = created.json()["job"]["id"]
        assert created.json()["job"]["user_id"] == owner["user"]["id"]
        assert json.loads((jobstore.JOBS_ROOT / job_id / "status.json").read_text())["user_id"] == owner["user"]["id"]

        other = _signup(client, email="other@example.com").json()
        headers = {"Authorization": f"Bearer {other['access_token']}"}
        assert client.get(f"/jobs/{job_id}", headers=headers).status_code == 403
        # Ownership is checked before FastAPI reports the missing required plan body.
        assert client.put(f"/jobs/{job_id}/plan", headers=headers, json={}).status_code == 403


class TestRefresh:
    def test_refresh_token_flow(self, client):
        r = _signup(client)
        refresh = r.json()["refresh_token"]
        r = client.post("/auth/refresh", json={"refresh_token": refresh})
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_refresh_invalid_token(self, client):
        r = client.post("/auth/refresh", json={"refresh_token": "invalid"})
        assert r.status_code == 401

    def test_refresh_from_httponly_cookie(self, client):
        assert _signup(client).status_code == 201
        r = client.post("/auth/refresh")
        assert r.status_code == 200
        assert "access_token" in r.json()


class TestPasswordReset:
    def test_forgot_password_generates_token(self, client):
        _signup(client)
        r = client.post("/auth/forgot-password", json={"email": "test@example.com"})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert "_dev_token" in r.json()

    def test_reset_password_valid_token(self, client):
        _signup(client)
        r = client.post("/auth/forgot-password", json={"email": "test@example.com"})
        token = r.json()["_dev_token"]
        r = client.post("/auth/reset-password", json={"token": token, "new_password": "newpass1234"})
        assert r.status_code == 200
        r = _login(client, password="newpass1234")
        assert r.status_code == 200

    def test_reset_password_invalid_token(self, client):
        r = client.post("/auth/reset-password", json={"token": "invalid", "new_password": "newpass1234"})
        assert r.status_code == 400

    def test_reset_password_expired_token(self, client, monkeypatch):
        _signup(client)
        monkeypatch.setattr(auth, "RESET_TOKEN_EXPIRES", -1)
        r = client.post("/auth/forgot-password", json={"email": "test@example.com"})
        token = r.json()["_dev_token"]
        r = client.post("/auth/reset-password", json={"token": token, "new_password": "newpass1234"})
        assert r.status_code == 400


class TestMe:
    def test_get_me(self, client):
        headers = _auth_header(client)
        r = client.get("/auth/me", headers=headers)
        assert r.status_code == 200
        assert r.json()["email"] == "test@example.com"


class TestLogout:
    def test_logout_invalidates_refresh(self, client):
        r = _signup(client)
        refresh = r.json()["refresh_token"]
        client.post("/auth/logout", json={"refresh_token": refresh})
        r = client.post("/auth/refresh", json={"refresh_token": refresh})
        assert r.status_code == 401

    def test_logout_uses_and_clears_refresh_cookie(self, client):
        assert _signup(client).status_code == 201
        r = client.post("/auth/logout")
        assert r.status_code == 200
        assert r.cookies.get("ai_render_refresh_token") is None
        assert client.post("/auth/refresh").status_code == 401

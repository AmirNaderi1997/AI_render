"""Focused readiness, request tracing, and redaction tests."""
from __future__ import annotations

import asyncio
import importlib
import io
import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pythonjsonlogger import jsonlogger

from app import health
from app.main import app, log
from hermes.main import app as hermes_app
from logging_config import SensitiveDataFilter


main_module = importlib.import_module("app.main")


@app.get("/auth/__observability_failure", include_in_schema=False)
async def _observability_failure():
    raise LookupError("response and logs must not expose this message")


def _set_health_checks(monkeypatch, *, database=True, redis=True, celery=True, disk=True, ffmpeg=True):
    for name, result in {
        "database": database,
        "redis": redis,
        "celery": celery,
        "disk": disk,
        "ffmpeg": ffmpeg,
    }.items():
        async def check(value=result):
            if isinstance(value, Exception):
                raise value
            return value

        monkeypatch.setattr(health, f"_check_{name}", check)


def test_readiness_all_checks_pass(monkeypatch):
    _set_health_checks(monkeypatch)

    response = TestClient(app).get("/api/health/ready")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["degraded"] is False
    assert {name: value["status"] for name, value in response.json()["checks"].items()} == {
        "database": "pass", "redis": "pass", "celery": "pass", "disk": "pass", "ffmpeg": "pass",
    }


def test_readiness_database_failure_is_503(monkeypatch):
    _set_health_checks(monkeypatch, database=False)

    response = TestClient(app).get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["ok"] is False
    assert response.json()["checks"]["database"]["status"] == "fail"


def test_readiness_celery_failure_is_degraded_200(monkeypatch):
    _set_health_checks(monkeypatch, celery=False)

    response = TestClient(app).get("/api/health/ready")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["degraded"] is True
    assert response.json()["checks"]["celery"]["status"] == "fail"


def test_readiness_never_exposes_dependency_error_details(monkeypatch):
    secret = "postgresql://admin:password@db.internal:5432/app"
    _set_health_checks(monkeypatch, database=RuntimeError(secret), redis=RuntimeError("redis://cache.internal"))

    response = TestClient(app).get("/api/health/ready")

    assert response.status_code == 503
    assert secret not in response.text
    assert "db.internal" not in response.text
    assert "cache.internal" not in response.text


def test_readiness_check_timeout_is_bounded(monkeypatch):
    async def slow_check():
        await asyncio.sleep(1)
        return True

    monkeypatch.setattr(health, "CHECK_TIMEOUT_SECONDS", 0.01)
    result = asyncio.run(health._timed_check(slow_check))

    assert result["status"] == "fail"
    assert result["duration_ms"] < 200


def test_celery_ping_is_cached_for_fifteen_seconds(monkeypatch):
    calls = []

    class Inspect:
        def ping(self):
            calls.append("ping")
            return {"worker": {"ok": "pong"}}

    fake_celery = SimpleNamespace(control=SimpleNamespace(inspect=lambda timeout: Inspect()))
    monkeypatch.setattr(health, "CELERY_AVAILABLE", True)
    monkeypatch.setattr(health, "celery", fake_celery)
    monkeypatch.setattr(health, "_celery_cache", None)

    assert health._celery_ping_cached() is True
    assert health._celery_ping_cached() is True
    assert calls == ["ping"]


def test_request_id_header_is_echoed():
    response = TestClient(app).get("/health", headers={"X-Request-ID": "trace-123"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.headers["X-Request-ID"] == "trace-123"


def test_request_id_is_generated_when_missing():
    response = TestClient(app).get("/health")

    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        response.headers["X-Request-ID"],
    )


def test_hermes_request_id_header_is_echoed():
    response = TestClient(hermes_app).get("/health", headers={"X-Request-ID": "hermes-trace-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "hermes-trace-123"


def test_request_id_and_request_fields_appear_in_json_log_output():
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(jsonlogger.JsonFormatter())
    handler.addFilter(SensitiveDataFilter())
    old_level = log.level
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        response = TestClient(app).get("/health", headers={"X-Request-ID": "trace-log-456"})
    finally:
        log.removeHandler(handler)
        log.setLevel(old_level)

    records = [json.loads(line) for line in output.getvalue().splitlines()]
    request_record = next(record for record in records if record.get("event") == "http_request")
    assert response.headers["X-Request-ID"] == "trace-log-456"
    assert request_record["request_id"] == "trace-log-456"
    assert request_record["method"] == "GET"
    assert request_record["path"] == "/health"
    assert request_record["status_code"] == 200
    assert isinstance(request_record["duration_ms"], (int, float))


def test_slow_request_logs_at_warning(monkeypatch, caplog):
    ticks = iter((100.0, 102.01))
    monkeypatch.setattr(main_module, "time", SimpleNamespace(monotonic=lambda: next(ticks)))

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        response = TestClient(app).get("/health")

    record = next(record for record in caplog.records if getattr(record, "event", None) == "http_request")
    assert response.status_code == 200
    assert record.levelno == logging.WARNING
    assert record.duration_ms == 2010.0


def test_unhandled_request_failure_logs_error_type_without_message(caplog):
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        response = TestClient(app).get("/auth/__observability_failure")

    record = next(record for record in caplog.records if getattr(record, "event", None) == "http_request")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert record.levelno == logging.ERROR
    assert record.exception_type == "LookupError"
    assert "response and logs must not expose this message" not in caplog.text


def test_sensitive_filter_redacts_new_structured_fields():
    record = logging.makeLogRecord({
        "msg": "request",
        "request_id": "token=secret-token-value",
        "path": "/users/person@example.com/from/203.0.113.10",
        "method": "GET",
        "status_code": 500,
        "duration_ms": 1.0,
    })

    assert SensitiveDataFilter().filter(record) is True
    rendered = json.dumps(record.__dict__)
    assert "secret-token-value" not in rendered
    assert "person@example.com" not in rendered
    assert "203.0.113.10" not in rendered
    assert rendered.count("[REDACTED]") >= 3


def test_encoded_email_is_redacted_from_application_and_nginx_access_logs():
    email = "log-probe-codex-20261010%40example.invalid"
    record = logging.makeLogRecord({"msg": f'GET /jobs/{email} HTTP/1.1 " 401'})

    assert SensitiveDataFilter().filter(record) is True
    assert email not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()

    nginx_config = (Path(__file__).resolve().parents[1] / "nginx" / "nginx.conf").read_text()
    assert "map $uri $safe_log_path" in nginx_config
    assert "~*(?:@|%40) \"[REDACTED]\";" in nginx_config
    assert '"path":"$safe_log_path"' in nginx_config

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import auth, jobs as jobstore, premiere_desktop
from app import main
from app.main import app
from engine.premiere import build_premiere
from engine.schema import validate_plan


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "USE_DB", False)
    monkeypatch.setattr(auth, "_secret", "test-secret-key-for-jwt-at-least-32-bytes")
    monkeypatch.setattr(auth, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(jobstore, "JOBS_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(jobstore, "DB_AVAILABLE", False)
    monkeypatch.setattr(main, "DB_AVAILABLE", False)
    jobstore.JOBS_ROOT.mkdir()
    jobstore._jobs.clear()
    with TestClient(app) as test_client:
        signup = test_client.post("/auth/signup", json={
            "email": "upload-recovery@example.com", "name": "Upload", "password": "password123"
        })
        assert signup.status_code == 201
        test_client.headers.update({"Authorization": f"Bearer {signup.json()['access_token']}"})
        yield test_client
    jobstore._jobs.clear()


def test_interrupted_upload_creates_no_job_row_or_partial_file(client, monkeypatch):
    def fail_stream(*args, **kwargs):
        job = args[0]
        partial = job.dir / "raw" / "clip.mp4"
        partial.write_bytes(b"partial")
        raise OSError("simulated interrupted stream")

    monkeypatch.setattr(jobstore, "save_raw", fail_stream)
    response = client.post("/jobs", files={"video": ("clip.mp4", b"complete upload", "video/mp4")})
    assert response.status_code == 500
    assert jobstore.list_jobs() == []
    assert list(jobstore.JOBS_ROOT.iterdir()) == []


def test_successful_upload_round_trips_through_raw(client):
    payload = b"verified source bytes"
    response = client.post("/jobs", files={"video": ("clip.mp4", payload, "video/mp4")})
    assert response.status_code == 201
    job_id = response.json()["job"]["id"]
    raw_response = client.get(f"/jobs/{job_id}/raw")
    assert raw_response.status_code == 200
    assert raw_response.content == payload


def test_premiere_status_requires_a_plan(client):
    created = client.post("/jobs", files={"video": ("clip.mp4", b"source", "video/mp4")})
    assert created.status_code == 201
    job_id = created.json()["job"]["id"]
    response = client.get(f"/jobs/{job_id}/premiere/status")
    assert response.status_code == 409
    assert response.json()["detail"] == "Generate a plan first"


def test_missing_source_returns_404_for_raw_premiere_music_and_denoise(client, media_dir):
    plan = json.loads((Path(__file__).parents[1] / "samples/plans/cut.json").read_text())
    plan["source"] = "raw/clip.mp4"
    created = client.post("/jobs", files={
        "video": ("clip.mp4", (media_dir / "raw.mp4").read_bytes(), "video/mp4"),
        "plan_text": (None, json.dumps(plan)),
    })
    assert created.status_code == 201, created.text
    job_id = created.json()["job"]["id"]
    job = jobstore.get(job_id)
    (job.dir / "music").mkdir()
    (job.dir / "music" / "track.mp3").write_bytes(b"track")
    job.music.file = "music/track.mp3"
    (job.dir / "raw" / "clip.mp4").unlink()

    for response in (
        client.get(f"/jobs/{job_id}/raw"),
        client.get(f"/jobs/{job_id}/premiere/status"),
        client.get(f"/jobs/{job_id}/music/preview"),
        client.post(f"/jobs/{job_id}/denoise/start", json={"strength": 0.5}),
    ):
        assert response.status_code == 404
        assert response.json()["detail"] == "Source media missing"


def test_premiere_status_reads_plan_record_from_database(tmp_path, media_dir, monkeypatch):
    job_dir = tmp_path / "abcdef123456"
    job_dir.mkdir()
    (job_dir / "exports").mkdir()
    (job_dir / "raw").mkdir()
    (job_dir / "raw" / "raw.mp4").write_bytes((media_dir / "raw.mp4").read_bytes())
    job = jobstore.Job(id=job_dir.name, dir=job_dir, raw_name="raw.mp4")
    plan_data = json.loads((Path(__file__).parents[1] / "samples/plans/cut.json").read_text())
    plan_data["source"] = "raw/raw.mp4"
    plan, errors = validate_plan(plan_data, base_dir=job.dir, check_media=True)
    assert not errors
    build_premiere(plan, job.dir, base_dir=job.dir)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, _statement):
            return SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(data=plan_data))

    monkeypatch.setattr(jobstore, "DB_AVAILABLE", True)
    monkeypatch.setattr(jobstore, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(jobstore, "_await_db", lambda coro: asyncio.run(coro))
    job.raw_name = "raw.mp4"
    job.plan_data = None

    status = premiere_desktop.status(job)
    assert status["editable_plan"] == "ready", status.get("warnings")
    assert job.plan_data == plan_data


def test_orphan_cleanup_marks_missing_upload_failed_without_deleting_row(tmp_path, monkeypatch):
    root = tmp_path / "jobs"
    root.mkdir()
    monkeypatch.setattr(jobstore, "JOBS_ROOT", root)
    orphan = SimpleNamespace(
        id="orphan123456", source_path="raw/clip.mp4", status="new", message=""
    )
    present = SimpleNamespace(
        id="present12345", source_path="raw/clip.mp4", status="new", message=""
    )
    (root / orphan.id / "raw").mkdir(parents=True)
    (root / present.id / "raw").mkdir(parents=True)
    (root / present.id / "raw" / "clip.mp4").write_bytes(b"kept")

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, _statement):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [orphan, present]))

        async def commit(self):
            pass

    monkeypatch.setattr(jobstore, "DB_AVAILABLE", True)
    monkeypatch.setattr(jobstore, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(jobstore, "_await_db", lambda coro: asyncio.run(coro))

    assert jobstore.cleanup_orphaned_jobs() == 1
    assert orphan.status == "failed"
    assert orphan.message == "Upload was interrupted. Please upload again."
    assert (root / orphan.id).is_dir()
    assert present.status == "new"


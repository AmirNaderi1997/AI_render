"""Rescan test: a job on disk (status.json, plan.json, raw, exports) survives
a fresh backend process. Simulates restart by clearing the in-memory registry
and calling jobstore.rescan(), which is the same function main.py's startup
event runs.
"""
from __future__ import annotations
import json
from pathlib import Path
import pytest

from app import jobs as jobstore


def test_rescan_restores_job_with_plan_and_exports(tmp_path, monkeypatch):
    if not jobstore.DB_AVAILABLE:
        pytest.skip("job rescan requires PostgreSQL metadata persistence")
    root = tmp_path / "jobs"
    root.mkdir()
    monkeypatch.setattr(jobstore, "JOBS_ROOT", root)

    # Simulate the previous process: create job, save raw + plan, "render" v1.
    job = jobstore.create_job()
    jid = job.id
    (job.dir / "raw" / "video.mp4").write_bytes(b"\x00fake")
    job.raw_name = "video.mp4"
    plan_body = {"version": "0.1", "hello": "world"}
    (job.dir / "plan.json").write_text(json.dumps(plan_body))
    (job.dir / "exports" / "v1.mp4").write_bytes(b"\x00fake")
    job.versions = ["v1.mp4"]
    # Also leave a stale "running" status behind — rescan must reset it.
    job.render.status = "running"
    job.render.progress = 42
    jobstore._write_status(job)

    # Simulate a fresh process: wipe memory, then rescan from disk.
    with jobstore._lock:
        jobstore._jobs.clear()
    assert jobstore.get(jid) is None

    n = jobstore.rescan()
    assert n == 1

    restored = jobstore.get(jid)
    assert restored is not None
    assert restored.raw_name == "video.mp4"
    assert (restored.dir / "plan.json").exists()
    assert jobstore.load_plan(restored) == plan_body
    assert restored.versions == ["v1.mp4"]
    assert (restored.dir / "exports" / "v1.mp4").exists()
    # Stale running state has been cleared.
    assert restored.render.status == "idle"
    assert restored.render.progress == 0

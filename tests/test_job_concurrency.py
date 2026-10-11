from __future__ import annotations

from pathlib import Path

import pytest

from app import jobs


class _NoStartThread:
    started = 0

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        type(self).started += 1


def _job(tmp_path: Path) -> jobs.Job:
    tmp_path.mkdir(exist_ok=True)
    return jobs.Job(id="0123456789ab", dir=tmp_path)


def test_duplicate_render_requests_do_not_start_two_workers(tmp_path, monkeypatch):
    _NoStartThread.started = 0
    monkeypatch.setattr(jobs.threading, "Thread", _NoStartThread)
    job = _job(tmp_path)

    jobs.start_render(job)
    jobs.start_render(job, preview=True)

    assert job.render.status == "queued"
    assert job.render.preview is False
    assert _NoStartThread.started == 1


def test_new_render_invalidates_previous_qc_results(tmp_path, monkeypatch):
    _NoStartThread.started = 0
    monkeypatch.setattr(jobs.threading, "Thread", _NoStartThread)
    monkeypatch.setattr(jobs, "DB_AVAILABLE", False)
    job = _job(tmp_path)
    job.qc = jobs.QCState(
        status="done",
        total_issues=1,
        issues=[{"type": "old_problem", "description": "stale"}],
    )

    jobs.start_render(job, preview=True)

    assert job.qc == jobs.QCState()
    assert job.render.status == "queued"
    assert job.render.preview is True


def test_plan_generation_persists_before_dispatch_without_registry_lock_deadlock(tmp_path, monkeypatch):
    _NoStartThread.started = 0
    monkeypatch.setattr(jobs.threading, "Thread", _NoStartThread)
    monkeypatch.setattr(jobs, "DB_AVAILABLE", False)
    job = _job(tmp_path)
    job.raw_name = "source.mp4"

    jobs.start_generate(job)

    assert job.generate.status == "running"
    assert _NoStartThread.started == 1
    with jobs._lock:
        jobs._jobs.pop(job.id, None)


def test_render_is_rejected_while_plan_generation_runs(tmp_path):
    job = _job(tmp_path)
    job.generate.status = "running"
    with pytest.raises(ValueError, match="generation must finish"):
        jobs.start_render(job)


def test_plan_generation_is_rejected_while_render_is_queued(tmp_path):
    job = _job(tmp_path)
    job.render.status = "queued"
    with pytest.raises(ValueError, match="render must finish"):
        jobs.start_generate(job)

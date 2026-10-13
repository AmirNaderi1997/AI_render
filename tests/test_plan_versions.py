"""Plan versioning, the operations/undo endpoints, and locks across regeneration."""
from __future__ import annotations

import pytest

from engine import operations as ops_module
from engine import schema


def _plan() -> dict:
    return {
        "canvas": {"width": 1080, "height": 1920, "fps": 30},
        "source": "raw/test.mp4",
        "segments": [{"id": "s1", "in": 0.0, "out": 3.0}, {"id": "s2", "in": 5.0, "out": 8.0}],
        "visual_effects": [{"segment_id": "s1", "type": "steady__neutral"}],
        "captions": [{"start": 0.5, "end": 2.0, "text": "Hello"}, {"start": 3.5, "end": 5.0, "text": "Later"}],
        "music": {"file": "m.mp3", "volume_db": -14},
        "export": {"file": "out.mp4"},
    }


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A job store with no database (file fallback) and no media probing."""
    from app import jobs, plan_versions
    monkeypatch.setattr(jobs, "DB_AVAILABLE", False)

    def no_media(data, base_dir=None, check_media=True):
        return schema.validate_plan(data, base_dir=base_dir, check_media=False)
    monkeypatch.setattr(jobs, "validate_plan", no_media)
    monkeypatch.setattr(ops_module, "validate_plan", no_media)
    job = jobs.Job(id="job1", dir=tmp_path)
    monkeypatch.setattr(jobs, "get", lambda _id: job)
    return jobs, plan_versions, job


def test_save_plan_records_versions_with_baseline(store):
    jobs, versions, job = store
    job.plan_data = _plan()  # saved before versioning existed
    edited = {**_plan(), "music": {"file": "m.mp3", "volume_db": -20}}
    _, errors = jobs.save_plan(job, edited)
    assert not errors
    rows = versions.list_versions(job)
    assert [(r["version"], r["parent_version"], r["source"]) for r in rows] == [
        (1, None, "legacy"), (2, 1, "user_ui")]
    assert "plan" not in rows[0]
    assert versions.get_version(job, 1)["plan"]["music"]["volume_db"] == -14


def test_operations_dry_run_apply_and_undo(store):
    jobs, versions, job = store
    jobs.save_plan(job, _plan(), source="ai_generate")
    op = [{"op": "set_music_volume", "volume_db": -22}]

    dry = jobs.apply_plan_operations(job, op, dry_run=True)
    assert dry["diff"] == [{"path": "music.volume_db", "before": -14, "after": -22}]
    assert job.plan_data["music"]["volume_db"] == -14
    assert len(versions.list_versions(job)) == 1

    applied = jobs.apply_plan_operations(job, op, base_version=1)
    assert applied["version"] == 2 and job.plan_data["music"]["volume_db"] == -22
    v2 = versions.get_version(job, 2)
    assert v2["source"] == "user_ui" and v2["operations"] == [{"op": "set_music_volume", "volume_db": -22.0}]

    with pytest.raises(jobs.PlanVersionConflict):
        jobs.apply_plan_operations(job, op, base_version=1)

    undone = jobs.undo_plan(job)
    assert undone["restored_version"] == 1 and undone["version"] == 3
    assert job.plan_data["music"]["volume_db"] == -14
    with pytest.raises(ValueError, match="nothing to undo"):
        jobs.undo_plan(job)  # v3's parent is v1's parent (none)


def test_repeated_undo_walks_back(store):
    jobs, versions, job = store
    jobs.save_plan(job, _plan(), source="ai_generate")
    for volume in (-16, -18, -20):
        jobs.apply_plan_operations(job, [{"op": "set_music_volume", "volume_db": volume}])
    assert jobs.undo_plan(job)["restored_version"] == 3
    assert jobs.undo_plan(job)["restored_version"] == 2
    assert job.plan_data["music"]["volume_db"] == -16


def test_failed_batch_saves_nothing(store):
    jobs, versions, job = store
    jobs.save_plan(job, _plan())
    with pytest.raises(ops_module.OperationError):
        jobs.apply_plan_operations(job, [{"op": "set_music_volume", "volume_db": -30},
                                         {"op": "remove_broll", "index": 0}])
    assert job.plan_data["music"]["volume_db"] == -14
    assert len(versions.list_versions(job)) == 1


def test_chat_edits_respect_locks(store):
    jobs, _versions, job = store
    jobs.save_plan(job, _plan())
    jobs.apply_plan_operations(job, [{"op": "lock", "target": "music"}])
    with pytest.raises(ops_module.LockedError):
        jobs.apply_plan_operations(job, [{"op": "set_music_volume", "volume_db": -30}], source="chat")
    jobs.apply_plan_operations(job, [{"op": "set_music_volume", "volume_db": -30}])
    assert job.plan_data["music"]["volume_db"] == -30


def test_edits_blocked_while_generating(store):
    jobs, _versions, job = store
    jobs.save_plan(job, _plan())
    job.generate.status = "running"
    with pytest.raises(ValueError, match="generation"):
        jobs.apply_plan_operations(job, [{"op": "set_music_volume", "volume_db": -30}])


def test_qc_apply_records_qc_version(store, monkeypatch):
    jobs, versions, job = store
    jobs.save_plan(job, _plan())
    job.qc.issues = [{"segment_id": "s1", "timestamp": 1.0, "type": "frozen_frame",
                      "suggested_fix": "add_zoom_effect"}]
    monkeypatch.setattr("brain.qc_patch.validate_plan",
                        lambda data, base_dir=None, check_media=True: schema.validate_plan(data, check_media=False))
    _, changes = jobs.apply_qc_fixes(job)
    assert changes
    latest = versions.latest_version(job)
    assert latest["source"] == "qc"
    assert latest["operations"] == [{"op": "set_effect", "segment_id": "s1", "effect": "slow_push__neutral"}]


# --- HTTP endpoints -----------------------------------------------------------

@pytest.fixture
def client(store):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import plans
    app = FastAPI()
    app.include_router(plans.router)
    jobs, _versions, job = store
    jobs.save_plan(job, _plan(), source="ai_generate")
    return TestClient(app), job


def test_operations_endpoint(client):
    http, job = client
    body = {"operations": [{"op": "set_caption_text", "index": 0, "text": "Hi"}], "dry_run": True}
    r = http.post("/jobs/job1/operations", json=body)
    assert r.status_code == 200 and r.json()["diff"][0]["path"] == "captions[0].text"
    assert job.plan_data["captions"][0]["text"] == "Hello"

    r = http.post("/jobs/job1/operations", json={**body, "dry_run": False})
    assert r.json()["version"] == 2 and job.plan_data["captions"][0]["text"] == "Hi"

    assert http.post("/jobs/job1/operations", json={**body, "base_version": 1}).status_code == 409
    bad = http.post("/jobs/job1/operations", json={"operations": [{"op": "set_effect", "segment_id": "nope",
                                                                   "effect": "steady"}]})
    assert bad.status_code == 422 and bad.json()["index"] == 0
    assert http.post("/jobs/job1/operations", json={"operations": [{"op": "fly"}]}).status_code == 422

    http.post("/jobs/job1/operations", json={"operations": [{"op": "lock", "target": "caption", "index": 0}]})
    locked = http.post("/jobs/job1/operations", json={"source": "chat", "operations": [
        {"op": "set_caption_text", "index": 0, "text": "nope"}]})
    assert locked.status_code == 423

    versions = http.get("/jobs/job1/plan/versions").json()
    assert versions["current"] == 3 and [v["source"] for v in versions["versions"]] == [
        "ai_generate", "user_ui", "user_ui"]

    undo = http.post("/jobs/job1/plan/undo")
    assert undo.status_code == 200 and undo.json()["restored_version"] == 2


def test_endpoints_enforce_job_ownership(client):
    http, job = client
    job.user_id = "42"
    calls = [http.post("/jobs/job1/operations", json={"operations": []}),
             http.get("/jobs/job1/plan/versions"),
             http.post("/jobs/job1/plan/undo")]
    assert [c.status_code for c in calls] == [403] * 3


# --- locks across regeneration ----------------------------------------------

def test_locked_items_survive_regeneration():
    from app.jobs import _restore_locked
    old = _plan()
    old["visual_effects"][0]["locked"] = True
    old["captions"][1]["locked"] = True          # output 3.5–5.0 -> source 5.5–7.0
    old["music"] = {"file": "m.mp3", "volume_db": -30, "locked": True,
                    "duck": [{"start": 4.0, "end": 4.5, "volume_db": -24}]}
    locked = ops_module.extract_locked(old)

    # The regenerated plan dropped source 0–1 and re-split the footage.
    new = {**_plan(),
           "segments": [{"id": "a", "in": 1.0, "out": 3.0}, {"id": "b", "in": 5.0, "out": 8.0}],
           "visual_effects": [{"segment_id": "a", "type": "punch__neutral"}],
           "captions": [{"start": 0.2, "end": 1.0, "text": "New"}, {"start": 2.4, "end": 3.2, "text": "Clash"}],
           "music": {"file": "other.mp3", "volume_db": -10}}
    _restore_locked(new, locked)
    assert new["visual_effects"] == [{"segment_id": "a", "type": "steady__neutral", "locked": True}]
    # Locked caption re-anchored to source 5.5–7.0 -> new output 2.5–4.0; the clashing caption is replaced.
    assert [(c["text"], c["start"], c["end"]) for c in new["captions"]] == [("New", 0.2, 1.0), ("Later", 2.5, 4.0)]
    assert new["music"]["file"] == "m.mp3" and new["music"]["volume_db"] == -30
    assert new["music"]["duck"] == [{"start": 3.0, "end": 3.5, "volume_db": -24}]
    assert "generation_meta" not in new


def test_locked_caption_whose_footage_was_cut_is_reported():
    from app.jobs import _restore_locked
    old = _plan()
    old["captions"][0]["locked"] = True  # source 0.5–2.0
    new = {**_plan(), "segments": [{"id": "b", "in": 5.0, "out": 8.0}], "visual_effects": [],
           "captions": [{"start": 0.5, "end": 1.0, "text": "x"}]}
    _restore_locked(new, ops_module.extract_locked(old))
    assert new["generation_meta"]["dropped_locks"] == ["locked caption 'Hello'"]


def test_start_generate_passes_locked_items(store, monkeypatch):
    jobs, _versions, job = store
    plan = _plan()
    plan["captions"][0]["locked"] = True
    job.plan_data = plan
    job.raw_name = "test.mp4"
    captured = {}

    class FakeThread:
        def __init__(self, target, args, daemon):
            captured["args"] = args

        def start(self):
            pass
    monkeypatch.setattr(jobs, "CELERY_AVAILABLE", False)
    monkeypatch.setattr(jobs.threading, "Thread", FakeThread)
    jobs.start_generate(job)
    assert captured["args"][-1]["captions"][0]["caption"]["text"] == "Hello"

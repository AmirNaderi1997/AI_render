from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import jobs, premiere_bridge as bridge, premiere_desktop as desktop
from app.main import app
from engine.premiere import build_premiere
from engine.schema import validate_plan


@pytest.fixture(autouse=True)
def isolated_sessions():
    with bridge._guard:
        bridge._sessions.clear()
        bridge._pairing_codes.clear()
    yield
    with bridge._guard:
        bridge._sessions.clear()
        bridge._pairing_codes.clear()


@pytest.fixture
def linked_job(tmp_path, media_dir):
    directory = tmp_path / "abc123def456"
    directory.mkdir()
    (directory / "raw.mp4").write_bytes((media_dir / "raw.mp4").read_bytes())
    data = json.loads((Path(__file__).parents[1] / "samples/plans/cut.json").read_text())
    data["source"] = "raw.mp4"
    data["captions"] = [{"start": 0, "end": 1, "text": "سلام", "style": "normal"}]
    (directory / "plan.json").write_text(json.dumps(data))
    plan, errors = validate_plan(data, base_dir=directory, check_media=True)
    assert not errors
    build_premiere(plan, directory, base_dir=directory)
    (directory / "exports").mkdir()
    (directory / "exports/v1.mp4").write_bytes(b"current final render")
    job = jobs.Job(id=directory.name, dir=directory)
    job.render = jobs.RenderState(status="done", output="v1.mp4",
                                  plan_sha256=desktop.sha256(directory / "plan.json"))
    project_name = f"ai-render-{job.id}-clean.prproj"
    (directory / project_name).write_bytes(b"saved by Premiere")
    # Offline jobs keep plan metadata on the Job object, not in plan.json.
    job.plan_data = data
    desktop.link_project(job, project_name)
    return job


def complete_receipt(command, job_id):
    return {
        "protocol_version": bridge.BRIDGE_PROTOCOL_VERSION,
        "operation_id": command["operation_id"],
        "job_id": job_id,
        "artifact_identity": command["artifact_identity"],
        "premiere_version": "25.3.0",
        "project": {
            "requested_path": command["expected_project_path"],
            "active_path": command["expected_project_path"],
            "opened": True,
            "saved": True,
        },
        "sequence": {
            "name": command["sequence_name"],
            "sequence_id": "sequence-1",
            "imported": True,
            "timeline_open": True,
            "video_track_count": 1,
            "audio_track_count": 1,
        },
        "render_reference": {
            "media_path": command["files"]["render"],
            "imported": True,
            "placed_on_editable_timeline": False,
        },
        "captions": {
            "media_path": command["files"]["captions"],
            "imported": True,
            "track_created": True,
            "placed": True,
        },
        "duplicates": {"sequence": 0, "render_reference": 0, "captions": 0},
        "warnings": [],
        "errors": [],
    }


def nested_parent(payload, dotted):
    parts = dotted.split(".")
    parent = payload
    for part in parts[:-1]:
        parent = parent[part]
    return parent, parts[-1]


def test_session_is_job_scoped_and_pairing_code_is_one_time(linked_job):
    started = bridge.create_session(linked_job)
    assert started["state"] == "waiting_for_premiere"
    assert "token" not in started
    paired = bridge.pair(started["pairing_code"], {
        "kind": "CEP", "version": "0.1.0", "premiere_version": "25.3.0"})
    command = paired["command"]
    assert command["job_id"] == linked_job.id
    assert command["expected_project_path"].endswith("-clean.prproj")
    assert command["requested_actions"]["open_timeline"] is True
    assert set(command["files"]) == {"xml", "render", "captions"}
    with pytest.raises(HTTPException) as error:
        bridge.pair(started["pairing_code"], {})
    assert error.value.status_code == 401


def test_expired_or_unknown_pairing_code_cannot_return_command(linked_job):
    started = bridge.create_session(linked_job)
    with bridge._guard:
        bridge._sessions[started["operation_id"]].created_at -= bridge.SESSION_TTL_SECONDS + 1
    with pytest.raises(HTTPException) as expired:
        bridge.pair(started["pairing_code"], {"kind": "CEP"})
    assert expired.value.status_code == 401
    with pytest.raises(HTTPException) as unknown:
        bridge.pair("AAAA-BBBB-CCCC", {"kind": "CEP"})
    assert unknown.value.status_code == 401


def test_expired_terminal_sessions_are_purged():
    import time

    operation_id = "expired-terminal-test"
    pairing_code = "DEAD-BEEF-CAFE"
    session = bridge.BridgeSession(
        operation_id=operation_id, job_id="0123456789ab", pairing_code=pairing_code,
        token_hash="unused", command={}, created_at=time.time() - bridge.SESSION_TTL_SECONDS - 1,
        state="completed",
    )
    bridge._sessions[operation_id] = session
    bridge._pairing_codes[pairing_code] = operation_id
    bridge._purge_expired()
    assert operation_id not in bridge._sessions
    assert pairing_code not in bridge._pairing_codes


def test_receipt_requires_bearer_and_exact_artifact_identity(linked_job):
    started = bridge.create_session(linked_job)
    paired = bridge.pair(started["pairing_code"], {"kind": "CEP", "premiere_version": "25.3.0"})
    command = paired["command"]
    receipt = complete_receipt(command, linked_job.id)
    with pytest.raises(HTTPException) as missing:
        bridge.accept_receipt(linked_job, command["operation_id"], None, receipt)
    assert missing.value.status_code == 401
    wrong = dict(receipt)
    wrong["artifact_identity"] = dict(receipt["artifact_identity"], xml_sha256="0" * 64)
    with pytest.raises(HTTPException) as stale:
        bridge.accept_receipt(linked_job, command["operation_id"],
                              f"Bearer {paired['token']}", wrong)
    assert stale.value.status_code == 409
    accepted = bridge.accept_receipt(linked_job, command["operation_id"],
                                     f"Bearer {paired['token']}", receipt)
    assert accepted == {"accepted": True, "state": "completed"}
    stored = json.loads((linked_job.dir / bridge.RECEIPT_FILE).read_text())
    assert stored["project_sha256"] == desktop.sha256(
        linked_job.dir / f"ai-render-{linked_job.id}-clean.prproj")
    assert stored["bridge"]["kind"] == "CEP"


def test_music_observation_must_match_command_and_cannot_complete_when_missing(linked_job):
    started = bridge.create_session(linked_job)
    paired = bridge.pair(started["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    command["files"]["music"] = str(linked_job.dir / "music.mp3")
    bridge._sessions[started["operation_id"]].command["files"]["music"] = command["files"]["music"]
    receipt = complete_receipt(command, linked_job.id)
    receipt["music"] = {"media_path": "/wrong/music.mp3", "imported": True, "placed_on_timeline": True}
    with pytest.raises(HTTPException) as error:
        bridge.accept_receipt(linked_job, command["operation_id"], f"Bearer {paired['token']}", receipt)
    assert error.value.status_code == 409
    receipt["music"]["media_path"] = command["files"]["music"]
    receipt["music"]["placed_on_timeline"] = False
    accepted = bridge.accept_receipt(linked_job, command["operation_id"], f"Bearer {paired['token']}", receipt)
    assert accepted["state"] == "partial"


def test_current_receipt_makes_reconnect_non_destructive(linked_job):
    first = bridge.create_session(linked_job)
    paired = bridge.pair(first["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    receipt = complete_receipt(command, linked_job.id)
    bridge.accept_receipt(linked_job, command["operation_id"],
                          f"Bearer {paired['token']}", receipt)
    second = bridge.create_session(linked_job)
    paired_again = bridge.pair(second["pairing_code"], {"kind": "CEP"})
    actions = paired_again["command"]["requested_actions"]
    assert actions["open_timeline"] is True
    assert actions["import_sequence"] is False
    assert actions["import_render_reference"] is False
    assert actions["place_captions"] is False


def test_project_byte_change_invalidates_bridge_receipt(linked_job):
    first = bridge.create_session(linked_job)
    paired = bridge.pair(first["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    bridge.accept_receipt(linked_job, command["operation_id"], f"Bearer {paired['token']}",
                          complete_receipt(command, linked_job.id))
    project = linked_job.dir / f"ai-render-{linked_job.id}-clean.prproj"
    project.write_bytes(project.read_bytes() + b"changed")
    assert bridge.status(linked_job)["state"] == "stale"
    second = bridge.create_session(linked_job)
    paired_again = bridge.pair(second["pairing_code"], {"kind": "CEP"})
    assert paired_again["command"]["requested_actions"]["import_sequence"] is True


REQUIRED_OBSERVATIONS = [
    "project.opened",
    "project.saved",
    "sequence.imported",
    "sequence.timeline_open",
    "render_reference.imported",
    "captions.imported",
    "captions.track_created",
    "captions.placed",
]


@pytest.mark.parametrize("field", REQUIRED_OBSERVATIONS)
def test_each_false_required_observation_prevents_completed(linked_job, field):
    started = bridge.create_session(linked_job)
    paired = bridge.pair(started["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    receipt = complete_receipt(command, linked_job.id)
    parent, key = nested_parent(receipt, field)
    parent[key] = False
    accepted = bridge.accept_receipt(
        linked_job, command["operation_id"], f"Bearer {paired['token']}", receipt)
    assert accepted["state"] == "failed"


@pytest.mark.parametrize("field", REQUIRED_OBSERVATIONS)
@pytest.mark.parametrize("invalid", ["missing", "wrong_type"])
def test_each_required_observation_is_strictly_required(linked_job, field, invalid):
    started = bridge.create_session(linked_job)
    paired = bridge.pair(started["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    receipt = complete_receipt(command, linked_job.id)
    parent, key = nested_parent(receipt, field)
    if invalid == "missing":
        del parent[key]
    else:
        parent[key] = 1
    with pytest.raises(HTTPException) as error:
        bridge.accept_receipt(
            linked_job, command["operation_id"], f"Bearer {paired['token']}", receipt)
    assert error.value.status_code == 422


def test_warning_can_classify_unobservable_reconnect_as_partial(linked_job):
    started = bridge.create_session(linked_job)
    paired = bridge.pair(started["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    receipt = complete_receipt(command, linked_job.id)
    receipt["captions"]["track_created"] = False
    receipt["captions"]["placed"] = False
    receipt["warnings"] = ["CEP cannot inspect existing caption tracks"]
    accepted = bridge.accept_receipt(
        linked_job, command["operation_id"], f"Bearer {paired['token']}", receipt)
    assert accepted["state"] == "partial"
    # After an unobservable (partial) first attempt, the second session MUST retry
    # placement because we cannot confirm captions were ever successfully placed.
    second = bridge.create_session(linked_job)
    paired_again = bridge.pair(second["pairing_code"], {"kind": "CEP"})
    assert paired_again["command"]["requested_actions"]["place_captions"] is True


def _unobservable_caption_receipt(job, project_xml):
    import gzip
    (job.dir / f"ai-render-{job.id}-clean.prproj").write_bytes(gzip.compress(project_xml.encode()))
    started = bridge.create_session(job)
    paired = bridge.pair(started["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    receipt = complete_receipt(command, job.id)
    receipt["captions"]["track_created"] = False
    receipt["captions"]["placed"] = False
    receipt["warnings"] = ["CEP cannot inspect existing caption tracks; caption persistence was not verified"]
    return bridge.accept_receipt(job, command["operation_id"], f"Bearer {paired['token']}", receipt)


def test_saved_project_caption_track_matching_srt_completes_reconnect(linked_job):
    xml = '<CaptionDataClipTrack ObjectUID="a">\n</CaptionDataClipTrack><CaptionDataClipTrackItem ObjectID="1">'
    assert _unobservable_caption_receipt(linked_job, xml)["state"] == "completed"
    assert bridge.status(linked_job)["receipt"]["verification"]["caption_persistence"]["verified"] is True


def test_saved_project_caption_mismatch_stays_partial(linked_job):
    xml = '<CaptionDataClipTrack ObjectUID="a"></CaptionDataClipTrack>'
    assert _unobservable_caption_receipt(linked_job, xml)["state"] == "partial"


def test_render_reference_on_timeline_is_always_failed(linked_job):
    started = bridge.create_session(linked_job)
    paired = bridge.pair(started["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    receipt = complete_receipt(command, linked_job.id)
    receipt["render_reference"]["placed_on_editable_timeline"] = True
    accepted = bridge.accept_receipt(
        linked_job, command["operation_id"], f"Bearer {paired['token']}", receipt)
    assert accepted["state"] == "failed"


@pytest.mark.parametrize("field,value", [
    ("protocol_version", 2),
    ("project.active_path", "/tmp/wrong.prproj"),
    ("sequence.name", "wrong sequence"),
    ("render_reference.media_path", "/tmp/wrong.mp4"),
    ("captions.media_path", "/tmp/wrong.srt"),
])
def test_unexpected_protocol_and_native_identity_are_rejected(linked_job, field, value):
    started = bridge.create_session(linked_job)
    paired = bridge.pair(started["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    receipt = complete_receipt(command, linked_job.id)
    parent, key = nested_parent(receipt, field)
    parent[key] = value
    with pytest.raises(HTTPException) as error:
        bridge.accept_receipt(
            linked_job, command["operation_id"], f"Bearer {paired['token']}", receipt)
    assert error.value.status_code in {409, 422}


def test_duplicate_observation_cannot_be_completed(linked_job):
    started = bridge.create_session(linked_job)
    paired = bridge.pair(started["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    receipt = complete_receipt(command, linked_job.id)
    receipt["duplicates"]["captions"] = 1
    accepted = bridge.accept_receipt(
        linked_job, command["operation_id"], f"Bearer {paired['token']}", receipt)
    assert accepted["state"] == "partial"


def test_final_receipt_and_token_cannot_be_replayed(linked_job):
    started = bridge.create_session(linked_job)
    paired = bridge.pair(started["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    receipt = complete_receipt(command, linked_job.id)
    authorization = f"Bearer {paired['token']}"
    bridge.accept_receipt(linked_job, command["operation_id"], authorization, receipt)
    with pytest.raises(HTTPException) as replayed:
        bridge.accept_receipt(linked_job, command["operation_id"], authorization, receipt)
    assert replayed.value.status_code == 409


def test_tampered_persisted_receipt_is_not_treated_as_current(linked_job):
    started = bridge.create_session(linked_job)
    paired = bridge.pair(started["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    bridge.accept_receipt(
        linked_job, command["operation_id"], f"Bearer {paired['token']}",
        complete_receipt(command, linked_job.id),
    )
    path = linked_job.dir / bridge.RECEIPT_FILE
    stored = json.loads(path.read_text())
    stored["captions"]["placed"] = False
    path.write_text(json.dumps(stored))
    assert bridge.status(linked_job)["state"] == "not_connected"


@pytest.mark.parametrize("field,value", [
    ("operation_id", "different-operation"),
    ("job_id", "000000000000"),
])
def test_unexpected_operation_or_job_identity_is_rejected(linked_job, field, value):
    started = bridge.create_session(linked_job)
    paired = bridge.pair(started["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    receipt = complete_receipt(command, linked_job.id)
    receipt[field] = value
    with pytest.raises(HTTPException) as error:
        bridge.accept_receipt(
            linked_job, command["operation_id"], f"Bearer {paired['token']}", receipt)
    assert error.value.status_code == 422


def test_cep_panel_contains_required_premiere_25_3_operations():
    root = Path(__file__).parents[1] / "premiere-bridge"
    manifest = (root / "CSXS/manifest.xml").read_text()
    jsx = (root / "jsx/bridge.jsx").read_text()
    assert 'Version="[25.0,25.6)"' in manifest
    for operation in ("app.project.importFiles", "app.project.openSequence",
                      "createCaptionTrack", "app.project.save"):
        assert operation in jsx


def test_caption_placement_error_classifies_as_failed(linked_job):
    """Item 25: track_created=False + explicit error → failed (not partial)."""
    started = bridge.create_session(linked_job)
    paired = bridge.pair(started["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    receipt = complete_receipt(command, linked_job.id)
    receipt["captions"]["track_created"] = False
    receipt["captions"]["placed"] = False
    receipt["errors"] = ["Premiere could not create the caption track."]
    accepted = bridge.accept_receipt(
        linked_job, command["operation_id"], f"Bearer {paired['token']}", receipt)
    assert accepted["state"] == "failed"


def test_stale_link_blocks_bridge_session(linked_job):
    """Item 26: bridge session raises 409 when project link is outdated."""
    (linked_job.dir / "exports/v1.mp4").write_bytes(b"updated render bytes")
    linked_job.render.plan_sha256 = desktop.sha256(linked_job.dir / "plan.json")
    from fastapi import HTTPException as _HTTPException
    with pytest.raises(_HTTPException) as error:
        bridge.create_session(linked_job)
    assert error.value.status_code == 409


def test_place_captions_not_suppressed_after_unobservable_warning(linked_job):
    """Item 27: unobservable warning alone must NOT suppress caption placement on reconnect."""
    started = bridge.create_session(linked_job)
    paired = bridge.pair(started["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    receipt = complete_receipt(command, linked_job.id)
    receipt["captions"]["track_created"] = False
    receipt["captions"]["placed"] = False
    receipt["warnings"] = ["CEP cannot inspect existing caption tracks; placement unverified"]
    bridge.accept_receipt(linked_job, command["operation_id"], f"Bearer {paired['token']}", receipt)
    second = bridge.create_session(linked_job)
    paired_again = bridge.pair(second["pairing_code"], {"kind": "CEP"})
    # Must retry because previous placement was never confirmed successful.
    assert paired_again["command"]["requested_actions"]["place_captions"] is True


def test_verify_saved_captions_with_gzipped_prproj(linked_job):
    """Item 28: verify_saved_captions counts caption tracks from gzipped prproj XML."""
    import gzip
    srt_path = linked_job.dir / "premiere_captions.srt"
    cue_count = len([b for b in __import__("re").split(
        r"\r?\n\s*\r?\n", srt_path.read_text(encoding="utf-8").strip()) if b.strip()])
    assert cue_count > 0
    track_items = "\n".join(
        f'<CaptionDataClipTrackItem ObjectID="{i}">' for i in range(cue_count))
    xml = (f'<CaptionDataClipTrack ObjectUID="a">\n{track_items}\n</CaptionDataClipTrack>')
    project = linked_job.dir / f"ai-render-{linked_job.id}-clean.prproj"
    project.write_bytes(gzip.compress(xml.encode()))
    result = bridge.verify_saved_captions(project, srt_path)
    assert result["verified"] is True
    assert result["tracks"] == 1
    assert result["items"] == cue_count
    assert result["cues"] == cue_count
    wrong_xml = '<CaptionDataClipTrack ObjectUID="a"></CaptionDataClipTrack>'
    project.write_bytes(gzip.compress(wrong_xml.encode()))
    mismatch = bridge.verify_saved_captions(project, srt_path)
    assert mismatch["verified"] is False


def test_force_refresh_requires_saved_updated_project_before_bridge_session(linked_job):
    (linked_job.dir / "exports/v1.mp4").write_bytes(b"updated render bytes")
    linked_job.render.plan_sha256 = desktop.sha256(linked_job.dir / "plan.json")
    assert desktop.status(linked_job)["project_state"] == "linked_outdated"
    with pytest.raises(HTTPException):
        bridge.create_session(linked_job)
    with pytest.raises(HTTPException) as error:
        bridge.create_session(linked_job, force_refresh=True)
    assert error.value.status_code == 409
    assert desktop.status(linked_job)["project_state"] == "linked_outdated"
    with pytest.raises(HTTPException):
        desktop.link_project(linked_job, f"ai-render-{linked_job.id}-clean.prproj")
    (linked_job.dir / f"ai-render-{linked_job.id}-clean.prproj").write_bytes(b"saved updated project")
    desktop.link_project(linked_job, f"ai-render-{linked_job.id}-clean.prproj")
    started = bridge.create_session(linked_job, force_refresh=True)
    assert started["state"] == "waiting_for_premiere"
    assert desktop.status(linked_job)["project_state"] == "linked_current"


def test_caption_api_available_is_recorded_in_receipt(linked_job):
    started = bridge.create_session(linked_job)
    paired = bridge.pair(started["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    receipt = complete_receipt(command, linked_job.id)
    receipt["caption_api_available"] = True
    accepted = bridge.accept_receipt(
        linked_job, command["operation_id"], f"Bearer {paired['token']}", receipt)
    assert accepted["state"] == "completed"
    stored = json.loads((linked_job.dir / bridge.RECEIPT_FILE).read_text())
    assert stored["caption_api_available"] is True


def test_caption_api_unavailable_is_recorded_in_receipt(linked_job):
    started = bridge.create_session(linked_job)
    paired = bridge.pair(started["pairing_code"], {"kind": "CEP"})
    command = paired["command"]
    receipt = complete_receipt(command, linked_job.id)
    receipt["caption_api_available"] = False
    receipt["captions"]["track_created"] = False
    receipt["captions"]["placed"] = False
    receipt["warnings"] = [
        "Sequence.createCaptionTrack is not available in this Premiere version. "
        "Import the SRT as a caption track manually."
    ]
    accepted = bridge.accept_receipt(
        linked_job, command["operation_id"], f"Bearer {paired['token']}", receipt)
    assert accepted["state"] == "partial"
    stored = json.loads((linked_job.dir / bridge.RECEIPT_FILE).read_text())
    assert stored["caption_api_available"] is False


def test_end_to_end_bridge_with_fake_extendscript(linked_job, monkeypatch):
    """Item 31: session → pair → execute (fake) → receipt → status, all via HTTP."""
    client = TestClient(app)
    origin = "http://localhost:5173"
    from app import auth
    monkeypatch.setattr(auth, "get_current_user_from_token", lambda _token: auth.User(
        id="test-user", email="bridge-test@example.com", name="Bridge Test",
        password_hash="", created_at=0,
    ))
    app_headers = {"Authorization": "Bearer web-app-test-token"}

    # Register the test job in the in-memory store so API routes can find it
    with jobs._lock:
        jobs._jobs[linked_job.id] = linked_job
    # JOBS_ROOT must point at the parent of the job directory for job_for_id's
    # safety check (job.dir.resolve().parent == JOBS_ROOT.resolve())
    monkeypatch.setattr(jobs, "JOBS_ROOT", linked_job.dir.parent)
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    monkeypatch.setattr(desktop, "capability", lambda: {
        "available": True, "version": "25.3.0",
        "bundle_id": "com.adobe.PremierePro.25",
        "app_path": "/Applications/Premiere.app",
        "local_launch_supported": True,
    })
    monkeypatch.setattr(desktop, "require_local", lambda request: None)
    monkeypatch.setattr(bridge, "require_loopback_peer", lambda request: None)

    try:
        # Step 1: check status before connection
        r = client.get(f"/jobs/{linked_job.id}/premiere/status",
                       headers={"Origin": origin, **app_headers})
        assert r.status_code == 200
        status_before = r.json()
        assert status_before["bridge"]["state"] == "not_connected"
        for suffix in ("/premiere", "/premiere.xml", "/premiere/captions", "/premiere/report"):
            served = client.get(f"/jobs/{linked_job.id}{suffix}", headers=app_headers)
            assert served.status_code == 200, suffix
        assert client.get("/jobs/not-a-job/premiere.xml", headers=app_headers).status_code == 404

        # Step 2: create bridge session (from web frontend)
        r = client.post(f"/jobs/{linked_job.id}/premiere/bridge/session",
                        headers={"Origin": origin, "Content-Type": "application/json", **app_headers},
                        json={})
        assert r.status_code == 200
        session = r.json()
        pairing_code = session["pairing_code"]
        assert session["state"] == "waiting_for_premiere"

        # Step 3: pair (from CEP panel at 127.0.0.1)
        r = client.post("/integrations/premiere/bridge/pair",
                        headers={"Content-Type": "application/json"},
                        json={"pairing_code": pairing_code,
                              "bridge": {"kind": "CEP", "version": "0.1.1",
                                         "premiere_version": "25.3.0"}})
        assert r.status_code == 200
        paired = r.json()
        token = paired["token"]
        command = paired["command"]

        # Step 4: fake ExtendScript execution — simulate what bridge.jsx does
        fake_receipt = complete_receipt(command, linked_job.id)
        fake_receipt["caption_api_available"] = True

        # Step 5: submit receipt (from CEP panel)
        r = client.post(f"/jobs/{linked_job.id}/premiere/bridge/receipt",
                        headers={"Content-Type": "application/json",
                                 "Authorization": f"Bearer {token}"},
                        json=fake_receipt)
        assert r.status_code == 200
        result = r.json()
        assert result["accepted"] is True
        assert result["state"] == "completed"

        # Step 6: verify status reflects completed bridge
        r = client.get(f"/jobs/{linked_job.id}/premiere/status",
                       headers={"Origin": origin, **app_headers})
        assert r.status_code == 200
        status_after = r.json()
        assert status_after["bridge"]["state"] == "completed"
        assert status_after["bridge"]["receipt"]["caption_api_available"] is True
    finally:
        with jobs._lock:
            jobs._jobs.pop(linked_job.id, None)


def test_cors_allows_only_frontend_and_cep_panel_origins():
    client = TestClient(app)
    headers = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,authorization",
    }
    for origin in ("null", "http://localhost:5173", "http://127.0.0.1:5173"):
        response = client.options(
            "/integrations/premiere/bridge/pair", headers={**headers, "Origin": origin})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
    rejected = client.options(
        "/integrations/premiere/bridge/pair",
        headers={**headers, "Origin": "http://evil.local:9999"},
    )
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers

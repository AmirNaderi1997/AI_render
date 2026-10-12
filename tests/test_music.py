"""Tests for music mixing and Premiere music export."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from engine.schema import validate_plan, EditPlan


BASE_PLAN = {
    "canvas": {"width": 1080, "height": 1920, "fps": 30},
    "source": "raw.mp4",
    "segments": [
        {"id": "s1", "in": 0.0, "out": 4.0},
        {"id": "s2", "in": 4.0, "out": 8.0},
    ],
    "captions": [],
    "broll": [],
    "sfx": [],
    "export": {"file": "out.mp4"},
}


def _v(plan: dict):
    return validate_plan(plan, check_media=False)


# ── Schema tests ─────────────────────────────────────────────────────────────


def test_plan_without_music_is_valid():
    plan, errs = _v({**BASE_PLAN})
    assert errs == []
    assert plan.music is None


def test_plan_with_music_is_valid():
    plan, errs = _v({**BASE_PLAN, "music": {"file": "music/track.mp3", "volume_db": -14}})
    assert errs == []
    assert plan.music is not None
    assert plan.music.file == "music/track.mp3"
    assert plan.music.volume_db == -14
    assert plan.music.duck == []


def test_music_with_duck_ranges():
    plan, errs = _v({
        **BASE_PLAN,
        "music": {
            "file": "music/track.mp3",
            "volume_db": -14,
            "duck": [
                {"start": 0.0, "end": 4.0, "volume_db": -18},
                {"start": 4.0, "end": 8.0, "volume_db": -18},
            ],
        },
    })
    assert errs == []
    assert len(plan.music.duck) == 2
    assert plan.music.duck[0].volume_db == -18


def test_music_duck_invalid_range():
    plan, errs = _v({
        **BASE_PLAN,
        "music": {
            "file": "music/track.mp3",
            "duck": [{"start": 5.0, "end": 3.0, "volume_db": -18}],
        },
    })
    assert plan is None
    assert any("end must be > start" in e for e in errs)


def test_music_default_volume():
    plan, errs = _v({**BASE_PLAN, "music": {"file": "music/track.mp3"}})
    assert errs == []
    assert plan.music.volume_db == -14


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), 1000, -1000])
def test_music_volume_rejects_nonfinite_and_extreme_levels(value):
    _, errs = _v({**BASE_PLAN, "music": {"file": "music/track.mp3", "volume_db": value}})
    assert errs


def test_sfx_at_exact_output_end_is_rejected():
    _, errs = _v({**BASE_PLAN, "sfx": [{"at": 8.0, "file": "sfx/hit.wav"}]})
    assert any("at or beyond output duration" in error for error in errs)


def test_sfx_cues_keep_requested_times_and_have_independent_tracks(tmp_path, monkeypatch):
    from engine.build_mlt import build

    monkeypatch.setattr("engine.build_mlt.probe_duration", lambda _path: 1.0)
    data = {**BASE_PLAN, "sfx": [
        {"at": 6.0, "file": "late.wav"},
        {"at": 1.0, "file": "early.wav"},
    ]}
    plan, errors = _v(data)
    assert not errors
    mlt, _ = build(plan, tmp_path / "build", base_dir=tmp_path)
    from xml.etree import ElementTree as ET
    root = ET.parse(mlt).getroot()
    for playlist_id, expected_start in (("a2_0", 180), ("a2_1", 30)):
        playlist = root.find(f"playlist[@id='{playlist_id}']")
        assert int(playlist.find("blank").attrib["length"]) == expected_start
        assert playlist.find("entry") is not None
        assert int(playlist.find("entry").attrib["out"]) == 29
    tractor = root.find("tractor[@id='main']")
    assert tractor.find("track[@producer='a2_0']") is not None
    assert tractor.find("track[@producer='a2_1']") is not None


# ── Auto-duck generation ────────────────────────────────────────────────────


def test_auto_duck_covers_speech_segments():
    """Auto-duck should create one duck range per segment."""
    plan_data = {
        **BASE_PLAN,
        "music": {"file": "music/track.mp3", "volume_db": -14},
    }
    plan, errs = _v(plan_data)
    assert errs == []
    # Simulate auto-duck: one range per segment
    ducks = [{"start": seg.in_, "end": seg.out, "volume_db": -18} for seg in plan.segments]
    plan_data["music"]["duck"] = ducks
    plan2, errs2 = _v(plan_data)
    assert errs2 == []
    assert len(plan2.music.duck) == 2
    assert plan2.music.duck[0].start == 0.0
    assert plan2.music.duck[0].end == 4.0
    assert plan2.music.duck[1].start == 4.0
    assert plan2.music.duck[1].end == 8.0


# ── Premiere XML music track ────────────────────────────────────────────────


def test_premiere_xml_has_music_track_when_music_present():
    """FCP7 XML should include a music audio track when plan has music."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Create dummy source and music files
        (tmp_path / "raw.mp4").write_bytes(b"\x00" * 100)
        music_dir = tmp_path / "music"
        music_dir.mkdir()
        (music_dir / "track.mp3").write_bytes(b"\x00" * 100)

        plan_data = {
            **BASE_PLAN,
            "music": {"file": "music/track.mp3", "volume_db": -14, "duck": [
                {"start": 0.0, "end": 4.0, "volume_db": -18},
            ]},
        }
        plan_data["source"] = "raw.mp4"
        (tmp_path / "plan.json").write_text(json.dumps(plan_data))

        plan, errs = validate_plan(plan_data, base_dir=tmp_path, check_media=False)
        assert errs == []

        from engine.premiere import build_premiere
        bundle = build_premiere(plan, tmp_path, base_dir=tmp_path)
        assert bundle.exists()

        xml_path = tmp_path / "project_premiere.xml"
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Find audio tracks
        audio_elem = root.find(".//media/audio")
        assert audio_elem is not None
        tracks = audio_elem.findall("track")
        # Should have at least 2 tracks: main audio + music
        assert len(tracks) >= 2

        music_track = tracks[-1]  # Music is the last track
        clip = music_track.find("clipitem")
        assert clip is not None
        assert "Music" in clip.find("name").text

        # Check volume filter
        filt = clip.find("filter")
        assert filt is not None
        effect = filt.find("effect")
        assert effect.find("name").text == "Audio Levels"

        # Check keyframes exist for duck range
        param = effect.find("parameter")
        keyframes = param.findall("keyframe")
        assert len(keyframes) >= 2  # At least ramp down + ramp up


def test_premiere_xml_no_music_track_when_no_music():
    """FCP7 XML should NOT include a music track when plan has no music."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "raw.mp4").write_bytes(b"\x00" * 100)

        plan_data = {**BASE_PLAN, "source": "raw.mp4"}
        (tmp_path / "plan.json").write_text(json.dumps(plan_data))

        plan, errs = validate_plan(plan_data, base_dir=tmp_path, check_media=False)
        assert errs == []

        from engine.premiere import build_premiere
        build_premiere(plan, tmp_path, base_dir=tmp_path)

        xml_path = tmp_path / "project_premiere.xml"
        tree = ET.parse(xml_path)
        root = tree.getroot()

        audio_elem = root.find(".//media/audio")
        tracks = audio_elem.findall("track")
        # Only the main audio track
        assert len(tracks) == 1


def test_premiere_bundle_includes_music_file():
    """ZIP bundle should include the music file when present."""
    import zipfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "raw.mp4").write_bytes(b"\x00" * 100)
        music_dir = tmp_path / "music"
        music_dir.mkdir()
        (music_dir / "track.mp3").write_bytes(b"\xff\xfb\x90\x00" * 25)  # fake mp3

        plan_data = {
            **BASE_PLAN,
            "source": "raw.mp4",
            "music": {"file": "music/track.mp3", "volume_db": -14},
        }
        (tmp_path / "plan.json").write_text(json.dumps(plan_data))

        plan, errs = validate_plan(plan_data, base_dir=tmp_path, check_media=False)
        assert errs == []

        from engine.premiere import build_premiere
        bundle = build_premiere(plan, tmp_path, base_dir=tmp_path)

        with zipfile.ZipFile(bundle) as zf:
            names = zf.namelist()
            assert any(n.startswith("media/") and n.endswith("-track.mp3") for n in names)


# ── Bridge receipt music field ───────────────────────────────────────────────


def test_bridge_receipt_accepts_music():
    from app.premiere_bridge import PremiereBridgeReceipt, MusicObservation

    base_receipt = {
        "protocol_version": 1,
        "operation_id": "test-op-id-12345678",
        "job_id": "abcdef012345",
        "artifact_identity": {
            "plan_sha256": "a" * 64,
            "xml_sha256": "b" * 64,
            "srt_sha256": "c" * 64,
            "render_sha256": "d" * 64,
            "project_path": "/tmp/test.prproj",
        },
        "premiere_version": "25.3.0",
        "project": {"requested_path": "/tmp/test.prproj", "active_path": "/tmp/test.prproj", "opened": True, "saved": True},
        "sequence": {"name": "AI Render editable sequence", "sequence_id": "seq-1", "imported": True, "timeline_open": True, "video_track_count": 1, "audio_track_count": 2},
        "render_reference": {"media_path": "/tmp/render.mp4", "imported": True, "placed_on_editable_timeline": False},
        "captions": {"media_path": "/tmp/captions.srt", "imported": True, "track_created": True, "placed": True},
        "music": {"media_path": "/tmp/music/track.mp3", "imported": True, "placed_on_timeline": False},
        "duplicates": {"sequence": 0, "render_reference": 0, "captions": 0},
        "warnings": [],
        "errors": [],
    }
    receipt = PremiereBridgeReceipt.model_validate(base_receipt)
    assert receipt.music is not None
    assert receipt.music.imported is True
    assert receipt.music.placed_on_timeline is False


def test_bridge_receipt_works_without_music():
    from app.premiere_bridge import PremiereBridgeReceipt

    base_receipt = {
        "protocol_version": 1,
        "operation_id": "test-op-id-12345678",
        "job_id": "abcdef012345",
        "artifact_identity": {
            "plan_sha256": "a" * 64,
            "xml_sha256": "b" * 64,
            "srt_sha256": "c" * 64,
            "render_sha256": "d" * 64,
            "project_path": "/tmp/test.prproj",
        },
        "premiere_version": "25.3.0",
        "project": {"requested_path": "/tmp/test.prproj", "active_path": "/tmp/test.prproj", "opened": True, "saved": True},
        "sequence": {"name": "AI Render editable sequence", "sequence_id": "seq-1", "imported": True, "timeline_open": True, "video_track_count": 1, "audio_track_count": 1},
        "render_reference": {"media_path": "/tmp/render.mp4", "imported": True, "placed_on_editable_timeline": False},
        "captions": {"media_path": "/tmp/captions.srt", "imported": True, "track_created": True, "placed": True},
        "duplicates": {"sequence": 0, "render_reference": 0, "captions": 0},
        "warnings": [],
        "errors": [],
    }
    receipt = PremiereBridgeReceipt.model_validate(base_receipt)
    assert receipt.music is None


# ── Attached background music: FFmpeg mix, API and Premiere export ───────────


def _ffmpeg(*args: str) -> None:
    import shutil
    import subprocess
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def _synthetic_media(root: Path, video_seconds: int = 4) -> dict[str, Path]:
    """A video with audio, a silent video, and a short (looping) music track."""
    media = {"voiced": root / "voiced.mp4", "silent": root / "silent.mp4", "music": root / "music.wav"}
    _ffmpeg("-f", "lavfi", "-i", f"color=c=blue:s=160x120:r=30:d={video_seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={video_seconds}",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(media["voiced"]))
    _ffmpeg("-f", "lavfi", "-i", f"color=c=blue:s=160x120:r=30:d={video_seconds}",
            "-c:v", "libx264", str(media["silent"]))
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=880:duration=1", str(media["music"]))
    return media


@pytest.mark.parametrize("args", [
    (-0.1, 2, 3), (1.1, 2, 3), (0.3, -1, 3), (0.3, 2, -1), (0.3, 2, 61),
    (float("nan"), 2, 3), (0.3, float("inf"), 3), (True, 2, 3),
])
def test_mix_params_are_validated(args):
    from brain.music import validate_params
    with pytest.raises(ValueError):
        validate_params(*args)


def test_fades_never_exceed_video_and_zero_fades_are_omitted():
    from brain.music import music_filter
    chain = music_filter(duration=4.0, volume=0.5, fade_in=4.0, fade_out=4.0)
    assert "afade=t=in:st=0:d=2.000" in chain and "afade=t=out:st=2.000:d=2.000" in chain
    assert "afade" not in music_filter(4.0, 0.5, 0.0, 0.0)


@pytest.mark.parametrize("kind", ["voiced", "silent"])
def test_mix_keeps_video_duration_and_always_has_audio(tmp_path, kind):
    from brain.music import mix_music
    from engine.probe import has_audio, probe_duration
    media = _synthetic_media(tmp_path)
    progress: list[int] = []
    out = mix_music(media[kind], media["music"], tmp_path / "out.mp4", volume_level=0.5, on_progress=progress.append)
    assert has_audio(out)
    assert abs(probe_duration(out) - probe_duration(media[kind])) < 0.1  # 1s track is looped/trimmed to the video
    assert progress and max(progress) <= 99
    assert not list(tmp_path.glob(".*out.mp4"))  # no partial files left behind


def test_failed_mix_leaves_no_output(tmp_path):
    from brain.music import MusicMixError, mix_music
    media = _synthetic_media(tmp_path)
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not audio")
    with pytest.raises(MusicMixError):
        mix_music(media["voiced"], bad, tmp_path / "out.mp4")
    assert not (tmp_path / "out.mp4").exists()


def test_music_url_must_be_public_http(tmp_path):
    from brain.music import MusicMixError, fetch_music_url
    for url in ("file:///etc/passwd.mp3", "http://127.0.0.1/a.mp3", "https://example.com/a.exe"):
        with pytest.raises(MusicMixError):
            fetch_music_url(url, tmp_path)


@pytest.fixture
def music_api(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import jobs
    from app.routers import music
    job = jobs.Job(id="job1", dir=tmp_path)
    (tmp_path / "exports").mkdir()
    monkeypatch.setattr(jobs, "get", lambda _id: job)
    monkeypatch.setattr(jobs, "_write_status", lambda _job: None)
    monkeypatch.setattr(jobs, "CELERY_AVAILABLE", False)
    app = FastAPI()
    app.include_router(music.router)
    return TestClient(app), job, tmp_path


def _finish_render(job, media: dict[str, Path]) -> None:
    import shutil
    shutil.copy(media["voiced"], job.dir / "exports" / "v1.mp4")
    job.render.status, job.render.output = "done", "v1.mp4"


def _wait_for_mix(client, timeout: float = 30.0) -> dict:
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get("/jobs/job1/music/status").json()
        if status["status"] in {"done", "error"}:
            return status
        time.sleep(0.1)
    raise AssertionError("mix did not finish")


def test_music_api_attach_mix_preview_remove(music_api):
    client, job, root = music_api
    media = _synthetic_media(root)
    _finish_render(job, media)
    assert client.get("/jobs/job1/music/status").json()["attached"] is False
    assert client.post("/jobs/job1/music/mix", json={}).status_code == 404  # nothing attached yet

    wav = media["music"].read_bytes()
    assert client.post("/jobs/job1/music", files={"file": ("track.txt", wav, "text/plain")}).status_code == 422
    assert client.post("/jobs/job1/music", files={"file": ("track.wav", b"junk", "audio/wav")}).status_code == 422
    attached = client.post("/jobs/job1/music", files={"file": ("My Track.wav", wav, "audio/wav")})
    assert attached.status_code == 200
    body = attached.json()
    assert body["attached"] and body["name"] == "My Track.wav" and 0.9 < body["duration_s"] < 1.1

    assert client.post("/jobs/job1/music/mix", json={"volume_level": 1.5}).status_code == 422
    accepted = client.post("/jobs/job1/music/mix", json={"volume_level": 0.5, "fade_in_seconds": 1, "fade_out_seconds": 1})
    assert accepted.status_code == 202
    status = _wait_for_mix(client)
    assert status["status"] == "done" and status["progress"] == 100
    assert status["output"] == "v1_music.mp4" and (root / "exports" / "v1_music.mp4").is_file()
    assert job.render.output == "v1.mp4"  # the render itself is never replaced
    assert status["volume_level"] == 0.5

    preview = client.get("/jobs/job1/music/preview?volume_level=0.2")
    assert preview.status_code == 200 and preview.headers["content-type"] == "audio/mp4" and preview.content
    assert client.get(f"/jobs/job1/music/preview?filename={Path(job.music.file).name}").status_code == 200

    assert client.delete("/jobs/job1/music").json() == {"ok": True}
    assert not (root / job.music.file if job.music.file else root / "gone").exists()
    assert not (root / "exports" / "v1_music.mp4").exists()
    assert client.get("/jobs/job1/music/status").json()["attached"] is False


def test_music_api_rejects_edits_while_busy_and_mix_without_render(music_api):
    client, job, root = music_api
    wav = _synthetic_media(root)["music"].read_bytes()
    assert client.post("/jobs/job1/music", files={"file": ("a.wav", wav, "audio/wav")}).status_code == 200
    assert client.post("/jobs/job1/music/mix", json={}).status_code == 409  # not rendered yet
    job.render.status = "running"
    assert client.post("/jobs/job1/music", files={"file": ("b.wav", wav, "audio/wav")}).status_code == 409
    assert client.delete("/jobs/job1/music").status_code == 409
    assert len(list((root / "music").iterdir())) == 1  # the rejected upload is not kept
    job.render.status, job.music.status = "idle", "running"
    from app import jobs
    with pytest.raises(ValueError):
        jobs.start_render(job)


def test_music_api_enforces_job_ownership(music_api):
    client, job, _root = music_api
    job.user_id = "42"  # request carries no authenticated user
    calls = [
        client.post("/jobs/job1/music", files={"file": ("a.wav", b"x", "audio/wav")}),
        client.post("/jobs/job1/music/mix", json={}),
        client.get("/jobs/job1/music/status"),
        client.get("/jobs/job1/music/preview"),
        client.delete("/jobs/job1/music"),
    ]
    assert [c.status_code for c in calls] == [403] * 5


def test_render_auto_mixes_attached_music_and_failure_keeps_render(tmp_path, monkeypatch):
    import shutil
    from types import SimpleNamespace
    from app import jobs
    media = _synthetic_media(tmp_path)
    job = jobs.Job(id="job1", dir=tmp_path, plan_data={"x": 1})
    (tmp_path / "exports").mkdir()
    (tmp_path / "music").mkdir()
    shutil.copy(media["music"], tmp_path / "music" / "attached_1.wav")
    job.music.file = "music/attached_1.wav"
    monkeypatch.setattr(jobs, "get", lambda _id: job)
    monkeypatch.setattr(jobs, "_write_status", lambda _job: None)
    monkeypatch.setattr(jobs, "CELERY_AVAILABLE", False)
    monkeypatch.setattr(jobs, "load_plan", lambda current: current.plan_data)
    monkeypatch.setattr(jobs, "validate_plan", lambda *a, **k: (SimpleNamespace(
        style="s", poster=False, export=SimpleNamespace(crf=None),
        canvas=SimpleNamespace(width=160, height=120, fps=30), output_duration=4.0), []))
    monkeypatch.setattr(jobs, "build", lambda *a, **k: (tmp_path / "p.mlt", None))
    seen = {}
    monkeypatch.setattr(jobs, "build_premiere", lambda *a, **k: seen.update(k))
    monkeypatch.setattr(jobs, "run_render", lambda mlt, out, **k: shutil.copy(media["voiced"], out))

    jobs._run_job(job, preview=False)
    assert job.render.status == "done" and job.render.output == "v1.mp4", job.render.message
    assert seen["attached_music"].file == tmp_path / "music" / "attached_1.wav"
    assert job.music.status == "done" and job.music.output == "v1_music.mp4"
    assert (tmp_path / "exports" / "v1_music.mp4").is_file()

    (tmp_path / "music" / "attached_1.wav").write_bytes(b"corrupt")  # next render: mix fails, render survives
    job.render = jobs.RenderState()
    jobs._run_job(job, preview=False)
    assert job.render.status == "done" and job.render.output == "v2.mp4"
    assert job.music.status == "error" and job.music.output is None


def _premiere_plan(tmp_path: Path, seconds: int = 4):
    (tmp_path / "raw.mp4").write_bytes(b"\x00" * 100)
    data = {**BASE_PLAN, "segments": [{"id": "s1", "in": 0.0, "out": float(seconds)}]}
    plan, errs = validate_plan(data, base_dir=tmp_path, check_media=False)
    assert errs == []
    return plan


def test_premiere_xml_includes_attached_music_track(tmp_path):
    import zipfile
    from engine.premiere import AttachedMusic, build_premiere
    plan = _premiere_plan(tmp_path, seconds=4)  # 120 frames
    track = tmp_path / "bg.wav"
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=880:duration=1.5", str(track))  # 45 frames: repeated 3x

    bundle = build_premiere(plan, tmp_path, base_dir=tmp_path,
                            attached_music=AttachedMusic(track, volume=0.5, fade_in=1.0, fade_out=2.0))
    root = ET.parse(tmp_path / "project_premiere.xml").getroot()
    clips = {c.get("id"): c for c in root.iter("clipitem") if (c.get("id") or "").startswith("audio-attached-music")}
    assert sorted(clips) == [f"audio-attached-music-{i}" for i in range(3)]
    assert [(c.findtext("start"), c.findtext("end")) for c in (clips[k] for k in sorted(clips))] == [
        ("0", "45"), ("45", "90"), ("90", "120")]
    files = [f for f in root.iter("file") if f.get("id") == "attached-music-file-1"]
    assert len(files) == 3 and sum(1 for f in files if f.findtext("pathurl")) == 1  # defined once, then referenced

    def keyframes(clip):
        return [(k.findtext("when"), k.findtext("value")) for k in clip.iter("keyframe")]
    assert keyframes(clips["audio-attached-music-0"]) == [("0", "-60"), ("30", "-6.02")]
    assert keyframes(clips["audio-attached-music-1"]) == []
    assert keyframes(clips["audio-attached-music-2"]) == [("0", "-6.02"), ("30", "-60")]
    with zipfile.ZipFile(bundle) as zf:
        assert any(name.endswith("-bg.wav") for name in zf.namelist())


def test_premiere_xml_without_attached_music_is_unchanged_and_missing_file_is_skipped(tmp_path):
    from engine.premiere import AttachedMusic, build_premiere
    plan = _premiere_plan(tmp_path)
    build_premiere(plan, tmp_path, base_dir=tmp_path)
    plain = (tmp_path / "project_premiere.xml").read_text()
    build_premiere(plan, tmp_path, base_dir=tmp_path, attached_music=AttachedMusic(tmp_path / "missing.wav"))
    assert (tmp_path / "project_premiere.xml").read_text() == plain
    assert "attached-music" not in plain

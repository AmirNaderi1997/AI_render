import json
import subprocess
import pytest

from PIL import Image

from engine import style_library as styles


def _isolated_library(tmp_path, monkeypatch):
    monkeypatch.setattr(styles, "ROOT", tmp_path)
    monkeypatch.setattr(styles, "DRAFTS", tmp_path / "drafts")
    monkeypatch.setattr(styles, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(styles, "ASSETS", tmp_path / "assets")
    for path in (styles.DRAFTS, styles.PROFILES, styles.ASSETS):
        path.mkdir(parents=True, exist_ok=True)


def test_snapshot_draft_has_unknown_timing_and_motion_and_visible_clues(tmp_path, monkeypatch):
    _isolated_library(tmp_path, monkeypatch)
    image_path = tmp_path / "sample.png"
    image = Image.new("RGB", (360, 640), "#242424")
    for y in range(520, 610):
        for x in range(30, 330):
            image.putpixel((x, y), (240, 180, 0) if (x // 12) % 2 else (255, 255, 255))
    image.save(image_path)
    draft = styles.import_snapshots([("sample.png", image_path.read_bytes())], "Snapshot")
    assert draft["state"] == "draft"
    assert draft["profile"]["learned"]["timing"] == {"status": "unknown", "value": None}
    assert draft["profile"]["learned"]["motion"] == {"status": "unknown", "value": None}
    assert draft["profile"]["learned"]["palette"]
    assert draft["profile"]["learned"]["typography_clues"]["candidates"]


def test_reference_video_has_sampled_frame_time_and_supporting_evidence(tmp_path, monkeypatch):
    _isolated_library(tmp_path, monkeypatch)
    video = tmp_path / "source.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=320x240:d=1.2:r=10",
                    "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1.2:r=10", "-filter_complex",
                    "[0:v][1:v]concat=n=2:v=1:a=0", "-t", "2.4", "-pix_fmt", "yuv420p", str(video), "-y"], check=True)
    draft = styles.import_reference_video("sample.mp4", video.read_bytes(), "Reference")
    frame_evidence = [e for e in draft["evidence"] if e["kind"] == "video_frame"]
    assert len(frame_evidence) >= 3
    assert all(e["at_seconds"] is not None and e["source_range"] for e in frame_evidence)
    assert all((styles.ASSETS / e["asset"]).is_file() for e in frame_evidence)
    assert draft["profile"]["learned"]["timing"]["status"] == "observed_samples"


def test_style_file_import_edit_approve_and_round_trip(tmp_path, monkeypatch):
    _isolated_library(tmp_path, monkeypatch)
    imported = styles.import_style_file("brand.yaml", b"captions:\n  base:\n    colour: '#F0B400'\n", "Brand")
    reopened = styles.get_draft(imported["id"])
    assert reopened["source"]["original"]["captions"]["base"]["colour"] == "#F0B400"
    reopened["profile"]["captions"]["base"]["size"] = 88
    updated = styles.update_draft(reopened["id"], {"name": "Brand final", "profile": reopened["profile"]})
    approved = styles.approve_draft(updated["id"])
    loaded = styles.get_profile(updated["id"], 1)
    assert loaded["profile"]["captions"]["base"]["colour"] == "#F0B400"
    assert loaded["profile"]["captions"]["base"]["size"] == 88
    assert approved["source"]["sha256"] == imported["source"]["sha256"]
    assert styles.resolve_preset(updated["id"], 1)["captions"]["base"]["colour"] == "#F0B400"


def test_style_import_rejects_values_that_would_crash_rendering(tmp_path, monkeypatch):
    _isolated_library(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="captions.base.size"):
        styles.import_style_file(
            "bad-size.yaml", b"captions:\n  base:\n    size: enormous\n"
        )
    with pytest.raises(ValueError, match="render.preview_scale"):
        styles.import_style_file(
            "bad-preview.yaml", b"render:\n  preview_scale: 4\n"
        )
    with pytest.raises(ValueError, match="render.preset"):
        styles.import_style_file(
            "bad-preset.yaml", b"render:\n  preset: [bad]\n"
        )
    with pytest.raises(ValueError, match="captions.styles.headline.background_colour"):
        styles.import_style_file(
            "bad-headline.yaml", b"captions:\n  styles:\n    headline:\n      background_colour: transparent\n"
        )
    with pytest.raises(ValueError, match="captions.styles.headline.enabled"):
        styles.import_style_file(
            "bad-hook-toggle.yaml", b"captions:\n  styles:\n    headline:\n      enabled: always\n"
        )


def test_style_selection_is_pinned_and_resolves_again_after_reload(tmp_path, monkeypatch):
    _isolated_library(tmp_path, monkeypatch)
    d = styles.import_style_file("persist.json", b'{"captions":{"base":{"colour":"#123456"}}}', "Persist")
    approved = styles.approve_draft(d["id"])
    job = tmp_path / "job"; job.mkdir()
    selection = {"style_id": approved["style_id"], "version": approved["version"], "name": approved["name"], "state": "pinned"}
    (job / "style_selection.json").write_text(json.dumps(selection))
    # A process restart reloads both the job pin and its immutable library version from disk.
    pin = json.loads((job / "style_selection.json").read_text())
    assert styles.get_profile(pin["style_id"], pin["version"])["state"] == "approved"
    assert styles.resolve_preset(pin["style_id"], pin["version"])["captions"]["base"]["colour"] == "#123456"


def test_remove_profile_hides_it_but_preserves_pinned_resolution(tmp_path, monkeypatch):
    _isolated_library(tmp_path, monkeypatch)
    draft = styles.import_style_file("old.yaml", b"captions:\n  base:\n    colour: '#654321'\n", "Old")
    approved = styles.approve_draft(draft["id"])

    removed = styles.remove_profile(approved["style_id"], approved["version"])
    assert removed["state"] == "archived"
    assert styles.list_library()["profiles"] == []
    assert styles.resolve_preset(approved["style_id"], approved["version"])["captions"]["base"]["colour"] == "#654321"
    next_draft = styles.fork_profile(approved["style_id"], approved["version"])
    assert styles.approve_draft(next_draft["id"])["version"] == 2


def test_remove_unapproved_style_draft(tmp_path, monkeypatch):
    _isolated_library(tmp_path, monkeypatch)
    draft = styles.import_style_file("draft.yaml", b"captions:\n  base:\n    colour: '#ABCDEF'\n", "Draft")
    assert styles.remove_draft(draft["id"])["state"] == "deleted"
    assert styles.list_library()["drafts"] == []


def test_job_plan_regeneration_reuses_approved_pin_after_restart(tmp_path, monkeypatch):
    from app import jobs

    _isolated_library(tmp_path, monkeypatch)
    draft = styles.import_style_file("pinned.yaml", b"captions:\n  base:\n    colour: '#AABBCC'\n", "Pinned")
    approved = styles.approve_draft(draft["id"])
    job_dir = tmp_path / "job"; job_dir.mkdir()
    (job_dir / "style_selection.json").write_text(json.dumps({"style_id": approved["style_id"],
        "version": approved["version"], "name": approved["name"], "state": "pinned"}))
    started = []

    class NoRunThread:
        def __init__(self, *args, **kwargs): started.append(kwargs["args"])
        def start(self): pass

    monkeypatch.setattr(jobs.threading, "Thread", NoRunThread)
    job = jobs.Job(id="fresh-restart", dir=job_dir, raw_name="source.mp4")
    jobs.start_generate(job, use_saved_transcript=True)
    args = started[-1]
    assert args[-1] == {"style_id": approved["style_id"], "version": 1, "name": "Pinned"}
    assert args[-2]["captions"]["base"]["colour"] == "#AABBCC"

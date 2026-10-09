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
            assert "track.mp3" in names


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

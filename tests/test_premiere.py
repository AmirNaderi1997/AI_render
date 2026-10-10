from __future__ import annotations

import json
import subprocess
import wave
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from brain import asset_match
from engine.premiere import (
    PREMIERE_BUNDLE,
    PREMIERE_CAPTIONS,
    PREMIERE_REPORT,
    PREMIERE_README,
    PREMIERE_VERIFICATION,
    PREMIERE_XML,
    build_premiere,
    validate_manifest,
    write_native_verification_record,
    _text,
)
from engine.schema import Broll, Music, Sfx, validate_plan


SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "plans"


def _plan(tmp_path: Path, media_dir: Path, transition_type: str | None = None):
    source = tmp_path / "raw.mp4"
    source.write_bytes((media_dir / "raw.mp4").read_bytes())
    data = json.loads((SAMPLES / "cut.json").read_text())
    data["source"] = "raw.mp4"
    data["captions"] = [{"start": 0, "end": 1, "text": "سلام", "style": "normal"}]
    if transition_type:
        data["version"] = "0.3"
        data["transitions"] = [{
            "from_segment_id": "s1", "to_segment_id": "s2",
            "type": transition_type, "duration_frames": 6,
            "direction": "right", "intensity": 0.75,
            "source": "manual", "locked": True,
        }]
    plan, errors = validate_plan(data, base_dir=tmp_path, check_media=True)
    assert errors == []
    return plan


def _xml(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def test_xml_text_filters_invalid_control_characters():
    root = ET.Element('xmeml')
    _text(root, 'name', 'clip\x00\x1f name')
    assert ET.fromstring(ET.tostring(root)).findtext('name') == 'clip name'


def _native_observations(tmp_path: Path, plan, classification: str = "exact_editable",
                         imported_type: str = "Cut") -> dict:
    prproj = tmp_path / "observed.prproj"
    screenshot = tmp_path / "active-sequence.png"
    prproj.write_bytes(b"premiere-project-evidence")
    screenshot.write_bytes(b"png-evidence")
    exports = tmp_path / "exports"
    exports.mkdir(exist_ok=True)
    (exports / "v1.mp4").write_bytes(b"rendered-reference-evidence")
    return {
        "premiere_version": "25.3.0",
        "prproj_path": str(prproj.resolve()),
        "verification_time": "2026-10-04T12:00:00+03:30",
        "verified_sequence_name": "AI Render editable sequence",
        "observed_frame_count": plan.output_frames,
        "observed_geometry": {"width": 1080, "height": 1920, "fps": 30,
                              "pixel_aspect": "square", "field_order": "progressive",
                              "audio_sample_rate": 48000},
        "transition_observations": [{"boundary_index": 0,
                                     "imported_type": imported_type,
                                     "duration_frames": plan.transitions[0].duration_frames if plan.transitions else 0,
                                     "classification": classification}],
        "caption_observations": {"caption_track_visible": True,
                                 "content_timing_classification": "sidecar_editable",
                                 "persisted_after_reopen": True,
                                 "styling_classification": "rendered_only"},
        "relink_observations": {"status": "verified", "persisted_after_reopen": True},
        "effect_observations": [],
        "save_reopen": {"status": "verified"},
        "evidence_screenshot_paths": [str(screenshot.resolve())],
    }


def test_premiere_hard_cut_is_backward_compatible(tmp_path, media_dir):
    plan = _plan(tmp_path, media_dir)
    bundle = build_premiere(plan, tmp_path, base_dir=tmp_path)
    root = _xml(tmp_path / PREMIERE_XML)

    assert root.tag == "xmeml" and root.get("version") == "5"
    assert root.findtext("./sequence/duration") == "150"
    assert root.findall("./sequence/media/video/track/transitionitem") == []
    clips = root.findall("./sequence/media/video/track/clipitem")
    assert [(c.findtext("start"), c.findtext("end")) for c in clips] == [("0", "60"), ("60", "150")]
    assert clips[0].findtext("file/pathurl").startswith("media/")
    with zipfile.ZipFile(bundle) as archive:
        assert clips[0].findtext("file/pathurl") in archive.namelist()
    assert bundle.name == PREMIERE_BUNDLE and bundle.exists()


def test_premiere_crossfade_preserves_overlap_and_audio_transition(tmp_path, media_dir):
    plan = _plan(tmp_path, media_dir, "crossfade")
    build_premiere(plan, tmp_path, base_dir=tmp_path)
    root = _xml(tmp_path / PREMIERE_XML)

    assert root.findtext("./sequence/duration") == str(plan.output_frames) == "144"
    video_clips = root.findall("./sequence/media/video/track/clipitem")
    assert [(c.findtext("start"), c.findtext("end")) for c in video_clips] == [("0", "-1"), ("-1", "144")]
    video_transition = root.find("./sequence/media/video/track/transitionitem")
    assert video_transition is not None
    assert (video_transition.findtext("start"), video_transition.findtext("end")) == ("54", "60")
    assert video_transition.findtext("effect/effectid") == "Cross Dissolve"
    audio_transition = root.find("./sequence/media/audio/track/transitionitem")
    assert audio_transition is not None
    assert audio_transition.findtext("effect/effectid") == "Cross Fade (+3dB)"

    report = json.loads((tmp_path / PREMIERE_REPORT).read_text())
    assert report["output_frames"] == 144
    assert report["transitions"][0]["status"] == "supported"
    assert report["transitions"][0]["premiere_mapping"] == "Cross Dissolve"


def test_premiere_directional_mapping_uses_explicit_verified_fallback(tmp_path, media_dir):
    plan = _plan(tmp_path, media_dir, "directional")
    bundle = build_premiere(plan, tmp_path, base_dir=tmp_path)
    root = _xml(tmp_path / PREMIERE_XML)
    transition = root.find("./sequence/media/video/track/transitionitem")
    assert transition is not None
    assert transition.findtext("effect/effectid") == "Cross Dissolve"
    assert transition.findall("effect/parameter") == []
    assert (transition.findtext("start"), transition.findtext("end")) == ("54", "60")

    report = json.loads((tmp_path / PREMIERE_REPORT).read_text())
    row = report["transitions"][0]
    assert row["status"] == "fallback"
    assert row["premiere_mapping"] == "Cross Dissolve"
    assert row["direction"] == "right"
    assert row["intensity"] == 0.75
    assert report["native_verification"]["version"] == "25.3.0"
    assert report["native_verification"]["fallback"] == ["directional"]
    assert report["warnings"]

    with zipfile.ZipFile(bundle) as archive:
        assert {PREMIERE_XML, PREMIERE_CAPTIONS, PREMIERE_REPORT, PREMIERE_README}.issubset(archive.namelist())
        assert all(path in archive.namelist() for path in
                   ET.fromstring(archive.read(PREMIERE_XML).split(b"<!DOCTYPE xmeml>\n", 1)[1])
                   .itertext() if path.startswith("media/"))
        assert b"File > Import" in archive.read(PREMIERE_README)
        assert "سلام" in archive.read(PREMIERE_CAPTIONS).decode("utf-8")


def test_package_contains_timed_broll_music_and_narration(tmp_path, media_dir):
    plan = _plan(tmp_path, media_dir)
    audio = tmp_path / "narration.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(b"\0\0" * 48000)
    plan.broll = [Broll(at=1, duration=1, in_=0.5, file="raw.mp4")]
    plan.music = Music(file="narration.wav", volume_db=-18)
    plan.sfx = [Sfx(at=2, file="narration.wav", volume_db=-3)]
    bundle = build_premiere(plan, tmp_path, base_dir=tmp_path)
    with zipfile.ZipFile(bundle) as archive:
        root = ET.fromstring(archive.read(PREMIERE_XML).split(b"<!DOCTYPE xmeml>\n", 1)[1])
        names = set(archive.namelist())
        for path in root.findall(".//file/pathurl"):
            assert path.text and path.text.startswith("media/") and path.text in names
        broll = root.find("./sequence/media/video/track/clipitem[@id='video-broll-0']")
        assert broll is not None
        assert [broll.findtext(tag) for tag in ("start", "end", "in", "out")] == ["30", "60", "15", "45"]
        narration = root.find("./sequence/media/audio/track/clipitem[@id='audio-sfx-0']")
        assert narration is not None
        assert [narration.findtext(tag) for tag in ("start", "end", "in", "out")] == ["60", "90", "0", "30"]
        music = root.find("./sequence/media/audio/track/clipitem[@id='audio-music']")
        assert music is not None
        music_track = next(track for track in root.findall("./sequence/media/audio/track")
                           if track.find("clipitem[@id='audio-music']") is not None)
        music_clips = music_track.findall("clipitem")
        assert len(music_clips) == 5
        assert [(clip.findtext("start"), clip.findtext("end")) for clip in music_clips] == [
            (str(start), str(start + 30)) for start in range(0, 150, 30)]


def test_package_refuses_missing_media(tmp_path, media_dir):
    plan = _plan(tmp_path, media_dir)
    plan.sfx = [Sfx(at=1, file="missing.wav")]
    with pytest.raises(FileNotFoundError, match="Premiere media is missing"):
        build_premiere(plan, tmp_path, base_dir=tmp_path)


def test_placeholder_broll_is_omitted_before_premiere_packaging(tmp_path, media_dir, monkeypatch):
    from brain.asset_match import resolve_plan_assets

    plan = _plan(tmp_path, media_dir)
    plan.broll = [Broll(at=1, duration=1, file="broll/placeholder.mp4", query="city skyline")]
    plan_data = plan.model_dump(by_alias=True)
    monkeypatch.setattr(asset_match, "broll_match", lambda *args, **kwargs: [])

    resolutions = resolve_plan_assets(plan_data, base_dir=tmp_path)
    assert plan_data["broll"] == []
    assert resolutions["omitted_broll"] == [{
        "index": 0,
        "query": "city skyline",
        "file": "broll/placeholder.mp4",
        "reason": "no existing B-roll media was available",
    }]

    resolved_plan, errors = validate_plan(plan_data, base_dir=tmp_path, check_media=False)
    assert errors == []
    assert build_premiere(resolved_plan, tmp_path, base_dir=tmp_path).is_file()


def test_silent_source_does_not_claim_an_audio_stream(tmp_path, media_dir):
    plan = _plan(tmp_path, media_dir)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=black:s=1080x1920:r=30:d=5", "-an", "-c:v", "libx264",
                    str(tmp_path / "silent.mp4")], check=True)
    plan.source = "silent.mp4"
    build_premiere(plan, tmp_path, base_dir=tmp_path)
    root = _xml(tmp_path / PREMIERE_XML)
    assert root.findall("./sequence/media/audio/track") == []
    assert root.find("./sequence/media/video/track/clipitem/file/media/audio") is None
    assert root.find("./sequence/media/video/track/clipitem/link/mediatype").text == "video"


def test_premiere_zoom_candidate_is_marked_unverified_until_native_acceptance(tmp_path, media_dir):
    plan = _plan(tmp_path, media_dir, "zoom")
    build_premiere(plan, tmp_path, base_dir=tmp_path)
    report = json.loads((tmp_path / PREMIERE_REPORT).read_text(encoding="utf-8"))
    transition = report["transitions"][0]
    assert transition["classification"] == "unverified"
    assert transition["premiere_representation"].startswith("Candidate Cross Dissolve")
    assert transition["requested_behavior"]["zoom_mode"] == "zoom_in"
    assert transition["requested_behavior"]["zoom_scale"] == 1.15
    assert transition["native_verification"]["status"] == "unverified"
    assert report["schema_version"] == "1.0"
    assert report["sequence"]["output_frames"] == plan.output_frames
    assert "zoom" in report["native_verification"]["unverified"]
    assert transition["capability_classification"] == "unverified"
    assert transition["current_artifact_verification"]["status"] == "unverified"
    assert report["current_artifact_verification"]["fully_verified"] is False
    assert report["overall_result"] == "awaiting_current_artifact_verification"
    validate_manifest(report)


def test_historical_capability_does_not_verify_the_current_package(tmp_path, media_dir):
    plan = _plan(tmp_path, media_dir, "crossfade")
    build_premiere(plan, tmp_path, base_dir=tmp_path)
    report = json.loads((tmp_path / PREMIERE_REPORT).read_text())
    row = report["transitions"][0]
    assert row["classification"] == row["capability_classification"] == "exact_editable"
    assert row["native_verification"]["scope"] == "historical_capability"
    assert row["current_artifact_verification"]["classification"] == "unverified"
    assert report["historical_capability_evidence"]["verified_on"] == "2026-10-04"
    assert "verification_time" not in report["current_artifact_verification"]
    assert report["overall_result"] == "awaiting_current_artifact_verification"


def test_hash_bound_zoom_observation_classifies_only_current_artifact(tmp_path, media_dir):
    plan = _plan(tmp_path, media_dir, "zoom")
    build_premiere(plan, tmp_path, base_dir=tmp_path)
    observations = _native_observations(tmp_path, plan, "editable_fallback", "Cross Dissolve")
    write_native_verification_record(plan, tmp_path, observations)
    build_premiere(plan, tmp_path, base_dir=tmp_path)
    report = json.loads((tmp_path / PREMIERE_REPORT).read_text())
    row = report["transitions"][0]
    assert row["capability_classification"] == "unverified"
    assert row["current_artifact_verification"]["status"] == "verified"
    assert row["current_artifact_verification"]["classification"] == "editable_fallback"
    assert report["current_artifact_verification"]["fully_verified"] is True
    assert report["overall_result"] == "current_artifact_verified_with_limitations"


def test_native_observation_must_match_planned_boundary_semantics(tmp_path, media_dir):
    plan = _plan(tmp_path, media_dir, "zoom")
    build_premiere(plan, tmp_path, base_dir=tmp_path)
    observations = _native_observations(tmp_path, plan, "exact_editable", "Zoom")
    with pytest.raises(ValueError, match="zoom cannot be certified as exact_editable"):
        write_native_verification_record(plan, tmp_path, observations)

    observations = _native_observations(tmp_path, plan, "editable_fallback", "Cross Dissolve")
    observations["transition_observations"][0]["duration_frames"] += 1
    with pytest.raises(ValueError, match="observed duration does not match the plan"):
        write_native_verification_record(plan, tmp_path, observations)


def test_plan_hash_change_invalidates_native_verification_and_refreshes_package(tmp_path, media_dir):
    plan = _plan(tmp_path, media_dir, "crossfade")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(by_alias=True, exclude_none=False), encoding="utf-8")
    build_premiere(plan, tmp_path, base_dir=tmp_path)
    write_native_verification_record(plan, tmp_path, _native_observations(
        tmp_path, plan, "exact_editable", "Cross Dissolve"))
    build_premiere(plan, tmp_path, base_dir=tmp_path)
    assert json.loads((tmp_path / PREMIERE_REPORT).read_text())["current_artifact_verification"]["status"] == "verified"

    plan_path.write_text(plan_path.read_text() + "\n", encoding="utf-8")
    build_premiere(plan, tmp_path, base_dir=tmp_path)
    report = json.loads((tmp_path / PREMIERE_REPORT).read_text())
    assert report["current_artifact_verification"]["status"] == "invalidated"
    assert report["current_artifact_verification"]["mismatched_fields"] == ["plan_sha256"]
    assert report["current_artifact_verification"]["fully_verified"] is False
    with zipfile.ZipFile(tmp_path / PREMIERE_BUNDLE) as archive:
        packaged = json.loads(archive.read(PREMIERE_REPORT))
    assert packaged["artifact_identity"] == report["artifact_identity"]
    assert packaged["overall_result"] == "awaiting_current_artifact_verification"
    assert (tmp_path / PREMIERE_VERIFICATION).is_file()


def test_render_hash_change_invalidates_native_verification(tmp_path, media_dir):
    plan = _plan(tmp_path, media_dir, "crossfade")
    build_premiere(plan, tmp_path, base_dir=tmp_path)
    write_native_verification_record(plan, tmp_path, _native_observations(
        tmp_path, plan, "exact_editable", "Cross Dissolve"))
    render = tmp_path / "exports/v1.mp4"
    render.write_bytes(b"changed copied render")
    build_premiere(plan, tmp_path, base_dir=tmp_path)
    report = json.loads((tmp_path / PREMIERE_REPORT).read_text())
    assert report["current_artifact_verification"]["status"] == "invalidated"
    assert report["current_artifact_verification"]["mismatched_fields"] == ["render_sha256"]


def test_manifest_validation_rejects_incomplete_component():
    report = {"schema_version": "1.0"}
    try:
        validate_manifest(report)
    except ValueError as error:
        assert "created_at" in str(error)
    else:
        raise AssertionError("incomplete compatibility manifest passed validation")


def test_srt_and_manifest_keep_utf8_caption_text_and_output_timing(tmp_path, media_dir):
    plan = _plan(tmp_path, media_dir, "crossfade")
    plan.captions[0].text = "سلام، AI Render!"
    # Captions are already defined on the overlap-adjusted output timeline.
    build_premiere(plan, tmp_path, base_dir=tmp_path)
    srt = (tmp_path / PREMIERE_CAPTIONS).read_text(encoding="utf-8")
    assert "سلام، AI Render!" in srt
    report = json.loads((tmp_path / PREMIERE_REPORT).read_text(encoding="utf-8"))
    component = report["captions"]["components"][0]
    assert component["classification"] == "sidecar_editable"
    assert component["requested_behavior"]["text"] == "سلام، AI Render!"
    assert component["planned_frame_range"] == {"start": 0, "end_exclusive": 30}
    assert report["captions"]["styling"]["does_not_transfer"]

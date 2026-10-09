"""Schema validation rules — no external tools required."""
from __future__ import annotations
from pathlib import Path

import pytest

from engine.schema import validate_plan
from engine.effects import EFFECT_CATALOG, effect_filter_xml


BASE_PLAN = {
    "canvas": {"width": 1080, "height": 1920, "fps": 30},
    "source": "raw.mp4",
    "segments": [{"id": "s1", "in": 0.0, "out": 4.0}],
    "captions": [],
    "broll": [],
    "sfx": [],
    "export": {"file": "out.mp4"},
}


def _v(plan: dict, base: Path | None = None, check_media: bool = False):
    return validate_plan(plan, base_dir=base, check_media=check_media)


def test_valid_plan_passes():
    plan, errs = _v({**BASE_PLAN})
    assert errs == []
    assert plan is not None
    assert plan.output_duration == 4.0


def test_h264_incompatible_canvas_is_rejected_during_plan_validation():
    _, errors = _v({**BASE_PLAN, "canvas": {"width": 1081, "height": 1920, "fps": 30}})
    assert any(error.startswith("canvas.width:") and "multiple of 2" in error for error in errors), errors
    _, errors = _v({**BASE_PLAN, "canvas": {"width": 1080, "height": 1921, "fps": 30}})
    assert any(error.startswith("canvas.height:") and "multiple of 2" in error for error in errors), errors


def test_negative_in_rejected():
    p = {**BASE_PLAN, "segments": [{"id": "s1", "in": -0.1, "out": 1.0}]}
    _, errs = _v(p)
    assert any(e.startswith("segments.0.in:") and "greater than or equal to 0" in e for e in errs), errs


def test_negative_times_rejected_everywhere():
    cases = {
        "segments.0.out": {"segments": [{"id": "s1", "in": 0, "out": -1.0}]},
        "captions.0.start": {"captions": [{"start": -1, "end": 1, "text": "x"}]},
        "broll.0.at": {"broll": [{"at": -1, "duration": 1, "file": "b.mp4"}]},
        "sfx.0.at": {"sfx": [{"at": -1, "file": "s.wav"}]},
    }
    for path, override in cases.items():
        _, errs = _v({**BASE_PLAN, **override})
        assert any(e.startswith(path + ":") and "greater than or equal to 0" in e for e in errs), (path, errs)


def test_out_not_greater_than_in_rejected():
    p = {**BASE_PLAN, "segments": [{"id": "s1", "in": 2.0, "out": 2.0}]}
    _, errs = _v(p)
    assert any(e.startswith("segments.0:") and "out (2.0) must be > in (2.0)" in e for e in errs), errs


def test_zoom_out_of_range_rejected():
    p = {**BASE_PLAN, "segments": [
        {"id": "s1", "in": 0, "out": 1, "zoom": {"from": 0.5, "to": 1.0}}
    ]}
    _, errs = _v(p)
    assert any(e.startswith("segments.0.zoom.from:") and "greater than or equal to 1" in e for e in errs), errs

    p2 = {**BASE_PLAN, "segments": [
        {"id": "s1", "in": 0, "out": 1, "zoom": {"from": 1.0, "to": 1.6}}
    ]}
    _, errs2 = _v(p2)
    assert any(e.startswith("segments.0.zoom.to:") and "less than or equal to 1.5" in e for e in errs2), errs2


def test_hundred_effect_presets_are_typed_and_renderable():
    assert len(EFFECT_CATALOG) == 100
    for effect_id in EFFECT_CATALOG:
        xml = effect_filter_xml(effect_id, 90, 1080, 1920, 6)
        assert "<filter" in xml or effect_id == "steady__neutral"


def test_visual_effect_validation():
    plan, errors = _v({**BASE_PLAN, "visual_effects": [
        {"segment_id": "s1", "type": "punch__lift_soft"}]})
    assert not errors and plan.visual_effects[0].type == "punch__lift_soft"
    _, errors = _v({**BASE_PLAN, "visual_effects": [
        {"segment_id": "s1", "type": "made_up"}]})
    assert any("unknown visual effect" in error for error in errors)
    _, errors = _v({**BASE_PLAN, "visual_effects": [
        {"segment_id": "missing", "type": "steady__neutral"}]})
    assert any("unknown segments" in error for error in errors)


def test_v4_effect_is_valid_in_plan():
    plan, errors = _v({**BASE_PLAN, "visual_effects": [
        {"segment_id": "s1", "type": "rgb_split"}]})
    assert not errors
    assert plan.visual_effects[0].type == "rgb_split"
    _, errors = _v({**BASE_PLAN, "visual_effects": [
        {"segment_id": "s1", "type": "text_pop_scale"}]})
    assert any("cannot be rendered" in error for error in errors)


def test_caption_end_not_after_start_rejected():
    p = {**BASE_PLAN, "captions": [{"start": 3, "end": 3, "text": "x"}]}
    _, errs = _v(p)
    assert any(e.startswith("captions.0:") and "end must be > start" in e for e in errs), errs


def test_blank_caption_and_nonfinite_times_are_rejected():
    _, blank_errors = _v({**BASE_PLAN, "captions": [{"start": 0, "end": 1, "text": "  "}]})
    assert any("caption text must not be empty" in error for error in blank_errors)
    _, nan_errors = _v({**BASE_PLAN, "segments": [{"id": "s1", "in": 0, "out": float("nan")}]})
    assert any("finite" in error for error in nan_errors)


def test_caption_past_output_rejected():
    p = {**BASE_PLAN, "captions": [{"start": 0, "end": 999, "text": "x"}]}
    _, errs = _v(p)
    assert any(e.startswith("captions[0].end") and "exceeds output duration" in e for e in errs), errs


def test_poster_frame_past_output_rejected():
    plan, errs = _v({**BASE_PLAN, "poster": {"text": "hook", "frame_time": 1.0}})
    assert not errs and plan.poster.text == "hook"
    _, errs = _v({**BASE_PLAN, "poster": {"text": "hook", "frame_time": 99}})
    assert any(e.startswith("poster.frame_time") for e in errs), errs


def test_cover_past_output_or_unknown_segment_rejected():
    _, errs = _v({**BASE_PLAN, "cover": {"text": "hook", "start": 0, "end": 9}})
    assert any(e.startswith("cover.end") and "exceeds output duration" in e for e in errs), errs
    _, errs = _v({**BASE_PLAN, "cover": {
        "text": "hook", "start": 0, "end": 2, "source_segment_id": "missing"}})
    assert any("cover references unknown segment" in e for e in errs), errs


def test_broll_past_output_rejected():
    p = {**BASE_PLAN, "broll": [{"at": 3.5, "duration": 5, "file": "b.mp4"}]}
    _, errs = _v(p)
    assert any(e.startswith("broll[0]") and "exceeds output duration" in e for e in errs), errs


def test_sfx_past_output_rejected():
    p = {**BASE_PLAN, "sfx": [{"at": 99, "file": "s.wav"}]}
    _, errs = _v(p)
    assert any(e.startswith("sfx[0].at") and "exceeds output duration" in e for e in errs), errs


def test_missing_source_rejected(tmp_path):
    p = {**BASE_PLAN, "source": "nope.mp4"}
    _, errs = _v(p, base=tmp_path, check_media=True)
    assert any(e.startswith("source: file not found") for e in errs), errs


def test_missing_broll_music_sfx_files_rejected(media_dir):
    p = {**BASE_PLAN,
         "broll": [{"at": 0, "duration": 1, "file": "missing_b.mp4"}],
         "music": {"file": "missing_m.wav"},
         "sfx": [{"at": 0, "file": "missing_s.wav"}]}
    _, errs = _v(p, base=media_dir, check_media=True)
    for path in ("broll[0].file", "music.file", "sfx[0].file"):
        assert any(e.startswith(path + ": file not found") for e in errs), (path, errs)


def test_existing_files_accepted(media_dir):
    p = {**BASE_PLAN,
         "broll": [{"at": 0, "duration": 1, "file": "broll.mp4"}],
         "music": {"file": "music.wav"},
         "sfx": [{"at": 0, "file": "whoosh.wav"}]}
    plan, errs = _v(p, base=media_dir, check_media=True)
    assert errs == [] and plan is not None


def test_segment_inside_source_duration_rejected(media_dir):
    p = {**BASE_PLAN, "source": "raw.mp4",
         "segments": [{"id": "s1", "in": 0.0, "out": 999}]}
    _, errs = _v(p, base=media_dir, check_media=True)
    assert any(e.startswith("segments[0].out") and "exceeds source duration" in e for e in errs), errs


def test_segment_inside_source_duration_accepted(media_dir):
    p = {**BASE_PLAN, "source": "raw.mp4",
         "segments": [{"id": "s1", "in": 0.0, "out": 4.0}]}
    plan, errs = _v(p, base=media_dir, check_media=True)
    assert errs == [] and plan is not None


def test_empty_segments_rejected():
    p = {**BASE_PLAN, "segments": []}
    _, errs = _v(p)
    assert any(e.startswith("segments:") and "non-empty" in e for e in errs), errs


def test_boundary_transitions_are_adjacent_frame_based_and_backward_compatible():
    legacy, errs = _v(BASE_PLAN)
    assert not errs and legacy.output_duration == 4.0
    data = {**BASE_PLAN,
            "segments": [{"id": "s1", "in": 0, "out": 2},
                         {"id": "s2", "in": 2, "out": 4}],
            "transitions": [{"from_segment_id": "s1", "to_segment_id": "s2",
                             "type": "crossfade", "duration_frames": 6,
                             "source": "planner"}]}
    plan, errs = _v(data)
    assert not errs, errs
    assert plan.output_frames == 114
    assert plan.output_duration == 3.8


def test_transition_rejects_non_adjacent_manual_or_consumed_segment():
    data = {**BASE_PLAN,
            "segments": [{"id": "s1", "in": 0, "out": 1},
                         {"id": "s2", "in": 1, "out": 2},
                         {"id": "s3", "in": 2, "out": 3}],
            "transitions": [{"from_segment_id": "s1", "to_segment_id": "s3",
                             "type": "crossfade", "duration_frames": 6}]}
    _, errs = _v(data)
    assert any("adjacent segments" in error for error in errs), errs
    data["transitions"] = [{"from_segment_id": "s1", "to_segment_id": "s2",
                            "type": "crossfade", "duration_frames": 30},
                           {"from_segment_id": "s2", "to_segment_id": "s3",
                            "type": "directional", "duration_frames": 30}]
    _, errs = _v(data)
    assert any("consume all frames of segment" in error for error in errs), errs


def test_zoom_transition_parameters_validate_and_format_cap_is_enforced():
    data = {**BASE_PLAN,
            "segments": [{"id": "s1", "in": 0, "out": 2}, {"id": "s2", "in": 2, "out": 4}],
            "transition_context": {"output_kind": "post", "style": "zoom", "request": "gentle zoom"},
            "transitions": [{"from_segment_id": "s1", "to_segment_id": "s2", "type": "zoom",
                             "duration_frames": 8, "zoom_mode": "zoom_out", "zoom_scale": 1.2,
                             "source": "manual", "locked": True}]}
    plan, errors = _v(data)
    assert not errors, errors
    assert plan.transitions[0].zoom_mode == "zoom_out"
    data["transitions"][0]["duration_frames"] = 9
    _, errors = _v(data)
    assert any("post cap" in error for error in errors), errors
    data["transitions"][0]["duration_frames"] = 6
    data["transitions"][0]["zoom_scale"] = 1.8
    _, errors = _v(data)
    assert any("zoom_scale" in error for error in errors), errors

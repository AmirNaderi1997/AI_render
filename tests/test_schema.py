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


def test_negative_in_rejected():
    p = {**BASE_PLAN, "segments": [{"id": "s1", "in": -0.1, "out": 1.0}]}
    _, errs = _v(p)
    assert any("in" in e for e in errs)


def test_out_not_greater_than_in_rejected():
    p = {**BASE_PLAN, "segments": [{"id": "s1", "in": 2.0, "out": 2.0}]}
    _, errs = _v(p)
    assert any("out" in e and "in" in e for e in errs)


def test_zoom_out_of_range_rejected():
    p = {**BASE_PLAN, "segments": [
        {"id": "s1", "in": 0, "out": 1, "zoom": {"from": 0.5, "to": 1.0}}
    ]}
    _, errs = _v(p)
    assert any("zoom" in e or "from" in e for e in errs)

    p2 = {**BASE_PLAN, "segments": [
        {"id": "s1", "in": 0, "out": 1, "zoom": {"from": 1.0, "to": 1.6}}
    ]}
    _, errs2 = _v(p2)
    assert any("zoom" in e or "to" in e for e in errs2)


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
        {"segment_id": "s1", "type": "text_pop_scale"}]})
    assert not errors
    assert plan.visual_effects[0].type == "text_pop_scale"


def test_caption_bounds():
    p = {**BASE_PLAN, "captions": [{"start": 3, "end": 3, "text": "x"}]}
    _, errs = _v(p)
    assert any("end" in e or "start" in e for e in errs)


def test_caption_past_output_rejected():
    p = {**BASE_PLAN, "captions": [{"start": 0, "end": 999, "text": "x"}]}
    _, errs = _v(p)
    assert any("exceeds output duration" in e for e in errs)


def test_broll_past_output_rejected():
    p = {**BASE_PLAN, "broll": [{"at": 3.5, "duration": 5, "file": "b.mp4"}]}
    _, errs = _v(p)
    assert any("exceeds output duration" in e for e in errs)


def test_missing_file_rejected(tmp_path):
    p = {**BASE_PLAN, "source": "nope.mp4"}
    _, errs = _v(p, base=tmp_path, check_media=True)
    assert any("file not found" in e for e in errs)


def test_source_duration_check(media_dir):
    p = {**BASE_PLAN, "source": "raw.mp4",
         "segments": [{"id": "s1", "in": 0.0, "out": 999}]}
    _, errs = _v(p, base=media_dir, check_media=True)
    assert any("exceeds source duration" in e for e in errs)


def test_empty_segments_rejected():
    p = {**BASE_PLAN, "segments": []}
    _, errs = _v(p)
    assert any("segments" in e for e in errs)

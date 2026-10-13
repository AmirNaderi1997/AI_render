"""QC patcher on top of EditOperations: zoom fixes, locks, and atomic revert."""
from __future__ import annotations

from brain.qc_patch import patch_plan
from brain.qc_review import QCIssue


def _plan(**overrides) -> dict:
    base = {
        "canvas": {"width": 1080, "height": 1920, "fps": 30},
        "source": "raw/test.mp4",
        "segments": [{"id": "s1", "in": 0.0, "out": 3.0}, {"id": "s2", "in": 3.0, "out": 6.0}],
        "visual_effects": [{"segment_id": "s1", "type": "steady__lift_soft"},
                           {"segment_id": "s2", "type": "punch__neutral"}],
        "captions": [{"start": 0.5, "end": 2.0, "text": "Hello"}],
        "music": {"file": "m.mp3", "volume_db": -10},
        "export": {"file": "out.mp4"},
    }
    base.update(overrides)
    return base


def _issue(type_: str, fix: str, segment_id=None, timestamp=1.0) -> QCIssue:
    return QCIssue(segment_id=segment_id, timestamp=timestamp, type=type_, severity="warning",
                   description="", suggested_fix=fix)


def test_frozen_frame_sets_zoom_effect_even_when_an_effect_exists():
    patched, changes = patch_plan(_plan(), [_issue("frozen_frame", "add_zoom_effect", "s1")])
    effects = {e["segment_id"]: e["type"] for e in patched["visual_effects"]}
    # The light treatment is kept; only the motion changes.
    assert effects["s1"] == "slow_push__lift_soft"
    assert changes[0]["type"] == "zoom_added"


def test_frozen_frame_skips_segment_already_moving():
    patched, changes = patch_plan(_plan(), [_issue("frozen_frame", "add_zoom_effect", "s2")])
    assert changes == [] and patched == _plan()


def test_bad_framing_softens_aggressive_effect():
    patched, changes = patch_plan(_plan(), [_issue("bad_framing", "adjust_zoom_params", "s2")])
    effects = {e["segment_id"]: e["type"] for e in patched["visual_effects"]}
    assert effects["s2"] == "slow_push__neutral"
    assert changes[0]["operation"] == {"op": "set_effect", "segment_id": "s2", "effect": "slow_push__neutral"}


def test_bad_framing_on_legacy_zoom_plan():
    plan = _plan(visual_effects=[], segments=[
        {"id": "s1", "in": 0.0, "out": 3.0, "zoom": {"from": 1.0, "to": 1.45}},
        {"id": "s2", "in": 3.0, "out": 6.0}])
    patched, changes = patch_plan(plan, [_issue("bad_framing", "adjust_zoom_params", "s1")])
    assert patched["visual_effects"] == [{"segment_id": "s1", "type": "slow_push__neutral"}]


def test_locked_items_are_not_patched_but_other_fixes_apply():
    plan = _plan()
    plan["visual_effects"][0]["locked"] = True
    plan["captions"][0]["locked"] = True
    issues = [_issue("frozen_frame", "add_zoom_effect", "s1"),
              _issue("caption_on_face", "shift_caption_timing", timestamp=1.0),
              _issue("music_too_loud", "lower_music_volume")]
    patched, changes = patch_plan(plan, issues)
    assert [c["type"] for c in changes] == ["music_volume_lowered"]
    assert patched["visual_effects"][0]["type"] == "steady__lift_soft"
    assert patched["captions"][0].get("position", "bottom") == "bottom"
    assert patched["music"]["volume_db"] == -14


def test_duck_and_caption_shift():
    issues = [_issue("speech_too_quiet", "adjust_music_volume", "s1", timestamp=2.0),
              _issue("speech_too_quiet", "adjust_music_volume", "s1", timestamp=2.5),
              _issue("caption_on_face", "shift_caption_timing", timestamp=1.0)]
    patched, changes = patch_plan(_plan(), issues)
    assert patched["music"]["duck"] == [{"start": 0.5, "end": 3.5, "volume_db": -24}]
    assert patched["captions"][0]["position"] == "top"
    assert len(changes) == 2  # the overlapping second duck is skipped


def test_black_frame_is_left_for_manual_review():
    patched, changes = patch_plan(_plan(), [_issue("black_frame", "trim_segment", "s1")])
    assert changes == []

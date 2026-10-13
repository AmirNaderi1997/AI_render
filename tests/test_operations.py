"""EditOperation layer: typed ops, atomic batches, dry-run diffs, locks."""
from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from engine.operations import (
    LockedError, OpContext, OperationError, apply_operations, output_duration,
    parse_operations, plan_diff, segment_spans, segments_in_range,
)
from engine.schema import validate_plan


def _plan(**overrides) -> dict:
    base = {
        "version": "0.3",
        "style": "rafiei_reel",
        "canvas": {"width": 1080, "height": 1920, "fps": 30},
        "source": "raw/test.mp4",
        "segments": [
            {"id": "s1", "in": 0.0, "out": 3.0},
            {"id": "s2", "in": 5.0, "out": 8.0},
            {"id": "s3", "in": 10.0, "out": 13.0},
        ],
        "visual_effects": [
            {"segment_id": "s1", "type": "steady__neutral"},
            {"segment_id": "s2", "type": "punch__neutral"},
        ],
        "transitions": [
            {"from_segment_id": "s1", "to_segment_id": "s2", "type": "crossfade", "duration_frames": 6,
             "source": "planner", "locked": False},
        ],
        "captions": [
            {"start": 0.5, "end": 2.0, "text": "Hello world", "highlighted_word": "world"},
            {"start": 3.5, "end": 4.5, "text": "Middle line"},
            {"start": 7.0, "end": 8.5, "text": "Last line"},
        ],
        "broll": [{"at": 6.0, "duration": 1.0, "file": "b.mp4"}],
        "music": {"file": "m.mp3", "volume_db": -14, "duck": [{"start": 1.0, "end": 2.0, "volume_db": -24}]},
        "sfx": [{"at": 3.6, "file": "s.wav"}, {"at": 8.0, "file": "s.wav"}],
        "export": {"file": "out.mp4", "crf": 20},
    }
    base.update(overrides)
    return base


def _ok(plan: dict) -> None:
    _, errors = validate_plan(plan, check_media=False)
    assert not errors, errors


# --- timeline -------------------------------------------------------------

def test_segment_spans_account_for_transition_overlap():
    spans = segment_spans(_plan())
    assert [round(s.start, 3) for s in spans] == [0.0, 2.8, 5.8]
    assert output_duration(_plan()) == pytest.approx(8.8)
    assert [s.id for s in segments_in_range(_plan(), 2.9, 3.0)] == ["s1", "s2"]
    assert [s.id for s in segments_in_range(_plan(), 6.0, 7.0)] == ["s3"]


# --- simple ops -------------------------------------------------------------

def test_set_effect_replaces_and_adds():
    result = apply_operations(_plan(), [
        {"op": "set_effect", "segment_id": "s2", "effect": "slow_push__neutral"},
        {"op": "set_effect", "segment_id": "s3", "effect": "slow_pull"},
    ])
    effects = {e["segment_id"]: e["type"] for e in result.plan["visual_effects"]}
    assert effects == {"s1": "steady__neutral", "s2": "slow_push__neutral", "s3": "slow_pull"}


def test_set_effect_range_maps_output_time_to_segments():
    result = apply_operations(_plan(), [{"op": "set_effect_range", "t_start": 2.0, "t_end": 4.0,
                                         "effect": "punch__neutral"}])
    effects = {e["segment_id"]: e["type"] for e in result.plan["visual_effects"]}
    assert effects == {"s1": "punch__neutral", "s2": "punch__neutral"}


def test_unknown_effect_is_rejected_and_input_untouched():
    plan = _plan()
    before = copy.deepcopy(plan)
    with pytest.raises(OperationError) as err:
        apply_operations(plan, [
            {"op": "set_music_volume", "volume_db": -20},
            {"op": "set_effect", "segment_id": "s1", "effect": "nope"},
        ])
    assert err.value.index == 1
    assert plan == before


def test_caption_text_and_highlight():
    result = apply_operations(_plan(), [
        {"op": "set_caption_text", "index": 0, "text": "Hi there"},
        {"op": "set_highlight", "index": 1, "word": "Middle"},
    ])
    caps = result.plan["captions"]
    assert caps[0]["text"] == "Hi there" and caps[0]["highlighted_word"] is None
    assert caps[1]["highlighted_word"] == "Middle"
    with pytest.raises(OperationError):
        apply_operations(_plan(), [{"op": "set_highlight", "index": 1, "word": "absent"}])


def test_move_captions_in_range():
    result = apply_operations(_plan(), [{"op": "move_captions", "t_start": 3.0, "t_end": 9.0, "position": "top"}])
    assert [c.get("position", "bottom") for c in result.plan["captions"]] == ["bottom", "top", "top"]


def test_set_transition_user_vs_ai():
    user = apply_operations(_plan(), [{"op": "set_transition", "from_segment_id": "s2", "to_segment_id": "s3",
                                       "type": "directional", "duration_frames": 4, "direction": "up"}])
    t = user.plan["transitions"][-1]
    assert t["source"] == "manual" and t["locked"] and t["duration_frames"] == 4
    ai = apply_operations(_plan(), [{"op": "set_transition", "from_segment_id": "s1", "to_segment_id": "s2",
                                     "type": "hard_cut"}], OpContext(actor="ai", respect_locks=True))
    assert ai.plan["transitions"][0]["duration_frames"] == 0
    assert ai.plan["transitions"][0]["locked"] is False
    with pytest.raises(OperationError):
        apply_operations(_plan(), [{"op": "set_transition", "from_segment_id": "s1", "to_segment_id": "s3",
                                    "type": "crossfade"}])


def test_music_volume_and_duck():
    result = apply_operations(_plan(), [
        {"op": "set_music_volume", "volume_db": -20},
        {"op": "add_duck", "start": 4.0, "end": 5.0},
    ])
    assert result.plan["music"]["volume_db"] == -20
    assert len(result.plan["music"]["duck"]) == 2
    with pytest.raises(OperationError):
        apply_operations(_plan(), [{"op": "add_duck", "start": 1.5, "end": 3.0}])
    with pytest.raises(OperationError):
        apply_operations(_plan(music=None), [{"op": "set_music_volume", "volume_db": -20}])


def test_remove_broll():
    result = apply_operations(_plan(), [{"op": "remove_broll", "index": 0}])
    assert result.plan["broll"] == []
    with pytest.raises(OperationError):
        apply_operations(_plan(), [{"op": "remove_broll", "index": 3}])


def test_parse_rejects_unknown_op_and_extra_fields():
    with pytest.raises(ValidationError):
        parse_operations([{"op": "explode"}])
    with pytest.raises(ValidationError):
        parse_operations([{"op": "set_music_volume", "volume_db": -1, "bogus": 1}])


# --- remove_range / trim ----------------------------------------------------

def test_remove_range_splits_segment_and_shifts_events():
    plan = _plan()
    # Cut 6.5–7.5s of output: inside s3 (output 5.8–8.8, source 10–13).
    result = apply_operations(plan, [{"op": "remove_range", "t_start": 6.5, "t_end": 7.5}])
    p = result.plan
    _ok(p)
    assert [s["id"] for s in p["segments"]] == ["s1", "s2", "s3", "s3b"]
    assert p["segments"][2]["out"] == pytest.approx(10.7)
    assert p["segments"][3]["in"] == pytest.approx(11.7)
    assert output_duration(p) == pytest.approx(7.8)
    # The caption 7.0–8.5 straddles the cut end; it is clipped and shifted.
    assert p["captions"][2]["start"] == pytest.approx(6.5)
    assert p["captions"][2]["end"] == pytest.approx(7.5)
    # SFX at 8.0 shifts left by 1s.
    assert p["sfx"][1]["at"] == pytest.approx(7.0)
    # B-roll 6.0–7.0 is clipped at the cut start.
    assert p["broll"][0]["duration"] == pytest.approx(0.5)


def test_remove_range_across_boundary_drops_dangling_transition():
    result = apply_operations(_plan(), [{"op": "remove_range", "t_start": 2.0, "t_end": 4.0}])
    p = result.plan
    _ok(p)
    assert [s["id"] for s in p["segments"]] == ["s1", "s2", "s3"]
    assert (p["segments"][0]["out"], p["segments"][1]["in"]) == (pytest.approx(2.0), pytest.approx(6.2))
    # s1 -> s2 stay adjacent, so their crossfade survives.
    assert p["transitions"][0]["duration_frames"] == 6
    assert output_duration(p) == pytest.approx(6.6)
    # The caption 3.5–4.5 fell mostly in the cut and keeps only its tail.
    assert (p["captions"][1]["start"], p["captions"][1]["end"]) == (pytest.approx(2.0), pytest.approx(2.3))


def test_remove_range_whole_segment():
    result = apply_operations(_plan(transitions=[]), [{"op": "remove_range", "t_start": 3.0, "t_end": 6.0}])
    p = result.plan
    _ok(p)
    assert [s["id"] for s in p["segments"]] == ["s1", "s3"]
    assert all(e["segment_id"] != "s2" for e in p["visual_effects"])
    assert [c["text"] for c in p["captions"]] == ["Hello world", "Last line"]
    assert p["captions"][1]["start"] == pytest.approx(4.0)


def test_cannot_remove_everything():
    with pytest.raises(OperationError):
        apply_operations(_plan(), [{"op": "remove_range", "t_start": 0, "t_end": 100}])


def test_trim_segment_shortens_both_ends():
    result = apply_operations(_plan(transitions=[]), [
        {"op": "trim_segment", "segment_id": "s2", "source_in": 5.5, "source_out": 7.5}])
    p = result.plan
    _ok(p)
    seg = next(s for s in p["segments"] if s["id"] == "s2")
    assert (seg["in"], seg["out"]) == (pytest.approx(5.5), pytest.approx(7.5))
    assert output_duration(p) == pytest.approx(8.0)
    with pytest.raises(OperationError):
        apply_operations(_plan(), [{"op": "trim_segment", "segment_id": "s2", "source_in": 4.0}])


# --- locks ------------------------------------------------------------------

def test_locks_block_ai_but_not_user():
    locked = apply_operations(_plan(), [
        {"op": "lock", "target": "effect", "segment_id": "s2"},
        {"op": "lock", "target": "caption", "index": 0},
        {"op": "lock", "target": "music"},
    ]).plan
    assert locked["visual_effects"][1]["locked"] and locked["captions"][0]["locked"] and locked["music"]["locked"]
    _ok(locked)
    ai = OpContext(actor="ai", respect_locks=True)
    for op in ({"op": "set_effect", "segment_id": "s2", "effect": "steady"},
               {"op": "set_caption_text", "index": 0, "text": "x"},
               {"op": "set_music_volume", "volume_db": -30},
               {"op": "remove_range", "t_start": 1.0, "t_end": 1.5}):
        with pytest.raises(LockedError):
            apply_operations(locked, [op], ai)
    # The user can still edit a locked item directly.
    user = apply_operations(locked, [{"op": "set_music_volume", "volume_db": -30}])
    assert user.plan["music"]["volume_db"] == -30
    # Only users lock/unlock.
    with pytest.raises(OperationError):
        apply_operations(locked, [{"op": "unlock", "target": "music"}], ai)


def test_transition_lock_roundtrip_keeps_schema_valid():
    p = apply_operations(_plan(), [{"op": "lock", "target": "transition",
                                    "from_segment_id": "s1", "to_segment_id": "s2"}]).plan
    assert p["transitions"][0]["source"] == "manual"
    p = apply_operations(p, [{"op": "unlock", "target": "transition",
                              "from_segment_id": "s1", "to_segment_id": "s2"}]).plan
    assert p["transitions"][0] == {**_plan()["transitions"][0], "locked": False, "source": "planner"}


# --- dry run diff -------------------------------------------------------------

def test_diff_reports_changed_paths():
    result = apply_operations(_plan(), [{"op": "set_music_volume", "volume_db": -20}])
    assert result.diff == [{"path": "music.volume_db", "before": -14, "after": -20}]
    assert plan_diff({"a": [1]}, {"a": [1, 2]}) == [{"path": "a[1]", "before": None, "after": 2}]
    assert result.operations == [{"op": "set_music_volume", "volume_db": -20.0}]


def test_locked_flags_are_optional_for_legacy_plans():
    plan = _plan()
    _ok(plan)
    assert "locked" not in plan["captions"][0]

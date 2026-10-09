"""Tests for Stage 5: Style Learner — reference analysis, profile building, feedback."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── style_learner tests ──

def test_segment_durations():
    from brain.style_learner import _segment_durations
    cuts = [2.0, 5.0, 8.0]
    durations = _segment_durations(cuts, 10.0)
    assert durations == pytest.approx([2.0, 3.0, 3.0, 2.0], abs=0.01)


def test_segment_durations_no_cuts():
    from brain.style_learner import _segment_durations
    assert _segment_durations([], 15.0) == pytest.approx([15.0], abs=0.01)


def test_pacing_trend():
    from brain.style_learner import _pacing_trend
    assert _pacing_trend([4.0, 3.5], [2.5, 2.0], [1.5, 1.0]) == "accelerating"
    assert _pacing_trend([1.0, 1.5], [2.0, 2.5], [3.0, 3.5]) == "decelerating"
    assert _pacing_trend([2.0, 2.1], [2.0, 1.9], [2.0, 2.0]) == "steady"


def test_stddev():
    from brain.style_learner import _stddev
    assert _stddev([]) == 0.0
    assert _stddev([5.0]) == 0.0
    assert _stddev([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]) == pytest.approx(2.14, abs=0.1)


def test_analyze_reference_rejects_audio_only_input(tmp_path, monkeypatch):
    from brain import style_learner

    video = tmp_path / "audio-only.mp4"
    video.write_bytes(b"fixture")
    monkeypatch.setattr(style_learner, "_require_video_stream",
                        lambda _path: (_ for _ in ()).throw(ValueError("reference reel contains no video stream")))
    with pytest.raises(ValueError, match="no video stream"):
        style_learner.analyze_reference(video)


# ── style_profile tests ──

def test_aggregate_analyses_insufficient():
    from brain.style_profile import aggregate_analyses
    analyses = [
        {"cut_lengths": {"avg": 3.0, "min": 1.0, "max": 5.0, "median": 3.0},
         "cut_count": 10, "total_duration": 30.0,
         "pacing": {"trend": "steady"}, "audio": {"mean_volume_db": -14},
         "estimated_caption_density_wps": 0.5},
    ]
    result = aggregate_analyses(analyses, min_references=3)
    assert result["sufficient"] is False
    assert result["sample_count"] == 1
    assert result["metrics"]["cut_length_avg"] == 3.0


def test_aggregate_analyses_handles_missing_and_zero_duration_metrics():
    from brain.style_profile import aggregate_analyses

    result = aggregate_analyses([
        {"cut_count": 0, "total_duration": 0},
        {"cut_count": 2, "total_duration": 0,
         "cut_lengths": {"avg": float("nan")}},
    ])
    assert result["metrics"]["cuts_per_minute"] == 120
    assert "cut_length_avg" not in result["metrics"]


def test_aggregate_analyses_sufficient():
    from brain.style_profile import aggregate_analyses
    analyses = [
        {"cut_lengths": {"avg": 2.0}, "cut_count": 15, "total_duration": 30.0,
         "pacing": {"trend": "accelerating"}, "audio": {"mean_volume_db": -12},
         "estimated_caption_density_wps": 0.6},
        {"cut_lengths": {"avg": 3.0}, "cut_count": 10, "total_duration": 30.0,
         "pacing": {"trend": "accelerating"}, "audio": {"mean_volume_db": -14},
         "estimated_caption_density_wps": 0.5},
        {"cut_lengths": {"avg": 2.5}, "cut_count": 12, "total_duration": 30.0,
         "pacing": {"trend": "steady"}, "audio": {"mean_volume_db": -13},
         "estimated_caption_density_wps": 0.55},
    ]
    result = aggregate_analyses(analyses, min_references=3)
    assert result["sufficient"] is True
    assert result["sample_count"] == 3
    assert result["metrics"]["cut_length_avg"] == pytest.approx(2.5, abs=0.01)


def test_build_learned_profile_with_overrides():
    from brain.style_profile import build_learned_profile
    analyses = [
        {"cut_lengths": {"avg": 2.0}, "cut_count": 15, "total_duration": 30.0,
         "pacing": {"trend": "accelerating"}, "audio": {"mean_volume_db": -12},
         "estimated_caption_density_wps": 0.8, "source_file": "reel1.mp4"},
        {"cut_lengths": {"avg": 2.5}, "cut_count": 12, "total_duration": 30.0,
         "pacing": {"trend": "steady"}, "audio": {"mean_volume_db": -13},
         "estimated_caption_density_wps": 0.7, "source_file": "reel2.mp4"},
        {"cut_lengths": {"avg": 2.2}, "cut_count": 14, "total_duration": 30.0,
         "pacing": {"trend": "accelerating"}, "audio": {"mean_volume_db": -11},
         "estimated_caption_density_wps": 0.9, "source_file": "reel3.mp4"},
    ]
    profile = build_learned_profile(analyses)
    assert "preset_overrides" in profile
    assert "editing" in profile["preset_overrides"]
    assert profile["preset_overrides"]["editing"]["max_static_sec"] > 0
    assert len(profile["few_shot_examples"]) > 0


def test_build_learned_profile_insufficient_keeps_empty_overrides():
    from brain.style_profile import build_learned_profile
    analyses = [{"cut_lengths": {"avg": 3.0}, "cut_count": 5, "total_duration": 15.0}]
    profile = build_learned_profile(analyses, min_references=3)
    assert profile["preset_overrides"] == {}
    assert profile["few_shot_examples"] == []


def test_save_and_load_profile():
    from brain.style_profile import save_learned_profile, load_learned_profile, LEARNED_PROFILES_DIR
    test_profile = {"preset_overrides": {"editing": {"max_static_sec": 3.0}},
                    "learned_metrics": {"sufficient": True}, "few_shot_examples": []}
    path = save_learned_profile(test_profile, name="test_profile")
    assert path.exists()
    loaded = load_learned_profile("test_profile")
    assert loaded["preset_overrides"]["editing"]["max_static_sec"] == 3.0
    path.unlink()


def test_merge_with_preset():
    from brain.style_profile import merge_with_preset
    preset = {"editing": {"max_static_sec": 4.0}, "captions": {"max_words": 5}}
    learned = {"preset_overrides": {"editing": {"max_static_sec": 2.5}}}
    merged = merge_with_preset(preset, learned)
    assert merged["editing"]["max_static_sec"] == 2.5
    assert merged["captions"]["max_words"] == 5


def test_merge_with_no_learned():
    from brain.style_profile import merge_with_preset
    preset = {"editing": {"max_static_sec": 4.0}}
    assert merge_with_preset(preset, None) == preset


# ── style_feedback tests ──

def test_compute_plan_diff_segment_removed():
    from brain.style_feedback import compute_plan_diff
    original = {"segments": [{"id": "s1", "in": 0, "out": 3}, {"id": "s2", "in": 3, "out": 6}]}
    edited = {"segments": [{"id": "s1", "in": 0, "out": 3}]}
    events = compute_plan_diff(original, edited)
    assert any(e["change_type"] == "segment_removed" and e["segment_id"] == "s2" for e in events)


def test_feedback_append_after_interrupted_tail_keeps_new_event_readable(tmp_path):
    from brain.style_feedback import load_job_feedback, log_feedback

    path = tmp_path / "feedback.jsonl"
    path.write_text('{"change_type":"partial', encoding="utf-8")
    log_feedback(tmp_path, [{"change_type": "caption_edited", "index": 2}])
    events = load_job_feedback(tmp_path)
    assert events == [{"change_type": "caption_edited", "index": 2}]


def test_compute_plan_diff_effect_changed():
    from brain.style_feedback import compute_plan_diff
    original = {"segments": [], "visual_effects": [{"segment_id": "s1", "type": "steady__neutral"}]}
    edited = {"segments": [], "visual_effects": [{"segment_id": "s1", "type": "punch__lift_medium"}]}
    events = compute_plan_diff(original, edited)
    assert any(e["change_type"] == "effect_changed" for e in events)
    eff_change = next(e for e in events if e["change_type"] == "effect_changed")
    assert eff_change["old_effect"] == "steady__neutral"
    assert eff_change["new_effect"] == "punch__lift_medium"


def test_compute_plan_diff_caption_edited():
    from brain.style_feedback import compute_plan_diff
    original = {"segments": [], "captions": [{"text": "hello", "start": 0, "end": 1}]}
    edited = {"segments": [], "captions": [{"text": "goodbye", "start": 0, "end": 1}]}
    events = compute_plan_diff(original, edited)
    assert any(e["change_type"] == "caption_edited" for e in events)


def test_compute_plan_diff_segment_trimmed():
    from brain.style_feedback import compute_plan_diff
    original = {"segments": [{"id": "s1", "in": 0, "out": 5}]}
    edited = {"segments": [{"id": "s1", "in": 0.5, "out": 4.5}]}
    events = compute_plan_diff(original, edited)
    assert any(e["change_type"] == "segment_trimmed" for e in events)


def test_log_and_load_feedback(tmp_path):
    from brain.style_feedback import log_feedback, load_job_feedback
    events = [{"change_type": "effect_changed", "segment_id": "s1"}]
    log_feedback(tmp_path, events)
    loaded = load_job_feedback(tmp_path)
    assert len(loaded) == 1
    assert loaded[0]["change_type"] == "effect_changed"
    # Append more
    log_feedback(tmp_path, [{"change_type": "caption_edited"}])
    loaded = load_job_feedback(tmp_path)
    assert len(loaded) == 2


def test_apply_feedback_to_effect_scores():
    from brain.style_feedback import apply_feedback_to_effect_scores
    scores = {"steady": 10.0, "punch": 8.0, "flash": 5.0}
    summary = {
        "effect_corrections": {
            "steady__neutral": {"punch__lift_medium": 4, "flash__neutral": 1},
        },
    }
    adjusted = apply_feedback_to_effect_scores(scores, summary)
    assert adjusted["steady"] < scores["steady"]
    assert adjusted["punch"] > scores["punch"]


def test_apply_feedback_no_summary():
    from brain.style_feedback import apply_feedback_to_effect_scores
    scores = {"steady": 10.0}
    assert apply_feedback_to_effect_scores(scores, None) == scores


def test_manual_override_persists(tmp_path):
    """Manual override via save/load cycle."""
    from brain.style_profile import save_learned_profile, load_learned_profile
    profile = {"preset_overrides": {"editing": {"max_static_sec": 2.0}},
               "learned_metrics": {"sufficient": True}, "few_shot_examples": []}
    # Manually override
    profile["preset_overrides"]["captions"] = {"max_words": 3}
    path = save_learned_profile(profile, name="manual_test")
    loaded = load_learned_profile("manual_test")
    assert loaded["preset_overrides"]["captions"]["max_words"] == 3
    path.unlink()


def test_few_shot_examples_valid():
    from brain.style_profile import _generate_few_shot_examples
    analyses = [
        {"cut_lengths": {"avg": 2.0}, "cut_count": 10, "total_duration": 20.0, "source_file": "r1.mp4"},
        {"cut_lengths": {"avg": 3.0}, "cut_count": 8, "total_duration": 24.0, "source_file": "r2.mp4"},
    ]
    examples = _generate_few_shot_examples(analyses)
    assert len(examples) == 2
    for ex in examples:
        assert "segments_preview" in ex
        assert len(ex["segments_preview"]) > 0
        for seg in ex["segments_preview"]:
            assert "id" in seg
            assert seg["out"] > seg["in"]


def test_style_enable_setting_survives_rebuild_and_reset(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from brain import style_profile
    from app.routers import style

    monkeypatch.setattr(style_profile, "LEARNED_PROFILES_DIR", tmp_path)
    refs = tmp_path / "references"
    refs.mkdir()
    analysis = {
        "cut_lengths": {"avg": 2.0}, "cut_count": 5,
        "total_duration": 12.0, "pacing": {"trend": "steady"},
        "audio": {"mean_volume_db": -12},
        "estimated_caption_density_wps": 0.8,
    }
    for index in range(3):
        (refs / f"ref-{index}.json").write_text(json.dumps(analysis))

    assert style.get_learned_style_profile()["sample_count"] == 3
    assert style.get_learned_style_profile()["active"] is False
    style.rebuild_learned_profile()
    assert style.get_learned_style_profile()["enabled"] is True
    style.update_learned_profile({"enabled": False})
    assert style.get_learned_style_profile()["enabled"] is False
    style.rebuild_learned_profile()
    assert style.get_learned_style_profile()["enabled"] is False

    with pytest.raises(HTTPException) as error:
        style.update_learned_profile({"enabled": "yes"})
    assert error.value.status_code == 422

    style.reset_learned_profile()
    assert style.get_learned_style_profile()["sample_count"] == 3
    assert style.get_learned_style_profile()["active"] is False

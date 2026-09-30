"""Unit tests for Stage 2 brain modules — mocked LLM, no network."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from brain.silence import word_gap_ranges, merge_ranges, _invert, detect_pauses
from brain.planner import source_to_output_time, output_to_source_time, generate_plan
from brain.llm import LLMUsage, _extract_json


# ---- Fixtures ----

WORDS = [
    {"w": "Hello", "start": 0.0, "end": 0.5, "prob": 0.95},
    {"w": "world", "start": 0.6, "end": 1.1, "prob": 0.9},
    # 0.8s pause here
    {"w": "this", "start": 1.9, "end": 2.3, "prob": 0.88},
    {"w": "is", "start": 2.35, "end": 2.5, "prob": 0.92},
    {"w": "a", "start": 2.55, "end": 2.6, "prob": 0.85},
    {"w": "test", "start": 2.65, "end": 3.0, "prob": 0.93},
]

SENTENCES = [
    {"text": "Hello world", "start": 0.0, "end": 1.1},
    {"text": "this is a test", "start": 1.9, "end": 3.0},
]

TRANSCRIPT = {
    "file_hash": "abc123",
    "language": "en",
    "duration": 3.5,
    "words": WORDS,
    "sentences": SENTENCES,
}

SEGMENTS = [
    {"id": "s1", "in": 0.0, "out": 1.1},
    {"id": "s2", "in": 1.9, "out": 3.0},
]


VALID_PLAN = {
    "version": "0.1",
    "style": "rafiei_reel",
    "canvas": {"width": 1080, "height": 1920, "fps": 30},
    "source": "raw/test.mp4",
    "segments": [
        {"id": "s1", "in": 0.0, "out": 1.1, "zoom": {"from": 1.0, "to": 1.0}},
        {"id": "s2", "in": 1.9, "out": 3.0, "zoom": {"from": 1.1, "to": 1.1}},
    ],
    "captions": [
        {"start": 0.0, "end": 1.1, "text": "Hello world", "style": "normal"},
        {"start": 1.1, "end": 2.2, "text": "this is a test", "style": "emphasis"},
    ],
    "broll": [],
    "music": None,
    "sfx": [],
    "export": {"file": "exports/v1.mp4", "crf": 20},
}


# ---- silence tests ----

def test_word_gap_ranges():
    gaps = word_gap_ranges(WORDS, min_gap=0.4)
    assert len(gaps) == 1
    assert gaps[0] == (1.1, 1.9)


def test_word_gap_ranges_no_gap():
    gaps = word_gap_ranges(WORDS, min_gap=2.0)
    assert gaps == []


def test_merge_ranges_overlap():
    merged = merge_ranges([(0, 3), (2, 5), (7, 9)])
    assert merged == [(0, 5), (7, 9)]


def test_merge_ranges_adjacent():
    merged = merge_ranges([(0, 1), (1.01, 2)])
    assert merged == [(0, 2)]


def test_merge_ranges_empty():
    assert merge_ranges([]) == []


def test_invert():
    result = _invert([(1.0, 2.0), (3.0, 4.0)], 0.0, 5.0)
    assert result == [(0.0, 1.0), (2.0, 3.0), (4.0, 5.0)]


def test_invert_empty():
    assert _invert([], 0.0, 5.0) == [(0.0, 5.0)]


# ---- planner time conversion tests ----

def test_source_to_output_first_segment():
    t = source_to_output_time(0.5, SEGMENTS)
    assert t == 0.5


def test_source_to_output_second_segment():
    # s1 duration = 1.1, s2 starts at 1.9 in source
    # word at 2.0 in source -> output = 1.1 + (2.0 - 1.9) = 1.2
    t = source_to_output_time(2.0, SEGMENTS)
    assert abs(t - 1.2) < 0.01


def test_source_to_output_in_removed_range():
    t = source_to_output_time(1.5, SEGMENTS)
    assert t is None


def test_output_to_source_first_segment():
    t = output_to_source_time(0.5, SEGMENTS)
    assert abs(t - 0.5) < 0.01


def test_output_to_source_second_segment():
    # output 1.5 -> second segment, offset = 1.5 - 1.1 = 0.4
    # source = 1.9 + 0.4 = 2.3
    t = output_to_source_time(1.5, SEGMENTS)
    assert abs(t - 2.3) < 0.01


# ---- LLM JSON extraction ----

def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert _extract_json('```json\n{"b": 2}\n```') == {"b": 2}


def test_extract_json_bad():
    with pytest.raises(json.JSONDecodeError):
        _extract_json("not json")


# ---- planner with mocked LLM ----

def test_planner_generates_valid_plan(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "test.mp4").write_bytes(b"fake")

    mock_usage = LLMUsage(input_tokens=1000, output_tokens=500, model="mock", elapsed_sec=1.0)

    with patch("brain.planner.chat_json", return_value=(VALID_PLAN.copy(), mock_usage)):
        plan, usage = generate_plan(
            job_dir=tmp_path,
            transcript=TRANSCRIPT,
            keep_ranges=[(0.0, 1.1), (1.9, 3.0)],
            remove_ranges=[(1.1, 1.9)],
            source_rel="raw/test.mp4",
        )

    assert plan["segments"][0]["id"] == "s1"
    assert len(plan["captions"]) == 2
    assert usage.input_tokens == 1000


def test_planner_retries_on_invalid(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "test.mp4").write_bytes(b"fake")

    bad_plan = {**VALID_PLAN, "segments": []}
    mock_usage = LLMUsage(input_tokens=500, output_tokens=250, model="mock", elapsed_sec=0.5)

    call_count = 0

    def mock_chat(system, user, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return bad_plan, mock_usage
        return VALID_PLAN.copy(), mock_usage

    with patch("brain.planner.chat_json", side_effect=mock_chat):
        plan, usage = generate_plan(
            job_dir=tmp_path,
            transcript=TRANSCRIPT,
            keep_ranges=[(0.0, 1.1), (1.9, 3.0)],
            remove_ranges=[(1.1, 1.9)],
            source_rel="raw/test.mp4",
        )

    assert call_count == 2
    assert plan["segments"][0]["id"] == "s1"


def test_planner_fails_after_max_retries(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "test.mp4").write_bytes(b"fake")

    bad_plan = {**VALID_PLAN, "segments": []}
    mock_usage = LLMUsage(input_tokens=100, output_tokens=50, model="mock", elapsed_sec=0.1)

    with patch("brain.planner.chat_json", return_value=(bad_plan, mock_usage)):
        with pytest.raises(ValueError, match="Failed to generate"):
            generate_plan(
                job_dir=tmp_path,
                transcript=TRANSCRIPT,
                keep_ranges=[(0.0, 1.1), (1.9, 3.0)],
                remove_ranges=[(1.1, 1.9)],
                source_rel="raw/test.mp4",
                max_retries=2,
            )


# ---- B-roll without file is skipped by engine ----

def test_broll_without_file_skipped_in_validation():
    plan_with_broll = {
        **VALID_PLAN,
        "broll": [{"at": 0.5, "duration": 1.0, "file": "broll/placeholder.mp4", "in": 0}],
    }
    from engine.schema import validate_plan
    plan, errs = validate_plan(plan_with_broll, check_media=False)
    assert errs == []
    assert plan is not None


# ---- caption splitting (word-time to output-time) ----

def test_caption_times_in_output_timeline():
    """Captions in the valid plan use output timeline times."""
    out_dur = sum(s["out"] - s["in"] for s in VALID_PLAN["segments"])
    for cap in VALID_PLAN["captions"]:
        assert cap["start"] >= 0
        assert cap["end"] <= out_dur + 0.01
        assert cap["end"] > cap["start"]

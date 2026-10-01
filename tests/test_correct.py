"""Tests for auto transcript correction — mocked LLM, no network."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from brain.correct import (
    auto_correct,
    detect_suspect_words,
    load_glossary,
    normalize_persian,
)
from brain.llm import LLMUsage
from brain.transcribe import effective_transcript, save_corrections


# ── helpers ────────────────────────────────────────────────────────────────────

def _words(*entries):
    return [{"w": w, "start": i * 0.5, "end": i * 0.5 + 0.4, "prob": p}
            for i, (w, p) in enumerate(entries)]


TRANSCRIPT = {
    "file_hash": "abc", "cache_key": "k1", "language": "fa",
    "duration": 3.0,
    "words": _words(("مخصول", 0.38), ("رو", 0.91), ("بخر", 0.85)),
    "sentences": [{"text": "مخصول رو بخر", "start": 0.0, "end": 1.4}],
}

PRESET_WITH_THRESHOLD = {
    "correction": {
        "low_prob_threshold": 0.60,
        "auto_apply_min_confidence": 0.85,
        "max_flagged_ratio": 0.40,
    }
}

GLOSSARY = {
    "vocabulary": ["محصول"],
    "corrections": {"مخصول": "محصول"},
}


# ── Persian normalization ──────────────────────────────────────────────────────

def test_normalize_arabic_ya_to_persian():
    assert normalize_persian("ي") == "ی"
    assert normalize_persian("ي") == "ی"
    assert normalize_persian("ى") == "ی"


def test_normalize_arabic_kaf_to_persian():
    assert normalize_persian("ك") == "ک"
    assert normalize_persian("ك") == "ک"


def test_normalize_mixed_word():
    assert normalize_persian("كتاب") == "کتاب"
    assert normalize_persian("يك") == "یک"


# ── detect_suspect_words ──────────────────────────────────────────────────────

def test_flags_low_prob_word():
    words = _words(("مخصول", 0.38), ("رو", 0.91))
    flagged = detect_suspect_words(words, threshold=0.60, glossary={})
    assert len(flagged) == 1
    assert flagged[0]["index"] == 0
    assert "low_prob" in flagged[0]["reasons"][0]


def test_flags_known_error_from_glossary():
    words = _words(("مخصول", 0.95))  # high prob but known bad form
    flagged = detect_suspect_words(words, threshold=0.60, glossary=GLOSSARY)
    assert len(flagged) == 1
    assert any("known_error" in r for r in flagged[0]["reasons"])


def test_skips_reviewed_words():
    words = _words(("مخصول", 0.38))
    words[0]["reviewed"] = True
    flagged = detect_suspect_words(words, threshold=0.60, glossary=GLOSSARY)
    assert flagged == []


def test_no_flags_when_all_high_prob():
    words = _words(("محصول", 0.95), ("رو", 0.91), ("بخر", 0.88))
    flagged = detect_suspect_words(words, threshold=0.60, glossary={})
    assert flagged == []


# ── auto_correct with mocked LLM ──────────────────────────────────────────────

def _mock_usage():
    return LLMUsage(input_tokens=100, output_tokens=30, model="mock", elapsed_sec=0.1)


def test_high_confidence_correction_returned():
    llm_resp = {"corrections": [
        {"index": 0, "old": "مخصول", "new": "محصول", "confidence": 0.95, "reason": "acoustic confusion"}
    ]}
    with patch("brain.correct.chat_json", return_value=(llm_resp, _mock_usage())):
        corrections, usage = auto_correct(TRANSCRIPT, PRESET_WITH_THRESHOLD, GLOSSARY)
    assert len(corrections) == 1
    assert corrections[0]["new"] == "محصول"
    assert corrections[0]["confidence"] == 0.95
    assert usage.input_tokens == 100


def test_low_confidence_correction_returned_but_marked():
    """Low-confidence corrections ARE returned; caller decides whether to apply."""
    llm_resp = {"corrections": [
        {"index": 0, "old": "مخصول", "new": "محصول", "confidence": 0.60, "reason": "uncertain"}
    ]}
    with patch("brain.correct.chat_json", return_value=(llm_resp, _mock_usage())):
        corrections, _ = auto_correct(TRANSCRIPT, PRESET_WITH_THRESHOLD, GLOSSARY)
    assert len(corrections) == 1
    assert corrections[0]["confidence"] == 0.60


def test_no_flags_still_calls_llm_for_context_review():
    """V2: the LLM reviews the full transcript even when no words are pre-flagged
    so it can catch contextually wrong words that Whisper was confident about."""
    good_transcript = {**TRANSCRIPT,
                       "words": _words(("محصول", 0.95), ("رو", 0.92), ("بخر", 0.88))}
    mock_result = {"corrections": []}  # LLM finds nothing to fix
    with patch("brain.correct.chat_json", return_value=(mock_result, LLMUsage())) as mock_llm:
        corrections, _ = auto_correct(good_transcript, PRESET_WITH_THRESHOLD, {})
    mock_llm.assert_called_once()  # always called now for context review
    assert corrections == []


def test_too_many_flagged_skips_llm_call():
    """If >40% of words are flagged, skip the LLM call (wrong language or noise)."""
    many_bad = {**TRANSCRIPT, "words": _words(
        ("xxx", 0.10), ("yyy", 0.10), ("zzz", 0.10), ("good", 0.95), ("fine", 0.95)
    )}
    with patch("brain.correct.chat_json") as mock_llm:
        corrections, _ = auto_correct(many_bad, PRESET_WITH_THRESHOLD, {})
    mock_llm.assert_not_called()
    assert corrections == []


def test_llm_failure_returns_empty():
    with patch("brain.correct.chat_json", side_effect=RuntimeError("network error")):
        corrections, usage = auto_correct(TRANSCRIPT, PRESET_WITH_THRESHOLD, GLOSSARY)
    assert corrections == []
    assert usage.input_tokens == 0


def test_correction_timing_preserved(tmp_path):
    """Auto-applied correction keeps the original word's start/end times."""
    raw = {
        "file_hash": "dig", "cache_key": "key1", "language": "fa", "duration": 2.0,
        "words": [
            {"w": "مخصول", "start": 0.1, "end": 0.6, "prob": 0.38},
            {"w": "رو", "start": 0.7, "end": 0.9, "prob": 0.91},
        ],
        "sentences": [{"text": "مخصول رو", "start": 0.1, "end": 0.9}],
    }
    (tmp_path / "transcript.json").write_text(json.dumps(raw, ensure_ascii=False))
    corrected = save_corrections(tmp_path, "key1", [{"index": 0, "text": "محصول"}])
    w = corrected["words"][0]
    assert w["w"] == "محصول"
    assert w["start"] == 0.1
    assert w["end"] == 0.6
    assert w.get("original_w") == "مخصول"


def test_undo_restores_raw(tmp_path):
    """Removing corrections via effective_transcript with no saved corrections returns raw."""
    raw = {
        "file_hash": "dig", "cache_key": "key1", "language": "fa", "duration": 2.0,
        "words": [{"w": "مخصول", "start": 0.1, "end": 0.6, "prob": 0.38}],
        "sentences": [{"text": "مخصول", "start": 0.1, "end": 0.6}],
    }
    (tmp_path / "transcript.json").write_text(json.dumps(raw, ensure_ascii=False))
    save_corrections(tmp_path, "key1", [{"index": 0, "text": "محصول"}])
    assert effective_transcript(tmp_path)["words"][0]["w"] == "محصول"

    # Overwrite corrections with empty list to simulate "undo"
    corr_path = tmp_path / "transcript_corrections" / "key1.json"
    corr_path.write_text(json.dumps({"base_key": "key1", "words": []}, ensure_ascii=False))
    assert effective_transcript(tmp_path)["words"][0]["w"] == "مخصول"


def test_captions_use_corrected_words(tmp_path):
    """After auto-correction, regenerated plan receives corrected words."""
    raw = {
        "file_hash": "dig", "cache_key": "key1", "language": "fa", "duration": 2.0,
        "words": [
            {"w": "مخصول", "start": 0.0, "end": 0.5, "prob": 0.38},
            {"w": "رو", "start": 0.6, "end": 0.8, "prob": 0.91},
        ],
        "sentences": [{"text": "مخصول رو", "start": 0.0, "end": 0.8}],
    }
    (tmp_path / "transcript.json").write_text(json.dumps(raw, ensure_ascii=False))
    save_corrections(tmp_path, "key1", [{"index": 0, "text": "محصول"}])
    t = effective_transcript(tmp_path)
    assert t["words"][0]["w"] == "محصول"
    assert t["sentences"][0]["text"] == "محصول رو"


def test_glossary_loads_from_default_path():
    """load_glossary() with no args reads presets/glossary.yaml if present."""
    glossary = load_glossary()
    # File exists in this project
    assert isinstance(glossary, dict)
    if glossary:
        assert "corrections" in glossary or "vocabulary" in glossary

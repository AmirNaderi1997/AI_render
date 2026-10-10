"""Transcript candidate and review persistence, without provider calls."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from brain.transcribe import (
    effective_transcript, file_hash, save_corrections, transcribe, transcript_key,
)
from app import jobs as jobstore
from app.jobs import Job, _run_generate
from brain.llm import LLMUsage


def _raw(key: str, digest: str) -> dict:
    return {
        "file_hash": digest, "cache_key": key, "model_size": "small",
        "language": "fa", "duration": 2.0,
        "words": [
            {"w": "مخصول", "start": 0.1, "end": 0.6, "prob": 0.4},
            {"w": "رو", "start": 0.7, "end": 0.9, "prob": 0.9},
        ],
        "sentences": [{"text": "مخصول رو", "start": 0.1, "end": 0.9}],
    }


def test_cache_key_changes_with_model_and_language():
    first = transcript_key("video", "small", "fa", "cpu", "int8")
    assert first != transcript_key("video", "medium", "fa", "cpu", "int8")
    assert first != transcript_key("video", "small", None, "cpu", "int8")
    assert first != transcript_key("video", "small", "fa", "cpu", "int8", "محصول")


def test_cache_key_accepts_missing_initial_prompt():
    assert transcript_key("video", "small", "fa", "cpu", "int8", None) == \
        transcript_key("video", "small", "fa", "cpu", "int8", "")


def test_transcribe_accepts_missing_initial_prompt(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test video data")
    result = _raw("candidate", file_hash(video))
    with patch("brain.transcribe._transcribe_whisper", return_value=result) as whisper, \
         patch.dict("os.environ", {"ELEVENLABS_API_KEY": ""}):
        transcribe(video, tmp_path, language="en", engine="whisper", initial_prompt=None)
    assert whisper.call_args.args[7] == ""


def test_missing_whisper_uses_empty_transcript_fallback(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test video data")
    import sys
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with patch("engine.probe.has_audio", return_value=True), \
         patch("engine.probe.probe_duration", return_value=2.0):
        result = transcribe(video, tmp_path, language="en", engine="whisper")
    assert result["engine"] == "none"
    assert result["words"] == []
    assert result["sentences"] == []
    assert "faster-whisper is not installed" in result["fallback_reason"]


def test_whisper_can_be_disabled_without_loading_the_runtime(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test video data")
    monkeypatch.setenv("WHISPER_ENABLED", "false")
    with patch("engine.probe.has_audio", return_value=True), \
         patch("engine.probe.probe_duration", return_value=2.0):
        result = transcribe(video, tmp_path, language="en", engine="whisper")
    assert result["engine"] == "none"
    assert result["fallback_reason"] == "Whisper skipped because WHISPER_ENABLED=false"


def test_elevenlabs_and_whisper_failures_are_both_reported(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test video data")
    with patch("brain.transcribe_elevenlabs.transcribe_elevenlabs",
               side_effect=RuntimeError("ElevenLabs key rejected")), \
         patch("brain.transcribe._transcribe_whisper",
               side_effect=RuntimeError("faster-whisper missing")), \
         patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-key"}):
        with pytest.raises(RuntimeError, match="ElevenLabs key rejected.*faster-whisper missing"):
            transcribe(video, tmp_path, language="fa", engine="elevenlabs")


def test_review_overlay_preserves_raw_and_sentences(tmp_path):
    raw = _raw("candidate-one", "digest")
    (tmp_path / "transcript.json").write_text(json.dumps(raw, ensure_ascii=False))
    corrected = save_corrections(tmp_path, "candidate-one", [{"index": 0, "text": "محصول"}])
    assert corrected["words"][0]["w"] == "محصول"
    assert corrected["words"][0]["reviewed"] is True
    assert corrected["sentences"][0]["text"] == "محصول رو"
    assert json.loads((tmp_path / "transcript.json").read_text())["words"][0]["w"] == "مخصول"
    assert effective_transcript(tmp_path)["correction_count"] == 1


def test_corrections_are_bound_to_candidate(tmp_path):
    (tmp_path / "transcript.json").write_text(json.dumps(_raw("one", "digest")))
    save_corrections(tmp_path, "one", [{"index": 0, "text": "محصول"}])
    with pytest.raises(ValueError, match="transcript changed"):
        save_corrections(tmp_path, "stale", [{"index": 0, "text": "wrong"}])
    (tmp_path / "transcript.json").write_text(json.dumps(_raw("two", "digest")))
    assert effective_transcript(tmp_path)["words"][0]["w"] == "مخصول"
    save_corrections(tmp_path, "two", [{"index": 0, "text": "محصول جدید"}])
    (tmp_path / "transcript.json").write_text(json.dumps(_raw("one", "digest")))
    assert effective_transcript(tmp_path)["words"][0]["w"] == "محصول"


def test_word_timing_correction_is_validated_and_applied(tmp_path):
    (tmp_path / "transcript.json").write_text(json.dumps(_raw("one", "digest")))
    result = save_corrections(tmp_path, "one", [
        {"index": 0, "text": "محصول", "start": 0.05, "end": 0.55}])
    assert result["words"][0]["start"] == 0.05
    assert result["words"][0]["end"] == 0.55
    with pytest.raises(ValueError, match="spoken order"):
        save_corrections(tmp_path, "one", [
            {"index": 1, "text": "رو", "start": 0.0, "end": 0.2}])


def test_cached_candidate_does_not_load_asr(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test clip")
    digest = file_hash(video)
    key = transcript_key(digest, "medium", "fa", "cpu", "int8")
    raw = _raw(key, digest)
    archive = tmp_path / "transcripts" / f"{key}.json"
    archive.parent.mkdir()
    archive.write_text(json.dumps(raw, ensure_ascii=False))
    old = _raw("old", digest)
    (tmp_path / "transcript.json").write_text(json.dumps(old, ensure_ascii=False))
    result = transcribe(video, tmp_path, model_size="medium", language="fa")
    assert result["cache_key"] == key
    assert (tmp_path / "transcripts" / "old.json").exists()
    assert json.loads((tmp_path / "transcript.json").read_text())["cache_key"] == key


def test_transcribe_only_leaves_existing_plan_untouched(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "clip.mp4").write_bytes(b"test clip")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text('{"existing": true}')
    job = Job(id="test", dir=tmp_path, raw_name="clip.mp4")
    with patch("brain.transcribe.transcribe", return_value=_raw("candidate", "digest")), \
         patch("brain.silence.detect_pauses", side_effect=AssertionError("should not plan")), \
         patch("brain.planner.generate_plan", side_effect=AssertionError("should not call LLM")):
        _run_generate(job, "rafiei_reel", "", "medium", "fa", False, True, "")
    assert job.generate.status == "done"
    assert plan_path.read_text() == '{"existing": true}'


def test_empty_transcript_builds_renderable_full_source_plan_without_llm(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "clip.mp4").write_bytes(b"test clip")
    job = Job(id="test", dir=tmp_path, raw_name="clip.mp4")
    transcript = {
        "file_hash": "digest", "cache_key": "candidate", "engine": "none",
        "language": "en", "duration": 2.0, "words": [], "sentences": [],
        "fallback_reason": "source has no audio stream",
    }
    (tmp_path / "transcript.json").write_text(json.dumps(transcript))
    with patch("brain.transcribe.transcribe", return_value=transcript), \
         patch("app.jobs.validate_plan", return_value=(object(), [])), \
         patch("brain.silence.detect_pauses", side_effect=AssertionError("should not detect pauses")), \
         patch("brain.planner.generate_plan", side_effect=AssertionError("should not call LLM")):
        _run_generate(job, "rafiei_reel", "", "small", "en", False, False, "")
    plan = job.plan_data
    assert plan is not None
    assert job.generate.status == "done"
    assert plan["segments"] == [{"id": "s1", "in": 0.0, "out": 2.0}]
    assert plan["captions"] == []


def test_missing_provider_builds_and_persists_local_plan(tmp_path, media_dir):
    (tmp_path / "raw").mkdir()
    video = tmp_path / "raw" / "clip.mp4"
    video.write_bytes((media_dir / "raw.mp4").read_bytes())
    transcript = _raw("candidate", file_hash(video))
    transcript["duration"] = 12.0
    (tmp_path / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False))
    job = Job(id="test", dir=tmp_path, raw_name="clip.mp4")

    with patch("brain.llm.provider_configured", return_value=False), \
         patch("brain.silence.detect_pauses", return_value={"keep": [(0.0, 2.0)], "remove": []}), \
         patch("brain.planner.generate_plan", side_effect=AssertionError("should not call LLM")), \
         patch("app.jobs._write_status", wraps=jobstore._write_status) as persist:
        _run_generate(job, "rafiei_reel", "", None, "fa", True, False, "", raise_errors=True)

    assert job.generate.status == "done"
    assert job.generate.message == "plan generated locally (no external provider)"
    assert job.generate.cost_usd == 0
    assert job.plan_data is not None
    assert job.plan_data["source"] == "raw/clip.mp4"
    assert job.plan_data["segments"] == [{"id": "s1", "in": 0.0, "out": 12.0}]
    assert job.plan_data["captions"] == []
    assert job.plan_data["sfx"] == []
    assert job.plan_data["generation_meta"] == {
        "provider": "local",
        "fallback_reason": "no external LLM provider configured",
    }
    assert persist.call_args.args[0].plan_data == job.plan_data


def test_unreachable_provider_falls_back_to_local_plan(tmp_path, media_dir):
    (tmp_path / "raw").mkdir()
    video = tmp_path / "raw" / "clip.mp4"
    video.write_bytes((media_dir / "raw.mp4").read_bytes())
    transcript = _raw("candidate", file_hash(video))
    transcript["duration"] = 12.0
    (tmp_path / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False))
    job = Job(id="test", dir=tmp_path, raw_name="clip.mp4")

    with patch("brain.llm.provider_configured", return_value=True), \
         patch("brain.silence.detect_pauses", return_value={"keep": [(0.0, 2.0)], "remove": []}), \
         patch("brain.planner.generate_plan", side_effect=ConnectionError("provider offline")):
        _run_generate(job, "rafiei_reel", "", None, "fa", True, False, "", raise_errors=True)

    assert job.generate.status == "done"
    assert job.plan_data is not None
    assert job.plan_data["segments"] == [{"id": "s1", "in": 0.0, "out": 12.0}]
    assert job.plan_data["generation_meta"]["provider"] == "local"
    assert "provider offline" in job.plan_data["generation_meta"]["fallback_reason"]


def test_regeneration_passes_reviewed_words_to_planner(tmp_path):
    (tmp_path / "raw").mkdir()
    video = tmp_path / "raw" / "clip.mp4"
    video.write_bytes(b"test clip")
    raw = _raw("candidate", file_hash(video))
    (tmp_path / "transcript.json").write_text(json.dumps(raw, ensure_ascii=False))
    save_corrections(tmp_path, "candidate", [{"index": 0, "text": "محصول"}])
    job = Job(id="test", dir=tmp_path, raw_name="clip.mp4")
    with patch("brain.silence.detect_pauses", return_value={"keep": [(0.0, 1.0)], "remove": []}), \
         patch("brain.llm.provider_configured", return_value=True), \
         patch("brain.planner.generate_plan", return_value=({"version": "0.2"}, LLMUsage())) as planner:
        _run_generate(job, "rafiei_reel", "", None, "fa", True, False, "")
    assert job.generate.status == "done"
    assert planner.call_args.kwargs["transcript"]["words"][0]["w"] == "محصول"

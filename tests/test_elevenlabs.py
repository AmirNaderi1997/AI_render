"""Tests for ElevenLabs Scribe v2 transcription engine (mocked)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from brain.transcribe import choose_engine, file_hash, transcribe
from brain.transcribe_elevenlabs import _map_response, _cache_key


def _fake_word(text, start, end, logprob=-0.1, wtype="word"):
    return SimpleNamespace(text=text, start=start, end=end, logprob=logprob, type=wtype)


def _fake_response(words, lang="fa", duration=5.0):
    resp = SimpleNamespace(
        words=words,
        language_code=lang,
        language_probability=0.98,
        text=" ".join(w.text for w in words if w.type == "word"),
        audio_duration_secs=duration,
    )
    return resp


class TestMapping:
    def test_maps_words_to_transcript_format(self):
        words = [
            _fake_word("سلام", 0.1, 0.5, -0.05),
            _fake_word("دنیا", 0.6, 1.0, -0.2),
        ]
        resp = _fake_response(words)
        result = _map_response(resp, "abc123", "key1", "fa", 5.0)

        assert len(result["words"]) == 2
        assert result["words"][0]["w"] == "سلام"
        assert result["words"][0]["start"] == 0.1
        assert result["words"][0]["end"] == 0.5
        assert "prob" in result["words"][0]
        assert result["engine"] == "elevenlabs"
        assert result["file_hash"] == "abc123"
        assert result["cache_key"] == "key1"
        assert len(result["sentences"]) == 1

    def test_persian_normalization(self):
        words = [_fake_word("يك", 0.0, 0.5)]  # Arabic ي ك
        resp = _fake_response(words)
        result = _map_response(resp, "h", "k", "fa", 1.0)
        assert result["words"][0]["w"] == "یک"  # Persian ی ک


class TestSpacingDropped:
    def test_spacing_tokens_are_dropped(self):
        words = [
            _fake_word("سلام", 0.1, 0.5),
            _fake_word(" ", 0.5, 0.6, wtype="spacing"),
            _fake_word("دنیا", 0.6, 1.0),
        ]
        resp = _fake_response(words)
        result = _map_response(resp, "h", "k", "fa", 2.0)
        assert len(result["words"]) == 2
        assert all(w["w"].strip() for w in result["words"])

    def test_audio_event_tokens_are_dropped(self):
        words = [
            _fake_word("(laughter)", 0.0, 0.3, wtype="audio_event"),
            _fake_word("سلام", 0.4, 0.8),
        ]
        resp = _fake_response(words)
        result = _map_response(resp, "h", "k", "fa", 1.0)
        assert len(result["words"]) == 1


class TestCacheHit:
    def test_cache_hit_skips_api_call(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"test video data")
        digest = file_hash(video)
        key = _cache_key(digest, "fa", "scribe_v2")

        cached = {
            "file_hash": digest, "cache_key": key, "engine": "elevenlabs",
            "model_id": "scribe_v2", "requested_language": "fa",
            "language": "fa", "duration": 3.0,
            "words": [{"w": "سلام", "start": 0.1, "end": 0.5, "prob": 0.9}],
            "sentences": [{"text": "سلام", "start": 0.1, "end": 0.5}],
        }
        archive = tmp_path / "transcripts" / f"{key}.json"
        archive.parent.mkdir()
        archive.write_text(json.dumps(cached, ensure_ascii=False))
        (tmp_path / "transcript.json").write_text(json.dumps(cached, ensure_ascii=False))

        with patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-key"}):
            result = transcribe(video, tmp_path, language="fa", engine="elevenlabs")

        assert result["cache_key"] == key


class TestFallbackOnError:
    def test_falls_back_to_whisper_on_elevenlabs_error(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"test video data")
        digest = file_hash(video)

        whisper_result = {
            "file_hash": digest, "cache_key": "whisper-key", "engine": "whisper",
            "model_size": "medium", "requested_language": "fa",
            "language": "fa", "duration": 3.0,
            "words": [{"w": "سلام", "start": 0.1, "end": 0.5, "prob": 0.8}],
            "sentences": [{"text": "سلام", "start": 0.1, "end": 0.5}],
        }
        (tmp_path / "transcript.json").write_text(json.dumps(whisper_result, ensure_ascii=False))

        with patch("brain.transcribe_elevenlabs.transcribe_elevenlabs",
                    side_effect=RuntimeError("API down")), \
             patch("brain.transcribe._transcribe_whisper", return_value=whisper_result) as mock_w, \
             patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-key"}):
            result = transcribe(video, tmp_path, language="fa", engine="elevenlabs")

        mock_w.assert_called_once()
        assert result["engine"] == "whisper"
        assert result["fallback_from"] == "elevenlabs"
        assert "API down" in result["fallback_reason"]
        persisted = json.loads((tmp_path / "transcript.json").read_text())
        assert persisted["fallback_from"] == "elevenlabs"


class TestChooseEngine:
    def test_explicit_engine(self):
        assert choose_engine("fa", "whisper") == "whisper"
        assert choose_engine("en", "elevenlabs") == "elevenlabs"

    def test_env_var(self):
        with patch.dict("os.environ", {"ASR_ENGINE": "elevenlabs"}):
            assert choose_engine("en") == "elevenlabs"

    def test_fa_with_key_defaults_to_elevenlabs(self):
        with patch.dict("os.environ", {"ELEVENLABS_API_KEY": "k"}, clear=False):
            assert choose_engine("fa") == "elevenlabs"

    def test_fa_without_key_defaults_to_whisper(self):
        import os
        env = {k: v for k, v in os.environ.items()
               if k not in ("ELEVENLABS_API_KEY", "ASR_ENGINE")}
        with patch.dict("os.environ", env, clear=True):
            assert choose_engine("fa") == "whisper"

    def test_en_defaults_to_whisper(self):
        import os
        env = {k: v for k, v in os.environ.items()
               if k not in ("ELEVENLABS_API_KEY", "ASR_ENGINE")}
        with patch.dict("os.environ", env, clear=True):
            assert choose_engine("en") == "whisper"

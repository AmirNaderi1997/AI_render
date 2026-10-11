"""Sarovi voice request and returned-format checks."""
import base64
import json
from pathlib import Path

import pytest

from brain import sarovi_voice
from brain.content_creator import _voice_provider


def test_sarovi_persian_voice_saves_returned_wav(tmp_path, monkeypatch):
    monkeypatch.setenv("SAROVI_API_KEY", "private-test-key")
    monkeypatch.delenv("SAROVI_TTS_VOICE", raising=False)
    seen = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False

    def fake_open(request, timeout):
        seen["body"] = json.loads(request.data)
        seen["authorization"] = request.get_header("Authorization")
        return Response()

    monkeypatch.setattr(sarovi_voice.urllib.request, "urlopen", fake_open)
    monkeypatch.setattr(sarovi_voice.json, "load", lambda _: {
        "output": {"data": base64.b64encode(b"wav-audio").decode(), "mediaType": "audio/wav"}
    })
    monkeypatch.setattr(sarovi_voice, "_get_audio_duration", lambda _: 2.5)
    result = sarovi_voice.generate_narration("سلام", tmp_path)
    assert Path(result.file_path).suffix == ".wav"
    assert Path(result.file_path).read_bytes() == b"wav-audio"
    assert result.duration_s == 2.5
    assert seen["body"]["model"] == sarovi_voice.DEFAULT_MODEL
    assert seen["body"]["voice"] == "Aoede"
    assert seen["authorization"] == "Bearer private-test-key"


def test_sarovi_voice_rejects_unplayable_output(tmp_path, monkeypatch):
    monkeypatch.setenv("SAROVI_API_KEY", "private-test-key")
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
    monkeypatch.setattr(sarovi_voice.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(sarovi_voice.json, "load", lambda _: {
        "output": {"data": base64.b64encode(b"bad").decode(), "mediaType": "audio/wav"}
    })
    monkeypatch.setattr(sarovi_voice, "_get_audio_duration", lambda _: 0)
    with pytest.raises(RuntimeError, match="playable duration"):
        sarovi_voice.generate_narration("سلام", tmp_path)
    assert not list(tmp_path.iterdir())


def test_voice_provider_defaults_to_edge_and_allows_sarovi(monkeypatch):
    from app.config import settings
    monkeypatch.delenv("CONTENT_TTS_PROVIDER", raising=False)
    monkeypatch.setattr(settings, "CONTENT_TTS_PROVIDER", "")
    monkeypatch.setenv("SAROVI_API_KEY", "configured")
    monkeypatch.delenv("CONTENT_VOICE_PROVIDER", raising=False)
    assert _voice_provider() == "edge"
    monkeypatch.setenv("CONTENT_VOICE_PROVIDER", "sarovi")
    assert _voice_provider() == "sarovi"
    monkeypatch.setenv("CONTENT_VOICE_PROVIDER", "edge")
    assert _voice_provider() == "edge"
    monkeypatch.delenv("SAROVI_API_KEY")
    monkeypatch.setenv("CONTENT_VOICE_PROVIDER", "auto")
    assert _voice_provider() == "edge"


def test_content_tts_provider_prefers_elevenlabs_override(monkeypatch):
    monkeypatch.setenv("TTS_PROVIDER", "edge-tts")
    monkeypatch.setenv("CONTENT_VOICE_PROVIDER", "edge")
    monkeypatch.setenv("CONTENT_TTS_PROVIDER", "elevenlabs")
    assert _voice_provider() == "elevenlabs"

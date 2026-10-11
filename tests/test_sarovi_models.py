"""Sarovi contract checks for plan JSON and generated image artifacts."""
import base64
import io
import json

from PIL import Image


def test_sarovi_plan_request_uses_responses_contract(monkeypatch):
    from brain import llm
    from app.config import settings

    seen = {}

    def fake_request(path, payload, *, timeout):
        seen.update(path=path, payload=payload, timeout=timeout)
        return {"model": payload["model"], "output_text": '{"scenes": []}',
                "usage": {"input_tokens": 3, "output_tokens": 4}}

    monkeypatch.setattr(settings, "SAROVI_LLM_MODEL", "anthropic/test-model")
    monkeypatch.setattr("brain.sarovi.request", fake_request)
    plan, usage = llm.chat_json(
        "Return JSON",
        "Plan a reel",
        max_tokens=500,
        provider="sarovi",
    )
    assert plan == {"scenes": []}
    assert usage.output_tokens == 4
    assert seen["path"] == "/responses"
    assert seen["payload"] == {
        "model": "anthropic/test-model", "instructions": "Return JSON",
        "input": "Plan a reel", "max_output_tokens": 500,
    }


def test_sarovi_response_reads_nested_responses_api_output():
    from brain.sarovi import response_output_text

    result = {
        "output": [{
            "type": "message",
            "content": [{"type": "output_text", "text": '{"ok":true}'}],
        }],
    }
    assert response_output_text(result) == '{"ok":true}'


def test_sarovi_image_provider_saves_valid_image(monkeypatch, tmp_path):
    from brain.media_provider import get_provider

    image = Image.new("RGB", (32, 48), "red")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    seen = {}

    def fake_request(path, payload, *, timeout=300):
        seen.update(path=path, payload=payload)
        return {"generationId": "sample-id", "outputs": [{
            "mediaType": "image/png", "data": base64.b64encode(buffer.getvalue()).decode(),
        }]}

    monkeypatch.setenv("SAROVI_API_KEY", "test-key")
    monkeypatch.setattr("brain.sarovi.request", fake_request)
    provider = get_provider("sarovi_nano_banana")
    result = provider.generate_image("A red object on a table", "9:16", tmp_path)
    assert result.source == "sarovi_nano_banana"
    assert (result.width, result.height) == (32, 48)
    assert Image.open(result.file_path).size == (32, 48)
    assert seen["path"] == "/studio/image"
    assert seen["payload"]["model"] == "google/gemini-2.5-flash-image"
    assert seen["payload"]["aspectRatio"] == "9:16"


def test_sarovi_image_provider_rejects_invalid_media(monkeypatch, tmp_path):
    import pytest
    from brain.media_provider import get_provider

    monkeypatch.setattr("brain.sarovi.request", lambda *_args, **_kwargs: {
        "outputs": [{"mediaType": "image/png", "data": "invalid"}],
    })
    with pytest.raises(RuntimeError, match="invalid image"):
        get_provider("sarovi_seedream").generate_image("A mountain landscape", "1:1", tmp_path)
    assert not list(tmp_path.iterdir())


def test_seedream_upstream_reference_error_falls_back_to_nano(monkeypatch, tmp_path):
    from brain.media_provider import get_provider

    image = Image.new("RGB", (16, 16), "blue")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    models = []

    def fake_request(_path, payload, **_kwargs):
        models.append(payload["model"])
        if len(models) == 1:
            raise RuntimeError("Sarovi request failed (HTTP 502: INVALID_REFERENCE)")
        return {"outputs": [{"mediaType": "image/png",
                              "data": base64.b64encode(buffer.getvalue()).decode()}]}

    monkeypatch.setattr("brain.sarovi.request", fake_request)
    result = get_provider("sarovi_seedream").generate_image("A blue sky", "1:1", tmp_path)
    assert models == ["bytedance-seed/seedream-5-0-lite", "google/gemini-2.5-flash-image"]
    assert result.metadata["fallback_used"] is True
    assert result.metadata["model"] == models[-1]

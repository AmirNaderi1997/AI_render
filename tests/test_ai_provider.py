from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from brain.ai_provider import (
    JarvisProvider,
    LocalFallbackProvider,
    SaroviProvider,
    get_provider,
    provider_status,
)
from brain.storyboard import generate_storyboard
from brain.planner import generate_plan
from app.config import Settings, settings


def _plan_context() -> dict:
    return {
        "duration": 4.0,
        "source_rel": "raw/clip.mp4",
        "preset_name": "rafiei_reel",
        "output_kind": "reel",
        "system_prompt": "Return JSON",
        "user_prompt": "Build a plan",
    }


def test_factory_selects_only_configured_jarvis_sarovi_or_local(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "jarvis")
    monkeypatch.setenv("JARVIS_API_KEY", "jarvis-key")
    assert isinstance(get_provider(), JarvisProvider)

    monkeypatch.setenv("LLM_PROVIDER", "sarovi")
    monkeypatch.setenv("SAROVI_API_KEY", "sarovi-key")
    assert isinstance(get_provider(), SaroviProvider)

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    assert isinstance(get_provider(), LocalFallbackProvider)


def test_local_plan_and_storyboard_are_editable_templates(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "jarvis")
    monkeypatch.setenv("JARVIS_API_KEY", "")
    provider = get_provider()
    plan, plan_usage = provider.generate_plan(_plan_context(), {"duration": 4.0})
    assert plan["generation_meta"]["provider"] == "local"
    assert plan["segments"] == [{"id": "s1", "in": 0.0, "out": 4.0}]
    assert plan_usage.model == "local_template"

    with patch("brain.storyboard.get_provider", return_value=provider):
        storyboard = generate_storyboard("Explain a useful habit", "reel", "en")
    assert storyboard.is_fallback is True
    assert [scene.description for scene in storyboard.scenes] == ["Intro", "Main point", "Outro"]


def test_local_plan_keeps_timestamped_transcript_as_renderable_captions():
    transcript = {
        "duration": 8.0,
        "words": [
            {"w": "سلام", "start": 0.1, "end": 0.5},
            {"w": "این", "start": 0.6, "end": 0.9},
            {"w": "یک", "start": 1.0, "end": 1.2},
            {"w": "تست", "start": 1.3, "end": 1.7},
            {"w": "است", "start": 1.8, "end": 2.1},
            {"w": "دوم", "start": 3.2, "end": 3.6},
            {"w": "موفق.", "start": 3.7, "end": 4.2},
        ],
    }
    plan, _ = LocalFallbackProvider("offline").generate_plan(_plan_context(), transcript)

    assert plan["captions"] == [
        {"start": 0.1, "end": 2.1, "text": "سلام این یک تست است", "style": "emphasis"},
        {"start": 3.2, "end": 4.0, "text": "دوم موفق.", "style": "cta"},
    ]


def test_planner_uses_factory_local_fallback_without_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "jarvis")
    monkeypatch.setenv("JARVIS_API_KEY", "")
    transcript = {
        "language": "en",
        "duration": 4.0,
        "words": [{"w": "hello", "start": 0.0, "end": 0.5}],
        "sentences": [{"text": "hello", "start": 0.0, "end": 0.5}],
    }
    plan, usage = generate_plan(
        job_dir=tmp_path,
        transcript=transcript,
        keep_ranges=[(0.0, 4.0)],
        remove_ranges=[],
        source_rel="raw/clip.mp4",
    )
    assert plan["generation_meta"]["provider"] == "local"
    assert plan["segments"] == [{"id": "s1", "in": 0.0, "out": 4.0}]
    assert usage.model == "local_template"


def test_jarvis_calls_configured_chat_completions_endpoint(monkeypatch):
    monkeypatch.setenv("JARVIS_API_KEY", "secret")
    monkeypatch.setenv("JARVIS_API_URL", "https://jarvis.example/v1")
    monkeypatch.setenv("JARVIS_MODEL", "jarvis-model")
    response = {
        "model": "jarvis-model",
        "choices": [{"message": {"content": '{"version":"0.1"}'}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }
    with patch("brain.ai_provider._post_json", return_value=response) as post:
        result, usage = JarvisProvider().generate_plan(_plan_context(), {})
    assert result == {"version": "0.1"}
    assert usage.model == "jarvis-model"
    assert post.call_args.args[0] == "https://jarvis.example/v1/chat/completions"
    assert post.call_args.args[1]["model"] == "jarvis-model"
    assert post.call_args.args[3] == 60.0


def test_jarvis_does_not_inherit_sarovi_text_model(monkeypatch):
    monkeypatch.setenv("JARVIS_API_KEY", "secret")
    monkeypatch.setenv("JARVIS_MODEL", "")
    monkeypatch.setenv("LLM_MODEL", "sarovi-only-model")
    assert JarvisProvider().model == "DEEPSEEK_V4_FLASH"


def test_default_llm_model_and_providers_read_settings(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("JARVIS_MODEL", raising=False)
    assert Settings(_env_file=None).LLM_MODEL == "CLAUDE_SONNET_5_5"

    monkeypatch.setattr(settings, "JARVIS_MODEL", "jarvis-model-from-settings")
    monkeypatch.setattr(settings, "LLM_MODEL", "sarovi-model-from-settings")
    assert JarvisProvider().model == settings.JARVIS_MODEL
    assert SaroviProvider().model == settings.LLM_MODEL


def test_sarovi_connection_failure_falls_back_without_exposing_key(monkeypatch, caplog):
    monkeypatch.setenv("SAROVI_API_KEY", "super-secret")
    monkeypatch.setenv("SAROVI_API_URL", "https://sarovi.example/v1")
    with patch("brain.ai_provider._post_json", side_effect=ConnectionError("offline")):
        plan, usage = SaroviProvider().generate_plan(_plan_context(), {"duration": 4.0})
    assert plan["generation_meta"]["provider"] == "local"
    assert "offline" in plan["generation_meta"]["fallback_reason"]
    assert usage.model == "local_template"
    assert "super-secret" not in caplog.text


def test_jarvis_connection_failure_uses_configured_sarovi_before_local(monkeypatch):
    monkeypatch.setenv("JARVIS_API_KEY", "jarvis-secret")
    monkeypatch.setenv("SAROVI_API_KEY", "sarovi-secret")
    expected = {"version": "0.3", "segments": [{"id": "s1"}]}
    with patch.object(JarvisProvider, "_chat_json", side_effect=ConnectionError("offline")), \
         patch.object(SaroviProvider, "_responses_json", return_value=(expected, SimpleNamespace(
             input_tokens=2, output_tokens=3, model="sarovi-model", elapsed_sec=0.1,
             cost_estimate=0.0,
         ))) as sarovi:
        plan, usage = JarvisProvider().generate_plan(_plan_context(), {"duration": 4.0})

    sarovi.assert_called_once_with("Return JSON", "Build a plan")
    assert plan == expected
    assert usage.model == "sarovi-model"


def test_timeout_uses_configured_ai_timeout(monkeypatch):
    monkeypatch.setenv("JARVIS_API_KEY", "secret")
    monkeypatch.setenv("AI_TIMEOUT_SECONDS", "17")
    response = {"choices": [{"message": {"content": '{"ok":true}'}}]}
    with patch("brain.ai_provider._post_json", return_value=response) as post:
        JarvisProvider().generate_plan(_plan_context(), {})
    assert post.call_args.args[3] == 17.0


def test_status_reports_provider_without_credentials(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "jarvis")
    monkeypatch.setenv("JARVIS_API_KEY", "top-secret")
    monkeypatch.setenv("JARVIS_MODEL", "model-a")
    status = provider_status()
    assert status == {"provider": "jarvis", "configured": True, "model": "model-a"}
    assert "top-secret" not in repr(status)

    monkeypatch.setenv("JARVIS_API_KEY", "")
    assert provider_status() == {
        "provider": "local", "configured": True, "message": "Using local templates"
    }


def test_ai_status_route_is_registered():
    from app.main import app

    assert "/api/ai/status" in app.openapi()["paths"]

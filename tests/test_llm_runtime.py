"""Runtime bounds for hosted LLM calls used by background generation jobs."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from brain.llm import _provider_timeout_seconds, chat_json


def test_openai_compatible_calls_use_a_bounded_timeout_without_sdk_retries():
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )
    with patch.dict("os.environ", {
        "LLM_PROVIDER": "jarvis",
        "JARVIS_API_KEY": "test-key",
        "JARVIS_BASE_URL": "https://example.invalid/v1",
        "AI_PROVIDER_TIMEOUT_SECONDS": "37",
    }, clear=True), patch("openai.OpenAI", return_value=client) as constructor:
        result, _usage = chat_json("system", "user", model="test-model", timeout_seconds=21)

    assert result == {"ok": True}
    constructor.assert_called_once_with(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        timeout=21.0,
        max_retries=0,
    )


def test_provider_timeout_has_safe_default_and_upper_bound():
    with patch.dict("os.environ", {}, clear=True):
        assert _provider_timeout_seconds() == 300.0
    with patch.dict("os.environ", {"AI_PROVIDER_TIMEOUT_SECONDS": "invalid"}, clear=True):
        assert _provider_timeout_seconds() == 300.0
    with patch.dict("os.environ", {"AI_PROVIDER_TIMEOUT_SECONDS": "999999"}, clear=True):
        assert _provider_timeout_seconds() == 600.0


def test_timeout_override_has_same_safety_bounds_as_environment_value():
    with patch.dict("os.environ", {"AI_PROVIDER_TIMEOUT_SECONDS": "37"}, clear=True):
        assert _provider_timeout_seconds(12) == 12.0
        assert _provider_timeout_seconds(999999) == 600.0
        assert _provider_timeout_seconds(-1) == 37.0

import logging

import pytest

from hermes import main


def test_short_token_key_raises_only_for_explicit_production(monkeypatch):
    monkeypatch.setattr(main, "enforce_production_config", True)
    monkeypatch.setattr(main.settings, "HERMES_TOKEN_KEY", "short")

    with pytest.raises(RuntimeError, match="at least 32 characters in production"):
        main._ensure_token_key()


def test_short_token_key_gets_random_development_fallback(monkeypatch, caplog):
    monkeypatch.setattr(main, "enforce_production_config", False)
    monkeypatch.setattr(main.settings, "HERMES_TOKEN_KEY", "short")

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        main._ensure_token_key()

    assert len(main.settings.HERMES_TOKEN_KEY) == 32
    assert main.settings.HERMES_TOKEN_KEY != "short"
    assert "random session-only development key" in caplog.text


def test_valid_token_key_is_preserved(monkeypatch):
    token_key = "x" * 32
    monkeypatch.setattr(main, "enforce_production_config", False)
    monkeypatch.setattr(main.settings, "HERMES_TOKEN_KEY", token_key)

    main._ensure_token_key()

    assert main.settings.HERMES_TOKEN_KEY == token_key

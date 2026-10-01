"""Provider-agnostic LLM client.

Chosen by env vars: LLM_PROVIDER (anthropic|openai|openai_compatible|jarvis),
LLM_MODEL, and the corresponding API key. Default: anthropic + claude-sonnet-5-5.

The "jarvis" provider is a preset for "openai_compatible" that reads
JARVIS_API_KEY and JARVIS_BASE_URL from the environment.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# Pricing per 1M tokens (input, output) — approximate
_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    elapsed_sec: float = 0.0

    @property
    def cost_estimate(self) -> float:
        inp_price, out_price = _PRICING.get(self.model, (3.0, 15.0))
        return (self.input_tokens * inp_price + self.output_tokens * out_price) / 1_000_000


def _provider() -> str:
    return os.getenv("LLM_PROVIDER", "anthropic").lower()


def _model() -> str:
    return os.getenv("LLM_MODEL", "claude-sonnet-5-5")


def chat_json(
    system: str,
    user: str,
    *,
    model: Optional[str] = None,
    max_tokens: int = 16000,
    temperature: float = 0.0,
) -> tuple[dict, LLMUsage]:
    """Send a single-turn request expecting a JSON response.

    Returns (parsed_json, usage).
    """
    provider = _provider()
    model = model or _model()

    t0 = time.monotonic()

    if provider == "anthropic":
        return _anthropic_call(system, user, model, max_tokens)
    elif provider == "openai":
        return _openai_call(system, user, model, max_tokens, temperature)
    elif provider in ("openai_compatible", "jarvis"):
        return _openai_compatible_call(
            system, user, model, max_tokens, temperature, preset=provider,
        )
    else:
        raise ValueError(f"unsupported LLM_PROVIDER={provider!r}")


def _anthropic_call(
    system: str, user: str, model: str, max_tokens: int,
) -> tuple[dict, LLMUsage]:
    import anthropic

    client = anthropic.Anthropic()
    t0 = time.monotonic()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    text = ""
    for block in response.content:
        if block.type == "text":
            text += block.text

    usage = LLMUsage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        model=model,
        elapsed_sec=round(time.monotonic() - t0, 2),
    )
    log.info(
        "LLM %s: %d in / %d out tokens, ~$%.4f, %.1fs",
        model, usage.input_tokens, usage.output_tokens,
        usage.cost_estimate, usage.elapsed_sec,
    )

    parsed = _extract_json(text)
    return parsed, usage


def _openai_call(
    system: str, user: str, model: str, max_tokens: int, temperature: float,
) -> tuple[dict, LLMUsage]:
    from openai import OpenAI

    client = OpenAI()
    t0 = time.monotonic()
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )

    text = response.choices[0].message.content or ""
    usage = LLMUsage(
        input_tokens=response.usage.prompt_tokens if response.usage else 0,
        output_tokens=response.usage.completion_tokens if response.usage else 0,
        model=model,
        elapsed_sec=round(time.monotonic() - t0, 2),
    )
    log.info(
        "LLM %s: %d in / %d out tokens, ~$%.4f, %.1fs",
        model, usage.input_tokens, usage.output_tokens,
        usage.cost_estimate, usage.elapsed_sec,
    )

    parsed = _extract_json(text)
    return parsed, usage


def _getenv_ci(name: str) -> str | None:
    """Case-insensitive env var lookup."""
    val = os.getenv(name)
    if val:
        return val
    lower = name.lower()
    for k, v in os.environ.items():
        if k.lower() == lower:
            return v
    return None


_PRESETS: dict[str, tuple[str, str]] = {
    "jarvis": ("JARVIS_API_KEY", "JARVIS_BASE_URL"),
}


def _openai_compatible_call(
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    temperature: float,
    preset: str = "openai_compatible",
) -> tuple[dict, LLMUsage]:
    from openai import OpenAI

    if preset in _PRESETS:
        key_env, url_env = _PRESETS[preset]
    else:
        key_env, url_env = "LLM_API_KEY", "LLM_BASE_URL"

    api_key = _getenv_ci(key_env)
    base_url = _getenv_ci(url_env)
    if not api_key:
        raise ValueError(f"{key_env} not set")
    if not base_url:
        raise ValueError(f"{url_env} not set")

    client = OpenAI(api_key=api_key, base_url=base_url)
    t0 = time.monotonic()
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )

    text = response.choices[0].message.content or ""
    usage = LLMUsage(
        input_tokens=response.usage.prompt_tokens if response.usage else 0,
        output_tokens=response.usage.completion_tokens if response.usage else 0,
        model=model,
        elapsed_sec=round(time.monotonic() - t0, 2),
    )
    log.info(
        "LLM %s (%s): %d in / %d out tokens, ~$%.4f, %.1fs",
        model, preset, usage.input_tokens, usage.output_tokens,
        usage.cost_estimate, usage.elapsed_sec,
    )

    parsed = _extract_json(text)
    return parsed, usage


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # drop ```json
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)

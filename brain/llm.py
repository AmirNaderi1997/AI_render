"""Provider-agnostic LLM client.

Chosen by env vars: LLM_PROVIDER (anthropic|openai), LLM_MODEL, and the
corresponding API key. Default: anthropic + claude-sonnet-5-5.
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

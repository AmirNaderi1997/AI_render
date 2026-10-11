"""Provider-agnostic LLM client.

Chosen by env vars:
  LLM_PROVIDER   (anthropic|openai|openai_compatible|jarvis|sarovi) – default: anthropic
  LLM_MODEL      – text/plan model                            – default: CLAUDE_SONNET_5_5
  VISION_PROVIDER (anthropic|openai|openai_compatible|jarvis) – default: same as LLM_PROVIDER
  VISION_MODEL   – image-capable model (content gen/editing/hints) – default: gpt-5-5-image

The "jarvis" provider is a preset for "openai_compatible" that reads
JARVIS_API_KEY and JARVIS_BASE_URL from the environment.

Two top-level functions:
  chat_json()    → text/JSON plan generation      uses LLM_PROVIDER + LLM_MODEL
  chat_vision()  → image + text content analysis  uses VISION_PROVIDER + VISION_MODEL
"""
from __future__ import annotations

import base64
import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from app.config import settings

log = logging.getLogger(__name__)

_DEFAULT_PROVIDER_TIMEOUT_SECONDS = 300.0
_MAX_PROVIDER_TIMEOUT_SECONDS = 600.0


def _provider_timeout_seconds(override: float | None = None) -> float:
    """Bound hosted model calls so a background job cannot wait indefinitely."""
    try:
        configured_timeout = float(settings.AI_PROVIDER_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        configured_timeout = _DEFAULT_PROVIDER_TIMEOUT_SECONDS
    if not math.isfinite(configured_timeout) or configured_timeout <= 0:
        configured_timeout = _DEFAULT_PROVIDER_TIMEOUT_SECONDS
    fallback = min(configured_timeout, _MAX_PROVIDER_TIMEOUT_SECONDS)
    if override is None:
        return fallback
    try:
        timeout = float(override)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(timeout) or timeout <= 0:
        return fallback
    return min(timeout, _MAX_PROVIDER_TIMEOUT_SECONDS)

# Pricing per 1M tokens (input, output) — approximate
_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "anthropic/claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-5-5-image": (5.00, 20.00),
    "DEEPSEEK_V4_FLASH": (0.10, 0.30),
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


# ── env helpers ──────────────────────────────────────────────────────────────

def _getenv_ci(name: str) -> str | None:
    """Case-insensitive env var lookup."""
    value = getattr(settings, name, None)
    return value if isinstance(value, str) and value else None


def _provider() -> str:
    return settings.LLM_PROVIDER.lower()


def _model(provider: str | None = None) -> str:
    if (provider or _provider()) == "sarovi":
        return _getenv_ci("SAROVI_LLM_MODEL") or settings.SAROVI_LLM_MODEL
    return _getenv_ci("LLM_MODEL") or settings.LLM_MODEL


def _vision_provider() -> str:
    return (settings.VISION_PROVIDER or _provider()).lower()


def _vision_model() -> str:
    return settings.VISION_MODEL


_PRESETS: dict[str, tuple[str, str]] = {
    "jarvis": ("JARVIS_API_KEY", "JARVIS_BASE_URL"),
}


def provider_configured() -> bool:
    """True when the selected text-LLM provider has the credentials it needs."""
    provider = _provider()
    if provider == "anthropic":
        return bool(_getenv_ci("ANTHROPIC_API_KEY"))
    if provider == "sarovi":
        return bool(_getenv_ci("SAROVI_API_KEY"))
    if provider in ("openai", "openai_compatible", "jarvis"):
        try:
            _resolve_preset(provider)
        except ValueError:
            return False
        return True
    return False


# ── plan/text model ───────────────────────────────────────────────────────────

def chat_json(
    system: str,
    user: str,
    *,
    model: Optional[str] = None,
    max_tokens: int = 16000,
    temperature: float = 0.0,
    timeout_seconds: Optional[float] = None,
    provider: Optional[str] = None,
) -> tuple[dict, LLMUsage]:
    """Send a single-turn request expecting a JSON response.

    Uses LLM_PROVIDER + LLM_MODEL (default: CLAUDE_SONNET_5_5).
    Returns (parsed_json, usage).
    """
    provider = (provider or _provider()).lower()
    model = model or _model(provider)
    t0 = time.monotonic()

    if provider == "anthropic":
        return _anthropic_call(system, user, model, max_tokens, timeout_seconds)
    elif provider == "openai":
        return _openai_call(system, user, model, max_tokens, temperature, timeout_seconds)
    elif provider == "sarovi":
        return _sarovi_call(system, user, model, max_tokens, timeout_seconds)
    elif provider in ("openai_compatible", "jarvis"):
        return _openai_compatible_call(
            system, user, model, max_tokens, temperature, preset=provider,
            timeout_seconds=timeout_seconds,
        )
    else:
        raise ValueError(f"unsupported LLM_PROVIDER={provider!r}")


def _sarovi_call(
    system: str, user: str, model: str, max_tokens: int,
    timeout_seconds: Optional[float] = None,
) -> tuple[dict, LLMUsage]:
    from .sarovi import request

    if len(system) > 12000:
        raise ValueError("Sarovi instructions exceed its 12000-character limit")
    if len(user) > 96000:
        raise ValueError("Sarovi input exceeds its 96000-character limit")
    t0 = time.monotonic()
    result = request("/responses", {
        "model": model,
        "instructions": system,
        "input": user,
        "max_output_tokens": max(128, min(max_tokens, 32768)),
    }, timeout=_provider_timeout_seconds(timeout_seconds))
    from .sarovi import response_output_text
    text = response_output_text(result)
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Sarovi returned no text")
    reported = result.get("usage") or {}
    usage = LLMUsage(
        input_tokens=reported.get("input_tokens", 0),
        output_tokens=reported.get("output_tokens", 0),
        model=result.get("model", model),
        elapsed_sec=round(time.monotonic() - t0, 2),
    )
    _log_usage(usage, provider="sarovi", call_type="text")
    return _extract_json(text), usage


# ── vision / content-analysis model ──────────────────────────────────────────

def chat_vision(
    system: str,
    user: str,
    *,
    images: Optional[list[Union[str, Path, bytes]]] = None,
    model: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    return_json: bool = False,
    timeout_seconds: Optional[float] = None,
) -> tuple[str | dict, LLMUsage]:
    """Image-capable call for content generation, editing, and engagement hints.

    Uses VISION_PROVIDER + VISION_MODEL (default: gpt-5-5-image via jarvis).

    images: list of file paths (str/Path), URLs (str starting with http), or raw bytes.
    return_json: if True, parse the response as JSON and return a dict.
    Returns (text_or_dict, usage).
    """
    provider = _vision_provider()
    model = model or _vision_model()
    images = images or []

    if provider == "anthropic":
        result = _anthropic_vision_call(system, user, images, model, max_tokens, timeout_seconds=timeout_seconds)
    elif provider in ("openai", "openai_compatible", "jarvis"):
        result = _openai_vision_call(
            system, user, images, model, max_tokens, temperature, preset=provider,
            timeout_seconds=timeout_seconds,
        )
    else:
        raise ValueError(f"unsupported VISION_PROVIDER={provider!r}")

    text, usage = result
    if return_json:
        return _extract_json(text), usage
    return text, usage


# ── anthropic implementations ─────────────────────────────────────────────────

def _anthropic_call(
    system: str, user: str, model: str, max_tokens: int,
    timeout_seconds: Optional[float] = None,
) -> tuple[dict, LLMUsage]:
    import anthropic

    client = anthropic.Anthropic(timeout=_provider_timeout_seconds(timeout_seconds))
    t0 = time.monotonic()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    text = "".join(b.text for b in response.content if b.type == "text")
    usage = LLMUsage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        model=model,
        elapsed_sec=round(time.monotonic() - t0, 2),
    )
    _log_usage(usage, provider="anthropic", call_type="text")
    return _extract_json(text), usage


def _anthropic_vision_call(
    system: str,
    user: str,
    images: list,
    model: str,
    max_tokens: int,
    timeout_seconds: Optional[float] = None,
) -> tuple[str, LLMUsage]:
    import anthropic

    client = anthropic.Anthropic(timeout=_provider_timeout_seconds(timeout_seconds))
    t0 = time.monotonic()

    content: list[dict] = []
    for img in images:
        b64, media_type = _encode_image(img)
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}})
    content.append({"type": "text", "text": user})

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    usage = LLMUsage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        model=model,
        elapsed_sec=round(time.monotonic() - t0, 2),
    )
    _log_usage(usage, provider="anthropic", call_type="vision")
    return text, usage


# ── openai implementations ────────────────────────────────────────────────────

def _openai_call(
    system: str, user: str, model: str, max_tokens: int, temperature: float,
    timeout_seconds: Optional[float] = None,
) -> tuple[dict, LLMUsage]:
    from openai import OpenAI

    api_key, base_url = _resolve_preset("openai")
    client = OpenAI(api_key=api_key, base_url=base_url or None,
                    timeout=_provider_timeout_seconds(timeout_seconds), max_retries=0)
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

    if not response.choices:
        raise RuntimeError("OpenAI returned no completion choices")
    text = response.choices[0].message.content or ""
    usage = LLMUsage(
        input_tokens=response.usage.prompt_tokens if response.usage else 0,
        output_tokens=response.usage.completion_tokens if response.usage else 0,
        model=model,
        elapsed_sec=round(time.monotonic() - t0, 2),
    )
    _log_usage(usage, provider="openai", call_type="text")
    return _extract_json(text), usage


def _openai_compatible_call(
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    temperature: float,
    preset: str = "openai_compatible",
    timeout_seconds: Optional[float] = None,
) -> tuple[dict, LLMUsage]:
    from openai import OpenAI

    api_key, base_url = _resolve_preset(preset)
    client = OpenAI(api_key=api_key, base_url=base_url,
                    timeout=_provider_timeout_seconds(timeout_seconds), max_retries=0)
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

    if not response.choices:
        raise RuntimeError(f"{preset} returned no completion choices")
    text = response.choices[0].message.content or ""
    usage = LLMUsage(
        input_tokens=response.usage.prompt_tokens if response.usage else 0,
        output_tokens=response.usage.completion_tokens if response.usage else 0,
        model=model,
        elapsed_sec=round(time.monotonic() - t0, 2),
    )
    _log_usage(usage, preset=preset, provider=preset, base_url=base_url,
               call_type="text")
    return _extract_json(text), usage


def _openai_vision_call(
    system: str,
    user: str,
    images: list,
    model: str,
    max_tokens: int,
    temperature: float,
    preset: str = "openai",
    timeout_seconds: Optional[float] = None,
) -> tuple[str, LLMUsage]:
    from openai import OpenAI

    if preset in ("openai_compatible", "jarvis"):
        api_key, base_url = _resolve_preset(preset)
        client = OpenAI(api_key=api_key, base_url=base_url,
                        timeout=_provider_timeout_seconds(timeout_seconds), max_retries=0)
    else:
        api_key, base_url = _resolve_preset("openai")
        client = OpenAI(api_key=api_key, base_url=base_url or None,
                        timeout=_provider_timeout_seconds(timeout_seconds), max_retries=0)

    t0 = time.monotonic()
    content: list[dict] = []
    for img in images:
        if isinstance(img, str) and img.startswith("http"):
            content.append({"type": "image_url", "image_url": {"url": img}})
        else:
            b64, media_type = _encode_image(img)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{b64}"},
            })
    content.append({"type": "text", "text": user})

    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
    )

    if not response.choices:
        raise RuntimeError(f"{preset} returned no completion choices")
    text = response.choices[0].message.content or ""
    usage = LLMUsage(
        input_tokens=response.usage.prompt_tokens if response.usage else 0,
        output_tokens=response.usage.completion_tokens if response.usage else 0,
        model=model,
        elapsed_sec=round(time.monotonic() - t0, 2),
    )
    base_url_val = ""
    if preset in ("openai_compatible", "jarvis"):
        _, base_url_val = _resolve_preset(preset)
    _log_usage(usage, preset=preset, provider=preset, base_url=base_url_val,
               call_type="vision")
    return text, usage


# ── shared helpers ────────────────────────────────────────────────────────────

def _resolve_preset(preset: str) -> tuple[str, str]:
    if preset in _PRESETS:
        key_env, url_env = _PRESETS[preset]
        api_key = _getenv_ci(key_env)
        base_url = _getenv_ci(url_env)
    else:
        api_key = _getenv_ci("LLM_API_KEY") or _getenv_ci("OPENAI_API_KEY")
        base_url = _getenv_ci("LLM_BASE_URL") or _getenv_ci("OPENAI_BASE_URL")
        key_env, url_env = "LLM_API_KEY or OPENAI_API_KEY", "LLM_BASE_URL or OPENAI_BASE_URL"
    if not api_key:
        raise ValueError(f"{key_env} not set")
    if not base_url and preset != "openai":
        raise ValueError(f"{url_env} not set")
    return api_key, base_url


def _encode_image(img: Union[str, Path, bytes]) -> tuple[str, str]:
    """Return (base64_str, media_type) from a file path or raw bytes."""
    if isinstance(img, bytes):
        raw = img
        media_type = "image/jpeg"
    else:
        p = Path(img)
        raw = p.read_bytes()
        ext = p.suffix.lower()
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(ext, "image/jpeg")
    return base64.b64encode(raw).decode(), media_type


def _log_usage(usage: LLMUsage, *, preset: str = "",
               provider: str = "", base_url: str = "",
               call_type: str = "text") -> None:
    tag = f" ({preset})" if preset else ""
    url_tag = f" base_url={base_url}" if base_url else ""
    print(
        f"[LLM {call_type}] model={usage.model} provider={provider or 'default'}"
        f"{url_tag}{tag}: {usage.input_tokens} in / {usage.output_tokens} out, "
        f"~${usage.cost_estimate:.4f}, {usage.elapsed_sec:.1f}s"
    )
    log.info(
        "LLM %s%s: %d in / %d out tokens, ~$%.4f, %.1fs",
        usage.model, tag,
        usage.input_tokens, usage.output_tokens,
        usage.cost_estimate, usage.elapsed_sec,
    )


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

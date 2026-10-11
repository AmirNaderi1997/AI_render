"""Unified text-intelligence providers for planning and content creation.

Only Jarvis, Sarovi, and the local editable templates are selectable here.
Media generation and vision-specific clients remain separate concerns.
"""
from __future__ import annotations

import json
import logging
import math
import os
import socket
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Callable

from app.config import settings
from .llm import LLMUsage, _extract_json

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_JARVIS_URL = "https://api.jarvis.you/v1"
_DEFAULT_SAROVI_URL = "https://api.sarovi.ir/v1"


def _config(name: str, *legacy_names: str, default: str = "") -> str:
    """Read current process env first, then the loaded application settings."""
    for candidate in (name, *legacy_names):
        if candidate in os.environ:
            return os.environ[candidate].strip()
        value = getattr(settings, candidate, None)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _timeout_seconds() -> float:
    raw = _config("AI_TIMEOUT_SECONDS", default=str(_DEFAULT_TIMEOUT_SECONDS))
    try:
        timeout = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT_SECONDS
    if not math.isfinite(timeout) or timeout <= 0:
        return _DEFAULT_TIMEOUT_SECONDS
    return timeout


def _endpoint(base_url: str, path: str) -> str:
    clean = base_url.rstrip("/")
    suffix = "/" + path.lstrip("/")
    return clean if clean.endswith(suffix) else clean + suffix


def _post_json(url: str, payload: dict, api_key: str, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.load(exc)
        except Exception:
            detail = None
        message = ""
        if isinstance(detail, dict):
            error = detail.get("error", detail)
            if isinstance(error, dict):
                message = str(error.get("message") or error.get("code") or "")
            elif error:
                message = str(error)
        suffix = f": {message}" if message else ""
        if exc.code in {408, 502, 503, 504}:
            raise ConnectionError(
                f"provider transport failed (HTTP {exc.code}){suffix}"
            ) from exc
        raise RuntimeError(f"provider request failed (HTTP {exc.code}){suffix}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("provider returned an invalid JSON response")
    return result


def _is_connection_failure(exc: BaseException) -> bool:
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, (TimeoutError, socket.timeout, ConnectionError)):
            return True
        if isinstance(current, urllib.error.URLError) and not isinstance(current, urllib.error.HTTPError):
            return True
        for nested in (
            getattr(current, "reason", None),
            getattr(current, "__cause__", None),
            getattr(current, "__context__", None),
        ):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return False


def _prompt_parts(prompt: Any, style: Any, default_system: str) -> tuple[str, str, dict]:
    context: dict = style if isinstance(style, dict) else {}
    system = str(context.get("system_prompt") or default_system)
    user = str(context.get("user_prompt") or prompt)
    return system, user, context


class AIProvider(ABC):
    """Contract shared by external and zero-network intelligence providers."""

    name = "unknown"
    configured = False
    model = ""

    @abstractmethod
    def generate_plan(self, video_metadata: dict, transcript: dict) -> tuple[dict, LLMUsage]:
        raise NotImplementedError

    @abstractmethod
    def generate_storyboard(self, prompt: Any, style: Any) -> tuple[dict, LLMUsage]:
        raise NotImplementedError

    @abstractmethod
    def suggest_edits(self, scene: dict, context: dict) -> tuple[dict, LLMUsage]:
        raise NotImplementedError


class LocalFallbackProvider(AIProvider):
    name = "local"
    configured = True
    model = "local_template"

    def __init__(self, reason: str = "no external LLM provider configured") -> None:
        self.reason = reason

    @staticmethod
    def _captions_from_transcript(transcript: dict, duration: float) -> list[dict]:
        """Build deterministic, renderable captions from timestamped ASR words.

        The hosted planner is allowed to rewrite caption grouping and emphasis,
        but losing a valid transcript just because that provider is offline is
        never a safe fallback.  The local plan keeps the complete source, so
        ASR source times are also output-timeline times.
        """
        timed_words: list[dict] = []
        for raw in transcript.get("words") or []:
            try:
                text = str(raw.get("w") or "").strip()
                start = max(0.0, float(raw.get("start")))
                end = min(duration, float(raw.get("end")))
            except (TypeError, ValueError):
                continue
            if text and end > start and start < duration:
                timed_words.append({"text": text, "start": start, "end": end})

        captions: list[dict] = []
        group: list[dict] = []
        sentence_endings = (".", "!", "?", "؟", "。")

        def flush() -> None:
            if not group:
                return
            captions.append({
                "start": round(group[0]["start"], 3),
                "end": round(group[-1]["end"], 3),
                "text": " ".join(item["text"] for item in group),
                "style": "normal",
            })
            group.clear()

        for word in timed_words:
            # Long silence starts a new readable caption even if the previous
            # group has fewer than the preferred five words.
            if group and word["start"] - group[-1]["end"] > 0.8:
                flush()
            group.append(word)
            if len(group) >= 5 or word["text"].endswith(sentence_endings):
                flush()
        flush()

        if captions:
            captions[0]["style"] = "emphasis"
            if len(captions) > 1:
                captions[-1]["style"] = "cta"
        return captions

    def generate_plan(self, video_metadata: dict, transcript: dict) -> tuple[dict, LLMUsage]:
        duration = float(video_metadata.get("duration") or transcript.get("duration") or 0)
        if duration <= 0:
            raise ValueError("source video has no positive duration")
        output_kind = str(video_metadata.get("output_kind") or "reel")
        canvas = {
            "width": 1080,
            "height": 1080 if output_kind == "post" else 1920,
            "fps": 30,
        }
        if video_metadata.get("caption_font"):
            canvas["caption_font"] = video_metadata["caption_font"]
        if video_metadata.get("caption_font_id"):
            canvas["caption_font_id"] = video_metadata["caption_font_id"]
        plan = {
            "version": "0.1",
            "style": str(video_metadata.get("preset_name") or "rafiei_reel"),
            "canvas": canvas,
            "source": str(video_metadata.get("source_rel") or ""),
            "segments": [{"id": "s1", "in": 0.0, "out": round(duration, 6)}],
            "transitions": [],
            "transition_context": {
                "output_kind": output_kind,
                "style": str(video_metadata.get("transition_style") or "auto"),
                "request": str(video_metadata.get("transition_request") or ""),
            },
            "captions": self._captions_from_transcript(transcript, duration),
            "broll": [],
            "sfx": [],
            "export": {"file": "output.mp4", "crf": 20},
            "generation_meta": {"provider": "local", "fallback_reason": self.reason},
        }
        if video_metadata.get("style_ref"):
            plan["style_profile"] = dict(video_metadata["style_ref"])
        return plan, LLMUsage(model=self.model)

    def generate_storyboard(self, prompt: Any, style: Any) -> tuple[dict, LLMUsage]:
        _system, _user, context = _prompt_parts(prompt, style, "")
        content_type = str(context.get("content_type") or "reel")
        placeholders = ([('Main point', 5.0)] if content_type == "post" else
                        [('Intro', 5.0), ('Main point', 5.0), ('Outro', 5.0)])
        scenes = [
            {
                "index": index,
                "description": label,
                "duration_s": duration,
                "text_overlay": label,
                "narration_text": "",
                "narration_voice": "default",
                "media_method": "generate",
                "media_prompt": f"Editable placeholder visual for the {label.lower()}",
                "estimated_cost": 0.0,
            }
            for index, (label, duration) in enumerate(placeholders)
        ]
        return {
            "scenes": scenes,
            "total_duration_s": sum(item[1] for item in placeholders),
            "_provider_meta": {"provider": "local", "fallback_reason": self.reason},
        }, LLMUsage(model=self.model)

    def suggest_edits(self, scene: dict, context: dict) -> tuple[dict, LLMUsage]:
        return {
            "suggestions": [],
            "provider": "local",
            "message": "Using local templates",
            "fallback_reason": self.reason,
        }, LLMUsage(model=self.model)


class _ExternalProvider(AIProvider):
    def _with_fallback(
        self,
        operation: str,
        call: Callable[[], tuple[dict, LLMUsage]],
        fallback: Callable[[LocalFallbackProvider], tuple[dict, LLMUsage]],
    ) -> tuple[dict, LLMUsage]:
        try:
            return call()
        except Exception as exc:
            if not _is_connection_failure(exc):
                raise
            reason = f"{self.name} {operation} failed: {exc}"
            log.warning("%s; using local fallback", reason)
            return fallback(LocalFallbackProvider(reason=reason[:300]))


class JarvisProvider(_ExternalProvider):
    name = "jarvis"
    configured = True

    def __init__(self) -> None:
        self.api_key = _config("JARVIS_API_KEY")
        self.api_url = (_config("JARVIS_API_URL", "JARVIS_BASE_URL",
                                default=_DEFAULT_JARVIS_URL) or _DEFAULT_JARVIS_URL)
        self.model = _config("JARVIS_MODEL", default="DEEPSEEK_V4_FLASH") or "DEEPSEEK_V4_FLASH"

    def _chat_json(self, system: str, user: str) -> tuple[dict, LLMUsage]:
        started = time.monotonic()
        result = _post_json(
            _endpoint(self.api_url, "chat/completions"),
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
            },
            self.api_key,
            _timeout_seconds(),
        )
        choices = result.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise RuntimeError("Jarvis returned no completion choices")
        message = choices[0].get("message") or {}
        text = message.get("content") if isinstance(message, dict) else ""
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Jarvis returned no text")
        reported = result.get("usage") or {}
        usage = LLMUsage(
            input_tokens=int(reported.get("prompt_tokens") or reported.get("input_tokens") or 0),
            output_tokens=int(reported.get("completion_tokens") or reported.get("output_tokens") or 0),
            model=str(result.get("model") or self.model),
            elapsed_sec=round(time.monotonic() - started, 2),
        )
        return _extract_json(text), usage

    def generate_plan(self, video_metadata: dict, transcript: dict) -> tuple[dict, LLMUsage]:
        system = str(video_metadata.get("system_prompt") or "Return a valid edit plan as JSON.")
        user = str(video_metadata.get("user_prompt") or json.dumps(transcript, ensure_ascii=False))

        def sarovi_or_local(local: LocalFallbackProvider) -> tuple[dict, LLMUsage]:
            if _config("SAROVI_API_KEY"):
                try:
                    log.warning("Jarvis plan generation unavailable; trying configured Sarovi provider")
                    return SaroviProvider()._responses_json(system, user)
                except Exception as exc:
                    log.warning("Sarovi plan failover also failed (%s); using local fallback", exc)
                    local = LocalFallbackProvider(
                        f"Jarvis unavailable and Sarovi failover failed: {exc}"[:300]
                    )
            return local.generate_plan(video_metadata, transcript)

        return self._with_fallback(
            "plan generation",
            lambda: self._chat_json(system, user),
            sarovi_or_local,
        )

    def generate_storyboard(self, prompt: Any, style: Any) -> tuple[dict, LLMUsage]:
        system, user, context = _prompt_parts(prompt, style, "Return a storyboard as JSON.")
        return self._with_fallback(
            "storyboard generation",
            lambda: self._chat_json(system, user),
            lambda local: local.generate_storyboard(prompt, context),
        )

    def suggest_edits(self, scene: dict, context: dict) -> tuple[dict, LLMUsage]:
        system = str(context.get("system_prompt") or "Suggest concrete render edits as JSON.")
        user = str(context.get("user_prompt") or json.dumps({"scene": scene, "context": context}, ensure_ascii=False))
        return self._with_fallback(
            "edit suggestion",
            lambda: self._chat_json(system, user),
            lambda local: local.suggest_edits(scene, context),
        )


class SaroviProvider(_ExternalProvider):
    name = "sarovi"
    configured = True

    def __init__(self) -> None:
        self.api_key = _config("SAROVI_API_KEY")
        self.api_url = _config("SAROVI_API_URL", default=_DEFAULT_SAROVI_URL) or _DEFAULT_SAROVI_URL
        self.model = _config(
            "SAROVI_LLM_MODEL",
            default=settings.SAROVI_LLM_MODEL,
        ) or settings.SAROVI_LLM_MODEL

    def _responses_json(self, system: str, user: str) -> tuple[dict, LLMUsage]:
        started = time.monotonic()
        result = _post_json(
            _endpoint(self.api_url, "responses"),
            {
                "model": self.model,
                "instructions": system,
                "input": user,
                "max_output_tokens": 16000,
            },
            self.api_key,
            _timeout_seconds(),
        )
        from .sarovi import response_output_text
        text = response_output_text(result)
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Sarovi returned no text")
        reported = result.get("usage") or {}
        usage = LLMUsage(
            input_tokens=int(reported.get("input_tokens") or 0),
            output_tokens=int(reported.get("output_tokens") or 0),
            model=str(result.get("model") or self.model),
            elapsed_sec=round(time.monotonic() - started, 2),
        )
        return _extract_json(text), usage

    def generate_plan(self, video_metadata: dict, transcript: dict) -> tuple[dict, LLMUsage]:
        system = str(video_metadata.get("system_prompt") or "Return a valid edit plan as JSON.")
        user = str(video_metadata.get("user_prompt") or json.dumps(transcript, ensure_ascii=False))
        return self._with_fallback(
            "plan generation",
            lambda: self._responses_json(system, user),
            lambda local: local.generate_plan(video_metadata, transcript),
        )

    def generate_storyboard(self, prompt: Any, style: Any) -> tuple[dict, LLMUsage]:
        system, user, context = _prompt_parts(prompt, style, "Return a storyboard as JSON.")
        return self._with_fallback(
            "storyboard generation",
            lambda: self._responses_json(system, user),
            lambda local: local.generate_storyboard(prompt, context),
        )

    def suggest_edits(self, scene: dict, context: dict) -> tuple[dict, LLMUsage]:
        reason = "Sarovi edit suggestions are not configured; using local templates"
        log.info(reason)
        return LocalFallbackProvider(reason).suggest_edits(scene, context)


def get_provider(provider_name: str | None = None) -> AIProvider:
    provider = (provider_name or _config("LLM_PROVIDER", default="")).strip().lower()
    if provider == "jarvis" and _config("JARVIS_API_KEY"):
        return JarvisProvider()
    if provider == "sarovi" and _config("SAROVI_API_KEY"):
        return SaroviProvider()
    return LocalFallbackProvider()


def provider_status() -> dict[str, Any]:
    provider = get_provider()
    if isinstance(provider, LocalFallbackProvider):
        return {"provider": "local", "configured": True, "message": "Using local templates"}
    result: dict[str, Any] = {"provider": provider.name, "configured": True}
    if provider.model:
        result["model"] = provider.model
    return result

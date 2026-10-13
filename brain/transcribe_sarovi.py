"""Sarovi hosted-Whisper transcription engine.

Sits between ElevenLabs Scribe and the local Whisper runtime in the ASR
fallback cascade: when ElevenLabs is unavailable (most often an exhausted
credit balance) Sarovi offers a fast, hosted ``whisper-large-v3`` without the
cold-start model download that makes the local engine slow and flaky.

Sarovi's ``/v1/audio/transcriptions`` contract returns plain text with no word
or segment timing. The edit-plan pipeline needs a ``words`` array with
start/end times to place captions and cuts, so we synthesise per-word
timestamps by spreading the transcript across the detected audio duration in
proportion to each word's length. These timings are approximate — the local
Whisper fallback still produces true timestamps — but they let the AI planner
run and caption the reel instead of silently degrading to a template plan.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import subprocess
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

ENDPOINT = "https://api.sarovi.ir/v1/audio/transcriptions"
DEFAULT_MODEL = "openai/whisper-large-v3-turbo"
# Rough per-second price used only when the API omits a cost. Sarovi bills in
# shared credits; the response's execution.costUsd is preferred when present.
_FALLBACK_COST_PER_SECOND = 0.006 / 60
# The request schema caps audioBase64 at 18,666,668 chars (~14 MB raw). Stay
# safely below that; a 64 kbps mono MP3 keeps ~29 minutes of audio under it.
_MAX_AUDIO_BYTES = 13_000_000
_TIMEOUT = int(os.environ.get("SAROVI_SCRIBE_TIMEOUT", "180"))

# Mirror the sentence boundaries ElevenLabs/Whisper mappers key on.
_SENTENCE_ENDERS = (".", "!", "?", "؟", "。", "…")


def _normalize_persian(text: str) -> str:
    return (
        text.replace("ي", "ی")  # Arabic ي -> Persian ی
        .replace("ى", "ی")       # alef maqsura -> ی
        .replace("ك", "ک")       # Arabic ك -> Persian ک
    )


def _cache_key(file_digest: str, language: Optional[str], model_id: str) -> str:
    settings = {
        "engine": "sarovi",
        "file_hash": file_digest,
        "model_id": model_id,
        "language": language,
    }
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:16]


def _extract_audio(video: Path, out_dir: Path) -> Path:
    """Extract a compact mono MP3 so even long reels fit the base64 ceiling."""
    audio = out_dir / f"audio_sarovi_{uuid.uuid4().hex[:8]}.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
         "-b:a", "64k", str(audio)],
        capture_output=True, check=True, timeout=120,
    )
    return audio


def _synthesize_words(text: str, duration: float) -> tuple[list[dict], list[dict]]:
    """Spread *text* across [0, duration] proportionally to word length.

    Timestamps are approximate — the API gives no timing — but keep words in
    order and within the clip so downstream caption placement stays sane.
    """
    tokens = [t for t in re.split(r"\s+", text.strip()) if t]
    if not tokens or duration <= 0:
        return [], []

    weights = [max(1, len(re.sub(r"[^\w؀-ۿ]", "", t)) or len(t)) for t in tokens]
    total_weight = sum(weights)
    words: list[dict] = []
    sentences: list[dict] = []
    current: list[dict] = []
    cursor = 0.0
    for token, weight in zip(tokens, weights):
        span = duration * (weight / total_weight)
        start = round(cursor, 3)
        end = round(min(duration, cursor + span), 3)
        cursor += span
        cleaned = _normalize_persian(token.strip())
        if not cleaned:
            continue
        entry = {"w": cleaned, "start": start, "end": end, "prob": 0.5}
        words.append(entry)
        current.append(entry)
        if cleaned.endswith(_SENTENCE_ENDERS) and current:
            sentences.append({
                "text": " ".join(e["w"] for e in current),
                "start": current[0]["start"],
                "end": current[-1]["end"],
            })
            current = []
    if current:
        sentences.append({
            "text": " ".join(e["w"] for e in current),
            "start": current[0]["start"],
            "end": current[-1]["end"],
        })
    return words, sentences


def _post(payload: dict) -> dict:
    key = os.environ.get("SAROVI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("SAROVI_API_KEY not set")
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        code = "provider_error"
        try:
            error = json.load(exc).get("error", {})
            if isinstance(error, dict):
                code = str(error.get("code") or code)
        except (ValueError, OSError, AttributeError):
            pass
        hint = ""
        if exc.code == 403 or "SCOPE" in code.upper():
            # /v1/audio/transcriptions requires the audio:write scope, which is
            # separate from the Studio TTS scope the account may already have.
            hint = " — enable the 'audio:write' scope on your Sarovi API key"
        raise RuntimeError(f"Sarovi transcription failed (HTTP {exc.code}: {code}){hint}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f"Sarovi transcription did not complete ({type(exc).__name__})") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Sarovi returned an invalid transcription response")
    return result


def transcribe_sarovi(
    video: Path,
    out_dir: Path,
    *,
    language: Optional[str] = None,
    file_digest: str,
    keyterms: Optional[list[str]] = None,  # accepted for signature parity; unused
) -> tuple[dict, float]:
    """Transcribe *video* via Sarovi hosted Whisper. Returns (transcript, cost_usd).

    Raises RuntimeError on any API failure so the caller can fall back to the
    local Whisper engine.
    """
    model = os.environ.get("SAROVI_STT_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    key = _cache_key(file_digest, language, model)
    archive = out_dir / "transcripts" / f"{key}.json"
    if archive.exists():
        cached = json.loads(archive.read_text())
        log.info("sarovi cache hit for %s (%s)", video.name, key)
        return cached, 0.0

    from engine.probe import has_audio, probe_duration
    if not has_audio(video):
        raise RuntimeError("source has no audio stream")

    audio = _extract_audio(video, out_dir)
    try:
        raw = audio.read_bytes()
        if len(raw) > _MAX_AUDIO_BYTES:
            raise RuntimeError(
                f"audio too long for Sarovi transcription ({len(raw)} bytes > {_MAX_AUDIO_BYTES})"
            )
        payload = {
            "audioBase64": base64.b64encode(raw).decode("ascii"),
            "mediaType": "audio/mpeg",
            "model": model,
        }
        if language and re.fullmatch(r"[a-z]{2,3}", language):
            payload["language"] = language

        result = _post(payload)
        text = result.get("text")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Sarovi returned no transcription text")

        duration = round(probe_duration(video), 3)
        words, sentences = _synthesize_words(text, duration)

        execution = result.get("execution") if isinstance(result.get("execution"), dict) else {}
        cost = execution.get("costUsd")
        if not isinstance(cost, (int, float)):
            cost = round(duration * _FALLBACK_COST_PER_SECOND, 6)

        transcript = {
            "file_hash": file_digest,
            "cache_key": key,
            "engine": "sarovi",
            "model_id": model,
            "requested_language": language,
            "language": language or "unknown",
            "duration": duration,
            "words": words,
            "sentences": sentences,
            # Downstream UI can note that these timings are estimated.
            "timing_estimated": True,
        }

        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))
        log.info("sarovi: %d words, %.1fs audio, $%.4f (model=%s)",
                 len(words), duration, float(cost or 0.0), model)
        return transcript, round(float(cost or 0.0), 6)
    finally:
        audio.unlink(missing_ok=True)

"""ElevenLabs Scribe v2 transcription engine."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger(__name__)

SCRIBE_MODEL = "scribe_v2"
SCRIBE_FALLBACK_MODEL = "scribe_v1"
# $0.40 per hour  →  per-second cost
COST_PER_SECOND = 0.40 / 3600
_CONNECT_TIMEOUT = int(os.environ.get("ELEVENLABS_SCRIBE_CONNECT_TIMEOUT", "10"))
_READ_TIMEOUT = int(os.environ.get("ELEVENLABS_SCRIBE_READ_TIMEOUT", "120"))

# Markers of errors that will fail identically on an immediate retry: an
# exhausted quota, or a rejected/forbidden key. These are surfaced right away
# so the caller can fall back to the local Whisper engine without delay.
_PERMANENT_ERROR_MARKERS = ("quota_exceeded", "quota", "status_code: 401", "status_code: 403")


def _is_permanent_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status in (401, 403):
        return True
    return any(marker in text for marker in _PERMANENT_ERROR_MARKERS)


def _normalize_persian(text: str) -> str:
    return (
        text
        .replace("ي", "ی")  # Arabic ي → Persian ی
        .replace("ى", "ی")  # Arabic alef maqsura → ی
        .replace("ك", "ک")  # Arabic ك → Persian ک
    )


def _extract_audio(video: Path, out_dir: Path) -> Path:
    wav = out_dir / "audio_elevenlabs.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-vn", "-acodec", "pcm_s16le",
         "-ar", "16000", "-ac", "1", str(wav)],
        capture_output=True, check=True,
    )
    return wav


def _cache_key(file_digest: str, language: Optional[str], model_id: str,
               keyterms: Optional[list[str]] = None) -> str:
    settings = {
        "engine": "elevenlabs",
        "file_hash": file_digest,
        "model_id": model_id,
        "language": language,
        "keyterms": sorted(keyterms or []),
    }
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:16]


def _map_response(resp, file_digest: str, key: str, language: Optional[str],
                  duration_secs: float) -> dict:
    words: list[dict] = []
    sentences: list[dict] = []
    current_sentence: list[dict] = []

    for w in (resp.words or []):
        if w.type != "word":
            continue
        cleaned = _normalize_persian(w.text.strip())
        if not cleaned:
            continue
        prob = round(math.exp(w.logprob), 3) if w.logprob is not None else 0.5
        entry = {
            "w": cleaned,
            "start": round(w.start, 3),
            "end": round(w.end, 3),
            "prob": prob,
        }
        words.append(entry)
        current_sentence.append(entry)

        ends_sentence = cleaned.endswith((".", "!", "?", "؟", "。"))
        if ends_sentence and current_sentence:
            sentences.append({
                "text": " ".join(e["w"] for e in current_sentence),
                "start": current_sentence[0]["start"],
                "end": current_sentence[-1]["end"],
            })
            current_sentence = []

    if current_sentence:
        sentences.append({
            "text": " ".join(e["w"] for e in current_sentence),
            "start": current_sentence[0]["start"],
            "end": current_sentence[-1]["end"],
        })

    return {
        "file_hash": file_digest,
        "cache_key": key,
        "engine": "elevenlabs",
        "model_id": SCRIBE_MODEL,
        "requested_language": language,
        "language": resp.language_code or language or "unknown",
        "duration": round(duration_secs, 3),
        "words": words,
        "sentences": sentences,
    }


def transcribe_elevenlabs(
    video: Path,
    out_dir: Path,
    *,
    language: Optional[str] = None,
    file_digest: str,
    keyterms: Optional[list[str]] = None,
) -> tuple[dict, float]:
    """Transcribe using ElevenLabs Scribe. Returns (transcript_dict, cost_usd).

    Raises RuntimeError on API failure (caller should fall back to Whisper).
    """
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not set")

    key = _cache_key(file_digest, language, SCRIBE_MODEL, keyterms)

    archive = out_dir / "transcripts" / f"{key}.json"
    if archive.exists():
        cached = json.loads(archive.read_text())
        cost = cached.get("duration", 0) * COST_PER_SECOND
        log.info("elevenlabs cache hit for %s (%s)", video.name, key)
        return cached, round(cost, 6)

    wav = _extract_audio(video, out_dir)
    try:
        import httpx as _httpx
        from elevenlabs import ElevenLabs
        client = ElevenLabs(
            api_key=api_key,
            timeout=_httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT),
        )

        kwargs: dict = {
            "model_id": SCRIBE_MODEL,
            "language_code": language or "fa",
            "tag_audio_events": False,
            "diarize": False,
            "timestamps_granularity": "word",
        }
        if keyterms:
            kwargs["keyterms"] = keyterms[:1000]

        t0 = time.monotonic()
        with open(wav, "rb") as f:
            try:
                resp = client.speech_to_text.convert(file=f, **kwargs)
            except Exception as first_err:
                # Quota/auth failures are permanent for this request; retrying
                # only burns another request cycle before the inevitable
                # fallback to Whisper. Fail fast so the fallback engine starts
                # sooner and the job does not sit in "generating plan" for
                # minutes on a request that can never succeed.
                if _is_permanent_error(first_err):
                    raise RuntimeError(
                        f"ElevenLabs API unavailable: {first_err}"
                    ) from first_err
                log.warning("scribe_v2 failed (%s), retrying once…", first_err)
                f.seek(0)
                try:
                    resp = client.speech_to_text.convert(file=f, **kwargs)
                except Exception as retry_err:
                    raise RuntimeError(
                        f"ElevenLabs API failed: {retry_err}"
                    ) from retry_err
        elapsed = time.monotonic() - t0

        duration = resp.audio_duration_secs if hasattr(resp, "audio_duration_secs") and resp.audio_duration_secs else 0.0
        cost = round(duration * COST_PER_SECOND, 6)
        if keyterms:
            cost = round(cost * 1.2, 6)

        transcript = _map_response(resp, file_digest, key, language, duration)

        log.info("elevenlabs: %d words, %.1fs audio, $%.4f, %.1fs elapsed",
                 len(transcript["words"]), duration, cost, elapsed)

        archive.parent.mkdir(exist_ok=True)
        archive.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))

        return transcript, cost

    finally:
        wav.unlink(missing_ok=True)

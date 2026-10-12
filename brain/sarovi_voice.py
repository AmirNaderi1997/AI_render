"""Persian narration through Sarovi Studio audio."""
from __future__ import annotations

import base64
import binascii
import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .tts import TTSResult, _get_audio_duration

ENDPOINT = "https://api.sarovi.ir/v1/studio/audio"
DEFAULT_MODEL = "google/gemini-3.8-flash-tts"
DEFAULT_VOICE = "Sulafat"
DEFAULT_INSTRUCTIONS = "فارسی معیار ایران، با تلفظ طبیعی و روان، لحن گرم و حرفه‌ای، بدون لهجهٔ غیرفارسی"
MAX_AUDIO_BYTES = 25_000_000


def generate_narration(text: str, output_dir: Path) -> TTSResult:
    key = os.getenv("SAROVI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Sarovi voice is not configured on the server")
    if not text.strip() or len(text) > 12_000:
        raise ValueError("Narration must contain 1 to 12000 characters")
    model = os.getenv("SAROVI_TTS_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    voice = os.getenv("SAROVI_TTS_VOICE", DEFAULT_VOICE).strip() or DEFAULT_VOICE
    instructions = os.getenv("SAROVI_TTS_INSTRUCTIONS", DEFAULT_INSTRUCTIONS).strip()
    payload = {"model": model, "text": text.strip(), "voice": voice, "format": "wav"}
    if instructions:
        payload["instructions"] = instructions
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        code = "provider_error"
        try:
            error = json.load(exc).get("error", {})
            if isinstance(error, dict):
                code = str(error.get("code") or code)
        except (ValueError, OSError, AttributeError):
            pass
        raise RuntimeError(f"Sarovi voice request failed ({exc.code}: {code})") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError("Sarovi voice request did not complete") from exc

    output = result.get("output", {}) if isinstance(result, dict) else {}
    encoded = output.get("data") if isinstance(output, dict) else None
    media_type = output.get("mediaType", "") if isinstance(output, dict) else ""
    if not isinstance(encoded, str) or not encoded:
        raise RuntimeError("Sarovi returned no voice audio")
    extensions = {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav"}
    if media_type not in extensions:
        raise RuntimeError("Sarovi returned an unsupported voice format")
    if len(encoded) > MAX_AUDIO_BYTES * 4 // 3 + 8:
        raise RuntimeError("Sarovi returned oversized voice audio")
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError("Sarovi returned invalid voice audio") from exc
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise RuntimeError("Sarovi returned empty or oversized voice audio")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"narration_sarovi_{uuid.uuid4().hex[:12]}{extensions[media_type]}"
    path.write_bytes(audio)
    duration = _get_audio_duration(str(path))
    if duration <= 0:
        path.unlink(missing_ok=True)
        raise RuntimeError("Sarovi returned voice audio with no playable duration")
    return TTSResult(file_path=str(path), duration_s=duration, cost_usd=None)

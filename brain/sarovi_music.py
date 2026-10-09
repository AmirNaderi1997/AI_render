"""Generate a short music clip through Sarovi's Studio audio API."""
from __future__ import annotations

import base64
import binascii
import json
import os
import urllib.error
import urllib.request

ENDPOINT = "https://api.sarovi.ir/v1/studio/audio"
MODEL = "google/lyria-3-clip-preview"
MAX_AUDIO_BYTES = 25_000_000


class MusicGenerationError(RuntimeError):
    pass


def generate_clip(prompt: str) -> bytes:
    key = os.getenv("SAROVI_API_KEY", "").strip()
    if not key:
        raise MusicGenerationError("Sarovi music is not configured on the server")
    description = prompt.strip()
    if not description or len(description) > 4000:
        raise MusicGenerationError("Describe the music in 1 to 4000 characters")

    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps({"model": MODEL, "text": description, "format": "mp3"}, ensure_ascii=False).encode("utf-8"),
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
        raise MusicGenerationError(f"Sarovi music request failed ({exc.code}: {code})") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise MusicGenerationError("Sarovi music request did not complete") from exc

    output = result.get("output", {}) if isinstance(result, dict) else {}
    encoded = output.get("data") if isinstance(output, dict) else None
    media_type = output.get("mediaType", "") if isinstance(output, dict) else ""
    if not isinstance(encoded, str) or not encoded:
        raise MusicGenerationError("Sarovi returned no audio")
    if media_type and media_type not in ("audio/mpeg", "audio/mp3"):
        raise MusicGenerationError("Sarovi returned an unsupported audio format")
    if len(encoded) > MAX_AUDIO_BYTES * 4 // 3 + 8:
        raise MusicGenerationError("Sarovi returned an oversized audio file")
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MusicGenerationError("Sarovi returned invalid audio data") from exc
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise MusicGenerationError("Sarovi returned an empty or oversized audio file")
    return audio

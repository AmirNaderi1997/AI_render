"""Text-to-Speech via Microsoft Edge TTS (free, no API key)."""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class TTSResult:
    file_path: str
    duration_s: float
    cost_usd: float | None = None


# Persian voices available in edge-tts:
# fa-IR-DilaraNeural (female) — natural, clear
# fa-IR-FaridNeural (male) — natural, clear
_DEFAULT_VOICE = "fa-IR-DilaraNeural"
_DEFAULT_EDGE_VOICE = "en-US-GuyNeural"
_ELEVENLABS_TIMEOUT_SECONDS = 10


def _get_audio_duration(path: str) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=10,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


async def _generate_async(text: str, output_path: str, voice: str, rate: str) -> None:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(output_path)


def _configured_provider(provider: str | None = None) -> str:
    """Return the explicitly selected narration provider.

    This is read at call time so worker processes and tests can change the
    environment without requiring an application restart.
    """
    provider = (provider or os.environ.get("TTS_PROVIDER", "edge-tts")).strip().lower()
    if provider == "edge":
        provider = "edge-tts"
    if provider not in {"edge-tts", "elevenlabs", "disabled"}:
        raise ValueError("TTS_PROVIDER must be edge-tts, elevenlabs, or disabled")
    return provider


def _edge_voice(voice_id: str) -> str:
    # TTS_VOICE is the current setting. Preserve TTS_VOICE_ID for existing
    # Persian installations that have not migrated their environment yet.
    return voice_id or os.environ.get("TTS_VOICE") or os.environ.get("TTS_VOICE_ID") or _DEFAULT_EDGE_VOICE


def _generate_elevenlabs(text: str, output_path: str) -> None:
    """Generate one MP3 through ElevenLabs with a bounded network timeout."""
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    if not api_key or not voice_id:
        raise RuntimeError("ElevenLabs is not configured with API key and voice ID")
    try:
        import httpx
        response = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": api_key, "accept": "audio/mpeg"},
            json={"text": text, "model_id": "eleven_multilingual_v2"},
            timeout=_ELEVENLABS_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        Path(output_path).write_bytes(response.content)
    except Exception as exc:
        Path(output_path).unlink(missing_ok=True)
        raise RuntimeError(f"ElevenLabs request failed ({type(exc).__name__})") from exc


def generate_narration(
    text: str,
    output_dir: Path,
    voice_id: str = "",
    model_id: str = "",
    rate: str = "+0%",
    provider: str | None = None,
) -> TTSResult:
    """Generate narration using the configured provider, with Edge fallback."""
    if not text.strip():
        raise ValueError("narration text is empty")

    provider = _configured_provider(provider)
    if provider == "disabled":
        log.info("narration skipped because TTS_PROVIDER=disabled")
        return TTSResult(file_path="", duration_s=0.0, cost_usd=0.0)

    voice = _edge_voice(voice_id)
    rate = os.environ.get("TTS_RATE", rate)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / f"narration_{uuid.uuid4().hex[:12]}.mp3"

    async def generate_with_timeout() -> None:
        await asyncio.wait_for(_generate_async(text, str(out_file), voice, rate), timeout=60)

    def run_once() -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # Content generation runs in a worker thread, which has no event loop.
            asyncio.run(generate_with_timeout())
        else:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                pool.submit(lambda: asyncio.run(generate_with_timeout())).result()

    if provider == "elevenlabs":
        try:
            log.info("generating narration with ElevenLabs (10s timeout)")
            _generate_elevenlabs(text, str(out_file))
        except Exception as exc:
            # ElevenLabs is commonly inaccessible in Iran. Edge remains a
            # no-key fallback even when ElevenLabs is explicitly requested.
            log.warning("ElevenLabs narration failed (%s); falling back to edge-tts", exc)
            out_file.unlink(missing_ok=True)
            provider = "edge-tts"

    if provider == "edge-tts":
        from aiohttp import ClientConnectionError
        for attempt in range(3):
            try:
                run_once()
                break
            except (TimeoutError, ClientConnectionError, ConnectionError, OSError) as exc:
                out_file.unlink(missing_ok=True)
                if attempt == 2:
                    raise RuntimeError(
                        f"edge-tts connection failed after 3 attempts ({type(exc).__name__})"
                    ) from exc
                delay = 2 ** attempt
                log.warning("edge-tts connection interrupted; retrying in %ss", delay)
                time.sleep(delay)
            except Exception as exc:
                out_file.unlink(missing_ok=True)
                raise RuntimeError(f"edge-tts generation failed ({type(exc).__name__})") from exc

    if not out_file.exists() or out_file.stat().st_size == 0:
        raise RuntimeError("edge-tts returned empty audio")

    duration = _get_audio_duration(str(out_file))
    if duration <= 0:
        out_file.unlink(missing_ok=True)
        raise RuntimeError("edge-tts returned audio with no playable duration")
    log.info("TTS generated with %s: %s (%.1fs)", provider, out_file.name, duration)
    return TTSResult(file_path=str(out_file), duration_s=duration, cost_usd=0.0)

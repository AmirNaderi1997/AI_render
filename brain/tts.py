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


def generate_narration(
    text: str,
    output_dir: Path,
    voice_id: str = "",
    model_id: str = "",
    rate: str = "+0%",
) -> TTSResult:
    """Generate speech as MP3 using edge-tts (free, no key needed)."""
    if not text.strip():
        raise ValueError("narration text is empty")

    voice = voice_id or os.environ.get("TTS_VOICE_ID", _DEFAULT_VOICE)
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
    log.info("TTS generated: %s (%.1fs)", out_file.name, duration)
    return TTSResult(file_path=str(out_file), duration_s=duration, cost_usd=0.0)

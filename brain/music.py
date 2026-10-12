"""Background music mixing for rendered videos (FFmpeg)."""
from __future__ import annotations

import ipaddress
import logging
import math
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Callable, Optional

from engine.probe import has_audio, probe, probe_duration

log = logging.getLogger(__name__)

MUSIC_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac"}
MAX_MUSIC_BYTES = 100_000_000
DEFAULT_VOLUME = 0.3
DEFAULT_FADE_IN = 2.0
DEFAULT_FADE_OUT = 3.0
PREVIEW_SECONDS = 30.0
_MAX_FADE_SECONDS = 60.0


class MusicMixError(RuntimeError):
    """Mixing failed or the inputs cannot be mixed."""


def validate_params(volume_level: float, fade_in_seconds: float, fade_out_seconds: float) -> tuple[float, float, float]:
    """Return validated (volume, fade_in, fade_out); raise ValueError on bad input."""
    for name, value in (("volume_level", volume_level), ("fade_in_seconds", fade_in_seconds),
                        ("fade_out_seconds", fade_out_seconds)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
    if not 0.0 <= volume_level <= 1.0:
        raise ValueError("volume_level must be between 0.0 and 1.0")
    if not 0.0 <= fade_in_seconds <= _MAX_FADE_SECONDS or not 0.0 <= fade_out_seconds <= _MAX_FADE_SECONDS:
        raise ValueError(f"fade durations must be between 0 and {int(_MAX_FADE_SECONDS)} seconds")
    return float(volume_level), float(fade_in_seconds), float(fade_out_seconds)


def probe_music(path: Path) -> float:
    """Return the playable duration of an audio file, or raise ValueError."""
    if Path(path).suffix.lower() not in MUSIC_EXTENSIONS:
        raise ValueError(f"unsupported music format: {Path(path).suffix or '(none)'}")
    try:
        info = probe(Path(path))
    except Exception as exc:
        raise ValueError("music file cannot be read") from exc
    if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
        raise ValueError("music file has no audio stream")
    try:
        duration = float(info.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        duration = 0.0
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("music file has no playable duration")
    return duration


def _fades(duration: float, fade_in: float, fade_out: float) -> tuple[float, float]:
    """Shrink fades proportionally so they never overlap or exceed the video."""
    total = fade_in + fade_out
    if total > duration > 0:
        scale = duration / total
        fade_in, fade_out = fade_in * scale, fade_out * scale
    return fade_in, fade_out


def music_filter(duration: float, volume: float, fade_in: float, fade_out: float) -> str:
    """Filter chain for the music input: trim to video length, volume, fades."""
    fade_in, fade_out = _fades(duration, fade_in, fade_out)
    chain = [f"atrim=0:{duration:.3f}", "asetpts=PTS-STARTPTS", f"volume={volume:.4f}"]
    if fade_in > 0.001:
        chain.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0.001:
        chain.append(f"afade=t=out:st={max(0.0, duration - fade_out):.3f}:d={fade_out:.3f}")
    return ",".join(chain)


def build_command(video: Path, music: Path, output: Path, *, duration: float, video_has_audio: bool,
                  volume: float, fade_in: float, fade_out: float,
                  target_lufs: float | None = None) -> list[str]:
    """FFmpeg argv that mixes `music` under the video's own audio.

    The music input is looped (so short tracks cover the whole video) and then
    trimmed to the video duration. Without a source audio track the music
    becomes the only audio track.
    """
    chain = music_filter(duration, volume, fade_in, fade_out)
    mixed_label = "mixed" if target_lufs is not None else "aout"
    if video_has_audio:
        graph = (f"[1:a]{chain}[music];"
                 f"[0:a][music]amix=inputs=2:duration=first:normalize=0[{mixed_label}]")
    else:
        graph = f"[1:a]{chain}[{mixed_label}]"
    if target_lufs is not None:
        graph += f";[mixed]loudnorm=I={target_lufs:g}:TP=-1.5:print_format=none[aout]"
    return [
        "ffmpeg", "-y", "-v", "error", "-nostdin", "-progress", "pipe:1", "-nostats",
        "-i", str(video), "-stream_loop", "-1", "-i", str(music),
        "-filter_complex", graph,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", f"{duration:.3f}", "-movflags", "+faststart", str(output),
    ]


def _run(cmd: list[str], duration: float, on_progress: Optional[Callable[[int], None]]) -> None:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    last = -1
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            key, _, value = line.strip().partition("=")
            if key in {"out_time_us", "out_time_ms"} and on_progress and duration > 0:
                try:
                    seconds = int(value) / 1_000_000
                except ValueError:
                    continue
                pct = min(99, max(0, int(seconds / duration * 100)))
                if pct != last:
                    last = pct
                    on_progress(pct)
        stderr = proc.stderr.read() if proc.stderr else ""
        code = proc.wait()
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    if code != 0:
        raise MusicMixError(f"ffmpeg failed: {stderr.strip()[-500:] or code}")


def mix_music(video_path: Path, music_path: Path, output_path: Path, *,
              volume_level: float = DEFAULT_VOLUME, fade_in_seconds: float = DEFAULT_FADE_IN,
              fade_out_seconds: float = DEFAULT_FADE_OUT,
              target_lufs: float | None = None,
              on_progress: Optional[Callable[[int], None]] = None) -> Path:
    """Mix `music_path` into `video_path`; the output is written atomically."""
    video_path, music_path, output_path = Path(video_path), Path(music_path), Path(output_path)
    volume, fade_in, fade_out = validate_params(volume_level, fade_in_seconds, fade_out_seconds)
    if not video_path.is_file():
        raise MusicMixError("rendered video not found")
    if not music_path.is_file():
        raise MusicMixError("music file not found")
    try:
        probe_music(music_path)
        duration = probe_duration(video_path)
        source_audio = has_audio(video_path)
    except ValueError as exc:
        raise MusicMixError(str(exc)) from exc
    except Exception as exc:
        raise MusicMixError("video cannot be read") from exc
    if duration <= 0:
        raise MusicMixError("video has no duration")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial = output_path.with_name(f".{uuid.uuid4().hex[:8]}.{output_path.name}")
    cmd = build_command(video_path, music_path, partial, duration=duration, video_has_audio=source_audio,
                        volume=volume, fade_in=fade_in, fade_out=fade_out,
                        target_lufs=target_lufs)
    try:
        _run(cmd, duration, on_progress)
        partial.replace(output_path)
    finally:
        partial.unlink(missing_ok=True)
    return output_path


def build_preview(video_path: Optional[Path], music_path: Path, output_path: Path, *,
                  volume_level: float = DEFAULT_VOLUME, fade_in_seconds: float = DEFAULT_FADE_IN,
                  fade_out_seconds: float = DEFAULT_FADE_OUT, seconds: float = PREVIEW_SECONDS) -> Path:
    """Write an audio-only (m4a) preview of the first `seconds` of the mix.

    The fade-out is only applied when the whole video fits in the preview;
    otherwise it would play at the 30s cut, not at the real end.
    """
    music_path, output_path = Path(music_path), Path(output_path)
    volume, fade_in, fade_out = validate_params(volume_level, fade_in_seconds, fade_out_seconds)
    try:
        probe_music(music_path)
        total = probe_duration(Path(video_path)) if video_path else seconds
        source_audio = bool(video_path) and has_audio(Path(video_path))
    except ValueError as exc:
        raise MusicMixError(str(exc)) from exc
    except Exception as exc:
        raise MusicMixError("video cannot be read") from exc
    length = min(total, seconds)
    if total > seconds:
        fade_out = 0.0
    chain = music_filter(length, volume, fade_in, fade_out)
    cmd = ["ffmpeg", "-y", "-v", "error", "-nostdin"]
    if source_audio:
        cmd += ["-t", f"{length:.3f}", "-i", str(video_path)]
    cmd += ["-stream_loop", "-1", "-i", str(music_path)]
    if source_audio:
        graph = f"[1:a]{chain}[music];[0:a]atrim=0:{length:.3f}[voice];[voice][music]amix=inputs=2:duration=first:normalize=0[aout]"
    else:
        graph = f"[0:a]{chain}[aout]"  # music is the only input
    cmd += ["-filter_complex", graph, "-map", "[aout]", "-vn", "-c:a", "aac", "-b:a", "128k",
            "-t", f"{length:.3f}", str(output_path)]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run(cmd, length, None)
    except BaseException:
        output_path.unlink(missing_ok=True)
        raise
    return output_path


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # redirects could bypass the address check
        return None


def _assert_public_host(host: str) -> None:
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise MusicMixError("music URL host cannot be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if not ip.is_global:
            raise MusicMixError("music URL must point to a public host")


def fetch_music_url(url: str, dest_dir: Path, *, timeout: float = 30.0) -> Path:
    """Download an http(s) audio file into `dest_dir` (public hosts only, size-capped)."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise MusicMixError("music URL must be http or https")
    ext = Path(parsed.path).suffix.lower()
    if ext not in MUSIC_EXTENSIONS:
        raise MusicMixError("music URL must end in mp3, wav, ogg, m4a, or aac")
    _assert_public_host(parsed.hostname)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"attached_{uuid.uuid4().hex[:8]}{ext}"
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(urllib.request.Request(url), timeout=timeout) as response, open(target, "wb") as out:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_MUSIC_BYTES:
                    raise MusicMixError("music file must be at most 100 MB")
                out.write(chunk)
        probe_music(target)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        target.unlink(missing_ok=True)
        raise MusicMixError(f"music download failed: {exc}") from exc
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def mix_job_music(job_id: str, music_file_path: Optional[str | Path] = None, music_url: Optional[str] = None, *,
                  volume_level: float = DEFAULT_VOLUME, fade_in_seconds: float = DEFAULT_FADE_IN,
                  fade_out_seconds: float = DEFAULT_FADE_OUT,
                  on_progress: Optional[Callable[[int], None]] = None) -> Path:
    """Mix music into a job's latest render and return the mixed file path.

    `music_file_path` is relative to the job directory (or absolute inside it);
    `music_url` is downloaded into the job's music folder. The render itself
    (`render.output`) is never replaced; the mix is written next to it as
    `<render>_music.mp4`.
    """
    from app import jobs as jobstore

    job = jobstore.get(job_id)
    if job is None:
        raise MusicMixError("job not found")
    if job.render.status != "done" or not job.render.output:
        raise MusicMixError("render the video before mixing music")
    if bool(music_file_path) == bool(music_url):
        raise MusicMixError("provide exactly one of music_file_path or music_url")
    if music_url:
        music = fetch_music_url(music_url, job.dir / "music")
    else:
        music = Path(music_file_path)
        music = music if music.is_absolute() else job.dir / music
        if not music.resolve().is_relative_to(job.dir.resolve()):
            raise MusicMixError("music file must be inside the job directory")
    video = job.dir / "exports" / job.render.output
    output = video.with_name(f"{video.stem}_music.mp4")
    target_lufs = music_target_lufs(job)
    return mix_music(video, music, output, volume_level=volume_level, fade_in_seconds=fade_in_seconds,
                     fade_out_seconds=fade_out_seconds, target_lufs=target_lufs,
                     on_progress=on_progress)


def music_target_lufs(job) -> float | None:
    """Use the same pinned render style and normalization choice for post-mix."""
    if not job.render.loudnorm:
        return None
    import json
    from engine.captions import load_style
    style_name = (job.plan_data or {}).get("style") or "rafiei_reel"
    style = load_style(style_name)
    selection_path = job.dir / "style_selection.json"
    if selection_path.exists():
        from engine.style_library import resolve_preset
        selection = json.loads(selection_path.read_text())
        style = resolve_preset(selection["style_id"], int(selection["version"]))
    return float(style.get("render", {}).get("loudness_lufs", -14))

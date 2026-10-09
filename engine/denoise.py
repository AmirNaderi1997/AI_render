"""Speech denoiser using ffmpeg built-in filters.

Extracts speech audio from video, applies noise reduction (afftdn),
and generates A/B comparison samples. Original audio is never modified.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional


# Preset name -> (afftdn noise floor dB, representative 0..1 strength)
STRENGTH_PRESETS: dict[str, tuple[int, float]] = {
    "light": (-20, 0.25),
    "medium": (-30, 0.5),
    "heavy": (-40, 0.9),
}
VOICE_FILTER = "highpass=f=80,lowpass=f=8000"


def preset_strength(level: str) -> float:
    """Return the 0..1 strength that represents a light/medium/heavy preset."""
    try:
        return STRENGTH_PRESETS[level][1]
    except KeyError:
        raise ValueError(f"strength must be one of {sorted(STRENGTH_PRESETS)}") from None


def _ffmpeg() -> str:
    p = shutil.which("ffmpeg")
    if not p:
        raise RuntimeError("ffmpeg not found on PATH")
    return p


def _ffprobe() -> str:
    p = shutil.which("ffprobe")
    if not p:
        raise RuntimeError("ffprobe not found on PATH")
    return p


def _probe_audio(path: Path) -> dict:
    """Return audio stream info: duration, sample_rate, channels."""
    proc = subprocess.run(
        [_ffprobe(), "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", "-select_streams", "a:0", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(proc.stdout)
    streams = data.get("streams", [])
    if not streams:
        return {}
    s = streams[0]
    return {
        "duration": float(s.get("duration") or data.get("format", {}).get("duration") or 0),
        "sample_rate": int(s.get("sample_rate", 44100)),
        "channels": int(s.get("channels", 1)),
    }


def extract_speech_audio(video_path: Path, out_dir: Optional[Path] = None) -> Path:
    """Extract audio track from video as WAV. Returns path to extracted audio."""
    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"source not found: {video_path}")

    if out_dir is None:
        out_dir = video_path.parent
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / "speech_original.wav"

    info = _probe_audio(video_path)
    if not info:
        raise RuntimeError("no audio stream found in source")

    cmd = [
        _ffmpeg(), "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le",
        "-ar", str(info.get("sample_rate", 44100)),
        "-ac", str(info.get("channels", 1)),
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def denoise_speech(audio_path: Path, strength: float = 0.5,
                   out_dir: Optional[Path] = None,
                   level: Optional[str] = None,
                   preserve_voice: bool = True) -> Path:
    """Apply noise reduction to speech audio. Returns path to cleaned file.

    level: "light" | "medium" | "heavy" -> afftdn=nf=-20/-30/-40 (takes precedence).
    strength: 0.0 (bypass) to 1.0 (maximum cleaning), used when level is None.
    preserve_voice: band-limit to 80-8000 Hz before denoising to protect speech.
    """
    audio_path = Path(audio_path)
    if not audio_path.is_file():
        raise FileNotFoundError(f"audio not found: {audio_path}")

    if level is not None:
        if level not in STRENGTH_PRESETS:
            raise ValueError(f"strength must be one of {sorted(STRENGTH_PRESETS)}")
        strength = STRENGTH_PRESETS[level][1]
    strength = max(0.0, min(1.0, strength))

    if out_dir is None:
        out_dir = audio_path.parent
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"speech_cleaned_{level or format(strength, '.2f')}.wav"

    if level is None and strength < 0.01:
        shutil.copy2(audio_path, out_path)
        return out_path

    if level is not None:
        afftdn = f"afftdn=nf={STRENGTH_PRESETS[level][0]}"
    else:
        # Map strength 0..1 to noise reduction 6..40 dB, noise floor -40..-80
        afftdn = f"afftdn=nr={6 + strength * 34:.0f}:nf={-40 - strength * 40:.0f}"
    chain = f"{VOICE_FILTER},{afftdn}" if preserve_voice else afftdn

    cmd = [_ffmpeg(), "-y", "-i", str(audio_path), "-af", chain, str(out_path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def remux_with_video(video_path: Path, audio_path: Path, out_path: Path) -> Path:
    """Write a copy of the video with its audio replaced; the original is untouched."""
    video_path, audio_path, out_path = Path(video_path), Path(audio_path), Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _ffmpeg(), "-y", "-i", str(video_path), "-i", str(audio_path),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
        "-shortest", str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def _detect_speech_offset(audio_path: Path) -> float:
    """Find a non-silent segment using ffmpeg silencedetect. Returns offset in seconds."""
    cmd = [
        _ffmpeg(), "-i", str(audio_path),
        "-af", "silencedetect=noise=-30dB:d=0.3",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    stderr = proc.stderr

    # Parse silence_end timestamps to find where speech starts
    ends = re.findall(r"silence_end:\s*([\d.]+)", stderr)
    if ends:
        return max(0.0, float(ends[0]) - 0.5)

    # No silence detected = audio is all speech; start at 1s
    info = _probe_audio(audio_path)
    dur = info.get("duration", 5.0)
    return min(1.0, dur * 0.2)


def generate_ab_samples(original_path: Path, cleaned_path: Path,
                        sample_duration: float = 5.0,
                        sample_offset: Optional[float] = None) -> dict:
    """Extract short A/B comparison clips from both versions at the same timestamp."""
    original_path = Path(original_path)
    cleaned_path = Path(cleaned_path)

    if sample_offset is None:
        sample_offset = _detect_speech_offset(original_path)

    info = _probe_audio(original_path)
    dur = info.get("duration", 10.0)
    if dur <= 0:
        raise ValueError("audio has no positive duration for A/B samples")

    sample_offset = max(0.0, min(float(sample_offset), max(0.0, dur - 0.05)))
    sample_duration = min(sample_duration, dur - sample_offset)
    if sample_duration < min(0.5, dur):
        sample_offset = 0.0
        sample_duration = min(5.0, dur)

    out_dir = original_path.parent
    orig_sample = out_dir / "sample_original.wav"
    clean_sample = out_dir / "sample_cleaned.wav"

    for src, dst in [(original_path, orig_sample), (cleaned_path, clean_sample)]:
        cmd = [
            _ffmpeg(), "-y", "-i", str(src),
            "-ss", f"{sample_offset:.3f}",
            "-t", f"{sample_duration:.3f}",
            "-acodec", "pcm_s16le",
            str(dst),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    return {
        "original_sample": orig_sample,
        "cleaned_sample": clean_sample,
        "offset_s": sample_offset,
        "duration_s": sample_duration,
    }


def measure_quality(original_path: Path, cleaned_path: Path) -> dict:
    """Measure loudness and basic quality metrics for both versions."""
    original_path = Path(original_path)
    cleaned_path = Path(cleaned_path)

    def lufs(path: Path) -> Optional[float]:
        cmd = [
            _ffmpeg(), "-nostats", "-i", str(path),
            "-af", "ebur128=peak=true", "-f", "null", "-",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        m = re.search(r"I:\s+(-?\d+(?:\.\d+)?)\s+LUFS", proc.stderr)
        return float(m.group(1)) if m else None

    orig_info = _probe_audio(original_path)
    clean_info = _probe_audio(cleaned_path)

    return {
        "loudness_original": lufs(original_path),
        "loudness_cleaned": lufs(cleaned_path),
        "duration_match": abs(orig_info.get("duration", 0) - clean_info.get("duration", 0)) < 0.1,
        "sample_rate_match": orig_info.get("sample_rate") == clean_info.get("sample_rate"),
        "original_duration": orig_info.get("duration"),
        "cleaned_duration": clean_info.get("duration"),
    }


def detect_silence(audio_path: Path, threshold_db: float = -35, min_duration: float = 0.5) -> bool:
    """Return True if the audio is entirely (or nearly entirely) silent."""
    info = _probe_audio(audio_path)
    dur = info.get("duration", 0)
    if dur <= 0:
        return True
    detection_window = min(min_duration, max(0.01, dur / 2))
    cmd = [
        _ffmpeg(), "-i", str(audio_path),
        "-af", f"silencedetect=noise={threshold_db}dB:d={detection_window}",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    # Check if silence covers >90% of audio
    starts = re.findall(r"silence_start:\s*([\d.]+)", proc.stderr)
    ends = re.findall(r"silence_end:\s*([\d.]+)", proc.stderr)
    silent_time = 0.0
    for s, e in zip(starts, ends):
        silent_time += float(e) - float(s)
    # If silence_start exists without matching end, silence goes to the end
    if len(starts) > len(ends):
        silent_time += dur - float(starts[-1])

    return silent_time > dur * 0.9

"""Fast, deterministic checks on every finished export.

These checks cover file integrity and sound level. Creative quality and
caption accuracy still require watching and listening to the result.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from .probe import probe


def inspect_export(path: Path, *, width: int, height: int, fps: int,
                   duration: float, target_lufs: float | None) -> dict:
    info = probe(path)
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if not video:
        raise RuntimeError("export has no playable video stream")
    actual_size = [int(video.get("width") or 0), int(video.get("height") or 0)]
    if actual_size != [width, height]:
        raise RuntimeError(f"export size {actual_size} differs from plan {width}x{height}")
    actual_duration = float(video.get("duration") or info.get("format", {}).get("duration") or 0)
    if actual_duration <= 0 or abs(actual_duration - duration) > max(0.25, 2 / fps):
        raise RuntimeError(f"export duration {actual_duration:.2f}s differs from plan {duration:.2f}s")
    actual_fps = float(Fraction(video.get("avg_frame_rate") or "0/1"))
    if abs(actual_fps - fps) > 0.02:
        raise RuntimeError(f"export frame rate {actual_fps:.2f} differs from plan {fps}")

    warnings: list[str] = []
    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    loudness = None
    true_peak = None
    if audio and shutil.which("ffmpeg"):
        result = subprocess.run([
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
            "-vn", "-af", "ebur128=peak=true", "-f", "null", "-",
        ], capture_output=True, text=True)
        if result.returncode == 0:
            summary = result.stderr.rsplit("Summary:", 1)[-1]
            lufs_match = re.search(r"\bI:\s*(-?\d+(?:\.\d+)?)\s*LUFS", summary)
            peak_match = re.search(r"\bPeak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", summary)
            if lufs_match:
                loudness = float(lufs_match.group(1))
            if peak_match:
                true_peak = float(peak_match.group(1))
    if target_lufs is not None and loudness is not None and abs(loudness - target_lufs) > 2.5:
        warnings.append(f"Audio is {loudness:.1f} LUFS; target is {target_lufs:.1f} LUFS.")
    if true_peak is not None and true_peak > -1.0:
        warnings.append(f"Audio true peak is {true_peak:.1f} dBFS; inspect for clipping.")

    return {
        "width": actual_size[0], "height": actual_size[1],
        "fps": video.get("avg_frame_rate"), "duration_seconds": round(actual_duration, 3),
        "video_codec": video.get("codec_name"), "audio_codec": audio.get("codec_name") if audio else None,
        "loudness_lufs": loudness, "true_peak_dbfs": true_peak, "warnings": warnings,
    }

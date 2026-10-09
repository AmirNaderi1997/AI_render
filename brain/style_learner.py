"""Reference reel analyzer — extracts editing style metrics from finished reels.

Uses ffprobe/ffmpeg for cut detection, duration analysis, and audio levels.
No heavy ML models — relies on scene_detect filter and basic signal processing.
"""
from __future__ import annotations

import json
import logging
import math
import re
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode:
        raise RuntimeError(f"ffprobe failed: {r.stderr[:200]}")
    duration = float(json.loads(r.stdout)["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("reference reel must have a positive finite duration")
    return duration


def _require_video_stream(path: Path) -> None:
    """Reject audio-only inputs before scene detection silently returns no cuts."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_type", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode:
        raise RuntimeError(f"ffprobe failed: {r.stderr[:200]}")
    streams = json.loads(r.stdout).get("streams", [])
    if not any(stream.get("codec_type") == "video" for stream in streams):
        raise ValueError("reference reel contains no video stream")


def _detect_cuts(path: Path, threshold: float = 0.3) -> list[float]:
    """Use ffmpeg scene detection filter to find cut points."""
    r = subprocess.run(
        ["ffmpeg", "-i", str(path), "-vf",
         f"select='gt(scene,{threshold})',showinfo", "-vsync", "vfr",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=120,
    )
    cuts = []
    for match in re.finditer(r"pts_time:([\d.]+)", r.stderr):
        cuts.append(float(match.group(1)))
    return sorted(set(cuts))


def _measure_audio(path: Path) -> dict:
    """Measure audio volume levels."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-vn",
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, timeout=60,
    )
    mean = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", r.stderr)
    peak = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", r.stderr)
    return {
        "mean_volume_db": float(mean.group(1)) if mean else None,
        "max_volume_db": float(peak.group(1)) if peak else None,
    }


def _segment_durations(cuts: list[float], total_duration: float) -> list[float]:
    """Convert cut timestamps to segment durations."""
    points = [0.0] + cuts + [total_duration]
    return [points[i + 1] - points[i] for i in range(len(points) - 1) if points[i + 1] - points[i] > 0.1]


def analyze_reference(path: Path, scene_threshold: float = 0.3) -> dict:
    """Analyze a single reference reel and extract style metrics.

    Returns a StyleProfile dict with:
    - cut_lengths: avg/min/max/median segment durations
    - cut_count: number of cuts detected
    - total_duration: video length
    - pacing: energy curve (early/mid/late avg cut length)
    - audio: volume levels
    - zoom_usage: estimated from motion between frames (placeholder)
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"reference reel not found: {path}")

    _require_video_stream(path)
    duration = _probe_duration(path)
    cuts = _detect_cuts(path, threshold=scene_threshold)
    segments = _segment_durations(cuts, duration)
    audio = _measure_audio(path)

    if not segments:
        segments = [duration]

    sorted_segs = sorted(segments)
    mid = len(sorted_segs) // 2
    median = sorted_segs[mid] if len(sorted_segs) % 2 else (sorted_segs[mid - 1] + sorted_segs[mid]) / 2

    # Pacing curve: split into thirds
    third = len(segments) // 3 or 1
    early = segments[:third]
    mid_segs = segments[third:2 * third]
    late = segments[2 * third:]

    def avg(lst: list[float]) -> float:
        return round(sum(lst) / len(lst), 3) if lst else 0.0

    # Caption density estimate: assume ~2 words/sec of speech
    estimated_caption_density = round(2.0 / avg(segments), 2) if avg(segments) > 0 else 0.0

    profile: dict = {
        "source_file": path.name,
        "total_duration": round(duration, 3),
        "cut_count": len(cuts),
        "cut_lengths": {
            "avg": round(avg(segments), 3),
            "min": round(min(segments), 3),
            "max": round(max(segments), 3),
            "median": round(median, 3),
            "stddev": round(_stddev(segments), 3),
        },
        "segment_count": len(segments),
        "pacing": {
            "early_avg": round(avg(early), 3),
            "mid_avg": round(avg(mid_segs), 3),
            "late_avg": round(avg(late), 3),
            "trend": _pacing_trend(early, mid_segs, late),
        },
        "audio": audio,
        "estimated_caption_density_wps": estimated_caption_density,
    }
    return profile


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return variance ** 0.5


def _pacing_trend(early: list[float], mid: list[float], late: list[float]) -> str:
    """Classify pacing as accelerating, decelerating, steady, or variable."""
    def avg(lst: list[float]) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    e, m, l = avg(early), avg(mid), avg(late)
    if not (e and m and l):
        return "unknown"
    if e > m > l:
        return "accelerating"
    if e < m < l:
        return "decelerating"
    if abs(e - l) < 0.3:
        return "steady"
    return "variable"

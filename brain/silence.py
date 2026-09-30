"""Detect pauses / silence and compute keep/remove ranges.

Combines ffmpeg silencedetect with gaps between Whisper words.
All thresholds come from presets/rafiei_reel.yaml → silence.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

import yaml

from engine.schema import PROJECT_ROOT

log = logging.getLogger(__name__)


def load_silence_cfg(preset: str = "rafiei_reel") -> dict:
    path = PROJECT_ROOT / "presets" / f"{preset}.yaml"
    style = yaml.safe_load(path.read_text())
    return style.get("silence", {})


def ffmpeg_silence_ranges(
    video: Path,
    noise_db: float = -35,
    min_dur: float = 0.4,
) -> list[tuple[float, float]]:
    """Run ffmpeg silencedetect and return [(start, end), …]."""
    cmd = [
        "ffmpeg", "-i", str(video), "-hide_banner",
        "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    text = proc.stderr

    starts: list[float] = []
    ends: list[float] = []
    for m in re.finditer(r"silence_start:\s*([\d.]+)", text):
        starts.append(float(m.group(1)))
    for m in re.finditer(r"silence_end:\s*([\d.]+)", text):
        ends.append(float(m.group(1)))

    ranges = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else s + min_dur
        ranges.append((round(s, 3), round(e, 3)))
    return ranges


def word_gap_ranges(
    words: list[dict],
    min_gap: float = 0.4,
) -> list[tuple[float, float]]:
    """Find gaps between consecutive words exceeding *min_gap*."""
    ranges = []
    for i in range(1, len(words)):
        gap_start = words[i - 1]["end"]
        gap_end = words[i]["start"]
        if gap_end - gap_start >= min_gap:
            ranges.append((round(gap_start, 3), round(gap_end, 3)))
    return ranges


def merge_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge overlapping or adjacent ranges."""
    if not ranges:
        return []
    sr = sorted(ranges)
    merged = [sr[0]]
    for s, e in sr[1:]:
        if s <= merged[-1][1] + 0.01:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def detect_pauses(
    video: Path,
    words: list[dict],
    preset: str = "rafiei_reel",
) -> dict:
    """Return {remove: [(start,end)], keep: [(start,end)]} ranges in source time.

    Combines ffmpeg silence detection with Whisper word gaps.
    Applies padding around speech boundaries.
    """
    cfg = load_silence_cfg(preset)
    min_pause = float(cfg.get("min_pause_sec", 0.4))
    padding = float(cfg.get("padding_sec", 0.08))
    noise_db = float(cfg.get("noise_db", -35))

    ff_ranges = ffmpeg_silence_ranges(video, noise_db=noise_db, min_dur=min_pause)
    wg_ranges = word_gap_ranges(words, min_gap=min_pause)

    all_pauses = merge_ranges(ff_ranges + wg_ranges)

    if not words:
        return {"remove": all_pauses, "keep": []}

    duration = words[-1]["end"] + 0.5

    remove = []
    for s, e in all_pauses:
        rs = round(s + padding, 3)
        re_ = round(max(e - padding, rs + 0.01), 3)
        if re_ - rs >= 0.05:
            remove.append((rs, re_))

    keep = _invert(remove, 0.0, duration)
    return {"remove": remove, "keep": keep}


def _invert(
    ranges: list[tuple[float, float]],
    start: float,
    end: float,
) -> list[tuple[float, float]]:
    """Return the complement of *ranges* within [start, end]."""
    if not ranges:
        return [(start, end)]
    result = []
    cursor = start
    for s, e in sorted(ranges):
        if s > cursor:
            result.append((round(cursor, 3), round(s, 3)))
        cursor = max(cursor, e)
    if cursor < end:
        result.append((round(cursor, 3), round(end, 3)))
    return result

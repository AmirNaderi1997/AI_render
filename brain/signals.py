"""Measure audio signals per video segment: loudness and speech rate.

Used to enrich segment analysis for smarter effect selection.
All measurements are graceful — any failure returns None for that field.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def _ffmpeg_loudness(video: Path, start: float, duration: float) -> Optional[float]:
    """Return integrated loudness (LUFS) for a time range using ffmpeg ebur128."""
    if duration < 0.1:
        return None
    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(round(start, 3)),
            "-t", str(round(duration, 3)),
            "-i", str(video),
            "-af", "ebur128=framelog=verbose",
            "-f", "null", "-",
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        # ebur128 prints "I:" integrated loudness in the summary
        for line in reversed(result.stderr.splitlines()):
            if "I:" in line and "LUFS" in line:
                parts = line.split("I:")
                if len(parts) == 2:
                    val = parts[1].strip().split()[0]
                    return round(float(val), 1)
    except Exception as exc:
        log.debug("ebur128 failed for %s @%.2f: %s", video.name, start, exc)
    return None


def _speech_rate(words: list[dict], seg_in: float, seg_out: float) -> Optional[float]:
    """Return words-per-second for words that fall within [seg_in, seg_out]."""
    seg_words = [
        w for w in words
        if seg_in - 0.05 <= w.get("start", 0) <= seg_out + 0.05
    ]
    if not seg_words:
        return None
    duration = seg_out - seg_in
    if duration < 0.1:
        return None
    return round(len(seg_words) / duration, 2)


def measure_segment_signals(
    video: Path,
    segments: list[dict],
    transcript: dict,
) -> list[dict]:
    """Return [{segment_id, loudness_lufs, speech_rate_wps}] for each segment.

    Both fields may be None if measurement fails.
    """
    words = transcript.get("words", [])
    results: list[dict] = []

    for seg in segments:
        seg_id = seg.get("id", "")
        seg_in = seg.get("in", 0.0)
        seg_out = seg.get("out", 0.0)
        duration = seg_out - seg_in

        loudness = _ffmpeg_loudness(video, seg_in, duration)
        rate = _speech_rate(words, seg_in, seg_out)

        results.append({
            "segment_id": seg_id,
            "loudness_lufs": loudness,
            "speech_rate_wps": rate,
        })

    measured = sum(1 for r in results if r["loudness_lufs"] is not None)
    log.info("signals: measured %d/%d segments", measured, len(segments))
    return results

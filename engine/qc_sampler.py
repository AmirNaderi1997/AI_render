"""QC Frame & Audio Sampler — extract keyframes and audio clips from rendered MP4."""
from __future__ import annotations

import subprocess
import shutil
from pathlib import Path
from typing import Optional

from .schema import EditPlan


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


def sample_keyframes(
    video: Path,
    plan: EditPlan,
    out_dir: Path,
    extra_times: Optional[list[float]] = None,
) -> list[dict]:
    """Extract keyframes at segment midpoints and transition boundaries.

    Returns list of {time, path, label} dicts sorted by time.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    times: list[tuple[float, str]] = []

    # Segment midpoints (in output timeline)
    cursor = 0.0
    fps = plan.canvas.fps
    trans_map = {(t.from_segment_id, t.to_segment_id): t for t in plan.transitions}
    for i, seg in enumerate(plan.segments):
        seg_frames = round(seg.duration * fps)
        seg_dur = seg_frames / fps
        mid = cursor + seg_dur / 2
        times.append((mid, f"seg_{seg.id}_mid"))
        cursor += seg_dur
        if i < len(plan.segments) - 1:
            pair = (seg.id, plan.segments[i + 1].id)
            tr = trans_map.get(pair)
            if tr and tr.duration_frames > 0:
                overlap = tr.duration_frames / fps
                boundary = cursor - overlap / 2
                times.append((boundary, f"tr_{seg.id}_{plan.segments[i + 1].id}"))
                cursor -= overlap

    if extra_times:
        for t in extra_times:
            times.append((t, f"extra_{t:.2f}"))

    times = sorted(set(times), key=lambda x: x[0])
    dur = plan.output_duration
    times = [(t, l) for t, l in times if 0 <= t < dur]

    results = []
    for t, label in times:
        out_path = out_dir / f"{label}.jpg"
        subprocess.run(
            [_ffmpeg(), "-y", "-ss", f"{t:.3f}", "-i", str(video),
             "-frames:v", "1", "-q:v", "2", str(out_path)],
            capture_output=True, check=True,
        )
        if out_path.exists():
            results.append({"time": round(t, 3), "path": str(out_path), "label": label})

    return results


def sample_audio_clips(
    video: Path,
    plan: EditPlan,
    out_dir: Path,
    clip_duration: float = 2.0,
) -> list[dict]:
    """Extract short audio clips at caption positions for loudness checks.

    Returns list of {time, path, label} dicts.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    dur = plan.output_duration

    for i, cap in enumerate(plan.captions):
        mid = (cap.start + cap.end) / 2
        start = max(0, mid - clip_duration / 2)
        length = min(clip_duration, dur - start)
        if length <= 0:
            continue
        out_path = out_dir / f"audio_cap_{i}.wav"
        subprocess.run(
            [_ffmpeg(), "-y", "-ss", f"{start:.3f}", "-i", str(video),
             "-t", f"{length:.3f}", "-vn", "-acodec", "pcm_s16le", str(out_path)],
            capture_output=True, check=True,
        )
        if out_path.exists():
            results.append({"time": round(mid, 3), "path": str(out_path), "label": f"cap_{i}"})

    return results


def measure_clip_lufs(wav_path: Path) -> Optional[float]:
    """Measure integrated LUFS of a short audio clip."""
    import re
    proc = subprocess.run(
        [_ffmpeg(), "-nostats", "-i", str(wav_path),
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = re.search(r"I:\s+(-?\d+(?:\.\d+)?)\s+LUFS", proc.stderr)
    return float(m.group(1)) if m else None

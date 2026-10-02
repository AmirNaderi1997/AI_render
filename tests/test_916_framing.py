"""Tests for 9:16 framing: 16:9 source must fill 1080x1920 with no black bars."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


needs_ffmpeg = pytest.mark.skipif(not _has("ffmpeg"), reason="ffmpeg not on PATH")
needs_melt = pytest.mark.skipif(not _has("melt") and not _has("melt-7"),
                                reason="melt not on PATH")


def _make_16x9_clip(path: Path, duration: float = 2.0) -> Path:
    """Generate a 1920x1080 (16:9) red clip."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"color=c=red:size=1920x1080:d={duration}:r=30",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", str(duration),
         str(path)],
        check=True, capture_output=True,
    )
    return path


@needs_ffmpeg
@needs_melt
def test_16x9_fills_frame_no_black_bars(tmp_path):
    """A 16:9 source rendered to 1080x1920 must have NO black (all-zero) rows."""
    clip = _make_16x9_clip(tmp_path / "raw.mp4")

    plan_data = {
        "version": "0.2",
        "style": "rafiei_reel",
        "canvas": {"width": 1080, "height": 1920, "fps": 30},
        "source": str(clip),
        "segments": [{"id": "s1", "in": 0, "out": 1.0}],
        "visual_effects": [],
        "captions": [],
        "broll": [],
        "music": None,
        "sfx": [],
        "export": {"file": str(tmp_path / "out.mp4"), "crf": 23},
    }
    (tmp_path / "plan.json").write_text(json.dumps(plan_data))

    from engine.schema import validate_plan
    plan, errs = validate_plan(plan_data, base_dir=tmp_path, check_media=True)
    assert plan is not None, f"plan validation failed: {errs}"

    from engine.build_mlt import build
    mlt_path, _ = build(plan, tmp_path, base_dir=tmp_path)

    from engine.render import render
    out = render(mlt_path, tmp_path / "out.mp4", preview=True)
    assert out.exists()

    # Extract frame 15 (middle) as raw RGB
    frame_path = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(out), "-vf", "select=eq(n\\,15)",
         "-frames:v", "1", str(frame_path)],
        check=True, capture_output=True,
    )
    assert frame_path.exists()

    # Use ffmpeg to sample top-row and bottom-row average brightness
    for label, crop_y in [("top", 0), ("bottom", None)]:
        crop_filter = f"select=eq(n\\,15),crop=iw:2:0:{crop_y if crop_y is not None else 'ih-2'}"
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(out), "-vf", crop_filter,
             "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True,
        )
        raw = r.stdout
        assert len(raw) > 0, f"No pixel data for {label} row"
        avg = sum(raw) / len(raw)
        assert avg > 10, f"{label} row avg brightness={avg:.1f} — black bars detected"


@needs_ffmpeg
def test_punch_in_scale_difference():
    """Punch-in effect must produce >= 5% scale difference in the affine rect."""
    from engine.effects import effect_filter_xml

    xml = effect_filter_xml("punch__neutral", frames=30, width=1080, height=1920,
                            punch_frames=6, cover_scale=1.0)

    rects = re.findall(r'(-?\d+)\s+(-?\d+)\s+(\d+)\s+(\d+)\s+\d', xml)
    assert len(rects) >= 2, f"Expected >=2 keyframes, got {len(rects)}"

    w_start = int(rects[0][2])
    w_end = int(rects[1][2])
    scale_change = abs(w_end - w_start) / w_start
    assert scale_change >= 0.05, (
        f"Punch-in scale change is only {scale_change:.1%} — must be >= 5%"
    )


@needs_ffmpeg
def test_cover_scale_16x9_on_9x16():
    """cover_scale for 16:9 on 9:16 canvas should be ~3.16."""
    from engine.probe import cover_scale
    cs = cover_scale(1920, 1080, 1080, 1920)
    assert cs > 3.0, f"cover_scale={cs}, expected > 3.0 for 16:9 → 9:16"
    assert cs < 3.5, f"cover_scale={cs}, unexpectedly large"


def test_cover_scale_same_aspect():
    """Same aspect ratio source → cover_scale = 1.0."""
    from engine.probe import cover_scale
    assert cover_scale(1080, 1920, 1080, 1920) == 1.0

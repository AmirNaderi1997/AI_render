"""ffprobe wrappers."""
import json
import subprocess
from pathlib import Path


def probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def probe(path: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(r.stdout)


def has_audio(path: Path) -> bool:
    for s in probe(path).get("streams", []):
        if s.get("codec_type") == "audio":
            return True
    return False


def video_stream(path: Path) -> dict:
    for s in probe(path).get("streams", []):
        if s.get("codec_type") == "video":
            return s
    raise ValueError(f"no video stream in {path}")


def video_dimensions(path: Path) -> tuple[int, int]:
    """Return (width, height) of the first video stream."""
    s = video_stream(path)
    return int(s["width"]), int(s["height"])


def cover_scale(src_w: int, src_h: int, canvas_w: int, canvas_h: int) -> float:
    """Compute the zoom factor so the source covers the canvas (no black bars).

    After MLT fits the source into the profile (preserving AR), the source may
    be letterboxed.  This returns the affine zoom needed to make the source
    fill the canvas, cropping the excess.
    """
    src_aspect = src_w / src_h
    canvas_aspect = canvas_w / canvas_h
    if abs(src_aspect - canvas_aspect) < 0.01:
        return 1.0
    if src_aspect > canvas_aspect:
        return (canvas_h * src_aspect) / canvas_w
    else:
        return canvas_w / (canvas_h * src_aspect)

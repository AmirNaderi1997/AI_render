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

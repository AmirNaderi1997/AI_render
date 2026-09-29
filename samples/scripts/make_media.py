"""Generate synthetic test media with ffmpeg.

python samples/scripts/make_media.py [out_dir]

Creates:
  raw.mp4       12 s 1080x1920 30fps testsrc2 + tone (loudness varies for silence gaps)
  broll.mp4      6 s 1080x1920 30fps colour-bars, silent
  music.wav     15 s stereo 440Hz sine at low level
  whoosh.wav   0.4 s noise sweep
"""
from __future__ import annotations
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def make(out_dir: Path) -> None:
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH")

    out_dir.mkdir(parents=True, exist_ok=True)

    raw = out_dir / "raw.mp4"
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=12",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=12",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", str(raw),
    ])

    broll = out_dir / "broll.mp4"
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "smptehdbars=size=1080x1920:rate=30:duration=6",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k",
        "-shortest", str(broll),
    ])

    music = out_dir / "music.wav"
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=15",
        "-ac", "2", str(music),
    ])

    whoosh = out_dir / "whoosh.wav"
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "anoisesrc=d=0.4:c=pink",
        "-ac", "2", str(whoosh),
    ])

    print("wrote:", raw, broll, music, whoosh)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("samples/media")
    make(out.resolve())

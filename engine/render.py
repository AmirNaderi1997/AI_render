"""Render a project.mlt with melt. Streams progress as 0..100 ints."""
from __future__ import annotations
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Iterator, Optional

from .captions import fonts_dir, load_style


_PROGRESS_RE = re.compile(r"percentage[: ]\s*(\d+)", re.IGNORECASE)


def melt_bin() -> str:
    """Return the melt executable, handling `melt-7` on some Homebrew installs."""
    for name in ("melt", "melt-7"):
        p = shutil.which(name)
        if p:
            return p
    raise RuntimeError("melt not found on PATH; install MLT (brew install mlt)")


def _melt_env(style: dict) -> dict:
    import os
    env = os.environ.copy()
    fd = fonts_dir(style)
    if fd:
        env["FONTCONFIG_PATH"] = str(fd)
    return env


def _run_and_stream(cmd: list[str], env: dict, on_progress: Optional[Callable[[int], None]]) -> int:
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, env=env,
    )
    assert proc.stdout is not None
    last_pct = -1
    for line in proc.stdout:
        m = _PROGRESS_RE.search(line)
        if m:
            pct = min(100, max(0, int(m.group(1))))
            if pct != last_pct and on_progress:
                on_progress(pct)
                last_pct = pct
    proc.wait()
    if on_progress and last_pct < 100 and proc.returncode == 0:
        on_progress(100)
    return proc.returncode


def _profile_from_mlt(mlt_text: str) -> tuple[int, int, int]:
    """Return (width, height, fps) parsed from the ``<profile>`` in an MLT XML.
    Defaults to 1080x1920@30 if the tag is missing.
    """
    import re
    m = re.search(r'<profile[^/>]*?width="(\d+)"', mlt_text)
    w = int(m.group(1)) if m else 1080
    m = re.search(r'<profile[^/>]*?height="(\d+)"', mlt_text)
    h = int(m.group(1)) if m else 1920
    m = re.search(r'<profile[^/>]*?frame_rate_num="(\d+)"', mlt_text)
    fps = int(m.group(1)) if m else 30
    return w, h, fps


def render(
    mlt: Path,
    out: Path,
    preview: bool = False,
    style_name: str = "rafiei_reel",
    on_progress: Optional[Callable[[int], None]] = None,
    apply_loudnorm: bool = False,
) -> Path:
    """Render mlt to out (mp4). Preview = 540x960, veryfast.

    When ``apply_loudnorm`` is set, a second pass runs ``ffmpeg -af loudnorm``
    targeting the LUFS value from the style preset (defaults to -14).
    """
    melt = melt_bin()

    style = load_style(style_name)
    render_cfg = style.get("render", {})
    crf = render_cfg.get("crf", 20)
    ab = render_cfg.get("audio_bitrate", "192k")

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    render_target = out
    if apply_loudnorm:
        # write raw melt output to a temp file next to the final path
        render_target = out.with_name(out.stem + ".raw" + out.suffix)

    src_w, src_h, src_fps = _profile_from_mlt(Path(mlt).read_text())

    cmd = [melt, str(mlt), "-progress"]
    if preview:
        # Preview at half the source dimensions (rounded to even).
        w = (src_w // 2) & ~1
        h = (src_h // 2) & ~1
        cmd += ["-consumer", f"avformat:{render_target}",
                f"width={w}", f"height={h}",
                f"frame_rate_num={src_fps}", "frame_rate_den=1",
                "sample_aspect_num=1", "sample_aspect_den=1",
                "display_aspect_num=9", "display_aspect_den=16",
                "progressive=1",
                "vcodec=libx264", "crf=26", "preset=veryfast",
                "acodec=aac", f"ab=128k"]
    else:
        cmd += ["-consumer", f"avformat:{render_target}",
                f"width={src_w}", f"height={src_h}",
                f"frame_rate_num={src_fps}", "frame_rate_den=1",
                "sample_aspect_num=1", "sample_aspect_den=1",
                "display_aspect_num=9", "display_aspect_den=16",
                "progressive=1",
                "vcodec=libx264", f"crf={crf}", "preset=medium",
                "acodec=aac", f"ab={ab}"]

    rc = _run_and_stream(cmd, _melt_env(style), on_progress)
    if rc != 0:
        raise RuntimeError(f"melt failed with exit code {rc}")

    if apply_loudnorm:
        target_lufs = float(render_cfg.get("loudness_lufs", -14))
        loudnorm(render_target, out, target_lufs=target_lufs)
        try:
            render_target.unlink()
        except OSError:
            pass
    return out


def loudnorm(src: Path, dst: Path, target_lufs: float = -14, true_peak: float = -1.5) -> Path:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH")
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src),
         "-af", f"loudnorm=I={target_lufs}:TP={true_peak}",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(dst)],
        check=True, capture_output=True,
    )
    return dst


def measure_lufs(src: Path) -> Optional[float]:
    """Return integrated LUFS reported by ffmpeg's ebur128 filter, or None."""
    if shutil.which("ffmpeg") is None:
        return None
    proc = subprocess.run(
        ["ffmpeg", "-nostats", "-i", str(src),
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    text = proc.stderr
    m = re.search(r"I:\s+(-?\d+(?:\.\d+)?)\s+LUFS", text)
    if not m:
        return None
    return float(m.group(1))

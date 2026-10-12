"""Render a project.mlt with melt. Streams progress as 0..100 ints."""
from __future__ import annotations
import hashlib
from math import gcd
import os
import platform
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Iterator, Optional

from .captions import fonts_dir, load_style


_PROGRESS_RE = re.compile(r"percentage[: ]\s*(\d+)", re.IGNORECASE)
_RAY_RENDER_FONTS = ("RAY-EXTRABLACK.TTF", "RAY-EXTRABOLD.TTF")


def melt_bin() -> str:
    """Return the melt executable, handling `melt-7` on some Homebrew installs."""
    for name in ("melt", "melt-7"):
        p = shutil.which(name)
        if p:
            return p
    raise RuntimeError("melt not found on PATH; install MLT (brew install mlt)")


def _macos_font_loader() -> Path:
    """Build and cache the CoreText loader used by Homebrew melt/Qt on macOS."""
    import fcntl

    source = Path(__file__).with_name("macos_font_loader.c")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    cache_dir = Path(tempfile.gettempdir()) / "ai-render-font-loader"
    cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    loader = cache_dir / f"font-loader-{platform.machine()}-{digest}.dylib"
    lock_path = cache_dir / "build.lock"

    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if loader.is_file():
            return loader
        clang = shutil.which("clang")
        if clang is None:
            raise RuntimeError(
                "clang is required to prepare the project-local macOS font loader"
            )
        pending = loader.with_name(f".{loader.name}.{os.getpid()}.tmp")
        try:
            subprocess.run(
                [clang, "-dynamiclib", "-O2", "-framework", "CoreFoundation",
                 "-framework", "CoreText", str(source), "-o", str(pending)],
                check=True, capture_output=True, text=True,
            )
            os.replace(pending, loader)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"failed to build macOS font loader: {exc.stderr.strip()}"
            ) from exc
        finally:
            pending.unlink(missing_ok=True)
    return loader


def _melt_env(style: dict, additional_font_files: Optional[list[Path]] = None) -> dict:
    env = os.environ.copy()
    fd = fonts_dir(style)
    font_files = [Path(p).resolve() for p in (additional_font_files or [])]
    if fd:
        font_files.extend((fd / name).resolve() for name in _RAY_RENDER_FONTS)
    font_files = list(dict.fromkeys(p for p in font_files if p.is_file()))
    if font_files and platform.system() == "Darwin":
        missing = [str(path) for path in font_files if not path.is_file()]
        if missing:
            raise RuntimeError(f"bundled render font missing: {', '.join(missing)}")
        loader = str(_macos_font_loader())
        inserted = [p for p in env.get("DYLD_INSERT_LIBRARIES", "").split(":") if p]
        if loader not in inserted:
            inserted.insert(0, loader)
        env["DYLD_INSERT_LIBRARIES"] = ":".join(inserted)
        env["AI_RENDER_FONT_FILES"] = "\n".join(str(path) for path in font_files)
        # Homebrew MLT's Qt 6 Cocoa backend uses CoreText, not fontconfig.
        env.pop("FONTCONFIG_PATH", None)
        env.pop("FONTCONFIG_FILE", None)
    elif font_files:
        # Make user-approved files visible to Fontconfig without installing
        # them system-wide. A per-process config preserves system defaults.
        import xml.sax.saxutils as xml_utils
        config_dir = Path(tempfile.gettempdir()) / "ai-render-fontconfig"
        config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        config = config_dir / "fonts.conf"
        font_dirs = sorted({p.parent for p in font_files})
        dirs = "".join(f"<dir>{xml_utils.escape(str(p))}</dir>" for p in font_dirs)
        config.write_text(f"<?xml version='1.0'?><fontconfig><include>/etc/fonts/fonts.conf</include>{dirs}</fontconfig>")
        env["FONTCONFIG_FILE"] = str(config)
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
    style_override: Optional[dict] = None,
    crf_override: Optional[int] = None,
) -> Path:
    """Render an MLT project using the plan's selected style and export settings.

    When ``apply_loudnorm`` is set, a second pass runs ``ffmpeg -af loudnorm``
    targeting the LUFS value from the style preset (defaults to -14).
    """
    melt = melt_bin()

    style = style_override or load_style(style_name)
    render_cfg = style.get("render", {})
    crf = crf_override if crf_override is not None else render_cfg.get("crf", 20)
    ab = render_cfg.get("audio_bitrate", "192k")

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    render_target = out
    if apply_loudnorm:
        # write raw melt output to a temp file next to the final path
        render_target = out.with_name(out.stem + ".raw" + out.suffix)

    src_w, src_h, src_fps = _profile_from_mlt(Path(mlt).read_text())
    aspect_divisor = gcd(src_w, src_h)
    display_aspect_num = src_w // aspect_divisor
    display_aspect_den = src_h // aspect_divisor

    cmd = [melt, str(mlt), "-progress"]
    if preview:
        # Use the selected preset's preview scale while preserving the canvas
        # aspect and H.264's even-dimension requirement.
        scale = render_cfg.get("preview_scale", 0.5)
        try:
            scale = float(scale)
        except (TypeError, ValueError):
            scale = 0.5
        scale = min(1.0, max(0.1, scale))
        w = max(2, int(src_w * scale) & ~1)
        h = max(2, int(src_h * scale) & ~1)
        preview_crf = int(render_cfg.get("preview_crf", 22))
        cmd += ["-consumer", f"avformat:{render_target}",
                f"width={w}", f"height={h}",
                f"frame_rate_num={src_fps}", "frame_rate_den=1",
                "sample_aspect_num=1", "sample_aspect_den=1",
                f"display_aspect_num={display_aspect_num}",
                f"display_aspect_den={display_aspect_den}",
                "progressive=1",
                "vcodec=libx264", f"crf={preview_crf}", "preset=veryfast",
                "acodec=aac", f"ab=128k"]
    else:
        cmd += ["-consumer", f"avformat:{render_target}",
                f"width={src_w}", f"height={src_h}",
                f"frame_rate_num={src_fps}", "frame_rate_den=1",
                "sample_aspect_num=1", "sample_aspect_den=1",
                f"display_aspect_num={display_aspect_num}", f"display_aspect_den={display_aspect_den}",
                "progressive=1",
                "vcodec=libx264", f"crf={crf}", f"preset={render_cfg.get('preset', 'medium')}",
                "acodec=aac", f"ab={ab}"]

    font_file = None
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(mlt).getroot()
        font_file = root.findtext("property[@name='ai-render:caption_font_file']")
    except (ET.ParseError, OSError, NameError):
        pass
    rc = _run_and_stream(cmd, _melt_env(style, [Path(font_file)] if font_file else None), on_progress)
    if rc != 0:
        raise RuntimeError(f"melt failed with exit code {rc}")

    if apply_loudnorm:
        try:
            # A silent source can still be edited/rendered normally. Do not
            # turn the optional normalization step into a failure when the
            # output has no audio stream to normalize.
            from .probe import has_audio
            if has_audio(render_target):
                target_lufs = float(render_cfg.get("loudness_lufs", -14))
                loudnorm(render_target, out, target_lufs=target_lufs)
            else:
                os.replace(render_target, out)
        finally:
            render_target.unlink(missing_ok=True)
    return out


def loudnorm(src: Path, dst: Path, target_lufs: float = -14, true_peak: float = -1.5) -> Path:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH")
    dst.parent.mkdir(parents=True, exist_ok=True)
    # MLT/AAC can pad the audio past the last video frame. Keep normalization
    # on the video timeline and undo loudnorm's automatic 192 kHz upsampling.
    from .probe import probe
    video = next((s for s in probe(src).get("streams", []) if s.get("codec_type") == "video"), {})
    video_duration = float(video.get("duration") or 0)
    trim = ["-t", str(video_duration)] if video_duration > 0 else []
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src),
         "-af", f"loudnorm=I={target_lufs}:TP={true_peak}",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", *trim, str(dst)],
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


def export_poster(plan, job_dir: Path, out: Path, base_dir: Optional[Path] = None,
                  style_name: str = "rafiei_reel", style_override: Optional[dict] = None,
                  style_ref: Optional[dict] = None) -> Optional[Path]:
    """Export ``plan.poster`` as a JPEG still with its text burned in.

    Builds a throwaway MLT project where the poster text takes the cover slot
    at ``poster.frame_time`` (same font/style as the cover, shaped by MLT like
    the video captions), then renders that single frame with melt.
    """
    if not plan.poster:
        return None
    from .build_mlt import build
    from .schema import Cover

    t = plan.poster.frame_time
    cover = Cover(text=plan.poster.text, start=t, end=t + 0.5)
    # The video hook must not be painted twice onto the standalone poster.
    poster_plan = plan.model_copy(update={"cover": cover, "poster": None})
    mlt, _ = build(poster_plan, Path(job_dir) / "poster_build", base_dir=base_dir,
                   style_name=style_name, style_override=style_override, style_ref=style_ref)
    _, _, fps = _profile_from_mlt(mlt.read_text())
    frame = int(round(t * fps))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [melt_bin(), str(mlt), f"in={frame}", f"out={frame}", "-consumer",
           f"avformat:{out}", "vcodec=mjpeg", "qscale=2", "an=1"]
    font_file = ET.parse(mlt).getroot().findtext("property[@name='ai-render:caption_font_file']")
    active_style = style_override or load_style(style_name)
    rc = _run_and_stream(cmd, _melt_env(active_style, [Path(font_file)] if font_file else None), None)
    if rc != 0 or not out.exists():
        raise RuntimeError(f"poster export failed (melt exit {rc})")
    return out


def embed_poster(video: Path, poster: Path, *, crf: int = 20, preset: str = "medium") -> Path:
    """Make the poster the MP4's opening frame and attached cover artwork.

    The opening frame makes the paused video show the poster in players that
    ignore MP4 cover artwork. Replacing one frame preserves narration timing.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH")
    from .probe import probe

    video = Path(video)
    poster = Path(poster)
    stream = next((s for s in probe(video).get("streams", [])
                   if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    if not stream:
        raise RuntimeError("rendered video has no video stream")
    width, height = int(stream["width"]), int(stream["height"])
    pending = video.with_name(f".{video.stem}.poster.tmp{video.suffix}")
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", str(video), "-i", str(poster),
            "-filter_complex",
            f"[1:v]scale={width}:{height}:flags=lanczos,setsar=1[cover];"
            "[0:v][cover]overlay=enable='eq(n,0)':eof_action=repeat,format=yuv420p[v]",
            "-map", "[v]", "-map", "0:a?", "-map", "1:v",
            "-map_metadata", "0", "-c:v:0", "libx264", "-crf", str(crf),
            "-preset", preset, "-c:a", "copy", "-c:v:1", "mjpeg",
            "-disposition:v:1", "attached_pic", "-movflags", "+faststart",
            str(pending),
        ], check=True, capture_output=True, text=True)
        os.replace(pending, video)
    finally:
        pending.unlink(missing_ok=True)
    return video

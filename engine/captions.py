"""Captions rendering helpers.

Two output formats are produced:

* **ASS** — the canonical caption file with per-style overrides. Kept for
  editors, external burn-in tools, and reference. It is rendered by MLT via
  ``avfilter.subtitles`` when the local ffmpeg was built with libass.
* **SRT** — a plain text/time file per caption style. MLT's built-in
  ``subtitle`` filter uses these together with per-filter font/colour/size
  properties from the preset. This path does not require libass and is the
  one wired into ``build_mlt`` on machines whose ffmpeg lacks the subtitles
  filter (e.g. the default Homebrew ffmpeg 9.x).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

from .schema import PROJECT_ROOT, Caption, Plan

STYLE_NAMES = ("normal", "emphasis", "cta")


def load_style(name: str = "rafiei_reel") -> dict:
    path = PROJECT_ROOT / "presets" / f"{name}.yaml"
    if not path.exists():
        path = PROJECT_ROOT / "presets" / "rafiei_reel.yaml"
    return yaml.safe_load(path.read_text())


# ---------------------------------------------------------------------------
# ASS output (canonical)
# ---------------------------------------------------------------------------

def ass_colour(hex_colour: str) -> str:
    """Convert ``#RRGGBB`` or ``#RRGGBBAA`` to the ASS ``&HAABBGGRR`` form.

    ASS uses a 32-bit BGR + alpha value where alpha=00 is opaque. A colour
    with no explicit alpha is treated as opaque.
    """
    h = hex_colour.lstrip("#")
    if len(h) not in (6, 8):
        raise ValueError(f"expected #RRGGBB or #RRGGBBAA, got {hex_colour!r}")
    r, g, b = h[0:2], h[2:4], h[4:6]
    a = h[6:8] if len(h) == 8 else "00"
    return f"&H{a}{b}{g}{r}".upper()


def mlt_colour(hex_colour: str, opaque_alpha: str = "ff") -> str:
    """Convert ``#RRGGBB`` (or with alpha) to the ``0xRRGGBBAA`` form MLT uses.

    MLT's own subtitle filter colours use RGBA where alpha=ff is opaque
    (opposite of the ASS convention).
    """
    h = hex_colour.lstrip("#")
    if len(h) not in (6, 8):
        raise ValueError(f"expected #RRGGBB or #RRGGBBAA, got {hex_colour!r}")
    r, g, b = h[0:2], h[2:4], h[4:6]
    a = h[6:8] if len(h) == 8 else opaque_alpha
    return f"0x{r}{g}{b}{a}".lower()


def ass_time(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def ass_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def build_ass(plan: Plan, style: dict) -> str:
    W, H = plan.canvas.width, plan.canvas.height
    cap = style.get("captions", {})
    base = cap.get("base", {})
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
             "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
             "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
             "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
             "Alignment, MarginL, MarginR, MarginV, Encoding"]
    for name in STYLE_NAMES:
        s = {**base, **(cap.get("styles", {}).get(name) or {})}
        lines.append(
            f"Style: {name},{s.get('font', 'Arial')},{s.get('size', 78)},"
            f"{ass_colour(s.get('colour', '#FFFFFF'))},&H000000FF,{ass_colour(s.get('outline_colour', '#000000'))},"
            f"&H80000000,{-1 if s.get('bold', True) else 0},0,0,0,100,100,0,0,1,"
            f"{s.get('outline', 6)},{s.get('shadow', 0)},2,{s.get('margin_sides', 60)},"
            f"{s.get('margin_sides', 60)},{s.get('margin_bottom', 520)},1")
    lines += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for c in plan.captions:
        lines.append(f"Dialogue: 0,{ass_time(c.start)},{ass_time(c.end)},{c.style},,0,0,0,,{ass_text(c.text)}")
    return "\n".join(lines) + "\n"


def write_ass(plan: Plan, style: dict, path: Path) -> Path:
    path.write_text(build_ass(plan, style), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# SRT output (per caption style, consumed by MLT's `subtitle` filter)
# ---------------------------------------------------------------------------

def srt_time(t: float) -> str:
    if t < 0:
        t = 0.0
    ms = int(round(t * 1000))
    return f"{ms // 3_600_000:02d}:{(ms // 60_000) % 60:02d}:{(ms // 1000) % 60:02d},{ms % 1000:03d}"


def _srt_text(text: str) -> str:
    return text.replace("\r", "").strip()


def build_srts(plan: Plan) -> Dict[str, str]:
    """Return {style_name: srt_body} for every style that has cues."""
    buckets: Dict[str, List[Caption]] = {name: [] for name in STYLE_NAMES}
    for c in plan.captions:
        buckets.setdefault(c.style, []).append(c)

    out: Dict[str, str] = {}
    for name, cues in buckets.items():
        if not cues:
            continue
        parts: List[str] = []
        for i, c in enumerate(cues, 1):
            parts.append(f"{i}\n{srt_time(c.start)} --> {srt_time(c.end)}\n{_srt_text(c.text)}\n")
        out[name] = "\n".join(parts)
    return out


def write_srts(plan: Plan, out_dir: Path) -> Dict[str, Path]:
    """Write one captions.<style>.srt per style used; returns {style: path}."""
    paths: Dict[str, Path] = {}
    for name, body in build_srts(plan).items():
        p = out_dir / f"captions.{name}.srt"
        p.write_text(body, encoding="utf-8")
        paths[name] = p
    return paths


def style_geometry(style_cfg: dict, canvas_w: int, canvas_h: int) -> str:
    """MLT subtitle geometry rect ``x/y:WxH:opacity`` in px, centred horizontally,
    bottom-anchored using margin_bottom from the preset.
    """
    margin_sides = int(style_cfg.get("margin_sides", 60))
    margin_bottom = int(style_cfg.get("margin_bottom", 520))
    font_size = int(style_cfg.get("size", 78))
    # Give ~2 lines of headroom.
    h = font_size * 2 + 40
    w = canvas_w - 2 * margin_sides
    y = canvas_h - margin_bottom - h
    return f"{margin_sides}/{y}:{w}x{h}:100"


def fonts_dir(style: dict) -> Path | None:
    d = style.get("captions", {}).get("fonts_dir")
    if not d:
        return None
    p = Path(d) if Path(d).is_absolute() else PROJECT_ROOT / d
    return p if p.is_dir() else None

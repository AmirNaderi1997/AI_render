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

STYLE_NAMES = ("normal", "emphasis", "cta", "cover")


def render_font_family(selected: str) -> str:
    """Translate UI font-file labels to the family names Fontconfig renders.

    The RAY files expose families such as ``Ray ExtraBlack`` rather than the
    filename stem ``RAY-EXTRABLACK`` shown by the font picker.
    """
    normalized = selected.strip().replace("_", "-").upper()
    ray_styles = {
        "RAY": "Ray",
        "RAY-LIGHT": "Ray Light",
        "RAY-MEDIUM": "Ray Medium",
        "RAY-BOLD": "Ray Bold",
        "RAY-EXTRABOLD": "Ray ExtraBold",
        "RAY-BLACK": "Ray Black",
        "RAY-EXTRABLACK": "Ray ExtraBlack",
    }
    return ray_styles.get(normalized, selected)


def load_style(name: str = "rafiei_reel") -> dict:
    preset_dir = (PROJECT_ROOT / "presets").resolve()
    candidate = (preset_dir / f"{name}.yaml").resolve()
    if candidate.parent != preset_dir or Path(name).name != name:
        raise ValueError(f"invalid style preset name: {name!r}")
    path = candidate
    if not path.exists():
        path = preset_dir / "rafiei_reel.yaml"
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


def _has_persian(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in text)


def _plan_is_persian(plan: Plan) -> bool:
    return any(_has_persian(c.text) for c in plan.captions)


def caption_scale(canvas_w: int, canvas_h: int) -> float:
    """Scale preset typography from its reference 1080x1920 reel canvas."""
    return min(canvas_w / 1080.0, canvas_h / 1920.0)


def build_ass(plan: Plan, style: dict) -> str:
    W, H = plan.canvas.width, plan.canvas.height
    scale = caption_scale(W, H)
    cap = style.get("captions", {})
    base = dict(cap.get("base", {}))
    if _plan_is_persian(plan) and "persian_font" in cap:
        base = {**base, "font": cap["persian_font"]}
    from .font_library import family_for_plan
    selected_font = family_for_plan(plan.canvas)
    if selected_font:
        base["font"] = render_font_family(selected_font)
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
             "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
             "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
             "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
             "Alignment, MarginL, MarginR, MarginV, Encoding"]
    all_styles = list(STYLE_NAMES)
    headline_s = cap.get("styles", {}).get("headline") or {}
    has_headline_in_ass = (
        plan.poster is not None
        and plan.poster.show_in_video
        and H > W  # portrait only
        and headline_s.get("enabled", True)
    )
    if has_headline_in_ass:
        all_styles = list(STYLE_NAMES) + ["headline"]

    for name in all_styles:
        if name == "headline":
            s = {**base, **headline_s}
            # Headline defaults: large, italic, dark background box.
            size_default = int(headline_s.get("accent_size", 90))
            bg_default = "#101010CC"
            margin_v_default = int(H * 0.22)  # ≈420 px from bottom at 1920
        else:
            s = {**base, **(cap.get("styles", {}).get(name) or {})}
            size_default = 78
            bg_default = "#00000000"
            margin_v_default = int(s.get("margin_bottom", 520))
        if selected_font:
            s["font"] = render_font_family(selected_font)
        def scaled(key: str, default: int, _s: dict = s) -> int:
            return max(0, int(round(float(_s.get(key, default)) * scale)))
        background = s.get("background_colour", bg_default)
        background_alpha = background.lstrip("#")[6:8] if len(background.lstrip("#")) == 8 else "00"
        border_style = int(s.get("ass_border_style", 3 if background_alpha.upper() != "00" else 1))
        outline_size = scaled("outline", 6)
        if border_style == 3:
            # ASS uses the outline field as padding when BorderStyle is 3.
            outline_size = scaled("box_padding", 10)
        italic_flag = -1 if s.get("italic", name == "headline") else 0
        margin_v = (
            max(0, int(round(margin_v_default * scale)))
            if name == "headline"
            else scaled("margin_bottom", 520)
        )
        lines.append(
            f"Style: {name},{s.get('font', 'Arial')},{max(1, scaled('size', size_default))},"
            f"{ass_colour(s.get('colour', '#FFFFFF'))},&H000000FF,{ass_colour(s.get('outline_colour', '#000000'))},"
            f"{ass_colour(background)},{-1 if s.get('bold', True) else 0},{italic_flag},0,0,100,100,0,0,{border_style},"
            f"{outline_size},{scaled('shadow', 0)},2,{scaled('margin_sides', 60)},"
            f"{scaled('margin_sides', 60)},{margin_v},1")
    lines += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    highlight_colour = cap.get("highlight_colour", "#FFD43B")
    for c in plan.captions:
        text = ass_text(c.text)
        if c.highlighted_word:
            start = c.text.find(c.highlighted_word)
            if start >= 0:
                end = start + len(c.highlighted_word)
                text = (
                    ass_text(c.text[:start])
                    + "{\\c" + ass_colour(highlight_colour) + "\\b1}"
                    + ass_text(c.text[start:end])
                    + "{\\r" + c.style + "}"
                    + ass_text(c.text[end:])
                )
        lines.append(f"Dialogue: 0,{ass_time(c.start)},{ass_time(c.end)},{c.style},,0,0,0,,{text}")
    if plan.cover:
        lines.append(
            f"Dialogue: 1,{ass_time(plan.cover.start)},{ass_time(plan.cover.end)},cover,,0,0,0,,"
            f"{ass_text(plan.cover.text)}"
        )
    if has_headline_in_ass:
        # Persistent hook: spans the full video. Split into white lead + yellow accent
        # using the same midpoint pivot as the SRT headline layers, then reassemble
        # into a single inline-coloured ASS text run on one line.
        hook_words = plan.poster.text.split()
        pivot = max(1, (len(hook_words) + 1) // 2)
        lead = " ".join(hook_words[:pivot])
        tail = " ".join(hook_words[pivot:])
        if tail:
            hook_text = (
                ass_text(lead) + " "
                + "{\\c" + ass_colour(highlight_colour) + "}"
                + ass_text(tail)
                + "{\\r headline}"
            )
        else:
            hook_text = ass_text(plan.poster.text)
        end_t = max(0.001, plan.output_duration - 1.0 / (plan.canvas.fps or 30))
        lines.append(
            f"Dialogue: 2,{ass_time(0)},{ass_time(end_t)},headline,,0,0,0,,{hook_text}"
        )
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
    """Return {style_name: srt_body} for every style that has cues.

    Each cue's end is shortened by 1 frame (1/fps) so back-to-back cues,
    even across different SRT feeds, never paint on the same frame.
    """
    buckets: Dict[str, List[Caption]] = {name: [] for name in STYLE_NAMES}
    for original in plan.captions:
        c = original
        if plan.cover and c.start < plan.cover.end and c.end > plan.cover.start:
            # Keep the caption in plan.json for review/history, but do not
            # paint a second lower sentence while the opening title is active.
            if c.end <= plan.cover.end:
                continue
            c = c.model_copy(update={"start": plan.cover.end})
        buckets.setdefault(c.style, []).append(c)
    if plan.cover:
        buckets["cover"].append(Caption(
            start=plan.cover.start,
            end=plan.cover.end,
            text=plan.cover.text,
            style="cover",
        ))

    frame = 1.0 / float(plan.canvas.fps)
    out: Dict[str, str] = {}
    for name, cues in buckets.items():
        if not cues:
            continue
        parts: List[str] = []
        for i, c in enumerate(cues, 1):
            end = max(c.start + 1e-3, c.end - frame)
            parts.append(f"{i}\n{srt_time(c.start)} --> {srt_time(end)}\n{_srt_text(c.text)}\n")
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
    scale = caption_scale(canvas_w, canvas_h)
    margin_sides = int(round(float(style_cfg.get("margin_sides", 60)) * scale))
    margin_bottom = int(round(float(style_cfg.get("margin_bottom", 520)) * scale))
    font_size = max(1, int(round(float(style_cfg.get("size", 78)) * scale)))
    # Give ~2 lines of headroom.
    h = font_size * 2 + int(round(40 * scale))
    w = canvas_w - 2 * margin_sides
    y = canvas_h - margin_bottom - h
    return f"{margin_sides}/{y}:{w}x{h}:100"


def fonts_dir(style: dict) -> Path | None:
    d = style.get("captions", {}).get("fonts_dir")
    if not d:
        return None
    p = Path(d) if Path(d).is_absolute() else PROJECT_ROOT / d
    return p if p.is_dir() else None

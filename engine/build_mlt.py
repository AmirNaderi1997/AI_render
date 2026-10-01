"""Build project.mlt + captions.ass from a Plan.

Faithful refactor of proof/build_mlt.py. All media paths become absolute in the MLT.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape as esc

from .schema import Plan, PROJECT_ROOT
from .captions import (
    STYLE_NAMES,
    load_style,
    mlt_colour,
    style_geometry,
    write_ass,
    write_srts,
)


def _rect(z: float, W: int, H: int) -> str:
    w, h = W * z, H * z
    return f"{(W - w) / 2:.0f} {(H - h) / 2:.0f} {w:.0f} {h:.0f} 1"


def build(
    plan: Plan,
    out_dir: Path,
    base_dir: Optional[Path] = None,
    style_name: str = "rafiei_reel",
) -> tuple[Path, Path]:
    """Write project.mlt + captions.ass into out_dir. Returns (mlt_path, ass_path)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = Path(base_dir) if base_dir else Path.cwd()

    def resolve(p: str) -> str:
        pp = Path(p)
        return str((pp if pp.is_absolute() else (base / pp)).resolve())

    W, H, FPS = plan.canvas.width, plan.canvas.height, plan.canvas.fps
    f = lambda sec: int(round(sec * FPS))

    style = load_style(style_name)
    punch_frames = int(style.get("zoom", {}).get("punch_frames", 6))
    music_fade = float(style.get("music", {}).get("fade_out", 0.8))

    ass_path = out_dir / "captions.ass"
    write_ass(plan, style, ass_path)
    srt_paths = write_srts(plan, out_dir)

    cap_cfg = style.get("captions", {})
    cap_base = cap_cfg.get("base", {})
    cap_styles = cap_cfg.get("styles", {}) or {}

    x = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<mlt LC_NUMERIC="C" producer="main">',
        f'<profile width="{W}" height="{H}" frame_rate_num="{FPS}" frame_rate_den="1" '
        f'sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="9" '
        f'display_aspect_den="16" progressive="1" colorspace="709"/>',
    ]

    # Filter B-roll to entries whose file actually exists on disk
    valid_broll = [(i, b) for i, b in enumerate(plan.broll)
                   if Path(resolve(b.file)).exists()]

    # --- producers OUTSIDE any playlist (proof gotcha) ---
    x.append(f'<producer id="raw"><property name="resource">{esc(resolve(plan.source))}</property></producer>')
    for i, b in valid_broll:
        x.append(f'<producer id="broll{i}"><property name="resource">{esc(resolve(b.file))}</property></producer>')
    if plan.music:
        x.append(f'<producer id="music"><property name="resource">{esc(resolve(plan.music.file))}</property></producer>')
    for i, s in enumerate(plan.sfx):
        x.append(f'<producer id="sfx{i}"><property name="resource">{esc(resolve(s.file))}</property></producer>')

    # V1: kept segments with per-entry affine zoom
    x.append('<playlist id="v1">')
    total = 0
    for s in plan.segments:
        n = f(s.out) - f(s.in_)
        z_from, z_to = s.zoom.from_, s.zoom.to
        if abs(z_from - z_to) < 1e-6:
            kf = f'0={_rect(z_from, W, H)}'
        else:
            end_kf = min(punch_frames, max(n - 1, 1))
            kf = f'0={_rect(z_from, W, H)};{end_kf}={_rect(z_to, W, H)}'
        x.append(
            f'<entry producer="raw" in="{f(s.in_)}" out="{f(s.out) - 1}">'
            f'<filter mlt_service="affine">'
            f'<property name="transition.rect">{kf}</property>'
            f'<property name="transition.fill">1</property>'
            f'</filter></entry>'
        )
        total += n
    x.append('</playlist>')

    # V2: B-roll track (skip entries whose file doesn't exist)
    x.append('<playlist id="v2">')
    pos = 0
    for i, b in valid_broll:
        at, dur = f(b.at), f(b.duration)
        # clamp so B-roll never extends past the output duration
        dur = min(dur, max(total - at, 0))
        if dur <= 0:
            continue
        if at > pos:
            x.append(f'<blank length="{at - pos}"/>')
        x.append(f'<entry producer="broll{i}" in="{f(b.in_)}" out="{f(b.in_) + dur - 1}"/>')
        pos = at + dur
    x.append('</playlist>')

    # A1: music with ducking + fade-out
    if plan.music:
        m = plan.music
        lv_parts = [f'0={m.volume_db}']
        for d in m.duck:
            lv_parts += [
                f'{f(d.start)}={d.volume_db}',
                f'{max(f(d.end) - 1, 1)}={d.volume_db}',
                f'{f(d.end) + 6}={m.volume_db}',
            ]
        fade_start = max(total / FPS - music_fade, 0.0)
        x.append(
            f'<playlist id="a1"><entry producer="music" in="0" out="{total - 1}">'
            f'<filter mlt_service="volume"><property name="level">{";".join(lv_parts)}</property></filter>'
            f'<filter mlt_service="avfilter.afade">'
            f'<property name="av.type">out</property>'
            f'<property name="av.start_time">{fade_start:.2f}</property>'
            f'<property name="av.duration">{music_fade:.2f}</property>'
            f'</filter></entry></playlist>'
        )
    else:
        x.append('<playlist id="a1"/>')

    # A2: SFX (clamp each entry so it never extends past total frames)
    x.append('<playlist id="a2">')
    pos = 0
    for i, s in enumerate(plan.sfx):
        at = f(s.at)
        remaining = max(total - at, 0)
        if remaining <= 0:
            continue
        if at > pos:
            x.append(f'<blank length="{at - pos}"/>')
        x.append(
            f'<entry producer="sfx{i}" in="0" out="{remaining - 1}">'
            f'<filter mlt_service="volume"><property name="level">{s.volume_db}</property></filter>'
            f'</entry>'
        )
        pos = at + remaining
    x.append('</playlist>')

    # Tractor
    x.append(
        f'<tractor id="main" in="0" out="{total - 1}">'
        '<track producer="v1"/>'
        '<track producer="v2"/>'
        '<track producer="a1" hide="video"/>'
        '<track producer="a2" hide="video"/>'
        '<transition mlt_service="affine">'
        '<property name="a_track">0</property><property name="b_track">1</property>'
        '<property name="always_active">1</property>'
        '</transition>'
    )
    for b in (1, 2, 3):
        x.append(
            f'<transition mlt_service="mix">'
            f'<property name="a_track">0</property><property name="b_track">{b}</property>'
            f'<property name="always_active">1</property><property name="sum">1</property>'
            f'</transition>'
        )
    # Captions: one MLT `subtitle` filter per style used. MLT's built-in filter
    # renders SRT with per-filter font/colour/size properties. This avoids the
    # avfilter.subtitles path, which needs an ffmpeg built with libass.
    for feed_idx, name in enumerate(STYLE_NAMES):
        srt = srt_paths.get(name)
        if srt is None:
            continue
        s = {**cap_base, **(cap_styles.get(name) or {})}
        family = s.get("font", "Arial")
        size = int(s.get("size", 78))
        fg = mlt_colour(s.get("colour", "#FFFFFF"))
        ol = mlt_colour(s.get("outline_colour", "#000000"))
        outline = int(s.get("outline", 6))
        weight = 700 if s.get("bold", True) else 400
        geom = style_geometry(s, W, H)
        x.append(
            f'<filter mlt_service="subtitle">'
            f'<property name="resource">{esc(str(srt.resolve()))}</property>'
            f'<property name="feed">{feed_idx}</property>'
            f'<property name="family">{esc(family)}</property>'
            f'<property name="size">{size}</property>'
            f'<property name="weight">{weight}</property>'
            f'<property name="fgcolour">{fg}</property>'
            f'<property name="olcolour">{ol}</property>'
            f'<property name="bgcolour">0x00000000</property>'
            f'<property name="outline">{outline}</property>'
            f'<property name="halign">center</property>'
            f'<property name="valign">middle</property>'
            f'<property name="geometry">{geom}</property>'
            f'</filter>'
        )
    x.append('</tractor></mlt>')

    mlt_path = out_dir / "project.mlt"
    mlt_path.write_text("\n".join(x) + "\n")
    return mlt_path, ass_path


# Backwards-compat alias
build_mlt = build

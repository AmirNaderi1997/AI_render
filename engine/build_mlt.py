"""Build project.mlt + captions.ass from a Plan.

Faithful refactor of proof/build_mlt.py. All media paths become absolute in the MLT.
"""
from __future__ import annotations
from pathlib import Path
from math import gcd
import logging
import shutil
import subprocess
from typing import Optional
from xml.sax.saxutils import escape as esc

from .schema import BoundaryTransition, Plan, PROJECT_ROOT
from .probe import cover_scale as _compute_cover_scale, probe_duration, video_dimensions
from .effects_v4 import effect_filter_xml_v4 as effect_filter_xml
from .captions import (
    STYLE_NAMES,
    caption_scale,
    load_style,
    mlt_colour,
    render_font_family,
    srt_time,
    style_geometry,
    write_ass,
    write_srts,
)

log = logging.getLogger(__name__)


def _split_cover_title(text: str, min_words: int = 4) -> tuple[str, Optional[str]]:
    """Split a short Persian hook into a setup line and a punch line."""
    words = text.split()
    if len(words) < min_words:
        return text, None
    pivot = (len(words) + 1) // 2
    return " ".join(words[:pivot]), " ".join(words[pivot:])


def _mlt_supports_ass_subtitles() -> bool:
    """Check whether this MLT install has the libass-backed subtitle filter."""
    melt = shutil.which("melt") or shutil.which("melt-7")
    if not melt:
        return False
    try:
        result = subprocess.run(
            [melt, "-query", "filter=avfilter.subtitles"],
            capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "identifier: avfilter.subtitles" in result.stdout


def _rect(z: float, W: int, H: int) -> str:
    w, h = W * z, H * z
    return f"{(W - w) / 2:.0f} {(H - h) / 2:.0f} {w:.0f} {h:.0f} 1"


def _transition_rect(transition: BoundaryTransition, W: int, H: int) -> str:
    """Return qtblend geometry for the incoming clip over the overlap."""
    end = transition.duration_frames - 1
    if transition.type == "crossfade":
        return f"0=0 0 {W} {H} 0;{end}=0 0 {W} {H} 1"
    if transition.type == "zoom":
        # Keep the subject centered while animating only scale. qtblend's
        # opacity ramp also avoids a hard reveal at either end of the overlap.
        first = transition.zoom_scale if transition.zoom_mode == "zoom_out" else 1.0
        last = 1.0 if transition.zoom_mode == "zoom_out" else transition.zoom_scale
        def rect(scale: float, opacity: float) -> str:
            width, height = W * scale, H * scale
            return f"{(W - width) / 2:.1f} {(H - height) / 2:.1f} {width:.1f} {height:.1f} {opacity:.3f}"
        return f"0={rect(first, 0)};{end}={rect(last, 1)}"
    distance = transition.intensity
    starts = {
        "left": (round(W * distance), 0),
        "right": (-round(W * distance), 0),
        "up": (0, round(H * distance)),
        "down": (0, -round(H * distance)),
    }
    x, y = starts[transition.direction]
    return f"0={x} {y} {W} {H} 1;{end}=0 0 {W} {H} 1"


def build(
    plan: Plan,
    out_dir: Path,
    base_dir: Optional[Path] = None,
    style_name: str = "rafiei_reel",
    style_override: Optional[dict] = None,
    style_ref: Optional[dict] = None,
) -> tuple[Path, Path]:
    """Write project.mlt + captions.ass into out_dir. Returns (mlt_path, ass_path)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = Path(base_dir) if base_dir else Path.cwd()

    def resolve(p: str) -> str:
        pp = Path(p)
        return str((pp if pp.is_absolute() else (base / pp)).resolve())

    W, H, FPS = plan.canvas.width, plan.canvas.height, plan.canvas.fps
    typography_scale = caption_scale(W, H)
    f = lambda sec: int(round(sec * FPS))

    def source_range(segment) -> tuple[int, int, int]:
        """Return a frame-stable inclusive source range for one segment.

        Segment duration is the Edit Plan authority.  Rounding ``in`` and
        ``out`` independently can lose a frame when both endpoints sit on the
        same side of a half-frame boundary (for example 0.06..3.48 at 30 fps).
        Anchor at the rounded source in-point and derive the inclusive out-point
        from the independently rounded duration instead.
        """
        source_in = f(segment.in_)
        frames = round(segment.duration * FPS)
        return source_in, source_in + frames - 1, frames

    style = style_override or load_style(style_name)
    punch_frames = int(style.get("zoom", {}).get("punch_frames", 6))
    music_fade = float(style.get("music", {}).get("fade_out", 0.8))

    try:
        src_w, src_h = video_dimensions(Path(resolve(plan.source)))
    except Exception:
        src_w, src_h = W, H
    cs = _compute_cover_scale(src_w, src_h, W, H)

    ass_path = out_dir / "captions.ass"
    write_ass(plan, style, ass_path)
    srt_paths = write_srts(plan, out_dir)

    cover_parts: dict[str, Path] = {}
    cover_style = (style.get("captions", {}).get("styles", {}) or {}).get("cover", {}) or {}
    if plan.cover:
        primary, accent = _split_cover_title(
            plan.cover.text, int(cover_style.get("split_min_words", 4))
        )
        if accent:
            frame = 1.0 / float(plan.canvas.fps)
            end = max(plan.cover.start + 1e-3, plan.cover.end - frame)
            for name, text in (("primary", primary), ("accent", accent)):
                path = out_dir / f"captions.cover_{name}.srt"
                path.write_text(
                    f"1\n{srt_time(plan.cover.start)} --> {srt_time(end)}\n{text}\n",
                    encoding="utf-8",
                )
                cover_parts[name] = path

    # The rated poster hook doubles as an optional, persistent lower-third in
    # portrait videos. Keep its text in a separate feed from spoken captions
    # so normal captions can change without making the hook flicker.
    headline_parts: dict[str, Path] = {}
    headline_style = (style.get("captions", {}).get("styles", {}) or {}).get("headline", {}) or {}
    if (plan.poster and plan.poster.show_in_video and H / W >= 1.6
            and headline_style.get("enabled", True)):
        primary, accent = _split_cover_title(
            plan.poster.text, int(headline_style.get("split_min_words", 4))
        )
        if accent is None:
            accent, primary = primary, None
        end = max(0.001, plan.output_duration - 1.0 / FPS)
        for name, text in (("primary", primary), ("accent", accent)):
            if not text:
                continue
            path = out_dir / f"captions.headline_{name}.srt"
            path.write_text(f"1\n{srt_time(0)} --> {srt_time(end)}\n{text}\n", encoding="utf-8")
            headline_parts[name] = path

    cap_cfg = style.get("captions", {})
    cap_base = dict(cap_cfg.get("base", {}))
    cap_styles = cap_cfg.get("styles", {}) or {}
    # Use Vazirmatn for Persian captions
    from .captions import _plan_is_persian
    if _plan_is_persian(plan) and "persian_font" in cap_cfg:
        cap_base = {**cap_base, "font": cap_cfg["persian_font"]}
    from .font_library import family_for_plan, stage_for_job
    selected_font = family_for_plan(plan.canvas)
    font_asset = stage_for_job(plan.canvas.caption_font_id, out_dir) if plan.canvas.caption_font_id else None
    from .font_library import render_font_path
    selected_font_file = (Path(font_asset["job_path"]) if font_asset
                          else render_font_path(plan.canvas))
    if selected_font:
        cap_base["font"] = render_font_family(selected_font)

    aspect_divisor = gcd(W, H)
    display_aspect_num = W // aspect_divisor
    display_aspect_den = H // aspect_divisor
    x = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<mlt LC_NUMERIC="C" producer="main">',
        f'<profile width="{W}" height="{H}" frame_rate_num="{FPS}" frame_rate_den="1" '
        f'sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="{display_aspect_num}" '
        f'display_aspect_den="{display_aspect_den}" progressive="1" colorspace="709"/>',
    ]
    if style_ref:
        x.extend([
            f'<property name="ai-render:style_id">{esc(style_ref["style_id"])}</property>',
            f'<property name="ai-render:style_version">{int(style_ref["version"])}</property>',
            f'<property name="ai-render:style_name">{esc(style_ref["name"])}</property>',
        ])
    if font_asset:
        x.extend([
            f'<property name="ai-render:caption_font_id">{esc(plan.canvas.caption_font_id)}</property>',
            f'<property name="ai-render:caption_font_family">{esc(font_asset["family"])}</property>',
            f'<property name="ai-render:caption_font_sha256">{esc(font_asset["sha256"])}</property>',
            f'<property name="ai-render:caption_font_file">{esc(str(font_asset["job_path"]))}</property>',
            f'<property name="ai-render:caption_font_relative_path">{esc(font_asset["job_relative_path"])}</property>',
            '<property name="ai-render:captions_ass">captions.ass</property>',
        ])
    elif selected_font_file:
        x.append(
            f'<property name="ai-render:caption_font_file">{esc(str(selected_font_file))}</property>'
        )

    # Filter B-roll to entries whose file actually exists on disk
    valid_broll = [(i, b) for i, b in enumerate(plan.broll)
                   if Path(resolve(b.file)).exists()]

    # --- producers OUTSIDE any playlist (proof gotcha) ---
    # If denoise is enabled, use cleaned audio as a separate producer
    _denoise_audio = None
    if plan.denoise and plan.denoise.get("enabled") and plan.denoise.get("audio_file"):
        _denoise_audio = resolve(plan.denoise["audio_file"])

    x.append(f'<producer id="raw"><property name="resource">{esc(resolve(plan.source))}</property></producer>')
    if _denoise_audio:
        x.append(f'<producer id="speech_clean"><property name="resource">{esc(_denoise_audio)}</property></producer>')
    for i, b in valid_broll:
        x.append(f'<producer id="broll{i}"><property name="resource">{esc(resolve(b.file))}</property></producer>')
    if plan.music:
        x.append(f'<producer id="music"><property name="resource">{esc(resolve(plan.music.file))}</property></producer>')
    for i, s in enumerate(plan.sfx):
        x.append(f'<producer id="sfx{i}"><property name="resource">{esc(resolve(s.file))}</property></producer>')

    # V1: typed effects override legacy per-entry zoom only on selected segments.
    # Legacy plans retain the original one-playlist graph byte-for-byte in
    # timing terms. Plans with explicit boundary transitions use two clip lanes
    # inside a tractor so adjacent clips can overlap without a parallel renderer.
    effects = {effect.segment_id: effect.type for effect in plan.visual_effects}
    # The source producer carries camera audio. Once an approved cleaned speech
    # track is selected, mute that audio on every source clip before mixing the
    # cleaned track, music, and SFX in the main tractor.
    raw_audio_mute = (
        '<filter mlt_service="volume"><property name="level">-60</property></filter>'
        if _denoise_audio else ""
    )
    entries: list[tuple[object, int, int, str]] = []
    transition_by_pair = {
        (transition.from_segment_id, transition.to_segment_id): transition
        for transition in plan.transitions
    }
    starts: list[int] = []
    cursor = 0
    for index, s in enumerate(plan.segments):
        _source_in, _source_out, n = source_range(s)
        starts.append(cursor)
        if s.id in effects:
            filter_xml = effect_filter_xml(effects[s.id], n, W, H, punch_frames,
                                           cover_scale=cs)
        else:
            z_from, z_to = s.zoom.from_ * cs, s.zoom.to * cs
            if abs(z_from - z_to) < 1e-6:
                kf = f'0={_rect(z_from, W, H)}'
            else:
                end_kf = min(punch_frames, max(n - 1, 1))
                kf = f'0={_rect(z_from, W, H)};{end_kf}={_rect(z_to, W, H)}'
            filter_xml = (f'<filter mlt_service="affine">'
                          f'<property name="transition.rect">{kf}</property>'
                          f'<property name="transition.fill">1</property></filter>')
        entries.append((s, cursor, n, filter_xml))
        cursor += n
        if index < len(plan.segments) - 1:
            next_segment = plan.segments[index + 1]
            cursor -= transition_by_pair.get((s.id, next_segment.id), BoundaryTransition(
                from_segment_id=s.id, to_segment_id=next_segment.id
            )).duration_frames
    total = cursor

    if not plan.transitions:
        x.append('<playlist id="v1">')
        for s, _start, _n, filter_xml in entries:
            source_in, source_out, _ = source_range(s)
            x.append(
                f'<entry producer="raw" in="{source_in}" out="{source_out}">'
                f'{raw_audio_mute}{filter_xml}</entry>'
            )
        x.append('</playlist>')
    else:
        for lane in range(2):
            x.append(f'<playlist id="v1{chr(97 + lane)}">')
            lane_cursor = 0
            for index, (s, start, _n, filter_xml) in enumerate(entries):
                if index % 2 != lane:
                    continue
                if start > lane_cursor:
                    x.append(f'<blank length="{start - lane_cursor}"/>')
                source_in, source_out, _ = source_range(s)
                x.append(
                    f'<entry producer="raw" in="{source_in}" out="{source_out}">'
                    f'{raw_audio_mute}{filter_xml}</entry>'
                )
                lane_cursor = start + _n
            x.append('</playlist>')
        x.append(f'<tractor id="v1" in="0" out="{total - 1}">')
        x.append('<track producer="v1a"/><track producer="v1b"/>')
        for index, transition in enumerate(plan.transitions):
            if transition.type == "hard_cut":
                continue
            boundary_index = next(i for i, segment in enumerate(plan.segments[:-1])
                                  if segment.id == transition.from_segment_id)
            incoming_lane = (boundary_index + 1) % 2
            outgoing_lane = boundary_index % 2
            start = starts[boundary_index + 1]
            end = start + transition.duration_frames - 1
            rect = _transition_rect(transition, W, H)
            x.append(
                f'<transition id="boundary_video_{index}" in="{start}" out="{end}" '
                f'mlt_service="qtblend">'
                f'<property name="a_track">{outgoing_lane}</property>'
                f'<property name="b_track">{incoming_lane}</property>'
                f'<property name="rect">{rect}</property>'
                '<property name="distort">1</property>'
                f'<property name="ai-render:type">{transition.type}</property>'
                f'<property name="ai-render:direction">{transition.direction}</property>'
                f'<property name="ai-render:intensity">{transition.intensity}</property>'
                '</transition>'
            )
            x.append(
                f'<transition id="boundary_audio_{index}" in="{start}" out="{end}" '
                f'mlt_service="mix">'
                f'<property name="a_track">{outgoing_lane}</property>'
                f'<property name="b_track">{incoming_lane}</property>'
                '<property name="start">-2</property>'
                '<property name="accepts_blanks">1</property>'
                '</transition>'
            )
        x.append('</tractor>')

    # V2: B-roll track (skip entries whose file doesn't exist)
    x.append('<playlist id="v2">')
    pos = 0
    for i, b in valid_broll:
        at, dur = f(b.at), f(b.duration)
        start = max(at, pos)
        dur = min(dur, max(total - start, 0))
        if dur <= 0:
            continue
        if at > pos:
            x.append(f'<blank length="{at - pos}"/>')
        x.append(f'<entry producer="broll{i}" in="{f(b.in_)}" out="{f(b.in_) + dur - 1}"/>')
        pos = start + dur
    x.append('</playlist>')

    # A1: music with ducking + fade-out
    if plan.music:
        m = plan.music
        music_path = Path(resolve(m.file))
        try:
            music_frames = max(1, round(probe_duration(music_path) * FPS))
        except Exception as exc:
            raise ValueError(f"could not probe music duration for {m.file}: {exc}") from exc

        duck_frames = sorted(
            (max(0, f(d.start)), min(total, f(d.end)), d.volume_db)
            for d in m.duck if f(d.end) > f(d.start)
        )
        # Segment based auto-duck can produce touching/overlapping ranges,
        # especially around transitions. Merge them before keyframe emission so
        # the recovery keyframe of one range cannot override the next duck.
        ramp_frames = max(1, round(0.2 * FPS))
        merged_ducks: list[list[float | int]] = []
        for start, end, level in duck_frames:
            if end <= start:
                continue
            if merged_ducks and start <= int(merged_ducks[-1][1]) + ramp_frames:
                merged_ducks[-1][1] = max(int(merged_ducks[-1][1]), end)
                merged_ducks[-1][2] = min(float(merged_ducks[-1][2]), float(level))
            else:
                merged_ducks.append([start, end, level])

        x.append('<playlist id="a1">')
        cursor_music = 0
        while cursor_music < total:
            piece_frames = min(music_frames, total - cursor_music)
            points: dict[int, float] = {0: float(m.volume_db)}
            for start, end, level in merged_ducks:
                local_start = max(0, int(start) - cursor_music)
                local_end = min(piece_frames, int(end) - cursor_music)
                if local_end <= local_start:
                    continue
                down_frame = max(0, local_start - ramp_frames)
                hold_end = max(local_start, local_end - 1)
                points[down_frame] = float(m.volume_db)
                points[local_start] = float(level)
                points[hold_end] = float(level)
                # A duck that continues into the next loop must stay down on
                # this piece's final frame. Otherwise every loop has a brief
                # full-volume spike underneath speech.
                if local_end < piece_frames:
                    recover_frame = min(piece_frames - 1, local_end + ramp_frames)
                    points[recover_frame] = float(m.volume_db)
            levels = ";".join(f"{frame}={level:g}" for frame, level in sorted(points.items()))
            x.append(
                f'<entry producer="music" in="0" out="{piece_frames - 1}">'
                f'<filter mlt_service="volume"><property name="level">{levels}</property></filter>'
            )
            x.append('</entry>')
            cursor_music += piece_frames
        if music_fade > 0:
            # The fade belongs to the output timeline, not to the final
            # repeated source clip. A clip-local afade can silence that clip
            # completely when its source timestamp starts after the fade.
            fade_duration = min(music_fade, total / FPS)
            fade_start = total / FPS - fade_duration
            x.append(
                '<filter mlt_service="avfilter.afade">'
                '<property name="av.type">out</property>'
                f'<property name="av.start_time">{fade_start:.3f}</property>'
                f'<property name="av.duration">{fade_duration:.3f}</property>'
                '</filter>'
            )
        x.append('</playlist>')
    else:
        x.append('<playlist id="a1"/>')

    # Give every SFX its own track so later and overlapping cues retain their
    # requested output times. A sequential playlist can shift overlaps or let
    # its first long entry consume the rest of the reel.
    sfx_tracks: list[int] = []
    sfx_durations: dict[int, int] = {}
    for i, s in enumerate(plan.sfx):
        audio_path = Path(resolve(s.file))
        try:
            duration_frames = max(1, round(probe_duration(audio_path) * FPS))
        except Exception as exc:
            raise ValueError(f"could not probe SFX duration for {s.file}: {exc}") from exc
        at = f(s.at)
        sfx_durations[i] = duration_frames
        length = min(duration_frames, max(0, total - at))
        playlist_id = f"a2_{i}"
        sfx_tracks.append(i)
        x.append(f'<playlist id="{playlist_id}">')
        if at:
            x.append(f'<blank length="{at}"/>')
        if length:
            x.append(
                f'<entry producer="sfx{i}" in="0" out="{length - 1}">'
                f'<filter mlt_service="volume"><property name="level">{s.volume_db}</property></filter>'
                f'</entry>'
            )
        tail = total - at - length
        if tail > 0:
            x.append(f'<blank length="{tail}"/>')
        x.append('</playlist>')

    # Keep the legacy A2 playlist for Kdenlive's four-track editable project.
    # The render tractor uses the independent tracks above, so this compatibility
    # playlist cannot shift or drop cues in the rendered output.
    x.append('<playlist id="a2">')
    pos = 0
    for i, s in sorted(enumerate(plan.sfx), key=lambda item: item[1].at):
        start = max(f(s.at), pos)
        length = min(sfx_durations[i], max(0, total - start))
        if start > pos:
            x.append(f'<blank length="{start - pos}"/>')
        if length:
            x.append(f'<entry producer="sfx{i}" in="0" out="{length - 1}"/>')
        pos = start + length
    x.append('</playlist>')

    # A0: denoised speech follows the same source cuts as the picture. The
    # cleaned file is extracted from the original source, not pre-edited to
    # the output timeline.
    if _denoise_audio:
        if not plan.transitions:
            x.append('<playlist id="a0">')
            for segment, _start, _n, _filter in entries:
                source_in, source_out, _ = source_range(segment)
                x.append(f'<entry producer="speech_clean" in="{source_in}" out="{source_out}"/>')
            x.append('</playlist>')
        else:
            for lane in range(2):
                x.append(f'<playlist id="a0{chr(97 + lane)}">')
                lane_cursor = 0
                for index, (segment, start, frames, _filter) in enumerate(entries):
                    if index % 2 != lane:
                        continue
                    if start > lane_cursor:
                        x.append(f'<blank length="{start - lane_cursor}"/>')
                    source_in, source_out, _ = source_range(segment)
                    x.append(f'<entry producer="speech_clean" in="{source_in}" out="{source_out}"/>')
                    lane_cursor = start + frames
                x.append('</playlist>')
            x.append(f'<tractor id="a0" in="0" out="{total - 1}">')
            x.append('<track producer="a0a"/><track producer="a0b"/>')
            for index, transition in enumerate(plan.transitions):
                if transition.type == "hard_cut":
                    continue
                boundary_index = next(i for i, segment in enumerate(plan.segments[:-1])
                                      if segment.id == transition.from_segment_id)
                start = starts[boundary_index + 1]
                end = start + transition.duration_frames - 1
                x.append(
                    f'<transition id="clean_audio_{index}" in="{start}" out="{end}" '
                    'mlt_service="mix">'
                    f'<property name="a_track">{boundary_index % 2}</property>'
                    f'<property name="b_track">{(boundary_index + 1) % 2}</property>'
                    '<property name="start">-2</property>'
                    '<property name="accepts_blanks">1</property>'
                    '</transition>'
                )
            x.append('</tractor>')

    # Tractor
    if _denoise_audio:
        x.append(
            f'<tractor id="main" in="0" out="{total - 1}">'
            '<track producer="v1" hide="audio"/>'
            '<track producer="v2" hide="audio"/>'
            '<track producer="a0" hide="video"/>'
            '<track producer="a1" hide="video"/>'
            '<transition mlt_service="affine">'
            '<property name="a_track">0</property><property name="b_track">1</property>'
            '<property name="always_active">1</property>'
            '</transition>'
        )
        # Keep original and B-roll camera audio out of the clean speech mix.
        for b in (2, 3):
            x.append(
                f'<transition mlt_service="mix">'
                f'<property name="a_track">0</property><property name="b_track">{b}</property>'
                f'<property name="always_active">1</property><property name="sum">1</property>'
                f'</transition>'
            )
        for index in sfx_tracks:
            x.append(f'<track producer="a2_{index}" hide="video"/>')
            track_index = 4 + index
            x.append(
                f'<transition mlt_service="mix">'
                f'<property name="a_track">0</property><property name="b_track">{track_index}</property>'
                f'<property name="always_active">1</property><property name="sum">1</property>'
                f'</transition>'
            )
    else:
        x.append(
            f'<tractor id="main" in="0" out="{total - 1}">'
            '<track producer="v1"/>'
            '<track producer="v2" hide="audio"/>'
            '<track producer="a1" hide="video"/>'
            '<transition mlt_service="affine">'
            '<property name="a_track">0</property><property name="b_track">1</property>'
            '<property name="always_active">1</property>'
            '</transition>'
        )
        for b in (1, 2):
            x.append(
                f'<transition mlt_service="mix">'
                f'<property name="a_track">0</property><property name="b_track">{b}</property>'
                f'<property name="always_active">1</property><property name="sum">1</property>'
                f'</transition>'
            )
        for index in sfx_tracks:
            x.append(f'<track producer="a2_{index}" hide="video"/>')
            track_index = 3 + index
            x.append(
                f'<transition mlt_service="mix">'
                f'<property name="a_track">0</property><property name="b_track">{track_index}</property>'
                f'<property name="always_active">1</property><property name="sum">1</property>'
                f'</transition>'
            )
    # Use libass when the plan contains word-level color runs: the built-in
    # MLT subtitle filter only accepts one foreground color for a whole cue.
    # Keep the established SRT path on MLT installs without libass.
    rich_captions = any(c.highlighted_word for c in plan.captions)
    use_ass_captions = rich_captions and _mlt_supports_ass_subtitles()
    if rich_captions and not use_ass_captions:
        log.warning(
            "plan contains highlighted caption words, but this MLT build lacks libass; "
            "export will use the single-colour SRT fallback"
        )
    layers = [
        (i, name, None, srt)
        for i, name in enumerate(STYLE_NAMES)
        if not use_ass_captions and not (name == "cover" and cover_parts)
        for srt in [srt_paths.get(name)]
        if srt is not None
    ]
    if not use_ass_captions and cover_parts:
        layers.extend([
            (len(STYLE_NAMES) - 1, "cover", "primary", cover_parts["primary"]),
            (len(STYLE_NAMES), "cover", "accent", cover_parts["accent"]),
        ])
    for offset, variant in enumerate(("primary", "accent"), len(STYLE_NAMES) + 1):
        if variant in headline_parts:
            layers.append((offset, "headline", f"headline_{variant}", headline_parts[variant]))
    if use_ass_captions:
        font_dir = selected_font_file.parent if selected_font_file else None
        preset_font_dir = style.get("captions", {}).get("fonts_dir")
        if not font_dir and preset_font_dir:
            candidate = Path(preset_font_dir)
            if not candidate.is_absolute():
                candidate = PROJECT_ROOT / candidate
            if candidate.is_dir():
                font_dir = candidate.resolve()
        x.append(
            '<filter mlt_service="avfilter.subtitles">'
            f'<property name="av.filename">{esc(str(ass_path.resolve()))}</property>'
            + (f'<property name="av.fontsdir">{esc(str(font_dir))}</property>'
               if font_dir else "")
            + '</filter>'
        )
    for feed_idx, name, variant, srt in layers:
        s = {**cap_base, **(cap_styles.get(name) or {})}
        if selected_font:
            s["font"] = render_font_family(selected_font)
        family = s.get("font", "Arial")
        font_style = str(s.get("font_style", "normal"))
        size = int(s.get("size", 78))
        fg = mlt_colour(s.get("colour", "#FFFFFF"))
        ol = mlt_colour(s.get("outline_colour", "#000000"))
        outline = int(s.get("outline", 6))
        weight = int(s.get("weight", 700 if s.get("bold", True) else 400))
        if variant == "primary":
            size = max(1, int(round(float(s.get("primary_size", 72)) * typography_scale)))
            if family.startswith("Ray"):
                family, font_style = "Ray ExtraBold", "ExtraBold"
        elif variant == "accent":
            size = max(1, int(round(float(s.get("accent_size", 92)) * typography_scale)))
            fg = mlt_colour(s.get("accent_colour", "#FFD43B"))
            if family.startswith("Ray"):
                family, font_style = "Ray ExtraBlack", "ExtraBlack"
        elif variant in {"headline_primary", "headline_accent"}:
            key = "primary" if variant.endswith("primary") else "accent"
            size = max(1, int(round(float(s.get(f"{key}_size", 68)) * typography_scale)))
            fg = mlt_colour(s.get(f"{key}_colour", "#FFFFFF" if key == "primary" else "#FFD43B"))
            if s.get("italic", True):
                font_style = "Italic"
            if family.startswith("Ray"):
                family, font_style = "Ray ExtraBlack", "ExtraBlack Italic" if s.get("italic", True) else "ExtraBlack"
        else:
            size = max(1, int(round(size * typography_scale)))
        outline = max(0, int(round(outline * typography_scale)))
        if family == "Ray ExtraBlack":
            family, font_style = "Ray", "ExtraBlack"
        elif family == "Ray ExtraBold":
            family, font_style = "Ray", "ExtraBold"
        if variant in {"primary", "accent"}:
            y = round(float(s.get(f"{variant}_y", 180 if variant == "primary" else 285)) * typography_scale)
            h = round(float(s.get(f"{variant}_height", 110 if variant == "primary" else 130)) * typography_scale)
            margin = round(float(s.get("margin_sides", 110)) * typography_scale)
            geom = f"{margin}/{y}:{W - 2 * margin}x{h}:100"
        elif variant in {"headline_primary", "headline_accent"}:
            key = "primary" if variant.endswith("primary") else "accent"
            y = round(float(s.get(f"{key}_y", 1420 if key == "primary" else 1510)) * typography_scale)
            h = round(float(s.get(f"{key}_height", 90)) * typography_scale)
            margin = round(float(s.get("margin_sides", 110)) * typography_scale)
            geom = f"{margin}/{y}:{W - 2 * margin}x{h}:100"
        else:
            geom = style_geometry(s, W, H)
        x.append(
            f'<filter mlt_service="subtitle">'
            f'<property name="resource">{esc(str(srt.resolve()))}</property>'
            f'<property name="feed">{feed_idx}</property>'
            f'<property name="family">{esc(family)}</property>'
            f'<property name="style">{esc(font_style)}</property>'
            f'<property name="size">{size}</property>'
            f'<property name="weight">{weight}</property>'
            f'<property name="fgcolour">{fg}</property>'
            f'<property name="olcolour">{ol}</property>'
            f'<property name="bgcolour">{mlt_colour(s.get("background_colour", "#00000000"))}</property>'
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

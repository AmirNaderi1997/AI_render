"""Proof: edit plan JSON -> MLT XML (+ ASS subtitles). Render with: melt project.mlt

If the local ``melt`` was not built against ffmpeg-with-libass, its
``avfilter.subtitles`` filter is missing and captions do not render. In
that case we fall back to MLT's own ``subtitle`` filter and drive it from
per-style SRT files — the same approach the engine uses.
"""
import json, shutil, subprocess, sys
from xml.sax.saxutils import escape as esc


def _has_avfilter_subtitles() -> bool:
    m = shutil.which("melt")
    if not m:
        return False
    try:
        out = subprocess.run([m, "-query", "filter"], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:
        return False
    return "avfilter.subtitles" in out


def _srt_time(t):
    ms = int(round(max(t, 0.0) * 1000))
    return f"{ms // 3_600_000:02d}:{(ms // 60_000) % 60:02d}:{(ms // 1000) % 60:02d},{ms % 1000:03d}"

plan = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "plan.json"))
W, H, FPS = plan["canvas"]["width"], plan["canvas"]["height"], plan["canvas"]["fps"]
f = lambda sec: int(round(sec * FPS))                      # seconds -> frames

def rect(z):                                               # centred zoom rect for affine
    w, h = W * z, H * z
    return f"{(W - w) / 2:.0f} {(H - h) / 2:.0f} {w:.0f} {h:.0f} 1"

def ass_time(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"

# --- captions -> ASS (rendered by MLT's avfilter.subtitles = libass, same as Kdenlive) ---
styles = {"normal": "&H00FFFFFF", "emphasis": "&H0000D7FF", "cta": "&H0000FF00"}
ass = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "",
       "[V4+ Styles]",
       "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, Bold, BorderStyle, Outline, Alignment, MarginV",
       *[f"Style: {k},DejaVu Sans,78,{c},&H00000000,1,1,6,2,520" for k, c in styles.items()], "",
       "[Events]", "Format: Layer, Start, End, Style, Text"]
ass += [f"Dialogue: 0,{ass_time(c['start'])},{ass_time(c['end'])},{c['style']},{c['text']}"
        for c in plan["captions"]]
open("captions.ass", "w").write("\n".join(ass) + "\n")

x = [f'<?xml version="1.0" encoding="utf-8"?>\n<mlt LC_NUMERIC="C" producer="main">',
     f'<profile width="{W}" height="{H}" frame_rate_num="{FPS}" frame_rate_den="1" '
     f'sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="9" display_aspect_den="16" progressive="1" colorspace="709"/>']
prod = lambda pid, res: x.append(f'<producer id="{pid}"><property name="resource">{esc(res)}</property></producer>')

# V1: kept segments of the raw video, each with its own zoom keyframes
prod("raw", plan["source"])
x.append('<playlist id="v1">')
total = 0
for s in plan["segments"]:
    n = f(s["out"]) - f(s["in"])
    z = s.get("zoom", {"from": 1, "to": 1})
    kf = f'0={rect(z["from"])};{min(6, n - 1)}={rect(z["to"])}'   # 0.2s punch-in
    x.append(f'<entry producer="raw" in="{f(s["in"])}" out="{f(s["out"]) - 1}">'
             f'<filter mlt_service="affine"><property name="transition.rect">{kf}</property>'
             f'<property name="transition.fill">1</property></filter></entry>')
    total += n
x.append('</playlist>')

# V2: B-roll over the speaker
for i, b in enumerate(plan["broll"]):                      # producers must be declared outside playlists
    prod(f"broll{i}", b["file"])
x.append('<playlist id="v2">'); pos = 0
for i, b in enumerate(plan["broll"]):
    if f(b["at"]) > pos: x.append(f'<blank length="{f(b["at"]) - pos}"/>')
    x.append(f'<entry producer="broll{i}" in="{f(b["in"])}" out="{f(b["in"]) + f(b["duration"]) - 1}"/>')
    pos = f(b["at"]) + f(b["duration"])
x.append('</playlist>')

# A1: music with ducking (volume.level keyframes in dB)
m = plan["music"]; prod("music", m["file"])
lv = [f'0={m["volume_db"]}']
for d in m.get("duck", []):
    lv += [f'{f(d["start"])}={d["volume_db"]}', f'{max(f(d["end"]) - 1, 1)}={d["volume_db"]}',
           f'{f(d["end"]) + 6}={m["volume_db"]}']
x.append(f'<playlist id="a1"><entry producer="music" in="0" out="{total - 1}">'
         f'<filter mlt_service="volume"><property name="level">{";".join(lv)}</property></filter>'
         f'<filter mlt_service="avfilter.afade"><property name="av.type">out</property>'
         f'<property name="av.start_time">{total / FPS - 0.8:.2f}</property><property name="av.duration">0.8</property></filter>'
         f'</entry></playlist>')

# A2: SFX
for i, s in enumerate(plan["sfx"]):
    prod(f"sfx{i}", s["file"])
x.append('<playlist id="a2">'); pos = 0
for i, s in enumerate(plan["sfx"]):
    if f(s["at"]) > pos: x.append(f'<blank length="{f(s["at"]) - pos}"/>')
    x.append(f'<entry producer="sfx{i}"><filter mlt_service="volume">'
             f'<property name="level">{s["volume_db"]}</property></filter></entry>')
    pos = f(s["at"]) + 18
x.append('</playlist>')

# Tractor: stack tracks, composite video, mix audio, burn captions
x.append(f'<tractor id="main" in="0" out="{total - 1}">'
         '<track producer="v1"/><track producer="v2"/><track producer="a1" hide="video"/><track producer="a2" hide="video"/>'
         '<transition mlt_service="affine"><property name="a_track">0</property><property name="b_track">1</property>'
         '<property name="always_active">1</property></transition>')
for b in (1, 2, 3):
    x.append(f'<transition mlt_service="mix"><property name="a_track">0</property><property name="b_track">{b}</property>'
             '<property name="always_active">1</property><property name="sum">1</property></transition>')
if _has_avfilter_subtitles():
    x.append('<filter mlt_service="avfilter.subtitles"><property name="av.filename">captions.ass</property></filter>')
else:
    # Fallback: MLT's own `subtitle` filter, one per style, driven by SRTs.
    STYLE_ORDER = ["normal", "emphasis", "cta"]
    STYLE_COLOUR = {"normal": "0xffffffff", "emphasis": "0xffd700ff", "cta": "0x00ff66ff"}
    STYLE_SIZE = {"normal": 78, "emphasis": 92, "cta": 84}
    from pathlib import Path as _P
    from collections import defaultdict as _dd
    buckets = _dd(list)
    for c in plan["captions"]:
        buckets[c["style"]].append(c)
    frame = 1.0 / FPS
    for feed_idx, name in enumerate(STYLE_ORDER):
        cues = buckets.get(name)
        if not cues:
            continue
        body = []
        for i, c in enumerate(cues, 1):
            end = max(c["start"] + 1e-3, c["end"] - frame)
            body.append(f"{i}\n{_srt_time(c['start'])} --> {_srt_time(end)}\n{c['text']}\n")
        srt_path = _P(f"captions.{name}.srt")
        srt_path.write_text("\n".join(body), encoding="utf-8")
        x.append(
            f'<filter mlt_service="subtitle">'
            f'<property name="resource">{esc(str(srt_path.resolve()))}</property>'
            f'<property name="feed">{feed_idx}</property>'
            f'<property name="family">DejaVu Sans</property>'
            f'<property name="size">{STYLE_SIZE[name]}</property>'
            f'<property name="weight">700</property>'
            f'<property name="fgcolour">{STYLE_COLOUR[name]}</property>'
            f'<property name="olcolour">0x000000ff</property>'
            f'<property name="bgcolour">0x00000000</property>'
            f'<property name="outline">6</property>'
            f'<property name="halign">center</property><property name="valign">middle</property>'
            f'<property name="geometry">60/1400:{W - 120}x196:100</property>'
            f'</filter>'
        )
x.append('</tractor></mlt>')
open("project.mlt", "w").write("\n".join(x) + "\n")
print(f"project.mlt written: {total} frames = {total / FPS:.2f}s")
